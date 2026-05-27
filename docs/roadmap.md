# CD_LAB Roadmap — Phases 3–6

Phases 1–2 are complete (FastAPI skeleton + libclang parser + CFG + dataflow
worklists + Cytoscape viewer + 21 passing tests). This document is the
implementation plan for the remaining work.

For a fast scan of *all* phases, see the top-level [README.md](../README.md).
For the detailed spec for the next concrete piece of work, see
[phase3-detectors.md](phase3-detectors.md).

---

## Phase 3 — UB Detectors (Weeks 5–7)

**Goal:** seven detectors emit `Diagnostic` records that flow back through
`POST /api/analyze`. Detectors layer on top of the existing AST + CFG +
reaching-defs / live-vars infrastructure.

| Detector | File | Strategy |
| --- | --- | --- |
| `null_deref` | `backend/analyzer/detectors/null_deref.py` | Track pointer assignments to `NULL`/`nullptr`/`0`; flag deref before reassignment |
| `uninit_var` | `backend/analyzer/detectors/uninit_var.py` | Reaching-defs: deref/use of var with no reaching definition |
| `div_zero` | `backend/analyzer/detectors/div_by_zero.py` | Constant-fold divisor; flag literal `0` or unchecked variable divisor |
| `use_after_free` | `backend/analyzer/detectors/use_after_free.py` | Track `free()` / `delete` call sites; flag use of freed pointer (no reassignment between) |
| `dangling_ptr` | `backend/analyzer/detectors/dangling_ptr.py` | Flag returns / escapes of `&local` |
| `oob_access` | `backend/analyzer/detectors/oob_access.py` | Static array decls + constant index check; flag index ≥ size |
| `int_overflow` | `backend/analyzer/detectors/int_overflow.py` | Detect signed `a+b` / `a*b` without an upstream bounds guard |

**Plumbing:**

1. `detectors/__init__.py` exposes `run_all(tu, cfgs, dataflows) -> list[Diagnostic]`
   — registers each detector and merges their outputs (deduped by `(category, range)`).
2. `routes/analyze.py` orchestrates: `parse_source` → `build_cfgs` → per-function
   `reaching_definitions` + `live_variables` → `run_all`. Each `Diagnostic` already
   carries the `id`, `category`, `severity`, `range`, `message` — `cfg_node_id` is
   set when the detector can pinpoint a specific block (helps the UI highlight in
   the CFG viewer in Phase 5).
3. Tests live in `tests/test_detectors.py`. Each detector ships with at least one
   true-positive sample under `samples/` (already seeded: `null_deref_01.c`,
   `uninit_var_01.c`, `div_zero_01.c`) and one true-negative.

**Definition of done:**
- All 7 detectors implemented and registered.
- `tests/test_detectors.py` passes (≥21 cases, 3 per detector).
- `samples/` covers each category with at least 1 TP and 1 TN.
- Hitting `POST /api/analyze` on a buggy sample returns ≥1 `Diagnostic` in JSON.

See [phase3-detectors.md](phase3-detectors.md) for the per-detector spec
(algorithms, AST patterns, edge cases, and per-detector test snippets).

---

## Phase 4 — LLM Explanation Layer (Weeks 7–8)

**Goal:** click a diagnostic in the UI → lazy fetch human-readable
explanation + concrete fix from Groq.

**New files:**
- `backend/llm/__init__.py`
- `backend/llm/client.py` — `ChatGroq(model="llama-3.3-70b-versatile")`
  initialized from `GROQ_API_KEY`. Adapted from
  [web-code-runner/code_assist/main.py](../../web-code-runner/code_assist/main.py)
  but stripped of the ReAct agent — we use a direct chat completion.
- `backend/llm/prompts.py` — single template per UB category. Inputs:
  `{category, code_snippet (±3 lines around diag), heuristic_message}`. Output
  contract: JSON with `{explanation, fix_suggestion}`.
- `backend/routes/explain.py` — `POST /api/explain` taking
  `{diagnostic: Diagnostic, code: str, context_lines: int}` and returning
  `ExplainResponse`.

**Frontend changes:**
- Clicking a diagnostic in the side panel calls `/api/explain` on demand
  (saves Groq tokens vs. eager generation).
- Explanation + fix render inline under the clicked diagnostic.
- Loading spinner while waiting; error banner if Groq key missing.

**Prompt structure** (concrete):

```
SYSTEM: You are an expert C/C++ static-analysis assistant. The user's
program triggered a heuristic UB detector. Explain why this is UB,
then suggest a minimal concrete fix. Return JSON only:
{"explanation": "...", "fix_suggestion": "..."}.
Keep explanation to 1-2 sentences. Fix suggestion: a code snippet or
1-line instruction.

USER: Category: {category}
Heuristic: {heuristic_message}
Code (lines {start}-{end}):
{snippet}
```

**Definition of done:**
- `/api/explain` returns valid JSON for all 7 categories on the seeded samples.
- Frontend lazy-loads explanations on diagnostic click.
- Missing `GROQ_API_KEY` produces a clear error in the UI (not a 500).

**Reuse note:** the LangChain + Groq scaffolding in
[web-code-runner/code_assist/](../../web-code-runner/code_assist/) can be
copied wholesale. We're swapping the prompt and dropping the agent loop.

---

## Phase 5 — UX Polish (Weeks 8–9)

**Goal:** the demo flow feels seamless. No new analysis logic — purely UI.

**Editor markers:**
- Bind Monaco markers (`monaco.editor.setModelMarkers`) to each diagnostic's
  `range`. `error` → red squiggle, `warning` → yellow, `info` → blue.
- Click a marker → scroll the side panel to that diagnostic.

**Diagnostic side panel:**
- List items already exist in Phase 1 styling. Extend with:
  - Click → scroll editor + select range + open LLM explanation lazily.
  - Severity icon + category badge per entry.

**CFG cross-linking:**
- If `diagnostic.cfg_node_id` is set, clicking the diagnostic also highlights
  that node in the Cytoscape viewer (`cy.$id(nodeId).addClass('highlight')`).
- New `.highlight` style in `cfg.js` style array.

**Sample loader:**
- Dropdown in the editor toolbar listing files in `samples/`.
- Backend route `GET /api/samples` returns `[{name, content}]`.
- Selecting an entry loads it into Monaco.

**Definition of done:**
- Squiggles appear under the correct columns on every detector output.
- Clicking a diagnostic highlights the matching CFG node.
- Sample dropdown loads all 14+ samples (2 per detector).

---

## Phase 6 — Evaluation + Report (Weeks 10–12)

**Goal:** prove the system works on real-world UB samples and write the report.

**Juliet curation:**
- Pull ~30 samples from [NIST Juliet C/C++](https://samate.nist.gov/SARD/test-suites/112)
  covering CWE-476 (null deref), CWE-416 (UAF), CWE-787 (OOB write), CWE-457
  (uninit), CWE-369 (div by zero), CWE-190 (int overflow).
- Each Juliet test case has a "good" and "bad" pair → use both for TP/TN
  measurement.
- Store under `samples/juliet/` and add a manifest `samples/juliet/index.json`
  mapping filename → expected category.

**Comparison harness:**
- `scripts/evaluate.py` (new): walks `samples/juliet/`, hits `/api/analyze`
  for each, compares emitted diagnostics against expected categories.
- Also shells out to `gcc -Wall -Wextra -fanalyzer`, `clang --analyze`,
  `cppcheck` and parses their output.
- Emits a comparison CSV: `sample,expected,our_tool,gcc,clang,cppcheck`.
- Computes per-category precision/recall/F1.

**Target metrics:**
- ≥80% recall on the curated Juliet subset for the 7 supported categories.
- FP rate documented (no hard target — just report it).
- Beat or match `gcc -Wall` on at least 3 of the 7 categories.

**Report deliverables:**
- 8–12 page PDF: motivation, architecture, detector algorithms, evaluation
  table, limitations, future work.
- 10-min demo recording: paste a Juliet sample → analyze → CFG → LLM
  explanation → fix → run gcc/clang/cppcheck side-by-side.

---

## Team split (reminder from the plan)

**Person 1 — Compiler/Backend Lead:**
Phase 3 detectors, Phase 6 evaluation harness, tests.

**Person 2 — Frontend/AI Lead:**
Phase 4 LLM client + prompts + `/api/explain`, Phase 5 UI polish, sample
curation, demo recording.

Phase 3 is the longest stretch — Person 2 can start drafting the LLM prompt
templates in parallel against synthetic `Diagnostic` payloads.
