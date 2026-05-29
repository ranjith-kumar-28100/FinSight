#!/usr/bin/env bash
# Launch the FinSight backend (FastAPI) and frontend (Vite) together.
# Requires: conda env `genai` activated, frontend deps installed.
set -e
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"

cleanup() {
  if [[ -n "${API_PID:-}" ]] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID"
  fi
}
trap cleanup EXIT

# Start API
echo "→ Starting FastAPI on http://127.0.0.1:8000"
( cd "$ROOT_DIR" && uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload ) &
API_PID=$!

# Frontend (foreground)
echo "→ Starting Vite on http://127.0.0.1:5173"
( cd "$ROOT_DIR/frontend" && npm run dev )
