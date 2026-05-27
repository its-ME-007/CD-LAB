"""Out of bounds access detector."""

from __future__ import annotations

from clang import cindex
from ..cfg import FunctionCFGData
from ..dataflow import ReachingDefsResult, LiveVarsResult
from ..util import walk_cursor, _lvalue_name, mk_diag
from backend.schemas import Diagnostic

def detect(
    tu: cindex.TranslationUnit,
    cfg: FunctionCFGData,
    rd: ReachingDefsResult,
    lv: LiveVarsResult,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    
    # 1. Walk the function body to find all local constant arrays and record their sizes
    constant_arrays = {}  # var_name -> size
    for sub_c in walk_cursor(cfg.cursor):
        if sub_c.kind.name == "VAR_DECL":
            t = sub_c.type
            if t is not None:
                # Type kind names in clang could be CONSTANTARRAY or contain CONSTANTARRAY
                t_kind = t.kind.name
                if t_kind == "CONSTANTARRAY" or "CONSTANTARRAY" in t_kind:
                    try:
                        size = t.get_array_size()
                        if size > 0 and sub_c.spelling:
                            constant_arrays[sub_c.spelling] = size
                    except Exception:
                        pass

    # 2. Walk the function body to find ARRAY_SUBSCRIPT_EXPR
    for sub_c in walk_cursor(cfg.cursor):
        if sub_c.kind.name == "ARRAY_SUBSCRIPT_EXPR":
            children = list(sub_c.get_children())
            if len(children) == 2:
                base, index = children
                base_var = _lvalue_name(base)
                
                if base_var and base_var in constant_arrays:
                    size = constant_arrays[base_var]
                    
                    # Check if index is an integer literal
                    val = None
                    is_negative = False
                    
                    if index.kind.name == "INTEGER_LITERAL":
                        try:
                            tokens = list(index.get_tokens())
                            if tokens:
                                val = int(tokens[0].spelling)
                        except ValueError:
                            pass
                    elif index.kind.name == "UNARY_OPERATOR":
                        # Check for unary minus (negative index)
                        try:
                            is_minus = any(t.spelling == "-" for t in index.get_tokens())
                        except Exception:
                            is_minus = False
                        if is_minus:
                            operand_children = list(index.get_children())
                            if operand_children and operand_children[0].kind.name == "INTEGER_LITERAL":
                                is_negative = True
                                
                    if is_negative:
                        diags.append(
                            mk_diag(
                                category="oob",
                                severity="error",
                                cursor=sub_c,
                                message=f"Out of bounds: negative index used on array '{base_var}' (size {size})",
                                cfg_node_id=None
                            )
                        )
                    elif val is not None:
                        if val < 0 or val >= size:
                            diags.append(
                                mk_diag(
                                    category="oob",
                                    severity="error",
                                    cursor=sub_c,
                                    message=f"Out of bounds: index {val} is out of bounds for array '{base_var}' (size {size})",
                                    cfg_node_id=None
                                )
                            )
                            
    return diags
