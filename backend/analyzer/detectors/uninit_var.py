"""Uninitialized variable detector."""

from __future__ import annotations

from clang import cindex
from ..cfg import FunctionCFGData
from ..dataflow import ReachingDefsResult, LiveVarsResult, extract_def_use
from ..util import walk_cursor, _lvalue_name, mk_diag
from backend.schemas import Diagnostic

def detect(
    tu: cindex.TranslationUnit,
    cfg: FunctionCFGData,
    rd: ReachingDefsResult,
    lv: LiveVarsResult,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    
    # 1. Identify local non-static variables declared inside the function that have no initializers
    uninit_candidates = {}
    for sub_c in walk_cursor(cfg.cursor):
        if sub_c.kind.name == "VAR_DECL":
            # Check storage class to filter out static/extern variables
            sc = sub_c.storage_class.name
            if sc in ("NONE", "AUTO"):
                # Check if it has any children that act as an initializer
                has_init = False
                for ch in sub_c.get_children():
                    if ch.kind.name not in ("TYPE_REF", "NAMESPACE_REF"):
                        has_init = True
                        break
                if not has_init and sub_c.spelling:
                    uninit_candidates[sub_c.spelling] = sub_c

    # 2. Iterate through each block to find uses of uninitialized variables
    for bid in cfg.graph.nodes():
        block = cfg.graph.nodes[bid]["block"]
        current_reaching = set(rd.in_sets[bid])
        
        for i, stmt in enumerate(block.statements):
            # Extract uses in the statement
            _, stmt_uses = extract_def_use(stmt)
            
            # Find the exact DECL_REF_EXPR cursors for the uses
            for sub_c in walk_cursor(stmt):
                if sub_c.kind.name == "DECL_REF_EXPR" and sub_c.spelling:
                    var = sub_c.spelling
                    if var in stmt_uses and var in uninit_candidates:
                        # Check reaching definitions
                        var_defs = {d for d in current_reaching if d.var == var}
                        if len(var_defs) == 0:
                            decl_cursor = uninit_candidates[var]
                            decl_line = decl_cursor.location.line or 0
                            use_line = sub_c.location.line or 0
                            reasoning = [
                                f"Variable '{var}' declared without initializer at line {decl_line}",
                                f"No reaching definition for '{var}' at the use site",
                                f"'{var}' read at line {use_line}",
                            ]
                            diags.append(
                                mk_diag(
                                    category="uninit",
                                    severity="error",
                                    cursor=sub_c,
                                    message=f"Use of uninitialized variable '{var}'",
                                    cfg_node_id=bid,
                                    reasoning=reasoning,
                                )
                            )
            
            # Update reaching definitions locally in the block
            stmt_defs, _ = extract_def_use(stmt)
            for v in stmt_defs:
                current_reaching = {d for d in current_reaching if d.var != v}
                from ..dataflow import Definition
                line = stmt.location.line or 0
                current_reaching.add(Definition(var=v, block_id=bid, stmt_index=i, line=line))
                
    return diags
