"""Tests for the LLVM IR regex-introspection module."""

from __future__ import annotations

import pytest

from backend.analyzer.ir_introspect import (
    CATEGORY_TO_KINDS,
    evidence_for,
    evidence_instrs_for,
    parse_ir,
)
from backend.analyzer.llvm_ir import clang_available, generate_llvm_ir

_HAS_CLANG, _ = clang_available()
needs_clang = pytest.mark.skipif(not _HAS_CLANG, reason="clang CLI required")

# Hand-written -O0 IR snippet mimicking `clang -g` output for a function
# that does a null deref + a signed division. Used to test the parser
# without depending on a real clang invocation.
_SAMPLE_IR_WITH_DBG = """\
; ModuleID = 'sample.c'
source_filename = "sample.c"

define dso_local i32 @demo(i32 %a, i32 %b) #0 !dbg !4 {
  %1 = alloca i32, align 4
  %2 = alloca ptr, align 8
  store i32 0, ptr %1, align 4
  store ptr null, ptr %2, align 8, !dbg !10
  %3 = load ptr, ptr %2, align 8, !dbg !11
  store i32 5, ptr %3, align 4, !dbg !12
  %4 = load i32, ptr %1, align 4, !dbg !13
  %5 = sdiv i32 %4, 0, !dbg !13
  ret i32 %5, !dbg !14
}

declare void @some_external()

!10 = !DILocation(line: 3, column: 9, scope: !4)
!11 = !DILocation(line: 4, column: 13, scope: !4)
!12 = !DILocation(line: 4, column: 12, scope: !4)
!13 = !DILocation(line: 5, column: 11, scope: !4)
!14 = !DILocation(line: 6, column: 5, scope: !4)
"""


# ---------------------------------------------------------------------------
# parse_ir — structural correctness on synthetic input
# ---------------------------------------------------------------------------

def test_parse_extracts_function_and_metrics():
    parsed = parse_ir(_SAMPLE_IR_WITH_DBG)
    assert parsed.metrics.functions == 1
    # entry + 0 extra labels in this snippet → 1 basic block
    assert parsed.metrics.basic_blocks == 1
    # 8 non-label, non-brace instructions inside the function body
    # (3× alloca/store before !dbg, plus store/load/store/load/sdiv/ret)
    assert parsed.metrics.instructions >= 8
    assert parsed.metrics.memory_ops >= 2
    assert parsed.metrics.arithmetic_ops >= 1


def test_parse_resolves_dbg_lines():
    parsed = parse_ir(_SAMPLE_IR_WITH_DBG)
    # The sdiv on `!dbg !13` should resolve to source line 5.
    sdivs = [ins for ins in parsed.instructions if ins.kind == "sdiv"]
    assert len(sdivs) == 1
    assert sdivs[0].dbg_line == 5
    assert sdivs[0].function == "demo"


def test_parse_strips_trailing_dbg_from_text():
    parsed = parse_ir(_SAMPLE_IR_WITH_DBG)
    for ins in parsed.instructions:
        assert "!dbg" not in ins.text, f"unstripped: {ins.text!r}"


def test_parse_handles_ir_without_debug_info():
    # Same snippet, debug refs and DILocation entries stripped.
    minimal = """\
define dso_local i32 @bar() #0 {
  %1 = alloca i32, align 4
  store i32 0, ptr %1, align 4
  %2 = load i32, ptr %1, align 4
  ret i32 %2
}
"""
    parsed = parse_ir(minimal)
    assert parsed.metrics.functions == 1
    assert all(ins.dbg_line is None for ins in parsed.instructions)


def test_parse_empty_input_is_safe():
    parsed = parse_ir("")
    assert parsed.metrics.functions == 0
    assert parsed.instructions == []


def test_parse_skips_declare_lines():
    parsed = parse_ir(_SAMPLE_IR_WITH_DBG)
    # `declare void @some_external()` must NOT count as a function.
    assert parsed.metrics.functions == 1


# ---------------------------------------------------------------------------
# evidence_for — category filtering and fallback tiers
# ---------------------------------------------------------------------------

def test_evidence_for_uses_line_when_available():
    parsed = parse_ir(_SAMPLE_IR_WITH_DBG)
    # null_deref → load/store. Line 4 has both a load + a store at !dbg.
    ev = evidence_for(parsed, function="demo", line=4, category="null_deref")
    assert ev, "expected at least one IR line"
    assert any("load" in s or "store" in s for s in ev)


def test_evidence_for_div_zero_hits_sdiv():
    parsed = parse_ir(_SAMPLE_IR_WITH_DBG)
    ev = evidence_for(parsed, function="demo", line=5, category="div_zero")
    assert any("sdiv" in s for s in ev), ev


def test_evidence_for_falls_back_to_function_level():
    # Same IR, but ask for a line that has no matching dbg entry.
    parsed = parse_ir(_SAMPLE_IR_WITH_DBG)
    ev = evidence_for(parsed, function="demo", line=999, category="null_deref")
    assert ev, "fallback should still return function-level instructions"


def test_evidence_for_unknown_category_returns_empty():
    parsed = parse_ir(_SAMPLE_IR_WITH_DBG)
    assert evidence_for(parsed, "demo", 4, category="not_a_category") == []


def test_evidence_for_respects_limit():
    parsed = parse_ir(_SAMPLE_IR_WITH_DBG)
    ev = evidence_for(parsed, "demo", None, category="null_deref", limit=1)
    assert len(ev) <= 1


def test_parse_records_ir_line_numbers():
    # ir_line is the 1-based line within the .ll text. The sdiv lives on
    # line 10 of _SAMPLE_IR_WITH_DBG (1: ModuleID, 2: source_filename,
    # 3: blank, 4: define, 5-9: body, 10: sdiv... count it explicitly).
    parsed = parse_ir(_SAMPLE_IR_WITH_DBG)
    lines = _SAMPLE_IR_WITH_DBG.splitlines()
    for ins in parsed.instructions:
        assert ins.ir_line >= 1
        # The recorded line, when stripped, must start with the same text
        # we stored (modulo the trailing !dbg we strip from `text`).
        raw = lines[ins.ir_line - 1].strip()
        assert raw.startswith(ins.text), (ins.ir_line, raw, ins.text)


def test_evidence_instrs_for_carries_ir_line():
    parsed = parse_ir(_SAMPLE_IR_WITH_DBG)
    instrs = evidence_instrs_for(parsed, "demo", 5, category="div_zero")
    assert instrs, "expected an sdiv instruction"
    assert all(i.ir_line >= 1 for i in instrs)
    # evidence_for must stay aligned with evidence_instrs_for (text-only view).
    texts = evidence_for(parsed, "demo", 5, category="div_zero")
    assert texts == [i.text for i in instrs]


def test_category_kinds_cover_every_ub_category():
    # Sanity: every category that the detectors emit should have a
    # CATEGORY_TO_KINDS mapping. parse_error is intentionally excluded.
    from backend.schemas import UBCategory  # type: ignore
    # UBCategory is a Literal — pull values via typing.get_args.
    from typing import get_args
    for cat in get_args(UBCategory):
        if cat == "parse_error":
            continue
        assert cat in CATEGORY_TO_KINDS, f"missing kinds map for {cat}"


# ---------------------------------------------------------------------------
# End-to-end against real clang (skip-if-missing)
# ---------------------------------------------------------------------------

@needs_clang
def test_end_to_end_real_clang_round_trip():
    """Generate IR for a real snippet, parse it, confirm dbg_lines pin to
    plausible source lines and that evidence_for finds a `sdiv`."""
    code = """\
int divide(int a) {
    return a / 0;
}
int main() { return divide(7); }
"""
    ir = generate_llvm_ir(code, language="c")
    assert ir.ok, ir.error

    parsed = parse_ir(ir.ir)
    assert parsed.metrics.functions >= 2  # divide + main
    sdivs = [i for i in parsed.instructions if i.kind == "sdiv"]
    assert sdivs, "expected at least one sdiv in the IR"
    # dbg_lines should land on lines 1..3 of our source (function body of `divide`).
    assert any(i.dbg_line in (1, 2, 3) for i in sdivs), [i.dbg_line for i in sdivs]
