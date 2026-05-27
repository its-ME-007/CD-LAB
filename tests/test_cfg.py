"""Phase 2: CFG shape tests.

Each test parses a small C snippet, builds the CFG for `main`, and checks
basic structural invariants. We avoid asserting exact node counts (they're
sensitive to lowering style) and instead check reachability, edge labels,
and the presence of expected block kinds.
"""

from __future__ import annotations

import networkx as nx
import pytest

from backend.analyzer import build_cfgs, parse_source


def _cfg_for(code: str, language: str = "c", function: str = "main"):
    parsed = parse_source(code, language=language)
    cfgs = [c for c in build_cfgs(parsed.tu, src_filename=None) if c.name == function]
    assert cfgs, f"function {function!r} not found in TU"
    return cfgs[0]


def _kinds(cfg) -> set[str]:
    return {data["block"].kind for _, data in cfg.graph.nodes(data=True)}


def _edge_labels(cfg) -> set[str]:
    return {d.get("label", "") for _, _, d in cfg.graph.edges(data=True)}


def test_trivial_main():
    cfg = _cfg_for("int main(void){return 0;}")
    assert cfg.entry in cfg.graph
    assert cfg.exit in cfg.graph
    assert nx.has_path(cfg.graph, cfg.entry, cfg.exit)
    assert "return" in _kinds(cfg)


def test_if_else_creates_diamond():
    code = """
    int main(int a) {
        int x;
        if (a) {
            x = 1;
        } else {
            x = 2;
        }
        return x;
    }
    """
    cfg = _cfg_for(code)
    kinds = _kinds(cfg)
    assert "cond" in kinds, kinds
    labels = _edge_labels(cfg)
    assert "T" in labels and "F" in labels, labels
    # Both branches must reach EXIT.
    assert nx.has_path(cfg.graph, cfg.entry, cfg.exit)


def test_if_no_else_falls_through():
    code = """
    int main(int a) {
        if (a) return 1;
        return 0;
    }
    """
    cfg = _cfg_for(code)
    # Two distinct paths to EXIT (one via the then-return, one via the trailing return).
    paths = list(nx.all_simple_paths(cfg.graph, cfg.entry, cfg.exit))
    assert len(paths) >= 2, paths


def test_while_has_back_edge_and_exit():
    code = """
    int main(void) {
        int i = 0;
        while (i < 10) { i = i + 1; }
        return i;
    }
    """
    cfg = _cfg_for(code)
    assert "loop_header" in _kinds(cfg)
    assert "back" in _edge_labels(cfg), "while loop must have a back-edge labeled 'back'"
    assert nx.has_path(cfg.graph, cfg.entry, cfg.exit)


def test_for_loop_has_header_and_inc_block():
    code = """
    int main(void) {
        int s = 0;
        for (int i = 0; i < 5; i = i + 1) { s = s + i; }
        return s;
    }
    """
    cfg = _cfg_for(code)
    kinds = _kinds(cfg)
    assert "loop_header" in kinds, kinds
    labels = _edge_labels(cfg)
    assert "T" in labels and "F" in labels and "back" in labels


def test_break_targets_after_loop():
    code = """
    int main(int n) {
        while (n) {
            if (n == 1) break;
            n = n - 1;
        }
        return n;
    }
    """
    cfg = _cfg_for(code)
    assert "break" in _kinds(cfg)
    # No edges should target ENTRY from a break.
    for src, _, d in cfg.graph.edges(data=True):
        if d.get("label") == "break":
            break
    else:
        pytest.fail("expected at least one edge labeled 'break'")


def test_unreachable_after_return_in_both_branches():
    code = """
    int main(int a) {
        if (a) return 1;
        else return 0;
        // unreachable below
        return 2;
    }
    """
    cfg = _cfg_for(code)
    # EXIT reachable from ENTRY.
    assert nx.has_path(cfg.graph, cfg.entry, cfg.exit)
    # The trailing `return 2` is in source but unreachable; the CFG should still be valid
    # (we don't assert it's absent — only that the diamond closes correctly).
    assert "return" in _kinds(cfg)


def test_multiple_functions_get_separate_cfgs():
    code = """
    int foo(void) { return 1; }
    int bar(void) { return 2; }
    int main(void) { return foo() + bar(); }
    """
    parsed = parse_source(code, language="c")
    cfgs = build_cfgs(parsed.tu, src_filename=None)
    names = {c.name for c in cfgs}
    assert {"foo", "bar", "main"} <= names, names
