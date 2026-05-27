"""Unit tests for the 7 Undefined Behavior static detectors."""

from __future__ import annotations

from backend.analyzer import (
    build_cfgs,
    live_variables,
    parse_source,
    reaching_definitions,
    run_all,
)

def _diagnostics_for(code: str, language: str = "cpp") -> list:
    parsed = parse_source(code, language=language)
    cfgs = build_cfgs(parsed.tu, src_filename=None)
    rds = [reaching_definitions(c) for c in cfgs]
    lvs = [live_variables(c) for c in cfgs]
    return run_all(parsed.tu, cfgs, rds, lvs)

def test_null_pointer_dereference():
    # True positive null dereference
    code = """
    void test() {
        int *p = 0;
        *p = 42;
    }
    """
    diags = _diagnostics_for(code)
    null_diags = [d for d in diags if d.category == "null_deref"]
    assert len(null_diags) >= 1
    assert "null pointer" in null_diags[0].message.lower()

    # Reassigned pointer (should NOT trigger)
    code_ok = """
    void test() {
        int x = 42;
        int *p = 0;
        p = &x;
        *p = 10;
    }
    """
    diags_ok = _diagnostics_for(code_ok)
    null_diags_ok = [d for d in diags_ok if d.category == "null_deref"]
    assert len(null_diags_ok) == 0

def test_uninitialized_variable():
    # True positive use of uninitialized variable
    code = """
    int test() {
        int x;
        int y = x + 1;
        return y;
    }
    """
    diags = _diagnostics_for(code)
    uninit_diags = [d for d in diags if d.category == "uninit"]
    assert len(uninit_diags) >= 1
    assert "uninitialized" in uninit_diags[0].message.lower()

    # Initialized variable (should NOT trigger)
    code_ok = """
    int test() {
        int x = 10;
        int y = x + 1;
        return y;
    }
    """
    diags_ok = _diagnostics_for(code_ok)
    uninit_diags_ok = [d for d in diags_ok if d.category == "uninit"]
    assert len(uninit_diags_ok) == 0

def test_division_by_zero():
    # True positive literal division by zero
    code = """
    int test() {
        return 10 / 0;
    }
    """
    diags = _diagnostics_for(code)
    div_diags = [d for d in diags if d.category == "div_zero"]
    assert len(div_diags) >= 1

    # True positive variable division by zero
    code_var = """
    int test() {
        int x = 0;
        return 10 / x;
    }
    """
    diags_var = _diagnostics_for(code_var)
    div_diags_var = [d for d in diags_var if d.category == "div_zero"]
    assert len(div_diags_var) >= 1

def test_use_after_free():
    # True positive use after free
    code = """
    #include <stdlib.h>
    void test() {
        int *p = (int*)malloc(sizeof(int));
        free(p);
        *p = 10;
    }
    """
    diags = _diagnostics_for(code)
    uaf_diags = [d for d in diags if d.category == "use_after_free"]
    assert len(uaf_diags) >= 1
    assert "freed" in uaf_diags[0].message.lower()

    # Reassigned after free (should NOT trigger)
    code_ok = """
    #include <stdlib.h>
    void test() {
        int *p = (int*)malloc(sizeof(int));
        free(p);
        p = 0;
    }
    """
    diags_ok = _diagnostics_for(code_ok)
    uaf_diags_ok = [d for d in diags_ok if d.category == "use_after_free"]
    assert len(uaf_diags_ok) == 0

def test_dangling_pointer():
    # True positive returning address of local stack variable
    code = """
    int* test() {
        int x = 10;
        return &x;
    }
    """
    diags = _diagnostics_for(code)
    dangling_diags = [d for d in diags if d.category == "dangling"]
    assert len(dangling_diags) >= 1
    assert "stack variable" in dangling_diags[0].message.lower()

def test_out_of_bounds_access():
    # True positive out of bounds access
    code = """
    void test() {
        int arr[5];
        arr[10] = 42;
    }
    """
    diags = _diagnostics_for(code)
    oob_diags = [d for d in diags if d.category == "oob"]
    assert len(oob_diags) >= 1
    assert "out of bounds" in oob_diags[0].message.lower()

def test_integer_overflow():
    # True positive signed integer overflow
    code = """
    void test() {
        int x = 2147483640 + 10;
    }
    """
    diags = _diagnostics_for(code)
    overflow_diags = [d for d in diags if d.category == "int_overflow"]
    assert len(overflow_diags) >= 1
    assert "overflow" in overflow_diags[0].message.lower()
