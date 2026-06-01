"""LLVM IR introspection — parse a `.ll` (text) module into structured records
so we can attach low-level evidence to diagnostics and compute module metrics.

Design choices:
- **Regex only.** No llvmlite, no LLVM Python bindings. The IR we parse is
  always `clang -O0` output, which is highly regular and easy to walk
  line-by-line. This keeps the dependency footprint at zero.
- **Two passes.** First sweep collects `!DILocation` metadata so we know
  `(metadata_id → source_line)`. Second sweep walks instructions and
  resolves each instruction's trailing `, !dbg !X` reference into a source
  line. Without `-g` the lookup just returns `None` and we fall back to
  function-level evidence.
- **Coarse instruction model.** We only care about the opcode kind and
  the raw textual line. We don't parse operand types or values — the
  detectors are AST-based; this module exists to ANNOTATE their
  diagnostics, not to drive new analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Instruction opcodes we extract. Anything else (alloca, ret, br, call …)
# is counted toward the total but not surfaced as evidence.
_MEMORY_KINDS = {"load", "store", "getelementptr"}
_ARITH_KINDS = {"add", "sub", "mul", "sdiv", "udiv", "shl"}
_KNOWN_KINDS = _MEMORY_KINDS | _ARITH_KINDS

# Map diagnostic category → relevant IR instruction kinds.
# Keys match the literals in `backend/schemas.py::UBCategory`.
CATEGORY_TO_KINDS: dict[str, set[str]] = {
    "null_deref":     {"load", "store"},
    "use_after_free": {"load", "store"},
    "dangling":       {"load", "store"},
    "oob":            {"getelementptr", "load", "store"},
    "uninit":         {"load"},
    "div_zero":       {"sdiv", "udiv"},
    "int_overflow":   {"add", "sub", "mul", "shl"},
}

_RE_FUNC_DEF = re.compile(r"^\s*define\s+(?:[^@]*\s)?@([A-Za-z0-9_.$]+)\s*\(")
_RE_DILOC    = re.compile(r"^!(\d+)\s*=\s*!DILocation\(line:\s*(\d+)")
_RE_LABEL    = re.compile(r"^[A-Za-z0-9_.$]+:\s*(;.*)?$")
_RE_OPCODE   = re.compile(r"^(?:%[A-Za-z0-9_.$]+\s*=\s*)?([A-Za-z]+)\b")
_RE_DBG_REF  = re.compile(r"!dbg\s+!(\d+)")


@dataclass(frozen=True)
class IRInstruction:
    kind: str            # e.g. "load", "sdiv"
    text: str            # raw .ll line (trimmed, no trailing comma+dbg)
    function: str        # containing function name (no @ prefix)
    dbg_line: int | None # source line via !dbg → !DILocation, else None
    ir_line: int         # 1-based line number within the .ll text (for click-to-jump)


@dataclass
class IRMetrics:
    functions: int = 0
    basic_blocks: int = 0
    instructions: int = 0
    memory_ops: int = 0
    arithmetic_ops: int = 0


@dataclass
class ParsedIR:
    instructions: list[IRInstruction] = field(default_factory=list)
    metrics: IRMetrics = field(default_factory=IRMetrics)
    # (function, source_line) → list of instructions hit at that pair.
    # Populated only when -g was supplied.
    by_function_line: dict[tuple[str, int], list[IRInstruction]] = field(default_factory=dict)
    # function → list of all instructions (preserves order). Used as the
    # fallback evidence source when source-line resolution fails.
    by_function: dict[str, list[IRInstruction]] = field(default_factory=dict)


def parse_ir(ir_text: str) -> ParsedIR:
    """Parse an LLVM IR text module. Tolerates missing debug metadata."""
    if not ir_text:
        return ParsedIR()

    di_locs: dict[int, int] = {}
    instructions: list[IRInstruction] = []
    metrics = IRMetrics()
    by_func_line: dict[tuple[str, int], list[IRInstruction]] = {}
    by_func: dict[str, list[IRInstruction]] = {}

    # Pass 1: collect !DILocation metadata. We do this in a single linear
    # scan even though metadata typically lives at the bottom — keeps the
    # function tiny.
    for line in ir_text.splitlines():
        m = _RE_DILOC.match(line.strip())
        if m:
            di_locs[int(m.group(1))] = int(m.group(2))

    # Pass 2: walk function bodies. We track brace depth conservatively;
    # in practice -O0 output never nests, but the depth counter is robust
    # against weird module-level metadata that happens to contain '{'.
    current_func: str | None = None
    brace_depth = 0

    # `ir_line_no` is the 1-based line number in the raw .ll text. We keep it
    # on every IRInstruction so the frontend can scroll the IR viewer to the
    # exact instruction backing a diagnostic (click-to-jump).
    for ir_line_no, raw in enumerate(ir_text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith(";"):
            continue

        # Function definition opens
        if current_func is None:
            m = _RE_FUNC_DEF.match(raw)
            if m and "{" in raw:
                current_func = m.group(1)
                brace_depth = 1
                metrics.functions += 1
                metrics.basic_blocks += 1  # implicit entry block
                continue

        if current_func is None:
            continue

        # Inside a function body
        if stripped == "}":
            brace_depth -= 1
            if brace_depth == 0:
                current_func = None
            continue

        if _RE_LABEL.match(stripped):
            metrics.basic_blocks += 1
            continue

        # Detect opcode
        op_match = _RE_OPCODE.match(stripped)
        if not op_match:
            continue
        opcode = op_match.group(1)
        metrics.instructions += 1

        if opcode not in _KNOWN_KINDS:
            continue
        if opcode in _MEMORY_KINDS:
            metrics.memory_ops += 1
        if opcode in _ARITH_KINDS:
            metrics.arithmetic_ops += 1

        # Resolve !dbg → source line, if present.
        dbg_line: int | None = None
        dbg_match = _RE_DBG_REF.search(stripped)
        if dbg_match:
            dbg_line = di_locs.get(int(dbg_match.group(1)))

        # Strip trailing ", !dbg !N" so the displayed text isn't noisy.
        display = _strip_trailing_dbg(stripped)

        ins = IRInstruction(
            kind=opcode,
            text=display,
            function=current_func,
            dbg_line=dbg_line,
            ir_line=ir_line_no,
        )
        instructions.append(ins)
        by_func.setdefault(current_func, []).append(ins)
        if dbg_line is not None:
            by_func_line.setdefault((current_func, dbg_line), []).append(ins)

    return ParsedIR(
        instructions=instructions,
        metrics=metrics,
        by_function_line=by_func_line,
        by_function=by_func,
    )


def evidence_instrs_for(
    parsed: ParsedIR,
    function: str | None,
    line: int | None,
    category: str,
    *,
    limit: int = 3,
) -> list[IRInstruction]:
    """Return up to `limit` IR instructions relevant to a diagnostic.

    Priority:
    1. If we have `(function, line)` and a non-empty hit — return those.
    2. Else if we have `function` — return all relevant kinds in that
       function (capped at limit).
    3. Else — return [].

    Returns the full `IRInstruction` records so callers can read both the
    display `text` and the `ir_line` (used for click-to-jump). For just the
    text, see `evidence_for`.
    """
    kinds = CATEGORY_TO_KINDS.get(category)
    if not kinds:
        return []

    # Tier 1: exact source-line evidence (requires -g).
    if function and line is not None:
        hits = parsed.by_function_line.get((function, line), [])
        relevant = [ins for ins in hits if ins.kind in kinds]
        if relevant:
            return relevant[:limit]

    # Tier 2: function-level fallback.
    if function and function in parsed.by_function:
        relevant = [ins for ins in parsed.by_function[function] if ins.kind in kinds]
        return relevant[:limit]

    return []


def evidence_for(
    parsed: ParsedIR,
    function: str | None,
    line: int | None,
    category: str,
    *,
    limit: int = 3,
) -> list[str]:
    """Return up to `limit` IR instruction *texts* relevant to a diagnostic.

    Thin wrapper over `evidence_instrs_for` preserved for callers (and tests)
    that only need the textual lines.
    """
    return [ins.text for ins in evidence_instrs_for(parsed, function, line, category, limit=limit)]


def _strip_trailing_dbg(line: str) -> str:
    """Remove a trailing `, !dbg !N` (with surrounding whitespace).

    The IR viewer already shows the raw `.ll`; the evidence panel is a
    *summary* so dropping the metadata keeps it readable.
    """
    return re.sub(r",\s*!dbg\s+!\d+\s*$", "", line).rstrip()
