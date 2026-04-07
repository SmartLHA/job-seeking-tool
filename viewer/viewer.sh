#!/bin/bash
# Convenience script to start/stop the local docs viewer

PORT=8765
DIR="$(cd "$(dirname "$0")/.." && pwd)"

start() {
    if lsof -Pi ":$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "Viewer already running on port $PORT"
    else
        cd "$DIR" && nohup python3 viewer/viewer_server.py > /tmp/viewer.log 2>&1 &
        sleep 1
        if lsof -Pi ":$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
            echo "Viewer started on http://localhost:$PORT/viewer/"
            echo "Usage endpoint: http://localhost:$PORT/usage"
        else
            echo "Viewer failed to start - check /tmp/viewer.log"
        fi
    fi
}

stop() {
    lsof -Pi ":$PORT" -sTCP:LISTEN -t | xargs kill 2>/dev/null && echo "Viewer stopped" || echo "Viewer not running"
}

status() {
    if lsof -Pi ":$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "Viewer running on http://localhost:$PORT/viewer/"
    else
        echo "Viewer not running"
    fi
}

case "${1:-start}" in
    start) start ;;
    stop)  stop ;;
    status) status ;;
    restart) stop && start ;;
    *)     echo "Usage: $0 {start|stop|status|restart}" ;;
esac
