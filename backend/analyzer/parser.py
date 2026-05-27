"""libclang wrapper: parse a C/C++ source string into a TranslationUnit
and a normalized AST suitable for JSON serialization.

Phase 1 goal: given source text, return (TranslationUnit, ASTNode tree,
parse-error list). Later phases (CFG, dataflow, detectors) reuse the
TranslationUnit handle; the JSON AST is for the frontend.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from clang import cindex

from ..schemas import ASTNode, SourceRange

_LIBCLANG_LOADED = False
_LIBCLANG_PATH: str | None = None


def _init_libclang() -> None:
    """Configure libclang once. Prefers $LIBCLANG_PATH; falls back to the
    `libclang` PyPI package's bundled binary (auto-discovered by cindex)."""
    global _LIBCLANG_LOADED, _LIBCLANG_PATH
    if _LIBCLANG_LOADED:
        return

    explicit = os.getenv("LIBCLANG_PATH", "").strip()
    if explicit:
        p = Path(explicit)
        if p.is_file():
            cindex.Config.set_library_file(str(p))
            _LIBCLANG_PATH = str(p)
        elif p.is_dir():
            cindex.Config.set_library_path(str(p))
            _LIBCLANG_PATH = str(p)

    # Touch Index() to force libclang load and surface errors early.
    cindex.Index.create()
    _LIBCLANG_LOADED = True
    if _LIBCLANG_PATH is None:
        # The `libclang` PyPI package patches cindex to find its bundled binary.
        try:
            import libclang  # noqa: F401

            _LIBCLANG_PATH = "<bundled libclang PyPI package>"
        except ImportError:
            _LIBCLANG_PATH = "<system default>"


def libclang_status() -> tuple[bool, str | None]:
    try:
        _init_libclang()
        return True, _LIBCLANG_PATH
    except Exception as exc:  # noqa: BLE001
        return False, f"load failed: {exc}"


@dataclass
class ParseResult:
    tu: cindex.TranslationUnit
    ast: ASTNode
    errors: list[str]
    source_path: str


def parse_source(code: str, language: str = "cpp", filename: str | None = None) -> ParseResult:
    """Parse a C/C++ source string.

    libclang requires a filename on disk for diagnostics to look natural,
    so we write to a temp file. The TU is returned with `cache_completion_results`
    off — we don't need completion, only AST + diagnostics.
    """
    _init_libclang()

    ext = ".cpp" if language == "cpp" else ".c"
    name = filename if filename and filename.endswith(ext) else f"input{ext}"

    with tempfile.TemporaryDirectory(prefix="cdlab_") as tmpdir:
        src_path = Path(tmpdir) / name
        src_path.write_text(code, encoding="utf-8")

        args = ["-std=c++17"] if language == "cpp" else ["-std=c11"]
        # -ferror-limit=0 → keep parsing past first error so we collect more diagnostics.
        args += ["-ferror-limit=0"]
        # Windows-specific: MSVC's STL static-asserts that the compiler is
        # Clang >= 19. The libclang PyPI wheel ships 18.1, so any `#include
        # <iostream>` etc. would explode in yvals_core.h. This macro is MSVC's
        # documented escape hatch and is harmless on non-Windows builds.
        if language == "cpp":
            args += ["-D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH"]

        index = cindex.Index.create()
        # Default parse options — we deliberately do NOT request
        # PARSE_DETAILED_PROCESSING_RECORD, because that pollutes the AST with
        # builtin macro definition cursors (__llvm__, __clang__, ...).
        tu = index.parse(str(src_path), args=args)

        errors = [
            f"{d.location.file.name if d.location.file else '?'}:"
            f"{d.location.line}:{d.location.column}: {d.spelling}"
            for d in tu.diagnostics
            if d.severity >= cindex.Diagnostic.Error
        ]

        ast = _cursor_to_node(tu.cursor, src_path.name)
        return ParseResult(tu=tu, ast=ast, errors=errors, source_path=str(src_path))


def _cursor_to_node(cursor: cindex.Cursor, src_filename: str, depth: int = 0) -> ASTNode:
    """Convert a libclang Cursor into a serializable ASTNode.

    Filters out children that come from system headers (only keep nodes whose
    location is in our temp source file). Caps recursion to keep payload bounded.
    """
    rng = _extract_range(cursor)
    spelling = cursor.spelling or None
    type_name = cursor.type.spelling if cursor.type and cursor.type.spelling else None

    children: list[ASTNode] = []
    if depth < 64:  # safety cap
        for child in cursor.get_children():
            loc_file = child.location.file
            # Keep TU root's direct children even when file info is missing
            # (some top-level cursors report None); for everything else, require
            # the location to live in our temp source file.
            if loc_file is None:
                if depth == 0:
                    children.append(_cursor_to_node(child, src_filename, depth + 1))
            elif Path(loc_file.name).name == src_filename:
                children.append(_cursor_to_node(child, src_filename, depth + 1))

    return ASTNode(
        kind=cursor.kind.name,
        spelling=spelling,
        type=type_name,
        range=rng,
        children=children,
    )


def _extract_range(cursor: cindex.Cursor) -> SourceRange | None:
    ext = cursor.extent
    if ext is None or ext.start.line == 0:
        return None
    return SourceRange(
        line=ext.start.line,
        column=ext.start.column,
        end_line=ext.end.line or ext.start.line,
        end_column=ext.end.column or ext.start.column,
    )
