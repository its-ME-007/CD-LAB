"""Null pointer dereference detector."""

from __future__ import annotations

from clang import cindex
from ..cfg import FunctionCFGData
from ..dataflow import ReachingDefsResult, LiveVarsResult, extract_def_use, Definition
from ..util import walk_cursor, is_null_constant, _lvalue_name, is_arrow_member_ref, mk_diag
from backend.schemas import Diagnostic


def _find_null_inits(stmt) -> list[tuple[str, object, int, int]]:
    """Return list of (var_name, block_id_placeholder, stmt_index, line) for null-init VAR_DECLs."""
    results = []
    if stmt.kind.name == "DECL_STMT":
        for ch in stmt.get_children():
            if ch.kind.name == "VAR_DECL":
                non_type_children = [c for c in ch.get_children()
                                     if c.kind.name not in ("TYPE_REF", "NAMESPACE_REF")]
                if non_type_children and is_null_constant(non_type_children[0]):
                    results.append((ch.spelling, ch.location.line or 0))
    elif stmt.kind.name == "VAR_DECL":
        non_type_children = [c for c in stmt.get_children()
                             if c.kind.name not in ("TYPE_REF", "NAMESPACE_REF")]
        if non_type_children and is_null_constant(non_type_children[0]):
            results.append((stmt.spelling, stmt.location.line or 0))
    return results


def detect(
    tu: cindex.TranslationUnit,
    cfg: FunctionCFGData,
    rd: ReachingDefsResult,
    lv: LiveVarsResult,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    # Pass 1: collect null definitions keyed by (var, block_id, stmt_index, line)
    null_definitions: set[tuple] = set()
    for bid in cfg.graph.nodes():
        block = cfg.graph.nodes[bid]["block"]
        for i, stmt in enumerate(block.statements):
            for var, line in _find_null_inits(stmt):
                null_definitions.add((var, bid, i, line))
            # Also handle plain assignment: p = NULL / p = 0
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
                        if var and is_null_constant(rhs):
                            null_definitions.add((var, bid, i, stmt.location.line or 0))

    # Pass 2: check dereferences
    for bid in cfg.graph.nodes():
        block = cfg.graph.nodes[bid]["block"]
        current_reaching: set[Definition] = set(rd.in_sets.get(bid, set()))

        for i, stmt in enumerate(block.statements):
            for sub_c in walk_cursor(stmt):
                var = None
                is_deref = False

                if sub_c.kind.name == "UNARY_OPERATOR":
                    try:
                        is_star = any(t.spelling == "*" for t in sub_c.get_tokens())
                    except Exception:
                        is_star = False
                    if is_star:
                        children = list(sub_c.get_children())
                        if children:
                            var = _lvalue_name(children[0])
                            is_deref = True

                elif sub_c.kind.name == "MEMBER_REF_EXPR" and is_arrow_member_ref(sub_c):
                    children = list(sub_c.get_children())
                    if children:
                        var = _lvalue_name(children[0])
                        is_deref = True

                if is_deref and var:
                    var_defs = {d for d in current_reaching if d.var == var}
                    if var_defs:
                        null_defs = {d for d in var_defs
                                     if (d.var, d.block_id, d.stmt_index, d.line) in null_definitions}
                        if len(null_defs) == len(var_defs):
                            diags.append(mk_diag("null_deref", "error", sub_c,
                                                 f"Dereference of null pointer '{var}'", bid))
                        elif null_defs:
                            diags.append(mk_diag("null_deref", "warning", sub_c,
                                                 f"Pointer '{var}' may be null when dereferenced", bid))

            # Update local reaching defs
            stmt_defs, _ = extract_def_use(stmt)
            line = stmt.location.line or 0
            for v in stmt_defs:
                current_reaching = {d for d in current_reaching if d.var != v}
                current_reaching.add(Definition(var=v, block_id=bid, stmt_index=i, line=line))

    return diags
