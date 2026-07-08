#!/bin/bash
# Kill any running instance and restart the server.
# Usage: ./restart.sh
# Or with custom port: PORT=9001 ./restart.sh

cd "$(dirname "$0")"

PORT="${PORT:-9000}"
PROFILE="${PROFILE:-data/mic_profile.json}"
HOST="${HOST:-127.0.0.1}"   # set HOST=0.0.0.0 to allow access from other devices (e.g. via Tailscale)

echo "Stopping any running instance on port $PORT..."
pkill -f "src.job_hunt_ui" 2>/dev/null
lsof -ti tcp:"$PORT" | xargs kill -9 2>/dev/null
sleep 0.3

echo "Starting server → http://127.0.0.1:$PORT"
exec python3 -m src.job_hunt_ui --profile "$PROFILE" --port "$PORT" --host "$HOST"
