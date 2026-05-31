"""Shared static analysis helper functions for AST traversal, null constants, and diagnostics."""

from __future__ import annotations

import uuid
from typing import Iterator
from clang import cindex
from ..schemas import Diagnostic, SourceRange

def walk_cursor(cursor: cindex.Cursor) -> Iterator[cindex.Cursor]:
    """Perform a pre-order depth-first traversal of the cursor AST."""
    yield cursor
    for child in cursor.get_children():
        yield from walk_cursor(child)

def is_null_constant(cursor: cindex.Cursor) -> bool:
    """Check if the cursor represents a null constant (0, NULL, nullptr)."""
    cur = cursor
    while True:
        kind = cur.kind.name
        if kind in ("UNEXPOSED_EXPR", "CSTYLE_CAST_EXPR", "PAREN_EXPR", "IMPLICIT_CAST_EXPR"):
            ch = list(cur.get_children())
            if not ch:
                break
            cur = ch[0]
        else:
            break
            
    kind = cur.kind.name
    if kind == "CXX_NULL_PTR_LITERAL_EXPR":
        return True
    if kind == "INTEGER_LITERAL":
        if cur.spelling == "0":
            return True
        try:
            tokens = list(cur.get_tokens())
            if tokens and tokens[0].spelling in ("0", "NULL", "nullptr"):
                return True
        except Exception:
            pass
    if cur.spelling in ("0", "NULL", "nullptr"):
        return True
    return False

def _lvalue_name(cursor: cindex.Cursor) -> str | None:
    """If cursor is a simple variable reference, return its spelling."""
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

def is_arrow_member_ref(cursor: cindex.Cursor) -> bool:
    """Return True if the member reference uses pointer indirection (->)."""
    try:
        return any(t.spelling == "->" for t in cursor.get_tokens())
    except Exception:
        return False

def mk_diag(
    category: str,
    severity: str,
    cursor: cindex.Cursor,
    message: str,
    cfg_node_id: str | None = None
) -> Diagnostic:
    """Construct a Pydantic Diagnostic object from a Cursor."""
    ext = cursor.extent
    # Fallback to cursor location if extent is invalid
    start_line = ext.start.line if ext and ext.start.line else cursor.location.line or 1
    start_col = ext.start.column if ext and ext.start.column else cursor.location.column or 1
    end_line = ext.end.line if ext and ext.end.line else start_line
    end_col = ext.end.column if ext and ext.end.column else start_col
    
    return Diagnostic(
        id=uuid.uuid4().hex,
        category=category,
        severity=severity,
        range=SourceRange(
            line=start_line,
            column=start_col,
            end_line=end_line,
            end_column=end_col
        ),
        message=message,
        cfg_node_id=cfg_node_id
    )
