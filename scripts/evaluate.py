#!/usr/bin/env python3
"""CD_LAB evaluation harness.

Walks `testcases/`, runs the analyzer against each file in-process (no
HTTP), and reports per-category precision / recall / F1. Optionally
compares against `gcc -Wall -Wextra -fanalyzer`, `clang --analyze`, and
`cppcheck` when those tools are on PATH.

Usage:
    python scripts/evaluate.py              # run, print markdown table
    python scripts/evaluate.py --json       # emit JSON instead
    python scripts/evaluate.py --no-baseline # skip gcc/clang/cppcheck

Test-case naming convention:
    <label>_<category>_<n>.<ext>
where:
    label   = "good" | "bad"
    category ∈ {null_deref, uninit, div_zero, oob, use_after_free,
                dangling, int_overflow}
    ext     = "c" | "cpp"
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# Make `backend` importable when running from any cwd.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

from backend.analyzer import (  # noqa: E402
    build_cfgs,
    live_variables,
    parse_source,
    reaching_definitions,
    run_all,
)

TESTCASES = _ROOT / "testcases"

# Category → keywords we look for in baseline tool output. Baselines emit
# free-form text; we use simple keyword matching to decide whether a tool
# "detected" a given category. This is intentionally generous to the
# baselines — better to over-credit them than under-credit them.
BASELINE_KEYWORDS = {
    "null_deref":     [r"null", r"nullptr", r"dereference of NULL"],
    "uninit":         [r"uninitialized", r"may be used uninitialized"],
    "div_zero":       [r"division by zero", r"divide.*by.*zero", r"zerodivision"],
    "oob":            [r"out.?of.?bound", r"buffer overflow", r"array.*bound", r"index.*out"],
    "use_after_free": [r"use.?after.?free", r"dangling.*pointer"],
    "dangling":       [r"address of (a |the )?local", r"address of stack memory", r"returning address",
                       r"address of local variable"],
    "int_overflow":   [r"integer overflow", r"signed.*overflow", r"overflow"],
}

FILENAME_RE = re.compile(r"^(good|bad)_(?P<cat>[a-z_]+?)_(?P<n>\d+)\.(?P<ext>c|cpp)$")


def parse_filename(name: str):
    m = FILENAME_RE.match(name)
    if not m:
        return None
    label = name.split("_", 1)[0]
    return label, m.group("cat"), m.group("ext")


# ---------------------------------------------------------------------------
# CD_LAB analyzer (in-process — no HTTP needed)
# ---------------------------------------------------------------------------

def analyze_with_cdlab(path: Path) -> set[str]:
    """Return set of detected category labels."""
    code = path.read_text(encoding="utf-8")
    language = "cpp" if path.suffix == ".cpp" else "c"
    try:
        parsed = parse_source(code, language=language)
        cfgs = build_cfgs(parsed.tu)
        rds = [reaching_definitions(c) for c in cfgs]
        lvs = [live_variables(c) for c in cfgs]
        diags = run_all(parsed.tu, cfgs, rds, lvs)
        return {d.category for d in diags}
    except Exception as exc:
        print(f"  [cdlab] crash on {path.name}: {exc}", file=sys.stderr)
        return set()


# ---------------------------------------------------------------------------
# Baseline tools (gcc / clang / cppcheck)
# ---------------------------------------------------------------------------

def _matches_category(text: str, category: str) -> bool:
    patterns = BASELINE_KEYWORDS.get(category, [])
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _run_capture(cmd: list[str], timeout: int = 20) -> str:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return (proc.stdout or "") + "\n" + (proc.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def analyze_with_gcc(path: Path) -> set[str]:
    if not shutil.which("gcc"):
        return set()
    cmd = ["gcc", "-Wall", "-Wextra", "-fanalyzer", "-fsyntax-only", str(path)]
    out = _run_capture(cmd)
    return {cat for cat in BASELINE_KEYWORDS if _matches_category(out, cat)}


def _resolve_clang() -> str | None:
    """Look up clang.exe like backend/analyzer/llvm_ir.py does: respect
    $CLANG_PATH (file or directory) first, then fall back to PATH."""
    import os
    explicit = os.getenv("CLANG_PATH", "").strip()
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return str(p)
        if p.is_dir():
            for name in ("clang.exe", "clang"):
                candidate = p / name
                if candidate.is_file():
                    return str(candidate)
    return shutil.which("clang") or shutil.which("clang++")


def analyze_with_clang(path: Path) -> set[str]:
    clang_exe = _resolve_clang()
    if not clang_exe:
        return set()
    cmd = [clang_exe, "--analyze", "-Xanalyzer", "-analyzer-output=text", str(path)]
    out = _run_capture(cmd)
    return {cat for cat in BASELINE_KEYWORDS if _matches_category(out, cat)}


def analyze_with_cppcheck(path: Path) -> set[str]:
    if not shutil.which("cppcheck"):
        return set()
    cmd = ["cppcheck", "--enable=warning,style", "--quiet", str(path)]
    out = _run_capture(cmd)
    return {cat for cat in BASELINE_KEYWORDS if _matches_category(out, cat)}


TOOLS = {
    "cdlab":    analyze_with_cdlab,
    "gcc":      analyze_with_gcc,
    "clang":    analyze_with_clang,
    "cppcheck": analyze_with_cppcheck,
}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def evaluate(tool_results: dict[str, dict[Path, set[str]]],
             cases: list[tuple[Path, str, str]]) -> dict[str, dict[str, dict]]:
    """Compute per-tool, per-category TP/FP/TN/FN + precision/recall/F1."""
    # tool → category → {tp, fp, tn, fn}
    out: dict[str, dict[str, dict[str, int]]] = {}
    for tool in tool_results:
        per_cat: dict[str, dict[str, int]] = defaultdict(
            lambda: {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
        )
        for path, label, category in cases:
            detected = tool_results[tool][path]
            is_bad = (label == "bad")
            hit = (category in detected)
            if is_bad and hit:
                per_cat[category]["tp"] += 1
            elif is_bad and not hit:
                per_cat[category]["fn"] += 1
            elif not is_bad and hit:
                per_cat[category]["fp"] += 1
            else:
                per_cat[category]["tn"] += 1
        out[tool] = dict(per_cat)
    return out


def _safe_div(num: int, den: int) -> float:
    return num / den if den else 0.0


def with_prf(metrics: dict[str, dict[str, dict[str, int]]]) -> dict:
    """Add precision/recall/F1 to a metrics dict."""
    enriched: dict = {}
    for tool, by_cat in metrics.items():
        enriched[tool] = {}
        for cat, counts in by_cat.items():
            tp, fp, fn, tn = counts["tp"], counts["fp"], counts["fn"], counts["tn"]
            p = _safe_div(tp, tp + fp)
            r = _safe_div(tp, tp + fn)
            f1 = _safe_div(2 * p * r, p + r) if (p + r) else 0.0
            enriched[tool][cat] = {**counts, "precision": p, "recall": r, "f1": f1}
    return enriched


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_markdown(metrics: dict, total_cases: int, tool_available: dict[str, bool]) -> None:
    print(f"\n# CD_LAB evaluation\n")
    print(f"**{total_cases} test cases** under `testcases/` "
          f"covering 7 UB categories.\n")
    print("Tool availability:")
    for tool, ok in tool_available.items():
        print(f"- `{tool}`: {'AVAILABLE' if ok else 'NOT INSTALLED — skipped'}")
    print()

    cdlab = metrics.get("cdlab", {})
    categories = sorted(cdlab.keys())

    # Per-category table for cdlab
    print("## Per-category metrics (CD_LAB)\n")
    print("| Category | TP | FP | TN | FN | Precision | Recall | F1 |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    for cat in categories:
        c = cdlab[cat]
        print(f"| `{cat}` | {c['tp']} | {c['fp']} | {c['tn']} | {c['fn']} | "
              f"{c['precision']:.2f} | {c['recall']:.2f} | {c['f1']:.2f} |")

    # Aggregate per tool
    print("\n## Aggregate comparison\n")
    print("| Tool | TP | FP | TN | FN | Precision | Recall | F1 |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    for tool in ["cdlab", "gcc", "clang", "cppcheck"]:
        if tool not in metrics or (tool != "cdlab" and not tool_available.get(tool, False)):
            continue
        tp = sum(c["tp"] for c in metrics[tool].values())
        fp = sum(c["fp"] for c in metrics[tool].values())
        tn = sum(c["tn"] for c in metrics[tool].values())
        fn = sum(c["fn"] for c in metrics[tool].values())
        p = _safe_div(tp, tp + fp)
        r = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * p * r, p + r) if (p + r) else 0.0
        print(f"| `{tool}` | {tp} | {fp} | {tn} | {fn} | "
              f"{p:.2f} | {r:.2f} | {f1:.2f} |")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of markdown")
    ap.add_argument("--no-baseline", action="store_true",
                    help="Skip gcc/clang/cppcheck and only run CD_LAB")
    ap.add_argument("--testcases", type=Path, default=TESTCASES,
                    help="Override the test-case directory")
    args = ap.parse_args()

    if not args.testcases.exists():
        print(f"error: {args.testcases} not found", file=sys.stderr)
        return 1

    # Collect cases.
    cases: list[tuple[Path, str, str]] = []
    for path in sorted(args.testcases.glob("*")):
        if not path.is_file() or path.suffix not in (".c", ".cpp"):
            continue
        parsed = parse_filename(path.name)
        if parsed is None:
            continue
        label, cat, _ = parsed
        cases.append((path, label, cat))

    if not cases:
        print(f"error: no matching test cases in {args.testcases}", file=sys.stderr)
        return 1

    # Decide which tools to actually run.
    tools_to_run = ["cdlab"]
    tool_available = {"cdlab": True}
    if not args.no_baseline:
        for t in ["gcc", "clang", "cppcheck"]:
            if t == "clang":
                available = _resolve_clang() is not None
            else:
                available = shutil.which(t) is not None
            tool_available[t] = available
            if available:
                tools_to_run.append(t)

    # Run.
    tool_results: dict[str, dict[Path, set[str]]] = {t: {} for t in tools_to_run}
    for path, _, _ in cases:
        for tool in tools_to_run:
            tool_results[tool][path] = TOOLS[tool](path)

    metrics_raw = evaluate(tool_results, cases)
    metrics = with_prf(metrics_raw)

    if args.json:
        # Convert path keys to strings for JSON
        print(json.dumps({
            "n_cases": len(cases),
            "tool_available": tool_available,
            "metrics": metrics,
        }, indent=2))
    else:
        print_markdown(metrics, len(cases), tool_available)

    return 0


if __name__ == "__main__":
    sys.exit(main())
