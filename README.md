# travel-claims-agent

A local agent that turns travel-inconvenience insurance clauses (旅遊不便險) from several insurers into a reviewed table of claim conditions, then answers: *would this situation be paid, by which product, and under which clause?*

It runs entirely on one laptop with an 8 GB GPU. No document, prompt, or trace leaves the machine.

**Status:** the design is settled and the public corpus is collected. The code lists the policies in a clause PDF by rules, with no model. It imports a policy as a Product into a draft workbook for review, and checks the reviewed workbook. It judges a flight-delay Scenario against confirmed workbooks. Every model call goes through a local-models port, served on this machine by llama-server. On the real model, importing 享樂遊 twice gives identical extracted fields; the run that records the two example Scenarios' Verdicts follows the reviewer's confirmation of its workbook. The full specification is [issue #1](https://github.com/matthewhoung/travel-claims-agent/issues/1), and the [roadmap](#roadmap) shows what comes next.

---

## The problem

A property and casualty actuary compares the claim conditions of travel-inconvenience products from different insurers and uses the result as input to pricing. Today that means reading each clause document and lining the products up by hand. It is slow, and it is subjective: whether a situation is paid often depends on how the cause of the incident is classified, and two readers can classify it differently.

The actuary's working documents are unpublished drafts. They cannot go to a cloud service or out through any API, so whatever helps has to run locally with no outbound traffic.

[docs/DISCOVERY.md](docs/DISCOVERY.md) records the conversation this came from, what the request turned out to mean, and what is still unconfirmed.

## What it produces

Both examples below were written by hand from the collected documents to show the intended output. The system does not produce them yet.

### 1. Alignment table

One row per parameter, one column per product and wording version. The regulator's reference clauses changed on 2026-04-01, so the same product exists in an old and a new wording.

Flight delay (班機延誤), Cathay Century 享樂遊海外旅行綜合保險, old versus new wording:

| | Old wording | New wording |
|---|---|---|
| Delay measured until | the actual departure or the first replacement flight; the next replacement flight if force majeure (不可抗力) prevented taking the first | the actual departure of the flight or of the first replacement flight |
| Typhoon exclusion | none | excluded if a sea typhoon warning (海上颱風警報) was already issued when the policy was bought |
| Strike exclusion | strike already announced or under way | also excluded if the right to strike was already obtained or a strike period was pre-announced |

Benefit amounts are not in the clauses. They come from each insurer's plan table:

| Insurer | Plan | Flight delay, per 4 hours | Maximum per incident |
|---|---|---|---|
| Shinkong | Easy / B / C | NT$1,000 / 3,000 / 6,000 | NT$2,000 / 6,000 / 12,000 |
| Cathay Century | 安心型, 海外豪華型 | NT$6,000 | NT$12,000 |
| Fubon | PD1 to PD4 | NT$6,000 | NT$12,000 |

### 2. Scenario verdict matrix

A scenario is judged against every product and wording version. Each cell is a verdict (paid, not paid, or undetermined with a reason) plus the clause it rests on.

> 「投保時海上颱風警報已發布。保險期間內，去程班機因颱風延誤 6 小時。」
> *A sea typhoon warning was already in effect when the policy was bought. Within the policy period, the outbound flight was delayed 6 hours by the typhoon.*

| | Old wording | New wording |
|---|---|---|
| Cathay Century 享樂遊 | Paid: delay of 4 hours or more (第三十條) | Not paid: typhoon-warning exclusion (第三十一條 二) |

When the cause is unclear, the system does not pick one:

> 「保險期間內，去程班機原定 10:00 起飛，延誤後航空公司安排了 15:00 出發的第一班替代班機。機場聯外道路封閉，我沒趕上，改搭 20:00 的下一班。」
> *Within the policy period, the outbound flight was due at 10:00. After the delay the airline offered a first replacement flight leaving at 15:00. The road to the airport was closed, I missed it, and took the next one at 20:00.*

| | New wording |
|---|---|
| Cathay Century 享樂遊 | **Undetermined: the cause is ambiguous.** The delay to the first replacement flight is 5 hours, so the threshold is met (第三十條). But not taking the first replacement flight is excluded, unless force majeure (不可抗力) prevented it, and the clauses do not define that term (第三十一條 五). If the road closure counts as force majeure: paid. If not: not paid. |

If one incident triggers more than one condition in the same product, the matrix marks the overlap and says whether an aggregate limit in the clauses already resolves it.

## How it works

```mermaid
flowchart LR
  P[Clause PDFs] --> S["Split into clauses<br/>(rules, no model)"]
  S --> X["Extract conditions<br/>and exclusions<br/>(local LLM)"]
  X --> T[("Condition table<br/>Excel")]
  T --> H{{"A person confirms<br/>and fills in amounts"}}
  H --> A[Alignment table]
  H --> J
  Q([Scenario]) --> F["Extract facts<br/>(local LLM)"]
  F --> J["Judge per product<br/>and wording version"]
  J --> M[Verdict matrix]
```

Three choices shape the design:

- **A person confirms the condition table before anything is answered from it.** The local model extracts. It does not decide. ([ADR 0001](docs/adr/0001-human-confirmed-condition-table.md))
- **Code does the arithmetic.** Thresholds, time windows, delay periods, amounts and limits are computed from the confirmed table. Besides reading the Scenario, the model judges one provision at a time, such as whether the facts fall within a covered event or under a specific exclusion, so the same input gives the same answer.
- **An unclear cause gives a conditional verdict.** The system shows the outcome under each reading and names the clause it turns on. ([ADR 0002](docs/adr/0002-conditional-verdict-when-cause-is-unclear.md))

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) covers the pipeline, the table layout, and how the models share one 8 GB GPU. [CONTEXT.md](CONTEXT.md) defines the vocabulary.

## Evaluation

Expected answers come mainly from third parties, not from the author.

| Source | Items | Wording |
|---|---|---|
| Financial Ombudsman Institution decisions (金融消費評議中心), public and anonymised | about 25 (6 collected so far) | old |
| Non-Life Insurance Association Q&A on the 2026 wording | about 16 of its 35 items: those describing a situation under a judged benefit | new |
| Hand-written threshold cases, cross-checked with a second model | about 20 | both |

| Metric | What it measures |
|---|---|
| Verdict accuracy | is each cell of the matrix right |
| Conditionally correct | against a ruling, one branch of a conditional verdict matches and names the clause the ruling turned on; reported separately |
| Undetermined rate | how often the system declines to judge |
| Citation accuracy | share of expected Clauses the system cites |
| Extraction accuracy | share of extracted fields the reviewer did not have to change |
| Run-to-run consistency | the same document imported twice gives the same extracted fields; the same Scenario run three times gives the same outcome for every Condition |
| Retrieval and rerank on or off | whether they change verdict accuracy |
| 9B versus 4B | what a weaker machine would cost in accuracy |

### Results

*Filled in as runs complete.*

| Model | Verdict acc. | Cond. correct | Undetermined | Citation acc. | Extraction acc. | Consistency | VRAM peak (MB) | Decode tok/s |
|---|---|---|---|---|---|---|---|---|
| Qwen3.5-9B Q4_K_M | | | | | | | | |
| Qwen3.5-4B Q4_K_M | | | | | | | | |

## Scope

**In scope for the proof of concept**

- Three insurers and four Products: Cathay Century 享樂遊 (old and new wording) and 享暢行 (new wording only), Fubon 個人海外旅行不便保險 and Shinkong 個人海外旅行不便綜合保險 (old and new wording each).
- Alignment across all six standard benefits: trip cancellation, flight delay, trip change, baggage delay, baggage loss, and loss of travel documents.
- Scenario judging for flight delay, trip cancellation and trip change, where cause is most contested.

**Out of scope**

- Statistical dependence between events, which needs claims data.
- Parsing insurers' plan tables. Amounts are entered by hand with their source.
- Pausing a question to ask the user for a missing fact. The system reports what is missing and the user asks again.
- Authentication, multiple users, fine-tuning.

## Stack

| Layer | Choice | Pinned |
|---|---|---|
| Inference engine | llama.cpp `llama-server`, router mode | build **b11277**, CUDA 12.8, `sm_89` |
| LLM (primary) | Qwen3.5-9B, GGUF Q4_K_M (unsloth), 8k context | commit and SHA-256 in `scripts/download_models.py`; served by `models.ini` |
| LLM (baseline) | Qwen3.5-4B, GGUF Q4_K_M (unsloth), 8k context | as above |
| Embedder | voyage-4-nano (open weights, Apache-2.0), 1024-d | HF revision in lockfile notes |
| Reranker | bge-reranker-v2-m3 (CPU) | |
| Vector store | Qdrant, embedded (no server, no Docker) | `uv.lock` |
| Orchestration | LangGraph | `uv.lock` |
| Tracing | Arize Phoenix, self-hosted | `uv.lock` |
| Review and export | Excel workbook (.xlsx) | |
| Interface | Minimal web page bound to localhost | |
| PDF text | pdfplumber, read in two-column order | `uv.lock` |
| Python | 3.12 installed by asdf; packages managed by uv | `.tool-versions`, `.python-version`, `uv.lock` |

**Hardware:** RTX 4060 Laptop GPU (8 GB, 7.6 GB free with the Windows desktop running), 16 cores, WSL2 Ubuntu 24.04 with 15 GB RAM.

## Data

The corpus is public: 13 clause documents from 8 Taiwanese insurers, 6 ombudsman decisions, the industry Q&A, and a table of published benefit amounts. [data/SOURCES.md](data/SOURCES.md) lists where each file came from, with checksums.

- **The PDFs are not in the repository.** They are the insurers' documents. The source list is committed so the set can be rebuilt.
- **Public documents stand in for the customer's.** They are handled as if confidential so the architecture reflects the real deployment. Nothing in this repository is private data.
- **One step uses a cloud model, on public data only.** Evaluation items are drafted from public decisions and the public Q&A with a cloud model, then checked by a person against the originals. The customer's documents never leave the local machine and are never in this repository.

## Repository layout

```
travel-claims-agent/
├── README.md
├── CONTEXT.md               # vocabulary: Clause, Condition, Alignment, Overlap, Verdict, ...
├── models.ini               # llama-server presets: Qwen3.5-9B and 4B
├── .env.example             # paths and air-gap switches; copy to .env
├── src/travel_claims/       # the application interface, and the adapter for the local models
├── tests/                   # fixtures/ holds page text captured from the clause PDFs
├── scripts/                 # model download, router, smoke test, real-model run; fixtures
├── results/smoke/           # one result file and router log per smoke-test run
├── results/real-run/        # one result file per step of the run on the real model
├── models/                  # model weights, git-ignored
├── store/                   # Clause store of imported Products, git-ignored
├── workbooks/               # draft and confirmed workbooks, git-ignored
├── docs/
│   ├── ARCHITECTURE.md      # pipeline, table layout, GPU scheduling, decision log
│   ├── DISCOVERY.md         # where the requirements came from
│   └── adr/                 # decisions that are hard to reverse
└── data/
    ├── SOURCES.md           # source URL and checksum for every file
    ├── amounts.csv          # published benefit amounts per plan
    ├── clauses/             # clause PDFs, git-ignored
    └── cases/               # ombudsman decisions and industry Q&A, git-ignored
```

The evaluation runner arrives with the roadmap steps.

## Setup (WSL2)

Keep the project and models on WSL's own filesystem (`~/...`). Reading models across `/mnt/c` is several times slower.

### Inference engine (once per machine)

llama.cpp is a tool, not a project dependency. It lives in `~/tools`, shared by all projects and pinned to a tag.

Prerequisites: the NVIDIA driver on **Windows only** (never install a Linux driver inside WSL), plus the WSL-Ubuntu CUDA toolkit.

```bash
sudo apt install -y build-essential cmake git libcurl4-openssl-dev
# CUDA toolkit from NVIDIA's wsl-ubuntu repo (no driver included)
sudo apt install -y cuda-toolkit-12-8
export PATH=/usr/local/cuda/bin:$PATH

git clone https://github.com/ggml-org/llama.cpp ~/tools/llama.cpp
cd ~/tools/llama.cpp && git checkout b11277
cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89 -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j 6

~/tools/llama.cpp/build/bin/llama-server --list-devices   # expect CUDA0: RTX 4060 Laptop GPU
```

### Local models

The weights (8.4 GB) are downloaded once into `models/`, at pinned commits, and checked by SHA-256. This is the only step that needs the network. The switches in `.env` keep everything after it offline.

```bash
cp .env.example .env                 # paths and air-gap switches
python3 scripts/download_models.py   # Qwen3.5-9B and 4B, Q4_K_M
scripts/serve_models.sh              # router on 127.0.0.1:8080, no model loaded
```

A request picks the model by name, `qwen3.5-9b` or `qwen3.5-4b`, through the OpenAI-compatible API. The router loads it on first use, unloading the other model first:

```bash
curl -s http://127.0.0.1:8080/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model": "qwen3.5-9b", "messages": [{"role": "user", "content": "你好"}]}'
```

### Hardware smoke test

The smoke test settles, by measurement, whether the 9B fits at 8k context. It starts its own router, so stop a running one first.

```bash
python3 scripts/smoke_test.py        # writes results/smoke/<time>.json
```

It loads each model in turn and records VRAM peak, headroom (the least VRAM left free), load time, time to first token and decode speed. It also checks that the router starts with no model loaded, and that asking for the other model, in either direction, unloads the current one before the other loads. It passes when every model leaves at least 300 MiB free and the router checks hold. A failed run still writes its results file, saying what failed. Measured on this laptop ([results/smoke/](results/smoke/)):

| Model, 8k context | VRAM peak | Headroom | Load time | Time to first token, full context | Decode |
|---|---|---|---|---|---|
| Qwen3.5-9B Q4_K_M | 5,690 MiB | 2,266 MiB | 1.9–2.8 s | 4.5 s | 39 tok/s |
| Qwen3.5-4B Q4_K_M | 3,406 MiB | 4,550 MiB | 1.3–1.4 s | 3.0–3.1 s | 61–63 tok/s |

The 9B passes, so it stays the primary model. A full-context prompt is 7,806 tokens. The speeds are for free-text replies with the model's default thinking; the JSON-schema-constrained output the application will use may be slower. The test also passes with no network at all, inside a namespace that has only a loopback interface:

```bash
unshare -rn sh -c 'ip link set lo up && python3 scripts/smoke_test.py'
```

### Python environment

asdf installs the interpreter named in `.tool-versions`, and uv installs the packages pinned in `uv.lock`. uv is set to use that interpreter and never downloads its own.

```bash
asdf install                       # Python 3.12.12
uv sync                            # .venv from uv.lock
uv run pytest                      # needs no GPU and no network
uv run mypy && uv run ruff check
```

Tests read page-text fixtures committed under `tests/fixtures/`. The tests against the full PDFs, including two-column reading order, run only when the PDFs are in `data/clauses/`, and are skipped otherwise.

### Listing the policies in a clause document

```bash
uv run travel-claims list-policies data/clauses/cathay/travel-bundle.new-wording.pdf
```

```
...
6. 國泰產物享樂遊海外旅行綜合保險
   pages 13–19, suggested wording: new
   82 Clauses: 第一條–第八十二條
7. 國泰產物享暢行海外旅行綜合保險
   pages 20–26, suggested wording: new
   83 Clauses: 第一條–第八十三條
...
```

The document can also be page text already extracted from a PDF, with a form feed between pages, as `scripts/capture_fixture.py` or `pdftotext` writes it.

### Importing a Product and confirming its workbook

Import one policy of a document as a Product, naming it and confirming its Wording version. `--policy` is its number in the list above, or `--pages` gives the pages that hold it:

```bash
uv run travel-claims import data/clauses/cathay/travel-bundle.new-wording.pdf \
  --policy 6 --product 享樂遊 --wording new
```

The local models extract the flight-delay Conditions and exclusions, and the general provisions, into a draft workbook, `workbooks/享樂遊.new.xlsx`. Import never overwrites a workbook. All of the policy's Clauses go to the Clause store in `store/`, which later steps cite and judge from. `import` and `judge` reach the models through the router started by `scripts/serve_models.sh`, so start it first; `LLM_MODEL` in `.env` picks the model, `qwen3.5-9b` or `qwen3.5-4b`.

A reviewer checks the workbook in Excel, corrects it, and records who confirmed it and when above the Conditions table. Load then lists every problem at once, such as a missing field, a Clause reference that is not among the stored Clauses, an exclusion that applies to an unknown Condition key, or a missing confirmation record. It also counts how many extracted fields the reviewer changed:

```bash
uv run travel-claims load workbooks/享樂遊.new.xlsx
```

```
2 problems:
Conditions!B1: Confirmed by is missing
Conditions!B2: Confirmed on is missing
32 fields extracted, 0 changed by the reviewer.
```

### Judging a Scenario

Describe a Scenario in free text and give the confirmed workbooks to judge it against, one cell of the Verdict matrix each:

```bash
uv run travel-claims judge --scenario "七月十四日晚上八點從成田返台的班機因颱風取消……" \
  workbooks/享樂遊.new.xlsx
```

```
Facts read from the Scenario:
  Benefits: flight delay
  Incident 1: return flight from 成田國際機場
    scheduled departure 2026-07-14 20:00, cancelled
    replacement departing 2026-07-15 14:00, arranged by the insured at 2026-07-15 09:00, to 桃園 (Taiwan), taken
  Cause: 颱風
  Policy bought: 2026-07-01 12:00
  Policy period: 2026-07-10 00:00 – 2026-07-14 23:59
  In force at purchase: none stated

享樂遊, new wording: paid
  flight delay, incident 1: paid (第三十條)
    a delay of 18 h 0 min: 4 full steps of 4 hours
```

Every workbook is validated as Load does first, and nothing is judged while any has a problem. Code measures the delay period from the stated times by the Wording version's rule and checks the threshold and the policy period; the local models judge the covered event, its requirements, each exclusion and its proviso, one provision at a time. Code derives every outcome from those judgements.

When the outcome cannot be decided, the cell says why: the Scenario lacks a fact (named), the outcome turns on how the Cause is classified, or the Clauses do not settle the situation. For the road-closure Scenario above, each reading is listed:

```
享樂遊, new wording: undetermined, Cause ambiguous
  flight delay, incident 1: undetermined, Cause ambiguous (第三十一條 五)
    turns on how the Cause is classified, under the proviso: 但被保險人因不可抗力因素致無法搭乘航空業者所提供之第一班替代交通工具者，不在此限。
    if the proviso of 第三十一條 五 is read as 不可抗力: paid (第三十條)
      a delay of 5 h 0 min: 1 full step of 4 hours
    if the proviso of 第三十一條 五 is read as 非不可抗力: not paid (第三十一條 五)
      the exclusion applies: 被保險人未搭乘航空業者所提供之第一班替代交通工具。
```

`--export verdicts.xlsx` also writes the Verdict matrix, the facts read and the per-Condition breakdown, with a row per reading, to a new Excel file. Flight delay in the new wording is judged so far.

### Running 享樂遊 end to end on the real model

`scripts/run_hsiang_le_you.py` checks the whole path on the real model, in two steps around the reviewer's confirmation. Each step drives the same commands as above, records the most models the router held at once, and writes `results/real-run/<time>-<step>.json`. Run inside a namespace with only a loopback interface, with `--serve` to start the router in it, to show that nothing needs the network:

```bash
unshare -rn sh -c 'ip link set lo up && .venv/bin/python scripts/run_hsiang_le_you.py import --serve'
# review and confirm workbooks/享樂遊.new.xlsx in Excel, then:
unshare -rn sh -c 'ip link set lo up && .venv/bin/python scripts/run_hsiang_le_you.py judge --serve'
```

`import` imports 享樂遊 into `workbooks/享樂遊.new.xlsx` and again into a scratch directory, and checks that both give identical extracted fields. `judge` loads the confirmed workbook, recording its extracted and changed field counts, then judges each README Scenario three times and checks that every run gives the same outcomes and the README's Verdicts.

The remaining run commands will be documented here as the code lands.

## Roadmap

- [x] Inference engine built (llama.cpp b11277, GPU visible from WSL)
- [x] Local model runtime: router presets, pinned weights, smoke test (the 9B fits at 8k context with 2.2 GB to spare)
- [x] Requirements and design settled; public corpus collected
- [ ] **Step 1:** split clause PDFs into clauses and import three insurers, two wordings each
- [ ] **Step 2:** extract conditions and exclusions to Excel, review them, measure extraction accuracy
- [ ] **Step 3:** produce the alignment table
- [ ] **Step 4:** draft and review the evaluation set
- [ ] **Step 5:** scenario judging and overlap marking
- [ ] **Step 6:** retrieval of general clauses; compare rerank on and off
- [ ] **Step 7:** full evaluation, 9B versus 4B
- [ ] **Step 8:** local web page, airplane-mode demo, add the remaining insurers without code changes, write-up
