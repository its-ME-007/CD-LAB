# The Role of LLVM in CD_LAB

A reference doc for contributors, viva preparation, and the project
report. For the *full* implementation details see
[IMPLEMENTATION.md](IMPLEMENTATION.md); this file explains what LLVM does in CD_LAB,
why it does only that, and how the pieces fit together.

---

## TL;DR — the viva line

> **The primary UB detection engine operates on AST, CFG, and dataflow
> information. LLVM IR is generated from the source code and used as a
> secondary analysis layer to provide low-level evidence for memory and
> arithmetic operations associated with detected undefined behaviour.**

This split is made explicit *inside the UI itself*: each diagnostic card
shows an **AST Reasoning** block (the decision chain produced by the
AST/CFG/dataflow detector) above a **Compiler Evidence (LLVM IR)** block
(the corresponding IR instructions). The UI labels are deliberately
chosen so that a reviewer can see the layering without reading any docs:
*AST Reasoning* is the cause, *Compiler Evidence* is the effect at the
IR level.

Memorise that sentence. Every LLVM design decision below either
defends it or stays out of its way.

---

## Two-layer architecture

```
            ┌─────────────────────────────────────┐
            │   Source code (C / C++)             │
            └────────────────┬────────────────────┘
                             │
            ┌────────────────┴────────────────────┐
            │           libclang                  │
            │ (Python bindings, AST only)         │
            └────────────────┬────────────────────┘
                             │
   ┌─────────────────────────┴─────────────────────────┐
   │                                                   │
   │  PRIMARY LAYER (where UB is *detected*)           │
   │  ─────────────────────────────────────            │
   │    AST  → CFG → Dataflow → 7 UB detectors         │
   │  ─────────────────────────────────────            │
   │  emits Diagnostic records                         │
   └────────────────┬──────────────────────────────────┘
                    │
                    │  (same source string also handed
                    │   off to a separate clang CLI call)
                    ▼
   ┌──────────────────────────────────────────────────┐
   │                                                  │
   │  SECONDARY LAYER (where UB is *evidenced*)       │
   │  ─────────────────────────────────────           │
   │    clang -O0 -g -emit-llvm → .ll text            │
   │                ↓                                 │
   │    regex IR introspector                         │
   │                ↓                                 │
   │    - per-diagnostic LLVM Evidence snippets       │
   │    - module-level LLVM Metrics                   │
   │  ─────────────────────────────────────           │
   └──────────────────────────────────────────────────┘
```

The two layers run **independently** and meet only at the very end of
the analyze pipeline, where the secondary layer annotates the primary
layer's diagnostics.

---

## What LLVM contributes (in scope)

### 1. IR viewer
A read-only Monaco editor on the **LLVM IR** tab showing the raw `.ll`
text produced by `clang -O0 -g -emit-llvm`. Read-only on purpose — the
viewer is a *demonstration*, not an editor.

### 2. LLVM Evidence per diagnostic
Each `Diagnostic` carries up to **3 IR instruction lines** related to
its category:

| Diagnostic category | IR instructions used as evidence |
| --- | --- |
| `null_deref`, `use_after_free`, `dangling` | `load`, `store` |
| `oob` | `getelementptr`, `load`, `store` |
| `uninit` | `load` |
| `div_zero` | `sdiv`, `udiv` |
| `int_overflow` | `add`, `sub`, `mul`, `shl` |

Resolution happens in two tiers:
1. **Source-line precise** — using `!dbg !N → !DILocation(line: M, …)`
   metadata embedded by `-g`. Most evidence lands here.
2. **Function-level fallback** — when `-g` is absent or a particular
   diagnostic line has no matching `!dbg` ref, return relevant
   instructions from the same function.

### 3. LLVM Metrics bar
A header strip above the IR viewer reporting:
- Functions
- Basic blocks
- Total instructions
- Memory ops (`load + store + getelementptr`)
- Arithmetic ops (`add + sub + mul + sdiv + udiv + shl`)

### 4. Click-to-jump from evidence to the IR viewer
Each evidence row is clickable: clicking it switches to the **LLVM IR**
tab and scrolls the viewer to the exact instruction, flashing a
whole-line highlight. This is the visual completion of the cause→effect
story — the AST Reasoning is the cause, and one click takes you from the
evidence snippet to where that instruction lives in the full module.

Mechanism: every parsed `IRInstruction` carries its 1-based `ir_line`
(its line in the `.ll` text). `evidence_instrs_for` returns the
instructions, and the route attaches their line numbers as
`Diagnostic.llvm_evidence_lines` (aligned 1:1 with `llvm_evidence`). The
frontend reads that array and calls `revealLineInCenter` on the IR Monaco
editor. No new analysis — it reuses the source-line resolution that
already powers the evidence snippets.

---

## What LLVM does NOT contribute (explicitly out of scope)

These were considered and rejected to keep scope honest:

- ❌ **Custom LLVM passes** — out of scope by 2-person-project budget.
- ❌ **LLVM-based CFG / dataflow / pointer analysis** — we already
  have AST-based versions; competing implementations would weaken the
  primary layer's story.
- ❌ **LLVM-based UB detection** — every UB finding originates in the
  AST/CFG/dataflow detectors. The LLVM layer never decides "this is
  UB"; it only ever shows *evidence for* what AST already flagged.
- ❌ **`-O2` vs `-O0` comparison** — interesting but out of scope.
- ❌ **llvmlite or any LLVM Python binding** — adds ~50 MB of
  toolchain coupling we don't need. The IR we parse is `clang -O0`
  output, which is regular enough for stdlib regex.

---

## Implementation choices, and why

### Why regex, not llvmlite?
- IR at `-O0` is highly regular: one instruction per line, predictable
  opcode placement, debug refs always trailing.
- llvmlite would force a matching LLVM version on every machine that
  runs tests.
- The parser we ended up with is ~160 lines and zero deps.

### Why `-O0 -g`, not just `-O0`?
- `-g` embeds `!DILocation` metadata, which is the only mechanism for
  mapping IR instructions back to source lines without parsing
  optimisation-mangled IR.
- Cost: ~10–20% larger `.ll` text. Worth it.

### Why generate IR via a separate CLI call instead of using libclang?
- The libclang Python bindings expose the AST but not the codegen
  backend. To get IR you have to either (a) shell out to `clang -S
  -emit-llvm` or (b) link against libLLVMCore. (a) is one line of
  `subprocess.run`.
- The CLI invocation is also useful in the report: it's the same
  binary professors expect to see in a "compiler design" project.

### Why does IR generation never fail the analyze endpoint?
- IR is a courtesy artefact. If clang is missing, the .env path is
  wrong, or the user pasted code that fails to compile, the AST-based
  analysis is still useful.
- `LLVMIR.ok = False` + a human-readable message in the IR tab; rest
  of the analyze response is unaffected.

---

## File map

| Path | Role |
| --- | --- |
| [backend/analyzer/llvm_ir.py](../backend/analyzer/llvm_ir.py) | Shells out to clang, returns `IRResult(ok, ir, error)`. Honours `$CLANG_PATH`. |
| [backend/analyzer/ir_introspect.py](../backend/analyzer/ir_introspect.py) | Regex IR parser. `parse_ir(text) → ParsedIR`, `evidence_instrs_for(...) → list[IRInstruction]` (carries `ir_line`), `evidence_for(...) → list[str]`. |
| [backend/schemas.py](../backend/schemas.py) | `IRMetrics`, `LLVMIR.metrics`, `Diagnostic.llvm_evidence` + `Diagnostic.llvm_evidence_lines`. |
| [backend/routes/analyze.py](../backend/routes/analyze.py) | Calls generator + introspector, decorates diagnostics, returns `AnalyzeResponse.llvm_ir`. |
| [static/index.html](../static/index.html) | LLVM IR tab + metrics-bar placeholder. |
| [static/app.js](../static/app.js) | `renderLLVMIR(payload)`, `renderLLVMMetrics(m)`, `renderLLVMEvidence(d)`, `jumpToIRLine(line)`. |
| [static/styles.css](../static/styles.css) | `.llvm-metrics-bar`, `.llvm-evidence`, `.evidence-code`. |
| [tests/test_llvm_ir.py](../tests/test_llvm_ir.py) | clang generation tests; auto-skip when clang missing. |
| [tests/test_ir_introspect.py](../tests/test_ir_introspect.py) | Parser/metrics/evidence tests. |
| [.env](../.env) (your local) / [.env.example](../.env.example) | `CLANG_PATH=` if clang isn't on `PATH`. |

---

## End-to-end pipeline (concrete)

For input `int main(){int *p=0; *p=5; return p[0]/0;}`:

1. **AST/CFG/detectors** flag two diagnostics:
   - `null_deref` at line 1 (`*p=5`)
   - `div_zero` at line 1 (`p[0]/0`)
2. **`generate_llvm_ir`** shells out to `clang -O0 -g -emit-llvm` and
   returns the `.ll` text.
3. **`parse_ir`** walks the text:
   - Pass 1 collects `!DILocation` entries into `{metadata_id → line}`.
   - Pass 2 walks instructions, records opcode, function, and resolves
     trailing `, !dbg !N` to a source line.
4. **`evidence_instrs_for`** is called per diagnostic with
   `(function_name, source_line, category)`. The function name is
   recovered from `Diagnostic.cfg_node_id` (which is `"<funcname>#<n>"`).
   Up to 3 relevant instructions are returned; their `.text` goes to
   `Diagnostic.llvm_evidence` and their `.ir_line` to
   `Diagnostic.llvm_evidence_lines` (aligned by index).
5. **`AnalyzeResponse.llvm_ir.metrics`** carries module-level counts.
6. **Frontend** renders:
   - Collapsible `<details class="llvm-evidence">` block under each
     diagnostic, one clickable row per instruction. Clicking a row calls
     `jumpToIRLine` → switches to the IR tab and reveals/flashes that line.
   - `<div class="llvm-metrics-bar">` above the IR viewer.

---

## Failure modes (and the user-visible behaviour)

| Cause | What the user sees |
| --- | --- |
| `clang` not on PATH and `CLANG_PATH` unset | LLVM IR tab shows a one-line install hint; Diagnostics still render without `LLVM Evidence`; Metrics bar hidden. |
| Source code has a syntax error | libclang collects parse errors (Parse errors tab) and we *also* try clang for IR — clang fails, IR tab shows clang's diagnostics. AST + dataflow analysis runs on the partial AST. |
| `-g` produced no `!DILocation` (rare; non-debuggable builtins) | `evidence_for` falls back to function-level: still shows up to 3 relevant instructions from the same function. |
| IR is enormous (large file) | `parse_ir` is O(n) over lines, regex-based; ~10 MB IR parses in well under a second. |

---

## How to extend

### Adding a new instruction kind to evidence
1. Add the opcode to `_MEMORY_KINDS` or `_ARITH_KINDS` in
   [ir_introspect.py](../backend/analyzer/ir_introspect.py).
2. Add it to the relevant set in `CATEGORY_TO_KINDS`.
3. Add a test snippet to
   [tests/test_ir_introspect.py](../tests/test_ir_introspect.py).

### Adding a new UB category (Phase 7+)
1. Extend the `UBCategory` Literal in
   [schemas.py](../backend/schemas.py).
2. Add the new category → kinds mapping in `CATEGORY_TO_KINDS`.
3. Write the AST-side detector under
   [backend/analyzer/detectors/](../backend/analyzer/detectors/).
4. The evidence rendering Just Works once both ends are wired.

### Adding a new metric (e.g., "branch instructions")
1. Add a field to `IRMetrics` (both the dataclass in
   [ir_introspect.py](../backend/analyzer/ir_introspect.py) and the
   Pydantic model in [schemas.py](../backend/schemas.py)).
2. Increment it in the `parse_ir` Pass 2 loop.
3. Add a `cell('Branches', metrics.branches)` row in
   `renderLLVMMetrics` in [app.js](../static/app.js).

---

## What to put in the project report

A suggested structure for the "LLVM" section of the final report:

1. **Why an IR layer at all?** Explain the AST-vs-IR distinction:
   AST sees `*p`, IR sees `store i32 5, ptr %p` — the IR makes the
   actual memory operation explicit. Useful for showing low-level
   evidence of UB.
2. **The pipeline** — reuse the ASCII diagram from this doc.
3. **One concrete example** — paste a 5-line C snippet, its IR, the
   evidence attached to the diagnostic, and the metrics. Best: the
   `int main(){int *p=0; *p=5; return p[0]/0;}` example used above —
   it produces both `store ptr null` and `sdiv i32 %, 0` evidence in
   under 15 lines of IR.
4. **Limitations** — say plainly: no IR-based UB detection, no
   optimisation comparison. This is a *secondary* layer; it evidences
   UB, it never decides it.
5. **Toolchain** — Clang 18.1.8 + the `libclang` PyPI package for
   AST parsing.
