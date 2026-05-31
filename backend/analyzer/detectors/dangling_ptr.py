"""Dangling pointer detector."""

from __future__ import annotations

from clang import cindex
from ..cfg import FunctionCFGData
from ..dataflow import ReachingDefsResult, LiveVarsResult
from ..util import walk_cursor, mk_diag
from backend.schemas import Diagnostic

def detect(
    tu: cindex.TranslationUnit,
    cfg: FunctionCFGData,
    rd: ReachingDefsResult,
    lv: LiveVarsResult,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    
    # 1. Walk the function cursor to find RETURN_STMT
    for sub_c in walk_cursor(cfg.cursor):
        if sub_c.kind.name == "RETURN_STMT":
            # Walk children of the return statement to find &local
            children = list(sub_c.get_children())
            if children:
                ret_expr = children[0]
                
                # Check for & operand
                is_addr_of = False
                if ret_expr.kind.name == "UNARY_OPERATOR":
                    try:
                        is_addr_of = any(t.spelling == "&" for t in ret_expr.get_tokens())
                    except Exception:
                        is_addr_of = False
                        
                if is_addr_of:
                    ret_expr_children = list(ret_expr.get_children())
                    if ret_expr_children:
                        operand = ret_expr_children[0]
                        if operand.kind.name == "DECL_REF_EXPR":
                            decl = operand.referenced
                            if decl is not None:
                                # Check if it is a parameter or stack variable
                                is_local = False
                                if decl.kind.name == "PARM_DECL":
                                    is_local = True
                                elif decl.kind.name == "VAR_DECL":
                                    sc = decl.storage_class.name
                                    if sc in ("NONE", "AUTO"):
                                        is_local = True
                                        
                                if is_local:
                                    diags.append(
                                        mk_diag(
                                            category="dangling",
                                            severity="error",
                                            cursor=sub_c,
                                            message=f"Address of local stack variable '{operand.spelling}' returned",
                                            cfg_node_id=None # We can leave this empty or match block id if we want
                                        )
                                    )
                                    
    return diags
