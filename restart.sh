#!/bin/bash
# Gracefully restart the server (only an instance started by this tool).
# Usage: ./restart.sh
# Or with custom port: PORT=9001 ./restart.sh

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
HOST="${HOST:-127.0.0.1}"   # set HOST=0.0.0.0 to allow access from other devices (e.g. via Tailscale)

exec "$PY" scripts/app_lifecycle.py restart --port "$PORT" --host "$HOST" --profile "$PROFILE"
