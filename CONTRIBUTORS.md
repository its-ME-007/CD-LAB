# CONTRIBUTORS

CD_LAB is a 2-person academic project for the **Compiler Design** lab.

| Name | GitHub | Email | Primary areas |
| --- | --- | --- | --- |
| **Anirudh R Kulkarni** | [@its-ME-007](https://github.com/its-ME-007) | anirudh007kulkarni@gmail.com | Backend lead — analyzer (parser, CFG, dataflow), detectors, LLVM IR layer, evaluation harness |
| **Ansuman Rath** | [@Ansuman-rath](https://github.com/Ansuman-rath) | ansumanrath.cs23@rvce.edu.in | Frontend lead — Monaco UI, Cytoscape CFG viewer, diagnostics rendering, LLM explanation flow, sample curation |

---

## How work was split

The contract between the two contributors is the `Diagnostic` Pydantic
model in [backend/schemas.py](backend/schemas.py). Once that was
locked on Day 1, backend and frontend could land in parallel without
stepping on each other.

### Backend (Anirudh)

- [backend/analyzer/](backend/analyzer/) — parser, CFG, dataflow, detectors,
  LLVM IR integration, IR introspection
- [backend/routes/analyze.py](backend/routes/analyze.py),
  [backend/routes/graph.py](backend/routes/graph.py) — orchestration
- [tests/](tests/) — pytest coverage
- [scripts/evaluate.py](scripts/evaluate.py) — baseline-comparison harness
- 46 unit tests + 17 end-to-end evaluation cases

### Frontend (Ansuman)

- [static/](static/) — Monaco editors (source + LLVM IR), Cytoscape CFG
  viewer, diagnostics panel, severity pills, persistence,
  keyboard shortcuts
- [backend/llm/](backend/llm/) + [backend/routes/explain.py](backend/routes/explain.py)
  — Groq client, prompts, `/api/explain` endpoint
- [samples/](samples/) — curated demo snippets loaded from the dropdown
- [demo/](demo/) — screenshot tour and failure-case walkthrough

### Shared

- [README.md](README.md), [docs/DESIGN.md](docs/DESIGN.md),
  [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md), [docs/EVALUATION.md](docs/EVALUATION.md)
- Sprint planning + review

---

## Acknowledgements

- **NIST SARD** — the [Juliet C/C++ Test Suite](https://samate.nist.gov/SARD/test-suites/112)
  inspired our `testcases/` "bad / good" pair structure.
- **LLVM project** — clang 18.1.8 + the `libclang` Python bindings.
- **Groq** — fast Llama 3.3 70B inference for the explanation layer.
- **Microsoft Monaco**, **Cytoscape.js** + **dagre** — frontend
  building blocks.

---

## Reaching out

Open an issue on the repository for bugs or questions. Pull requests
welcome, especially:

- Detector improvements (the path-sensitive null-deref miss
  documented in [EVALUATION.md §4](docs/EVALUATION.md) is the obvious
  starter task)
- Additional Juliet-style test cases
- Inter-procedural extensions to the existing analyses
