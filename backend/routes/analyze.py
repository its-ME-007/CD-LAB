from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..analyzer import (
    build_cfgs,
    generate_llvm_ir,
    live_variables,
    parse_source,
    reaching_definitions,
    run_all,
)
from ..analyzer.ir_introspect import evidence_instrs_for, parse_ir
from ..schemas import AnalyzeRequest, AnalyzeResponse, IRMetrics, LLVMIR

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

    # LLVM IR is a "supporting compiler artifact" — never fatal to /analyze.
    # If clang is missing or codegen fails (e.g. user pasted invalid source),
    # we surface ok=False + a message in the IR tab and continue.
    ir_result = generate_llvm_ir(req.code, language=req.language)

    # Introspect the IR (regex parser) so we can both (a) attach LLVM
    # evidence to each diagnostic and (b) report module-level metrics.
    # Failures here are silently downgraded — IR is a courtesy artifact.
    metrics_model: IRMetrics | None = None
    if ir_result.ok and ir_result.ir:
        try:
            parsed = parse_ir(ir_result.ir)
            metrics_model = IRMetrics(
                functions=parsed.metrics.functions,
                basic_blocks=parsed.metrics.basic_blocks,
                instructions=parsed.metrics.instructions,
                memory_ops=parsed.metrics.memory_ops,
                arithmetic_ops=parsed.metrics.arithmetic_ops,
            )
            # Attach evidence to each diagnostic. The function name is
            # encoded in cfg_node_id as "<funcname>#<n>" (see
            # analyzer/cfg.py::_CFGBuilder._new_block).
            for d in diagnostics:
                func = d.cfg_node_id.split("#", 1)[0] if d.cfg_node_id else None
                instrs = evidence_instrs_for(parsed, func, d.range.line, d.category)
                if instrs:
                    d.llvm_evidence = [i.text for i in instrs]
                    d.llvm_evidence_lines = [i.ir_line for i in instrs]
        except Exception:  # noqa: BLE001
            # Don't let an IR-parse hiccup break the analyze endpoint.
            metrics_model = None

    llvm_ir = LLVMIR(
        ok=ir_result.ok,
        ir=ir_result.ir,
        error=ir_result.error,
        metrics=metrics_model,
    )

    elapsed_ms = (time.perf_counter() - t0) * 1000

    return AnalyzeResponse(
        ok=True,
        diagnostics=diagnostics,
        ast=result.ast,
        parse_errors=result.errors,
        llvm_ir=llvm_ir,
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


