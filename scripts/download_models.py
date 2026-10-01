"""Download the model weights into models/, at pinned revisions.

Usage: python3 scripts/download_models.py

This is the only step that needs the network. Each file is fetched from
Hugging Face at a pinned commit and checked against its SHA-256. A file that is
already present and verified is skipped, and an interrupted download resumes.
Only the standard library is used, so it runs before the application package
is installed.
"""

import hashlib
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

MODELS = Path(__file__).resolve().parent.parent / "models"
CHUNK = 1 << 20


@dataclass(frozen=True)
class Weights:
    path: str
    repo: str
    revision: str
    sha256: str

    @property
    def url(self) -> str:
        name = Path(self.path).name
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{name}"


WEIGHTS = (
    Weights(
        "qwen3.5-9b/Qwen3.5-9B-Q4_K_M.gguf",
        "unsloth/Qwen3.5-9B-GGUF",
        "3885219b6810b007914f3a7950a8d1b469d598a5",
        "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8",
    ),
    Weights(
        "qwen3.5-4b/Qwen3.5-4B-Q4_K_M.gguf",
        "unsloth/Qwen3.5-4B-GGUF",
        "e87f176479d0855a907a41277aca2f8ee7a09523",
        "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4",
    ),
)


def main() -> None:
    for weights in WEIGHTS:
        target = MODELS / weights.path
        if target.exists() and _sha256(target) == weights.sha256:
            print(f"{weights.path}: present, verified")
            continue
        _download(weights, target)
    print("Done. Nothing else needs the network: keep the offline switches from .env.example set.")


def _download(weights: Weights, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    try:
        _fetch(weights, partial)
    except urllib.error.HTTPError as error:
        # 416: nothing left to fetch, the partial file is whole and only needs verifying.
        if error.code != 416:
            raise
    digest = _sha256(partial)
    if digest != weights.sha256:
        partial.unlink()
        sys.exit(f"{weights.path}: SHA-256 {digest} does not match the pinned {weights.sha256}")
    partial.rename(target)
    print(f"{weights.path}: downloaded, verified")


def _fetch(weights: Weights, partial: Path) -> None:
    """Fetch the file into `partial`, resuming from what is already there."""
    offset = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(weights.url, headers={"Range": f"bytes={offset}-"})
    with urllib.request.urlopen(request) as response:
        if response.status != 206:
            offset = 0
        total = offset + int(response.headers["Content-Length"])
        with partial.open("ab" if offset else "wb") as file:
            done, reported = offset, -1
            while chunk := response.read(CHUNK):
                file.write(chunk)
                done += len(chunk)
                percent = done * 100 // total
                if percent // 10 != reported // 10:
                    print(f"{weights.path}: {percent}% of {total / 2**30:.2f} GiB", flush=True)
                    reported = percent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
