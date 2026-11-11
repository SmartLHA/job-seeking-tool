#!/bin/bash
# Double-click launcher for the Job Seeking Tool.
# Starts the local server and opens it in your browser.

cd "$(dirname "$0")"

# Use the project venv (system python3 lacks bs4/dotenv).
PY="$(pwd)/venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "ERROR: $PY not found. Create the project venv (python3 -m venv venv) and install dependencies first." >&2
  exit 1
fi
if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "Interpreter: $PY"
  "$PY" --version
fi

PORT="${PORT:-9000}"
PROFILE="${PROFILE:-data/mic_profile.json}"
HOST="127.0.0.1"

# The helper never kills anything by name or port: it only stops an instance it
# started itself (SIGINT), and refuses if something else holds the port.
exec "$PY" scripts/app_lifecycle.py start --port "$PORT" --host "$HOST" --profile "$PROFILE" --open
