"""Integer overflow detector."""

from __future__ import annotations

from clang import cindex
from ..cfg import FunctionCFGData
from ..dataflow import ReachingDefsResult, LiveVarsResult
from ..util import walk_cursor, mk_diag
from backend.schemas import Diagnostic

def get_int_value(cursor: cindex.Cursor) -> int | None:
    """Evaluate an integer literal or unary minus literal expression."""
    if cursor.kind.name == "INTEGER_LITERAL":
        try:
            tokens = list(cursor.get_tokens())
            if tokens:
                sp = tokens[0].spelling.lower()
                # Strip integer type suffixes (unsigned, long, long long)
                for suffix in ("ull", "llu", "ll", "ul", "lu", "u", "l"):
                    if sp.endswith(suffix):
                        sp = sp[:-len(suffix)]
                        break
                # Handle base conversions
                if sp.startswith("0x"):
                    return int(sp, 16)
                if sp.startswith("0b"):
                    return int(sp, 2)
                if sp.startswith("0") and len(sp) > 1:
                    return int(sp, 8)
                return int(sp)
        except Exception:
            return None
    elif cursor.kind.name == "UNARY_OPERATOR":
        # Check for unary minus
        try:
            is_minus = any(t.spelling == "-" for t in cursor.get_tokens())
        except Exception:
            is_minus = False
        if is_minus:
            children = list(cursor.get_children())
            if children:
                val = get_int_value(children[0])
                if val is not None:
                    return -val
    return None

def detect(
    tu: cindex.TranslationUnit,
    cfg: FunctionCFGData,
    rd: ReachingDefsResult,
    lv: LiveVarsResult,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    
    INT_MIN = -2147483648
    INT_MAX = 2147483647
    
    # Walk the function body to find BINARY_OPERATOR
    for sub_c in walk_cursor(cfg.cursor):
        if sub_c.kind.name == "BINARY_OPERATOR":
            # Extract operator
            op = None
            try:
                for tok in sub_c.get_tokens():
                    if tok.spelling in ("+", "-", "*", "<<"):
                        op = tok.spelling
                        break
            except Exception:
                pass
                
            if op in ("+", "-", "*", "<<"):
                children = list(sub_c.get_children())
                if len(children) == 2:
                    lhs, rhs = children
                    val1 = get_int_value(lhs)
                    val2 = get_int_value(rhs)
                    
                    if val1 is not None and val2 is not None:
                        res = None
                        if op == "+":
                            res = val1 + val2
                        elif op == "-":
                            res = val1 - val2
                        elif op == "*":
                            res = val1 * val2
                        elif op == "<<":
                            # Prevent huge shifts from overflowing Python itself or taking forever
                            if 0 <= val2 < 64:
                                res = val1 << val2
                                
                        if res is not None:
                            if res < INT_MIN or res > INT_MAX:
                                diags.append(
                                    mk_diag(
                                        category="int_overflow",
                                        severity="error",
                                        cursor=sub_c,
                                        message=f"Signed integer overflow: {val1} {op} {val2} results in {res}, which is outside of [INT_MIN, INT_MAX]",
                                        cfg_node_id=None
                                    )
                                )
                                
    return diags
