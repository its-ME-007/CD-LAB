"""Classical dataflow analyses over a `FunctionCFGData`.

Implements the two analyses the Phase-3 detectors need:

* **Reaching definitions** (forward, may): which `(var, location)` pairs can
  reach the entry of each block.
* **Live variables** (backward, may): which variables are live at the entry
  and exit of each block.

Both use the standard worklist iteration. Def/use extraction is a syntactic
walk of statement subtrees:

* `VAR_DECL` with initializer → defines that variable, uses appear in the init.
* `BINARY_OPERATOR` whose top-level operator is `=` / `+=` / ... → defines the
  LHS variable (if it's a simple `DECL_REF_EXPR`); both sides contribute uses
  for compound assignment, only RHS for plain `=`.
* `UNARY_OPERATOR` `++` / `--` → both a use and a def of the operand.
* `DECL_REF_EXPR` outside an LHS context → use.

This is intentionally conservative and syntactic. Phase 3 detectors layer
their own AST walks on top for category-specific reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from clang import cindex

from .cfg import FunctionCFGData


_ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}
_COMPOUND_ASSIGN_OPS = _ASSIGN_OPS - {"="}
_INCDEC_OPS = {"++", "--"}


# ---------------------------------------------------------------------------
# Def/Use extraction
# ---------------------------------------------------------------------------

def _top_level_op(cursor: cindex.Cursor) -> str | None:
    """Return the operator spelling between cursor's two operands, or None.

    Works by finding tokens that fall in the gap between the LHS extent end
    and the RHS extent start.
    """
    children = list(cursor.get_children())
    if len(children) != 2:
        return None
    lhs_end = children[0].extent.end
    rhs_start = children[1].extent.start
    lhs_pos = (lhs_end.line, lhs_end.column)
    rhs_pos = (rhs_start.line, rhs_start.column)
    for tok in cursor.get_tokens():
        loc = tok.location
        pos = (loc.line, loc.column)
        if lhs_pos <= pos < rhs_pos:
            return tok.spelling
    return None


def _unary_op(cursor: cindex.Cursor) -> str | None:
    """Best-effort: scan tokens for a recognized unary operator."""
    for tok in cursor.get_tokens():
        if tok.spelling in _INCDEC_OPS or tok.spelling in {"-", "+", "!", "~", "*", "&"}:
            return tok.spelling
    return None


def _lvalue_name(cursor: cindex.Cursor) -> str | None:
    """If cursor is a simple variable reference (possibly wrapped in
    UNEXPOSED_EXPR / PAREN_EXPR), return its spelling."""
    cur = cursor
    for _ in range(4):
        kind = cur.kind.name
        if kind == "DECL_REF_EXPR":
            return cur.spelling or None
        if kind in ("UNEXPOSED_EXPR", "PAREN_EXPR"):
            ch = list(cur.get_children())
            if not ch:
                return None
            cur = ch[0]
            continue
        return None
    return None


def extract_def_use(stmt: cindex.Cursor) -> tuple[set[str], set[str]]:
    """Walk a statement subtree and return (defined_vars, used_vars).

    Pure syntactic; no type or pointer reasoning.
    """
    defs: set[str] = set()
    uses: set[str] = set()

    def walk(c: cindex.Cursor, lhs_context: bool = False) -> None:
        kind = c.kind.name

        if kind == "VAR_DECL":
            # `int x = expr;` — defines x and uses anything in expr.
            children = list(c.get_children())
            has_init = any(ch.kind.name not in ("TYPE_REF", "NAMESPACE_REF") for ch in children)
            if has_init and c.spelling:
                defs.add(c.spelling)
            for ch in children:
                walk(ch)
            return

        if kind in ("BINARY_OPERATOR", "COMPOUND_ASSIGNMENT_OPERATOR"):
            op = _top_level_op(c)
            children = list(c.get_children())
            if op in _ASSIGN_OPS and len(children) == 2:
                lhs, rhs = children
                lhs_var = _lvalue_name(lhs)
                if lhs_var:
                    defs.add(lhs_var)
                if op in _COMPOUND_ASSIGN_OPS and lhs_var:
                    uses.add(lhs_var)
                # Always walk RHS for nested uses.
                walk(rhs)
                # Walk LHS subtree skipping the top-level var name (e.g.
                # `arr[i] = ...` — `i` is a use even though arr is the lvalue).
                if lhs_var is None:
                    walk(lhs)
                else:
                    for ch in lhs.get_children():
                        walk(ch)
                return
            # Non-assign binary op: just recurse normally.
            for ch in children:
                walk(ch)
            return

        if kind == "UNARY_OPERATOR":
            op = _unary_op(c)
            children = list(c.get_children())
            if op in _INCDEC_OPS and children:
                target = _lvalue_name(children[0])
                if target:
                    defs.add(target)
                    uses.add(target)
                else:
                    walk(children[0])
            else:
                for ch in children:
                    walk(ch)
            return

        if kind == "DECL_REF_EXPR":
            if not lhs_context and c.spelling:
                uses.add(c.spelling)
            return

        # Default: recurse into children.
        for ch in c.get_children():
            walk(ch)

    walk(stmt)
    return defs, uses


# ---------------------------------------------------------------------------
# Reaching definitions (forward / may)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Definition:
    var: str
    block_id: str
    stmt_index: int
    line: int

    def __repr__(self) -> str:  # for nicer test failures
        return f"Def({self.var}@{self.block_id}:{self.stmt_index}/L{self.line})"


@dataclass
class ReachingDefsResult:
    in_sets: dict[str, set[Definition]] = field(default_factory=dict)
    out_sets: dict[str, set[Definition]] = field(default_factory=dict)
    gen: dict[str, set[Definition]] = field(default_factory=dict)
    kill: dict[str, set[Definition]] = field(default_factory=dict)
    all_defs_by_var: dict[str, set[Definition]] = field(default_factory=dict)


def reaching_definitions(cfg: FunctionCFGData) -> ReachingDefsResult:
    blocks = list(cfg.graph.nodes())
    all_defs_by_var: dict[str, set[Definition]] = {}
    block_defs: dict[str, list[Definition]] = {b: [] for b in blocks}

    for bid in blocks:
        block = cfg.graph.nodes[bid]["block"]
        for i, stmt in enumerate(block.statements):
            stmt_defs, _ = extract_def_use(stmt)
            line = (stmt.location.line if stmt.location else 0) or 0
            for var in stmt_defs:
                d = Definition(var=var, block_id=bid, stmt_index=i, line=line)
                block_defs[bid].append(d)
                all_defs_by_var.setdefault(var, set()).add(d)

    gen: dict[str, set[Definition]] = {b: set() for b in blocks}
    kill: dict[str, set[Definition]] = {b: set() for b in blocks}
    for bid in blocks:
        last_def_for_var: dict[str, Definition] = {}
        for d in block_defs[bid]:
            last_def_for_var[d.var] = d
        gen[bid] = set(last_def_for_var.values())
        for var, last in last_def_for_var.items():
            kill[bid] |= all_defs_by_var.get(var, set()) - {last}

    in_sets: dict[str, set[Definition]] = {b: set() for b in blocks}
    out_sets: dict[str, set[Definition]] = {b: set(gen[b]) for b in blocks}

    worklist = list(blocks)
    in_worklist = set(blocks)
    while worklist:
        bid = worklist.pop()
        in_worklist.discard(bid)
        new_in: set[Definition] = set()
        for pred in cfg.graph.predecessors(bid):
            new_in |= out_sets[pred]
        new_out = gen[bid] | (new_in - kill[bid])
        if new_in != in_sets[bid] or new_out != out_sets[bid]:
            in_sets[bid] = new_in
            out_sets[bid] = new_out
            for succ in cfg.graph.successors(bid):
                if succ not in in_worklist:
                    worklist.append(succ)
                    in_worklist.add(succ)

    return ReachingDefsResult(
        in_sets=in_sets,
        out_sets=out_sets,
        gen=gen,
        kill=kill,
        all_defs_by_var=all_defs_by_var,
    )


# ---------------------------------------------------------------------------
# Live variables (backward / may)
# ---------------------------------------------------------------------------

@dataclass
class LiveVarsResult:
    in_sets: dict[str, set[str]] = field(default_factory=dict)
    out_sets: dict[str, set[str]] = field(default_factory=dict)
    use: dict[str, set[str]] = field(default_factory=dict)
    defs: dict[str, set[str]] = field(default_factory=dict)


def live_variables(cfg: FunctionCFGData) -> LiveVarsResult:
    blocks = list(cfg.graph.nodes())
    use: dict[str, set[str]] = {b: set() for b in blocks}
    defs: dict[str, set[str]] = {b: set() for b in blocks}

    for bid in blocks:
        block = cfg.graph.nodes[bid]["block"]
        local_defined: set[str] = set()
        for stmt in block.statements:
            d, u = extract_def_use(stmt)
            for v in u:
                if v not in local_defined:
                    use[bid].add(v)
            local_defined |= d
        defs[bid] = local_defined

    in_sets: dict[str, set[str]] = {b: set() for b in blocks}
    out_sets: dict[str, set[str]] = {b: set() for b in blocks}

    worklist = list(blocks)
    in_worklist = set(blocks)
    while worklist:
        bid = worklist.pop()
        in_worklist.discard(bid)
        new_out: set[str] = set()
        for succ in cfg.graph.successors(bid):
            new_out |= in_sets[succ]
        new_in = use[bid] | (new_out - defs[bid])
        if new_in != in_sets[bid] or new_out != out_sets[bid]:
            in_sets[bid] = new_in
            out_sets[bid] = new_out
            for pred in cfg.graph.predecessors(bid):
                if pred not in in_worklist:
                    worklist.append(pred)
                    in_worklist.add(pred)

    return LiveVarsResult(in_sets=in_sets, out_sets=out_sets, use=use, defs=defs)
