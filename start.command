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
  exit 0
fi

PORT="${PORT:-9000}"
PROFILE="${PROFILE:-data/mic_profile.json}"
HOST="127.0.0.1"
URL="http://127.0.0.1:$PORT"

echo "Stopping any running instance on port $PORT..."
pkill -f "src.job_hunt_ui" 2>/dev/null
lsof -ti tcp:"$PORT" | xargs kill -9 2>/dev/null
sleep 0.3

# Open the browser once the port is accepting connections (background loop).
(
  for i in $(seq 1 30); do
    if lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
      open "$URL"
      break
    fi
    sleep 0.5
  done
) &

echo "Starting server -> $URL"
echo "(Keep this window open. Close it or press Ctrl+C to stop the server.)"
exec "$PY" -m src.job_hunt_ui --profile "$PROFILE" --port "$PORT" --host "$HOST"
