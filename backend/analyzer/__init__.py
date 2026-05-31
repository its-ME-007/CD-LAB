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
from .parser import libclang_status, parse_source
from .detectors import run_all

__all__ = [
    "BasicBlock",
    "Definition",
    "FunctionCFGData",
    "LiveVarsResult",
    "ReachingDefsResult",
    "build_cfgs",
    "extract_def_use",
    "libclang_status",
    "live_variables",
    "parse_source",
    "reaching_definitions",
    "run_all",
]

