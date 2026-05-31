"""FastAPI route for explaining static analysis diagnostics via Groq."""

from __future__ import annotations

from fastapi import APIRouter
from ..llm.client import explain_diagnostic
from ..schemas import ExplainRequest, ExplainResponse

router = APIRouter(prefix="/api", tags=["explain"])

@router.post("/explain", response_model=ExplainResponse)
def explain(req: ExplainRequest) -> ExplainResponse:
    try:
        # Extract source code lines around the diagnostic
        lines = req.code.splitlines()
        diag_line = req.diagnostic.range.line
        
        # Gather context lines
        start_idx = max(1, diag_line - req.context_lines)
        end_idx = min(len(lines), req.diagnostic.range.end_line + req.context_lines)
        
        # Build the slice with 1-based line annotations for LLM context
        snippet_lines = []
        for idx in range(start_idx, end_idx + 1):
            line_val = lines[idx - 1]
            # Highlight the exact diagnostic line with a marker if it fits
            if idx == diag_line:
                snippet_lines.append(f"{idx}: {line_val}  <-- {req.diagnostic.message}")
            else:
                snippet_lines.append(f"{idx}: {line_val}")
                
        snippet = "\n".join(snippet_lines)
        
        explanation, fix_suggestion = explain_diagnostic(
            category=req.diagnostic.category,
            message=req.diagnostic.message,
            code_snippet=snippet,
            start_line=start_idx,
            end_line=end_idx,
        )
        
        return ExplainResponse(
            ok=True,
            explanation=explanation,
            fix_suggestion=fix_suggestion,
        )
    except Exception as exc:
        return ExplainResponse(
            ok=False,
            error=str(exc),
        )
