# CD_LAB — AI-Assisted UB Detection in C/C++

Static analyzer for Undefined Behaviour in C/C++ programs. Built on
**libclang** (AST) + custom **CFG/dataflow** + **LLM explanation layer**.

Compiler Design lab project, 2 contributors.

## Quick start

```powershell
cd d:\CD_LAB
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then edit .env (only GROQ_API_KEY needed for LLM features)
uvicorn backend.main:app --reload --port 8000
```

Open <http://localhost:8000/> and paste a C/C++ snippet.

## libclang on Windows

The `libclang` PyPI package ships a bundled `libclang.dll`, so no system
LLVM install is required for development. If you'd rather use a system
install (e.g. via [LLVM releases](https://github.com/llvm/llvm-project/releases)),
set `LIBCLANG_PATH` in `.env` to the absolute path of `libclang.dll`.

## Layout

```
backend/
  main.py            FastAPI app + static mount
  schemas.py         Pydantic models (Diagnostic, AnalyzeRequest/Response)
  analyzer/
    parser.py        libclang wrapper, AST normalization
    cfg.py           CFG builder (Phase 2)
    dataflow.py      Reaching defs + live vars (Phase 2)
    detectors/       UB detectors (Phase 3)
  llm/               Groq client + prompts (Phase 4)
  routes/            FastAPI routers
static/              Monaco editor UI
samples/             Curated UB test snippets
tests/               pytest suite
```

## Roadmap

| Phase | Weeks | Deliverable | Status |
| ----- | ----- | ----------- | ------ |
| 1 | 1–2 | Skeleton + libclang parser + Monaco UI | ✅ |
| 2 | 3–5 | CFG + reaching-defs + Cytoscape viewer | ✅ |
| 3 | 5–7 | 7 UB detectors | 🔜 next |
| 4 | 7–8 | Groq LLM explanation layer | — |
| 5 | 8–9 | Diagnostics UX polish | — |
| 6 | 10–12 | Juliet evaluation + report | — |

Detailed plans:
- [docs/roadmap.md](docs/roadmap.md) — overview of Phases 3–6
- [docs/phase3-detectors.md](docs/phase3-detectors.md) — per-detector spec
  (AST patterns, algorithms, test snippets) for the next phase
