"""POST /api/cfg — parse source and return Cytoscape-compatible CFG JSON.

Response payload (FunctionCFG) is grouped per function so the frontend can
render multiple functions on one canvas or in a tabbed view. Each node carries
the statement text and source lines for cross-referencing with the editor.
"""

from __future__ import annotations

import time
from pathlib import Path

from clang import cindex
from fastapi import APIRouter, HTTPException

from ..analyzer import build_cfgs, parse_source
from ..schemas import CFGEdge, CFGNode, CFGRequest, CFGResponse, CFGStatement, FunctionCFG

router = APIRouter(prefix="/api", tags=["cfg"])


@router.post("/cfg", response_model=CFGResponse)
def cfg(req: CFGRequest) -> CFGResponse:
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="code is empty")

    t0 = time.perf_counter()
    try:
        parsed = parse_source(req.code, language=req.language, filename=req.filename)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"parser failure: {exc}") from exc

    src_filename = Path(parsed.source_path).name
    cfgs_internal = build_cfgs(parsed.tu, src_filename=src_filename)
    if req.function:
        cfgs_internal = [c for c in cfgs_internal if c.name == req.function]

    out_cfgs = [_serialize(c) for c in cfgs_internal]
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return CFGResponse(
        ok=True,
        cfgs=out_cfgs,
        parse_errors=parsed.errors,
        elapsed_ms=round(elapsed_ms, 2),
    )


def _serialize(fcfg) -> FunctionCFG:
    nodes: list[CFGNode] = []
    for _, data in fcfg.graph.nodes(data=True):
        b = data["block"]
        statements = [_stmt_to_payload(s) for s in b.statements]
        nodes.append(
            CFGNode(
                id=b.id,
                kind=b.kind,
                label=b.label,
                statements=statements,
                start_line=b.start_line,
                end_line=b.end_line,
            )
        )

    edges = [
        CFGEdge(source=src, target=dst, label=data.get("label", ""))
        for src, dst, data in fcfg.graph.edges(data=True)
    ]

    return FunctionCFG(
        function=fcfg.name,
        entry=fcfg.entry,
        exit=fcfg.exit,
        nodes=nodes,
        edges=edges,
    )


def _stmt_to_payload(cursor: cindex.Cursor) -> CFGStatement:
    ext = cursor.extent
    text = _cursor_text(cursor)
    return CFGStatement(
        kind=cursor.kind.name,
        text=text,
        line=ext.start.line or 0,
        column=ext.start.column or 0,
        end_line=ext.end.line or 0,
        end_column=ext.end.column or 0,
    )


def _cursor_text(cursor: cindex.Cursor) -> str:
    """Reconstruct the source slice for a cursor by joining its tokens."""
    try:
        toks = [t.spelling for t in cursor.get_tokens()]
    except Exception:  # noqa: BLE001
        return cursor.spelling or cursor.kind.name
    text = " ".join(toks)
    # Clip absurdly long expressions (e.g. macro expansions) for UI sanity.
    if len(text) > 160:
        text = text[:157] + "..."
    return text or cursor.spelling or cursor.kind.name
