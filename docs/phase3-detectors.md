# Phase 3 — UB Detectors (Implementation Spec)

This is the per-detector cookbook. Each section gives the AST/dataflow inputs,
the algorithm, the false-positive trap to avoid, and a TP + TN test snippet.

All detectors live in `backend/analyzer/detectors/` and follow the same
interface:

```python
def detect(
    tu: cindex.TranslationUnit,
    cfg: FunctionCFGData,
    rd: ReachingDefsResult,
    lv: LiveVarsResult,
) -> list[Diagnostic]:
    ...
```

`detectors/__init__.py` exposes:

```python
DETECTORS = [null_deref.detect, uninit_var.detect, ...]

def run_all(tu, cfgs, dataflows) -> list[Diagnostic]:
    out = []
    for cfg, rd, lv in zip(cfgs, dataflows_rd, dataflows_lv):
        for fn in DETECTORS:
            out.extend(fn(tu, cfg, rd, lv))
    return _dedupe(out)
```

`routes/analyze.py` is updated to compute `dataflows` once per function and
pass them in.

---

## Shared helpers (add to `analyzer/dataflow.py` or new `analyzer/util.py`)

- `is_null_constant(cursor) -> bool` — true if cursor expands to `0`,
  `NULL`, or `nullptr`. Walk through `UNEXPOSED_EXPR` / `CSTYLE_CAST_EXPR`
  wrappers; bottom must be `INTEGER_LITERAL` with spelling `"0"` or
  `CXX_NULL_PTR_LITERAL_EXPR`.
- `extract_lvalue_chain(cursor) -> str | None` — already exists in
  `dataflow.py` as `_lvalue_name`; expose it.
- `walk_cursor(cursor) -> Iterator[cindex.Cursor]` — pre-order walk; used
  pervasively below.
- `mk_diag(category, severity, cursor, message, cfg_node_id=None) -> Diagnostic`
  — fills `range` from `cursor.extent`, generates UUID `id`.

---

## 1. `null_deref`

**Inputs:** AST + reaching defs.

**Algorithm:**
1. Build a set `null_defs[var]` = definitions where the RHS is a null
   constant (walk every `BINARY_OPERATOR =` and `VAR_DECL` initializer).
2. For each `UNARY_OPERATOR *` (dereference) or `MEMBER_REF_EXPR` with `->`,
   extract the operand's variable name.
3. Look up the block's `rd.in_sets`. If *every* reaching definition of that
   var is in `null_defs[var]`, emit `error`. If *some* are null, emit `warning`.

**Trap:** `*p` where `p` is reassigned in the same block before the deref →
the in-set is stale. Walk statements within the block in order, updating
the "live" set of defs locally.

**TP sample:**
```c
int *p = NULL;
*p = 5;            // → null_deref error
```

**TN sample:**
```c
int x = 0;
int *p = &x;
*p = 5;            // OK
```

---

## 2. `uninit_var`

**Inputs:** reaching defs.

**Algorithm:**
1. For every `DECL_REF_EXPR` in a use context (not LHS of assignment),
   extract var name.
2. Find the block containing this cursor (walk CFG nodes; match by cursor
   identity or location).
3. Look up `rd.in_sets[block]`. If the var has zero reaching definitions
   AND its declaring `VAR_DECL` had no initializer, emit `error`.

**Trap:** parameters and globals appear as no-reaching-def at function entry
but are not UB. Filter by `VAR_DECL.storage_class == NONE` AND the decl is
inside the function body (not a `PARM_DECL`).

**TP sample:**
```c
int x;
int y = x + 1;     // uninit
```

**TN sample:**
```c
int x = 0;
int y = x + 1;     // OK
```

---

## 3. `div_by_zero`

**Inputs:** AST + reaching defs.

**Algorithm:**
1. For every `BINARY_OPERATOR` with top-level op `/` or `%`, look at the RHS.
2. If RHS is an `INTEGER_LITERAL` with value `0` → `error`.
3. If RHS is a `DECL_REF_EXPR` and its reaching defs all set it to literal
   `0` → `error`.
4. If RHS is a variable with mixed defs (some 0, some not), and there's no
   guard like `if (rhs != 0) { ... }` upstream → `warning`. (Phase 3
   simplification: just emit `warning` if any reaching def is 0.)

**Trap:** unsigned arithmetic where the divisor is known non-zero from
context. Out of scope — accept the false positive and let the LLM
explanation clarify.

**TP sample:**
```c
int a = 10;
int b = a / 0;     // div_zero error
```

**TN sample:**
```c
int a = 10;
int b = a / 2;     // OK
```

---

## 4. `use_after_free`

**Inputs:** AST + CFG.

**Algorithm:**
1. Walk the AST for `CALL_EXPR` to `free` or `delete` / `delete[]`. Record
   `(var, location)` for the freed pointer.
2. Maintain a per-block "freed" set during CFG traversal in topological order
   (or via a small forward dataflow: GEN = freed-in-block, KILL =
   reassignments to that var).
3. For every use of a freed pointer (deref or pass-to-function) before
   reassignment → `error`.

**Trap:** `p = NULL;` after `free(p);` should clear `p` from freed set.
Treat `VAR_DECL` re-decls (impossible in C, allowed in C++ shadowing) as
KILL too.

**TP sample:**
```cpp
int* p = new int(7);
delete p;
int x = *p;        // use_after_free error
```

**TN sample:**
```cpp
int* p = new int(7);
delete p;
p = nullptr;
if (p) { /* ... */ }   // OK
```

---

## 5. `dangling_ptr`

**Inputs:** AST only.

**Algorithm:**
1. For every `RETURN_STMT`, walk its child expression.
2. If the expression is `UNARY_OPERATOR &` applied to a `DECL_REF_EXPR`
   pointing to a local variable (storage class `auto`, decl inside the
   function body) → `error`.
3. Same check for assignments where RHS is `&local` and LHS escapes (passed
   to a function, stored in a non-local) — Phase 3 minimum: just handle the
   return case.

**Trap:** returning `&global_var` or `&static_var` is fine. Verify the
referent's `linkage_kind` / `storage_class`.

**TP sample:**
```c
int* f(void) {
    int local = 42;
    return &local;     // dangling_ptr error
}
```

**TN sample:**
```c
static int g = 42;
int* f(void) {
    return &g;          // OK
}
```

---

## 6. `oob_access`

**Inputs:** AST only (Phase 3 minimum — no loop analysis).

**Algorithm:**
1. Walk `VAR_DECL` cursors with `type.kind == cindex.TypeKind.CONSTANTARRAY`.
   Record `(var_name, size)` per function.
2. For every `ARRAY_SUBSCRIPT_EXPR`, extract:
   - The base var name (via `_lvalue_name` on `children[0]`).
   - The index expression (children[1]).
3. If the index is an `INTEGER_LITERAL` with value `>= size` OR `< 0` → `error`.
4. Otherwise (variable or computed index) → skip (Phase 3 doesn't do range
   analysis; bound-check would belong in a later phase).

**Trap:** `arr[i]` where `i` is a constant in a `for (int i = 0; i < N; ++i)`
loop — we'd want to know `i ∈ [0, N)`. Out of scope for Phase 3.

**TP sample:**
```c
int arr[3] = {1, 2, 3};
int x = arr[5];        // oob_access error
```

**TN sample:**
```c
int arr[3] = {1, 2, 3};
int x = arr[2];        // OK
```

---

## 7. `int_overflow`

**Inputs:** AST only (Phase 3 minimum — pattern-based).

**Algorithm:**
1. Walk `BINARY_OPERATOR` with top-level op in `{+, -, *, <<}`.
2. If both operands are `INTEGER_LITERAL`s and the computed result exceeds
   the type's range (`INT_MAX` for `int`) → `error`.
3. If both operands are signed `int`-typed variables and there's no guard
   like `if (a < INT_MAX - b)` upstream → `info` (very noisy; Phase 3
   default = off, behind a config flag).

**Trap:** category 3 is too noisy for default-on. Ship only category 1+2
detection initially. Document the limitation in the report.

**TP sample:**
```c
int x = 2147483647 + 1;    // int_overflow error
```

**TN sample:**
```c
int x = 100 + 1;           // OK
```

---

## Detector registration

```python
# backend/analyzer/detectors/__init__.py
from . import (
    null_deref, uninit_var, div_by_zero, use_after_free,
    dangling_ptr, oob_access, int_overflow,
)

DETECTORS = [
    null_deref.detect,
    uninit_var.detect,
    div_by_zero.detect,
    use_after_free.detect,
    dangling_ptr.detect,
    oob_access.detect,
    int_overflow.detect,
]

def run_all(tu, cfgs, dataflows_rd, dataflows_lv) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for cfg, rd, lv in zip(cfgs, dataflows_rd, dataflows_lv):
        for fn in DETECTORS:
            try:
                out.extend(fn(tu, cfg, rd, lv))
            except Exception as exc:
                # Detectors must never crash the pipeline. Log and skip.
                import logging
                logging.exception("detector %s failed: %s", fn.__module__, exc)
    return _dedupe(out)

def _dedupe(diags):
    seen, out = set(), []
    for d in diags:
        key = (d.category, d.range.line, d.range.column, d.message)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out
```

---

## Tests (`tests/test_detectors.py`)

One file, parameterized:

```python
import pytest
from backend.analyzer import parse_source, build_cfgs, reaching_definitions, live_variables
from backend.analyzer.detectors import run_all

CASES = [
    # (category, code, expected_hit)
    ("null_deref",  "int main(){int* p=0; *p=5; return 0;}",                  True),
    ("null_deref",  "int main(){int x=0; int* p=&x; *p=5; return 0;}",        False),
    ("uninit",      "int main(){int x; return x+1;}",                          True),
    ("uninit",      "int main(){int x=0; return x+1;}",                        False),
    # ... 14 cases total (2 per detector)
]

@pytest.mark.parametrize("category,code,expected_hit", CASES)
def test_detector(category, code, expected_hit):
    parsed = parse_source(code, language="c")
    cfgs = build_cfgs(parsed.tu)
    rds  = [reaching_definitions(c) for c in cfgs]
    lvs  = [live_variables(c)       for c in cfgs]
    diags = run_all(parsed.tu, cfgs, rds, lvs)
    hit = any(d.category == category for d in diags)
    assert hit == expected_hit, f"{category} expected={expected_hit} got={[d.category for d in diags]}"
```

---

## Order of implementation (suggested)

1. **`null_deref`** + **`uninit_var`** + **`div_by_zero`** — share reaching-defs
   plumbing; implementing them together exercises the `run_all` machinery.
2. **`dangling_ptr`** — pure AST walk; easiest detector, good morale boost.
3. **`oob_access`** — pure AST walk; introduces `TypeKind.CONSTANTARRAY`.
4. **`use_after_free`** — needs its own forward dataflow (freed-set);
   slightly more involved.
5. **`int_overflow`** — ship the literal-arithmetic case only; defer the
   noisy variable case.

Person 1 owns this entire phase. Person 2 should start drafting Phase 4 LLM
prompts using hand-written `Diagnostic` payloads while Phase 3 lands.
