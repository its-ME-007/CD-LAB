# EVALUATION — Metrics, Baseline Comparison, Test Cases

This is the measurable-evaluation document required by the submission
brief. It covers:

1. The test corpus (`testcases/`)
2. The methodology (`scripts/evaluate.py`)
3. The current results (per-category and aggregate, vs. gcc and Clang
   Static Analyzer)
4. The unit-test suite (`pytest tests/`)

For *why* we designed it this way see [DESIGN.md](DESIGN.md). For *how*
the analyzer works see [IMPLEMENTATION.md](IMPLEMENTATION.md).

---

## 1. Test corpus

25 hand-written Juliet-style cases under [testcases/](../testcases/),
covering all 7 UB categories:

| Category | CWE | Bad cases | Good cases |
| --- | --- | ---: | ---: |
| `null_deref` | CWE-476 | 4 | 2 |
| `uninit` | CWE-457 | 2 | 1 |
| `div_zero` | CWE-369 | 3 | 1 |
| `oob` | CWE-787 / CWE-125 | 2 | 1 |
| `use_after_free` | CWE-416 | 2 | 2 |
| `dangling` | CWE-562 | 2 | 1 |
| `int_overflow` | CWE-190 | 1 | 1 |
| **TOTAL** | | **16** | **9** |

Several cases (notably the `null_deref`, `use_after_free`, and
`dangling` additions) are written in C++ to exercise `nullptr`,
`new`/`delete`, and `delete[]` idioms alongside the C cases.

**Naming convention:** `<label>_<category>_<n>.<ext>` where `label` is
`bad` (UB present, must be detected) or `good` (no UB, must NOT be
flagged). The harness parses these automatically — adding a new case is
just dropping a correctly-named file in `testcases/`.

The Juliet C/C++ Test Suite from NIST SARD was not vendored directly
because it ships at ~3 GB and would dominate the repository. Each case
here mirrors the Juliet "bad / good" pair structure for the same CWEs
Juliet covers.

Manifest with CWE mapping: [testcases/index.json](../testcases/index.json).

---

## 2. Methodology

[scripts/evaluate.py](../scripts/evaluate.py) implements the evaluation
loop:

```
for case in testcases/:
    detected_by_cdlab = run_analyzer_in_process(case)
    detected_by_gcc   = run_external("gcc -Wall -Wextra -fanalyzer -fsyntax-only", case)
    detected_by_clang = run_external("clang --analyze", case)
    detected_by_cppcheck = run_external("cppcheck --enable=warning,style", case)
    for tool, detected_set in ...:
        if case.label == "bad" and case.category in detected_set: TP
        elif case.label == "bad" and case.category not in detected_set: FN
        elif case.label == "good" and case.category in detected_set: FP
        elif case.label == "good" and case.category not in detected_set: TN
```

Baseline tools (`gcc`, `clang`, `cppcheck`) are run via `subprocess`.
Their output is matched against a per-category keyword list to decide
"did this tool detect this category?". The keyword list is deliberately
**generous to the baselines** — under-crediting them would be
dishonest.

Definitions:

- **Precision** = TP / (TP + FP)
- **Recall** = TP / (TP + FN)
- **F1** = 2·P·R / (P + R)

CD_LAB runs **in-process** (`from backend.analyzer import …`) — no HTTP
needed. This keeps the harness fast and deterministic. The external
baselines run via `subprocess` because that's how a real reviewer would
invoke them.

Run it:

```bash
./evaluate.sh                  # markdown table
./evaluate.sh --json           # machine-readable
./evaluate.sh --no-baseline    # CD_LAB only, faster
```

---

## 3. Current results

> Captured on a Windows 11 / Python 3.13 / Clang 18.1.8 / GCC 13
> development machine.
> `cppcheck` was not installed and is skipped — install it to enable
> the third baseline.

### Per-category — CD_LAB

| Category | TP | FP | TN | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `dangling` | 2 | 0 | 1 | 0 | 1.00 | 1.00 | 1.00 |
| `div_zero` | 3 | 0 | 1 | 0 | 1.00 | 1.00 | 1.00 |
| `int_overflow` | 1 | 0 | 1 | 0 | 1.00 | 1.00 | 1.00 |
| `null_deref` | 3 | 0 | 2 | 1 | 1.00 | 0.75 | 0.86 |
| `oob` | 2 | 0 | 1 | 0 | 1.00 | 1.00 | 1.00 |
| `uninit` | 2 | 0 | 1 | 0 | 1.00 | 1.00 | 1.00 |
| `use_after_free` | 2 | 0 | 2 | 0 | 1.00 | 1.00 | 1.00 |

### Aggregate — CD_LAB vs. baselines

| Tool | TP | FP | TN | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| **`cdlab`** | **15** | **0** | **9** | **1** | **1.00** | **0.94** | **0.97** |
| `gcc -fanalyzer` | 5 | 0 | 9 | 11 | 1.00 | 0.31 | 0.48 |
| `clang --analyze` | 14 | 0 | 9 | 2 | 1.00 | 0.88 | 0.93 |

### Headlines

- **Precision = 1.00** on every category and overall. Every flag is a
  true positive. Zero false alarms.
- **Recall = 0.94** overall. 15 of 16 "bad" cases caught.
- **F1 = 0.97** edges out the Clang Static Analyzer (0.93) and beats
  `gcc -fanalyzer` by 0.49.
- The single false negative is documented below.

---

## 4. Known false negative

`bad_null_deref_02.c` is the one missed case:

```c
int main(void) {
    int *p;          /* uninitialised pointer (declaration only) */
    p = 0;           /* null assignment — separate statement */
    *p = 1;          /* deref — should flag null_deref */
    return 0;
}
```

CD_LAB recognises the null assignment pattern when it appears in a
`VAR_DECL` initializer (`int *p = NULL;`) but the second-statement
form `p = 0;` after a separate declaration is missed by the current
`_find_null_inits` walk. This is a small fix in
[backend/analyzer/detectors/null_deref.py](../backend/analyzer/detectors/null_deref.py)
— catching the BINARY_OPERATOR `=` with `is_null_constant(rhs)` and
adding it to the null-defs set. Tracked as future work.

`clang --analyze` catches it because its path-sensitive symbolic
execution treats every assignment uniformly. See [DESIGN.md §5d](DESIGN.md)
on why we explicitly didn't build a symbolic engine.

---

## 5. Unit-test suite

A separate axis of evaluation — implementation correctness rather than
end-to-end UB detection:

```
$ pytest tests/
55 passed in 3.07s
```

Breakdown:

| File | Cases | Scope |
| --- | ---: | --- |
| `test_parser.py` | 3 | libclang load, trivial parse, syntax errors |
| `test_cfg.py` | 8 | shape tests for if/else, while, for, do, break, continue |
| `test_dataflow.py` | 10 | reaching-defs kill/union, live-vars dead-store, def/use extraction |
| `test_detectors.py` | 14 | per-detector TP/TN, C++ idioms (nullptr, new/delete, delete[]), reasoning contract |
| `test_llvm_ir.py` | 5 | clang invocation, friendly errors, real end-to-end |
| `test_ir_introspect.py` | 15 | regex parse, dbg-line resolution, evidence tiers, IR line numbers, real end-to-end |
| **TOTAL** | **55** | |

Tests that require the real `clang` CLI auto-skip when it's missing.

---

## 6. Reproducing these numbers

```bash
git clone <this-repo>
cd CD_LAB
./build.sh
cp .env.example .env       # optional: fill CLANG_PATH if clang isn't on PATH
./evaluate.sh > eval-results.md
pytest tests/
```

Expected runtime: ~30 s for `evaluate.sh`, ~2 s for `pytest tests/`.

---

## 7. Limitations

Honest list of what these numbers don't show:

- **25 cases is small.** Each case is hand-written; we know the
  expected outcome by construction. A bigger run against the full
  NIST Juliet C++ corpus would surface more failure modes.
- **Keyword-matching for baselines is imperfect.** `gcc -fanalyzer`
  sometimes emits warnings whose phrasing doesn't include our
  keyword for the relevant category. We err on the side of being
  generous (see [scripts/evaluate.py::BASELINE_KEYWORDS](../scripts/evaluate.py)).
- **No inter-procedural analysis.** Detection is intra-procedural —
  each flag is decided within one function (even when a case defines a
  helper plus `main`). Real-world UB often spans calls.
- **No optimization-sensitive cases.** All testcases compile and
  run identically at every `-O` level; we don't test UB that only
  manifests after `-O2` constant-folding.

These are acknowledged in [DESIGN.md §9](DESIGN.md) as
"what we'd do with another month."

---

## 8. Adding a new test case

1. Pick a category in `testcases/index.json`.
2. Write `bad_<category>_<n>.c` (or `.cpp`) demonstrating the UB.
3. Write `good_<category>_<n>.<ext>` demonstrating the safe form.
4. Re-run `./evaluate.sh` — the harness picks up new files
   automatically.

There is no extra configuration. Filename convention drives everything.
