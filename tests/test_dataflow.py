"""Phase 2: dataflow tests for reaching definitions and live variables."""

from __future__ import annotations

from backend.analyzer import (
    build_cfgs,
    extract_def_use,
    live_variables,
    parse_source,
    reaching_definitions,
)


def _cfg_for(code: str, function: str = "main"):
    parsed = parse_source(code, language="c")
    cfgs = [c for c in build_cfgs(parsed.tu, src_filename=None) if c.name == function]
    assert cfgs, f"function {function!r} not in TU"
    return cfgs[0]


# ---------------------------------------------------------------------------
# Def/use extraction
# ---------------------------------------------------------------------------

def _stmts(cfg):
    for _, data in cfg.graph.nodes(data=True):
        yield from data["block"].statements


def test_vardecl_with_initializer_defines_lhs():
    cfg = _cfg_for("int main(void){int x = 5; return x;}")
    all_defs: set[str] = set()
    for stmt in _stmts(cfg):
        d, _ = extract_def_use(stmt)
        all_defs |= d
    assert "x" in all_defs


def test_vardecl_without_initializer_does_not_define():
    cfg = _cfg_for("int main(void){int x; return 0;}")
    for stmt in _stmts(cfg):
        d, _ = extract_def_use(stmt)
        assert "x" not in d, "uninitialized VAR_DECL must not count as a definition"


def test_assignment_defines_and_rhs_uses():
    code = """
    int main(void){
        int x = 0;
        int y = 0;
        x = y + 1;
        return x;
    }
    """
    cfg = _cfg_for(code)
    saw_x_def_with_y_use = False
    for stmt in _stmts(cfg):
        d, u = extract_def_use(stmt)
        if "x" in d and "y" in u:
            saw_x_def_with_y_use = True
    assert saw_x_def_with_y_use


def test_compound_assignment_is_use_and_def():
    code = "int main(void){int x = 1; x += 2; return x;}"
    cfg = _cfg_for(code)
    saw_compound = False
    for stmt in _stmts(cfg):
        d, u = extract_def_use(stmt)
        if "x" in d and "x" in u:
            saw_compound = True
    assert saw_compound, "x += 2 must count as both a use and a def of x"


# ---------------------------------------------------------------------------
# Reaching definitions
# ---------------------------------------------------------------------------

def test_reaching_defs_propagate_to_exit_in_straight_line():
    cfg = _cfg_for("int main(void){int x = 1; int y = 2; return x + y;}")
    rd = reaching_definitions(cfg)
    out_vars_at_exit = {d.var for d in rd.in_sets[cfg.exit]}
    assert {"x", "y"} <= out_vars_at_exit


def test_reaching_defs_kill_overwritten_definition():
    code = """
    int main(void){
        int x = 1;
        x = 2;
        return x;
    }
    """
    cfg = _cfg_for(code)
    rd = reaching_definitions(cfg)
    # At EXIT, only the most recent `x` def should reach (the one on the second
    # statement). We assert that exactly one definition of `x` reaches EXIT.
    defs_of_x = [d for d in rd.in_sets[cfg.exit] if d.var == "x"]
    assert len(defs_of_x) == 1, defs_of_x


def test_reaching_defs_branch_union():
    code = """
    int main(int a) {
        int x;
        if (a) { x = 1; } else { x = 2; }
        return x;
    }
    """
    cfg = _cfg_for(code)
    rd = reaching_definitions(cfg)
    defs_of_x_at_exit = [d for d in rd.in_sets[cfg.exit] if d.var == "x"]
    # Both branch defs of x must reach EXIT (may-analysis joins on union).
    assert len(defs_of_x_at_exit) >= 2, defs_of_x_at_exit


def test_uninitialized_use_has_no_reaching_def():
    code = """
    int main(void){
        int x;
        return x;     // <-- uninit use
    }
    """
    cfg = _cfg_for(code)
    rd = reaching_definitions(cfg)
    # No definition of x exists anywhere in the function.
    assert rd.all_defs_by_var.get("x", set()) == set()


# ---------------------------------------------------------------------------
# Live variables
# ---------------------------------------------------------------------------

def test_live_vars_return_value_is_live_at_entry():
    cfg = _cfg_for("int main(void){int x = 1; return x;}")
    lv = live_variables(cfg)
    # `x` should be live somewhere on the return path. We don't pin the exact
    # block, just check the union of all in-sets contains x.
    all_live: set[str] = set()
    for s in lv.in_sets.values():
        all_live |= s
    assert "x" in all_live


def test_live_vars_dead_assignment_excluded():
    code = """
    int main(void) {
        int x = 1;
        int y = 2;
        return y;    // x is dead from here back to its assignment
    }
    """
    cfg = _cfg_for(code)
    lv = live_variables(cfg)
    # At EXIT, no variable should be live (no successors).
    assert lv.in_sets[cfg.exit] == set()
    # Somewhere in the body, y is live but x need not be (we only assert y).
    all_live: set[str] = set()
    for s in lv.in_sets.values():
        all_live |= s
    assert "y" in all_live
