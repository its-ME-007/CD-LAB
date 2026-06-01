"""Pydantic models shared between analyzer, routes, and frontend.

The `Diagnostic` model is the contract that frontend and backend agree on
in Phase 1 — keep changes here backward compatible after Day 1.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["error", "warning", "info"]

UBCategory = Literal[
    "null_deref",
    "use_after_free",
    "oob",
    "uninit",
    "div_zero",
    "int_overflow",
    "dangling",
    "parse_error",
]


class SourceRange(BaseModel):
    line: int = Field(..., ge=1)
    column: int = Field(..., ge=1)
    end_line: int = Field(..., ge=1)
    end_column: int = Field(..., ge=1)


class Diagnostic(BaseModel):
    id: str
    category: UBCategory
    severity: Severity
    range: SourceRange
    message: str
    explanation: str | None = None
    fix_suggestion: str | None = None
    cfg_node_id: str | None = None
    llvm_evidence: list[str] | None = None
    # 1-based line numbers into `LLVMIR.ir`, aligned 1:1 with `llvm_evidence`,
    # so the UI can scroll the IR viewer to the instruction backing each
    # evidence row (click-to-jump). None when no IR/evidence is available.
    llvm_evidence_lines: list[int] | None = None
    # 2-3 plain-text bullets from the AST/CFG/dataflow detector describing
    # *why* this code was flagged. Distinct from llvm_evidence (which is the
    # downstream IR artefact). Populated by each detector at mk_diag time.
    reasoning: list[str] | None = None


class ASTNode(BaseModel):
    kind: str
    spelling: str | None = None
    type: str | None = None
    range: SourceRange | None = None
    children: list["ASTNode"] = Field(default_factory=list)


ASTNode.model_rebuild()


class AnalyzeRequest(BaseModel):
    code: str
    language: Literal["c", "cpp"] = "cpp"
    filename: str | None = None


class IRMetrics(BaseModel):
    functions: int = 0
    basic_blocks: int = 0
    instructions: int = 0
    memory_ops: int = 0
    arithmetic_ops: int = 0


class LLVMIR(BaseModel):
    ok: bool
    ir: str | None = None
    error: str | None = None
    metrics: IRMetrics | None = None


class AnalyzeResponse(BaseModel):
    ok: bool
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    ast: ASTNode | None = None
    parse_errors: list[str] = Field(default_factory=list)
    llvm_ir: LLVMIR | None = None
    elapsed_ms: float = 0.0


class CFGStatement(BaseModel):
    kind: str
    text: str
    line: int
    column: int
    end_line: int
    end_column: int


class CFGNode(BaseModel):
    id: str
    kind: Literal[
        "entry", "exit", "stmt", "cond", "loop_header",
        "return", "break", "continue",
    ]
    label: str
    statements: list[CFGStatement] = Field(default_factory=list)
    start_line: int | None = None
    end_line: int | None = None


class CFGEdge(BaseModel):
    source: str
    target: str
    label: str = ""  # "T" / "F" / "back" / "" (fallthrough)


class FunctionCFG(BaseModel):
    function: str
    entry: str
    exit: str
    nodes: list[CFGNode] = Field(default_factory=list)
    edges: list[CFGEdge] = Field(default_factory=list)


class CFGRequest(BaseModel):
    code: str
    language: Literal["c", "cpp"] = "cpp"
    filename: str | None = None
    function: str | None = None  # optional filter; default = all functions


class CFGResponse(BaseModel):
    ok: bool
    cfgs: list[FunctionCFG] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    elapsed_ms: float = 0.0


class ExplainRequest(BaseModel):
    diagnostic: Diagnostic
    code: str
    context_lines: int = 3


class ExplainResponse(BaseModel):
    ok: bool
    explanation: str | None = None
    fix_suggestion: str | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    libclang_loaded: bool
    libclang_path: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)
