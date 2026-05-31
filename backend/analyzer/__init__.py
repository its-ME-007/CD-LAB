"""Static analysis pipeline: parser → cfg → dataflow → detectors."""

from .cfg import BasicBlock, FunctionCFGData, build_cfgs
from .dataflow import (
    Definition,
    LiveVarsResult,
    ReachingDefsResult,
    extract_def_use,
    live_variables,
    reaching_definitions,
)
from .llvm_ir import IRResult, clang_available, generate_llvm_ir
from .parser import libclang_status, parse_source
from .detectors import run_all

__all__ = [
    "BasicBlock",
    "Definition",
    "FunctionCFGData",
    "IRResult",
    "LiveVarsResult",
    "ReachingDefsResult",
    "build_cfgs",
    "clang_available",
    "extract_def_use",
    "generate_llvm_ir",
    "libclang_status",
    "live_variables",
    "parse_source",
    "reaching_definitions",
    "run_all",
]

