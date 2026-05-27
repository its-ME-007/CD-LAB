"""Phase 1 smoke tests for the libclang wrapper."""

from __future__ import annotations

from backend.analyzer import libclang_status, parse_source


def test_libclang_loads():
    loaded, info = libclang_status()
    assert loaded, f"libclang failed to load: {info}"


def test_parse_trivial_main():
    result = parse_source("int main(void){return 0;}", language="c")
    assert result.tu is not None
    assert result.ast.kind == "TRANSLATION_UNIT"
    assert result.errors == []
    # Expect at least one child cursor that represents `main`.
    kinds = [c.kind for c in result.ast.children]
    assert any("FUNCTION_DECL" in k for k in kinds), kinds


def test_parse_with_syntax_error_collects_errors():
    bad = "int main(void) { int x = ; return 0; }"  # missing rhs
    result = parse_source(bad, language="c")
    assert result.errors, "expected at least one parse error"
