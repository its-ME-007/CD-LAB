"""POST /analyze — parse source, return AST + diagnostics.

Phase 1: only the parser runs; the diagnostics list is empty unless libclang
itself emits parse errors (those are surfaced separately via `parse_errors`).
Phase 2+ wires the CFG/dataflow/detectors pipeline.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from ..analyzer import parse_source
from ..schemas import AnalyzeRequest, AnalyzeResponse

router = APIRouter(prefix="/api", tags=["analyze"])


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="code is empty")

    t0 = time.perf_counter()
    try:
        result = parse_source(req.code, language=req.language, filename=req.filename)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"parser failure: {exc}") from exc

    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Phase 2+ will populate diagnostics from detectors.
    return AnalyzeResponse(
        ok=True,
        diagnostics=[],
        ast=result.ast,
        parse_errors=result.errors,
        elapsed_ms=round(elapsed_ms, 2),
    )
