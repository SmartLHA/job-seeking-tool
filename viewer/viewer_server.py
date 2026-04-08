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

def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


VIEWER_DIR = Path(__file__).parent.resolve()
TASK_IDS_FILE = VIEWER_DIR / "task_ids.json"
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


def _get_active_sessions() -> dict:
    """Get session counts per agent: total, active 2h, recent 5m."""
    now_ms = datetime.now().timestamp() * 1000
    TWO_HOURS = 7200000
    FIVE_MINS = 300000
    agents = ["main", "codex", "qa"]
    result = {}
    for agent in agents:
        sessions_file = Path(f"/Users/lhaclaw/.openclaw/agents/{agent}/sessions/sessions.json")
        total = 0
        active_2h = 0
        recent_5m = 0
        if sessions_file.exists():
            try:
                with open(sessions_file) as f:
                    data = json.load(f)
                for val in data.values():
                    updated = val.get("updatedAt", 0)
                    total += 1
                    age = now_ms - updated
                    if age < TWO_HOURS:
                        active_2h += 1
                    if age < FIVE_MINS:
                        recent_5m += 1
            except Exception:
                pass
        result[agent] = {"total": total, "active_2h": active_2h, "recent_5m": recent_5m}
    return result


def _get_ollama_usage() -> dict:
    """Get last used time for Ollama models from session history."""
    now_ms = datetime.now().timestamp() * 1000
    ONE_DAY = 86400000
    result = {}
    
    # Check all agents for gemma usage
    for agent in ["main", "codex", "qa"]:
        sessions_file = Path(f"/Users/lhaclaw/.openclaw/agents/{agent}/sessions/sessions.json")
        if sessions_file.exists():
            try:
                with open(sessions_file) as f:
                    data = json.load(f)
                for val in data.values():
                    model = val.get("model", "")
                    if "gemma" in model.lower():
                        updated = val.get("updatedAt", 0)
                        age = now_ms - updated
                        if age < ONE_DAY:
                            # Store as negative age (last used ago)
                            if model not in result or result[model]["ago_ms"] > age:
                                result[model] = {
                                    "ago_ms": age,
                                    "input_tokens": val.get("inputTokens", 0),
                                    "output_tokens": val.get("outputTokens", 0)
                                }
            except Exception:
                pass
    return result


def _recent_sessions() -> dict:
    """Get the 5 most recent sessions across all agents."""
    now_ms = datetime.now().timestamp() * 1000
    ONE_WEEK = 604800000
    all_sessions = []

    for agent in ["main", "codex", "qa"]:
        sessions_file = Path(f"/Users/lhaclaw/.openclaw/agents/{agent}/sessions/sessions.json")
        if sessions_file.exists():
            try:
                with open(sessions_file) as f:
                    data = json.load(f)
                for sid, val in data.items():
                    updated = val.get("updatedAt", 0)
                    age = now_ms - updated
                    if age < ONE_WEEK:
                        all_sessions.append({
                            "agent": agent,
                            "id": sid,
                            "updatedAt": updated,
                            "age_ms": age,
                            "model": val.get("model", "—"),
                            "status": val.get("status", "—"),
                        })
            except Exception:
                pass

    # Sort by updatedAt descending, take 5
    all_sessions.sort(key=lambda x: x["updatedAt"], reverse=True)
    recent = all_sessions[:5]

    return {
        "sessions": [
            {
                "agent": s["agent"],
                "id": s["id"],
                "model": s["model"],
                "age": _age(s["age_ms"]),
                "status": s["status"],
            }
            for s in recent
        ],
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }


def handle_api_health() -> bytes:
    data = {
        "ollama": {"available": [], "running": [], "error": None},
        "openclaw": {"default_model": None, "sessions": [], "error": None},
        "cron_jobs": [],
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    try:
        # Use Ollama API to get detailed model info
        api_result = subprocess.run(
            ["curl", "-s", "http://127.0.0.1:11434/api/tags"],
            capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL
        )
        ollama_available = []
        ollama_running = []
        if api_result.returncode == 0:
            models_data = json.loads(api_result.stdout)
            for m in models_data.get("models", []):
                ollama_available.append({
                    "name": m.get("name", "?"),
                    "size": m.get("size", 0),
                    "details": m.get("details", {})
                })
        # Also check running models via ollama list
        list_result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL
        )
        for line in list_result.stdout.split("\n"):
            if line.strip() and not line.startswith("NAME") and "running" in line:
                parts = re.split(r"\s+", line.strip())
                if len(parts) >= 1:
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

    # Add active session counts (updated within 1 hour)
    data["active_sessions"] = _get_active_sessions()
    
    # Add Ollama model usage from session history
    data["ollama_usage"] = _get_ollama_usage()

    return json.dumps(data).encode()


def handle_api_role_status() -> bytes:
    return json.dumps(_role_status()).encode()


def _latest_message() -> dict:
    """Get the most recent meaningful message from the main session that needs Mic's review."""
    try:
        sessions_file = Path(f"/Users/lhaclaw/.openclaw/agents/main/sessions/sessions.json")
        if not sessions_file.exists():
            return {"text": "All systems operational.", "error": None}
        with open(sessions_file) as f:
            data = json.load(f)
        # Find most recent main session
        sorted_sessions = sorted(data.items(), key=lambda x: x[1].get("updatedAt", 0), reverse=True)
        main_sessions = [(k, v) for k, v in sorted_sessions if k.startswith("agent:main:")]
        if not main_sessions:
            return {"text": "All systems operational.", "error": None}
        session_key, session_val = main_sessions[0]
        # Find the JSONL file
        sid = session_val.get("sessionId", "")
        jsonl_pattern = f"/Users/lhaclaw/.openclaw/agents/main/sessions/{sid}*.jsonl"
        files = glob.glob(jsonl_pattern)
        if not files:
            return {"text": "All systems operational.", "error": None}
        jsonl_path = files[0]
        lines = open(jsonl_path).readlines()
        # Scan from end for last assistant text message (not thinking/toolCall)
        for line in reversed(lines):
            try:
                m = json.loads(line)
                if m.get("type") != "message":
                    continue
                msg = m.get("message", {})
                if msg.get("role") != "assistant":
                    continue
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Extract only text blocks, skip thinking and tool calls
                    text_parts = []
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            text_parts.append(c.get("text", ""))
                    content = " ".join(text_parts)
                if content and content.strip():
                    # Skip if it looks like internal housekeeping
                    stripped = content.strip()
                    if stripped.startswith("<<<"):
                        continue
                    return {"text": stripped[:500], "error": None}  # cap at 500 chars
            except Exception:
                continue
        return {"text": "All systems operational.", "error": None}
    except Exception as e:
        return {"text": "All systems operational.", "error": str(e)}


def handle_api_latest_message() -> bytes:
    return json.dumps(_latest_message()).encode()


def handle_api_recent_sessions() -> bytes:
    return json.dumps(_recent_sessions()).encode()


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
        if method not in ("GET", "POST"):
            sock.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return

        # Extract POST body — for small bodies it's already in the initial recv(8192)
        post_body = b""
        if method == "POST":
            content_length = 0
            body_start = request.find("\r\n\r\n")
            if body_start >= 0:
                header_part = request[:body_start]
                body_start += 4
                for line in header_part.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":", 1)[1].strip())
                        break
                # Body starts right after \r\n\r\n in the request
                if content_length > 0:
                    post_body = request[body_start:body_start + content_length].encode("utf-8")

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

        if path == "/api/recent-sessions":
            data = handle_api_recent_sessions()
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

        if path == "/api/latest-message":
            data = handle_api_latest_message()
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

        # POST: register a task_id for a session
        if path == "/api/register-task-id" and method == "POST":
            try:
                body = json.loads(post_body.decode("utf-8"))
                session_key = body.get("session_key", "")
                task_id = body.get("task_id", "")
                if not session_key or not task_id:
                    data = json.dumps({"ok": False, "error": "session_key and task_id required"}).encode()
                else:
                    task_ids = _load_json(TASK_IDS_FILE)
                    task_ids[session_key] = task_id
                    TASK_IDS_FILE.write_text(json.dumps(task_ids, indent=2))
                    data = json.dumps({"ok": True}).encode()
            except Exception as e:
                data = json.dumps({"ok": False, "error": str(e)}).encode()
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

        # POST: spawn-gate — check for duplicate before creating a session
        # Body: { "role": "handy", "task_id": "T123" }
        # Returns: { "ok": true/false, "duplicate": bool, "existing_session_key": "...", "action": "..." }
        if path == "/api/spawn-gate" and method == "POST":
            try:
                body = json.loads(post_body.decode("utf-8"))
                role = body.get("role", "")
                task_id = body.get("task_id", "")
                if not role:
                    data = json.dumps({"ok": False, "error": "role required"}).encode()
                else:
                    # Map role → agent
                    ROLE_AGENT_MAP = {"handy": "codex", "scout": "qa", "planner": "main", "reviewer": "main"}
                    agent_id = ROLE_AGENT_MAP.get(role, role)
                    sessions_file = Path(f"/Users/lhaclaw/.openclaw/agents/{agent_id}/sessions/sessions.json")
                    task_ids = _load_json(TASK_IDS_FILE)

                    active_sessions = []
                    if sessions_file.exists():
                        with open(sessions_file) as f:
                            sessions_data = json.load(f)
                        now_ms = datetime.now().timestamp() * 1000
                        for sk, sv in sessions_data.items():
                            if sv.get("status") not in ("running", "waiting", "active"):
                                continue
                            stored_task = task_ids.get(sk, "")
                            if task_id and stored_task == task_id:
                                active_sessions.append(sk)

                    if active_sessions:
                        data = json.dumps({
                            "ok": True,
                            "duplicate": True,
                            "existing_session_key": active_sessions[0],
                            "action": "reuse",
                            "message": f"Active {role} session with task_id={task_id} already exists: {active_sessions[0]}"
                        }).encode()
                    else:
                        data = json.dumps({
                            "ok": True,
                            "duplicate": False,
                            "action": "create",
                            "message": f"No duplicate {role} session for task_id={task_id}. Proceed to spawn."
                        }).encode()
            except Exception as e:
                data = json.dumps({"ok": False, "error": str(e)}).encode()
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
