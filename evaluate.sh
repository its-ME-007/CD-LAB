#!/usr/bin/env bash
# CD_LAB — evaluation harness driver.
# Runs the analyzer against every file in testcases/ and prints
# per-category precision / recall / F1, plus a baseline comparison
# against gcc / clang / cppcheck when those are on PATH.

set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "[eval] No .venv found. Running build.sh first ..."
    ./build.sh
fi

if [ -f ".venv/Scripts/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/Scripts/activate
else
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

exec python scripts/evaluate.py "$@"
