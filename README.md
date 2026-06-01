# CD_LAB — AI-Assisted UB Detection in C/C++

A static analyzer that detects **Undefined Behaviour** in C/C++ source
code, explains each finding with an LLM, and shows the underlying
control-flow graph and LLVM IR side-by-side.

Compiler Design lab project — 2 contributors.
See [CONTRIBUTORS.md](CONTRIBUTORS.md).

> ![demo placeholder](demo/screenshots/01-overview.png)
>
> *(See [demo/](demo/) for the screenshot tour and failure-case demo.)*

---

## What it does

Paste a C / C++ snippet → click **Analyze** → get:

| Pane | Contents |
| --- | --- |
| **Source** | Monaco editor with red / yellow squiggle markers on UB lines |
| **Diagnostics** | One card per finding: severity, category (`null_deref`, `div_zero`, …), source line, LLVM IR evidence, "Explain & Suggest Fix" button (calls Groq) |
| **CFG** | Cytoscape.js control-flow graph per function (colored by block kind) |
| **AST** | Normalized libclang AST tree |
| **LLVM IR** | Read-only `.ll` output with a module metrics bar (functions / blocks / instructions / memory ops / arithmetic ops) |
| **Parse errors** | Hard errors from libclang |

**Seven detectors** implemented (NIST CWE mapping):

| Category | CWE | Strategy |
| --- | --- | --- |
| `null_deref` | CWE-476 | Reaching-defs of pointer ⇄ NULL/0/nullptr |
| `uninit` | CWE-457 | Use without any reaching definition |
| `div_zero` | CWE-369 | Constant-fold divisor, flag literal 0 |
| `oob` | CWE-787 / CWE-125 | Static array decl + constant-index check |
| `use_after_free` | CWE-416 | Forward dataflow on freed-set |
| `dangling` | CWE-562 | Return of `&local` |
| `int_overflow` | CWE-190 | Literal arithmetic that exceeds the type |

---

## How to run

### Prerequisites

- **Python 3.10+**
- **Clang 18** for the LLVM IR view ([releases](https://github.com/llvm/llvm-project/releases))
  — optional but recommended; without it the LLVM tab shows an install banner
- **Groq API key** ([console.groq.com/keys](https://console.groq.com/keys))
  — optional; without it the "Explain & Suggest Fix" button shows an offline notice

### One-shot build + run

```bash
./build.sh         # creates .venv, installs requirements
cp .env.example .env  # fill in GROQ_API_KEY and (if needed) CLANG_PATH
./run.sh           # starts the app at http://localhost:8000/
```

On Windows PowerShell the `.sh` scripts run via Git Bash. If you don't have
Git Bash:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env  # edit it
uvicorn backend.main:app --reload --port 8000 --app-dir .
```

Open <http://localhost:8000/>, paste code, press **Ctrl+Enter**.

### Run the evaluation harness

```bash
./evaluate.sh                 # markdown table, includes gcc/clang baselines
./evaluate.sh --json          # machine-readable
./evaluate.sh --no-baseline   # CD_LAB only, no external tools
```

See [docs/EVALUATION.md](docs/EVALUATION.md) for the methodology and current scores.

### Run the test suite

```bash
.venv/Scripts/python -m pytest tests/   # 47 tests
```

---

## Repository layout

```
CD_LAB/
├── README.md              <- this file
├── CONTRIBUTORS.md        <- team
│
├── build.sh / run.sh / evaluate.sh   <- entry-point scripts
│
├── backend/               <- FastAPI + analyzer ("src" for the backend)
│   ├── main.py            <- app entry, mounts /static, registers routes
│   ├── schemas.py         <- Pydantic models (Diagnostic, LLVMIR, ...)
│   ├── analyzer/          <- parser, cfg, dataflow, ir_introspect, detectors/
│   ├── llm/               <- Groq client + prompts
│   └── routes/            <- /api/analyze, /api/cfg, /api/explain, /api/samples
│
├── static/                <- vanilla HTML + Monaco + Cytoscape ("src" for the UI)
│
├── tests/                 <- pytest (47 cases, including end-to-end with real clang)
│
├── testcases/             <- 17 Juliet-style cases used by the evaluation harness
├── scripts/evaluate.py    <- the harness itself
│
├── samples/               <- 4 hand-written examples loaded by the UI dropdown
├── demo/                  <- screenshot tour + failure-case walkthrough
├── docs/                  <- DESIGN, IMPLEMENTATION, EVALUATION, llvm deep-dive
│
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Tech stack

- **Backend:** Python 3.13, FastAPI, libclang (AST), networkx (CFG),
  Groq SDK (LLM), clang CLI (LLVM IR)
- **Frontend:** vanilla HTML + JS, Monaco editor (source + IR),
  Cytoscape.js + dagre layout (CFG)
- **Testing:** pytest

No build step on the frontend. Cytoscape is vendored under
`static/vendor/`. Monaco loads from CDN.

---

## Documentation

Read in this order:

1. **[docs/DESIGN.md](docs/DESIGN.md)** — what we built, what we considered, what we rejected
2. **[docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)** — how it works inside, file map, LLVM layer
3. **[docs/EVALUATION.md](docs/EVALUATION.md)** — results, methodology, baseline comparison
4. **[CONTRIBUTORS.md](CONTRIBUTORS.md)** — team

For the LLVM deep-dive see [docs/llvm.md](docs/llvm.md).
