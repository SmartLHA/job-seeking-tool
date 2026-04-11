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
import time
from concurrent.futures import ThreadPoolExecutor
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

# Cache for expensive health check (10s TTL)
_HEALTH_CACHE = {"data": None, "ts": 0.0}
_HEALTH_TTL = 30.0


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
        "handy": "dev",
        "scout": "qa",
        "wiser": "wiser",
        "scout-dev": "dev",
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
            build_role("wiser", "Wiser"),
            build_role("scout-dev", "Scout-Dev"),
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

def _get_model_usage() -> dict:
    """Get token usage per model over the past 5 hours across all agents."""
    now_ms = datetime.now().timestamp() * 1000
    FIVE_HOURS = 5 * 3600000
    result = {}
    for agent in ["main", "codex", "qa", "dev", "wiser"]:
        sessions_file = Path(f"/Users/lhaclaw/.openclaw/agents/{agent}/sessions/sessions.json")
        if not sessions_file.exists():
            continue
        try:
            with open(sessions_file) as f:
                data = json.load(f)
            for val in data.values():
                updated = val.get("updatedAt", 0)
                if now_ms - updated > FIVE_HOURS:
                    continue
                model = val.get("model", "")
                if not model:
                    continue
                key = model.replace("minimax/", "").replace("ollama/", "")
                inp = val.get("inputTokens", 0) or 0
                out = val.get("outputTokens", 0) or 0
                tot = inp + out
                if key not in result:
                    result[key] = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0, "count": 0}
                result[key]["inputTokens"] += inp
                result[key]["outputTokens"] += out
                result[key]["totalTokens"] += tot
                result[key]["count"] += 1
        except Exception:
            pass
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
                            "inputTokens": val.get("inputTokens", 0) or 0,
                            "outputTokens": val.get("outputTokens", 0) or 0,
                            "totalTokens": val.get("totalTokens", 0) or 0,
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
                "inputTokens": s.get("inputTokens", 0),
                "outputTokens": s.get("outputTokens", 0),
                "totalTokens": s.get("totalTokens", 0),
            }
            for s in recent
        ],
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }


def handle_api_health() -> bytes:
    global _HEALTH_CACHE
    now = time.time()
    if _HEALTH_CACHE["data"] is not None and (now - _HEALTH_CACHE["ts"]) < _HEALTH_TTL:
        return _HEALTH_CACHE["data"]

    # Shared result dict for thread-safe parallel collection
    results = {"ollama": None, "openclaw": None, "cron": None}

    def fetch_ollama():
        try:
            api_result = subprocess.run(
                ["curl", "-s", "http://127.0.0.1:11434/api/tags"],
                capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL
            )
            list_result = subprocess.run(
                ["ollama", "list"], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL
            )
            available = []
            if api_result.returncode == 0:
                for m in json.loads(api_result.stdout).get("models", []):
                    available.append({"name": m.get("name", "?"), "size": m.get("size", 0), "details": m.get("details", {})})
            running = []
            for line in list_result.stdout.split("\n"):
                if line.strip() and not line.startswith("NAME") and "running" in line:
                    parts = re.split(r"\s+", line.strip())
                    if parts:
                        running.append(parts[0])
            results["ollama"] = {"available": available, "running": running, "error": None}
        except Exception as e:
            results["ollama"] = {"available": [], "running": [], "error": str(e)}

    def fetch_openclaw_status():
        try:
            status = _openclaw_status()
            if isinstance(status, dict) and status.get("ok") is not False:
                results["openclaw"] = {
                    "default_model": status.get("model"),
                    "sessions": status.get("sessions", []),
                    "error": None,
                }
            else:
                results["openclaw"] = {"default_model": None, "sessions": [], "error": None}
        except Exception as e:
            results["openclaw"] = {"default_model": None, "sessions": [], "error": str(e)}

    def fetch_cron():
        try:
            cron_result = subprocess.run(
                ["/opt/homebrew/bin/openclaw", "cron", "list", "--json"],
                capture_output=True, text=True, timeout=15,
                stdin=subprocess.DEVNULL,
                env=dict(os.environ, PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"),
            )
            cron_data = json.loads(cron_result.stdout) if cron_result.returncode == 0 else {}
            cron_list = cron_data.get("jobs", [])
            results["cron"] = [
                {
                    "name": j.get("name", "?"),
                    "last_run": j.get("state", {}).get("lastRunAtMs"),
                    "last_status": j.get("state", {}).get("lastRunStatus", "?"),
                    "error": j.get("state", {}).get("lastError"),
                }
                for j in cron_list
            ]
        except Exception:
            results["cron"] = []

    # Run all 3 slow calls in parallel
    with ThreadPoolExecutor(max_workers=3) as executor:
        executor.submit(fetch_ollama)
        executor.submit(fetch_openclaw_status)
        executor.submit(fetch_cron)

    data = {
        "ollama": results.get("ollama") or {"available": [], "running": [], "error": None},
        "openclaw": results.get("openclaw") or {"default_model": None, "sessions": [], "error": None},
        "cron_jobs": results.get("cron") or [],
        "active_sessions": _get_active_sessions(),
        "ollama_usage": _get_ollama_usage(),
        "model_usage": _get_model_usage(),
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    result = json.dumps(data).encode()
    _HEALTH_CACHE = {"data": result, "ts": now}
    return result


def handle_api_role_status() -> bytes:
    return json.dumps(_role_status()).encode()


def handle_api_model_usage() -> bytes:
    return json.dumps(_get_model_usage()).encode()


    """Get the 3 most recent meaningful messages from the main session."""
    try:
        sessions_file = Path(f"/Users/lhaclaw/.openclaw/agents/main/sessions/sessions.json")
        if not sessions_file.exists():
            return {"messages": [{"text": "All systems operational.", "error": None}], "error": None}
        with open(sessions_file) as f:
            data = json.load(f)
        sorted_sessions = sorted(data.items(), key=lambda x: x[1].get("updatedAt", 0), reverse=True)
        main_sessions = [(k, v) for k, v in sorted_sessions if k.startswith("agent:main:")]
        if not main_sessions:
            return {"messages": [{"text": "All systems operational.", "error": None}], "error": None}

        results = []
        # Check most recent 3 main sessions
        for session_key, session_val in main_sessions[:3]:
            sid = session_val.get("sessionId", "")
            jsonl_pattern = f"/Users/lhaclaw/.openclaw/agents/main/sessions/{sid}*.jsonl"
            files = glob.glob(jsonl_pattern)
            if not files:
                continue
            jsonl_path = files[0]
            lines = open(jsonl_path).readlines()
            # Scan from end for last assistant text message
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
                        text_parts = []
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                text_parts.append(c.get("text", ""))
                        content = " ".join(text_parts)
                    if content and content.strip():
                        stripped = content.strip()
                        if stripped.startswith("<<<"):
                            continue
                        # Get age from session
                        age_ms = session_val.get("updatedAt", 0)
                        now_ms = datetime.now().timestamp() * 1000
                        ago_ms = now_ms - age_ms
                        mins = int(ago_ms / 60000)
                        hours = int(ago_ms / 3600000)
                        days = int(ago_ms / 86400000)
                        if days > 0:
                            age_str = f"{days}d ago"
                        elif hours > 0:
                            age_str = f"{hours}h ago"
                        else:
                            age_str = f"{mins}m ago"
                        results.append({"text": stripped[:500], "age": age_str, "session": session_key.split(":")[-1][:12], "error": None})
                        break
                except Exception:
                    continue
            if len(results) >= 3:
                break

        if not results:
            return {"messages": [{"text": "All systems operational.", "error": None}], "error": None}
        return {"messages": results, "error": None}
    except Exception as e:
        return {"messages": [{"text": "All systems operational.", "error": str(e)}], "error": str(e)}


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


def _send_sse_event(sock: socket.socket, model: str, content: str, done: bool) -> None:
    """Send one SSE event as a single HTTP chunk."""
    event_id = f"{model}-{time.time()}"
    event_text = (
        f"event: message\r\n"
        f"id: {event_id}\r\n"
        f"data: {json.dumps({'model': model, 'content': content, 'done': done})}\r\n"
        f"\r\n"
    )
    encoded = event_text.encode("utf-8")
    try:
        sock.sendall(f"{len(encoded):x}\r\n".encode())
        sock.sendall(encoded)
        sock.sendall(b"\r\n")
    except Exception:
        pass


def _call_gemma(message: str, history: list, out_q: list) -> None:
    """Call Ollama Gemma and put result in out_q."""
    try:
        # Build Ollama messages format
        ollama_msgs = history + [{'role': 'user', 'content': message}]
        payload = {
            "model": "gemma4:e4b",
            "messages": ollama_msgs,
            "stream": False
        }
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", "http://127.0.0.1:11434/api/chat",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload),
             "--max-time", "60"],
            capture_output=True, text=True, timeout=65
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            content = data.get("message", {}).get("content", "")
            out_q.append({"model": "gemma", "content": content, "done": True})
        else:
            out_q.append({"model": "gemma", "content": f"Error: curl exit {r.returncode}", "done": True, "error": True})
    except Exception as e:
        out_q.append({"model": "gemma", "content": f"Error: {e}", "done": True, "error": True})


def _call_minimax(message: str, history: list, out_q: list) -> None:
    """Call MiniMax-M2.7 via gateway's OpenAI-compatible /v1/chat/completions endpoint."""
    try:
        gateway_token = "8184f5fc629903f19ff5dfaffc456950bbcc3a96b56fc6ad"
        
        # Build messages including history
        msgs = []
        for h in history:
            msgs.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        msgs.append({"role": "user", "content": message})
        
        payload = {
            "model": "openclaw",
            "messages": msgs,
            "max_tokens": 1024
        }
        
        r = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "http://127.0.0.1:18789/v1/chat/completions",
             "-H", "Content-Type: application/json",
             "-H", f"Authorization: Bearer {gateway_token}",
             "-d", json.dumps(payload),
             "--max-time", "45"],
            capture_output=True, text=True, timeout=50, stdin=subprocess.DEVNULL
        )
        
        if r.returncode == 0:
            try:
                data = json.loads(r.stdout)
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    out_q.append({"model": "minimax", "content": content, "done": True})
                else:
                    out_q.append({"model": "minimax", "content": f"No response: {r.stdout[:200]}", "done": True, "error": True})
            except json.JSONDecodeError:
                out_q.append({"model": "minimax", "content": f"Parse error: {r.stdout[:200]}", "done": True, "error": True})
        else:
            out_q.append({"model": "minimax", "content": f"curl error {r.returncode}: {r.stderr[:200]}", "done": True, "error": True})
    except Exception as e:
        out_q.append({"model": "minimax", "content": f"Error: {e}", "done": True, "error": True})


def _call_gpt(message: str, history: list, out_q: list) -> None:
    """Call GPT-5.4 via gateway's OpenAI-compatible endpoint using openclaw/codex (Codex agent)."""
    try:
        gateway_token = "8184f5fc629903f19ff5dfaffc456950bbcc3a96b56fc6ad"
        
        msgs = []
        for h in history:
            msgs.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        msgs.append({"role": "user", "content": message})
        
        payload = {
            "model": "openclaw/codex",
            "messages": msgs,
            "stream": True,
            "max_tokens": 1024
        }
        
        r = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "http://127.0.0.1:18789/v1/chat/completions",
             "-H", "Content-Type: application/json",
             "-H", f"Authorization: Bearer {gateway_token}",
             "-d", json.dumps(payload),
             "--max-time", "60"],
            capture_output=True, text=True, timeout=65, stdin=subprocess.DEVNULL
        )
        
        if r.returncode == 0:
            # Parse SSE streaming response
            content = ""
            for line in r.stdout.split("\n"):
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]" or not data_str:
                        continue
                    try:
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            content += delta
                    except json.JSONDecodeError:
                        pass
            out_q.append({"model": "gpt", "content": content or r.stdout[:200], "done": True})
        else:
            out_q.append({"model": "gpt", "content": f"curl error {r.returncode}: {r.stderr[:200]}", "done": True, "error": True})
    except Exception as e:
        out_q.append({"model": "gpt", "content": f"Error: {e}", "done": True, "error": True})


def handle_api_multi_chat(sock: socket.socket, post_body: bytes) -> None:
    """Stream a multi-LLM chat response via SSE.
    POST body: {"message": "...", "history": [...]}
    SSE stream: one event per model as it completes.
    """
    try:
        body = json.loads(post_body.decode("utf-8"))
    except Exception:
        sock.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        return

    message = body.get("message", "")
    history = body.get("history", [])

    if not message:
        sock.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        return

    # SSE header: chunked transfer
    hdrs = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/event-stream\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"Access-Control-Allow-Origin: *\r\n"
        b"Cache-Control: no-cache\r\n"
        b"Connection: keepalive\r\n"
        b"\r\n"
    )
    sock.sendall(hdrs)

    # Queue for results from 3 threads
    results = []
    results_lock = threading.Lock()

    def synchronized_append(r):
        with results_lock:
            results.append(r)
            # Notify main thread by sending a ping through the socket
            # We'll poll the results list instead

    # Start 3 concurrent threads
    threads = [
        threading.Thread(target=_call_gemma, args=(message, history, results)),
        threading.Thread(target=_call_minimax, args=(message, history, results)),
        threading.Thread(target=_call_gpt, args=(message, history, results)),
    ]

    for t in threads:
        t.start()

    # Poll for results and stream them as they arrive
    sent = set()
    while any(t.is_alive() for t in threads) or len(sent) < len(results):
        with results_lock:
            for r in results:
                rid = id(r)
                if rid not in sent:
                    sent.add(rid)
                    _send_sse_event(sock, r["model"], r["content"], r.get("done", True))
        if len(sent) >= 3:
            break
        time.sleep(0.2)

    # Final flush
    with results_lock:
        for r in results:
            rid = id(r)
            if rid not in sent:
                sent.add(rid)
                _send_sse_event(sock, r["model"], r["content"], r.get("done", True))

    # SSE stream terminator: final blank chunk
    try:
        sock.sendall(b"0\r\n\r\n")
    except Exception:
        pass

    # Wait for threads to finish
    for t in threads:
        t.join(timeout=5)


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

        if path == "/api/model-usage":
            data = handle_api_model_usage()
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

        if path == "/api/multi-chat" and method == "POST":
            handle_api_multi_chat(sock, post_body)
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
