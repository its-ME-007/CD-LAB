"""Division by zero detector."""

from __future__ import annotations

from clang import cindex
from ..cfg import FunctionCFGData
from ..dataflow import ReachingDefsResult, LiveVarsResult, extract_def_use, Definition
from ..util import walk_cursor, is_null_constant, _lvalue_name, mk_diag
from backend.schemas import Diagnostic


def _is_zero_constant(cursor: cindex.Cursor) -> bool:
    """Return True if the cursor is a zero integer constant (0, not just NULL)."""
    cur = cursor
    for _ in range(4):
        kind = cur.kind.name
        if kind == "INTEGER_LITERAL":
            try:
                toks = [t.spelling for t in cur.get_tokens()]
                return toks == ["0"]
            except Exception:
                return cur.spelling == "0"
        if kind in ("UNEXPOSED_EXPR", "PAREN_EXPR", "IMPLICIT_CAST_EXPR"):
            ch = list(cur.get_children())
            if not ch:
                return False
            cur = ch[0]
        else:
            break
    return False


def _find_zero_inits(stmt) -> list[tuple[str, int]]:
    """Return (var_name, line) for VAR_DECLs initialized to zero."""
    results = []
    if stmt.kind.name == "DECL_STMT":
        for ch in stmt.get_children():
            if ch.kind.name == "VAR_DECL":
                non_type = [c for c in ch.get_children()
                            if c.kind.name not in ("TYPE_REF", "NAMESPACE_REF")]
                if non_type and _is_zero_constant(non_type[0]):
                    results.append((ch.spelling, ch.location.line or 0))
    elif stmt.kind.name == "VAR_DECL":
        non_type = [c for c in stmt.get_children()
                    if c.kind.name not in ("TYPE_REF", "NAMESPACE_REF")]
        if non_type and _is_zero_constant(non_type[0]):
            results.append((stmt.spelling, stmt.location.line or 0))
    return results


def detect(
    tu: cindex.TranslationUnit,
    cfg: FunctionCFGData,
    rd: ReachingDefsResult,
    lv: LiveVarsResult,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    # Pass 1: collect zero-value definitions
    zero_definitions: set[tuple] = set()
    for bid in cfg.graph.nodes():
        block = cfg.graph.nodes[bid]["block"]
        for i, stmt in enumerate(block.statements):
            for var, line in _find_zero_inits(stmt):
                zero_definitions.add((var, bid, i, line))
            if stmt.kind.name in ("BINARY_OPERATOR", "COMPOUND_ASSIGNMENT_OPERATOR"):
                children = list(stmt.get_children())
                if len(children) == 2:
                    lhs, rhs = children
                    try:
                        is_assign = any(t.spelling == "=" for t in stmt.get_tokens())
                    except Exception:
                        is_assign = True
                    if is_assign:
                        var = _lvalue_name(lhs)
                        if var and _is_zero_constant(rhs):
                            zero_definitions.add((var, bid, i, stmt.location.line or 0))

    # Pass 2: find division/modulo by zero
    for bid in cfg.graph.nodes():
        block = cfg.graph.nodes[bid]["block"]
        current_reaching: set[Definition] = set(rd.in_sets.get(bid, set()))

        for i, stmt in enumerate(block.statements):
            for sub_c in walk_cursor(stmt):
                if sub_c.kind.name == "BINARY_OPERATOR":
                    try:
                        children = list(sub_c.get_children())
                        if len(children) != 2:
                            continue
                        lhs, rhs = children
                        # Identify operator token between operands
                        lhs_end = (children[0].extent.end.line, children[0].extent.end.column)
                        rhs_start = (children[1].extent.start.line, children[1].extent.start.column)
                        op = None
                        for tok in sub_c.get_tokens():
                            pos = (tok.location.line, tok.location.column)
                            if lhs_end <= pos < rhs_start and tok.spelling in ("/", "%"):
                                op = tok.spelling
                                break
                    except Exception:
                        continue

                    if op not in ("/", "%"):
                        continue

                    op_line = sub_c.location.line or 0

                    # Case 1: literal zero divisor
                    if _is_zero_constant(rhs):
                        reasoning = [
                            f"Right-hand operand of '{op}' is the integer literal 0",
                            f"No guard condition prevents the division at line {op_line}",
                        ]
                        diags.append(mk_diag("div_zero", "error", sub_c,
                                             f"Division by literal zero ('{op}')", bid,
                                             reasoning=reasoning))
                        continue

                    # Case 2: variable divisor — check if always/possibly zero
                    var = _lvalue_name(rhs)
                    if var:
                        var_defs = {d for d in current_reaching if d.var == var}
                        if var_defs:
                            zero_defs = {d for d in var_defs
                                         if (d.var, d.block_id, d.stmt_index, d.line) in zero_definitions}
                            zero_lines = sorted({d.line for d in zero_defs if d.line})
                            if len(zero_defs) == len(var_defs):
                                reasoning = [
                                    (f"All reaching definitions of '{var}' assign 0 "
                                     f"(lines {zero_lines})" if zero_lines
                                     else f"All reaching definitions of '{var}' assign 0"),
                                    f"Used as divisor of '{op}' at line {op_line}",
                                ]
                                diags.append(mk_diag("div_zero", "error", sub_c,
                                                     f"Division by zero: '{var}' is always 0", bid,
                                                     reasoning=reasoning))
                            elif zero_defs:
                                reasoning = [
                                    (f"Some reaching definitions of '{var}' assign 0 "
                                     f"(lines {zero_lines})" if zero_lines
                                     else f"Some reaching definitions of '{var}' assign 0"),
                                    f"Zero divisor not ruled out on all paths",
                                    f"Used as divisor of '{op}' at line {op_line}",
                                ]
                                diags.append(mk_diag("div_zero", "warning", sub_c,
                                                     f"Division by zero: '{var}' may be 0", bid,
                                                     reasoning=reasoning))

            stmt_defs, _ = extract_def_use(stmt)
            line = stmt.location.line or 0
            for v in stmt_defs:
                current_reaching = {d for d in current_reaching if d.var != v}
                current_reaching.add(Definition(var=v, block_id=bid, stmt_index=i, line=line))

    return diags
