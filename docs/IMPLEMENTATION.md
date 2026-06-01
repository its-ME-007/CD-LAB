# IMPLEMENTATION — Internals, File Map, LLVM Details

This doc explains how CD_LAB is built. For the *what* and *why* see
[DESIGN.md](DESIGN.md). For results see [EVALUATION.md](EVALUATION.md).

---

## 1. End-to-end request flow

A click on **Analyze** triggers a single POST to `/api/analyze`. Inside
the handler:

```
POST /api/analyze
        │
        ▼
parse_source(code, language)
   • libclang -> TranslationUnit
   • normalized AST dict for the UI
   • parse-error list
        │
        ▼
build_cfgs(tu)
   • one FunctionCFGData per defined function
   • networkx.DiGraph with BasicBlock attrs
   • labeled edges: "" / T / F / back / break / continue
        │
        ▼
reaching_definitions(cfg) + live_variables(cfg)
   • classic worklist algorithm
   • Definition(var, block_id, stmt_index, line)
        │
        ▼
run_all(tu, cfgs, rds, lvs)
   • 7 detectors, each detect(tu, cfg, rd, lv) -> list[Diagnostic]
   • dedup by (category, line, column, message)
        │
        ▼
generate_llvm_ir(code, language)
   • shells to `clang -S -emit-llvm -O0 -g`
   • IRResult.ok = False on failure (never raises)
        │
        ▼
parse_ir(ir_text)              ──┐
   • regex parser                │ if IR succeeded
   • IRInstruction records       │
   • IRMetrics counts            │
   • by_function_line index      │
                                 │
evidence_for(parsed, fn, line,   │
             category) per diag  │
   • attaches up to 3 IR lines   │
   • Diagnostic.llvm_evidence  ──┘
        │
        ▼
AnalyzeResponse {
    diagnostics, ast, parse_errors,
    llvm_ir { ok, ir, error, metrics }
}
```

A parallel `POST /api/cfg` returns Cytoscape JSON for the CFG tab.

`POST /api/explain` (lazy, on diagnostic click) sends `{diagnostic,
code, context_lines}` to Groq via the `groq` Python SDK.

---

## 2. File map

### Backend

| Path | Role |
| --- | --- |
| [backend/main.py](backend/main.py) | FastAPI app entry. Mounts `/static`, registers routes, exposes `/health`. |
| [backend/schemas.py](backend/schemas.py) | All Pydantic models: `Diagnostic`, `AnalyzeRequest`, `AnalyzeResponse`, `LLVMIR`, `IRMetrics`, `ExplainRequest`, `ExplainResponse`, CFG schemas. |
| [backend/analyzer/parser.py](backend/analyzer/parser.py) | libclang wrapper. `parse_source(code, language)` writes to a temp file, invokes `cindex.Index.parse`, returns `(TranslationUnit, ASTNode, errors)`. |
| [backend/analyzer/cfg.py](backend/analyzer/cfg.py) | `_CFGBuilder` walks each function body, emits `BasicBlock`s + labeled edges. Handles `IF_STMT`, `WHILE_STMT`, `DO_STMT`, `FOR_STMT`, `RETURN_STMT`, `BREAK_STMT`, `CONTINUE_STMT`, `COMPOUND_STMT`. |
| [backend/analyzer/dataflow.py](backend/analyzer/dataflow.py) | Reaching definitions + live variables. `extract_def_use(stmt)` walks an AST subtree, returns `(defined_vars, used_vars)`. Token inspection for `=`, `+=`, `++`, `--`. |
| [backend/analyzer/detectors/__init__.py](backend/analyzer/detectors/__init__.py) | `DETECTORS` list + `run_all(tu, cfgs, rds, lvs)`. Catches per-detector exceptions, dedupes. |
| `backend/analyzer/detectors/*.py` | One file per category. Each exports `def detect(tu, cfg, rd, lv) -> list[Diagnostic]`. |
| [backend/analyzer/llvm_ir.py](backend/analyzer/llvm_ir.py) | Shells to `clang -S -emit-llvm -O0 -g -gcolumn-info`. Honours `$CLANG_PATH`. Returns `IRResult(ok, ir, error)`. |
| [backend/analyzer/ir_introspect.py](backend/analyzer/ir_introspect.py) | Pure-regex IR parser. Emits `IRInstruction`, `IRMetrics`, `ParsedIR`. `evidence_for(parsed, fn, line, category) -> list[str]`. |
| [backend/llm/client.py](backend/llm/client.py) | `explain_diagnostic(category, message, snippet, lines) -> (explanation, fix)`. Uses `groq.Groq` with Llama 3.3 70B. |
| [backend/llm/prompts.py](backend/llm/prompts.py) | System prompt + user template. |
| [backend/routes/analyze.py](backend/routes/analyze.py) | `POST /api/analyze` orchestrator + `GET /api/samples`. |
| [backend/routes/graph.py](backend/routes/graph.py) | `POST /api/cfg` — serializes one CFG per function to Cytoscape JSON. |
| [backend/routes/explain.py](backend/routes/explain.py) | `POST /api/explain` — builds snippet context, calls LLM client. |

### Frontend

| Path | Role |
| --- | --- |
| [static/index.html](static/index.html) | Layout, tab markup, script tags. Cytoscape loaded *before* Monaco's AMD loader to avoid `define()` collision. |
| [static/app.js](static/app.js) | Monaco bootstrap (source + LLVM editors), tab logic, persistence (`localStorage`), `Ctrl+Enter`, `renderDiagnostics`, `renderLLVMIR`, `renderLLVMEvidence`, `renderLLVMMetrics`. |
| [static/cfg.js](static/cfg.js) | Cytoscape rendering, dagre layout, node-kind styles, click-to-reveal in Monaco. |
| [static/styles.css](static/styles.css) | Dark theme, tab pills, diagnostic cards, LLVM evidence block, metrics bar. |
| [static/vendor/](static/vendor/) | Cytoscape + dagre + cytoscape-dagre, vendored to avoid CDN dependency. |

### Tests

| Path | Cases |
| --- | --- |
| [tests/test_parser.py](tests/test_parser.py) | 3 — libclang load, trivial parse, syntax-error collection |
| [tests/test_cfg.py](tests/test_cfg.py) | 8 — shape tests for if/else, while/for/do, break/continue, return |
| [tests/test_dataflow.py](tests/test_dataflow.py) | 10 — def/use extraction, reaching-def kill/union, live-vars dead-store |
| [tests/test_detectors.py](tests/test_detectors.py) | 7 — one TP per detector |
| [tests/test_llvm_ir.py](tests/test_llvm_ir.py) | 5 — clang invocation, friendly errors, real end-to-end |
| [tests/test_ir_introspect.py](tests/test_ir_introspect.py) | 13 — regex parse, dbg-line resolution, evidence tiers, real end-to-end |

**Total: 46 tests.** Each test that needs the clang CLI auto-skips when
clang is missing.

### Entry-point scripts

| Path | Role |
| --- | --- |
| [build.sh](build.sh) | Create `.venv`, `pip install -r requirements.txt`. Idempotent. |
| [run.sh](run.sh) | Activate `.venv`, start uvicorn on `:8000`. |
| [evaluate.sh](evaluate.sh) | Activate `.venv`, run `scripts/evaluate.py`. |
| [scripts/evaluate.py](scripts/evaluate.py) | Walk `testcases/`, run CD_LAB + gcc + clang + cppcheck, compute per-category P/R/F1, print markdown. |

---

## 3. CFG construction

`_CFGBuilder` in [cfg.py](backend/analyzer/cfg.py) is structured as a
dispatch table on cursor kind. Each handler returns either:

- the **block** new statements should append to (control falls through), or
- `None` (control diverged — `return`, `break`, `continue`).

A loop stack tracks `(continue_target, break_target)` pairs so nested
loops emit correct backedges. Sample shape for `for`:

```
ENTRY
  ↓
for_init  ──→  for_cond (loop_header) ──T──→ for_body ──→ for_inc
                       │                                     │
                       └──F──→ after_for                     │
                                                             │
                       ←────────── back ────────────────────┘
```

`break` synthesises a one-statement `break` block with an edge labeled
`break` to the loop's break-target; `continue` does the same to the
continue-target. The post-loop block `after_for` is created up-front
and dropped at the end if no edge points at it (every branch
diverged).

---

## 4. Dataflow

Both analyses use the textbook worklist algorithm.

**Reaching definitions** (forward, may):

- `Definition = (var, block_id, stmt_index, line)`
- `GEN[B]` = last def of each var in block `B`
- `KILL[B]` = all other defs of vars defined in `B`
- `IN[B] = ⋃ OUT[pred]`
- `OUT[B] = GEN[B] ∪ (IN[B] − KILL[B])`

**Live variables** (backward, may):

- `USE[B]` = vars used before being defined inside `B`
- `DEF[B]` = vars defined inside `B`
- `OUT[B] = ⋃ IN[succ]`
- `IN[B] = USE[B] ∪ (OUT[B] − DEF[B])`

`extract_def_use(stmt_cursor)` is the single source of truth for both
analyses. It handles:

- `VAR_DECL` with non-trivial initializer → defines the variable
- `BINARY_OPERATOR` with top-level token `=` → defines the LHS,
  uses the RHS; compound forms (`+=`) also use the LHS
- `UNARY_OPERATOR` with `++` or `--` → both def and use of operand
- `DECL_REF_EXPR` in a non-LHS context → use

Operator detection is token-based: we walk the gap between LHS and
RHS extents looking for `=`, `+=`, …, `++`, `--`. This works for
every `-O0` program we tested.

---

## 5. Detectors

Each detector follows the same skeleton:

```python
def detect(tu, cfg, rd, lv) -> list[Diagnostic]:
    diags = []
    for block_id in cfg.graph.nodes():
        for stmt in cfg.graph.nodes[block_id]["block"].statements:
            for sub in walk_cursor(stmt):
                if <pattern matches>:
                    diags.append(mk_diag(category, severity, sub, msg, block_id))
    return diags
```

Shared helpers in [backend/analyzer/util.py](backend/analyzer/util.py):

- `walk_cursor(cursor)` — pre-order AST iterator
- `is_null_constant(cursor)` — recognise `NULL`, `nullptr`, `0`
  through `UNEXPOSED_EXPR` / `CSTYLE_CAST_EXPR` wrappers
- `_lvalue_name(cursor)` — resolve a possibly-parenthesised reference
  to a bare variable name
- `is_arrow_member_ref(cursor)` — distinguish `p->x` from `s.x`
- `mk_diag(category, severity, cursor, message, cfg_node_id)` —
  builds a `Diagnostic` with a UUID and the cursor extent as the
  range

For category-specific logic see the individual detector files.

---

## 6. LLVM layer

We invoke `clang -S -emit-llvm -O0 -g -gcolumn-info` on the same
source. The `-g` flag is what makes per-instruction source-line
attribution possible: every IR instruction emits a trailing
`, !dbg !N`, and the bottom of the module has `!N = !DILocation(line:
M, column: K, scope: !S)` nodes.

[ir_introspect.py](backend/analyzer/ir_introspect.py) parses this in
two passes:

1. **First pass** — sweep every line for `!N = !DILocation(line: M`
   and build `dict[int, int]` of metadata id → source line.
2. **Second pass** — walk function bodies. Track current function
   and brace depth. For each instruction line:
   - Match opcode with `^(?:%X\s*=\s*)?(\w+)\b`.
   - Increment `metrics.instructions`. If opcode is one of our
     interest kinds (`load`, `store`, `getelementptr`, `sdiv`,
     `udiv`, `add`, `sub`, `mul`, `shl`), bucket it.
   - Look up trailing `!dbg !N` and resolve via pass-1 dict.
   - Record an `IRInstruction(kind, text, function, dbg_line)`.

`evidence_for(parsed, function, line, category)` is a two-tier lookup:

1. **Source-line precise** — `parsed.by_function_line[(fn, line)]`
   filtered by the category's kind set. This is the common case when
   `-g` worked.
2. **Function-level fallback** — all relevant instructions inside
   the function. Used when the diagnostic line has no exact `!dbg`
   match.

Category → kinds map:

| Category | Kinds |
| --- | --- |
| `null_deref`, `use_after_free`, `dangling` | `load`, `store` |
| `oob` | `getelementptr`, `load`, `store` |
| `uninit` | `load` |
| `div_zero` | `sdiv`, `udiv` |
| `int_overflow` | `add`, `sub`, `mul`, `shl` |

The function name is recovered from `Diagnostic.cfg_node_id`
(`"<funcname>#<n>"` — see `_CFGBuilder._new_block`).

For the longer rationale and scope-locks see
[llvm.md](llvm.md).

---

## 7. LLM explanation layer

[backend/routes/explain.py](backend/routes/explain.py) builds an
explanation request by:

1. Slicing the source around the diagnostic line (`±context_lines`,
   default 3), with the offending line marked `<-- {message}`.
2. Passing `(category, message, snippet, start_line, end_line)` to
   `explain_diagnostic` in [backend/llm/client.py](backend/llm/client.py).

The Groq SDK call uses `llama-3.3-70b-versatile` with temperature
0.1. The model is asked for JSON only:

```json
{"explanation": "...", "fix_suggestion": "..."}
```

Markdown code fences are stripped before `json.loads`. If JSON
parsing fails we still surface the raw content — better than a 500.

---

## 8. Frontend

Vanilla JS, no build step. Two Monaco editors:

- **Source editor** (`#editor`) — full edit + save to `localStorage`
  on every keystroke (debounced 500 ms).
- **LLVM IR editor** (`#llvm-editor`) — `readOnly: true`,
  `language: 'plaintext'`. Monaco doesn't ship an `llvm` Monarch
  grammar; plaintext is acceptable.

Cytoscape **must load before** Monaco's AMD loader, because both
UMD libraries detect `define()` and try to register as anonymous AMD
modules. Loading them first means they fall back to globals
(`window.cytoscape`, `window.dagre`, `window.cytoscapeDagre`).

Persistence keys (`localStorage`):

- `cdlab.source` — editor contents
- `cdlab.language` — c / cpp
- `cdlab.activeTab` — which tab was last active

Restored at `initMonaco` time. `Ctrl+Enter` (or `Cmd+Enter`) anywhere
on the page triggers Analyze.

---

## 9. Configuration

| Env var | Purpose | Default |
| --- | --- | --- |
| `GROQ_API_KEY` | Enables LLM explanations | `""` (offline notice in UI) |
| `CLANG_PATH` | Override clang lookup for LLVM IR | first `clang` on PATH |
| `LIBCLANG_PATH` | Override libclang.dll path | bundled in `libclang` PyPI package |

Example: see [.env.example](.env.example). `python-dotenv` loads
`.env` at import time in [backend/main.py](backend/main.py) and in
[conftest.py](conftest.py) so pytest picks up the same config.

---

## 10. Testing strategy

| Test class | Approach |
| --- | --- |
| Parser | Smoke (libclang loads, trivial program parses). |
| CFG | Shape tests — count nodes by kind, assert reachability, assert specific edge labels (`T`, `F`, `back`). |
| Dataflow | Run reaching-defs / live-vars on hand-written programs with known answers. |
| Detectors | Parameterised — `(category, code, expected_hit)`. |
| LLVM IR | Two layers: (1) parser pure-string tests, (2) end-to-end tests that shell out to real clang and assert the IR contains expected opcodes (auto-skip when clang missing). |
| Integration | The evaluation harness *is* the integration test: it exercises every layer end-to-end against the testcases directory. |

`pytest tests/` runs all 46 cases in ~2 s on the dev machine.

`./evaluate.sh` runs the full pipeline against the 17 testcases plus
gcc / clang baselines in ~30 s on the dev machine.
