# DESIGN — Approach & Alternatives

This document explains **what we chose to build, what we considered, and
why we rejected the alternatives**. For step-by-step internals see
[IMPLEMENTATION.md](IMPLEMENTATION.md). For metrics see [EVALUATION.md](EVALUATION.md).

---

## 1. Problem statement

C and C++ allow programs to express **Undefined Behaviour (UB)** —
operations the standard refuses to constrain. Examples: dereferencing
NULL, dividing by zero, reading uninitialized memory, accessing arrays
out-of-bounds. The compiler is free to assume UB never happens, which
makes UB-laden programs miscompile silently.

We wanted a tool that:

1. **Detects** at least 5 common UB categories without running the
   program.
2. **Explains** each finding in plain English so a learner can act on
   it.
3. **Visualises** the analysis stages — AST, CFG, LLVM IR — so it
   doubles as a compiler-design teaching aid.

Constraints: 2-person team, ~10–12 week academic timeline, Windows
demo machine, must run via a single `./build.sh && ./run.sh`.

---

## 2. The approach we picked

**Two-layer static analysis** with an LLM explanation layer on top:

```
┌─────────────────────────────────────────────┐
│  Source (C / C++)                           │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  libclang  →  AST                           │
│              ↓                              │
│  custom CFG builder (networkx)              │
│              ↓                              │
│  reaching defs + live vars (worklist)       │
│              ↓                              │
│  7 UB detectors  →  Diagnostic              │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  clang -O0 -g -emit-llvm  →  .ll text       │
│              ↓                              │
│  regex IR introspector                      │
│              ↓                              │
│  attaches "LLVM Evidence" + metrics         │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  Groq (Llama 3.3 70B)                       │
│  lazily explains a clicked diagnostic       │
└─────────────────────────────────────────────┘
```

The primary layer **decides** UB. The LLVM layer **evidences** it. The
LLM **explains** it. Each stage is independent — kill any one, the
other two still work.

---

## 3. Detector strategy

| Category | Inputs | Algorithm |
| --- | --- | --- |
| `null_deref` | AST + reaching defs | Track pointer assignments to `NULL`/`nullptr`/`0`. Walk every `*p` or `p->...`; if *every* reaching def for `p` is a null assignment → error, if *some* → warning. |
| `uninit` | reaching defs | For every variable use, look up reaching defs for that var at the use site. Empty set + no initializer in the declaration → error. Filters out parameters / globals. |
| `div_zero` | AST | Walk every `BINARY_OPERATOR /` / `%`. RHS is `INTEGER_LITERAL 0` → error. RHS is a variable with a reaching def of 0 → warning. |
| `oob` | AST | Find `ConstantArray` decls + their sizes. Walk every `ARRAY_SUBSCRIPT_EXPR`. Constant index `≥ size` or `< 0` → error. Variable indices are out of scope. |
| `use_after_free` | AST + CFG | Forward dataflow on a "freed-set" — `free()` / `delete` adds to it, reassignments remove. Any use of a freed pointer before clearing → error. |
| `dangling` | AST | Walk every `RETURN_STMT`. If the expression is `&local` where the referent's storage class is auto → error. Statics and globals are safe. |
| `int_overflow` | AST | Walk `+`, `-`, `*`, `<<`. Both operands literal AND result outside the type range → error. Variable arithmetic without a bounds guard → info (off by default — too noisy). |

We deliberately keep the detectors **syntactic and conservative**. They
are easier to explain, easier to test, and easier to teach in the
viva. Path-sensitive symbolic execution and abstract interpretation
were considered (see §5).

---

## 4. The LLM explanation layer

Diagnostics carry a stable category code + a short heuristic message.
That's enough for an LLM to write a one-paragraph explanation and a
concrete fix.

We use **Groq Llama 3.3 70B** (free tier, ~200 ms latency) via the
official Python SDK. The prompt is a single system message + a user
message containing `category`, the heuristic message, and 7 lines of
source context (`±3` around the diagnostic). Output is parsed as JSON
with `{explanation, fix_suggestion}`.

The explanation is **lazy**. Diagnostics render without explanations;
the user clicks **Explain & Suggest Fix** to spend tokens. This keeps
the page fast and the bill small.

---

## 5. Alternatives considered (and rejected)

### a. Use Clang's own static analyzer
**Why considered:** Clang Static Analyzer is mature and detects the
same CWEs we target.
**Why rejected:** This is a *compiler design* lab. Wrapping someone
else's analyzer doesn't demonstrate compiler skills. We *do* run
Clang as a baseline in [EVALUATION.md](EVALUATION.md) so reviewers
can see we tie its scores.

### b. Build the analyzer on LLVM IR instead of AST
**Why considered:** IR is uniform and language-independent; LLVM
provides per-instruction APIs.
**Why rejected:** IR has lost the type information needed for many UB
categories — pointer types collapse to `ptr`, struct field accesses
become `getelementptr` with integer offsets. AST keeps `int *`,
`MyClass::field`, etc., which makes the detectors easier and the
messages clearer. We use IR for *evidence*, not analysis.

### c. Use a GNN to learn UB patterns
**Why considered:** Trendy. Other lab projects in the space do this.
**Why rejected:** Out of scope for a 2-person 10-week project. ML
adds dataset curation, training, model versioning, and explainability
debt. Classical dataflow is the textbook answer; AI we *do* use is
the explanation layer, where LLMs are well-suited.

### d. Path-sensitive analysis (symbolic execution)
**Why considered:** Catches UB that flow-insensitive detectors miss
(e.g. `if (flag) p = NULL; ... *p`).
**Why rejected:** Implementing a path-sensitive engine well is a
project of its own. We *flag* this as a likely false-negative source
in [EVALUATION.md](EVALUATION.md).

### e. Inter-procedural analysis
**Why considered:** Real UB often spans functions.
**Why rejected:** Same as (d) — large scope. We keep every analysis
intra-procedural (one CFG per function).

### f. Tree-sitter instead of libclang
**Why considered:** Tree-sitter is faster and easier to embed.
**Why rejected:** Tree-sitter is great for syntax, but not for
semantic queries (type information, scope, declarations). libclang
gives us all of that for free.

### g. React + TypeScript frontend
**Why considered:** Polished, type-safe.
**Why rejected:** Vanilla HTML + Monaco gets us the same demo with
zero build step. The 2-person budget went to the analyzer.

### h. Persistent database (Postgres / SQLite)
**Why considered:** Save user analyses, multi-user, history.
**Why rejected:** Single-user demo tool. `localStorage` is enough.

### i. Docker the whole thing
**Why considered:** Reproducibility.
**Why rejected:** Adds friction to the demo. A virtualenv is enough.
Documented Clang install separately.

---

## 6. Design constraints (locked at Day 1)

These were the rails we did not cross:

- **No CFG/dataflow analysis on IR.** IR support is *secondary*.
- **No interactive source↔IR navigation.** Static evidence in the
  diagnostic card, not click-to-jump. Keeps scope honest.
- **No custom LLVM passes.** Would explode the dependency surface
  (matching LLVM dev libs on every machine).
- **No optimisation-level comparison (-O0 vs -O2).** Interesting,
  out of scope.
- **No backend "primary detection" rewrite on LLVM.** AST stays the
  source of truth for UB findings.

---

## 7. Failure-mode design

The tool degrades gracefully when components are missing:

| Missing component | What still works |
| --- | --- |
| Groq API key | Everything except the explanation. Click on the button shows a one-line offline notice. |
| `clang` CLI | Everything except the LLVM IR tab and LLVM Evidence. IR tab shows install hint. |
| libclang (impossible — bundled in `libclang` PyPI package) | n/a |
| Internet (after first load) | Monaco CDN is the only remote dependency. Vendor it under `static/vendor/` if a demo without internet is needed. Cytoscape is already vendored. |
| Syntax error in user code | Parse errors tab populates; analyzer runs on the partial AST. |

This was a deliberate design goal — a viva demo on a flaky network
should still show *something*.

---

## 8. UX design choices

- **Two-pane layout** (editor left, output right) — universal across
  IDEs. We chose this over a tabbed workflow because reviewers can
  see source and diagnostics at the same time.
- **Tabs for output** (Diagnostics / CFG / AST / LLVM IR / Parse
  errors) — quick switching, no scrolling. Active-tab + active
  diagnostic are both persisted to `localStorage`.
- **Ctrl+Enter triggers Analyze** — emacs/VSCode muscle memory.
- **Severity-count pills** in the Diagnostics tab title — at-a-glance
  before clicking.
- **Lazy LLM** — each diagnostic has its own "Explain" button; no
  page-load cost.
- **Color-coded CFG nodes** — entry (green), exit (red), cond
  (yellow diamond), loop_header (cyan), return / break / continue
  (other accents).

See [llvm.md](llvm.md) for the LLVM-specific reasoning.

---

## 9. What we'd do differently with another month

- **Path-sensitive null analysis** to recover the missed false
  negative documented in [EVALUATION.md](EVALUATION.md).
- **Inter-procedural** view to flag dangling pointers returned from
  arbitrary callees (we currently only catch the direct
  `return &local` pattern).
- **Sanitizer integration** — compile + run with `-fsanitize=address`
  and surface dynamic findings alongside the static ones.
- **Juliet-suite import** — current `testcases/` is a hand-crafted
  Juliet-style set. Pulling in the actual NIST Juliet C++ corpus
  would give a much larger evaluation surface.
