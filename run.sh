#!/usr/bin/env bash
# One-command start: installs deps if needed, builds the UI, starts Ollama + the local server.
set -e
cd "$(dirname "$0")"

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r backend/requirements.txt
[ -d frontend/node_modules ] || (cd frontend && npm install --no-audit --no-fund)
(cd frontend && npm run build >/dev/null)

if ! curl -s localhost:11434/api/version >/dev/null; then
  echo "Starting Ollama…"; (ollama serve >/dev/null 2>&1 &)
fi

echo "Dime → http://127.0.0.1:8000"
(sleep 1.5 && open http://127.0.0.1:8000) &
cd backend && exec ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
