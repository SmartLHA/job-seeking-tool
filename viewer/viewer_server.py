#!/usr/bin/env python3
"""
Minimal combined viewer + API server using raw sockets.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import glob
import threading
import socket
from pathlib import Path
from datetime import datetime

VIEWER_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = VIEWER_DIR.parent.resolve()
PORT = 8765
VIEWER_HOST = "0.0.0.0"
MAIN_SESSIONS_FILE = Path("/Users/lhaclaw/.openclaw/agents/main/sessions/sessions.json")


def _age(ms: int) -> str:
    if ms < 60000:
        return f"{ms/1000:.0f}s ago"
    elif ms < 3600000:
        return f"{ms/60000:.0f}m ago"
    else:
        return f"{ms/3600000:.1f}h ago"


def _get_session_task(key: str, sid: str, session_updated_ms: int) -> tuple[str, str]:
    """Extract task name + age from a session's transcript."""
    pattern = f"/Users/lhaclaw/.openclaw/agents/main/sessions/{sid}*.jsonl"
    files = glob.glob(pattern)
    if not files:
        return None, None
    path = files[0]
    try:
        lines = open(path).readlines()
    except Exception:
        return None, None

    now_ms = datetime.now().timestamp() * 1000
    age_ms = now_ms - session_updated_ms

    # Scan from end for last user message with Handy/Scout task header
    for line in reversed(lines):
        try:
            m = json.loads(line)
            if m.get("type") != "message":
                continue
            msg = m.get("message", {})
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    str(c.get("text", "")) for c in content if isinstance(c, dict)
                )
            content = str(content)

            # Match Handy/Scout task header
            m_task = re.search(r"## (Handy|Scout|SilverHand)[^\n]*", content)
            if m_task:
                task_name = m_task.group(0).lstrip("## ").strip()
                # Clean: remove model line
                task_name = re.sub(r"\*\*Task from:[^*]+\*\*", "", task_name).strip()
                task_name = re.sub(r"\*\*Model:[^*]+\*\*", "", task_name).strip()
                task_name = task_name[:100].strip()
                return task_name, _age(age_ms)
        except Exception:
            pass

    return None, None


def _role_status() -> dict:
    """Build role status from main/codex/qa agent sessions."""
    # Map role -> agent folder
    ROLE_AGENT_MAP = {
        "silverhand": "main",
        "handy": "codex",
        "scout": "qa",
    }
    now_ms = datetime.now().timestamp() * 1000

    def get_recent_session(agent: str) -> tuple:
        """Get most recent session for an agent."""
        sessions_file = Path(f"/Users/lhaclaw/.openclaw/agents/{agent}/sessions/sessions.json")
        if not sessions_file.exists():
            return None, None
        try:
            with open(sessions_file) as f:
                data = json.load(f)
            if not data:
                return None, None
            # Sort by updatedAt descending
            sorted_sessions = sorted(data.items(), key=lambda x: x[1].get("updatedAt", 0), reverse=True)
            if sorted_sessions:
                key, val = sorted_sessions[0]
                return key, val
        except Exception:
            pass
        return None, None

    def build_role(key: str, label: str) -> dict:
        session_key, session_val = get_recent_session(ROLE_AGENT_MAP.get(key.lower(), key))
        if not session_key:
            return {"key": key, "label": label, "status": "amber", "age": "—", "summary": f"No recent {label} session", "session_key": "—"}
        
        updated = session_val.get("updatedAt", 0)
        age_ms = now_ms - updated
        age_str = _age(age_ms)
        session_short = session_key.split(":")[-1][:12]
        
        # Determine status: running (green) if active recently + running state
        # error (red) if failed/aborted, idle (amber) otherwise
        sess_status = session_val.get("status", "")
        aborted = session_val.get("abortedLastRun", False)
        
        if aborted or sess_status in ("failed", "error"):
            status = "red"
        elif sess_status == "running" and age_ms < 120000:  # updated within 2 min
            status = "green"
        else:
            status = "amber"
        
        return {
            "key": key,
            "label": label,
            "status": status,
            "age": age_str,
            "summary": f"Session {session_short}…",
            "session_key": session_key,
        }

    result = {
        "roles": [
            build_role("silverhand", "SilverHand"),
            build_role("handy", "Handy"),
            build_role("scout", "Scout"),
        ],
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return result


def _openclaw_status() -> dict:
    try:
        result = subprocess.run(
            ["openclaw", "status", "--json"],
            capture_output=True, text=True, timeout=10,
            stdin=subprocess.DEVNULL,
            env=dict(os.environ, PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"),
        )
        return json.loads(result.stdout)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def handle_api_health() -> bytes:
    data = {
        "ollama": {"available": [], "running": [], "error": None},
        "openclaw": {"default_model": None, "sessions": [], "error": None},
        "cron_jobs": [],
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL
        )
        ollama_available = []
        ollama_running = []
        for line in result.stdout.split("\n"):
            if line.strip() and not line.startswith("NAME"):
                parts = re.split(r"\s+", line.strip())
                if len(parts) >= 2:
                    ollama_available.append({"name": parts[0], "size": parts[1]})
                    if len(parts) >= 3 and parts[2] == "running":
                        ollama_running.append(parts[0])
        data["ollama"] = {"available": ollama_available, "running": ollama_running, "error": None}
    except Exception as e:
        data["ollama"] = {"available": [], "running": [], "error": str(e)}

    try:
        status = _openclaw_status()
        if isinstance(status, dict) and status.get("ok") is not False:
            data["openclaw"] = {
                "default_model": status.get("model"),
                "sessions": status.get("sessions", []),
                "error": None,
            }
    except Exception as e:
        data["openclaw"] = {"default_model": None, "sessions": [], "error": str(e)}

    try:
        cron_result = subprocess.run(
            ["/opt/homebrew/bin/openclaw", "cron", "list", "--json"],
            capture_output=True, text=True, timeout=10,
            stdin=subprocess.DEVNULL,
            env=dict(os.environ, PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"),
        )
        cron_data = json.loads(cron_result.stdout) if cron_result.returncode == 0 else {}
        cron_list = cron_data.get("jobs", [])
        data["cron_jobs"] = [
            {
                "name": j.get("name", "?"),
                "last_run": j.get("state", {}).get("lastRunAtMs"),
                "last_status": j.get("state", {}).get("lastRunStatus", "?"),
                "error": j.get("state", {}).get("lastError"),
            }
            for j in cron_list
        ]
    except Exception:
        data["cron_jobs"] = []

    return json.dumps(data).encode()


def handle_api_role_status() -> bytes:
    return json.dumps(_role_status()).encode()


def handle_api_help() -> bytes:
    """Check if openclaw CLI is accessible."""
    try:
        result = subprocess.run(
            ["/opt/homebrew/bin/openclaw", "--help"],
            capture_output=True, text=True, timeout=5,
            stdin=subprocess.DEVNULL,
            env=dict(os.environ, PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"),
        )
        if result.returncode == 0:
            return json.dumps({"ok": True, "output": "OpenClaw CLI is accessible"}).encode()
        else:
            return json.dumps({"ok": False, "error": result.stderr[:200]}).encode()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}).encode()


def serve_file(sock: socket.socket, path: str) -> bool:
    if path.startswith("/viewer/"):
        rel = path.replace("/viewer/", "", 1).replace("/viewer", "", 1)
        normalized = os.path.normpath("viewer/" + rel).lstrip("/")
    elif path == "/viewer":
        normalized = "viewer/index.html"
    elif path == "/":
        normalized = "viewer/index.html"
    else:
        normalized = os.path.normpath(path).lstrip("/")
        candidate_check = (PROJECT_ROOT / normalized).resolve()
        if not str(candidate_check).startswith(str(PROJECT_ROOT) + os.sep):
            return False

    file_path = (PROJECT_ROOT / normalized).resolve()
    if not str(file_path).startswith(str(PROJECT_ROOT) + os.sep):
        return False
    if file_path.is_dir():
        file_path = file_path / "index.html"
    if not file_path.is_file():
        return False

    content = file_path.read_bytes()
    content_type = "text/html"
    if normalized.endswith(".js"):
        content_type = "application/javascript"
    elif normalized.endswith(".css"):
        content_type = "text/css"
    elif normalized.endswith(".json"):
        content_type = "application/json"

    response = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: " + content_type.encode() + b"\r\n"
        b"Content-Length: " + str(len(content)).encode() + b"\r\n"
        b"Connection: close\r\n"
        b"\r\n" + content
    )
    sock.sendall(response)
    return True


def handle_request(sock: socket.socket) -> None:
    try:
        request = sock.recv(8192).decode("utf-8", errors="replace")
        if not request:
            return
        lines = request.split("\r\n")
        if not lines:
            return
        method, raw_path, _ = lines[0].split(" ", 2)
        path = raw_path.split("?")[0].split(" ")[0]
        if method != "GET":
            sock.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return

        if path == "/usage":
            try:
                idx_file = VIEWER_DIR / "usage.json"
                if idx_file.exists():
                    data = json.dumps({"ok": True, **json.loads(idx_file.read_text())}).encode()
                else:
                    data = b'{"ok": false}'
            except Exception:
                data = b'{"ok": false}'
            resp = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Connection: close\r\n"
                b"\r\n" + data
            )
            sock.sendall(resp)
            return

        if path == "/api/health":
            data = handle_api_health()
            resp = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Connection: close\r\n"
                b"\r\n" + data
            )
            sock.sendall(resp)
            return

        if path == "/api/role-status":
            data = handle_api_role_status()
            resp = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Connection: close\r\n"
                b"\r\n" + data
            )
            sock.sendall(resp)
            return

        if path == "/api/help":
            data = handle_api_help()
            resp = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Connection: close\r\n"
                b"\r\n" + data
            )
            sock.sendall(resp)
            return

        if serve_file(sock, path):
            return

        body = b"404 Not Found"
        sock.sendall(
            b"HTTP/1.1 404 Not Found\r\n"
            b"Content-Type: text/plain\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Connection: close\r\n"
            b"\r\n" + body,
        )
    except Exception:
        pass
    finally:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        sock.close()


def main() -> None:
    os.chdir(PROJECT_ROOT)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((VIEWER_HOST, PORT))
    server.listen(50)
    print(f"Viewer running at http://127.0.0.1:{PORT}/viewer/")
    print(f"API: /api/health, /api/role-status, /api/help")
    try:
        while True:
            client_sock, _ = server.accept()
            t = threading.Thread(target=handle_request, args=(client_sock,), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
