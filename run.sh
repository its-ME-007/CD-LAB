#!/usr/bin/env bash
# CD_LAB — run script.
# Starts the FastAPI server at http://localhost:8000/.

set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "[run] No .venv found. Running build.sh first ..."
    ./build.sh
fi

if [ -f ".venv/Scripts/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/Scripts/activate
else
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"

echo "[run] Starting CD_LAB at http://$HOST:$PORT/"
echo "[run] Press Ctrl+C to stop."
echo
exec python -m uvicorn backend.main:app --port "$PORT" --host "$HOST" --app-dir .
