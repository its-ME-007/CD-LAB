from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..analyzer import (
    build_cfgs,
    live_variables,
    parse_source,
    reaching_definitions,
    run_all,
)
from ..schemas import AnalyzeRequest, AnalyzeResponse

router = APIRouter(prefix="/api", tags=["analyze"])


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="code is empty")

    t0 = time.perf_counter()
    try:
        result = parse_source(req.code, language=req.language, filename=req.filename)
        
        src_filename = Path(result.source_path).name
        cfgs = build_cfgs(result.tu, src_filename=src_filename)
        rds = [reaching_definitions(c) for c in cfgs]
        lvs = [live_variables(c) for c in cfgs]
        diagnostics = run_all(result.tu, cfgs, rds, lvs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"parser/detector failure: {exc}") from exc

    elapsed_ms = (time.perf_counter() - t0) * 1000

    return AnalyzeResponse(
        ok=True,
        diagnostics=diagnostics,
        ast=result.ast,
        parse_errors=result.errors,
        elapsed_ms=round(elapsed_ms, 2),
    )


@router.get("/samples")
def get_samples() -> list[dict[str, str]]:
    import os
    samples_dir = Path(__file__).resolve().parent.parent.parent / "samples"
    out = []
    if samples_dir.exists():
        for filename in sorted(os.listdir(samples_dir)):
            p = samples_dir / filename
            if p.is_file() and (filename.endswith(".c") or filename.endswith(".cpp")):
                try:
                    out.append({
                        "name": filename,
                        "content": p.read_text(encoding="utf-8")
                    })
                except Exception:
                    pass
    return out


