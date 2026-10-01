"""Hardware smoke test: does each model fit on this GPU at its preset context size?

Usage: python3 scripts/smoke_test.py [MODEL ...]   (default: qwen3.5-9b qwen3.5-4b)

Starts the model router with the committed presets (scripts/serve_models.sh)
and checks that it starts with no model loaded. Then, for each model in turn,
while VRAM is sampled every 20 ms, it measures:

- load time: the first request to the unloaded model minus the same request warm;
- time to first token and decode speed, on a short prompt and on one that fills
  the context;
- VRAM peak, and headroom: the least VRAM left free while the model is loaded.

A model fits when it loads and leaves at least 300 MiB free. Between models, and
from the last back to the first, it asks for the next model while the current one
is loaded, and checks that the router unloads the current one before it starts
loading the next.

Writes results/smoke/<time>.json, also when something fails, and exits non-zero
unless every model fits and every router check holds. The GPU must have no other
tenant, so the router's port must be free: stop a running router first.

Only the standard library is used, so the test runs before, and apart from, the
application package.
"""

import argparse
import contextlib
import ctypes
import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Self

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "smoke"
MIN_HEADROOM_MIB = 300
SAMPLE_SECONDS = 0.02
SEED = 42
SHORT_TOKENS = 64
LONG_TOKENS = 256
# Room left in the context for the chat template around the prompt.
TEMPLATE_MARGIN = 128
SHORT_PROMPT = "用一句話說明什麼是班機延誤保險。"
CLAUSE = (
    "第{n}條 被保險人於保險期間內，因搭乘之定期航班較預定出發時間延誤四小時以上，"
    "本公司依保險單所載之保險金額，給付旅程延誤保險金。\n"
)
LONG_QUESTION = "以上條文中，給付旅程延誤保險金的延誤時數門檻是幾小時？"
# Router statuses of a model whose instance holds GPU memory. An instance that is
# being stopped stays "loaded" until its process exits.
RESIDENT = {"loading", "loaded", "sleeping"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("models", nargs="*", default=["qwen3.5-9b", "qwen3.5-4b"])
    models: list[str] = parser.parse_args().models

    env = _read_env(ROOT / ".env")
    port = int(env["LLAMA_PORT"])
    if _listening(port):
        sys.exit(
            f"Something already listens on port {port}. Stop it: the smoke test needs the GPU to itself."
        )

    version = _version(env["LLAMA_SERVER"])

    started = datetime.now().astimezone()
    RESULTS.mkdir(parents=True, exist_ok=True)
    stem = RESULTS / started.strftime("%Y-%m-%dT%H%M%S")
    sampler = VramSampler()
    results: dict[str, Any] = {
        "started": started.isoformat(timespec="seconds"),
        "llama_server": version,
        "gpu": sampler.gpu,
        "vram_total_mib": sampler.total_mib,
        "vram_method": "NVML memory used and free (as nvidia-smi reports them), "
        "sampled every 20 ms",
        "requests": "streamed chat; temperature 0, seed 42, fixed output length, "
        "no prompt cache; free text, no JSON schema",
        "min_headroom_mib": MIN_HEADROOM_MIB,
        "started_with_no_model_loaded": None,
        "models": [],
        "switches": [],
    }
    with stem.with_suffix(".log").open("w") as log:
        server = subprocess.Popen(
            [ROOT / "scripts" / "serve_models.sh"],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        router = Router(port, server)
        try:
            _run(router, sampler, models, results)
        except FAILURES as error:
            results["error"] = _describe(error)
        finally:
            router.stop()
            sampler.stop()

    results["passed"] = (
        "error" not in results
        and results["started_with_no_model_loaded"] is True
        and all(model["fits"] for model in results["models"])
        and all(switch["passed"] for switch in results["switches"])
    )
    stem.with_suffix(".json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    _report(results, stem.with_suffix(".json"))
    sys.exit(0 if results["passed"] else 1)


def _run(
    router: "Router", sampler: "VramSampler", models: list[str], results: dict[str, Any]
) -> None:
    """Fill `results` as the run goes, so a failure keeps what was measured before it."""
    router.wait_until_up()
    statuses = router.statuses()
    unknown = [model for model in models if model not in statuses]
    if unknown:
        raise SmokeTestFailure(f"no preset in models.ini for {', '.join(unknown)}")
    results["started_with_no_model_loaded"] = not router.resident()
    for previous, model in zip([None, *models], models):
        if previous is not None and "error" not in results["models"][-1]:
            results["switches"].append(_switch(router, sampler, previous, model))
        results["models"].append(_measure(router, sampler, model))
    if len(models) > 1 and "error" not in results["models"][-1]:
        results["switches"].append(_switch(router, sampler, models[-1], models[0]))


def _switch(router: "Router", sampler: "VramSampler", current: str, model: str) -> dict[str, Any]:
    """Ask for `model` while `current` is loaded: the router must unload `current` first."""
    result: dict[str, Any] = {"from": current, "to": model}
    start = time.monotonic()
    with ResidencyWatch(router) as watch:
        try:
            router.chat(model, SHORT_PROMPT, SHORT_TOKENS)
        except FAILURES as error:
            result["error"] = _describe(error)
    resident = router.resident()
    result |= {
        "most_models_resident": watch.most,
        "resident_after": resident,
        "headroom_mib": sampler.headroom(start, time.monotonic()),
        "passed": "error" not in result and watch.most == 1 and resident == [model],
    }
    return result


def _measure(router: "Router", sampler: "VramSampler", model: str) -> dict[str, Any]:
    router.unload_all()
    idle_used = sampler.latest_used()
    start = time.monotonic()
    result: dict[str, Any] = {"model": model}
    try:
        cold = router.chat(model, SHORT_PROMPT, SHORT_TOKENS)
        warm = router.chat(model, SHORT_PROMPT, SHORT_TOKENS)
        props = router.get(f"/props?model={model}")
        ctx_size = props["default_generation_settings"]["n_ctx"]
        prompt = _long_prompt(router, model, ctx_size - LONG_TOKENS - TEMPLATE_MARGIN)
        full = router.chat(model, prompt, LONG_TOKENS)
        result |= {
            "args": router.status(model).get("args"),
            "ctx_size": ctx_size,
            "load_time_s": round(cold.latency - warm.latency, 2),
            "short_prompt": warm.summary(),
            "full_context": full.summary(),
        }
    except FAILURES as error:
        result |= {"error": _describe(error), "status": _status_or_reason(router, model)}
    end = time.monotonic()
    headroom = sampler.headroom(start, end)
    result |= {
        "vram_idle_used_mib": idle_used,
        "vram_peak_used_mib": sampler.peak_used(start, end),
        "headroom_mib": headroom,
        "fits": "error" not in result and headroom >= MIN_HEADROOM_MIB,
    }
    return result


def _long_prompt(router: "Router", model: str, tokens: int) -> str:
    """A prompt of about `tokens` tokens: numbered Clauses and a question about them."""
    sample = "".join(CLAUSE.format(n=n) for n in range(100, 200))
    per_clause = len(router.tokenize(model, sample)) / 100
    question = len(router.tokenize(model, LONG_QUESTION))
    count = int((tokens - question) / per_clause)
    return "".join(CLAUSE.format(n=n) for n in range(100, 100 + count)) + LONG_QUESTION


class SmokeTestFailure(Exception):
    """The router or a model did not do what the smoke test asked of it."""


# What a model that does not load, an instance that dies mid-request, or a reply
# without the expected fields raises. Anything else is a bug in this script.
FAILURES = (OSError, http.client.HTTPException, ValueError, KeyError, SmokeTestFailure)


def _describe(error: BaseException) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"{error}: {error.read().decode(errors='replace')}"
    return f"{type(error).__name__}: {error}"


def _status_or_reason(router: "Router", model: str) -> Any:
    """The router's status for `model`, or why it could not be read."""
    try:
        return router.status(model)
    except FAILURES as error:
        return _describe(error)


@dataclass(frozen=True)
class Reply:
    latency: float
    ttft: float | None
    timings: dict[str, float]

    def summary(self) -> dict[str, Any]:
        return {
            "prompt_tokens": int(self.timings["prompt_n"]),
            "generated_tokens": int(self.timings["predicted_n"]),
            "ttft_s": None if self.ttft is None else round(self.ttft, 3),
            "prompt_tokens_per_s": round(self.timings["prompt_per_second"], 1),
            "decode_tokens_per_s": round(self.timings["predicted_per_second"], 1),
        }


class Router:
    def __init__(self, port: int, server: subprocess.Popen[bytes]) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self.server = server

    def wait_until_up(self) -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.server.poll() is not None:
                raise SmokeTestFailure(f"the router exited with code {self.server.returncode}")
            try:
                self.get("/models")
                return
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.5)
        raise SmokeTestFailure("the router did not come up within 60 s")

    def stop(self) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(self.server.pid, signal.SIGTERM)
        self.server.wait(timeout=60)

    def get(self, path: str) -> Any:
        with urllib.request.urlopen(self.base + path, timeout=30) as response:
            return json.load(response)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        with urllib.request.urlopen(self._request(path, body), timeout=600) as response:
            return json.load(response)

    def statuses(self) -> dict[str, dict[str, Any]]:
        """Each model's status object from GET /models, by model name."""
        return {entry["id"]: entry["status"] for entry in self.get("/models")["data"]}

    def status(self, model: str) -> dict[str, Any]:
        return self.statuses()[model]

    def resident(self) -> list[str]:
        """The models whose instance holds GPU memory."""
        return sorted(
            name for name, status in self.statuses().items() if status["value"] in RESIDENT
        )

    def unload_all(self) -> None:
        for model in self.resident():
            self.post("/models/unload", {"model": model})
        deadline = time.monotonic() + 60
        while self.resident():
            if time.monotonic() > deadline:
                raise SmokeTestFailure(f"{', '.join(self.resident())} did not unload within 60 s")
            time.sleep(0.2)
        time.sleep(1)  # let freed VRAM show up in the samples

    def tokenize(self, model: str, text: str) -> list[int]:
        tokens: list[int] = self.post("/tokenize", {"model": model, "content": text})["tokens"]
        return tokens

    def chat(self, model: str, prompt: str, max_tokens: int) -> Reply:
        """One streamed chat request that always generates exactly `max_tokens` tokens."""
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "seed": SEED,
            "ignore_eos": True,
            "cache_prompt": False,
            "stream": True,
        }
        sent = time.monotonic()
        ttft: float | None = None
        timings: dict[str, float] = {}
        with urllib.request.urlopen(
            self._request("/v1/chat/completions", body), timeout=600
        ) as response:
            for raw in response:
                line = raw.decode().strip()
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                chunk = json.loads(line.removeprefix("data: "))
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if ttft is None and (delta.get("content") or delta.get("reasoning_content")):
                        ttft = time.monotonic() - sent
                if "error" in chunk:
                    raise SmokeTestFailure(json.dumps(chunk["error"], ensure_ascii=False))
                timings = chunk.get("timings", timings)
        if not timings:
            raise SmokeTestFailure("the reply ended without timings")
        return Reply(time.monotonic() - sent, ttft, timings)

    def _request(self, path: str, body: dict[str, Any]) -> urllib.request.Request:
        return urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )


class ResidencyWatch:
    """Polls the router while in use, keeping the most models resident at once."""

    def __init__(self, router: Router) -> None:
        self.router = router
        self.most = 0
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._poll, daemon=True)

    def __enter__(self) -> Self:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.done.set()
        self.thread.join()

    def _poll(self) -> None:
        while not self.done.is_set():
            with contextlib.suppress(urllib.error.URLError, ConnectionError):
                self.most = max(self.most, len(self.router.resident()))
            self.done.wait(0.05)


class _Memory(ctypes.Structure):
    """NVML's nvmlMemory_v2_t."""

    _fields_ = [
        ("version", ctypes.c_uint),
        ("total", ctypes.c_ulonglong),
        ("reserved", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class VramSampler:
    """Samples whole-GPU VRAM use until stopped.

    It reads NVML, the library nvidia-smi reads, in-process: nvidia-smi buffers
    its output when piped, so its samples arrive late and in bursts.
    """

    def __init__(self) -> None:
        self.nvml = ctypes.CDLL("libnvidia-ml.so.1")
        self._check(self.nvml.nvmlInit_v2())
        self.device = ctypes.c_void_p()
        self._check(self.nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self.device)))
        name = ctypes.create_string_buffer(96)
        self._check(self.nvml.nvmlDeviceGetName(self.device, name, len(name)))
        self.gpu = name.value.decode()
        self.total_mib = _mib(self._memory().total)
        self.samples: list[tuple[float, int, int]] = []
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)
        self.thread.start()
        while not self.samples:
            time.sleep(SAMPLE_SECONDS)

    def _sample(self) -> None:
        while not self.done.is_set():
            memory = self._memory()
            self.samples.append((time.monotonic(), _mib(memory.used), _mib(memory.free)))
            self.done.wait(SAMPLE_SECONDS)

    def _memory(self) -> _Memory:
        memory = _Memory(version=ctypes.sizeof(_Memory) | 2 << 24)
        self._check(self.nvml.nvmlDeviceGetMemoryInfo_v2(self.device, ctypes.byref(memory)))
        return memory

    @staticmethod
    def _check(code: int) -> None:
        if code != 0:
            sys.exit(f"An NVML call failed with code {code}.")

    def latest_used(self) -> int:
        return self.samples[-1][1]

    def peak_used(self, start: float, end: float) -> int:
        return max(used for _, used, _ in self._between(start, end))

    def headroom(self, start: float, end: float) -> int:
        """The least VRAM left free between `start` and `end`."""
        return min(free for _, _, free in self._between(start, end))

    def _between(self, start: float, end: float) -> list[tuple[float, int, int]]:
        window = [sample for sample in self.samples if start <= sample[0] <= end]
        return window or [self.samples[-1]]

    def stop(self) -> None:
        self.done.set()
        self.thread.join()
        self.nvml.nvmlShutdown()


def _mib(size: int) -> int:
    return round(size / 2**20)


def _read_env(path: Path) -> dict[str, str]:
    """The KEY=value lines of `path`, read as the shell's `source` would read these simple ones."""
    if not path.is_file():
        sys.exit("No .env: copy .env.example to .env first.")
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            env[key.strip()] = os.path.expandvars(value.strip().strip("'\""))
    return env


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _version(binary: str) -> str:
    try:
        output = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, check=True
        ).stderr
    except (OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"LLAMA_SERVER in .env does not run: {error}")
    return next(
        (line for line in output.splitlines() if line.startswith("version:")), output.strip()
    )


def _report(results: dict[str, Any], path: Path) -> None:
    if "error" in results:
        print(f"The run stopped: {results['error']}")
    print(f"Router started with no model loaded: {results['started_with_no_model_loaded']}")
    for model in results["models"]:
        print(f"\n{model['model']}: {'fits' if model['fits'] else 'DOES NOT FIT'}")
        if "error" in model:
            print(f"  failed: {model['error']} {model['status']}")
        else:
            short, full = model["short_prompt"], model["full_context"]
            print(f"  context {model['ctx_size']}, load time {model['load_time_s']} s")
            print(
                f"  short prompt: TTFT {short['ttft_s']} s, decode {short['decode_tokens_per_s']} tok/s"
            )
            print(
                f"  full context ({full['prompt_tokens']} prompt tokens): TTFT {full['ttft_s']} s, "
                f"decode {full['decode_tokens_per_s']} tok/s"
            )
        print(
            f"  VRAM idle {model['vram_idle_used_mib']} MiB, peak {model['vram_peak_used_mib']} MiB, "
            f"headroom {model['headroom_mib']} MiB (needs {MIN_HEADROOM_MIB})"
        )
    for switch in results["switches"]:
        print(
            f"\nSwitch {switch['from']} -> {switch['to']}: {'ok' if switch['passed'] else 'FAILED'}, "
            f"at most {switch['most_models_resident']} model resident, "
            f"headroom {switch['headroom_mib']} MiB"
        )
        if "error" in switch:
            print(f"  failed: {switch['error']}")
    print(f"\n{'PASS' if results['passed'] else 'FAIL'}: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
