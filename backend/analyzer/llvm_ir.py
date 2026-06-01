"""LLVM IR generation via the system `clang` / `clang++` CLI.

This is intentionally simple: write the source to a temp file, shell out
to `clang -S -emit-llvm -O0`, read the resulting `.ll`. No debug metadata,
no source↔IR mapping — the IR is presented purely as a "compiler artifact"
view alongside AST and CFG (see docs/llvm.md for the agreed scope).

If clang is not on PATH, `generate_llvm_ir` returns an `IRResult` whose
`ok=False`; the analyze route uses that to surface a friendly message in
the UI instead of crashing the whole pipeline.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class IRResult:
    ok: bool
    ir: str | None = None
    error: str | None = None
    clang_path: str | None = None


def _find_clang(language: str) -> str | None:
    """Locate a clang invocation. Honors $CLANG_PATH, then PATH.

    For C we want `clang`; for C++ we prefer `clang++` (so the STL is on
    the default search path) but fall back to `clang -x c++` if needed.
    """
    explicit = os.getenv("CLANG_PATH", "").strip()
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return str(p)
        if p.is_dir():
            candidate = p / ("clang++.exe" if language == "cpp" else "clang.exe")
            if candidate.is_file():
                return str(candidate)
            candidate = p / ("clang++" if language == "cpp" else "clang")
            if candidate.is_file():
                return str(candidate)

    exe = "clang++" if language == "cpp" else "clang"
    found = shutil.which(exe)
    if found:
        return found
    # Fall back to plain `clang` and we'll pass `-x c++` at the call site.
    return shutil.which("clang")


def generate_llvm_ir(code: str, language: str = "cpp") -> IRResult:
    """Generate LLVM IR for `code` and return the .ll contents.

    Returns IRResult.ok=False with a human-readable error if clang is
    missing or the compile fails (e.g. the user's code has a syntax error).
    The analyze route treats `ok=False` as "show a banner in the IR tab,
    don't break the rest of the response".
    """
    clang = _find_clang(language)
    if clang is None:
        return IRResult(
            ok=False,
            error=(
                "clang not found on PATH. Install LLVM "
                "(https://github.com/llvm/llvm-project/releases) and ensure "
                "`clang` / `clang++` are on PATH, or set CLANG_PATH in .env."
            ),
        )

    ext = ".cpp" if language == "cpp" else ".c"
    with tempfile.TemporaryDirectory(prefix="cdlab_ir_") as tmpdir:
        src_path = Path(tmpdir) / f"input{ext}"
        ll_path = Path(tmpdir) / "input.ll"
        src_path.write_text(code, encoding="utf-8")

        # -O0 keeps IR readable; -S emits assembly form (.ll text, not bitcode).
        # -g embeds DWARF-style !dbg / !DILocation metadata so the IR
        # introspector can map each instruction back to a source line for
        # the "LLVM Evidence" panel. -gcolumn-info adds column data (we
        # don't use it today but it's cheap and the parser is robust if
        # absent).
        # Suppress -Werror surprises and unused-result chatter so stderr stays
        # informative without drowning in noise.
        cmd: list[str] = [
            clang,
            "-S",
            "-emit-llvm",
            "-O0",
            "-g",
            "-gcolumn-info",
            "-w",  # silence warnings — we only care about hard errors
        ]
        # Force language when we ended up with bare `clang` for C++.
        if language == "cpp" and "clang++" not in os.path.basename(clang).lower():
            cmd += ["-x", "c++", "-std=c++17"]
        elif language == "cpp":
            cmd += ["-std=c++17"]
        else:
            cmd += ["-std=c11"]

        if language == "cpp":
            # Same Windows/MSVC-STL escape hatch the parser uses.
            cmd += ["-D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH"]

        cmd += [str(src_path), "-o", str(ll_path)]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError as exc:
            return IRResult(ok=False, error=f"failed to invoke clang: {exc}", clang_path=clang)
        except subprocess.TimeoutExpired:
            return IRResult(
                ok=False,
                error="clang timed out after 30s",
                clang_path=clang,
            )

        if proc.returncode != 0 or not ll_path.exists():
            err = proc.stderr.strip() or proc.stdout.strip() or "clang exited non-zero"
            # Trim huge diagnostic dumps for the UI.
            if len(err) > 2000:
                err = err[:1900] + "\n... (truncated)"
            return IRResult(ok=False, error=err, clang_path=clang)

        try:
            ir = ll_path.read_text(encoding="utf-8")
        except OSError as exc:
            return IRResult(ok=False, error=f"failed to read .ll: {exc}", clang_path=clang)

        return IRResult(ok=True, ir=ir, clang_path=clang)


def clang_available() -> tuple[bool, str | None]:
    """Health-check helper used by /health (Phase 1 endpoint can advertise it)."""
    clang = _find_clang("cpp") or _find_clang("c")
    return (clang is not None), clang
