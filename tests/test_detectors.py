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


# ---------------------------------------------------------------------------
# C++-specific idioms: nullptr, new/delete, delete[], references.
# These exercise the same detectors through C++-only syntax that the
# C-centric tests above don't cover.
# ---------------------------------------------------------------------------

def test_cpp_nullptr_dereference():
    # TP: pointer initialised to nullptr and dereferenced.
    code = """
    void test() {
        int* p = nullptr;
        *p = 5;
    }
    """
    null_diags = [d for d in _diagnostics_for(code) if d.category == "null_deref"]
    assert len(null_diags) >= 1
    assert "null pointer" in null_diags[0].message.lower()

    # TN: nullptr reassigned to a valid address before use.
    code_ok = """
    void test() {
        int x = 42;
        int* p = nullptr;
        p = &x;
        *p = 5;
    }
    """
    assert [d for d in _diagnostics_for(code_ok) if d.category == "null_deref"] == []


def test_cpp_nullptr_arrow_member_access():
    # TP: nullptr struct pointer accessed via `->`.
    code = """
    struct Widget { int value; };
    void test() {
        Widget* w = nullptr;
        w->value = 1;
    }
    """
    null_diags = [d for d in _diagnostics_for(code) if d.category == "null_deref"]
    assert len(null_diags) >= 1


def test_cpp_new_delete_use_after_free():
    # TP: new/delete then dereference.
    code = """
    void test() {
        int* p = new int(7);
        delete p;
        *p = 10;
    }
    """
    uaf_diags = [d for d in _diagnostics_for(code) if d.category == "use_after_free"]
    assert len(uaf_diags) >= 1
    assert "freed" in uaf_diags[0].message.lower()

    # TN: new/delete with no access after delete.
    code_ok = """
    void test() {
        int* p = new int(7);
        *p = 10;
        delete p;
    }
    """
    assert [d for d in _diagnostics_for(code_ok) if d.category == "use_after_free"] == []


def test_cpp_new_array_delete_use_after_free():
    # TP: new[]/delete[] then index.
    code = """
    void test() {
        int* a = new int[4];
        delete[] a;
        a[0] = 1;
    }
    """
    uaf_diags = [d for d in _diagnostics_for(code) if d.category == "use_after_free"]
    assert len(uaf_diags) >= 1


def test_cpp_dangling_pointer_from_function():
    # TP: returning address of a local from a non-main function.
    code = """
    int* makePtr() {
        int local = 10;
        return &local;
    }
    """
    dangling_diags = [d for d in _diagnostics_for(code) if d.category == "dangling"]
    assert len(dangling_diags) >= 1
    assert "stack variable" in dangling_diags[0].message.lower()


def test_cpp_out_of_bounds_and_div_zero():
    # OOB on a C++ stack array.
    oob = [d for d in _diagnostics_for("void f(){int a[3]; a[7]=1;}") if d.category == "oob"]
    assert len(oob) >= 1

    # Division by a variable that is provably zero.
    div = [d for d in _diagnostics_for("int f(){int d=0; return 100/d;}") if d.category == "div_zero"]
    assert len(div) >= 1


def test_every_detector_populates_reasoning():
    """Every positive diagnostic from every detector must carry a non-empty
    `reasoning` list. The "AST Reasoning" UI block depends on this contract."""
    samples = [
        # (category, code, language)
        ("null_deref",     "void f(){int*p=0;*p=1;}",                                 "cpp"),
        ("uninit",         "int f(){int x; return x+1;}",                              "c"),
        ("div_zero",       "int f(){return 10/0;}",                                    "c"),
        ("oob",            "void f(){int a[3]={1,2,3}; a[5]=1;}",                      "c"),
        ("use_after_free", "#include <stdlib.h>\nvoid f(){int*p=(int*)malloc(4);free(p);*p=1;}", "c"),
        ("dangling",       "int* f(){int x=42; return &x;}",                           "c"),
        ("int_overflow",   "int f(){return 2147483647+1;}",                            "c"),
    ]
    for category, code, lang in samples:
        diags = _diagnostics_for(code, language=lang)
        matches = [d for d in diags if d.category == category]
        assert matches, f"detector {category} produced no diagnostic for {code!r}"
        for d in matches:
            assert d.reasoning, f"{category} diagnostic missing reasoning: {d!r}"
            assert len(d.reasoning) >= 2, (
                f"{category} reasoning should have >=2 bullets, got {d.reasoning!r}"
            )
            for bullet in d.reasoning:
                assert isinstance(bullet, str) and bullet.strip(), (
                    f"{category} reasoning bullet must be a non-empty string: {bullet!r}"
                )
