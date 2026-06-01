#!/usr/bin/env bash
# CD_LAB — build / install script.
# Creates a Python virtualenv and installs all backend dependencies.
# Works on Git Bash / WSL / Linux / macOS.

set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python}"

echo "[build] Creating virtualenv at .venv ..."
if [ ! -d ".venv" ]; then
    "$PYTHON" -m venv .venv
fi

# Activate (Windows vs. POSIX path layout)
if [ -f ".venv/Scripts/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/Scripts/activate
else
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

echo "[build] Upgrading pip ..."
python -m pip install --upgrade pip --quiet

echo "[build] Installing requirements ..."
pip install -r requirements.txt --quiet

echo
echo "[build] Done."
echo "[build] Next steps:"
echo "        1. cp .env.example .env  (then fill in GROQ_API_KEY for LLM explanations,"
echo "                                   and optionally CLANG_PATH if clang isn't on PATH)"
echo "        2. ./run.sh              (starts the web app at http://localhost:8000/)"
echo "        3. ./evaluate.sh         (runs the offline evaluation harness)"
