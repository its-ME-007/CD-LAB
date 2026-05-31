"""LLVM IR generation tests.

These tests shell out to the real `clang` binary on PATH. If clang isn't
installed they auto-skip — CI / teammates without LLVM won't be broken.
"""

from __future__ import annotations

import pytest

from backend.analyzer.llvm_ir import clang_available, generate_llvm_ir


_HAS_CLANG, _CLANG_PATH = clang_available()
needs_clang = pytest.mark.skipif(
    not _HAS_CLANG,
    reason="clang CLI not installed; LLVM IR tests require it on PATH",
)


def test_clang_available_returns_tuple():
    ok, path = clang_available()
    assert isinstance(ok, bool)
    assert path is None or isinstance(path, str)


def test_missing_clang_produces_friendly_error(monkeypatch):
    # Force the lookup to fail so we exercise the no-clang branch
    # regardless of the host's LLVM install.
    import backend.analyzer.llvm_ir as mod

    monkeypatch.setattr(mod, "_find_clang", lambda lang: None)
    result = generate_llvm_ir("int main(){return 0;}", language="c")
    assert result.ok is False
    assert result.ir is None
    assert result.error and "clang" in result.error.lower()


@needs_clang
def test_generate_ir_for_trivial_c():
    result = generate_llvm_ir("int add(int a, int b){return a+b;}", language="c")
    assert result.ok, result.error
    assert result.ir is not None
    # Standard markers in any clang-emitted .ll
    assert "define" in result.ir
    assert "@add" in result.ir


@needs_clang
def test_generate_ir_for_trivial_cpp():
    code = """
    int square(int x) {
        return x * x;
    }
    int main() {
        return square(5);
    }
    """
    result = generate_llvm_ir(code, language="cpp")
    assert result.ok, result.error
    assert result.ir is not None
    assert "@main" in result.ir
    # Function names are mangled in C++; just check `square` is somewhere.
    assert "square" in result.ir


@needs_clang
def test_invalid_code_returns_ok_false_with_error():
    # Missing semicolon → clang exits non-zero. Should NOT raise.
    result = generate_llvm_ir("int main(){int x = ; return 0;}", language="c")
    assert result.ok is False
    assert result.ir is None
    assert result.error  # non-empty
