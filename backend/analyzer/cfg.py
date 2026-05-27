"""Control-Flow Graph builder.

Given a libclang `TranslationUnit`, walks each function body and emits a
`FunctionCFGData` per function. The graph is `networkx.DiGraph`:

    node attributes:
        block: BasicBlock dataclass (kind, label, statements[Cursor], lines)
    edge attributes:
        label: "" (fallthrough) | "T" | "F" | "back" | "break" | "continue"

Cursors are kept inside the block objects so that the dataflow stage can read
def/use info directly from them. JSON serialization happens in `routes/graph.py`
(it discards the cursor handles).

Supported constructs (Phase 2): COMPOUND_STMT, IF_STMT, WHILE_STMT, FOR_STMT,
DO_STMT, RETURN_STMT, BREAK_STMT, CONTINUE_STMT, plain statements.
SWITCH/GOTO are intentionally out of scope — Phase 3 detectors don't need them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import networkx as nx
from clang import cindex


CONTROL_FLOW_KINDS = {
    "IF_STMT", "WHILE_STMT", "FOR_STMT", "DO_STMT",
    "RETURN_STMT", "BREAK_STMT", "CONTINUE_STMT",
    "COMPOUND_STMT",
}


@dataclass
class BasicBlock:
    id: str
    kind: str  # entry|exit|stmt|cond|loop_header|return|break|continue
    label: str
    statements: list[cindex.Cursor] = field(default_factory=list)
    start_line: int | None = None
    end_line: int | None = None

    def add_stmt(self, cursor: cindex.Cursor) -> None:
        self.statements.append(cursor)
        line = cursor.location.line if cursor.location else None
        if line:
            if self.start_line is None:
                self.start_line = line
            self.end_line = line


@dataclass
class FunctionCFGData:
    name: str
    cursor: cindex.Cursor
    graph: nx.DiGraph
    entry: str
    exit: str

    def blocks(self) -> Iterable[BasicBlock]:
        for _, data in self.graph.nodes(data=True):
            yield data["block"]


class _CFGBuilder:
    def __init__(self, func: cindex.Cursor) -> None:
        self.func = func
        self.name = func.spelling or "<anon>"
        self.graph: nx.DiGraph = nx.DiGraph()
        self._next = 0
        self.entry = self._new_block("ENTRY", kind="entry")
        self.exit = self._new_block("EXIT", kind="exit")
        # Stack of (continue_target, break_target) for nested loops.
        self.loop_stack: list[tuple[str, str]] = []

    def _new_block(self, label: str, kind: str = "stmt") -> str:
        bid = f"{self.name}#{self._next}"
        self._next += 1
        self.graph.add_node(bid, block=BasicBlock(id=bid, kind=kind, label=label))
        return bid

    def _block(self, bid: str) -> BasicBlock:
        return self.graph.nodes[bid]["block"]

    def _edge(self, src: str, dst: str, label: str = "") -> None:
        self.graph.add_edge(src, dst, label=label)

    def build(self) -> FunctionCFGData:
        body = _find_body(self.func)
        if body is None:
            self._edge(self.entry, self.exit)
            return self._result()

        end = self._build_stmt(body, self.entry)
        if end is not None:
            self._edge(end, self.exit)
        return self._result()

    def _result(self) -> FunctionCFGData:
        return FunctionCFGData(
            name=self.name,
            cursor=self.func,
            graph=self.graph,
            entry=self.entry,
            exit=self.exit,
        )

    # ------------------------------------------------------------------
    # statement dispatch
    # ------------------------------------------------------------------
    def _build_stmt(self, cursor: cindex.Cursor, current: str | None) -> str | None:
        """Lower `cursor` into the CFG starting from `current`. Returns the
        block that subsequent statements should append to, or None if
        control cannot fall through (after a return/break/continue)."""
        if current is None:
            return None

        kind = cursor.kind.name
        handler = self._dispatch.get(kind, self.__class__._stmt_default)
        return handler(self, cursor, current)

    def _stmt_default(self, cursor: cindex.Cursor, current: str) -> str:
        self._block(current).add_stmt(cursor)
        return current

    def _stmt_compound(self, cursor: cindex.Cursor, current: str | None) -> str | None:
        for child in cursor.get_children():
            if current is None:
                break
            current = self._build_stmt(child, current)
        return current

    def _stmt_if(self, cursor: cindex.Cursor, current: str) -> str | None:
        children = list(cursor.get_children())
        if not children:
            return current
        cond = children[0]
        then_stmt = children[1] if len(children) > 1 else None
        else_stmt = children[2] if len(children) > 2 else None

        cond_block = self._new_block(f"if @ L{cursor.location.line}", kind="cond")
        self._block(cond_block).add_stmt(cond)
        self._edge(current, cond_block)

        merge = self._new_block("after_if")

        # then branch
        then_block = self._new_block("then")
        self._edge(cond_block, then_block, "T")
        then_end = self._build_stmt(then_stmt, then_block) if then_stmt else then_block
        if then_end is not None:
            self._edge(then_end, merge)

        # else branch (or fall-through to merge)
        if else_stmt is not None:
            else_block = self._new_block("else")
            self._edge(cond_block, else_block, "F")
            else_end = self._build_stmt(else_stmt, else_block)
            if else_end is not None:
                self._edge(else_end, merge)
        else:
            self._edge(cond_block, merge, "F")

        # If both branches diverge (return/break/etc.), merge is unreachable.
        if self.graph.in_degree(merge) == 0:
            self.graph.remove_node(merge)
            return None
        return merge

    def _stmt_while(self, cursor: cindex.Cursor, current: str) -> str | None:
        children = list(cursor.get_children())
        if not children:
            return current
        cond = children[0]
        body = children[1] if len(children) > 1 else None

        header = self._new_block(f"while @ L{cursor.location.line}", kind="loop_header")
        self._block(header).add_stmt(cond)
        self._edge(current, header)

        after = self._new_block("after_while")
        body_block = self._new_block("while_body")
        self._edge(header, body_block, "T")
        self._edge(header, after, "F")

        self.loop_stack.append((header, after))
        try:
            body_end = self._build_stmt(body, body_block) if body is not None else body_block
        finally:
            self.loop_stack.pop()

        if body_end is not None:
            self._edge(body_end, header, "back")
        return after

    def _stmt_do(self, cursor: cindex.Cursor, current: str) -> str | None:
        # do { body } while (cond) — libclang reports children in source order:
        # body first, then cond.
        children = list(cursor.get_children())
        if not children:
            return current
        body = children[0]
        cond = children[1] if len(children) > 1 else None

        body_block = self._new_block(f"do_body @ L{cursor.location.line}")
        self._edge(current, body_block)

        cond_block = self._new_block("do_while_cond", kind="cond")
        if cond is not None:
            self._block(cond_block).add_stmt(cond)
        after = self._new_block("after_do")

        self.loop_stack.append((cond_block, after))
        try:
            body_end = self._build_stmt(body, body_block)
        finally:
            self.loop_stack.pop()

        if body_end is not None:
            self._edge(body_end, cond_block)
        self._edge(cond_block, body_block, "T")
        self._edge(cond_block, after, "F")
        return after

    def _stmt_for(self, cursor: cindex.Cursor, current: str) -> str | None:
        """`for (init; cond; inc) body` — libclang exposes children in source
        order, with optional pieces omitted entirely. We use a heuristic: the
        last child is always the body; the rest are init/cond/inc in source order.

        For Phase 2 we don't introspect which of init/cond/inc is which — we
        attach all of them to the right places by position when the count is
        unambiguous (4 children), otherwise we fall back to "everything before
        body goes into the init block, cond is empty (treat as always true)".
        """
        children = list(cursor.get_children())
        if not children:
            return current

        body = children[-1]
        head_children = children[:-1]
        # Common case: 4 children → init, cond, inc, body.
        if len(head_children) == 3:
            init, cond, inc = head_children
        elif len(head_children) == 2:
            # Ambiguous; treat as cond + inc (no init) — common in `for(;c;i)`.
            init, cond, inc = None, head_children[0], head_children[1]
        elif len(head_children) == 1:
            init, cond, inc = None, head_children[0], None
        else:
            init = cond = inc = None

        # Build: current → init_block → header → (T) body → inc_block → header
        #                                       → (F) after
        init_block = self._new_block(f"for_init @ L{cursor.location.line}")
        self._edge(current, init_block)
        if init is not None:
            self._block(init_block).add_stmt(init)

        header = self._new_block("for_cond", kind="loop_header")
        if cond is not None:
            self._block(header).add_stmt(cond)
        self._edge(init_block, header)

        body_block = self._new_block("for_body")
        after = self._new_block("after_for")
        self._edge(header, body_block, "T")
        self._edge(header, after, "F")

        inc_block = self._new_block("for_inc")
        if inc is not None:
            self._block(inc_block).add_stmt(inc)
        self._edge(inc_block, header, "back")

        self.loop_stack.append((inc_block, after))
        try:
            body_end = self._build_stmt(body, body_block)
        finally:
            self.loop_stack.pop()

        if body_end is not None:
            self._edge(body_end, inc_block)
        return after

    def _stmt_return(self, cursor: cindex.Cursor, current: str) -> None:
        ret_block = self._new_block(f"return @ L{cursor.location.line}", kind="return")
        self._block(ret_block).add_stmt(cursor)
        self._edge(current, ret_block)
        self._edge(ret_block, self.exit)
        return None

    def _stmt_break(self, cursor: cindex.Cursor, current: str) -> None:
        if not self.loop_stack:
            # Defensive: stray break outside a loop is malformed; just drop edge.
            return None
        _, brk_target = self.loop_stack[-1]
        blk = self._new_block(f"break @ L{cursor.location.line}", kind="break")
        self._block(blk).add_stmt(cursor)
        self._edge(current, blk)
        self._edge(blk, brk_target, "break")
        return None

    def _stmt_continue(self, cursor: cindex.Cursor, current: str) -> None:
        if not self.loop_stack:
            return None
        cont_target, _ = self.loop_stack[-1]
        blk = self._new_block(f"continue @ L{cursor.location.line}", kind="continue")
        self._block(blk).add_stmt(cursor)
        self._edge(current, blk)
        self._edge(blk, cont_target, "continue")
        return None

    _dispatch = {
        "COMPOUND_STMT": _stmt_compound,
        "IF_STMT": _stmt_if,
        "WHILE_STMT": _stmt_while,
        "DO_STMT": _stmt_do,
        "FOR_STMT": _stmt_for,
        "RETURN_STMT": _stmt_return,
        "BREAK_STMT": _stmt_break,
        "CONTINUE_STMT": _stmt_continue,
    }


def _find_body(func: cindex.Cursor) -> cindex.Cursor | None:
    for child in func.get_children():
        if child.kind.name == "COMPOUND_STMT":
            return child
    return None


def build_cfgs(tu: cindex.TranslationUnit, src_filename: str | None = None) -> list[FunctionCFGData]:
    """Build one FunctionCFGData per function defined in `tu`.

    If `src_filename` is given, only functions whose location is in that file
    are considered — handy to skip system-header decls pulled in by #include.
    """
    cfgs: list[FunctionCFGData] = []
    for cursor in tu.cursor.get_children():
        if cursor.kind.name != "FUNCTION_DECL":
            continue
        if not cursor.is_definition():
            continue
        if src_filename is not None:
            loc_file = cursor.location.file
            if loc_file is None:
                continue
            from pathlib import Path
            if Path(loc_file.name).name != src_filename:
                continue
        cfgs.append(_CFGBuilder(cursor).build())
    return cfgs
