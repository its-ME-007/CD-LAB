"""Use after free detector."""

from __future__ import annotations

from clang import cindex
from ..cfg import FunctionCFGData
from ..dataflow import ReachingDefsResult, LiveVarsResult, extract_def_use
from ..util import walk_cursor, _lvalue_name, mk_diag
from backend.schemas import Diagnostic


def _callee_name(cursor: cindex.Cursor) -> str | None:
    """Return the spelling of the called function, including OVERLOADED_DECL_REF."""
    for sub in walk_cursor(cursor):
        if sub.kind.name in ("DECL_REF_EXPR", "OVERLOADED_DECL_REF") and sub.spelling:
            return sub.spelling
    return None


def get_freed_var(cursor: cindex.Cursor) -> str | None:
    """If cursor is free(p) or delete p, return the variable name.

    Handles both CALL_EXPR (C mode) and the flat UNEXPOSED_EXPR pattern
    that libclang emits for C++ when stdlib.h defines free as overloaded.
    """
    # Token-based fast check: if tokens don't start with 'free', skip
    try:
        toks = [t.spelling for t in cursor.get_tokens()]
    except Exception:
        toks = []

    if toks and toks[0] == "free" and len(toks) >= 4:
        # tokens: ['free', '(', '<var>', ')']
        # Extract the variable name directly from tokens
        return toks[2] if toks[1] == "(" and toks[3] == ")" else None

    # Unwrap UNEXPOSED_EXPR / PAREN_EXPR layers then check for CALL_EXPR
    cur = cursor
    for _ in range(4):
        if cur.kind.name in ("UNEXPOSED_EXPR", "PAREN_EXPR"):
            ch = list(cur.get_children())
            if not ch:
                return None
            cur = ch[0]
        else:
            break

    if cur.kind.name == "CALL_EXPR":
        children = list(cur.get_children())
        if children and _callee_name(children[0]) == "free":
            args = children[1:]
            if args:
                return _lvalue_name(args[0])
    elif cur.kind.name == "CXX_DELETE_EXPR":
        children = list(cur.get_children())
        if children:
            return _lvalue_name(children[0])
    return None


def detect(
    tu: cindex.TranslationUnit,
    cfg: FunctionCFGData,
    rd: ReachingDefsResult,
    lv: LiveVarsResult,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    blocks = list(cfg.graph.nodes())
    if not blocks:
        return diags

    # Pass 1: compute per-block GEN (freed vars) and KILL (reassigned vars).
    # Also record the source line of every free() / delete site so the
    # reasoning bullets can name a concrete line.
    gen: dict[str, set[str]] = {b: set() for b in blocks}
    kill: dict[str, set[str]] = {b: set() for b in blocks}
    freed_at: dict[str, list[int]] = {}
    for bid in blocks:
        block = cfg.graph.nodes[bid]["block"]
        freed_local: set[str] = set()
        killed_local: set[str] = set()
        for stmt in block.statements:
            freed = get_freed_var(stmt)
            if freed:
                freed_local.add(freed)
                killed_local.discard(freed)
                freed_at.setdefault(freed, []).append(stmt.location.line or 0)
            stmt_defs, _ = extract_def_use(stmt)
            for v in stmt_defs:
                freed_local.discard(v)
                killed_local.add(v)
        gen[bid] = freed_local
        kill[bid] = killed_local

    # Pass 2: forward dataflow for freed-pointer sets
    in_freed: dict[str, set[str]] = {b: set() for b in blocks}
    out_freed: dict[str, set[str]] = {b: set(gen[b]) for b in blocks}
    worklist = list(blocks)
    in_wl: set[str] = set(blocks)
    while worklist:
        bid = worklist.pop()
        in_wl.discard(bid)
        new_in: set[str] = set()
        for pred in cfg.graph.predecessors(bid):
            new_in |= out_freed[pred]
        new_out = gen[bid] | (new_in - kill[bid])
        if new_in != in_freed[bid] or new_out != out_freed[bid]:
            in_freed[bid] = new_in
            out_freed[bid] = new_out
            for succ in cfg.graph.successors(bid):
                if succ not in in_wl:
                    worklist.append(succ)
                    in_wl.add(succ)

    # Pass 3: report uses of freed pointers
    for bid in blocks:
        block = cfg.graph.nodes[bid]["block"]
        current_freed: set[str] = set(in_freed[bid])
        for stmt in block.statements:
            # Skip the free/delete call itself
            freed = get_freed_var(stmt)
            if freed:
                current_freed.add(freed)
                stmt_defs, _ = extract_def_use(stmt)
                for v in stmt_defs:
                    current_freed.discard(v)
                continue

            # Walk statement looking for DECL_REF_EXPR of freed vars
            _, stmt_uses = extract_def_use(stmt)
            for sub_c in walk_cursor(stmt):
                if (sub_c.kind.name == "DECL_REF_EXPR"
                        and sub_c.spelling
                        and sub_c.spelling in current_freed
                        and sub_c.spelling in stmt_uses):
                    var = sub_c.spelling
                    use_line = sub_c.location.line or 0
                    fr_lines = sorted({ln for ln in freed_at.get(var, []) if ln})
                    reasoning = [
                        (f"Pointer '{var}' freed at line {fr_lines[0]}"
                         if fr_lines else f"Pointer '{var}' freed by free()/delete"),
                        f"No reassignment of '{var}' between free and use",
                        f"'{var}' used at line {use_line}",
                    ]
                    diags.append(mk_diag(
                        category="use_after_free",
                        severity="error",
                        cursor=sub_c,
                        message=f"Use of freed pointer '{var}'",
                        cfg_node_id=bid,
                        reasoning=reasoning,
                    ))
                    break  # one diagnostic per statement is enough

            stmt_defs, _ = extract_def_use(stmt)
            for v in stmt_defs:
                current_freed.discard(v)

    return diags
