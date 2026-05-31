"""Registry and coordinator for static Undefined Behavior detectors."""

from __future__ import annotations

import logging
from backend.schemas import Diagnostic
from . import (
    null_deref,
    uninit_var,
    div_by_zero,
    use_after_free,
    dangling_ptr,
    oob_access,
    int_overflow,
)

DETECTORS = [
    null_deref.detect,
    uninit_var.detect,
    div_by_zero.detect,
    use_after_free.detect,
    dangling_ptr.detect,
    oob_access.detect,
    int_overflow.detect,
]

def run_all(
    tu,
    cfgs,
    dataflows_rd,
    dataflows_lv
) -> list[Diagnostic]:
    """Execute all registered static detectors and deduplicate their output."""
    out: list[Diagnostic] = []
    for cfg, rd, lv in zip(cfgs, dataflows_rd, dataflows_lv):
        for fn in DETECTORS:
            try:
                out.extend(fn(tu, cfg, rd, lv))
            except Exception as exc:
                logging.exception("detector %s failed: %s", fn.__module__, exc)
    return _dedupe(out)

def _dedupe(diags: list[Diagnostic]) -> list[Diagnostic]:
    seen = set()
    out = []
    for d in diags:
        key = (d.category, d.range.line, d.range.column, d.message)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out
