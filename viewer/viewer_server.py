#!/usr/bin/env python3
"""
Minimal combined viewer + API server using raw sockets.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import glob
import threading
import socket
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Import kanban store
import kanban_store

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
CONVERSATIONS_DIR = VIEWER_DIR / "conversations"
CONVERSATIONS_TMP_DIR = CONVERSATIONS_DIR / ".tmp"
CONVERSATIONS_CORRUPT_DIR = CONVERSATIONS_DIR / ".corrupt"
MULTI_CHAT_MODELS = ["minimax", "gemma", "gpt"]
MULTI_CHAT_SCHEMA_VERSION = 1
MAX_TURNS = 40
MAX_RESPONSE_CHARS = 8000
MAX_THREAD_BYTES = 2 * 1024 * 1024
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()

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
        "scout-dev": "codex",
        "helper": "helper",
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
            return {"key": key, "label": label, "status": "amber", "age": "-", "summary": f"No recent {label} session", "session_key": "-"}

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
            "summary": f"Session {session_short}...",
            "session_key": session_key,
        }

    result = {
        "roles": [
            build_role("silverhand", "SilverHand"),
            build_role("handy", "Handy"),
            build_role("scout", "Scout"),
            build_role("wiser", "Wiser"),
            build_role("scout-dev", "Codex"),
            build_role("helper", "Helper"),
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
    agents = ["main", "codex", "qa", "helper"]
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
    for agent in ["main", "codex", "qa", "dev", "wiser", "helper"]:
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


def _get_openrouter_status() -> dict:
    """Check OpenRouter API key status and free tier rate limits."""
    # Read key from openclaw.json environmentVariables
    try:
        import pathlib
        cfg = json.load(open(pathlib.Path.home() / ".openclaw/openclaw.json"))
        api_key = cfg.get("env", {}).get("OPENROUTER_API_KEY", "")
    except Exception:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")

    if not api_key or api_key == "OPENROUTER_API_KEY":
        return {"status": "no_key", "message": "API key not set", "daily_limit_ok": None, "requests_today": None}

    try:
        # Quick viability probe — does not consume quota
        import urllib.request
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        key_data = data.get("data", {})
        return {
            "status": "ok",
            "message": f"Key: {api_key[:12]}...",
            "daily_limit_ok": True,
            "requests_today": key_data.get("usage", 0),
            "limit": key_data.get("limit", "N/A"),
        }
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            err_data = json.loads(err_body)
            msg = err_data.get("error", {}).get("message", str(e))
        except Exception:
            msg = str(e)
        is_rate_limit = "rate limit" in msg.lower() or "429" in msg
        return {
            "status": "rate_limited" if is_rate_limit else "error",
            "message": msg,
            "daily_limit_ok": not is_rate_limit,
            "requests_today": None,
            "limit": None,
        }
    except Exception as e:
        return {"status": "unreachable", "message": str(e), "daily_limit_ok": None, "requests_today": None}


def _get_ollama_usage() -> dict:
    """Get last used time for Ollama models from session history."""
    now_ms = datetime.now().timestamp() * 1000
    ONE_DAY = 86400000
    result = {}

    # Check all agents for gemma usage
    for agent in ["main", "codex", "qa", "helper"]:
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


def _get_qa_gemma_sessions() -> list:
    """Get QA agent gemma sessions with lastUsed timestamps."""
    sessions_file = Path("/Users/lhaclaw/.openclaw/agents/qa/sessions/sessions.json")
    if not sessions_file.exists():
        return []
    try:
        data = json.loads(sessions_file.read_text())
        return [
            {"model": v.get("model", ""), "lastUsed": v.get("updatedAt", 0)}
            for v in data.values()
            if "gemma" in v.get("model", "").lower()
        ]
    except Exception:
        return []


def _recent_sessions() -> dict:
    """Get the 5 most recent sessions across all agents."""
    now_ms = datetime.now().timestamp() * 1000
    ONE_WEEK = 604800000
    all_sessions = []

    for agent in ["main", "codex", "qa", "helper"]:
        sessions_file = Path(f"/Users/lhaclaw/.openclaw/agents/{agent}/sessions/sessions.json")
        if sessions_file.exists():
            try:
                with open(sessions_file) as f:
                    data = json.load(f)
                for sid, val in data.items():
                    updated = val.get("updatedAt", 0)
                    age = now_ms - updated
                    if age < ONE_WEEK and ':openai:' not in sid:
                        all_sessions.append({
                            "agent": agent,
                            "id": sid,
                            "updatedAt": updated,
                            "age_ms": age,
                            "model": val.get("model", "-"),
                            "status": val.get("status", "-"),
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
        "qa_gemma_sessions": _get_qa_gemma_sessions(),
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    result = json.dumps(data).encode()
    _HEALTH_CACHE = {"data": result, "ts": now}
    return result


def handle_api_role_status() -> bytes:
    return json.dumps(_role_status()).encode()


def handle_api_model_usage() -> bytes:
    return json.dumps(_get_model_usage()).encode()


def handle_api_openrouter_status() -> bytes:
    return json.dumps(_get_openrouter_status()).encode()



def _latest_message() -> dict:
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


def handle_api_kanban(post_body: bytes) -> bytes:
    """Kanban board API — GET returns board, POST handles actions."""
    try:
        body = json.loads(post_body.decode("utf-8"))
    except Exception:
        # GET request — return full board
        board = kanban_store.get_board()
        return json.dumps(board).encode()

    action = body.get("action", "")

    if action == "upsert":
        card_data = body.get("card", {})
        column_id = body.get("column_id", "backlog")
        try:
            card = kanban_store.upsert_card(column_id, card_data)
            board = kanban_store.get_board()
            return json.dumps(board).encode()
        except (ValueError, IOError) as e:
            return json.dumps({"error": str(e)}).encode()

    elif action == "move":
        card_id = body.get("card_id", "")
        to_column = body.get("to_column", "")
        to_index = body.get("to_index")
        try:
            kanban_store.move_card(card_id, to_column, to_index)
            board = kanban_store.get_board()
            return json.dumps(board).encode()
        except (ValueError, IOError) as e:
            return json.dumps({"error": str(e)}).encode()

    elif action == "delete":
        card_id = body.get("card_id", "")
        kanban_store.delete_card(card_id)
        board = kanban_store.get_board()
        return json.dumps(board).encode()

    else:
        # Unknown action → return full board
        board = kanban_store.get_board()
        return json.dumps(board).encode()


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


def _ensure_multi_chat_dirs() -> None:
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    CONVERSATIONS_TMP_DIR.mkdir(parents=True, exist_ok=True)
    CONVERSATIONS_CORRUPT_DIR.mkdir(parents=True, exist_ok=True)


def _thread_path(thread_id: str) -> Path:
    return CONVERSATIONS_DIR / f"{thread_id}.json"


def _lock_for(thread_id: str) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(thread_id)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[thread_id] = lock
        return lock


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _new_thread(thread_id: str) -> dict:
    now = _utc_now_iso()
    return {
        "schema_version": MULTI_CHAT_SCHEMA_VERSION,
        "thread_id": thread_id,
        "created_at": now,
        "updated_at": now,
        "models": list(MULTI_CHAT_MODELS),
        "deleted": False,
        "turns": [],
    }


def _truncate_response_text(text: str) -> tuple[str, bool]:
    text = str(text or "")
    suffix = "(truncated)"
    if len(text) <= MAX_RESPONSE_CHARS:
        return text, False
    cutoff = max(0, MAX_RESPONSE_CHARS - len(suffix))
    return text[:cutoff] + suffix, True


def _truncate_turns(turns: list) -> list:
    """Enforce max 40 turns — drop oldest from front."""
    while len(turns) > MAX_TURNS:
        turns.pop(0)
    return turns


def _materialize_model_history(model: str, turns: list) -> list:
    """Build message history for a model by iterating turns."""
    messages = []
    for turn in turns:
        user_text = turn.get("user", {}).get("text", "")
        if user_text:
            messages.append({"role": "user", "content": user_text})
        resp = turn.get("responses", {}).get(model)
        if resp and resp.get("text"):
            messages.append({"role": "assistant", "content": resp["text"]})
    return messages


def _coerce_thread_data_v1(thread_id: str, data: dict) -> dict:
    """Migrate Rev2 flat structure to Rev3 turns array."""
    created_at = str(data.get("created_at") or _utc_now_iso())
    updated_at = str(data.get("updated_at") or created_at)

    shared = data.get("shared_user_messages", [])
    responses_by_model = data.get("responses_by_model", {})

    # Build turns array from flat structure
    turns = []
    num_turns = len(shared)  # each shared message is one turn
    for i in range(num_turns):
        user_entry = shared[i] if i < len(shared) else {}
        responses = {}
        for model in MULTI_CHAT_MODELS:
            model_responses = responses_by_model.get(model, [])
            if i < len(model_responses):
                entry = model_responses[i]
                text, was_truncated = _truncate_response_text(entry.get("text", ""))
                resp_obj = {"text": text, "ts": str(entry.get("ts") or updated_at)}
                if was_truncated or entry.get("truncated"):
                    resp_obj["truncated"] = True
                responses[model] = resp_obj
            else:
                responses[model] = None

        turns.append({
            "turn_index": i,
            "user": {"text": str(user_entry.get("text", "")), "ts": str(user_entry.get("ts") or updated_at)},
            "responses": responses,
        })

    return {
        "schema_version": MULTI_CHAT_SCHEMA_VERSION,
        "thread_id": thread_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "models": list(MULTI_CHAT_MODELS),
        "deleted": bool(data.get("deleted", False)),
        "turns": turns,
    }


def _load_thread(thread_id: str) -> tuple[dict, dict]:
    """Atomic read: validates schema version, handles corruption, returns (data, history_reset)."""
    _ensure_multi_chat_dirs()
    path = _thread_path(thread_id)
    history_reset = {model: False for model in MULTI_CHAT_MODELS}

    if not path.exists():
        return _new_thread(thread_id), history_reset

    if path.stat().st_size > MAX_THREAD_BYTES:
        raise ValueError("thread_too_large")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        # Corruption: rename to .corrupt/, start fresh
        corrupt_path = CONVERSATIONS_CORRUPT_DIR / f"{thread_id}.json"
        if corrupt_path.exists():
            corrupt_path = CONVERSATIONS_CORRUPT_DIR / f"{thread_id}-{int(time.time())}.json"
        shutil.move(str(path), str(corrupt_path))
        history_reset = {model: True for model in MULTI_CHAT_MODELS}
        return _new_thread(thread_id), history_reset

    schema = data.get("schema_version")
    if schema != MULTI_CHAT_SCHEMA_VERSION:
        # Unknown version: rename to .corrupt/, start fresh
        backup = path.with_suffix(path.suffix + f".bak")
        if backup.exists():
            backup = path.with_suffix(path.suffix + f".{int(time.time())}.bak")
        shutil.move(str(path), str(backup))
        history_reset = {model: True for model in MULTI_CHAT_MODELS}
        return _new_thread(thread_id), history_reset

    # Check for Rev2 flat structure and migrate
    if "turns" not in data:
        return _coerce_thread_data_v1(thread_id, data), history_reset

    return data, history_reset


def _save_thread(thread_id: str, data: dict) -> None:
    """Atomic write: tmp file + fsync + rename."""
    _ensure_multi_chat_dirs()
    data["updated_at"] = _utc_now_iso()
    encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    if len(encoded) > MAX_THREAD_BYTES:
        raise ValueError("thread_too_large")

    tmp_path = CONVERSATIONS_TMP_DIR / f"{thread_id}.json.tmp"
    final_path = _thread_path(thread_id)

    with open(tmp_path, "wb") as fh:
        fh.write(encoded)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, final_path)


def _validate_thread_id(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except Exception:
        return None


def _call_model_threaded(fn, message: str, history: list, results: list) -> None:
    fn(message, history, results)


def handle_api_multi_chat(sock: socket.socket, post_body: bytes) -> None:
    try:
        body = json.loads(post_body.decode("utf-8"))
    except Exception:
        _json_response(sock, 400, {"error": "bad request"})
        return

    message = str(body.get("message", "")).strip()
    if not message:
        _json_response(sock, 400, {"error": "empty message"})
        return

    request_id = str(body.get("request_id", "")).strip() or str(uuid.uuid4())
    incoming_thread_id = body.get("thread_id")
    thread_id = _validate_thread_id(incoming_thread_id) if incoming_thread_id else str(uuid.uuid4())
    if incoming_thread_id and not thread_id:
        _json_response(sock, 400, {"error": "invalid thread_id"})
        return

    lock = _lock_for(thread_id)
    with lock:
        try:
            thread, history_reset = _load_thread(thread_id)
        except ValueError as exc:
            if str(exc) == "thread_too_large":
                path = _thread_path(thread_id)
                size = path.stat().st_size if path.exists() else 0
                _json_response(sock, 413, {"error": "Thread too large", "current_size_bytes": size, "thread_id": thread_id})
                return
            raise

        # Check durable deleted flag
        if thread.get("deleted", False):
            _json_response(sock, 409, {"error": "thread deleted", "thread_id": thread_id})
            return

        # Check request_id cache for idempotency
        # Search existing turns for this request_id
        for turn in thread.get("turns", []):
            cached_req = turn.get("request_id")
            if cached_req and cached_req == request_id:
                cached_results = []
                for model in MULTI_CHAT_MODELS:
                    resp = turn.get("responses", {}).get(model)
                    if resp and resp.get("text"):
                        cached_results.append({
                            "model": model,
                            "content": resp["text"],
                            "done": True,
                        })
                    else:
                        cached_results.append({"model": model, "content": "", "done": True, "error": True})
                _json_response(sock, 200, {
                    "results": cached_results,
                    "thread_id": thread_id,
                    "history_reset": history_reset,
                })
                return

        # Truncate before adding new turn
        _truncate_turns(thread.setdefault("turns", []))

        # Compute next turn_index
        existing_turns = thread.get("turns", [])
        next_index = (existing_turns[-1]["turn_index"] + 1) if existing_turns else 0

        # Add new turn with null responses (filled after model calls)
        new_turn = {
            "turn_index": next_index,
            "user": {"text": message, "ts": _utc_now_iso()},
            "responses": {model: None for model in MULTI_CHAT_MODELS},
            "request_id": request_id,
        }
        thread["turns"].append(new_turn)

        # Call all 3 models in parallel with materialized history
        results = []
        threads = []
        for model, fn_model in (("gemma", _call_gemma), ("minimax", _call_minimax), ("gpt", _call_gpt)):
            history = _materialize_model_history(model, thread["turns"])
            t = threading.Thread(target=_call_model_threaded, args=(fn_model, message, history, results))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=65)

        # Collect results and fill in responses
        by_model = {item.get("model"): item for item in results if isinstance(item, dict)}
        final_results = []
        for model in MULTI_CHAT_MODELS:
            raw = by_model.get(model) or {"model": model, "content": "", "done": True, "error": True}
            text, was_truncated = _truncate_response_text(raw.get("content", ""))
            result_entry = {
                "model": model,
                "content": text,
                "done": bool(raw.get("done", True)),
            }
            if raw.get("error"):
                result_entry["error"] = True
            if was_truncated:
                result_entry["truncated"] = True
            final_results.append(result_entry)

            response_entry = {"text": text, "ts": _utc_now_iso()}
            if was_truncated:
                response_entry["truncated"] = True
            thread["turns"][-1]["responses"][model] = response_entry

        # Truncate again to enforce max 40
        _truncate_turns(thread["turns"])

        # Re-check deleted flag after model calls (DELETE may have occurred)
        if thread.get("deleted", False):
            _json_response(sock, 409, {"error": "thread deleted", "thread_id": thread_id})
            return

        try:
            _save_thread(thread_id, thread)
        except ValueError as exc:
            if str(exc) == "thread_too_large":
                path = _thread_path(thread_id)
                size = path.stat().st_size if path.exists() else 0
                _json_response(sock, 413, {"error": "Thread too large", "current_size_bytes": size, "thread_id": thread_id})
                return
            raise

        _json_response(sock, 200, {
            "results": final_results,
            "thread_id": thread_id,
            "history_reset": history_reset,
        })


def handle_api_multi_chat_get(sock: socket.socket, thread_id: str) -> None:
    validated = _validate_thread_id(thread_id)
    if not validated:
        _json_response(sock, 400, {"error": "invalid thread_id"})
        return
    thread_id = validated

    lock = _lock_for(thread_id)
    with lock:
        try:
            thread, history_reset = _load_thread(thread_id)
        except ValueError as exc:
            if str(exc) == "thread_too_large":
                path = _thread_path(thread_id)
                size = path.stat().st_size if path.exists() else 0
                _json_response(sock, 413, {"error": "thread too large", "current_size_bytes": size})
                return
            raise

        if thread.get("deleted", False):
            _json_response(sock, 409, {"error": "thread deleted", "thread_id": thread_id})
            return

        payload = dict(thread)
        payload["history_reset"] = history_reset
        _json_response(sock, 200, payload)


def handle_api_multi_chat_delete(sock: socket.socket, thread_id: str) -> None:
    validated = _validate_thread_id(thread_id)
    if not validated:
        _json_response(sock, 400, {"error": "invalid thread_id"})
        return
    thread_id = validated

    lock = _lock_for(thread_id)
    with lock:
        # Idempotent: check durable deleted flag first
        try:
            thread, _ = _load_thread(thread_id)
        except ValueError:
            pass

        if thread.get("deleted", False):
            # Already deleted — return 204 immediately
            _json_response_no_content(sock, 204)
            return

        # Set durable tombstone
        thread["deleted"] = True
        path = _thread_path(thread_id)
        try:
            if path.exists():
                _save_thread(thread_id, thread)
                path.unlink()
        except Exception:
            pass

        _json_response_no_content(sock, 204)


def _json_response_no_content(sock: socket.socket, status: int) -> None:
    reasons = {204: "No Content", 400: "Bad Request", 404: "Not Found", 409: "Conflict", 413: "Payload Too Large", 500: "Internal Server Error"}
    reason = reasons.get(status, "OK")
    hdrs = (
        f"HTTP/1.1 {status} {reason}\r\n".encode()
        + b"Access-Control-Allow-Origin: *\r\n"
        + b"Connection: close\r\n"
        + b"\r\n"
    )
    try:
        sock.sendall(hdrs)
    except Exception:
        pass


def _json_response(sock: socket.socket, status: int, data: dict) -> None:
    encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
    reasons = {
        200: "OK",
        400: "Bad Request",
        404: "Not Found",
        409: "Conflict",
        413: "Payload Too Large",
        500: "Internal Server Error",
    }
    reason = reasons.get(status, "OK")
    hdrs = (
        f"HTTP/1.1 {status} {reason}\r\n".encode()
        + b"Content-Type: application/json\r\n"
        + b"Content-Length: " + str(len(encoded)).encode() + b"\r\n"
        + b"Access-Control-Allow-Origin: *\r\n"
        + b"Connection: close\r\n"
        + b"\r\n"
    )
    try:
        sock.sendall(hdrs + encoded)
    except Exception:
        pass


def _call_gemma(message: str, history: list, out_q: list) -> None:
    """Call Ollama Gemma and put result in out_q."""
    try:
        payload = {
            "model": "gemma4:e4b",
            "messages": history,
            "stream": False
        }
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", "http://127.0.0.1:11434/api/chat",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload),
             "--max-time", "90"],
            capture_output=True, text=True, timeout=95
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
        
        payload = {
            "model": "openclaw",
            "messages": history,
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
        
        payload = {
            "model": "openclaw/codex",
            "messages": history,
            "stream": False,
            "max_tokens": 1024
        }

        r = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "http://127.0.0.1:18789/v1/chat/completions",
             "-H", "Content-Type: application/json",
             "-H", f"Authorization: Bearer {gateway_token}",
             "-d", json.dumps(payload),
             "--max-time", "120"],
            capture_output=True, text=True, timeout=65, stdin=subprocess.DEVNULL
        )

        if r.returncode == 0:
            try:
                data = json.loads(r.stdout)
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    out_q.append({"model": "gpt", "content": content, "done": True})
                else:
                    out_q.append({"model": "gpt", "content": f"No response: {r.stdout[:200]}", "done": True, "error": True})
            except json.JSONDecodeError:
                out_q.append({"model": "gpt", "content": f"Parse error: {r.stdout[:200]}", "done": True, "error": True})
        else:
            out_q.append({"model": "gpt", "content": f"curl error {r.returncode}: {r.stderr[:200]}", "done": True, "error": True})
    except Exception as e:
        out_q.append({"model": "gpt", "content": f"Error: {e}", "done": True, "error": True})



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

        # Extract POST body - for small bodies it's already in the initial recv(8192)
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

        if path == "/api/openrouter-status":
            data = handle_api_openrouter_status()
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

        # Kanban board API
        if path == "/api/kanban":
            if method == "POST":
                data = handle_api_kanban(post_body)
            else:
                data = handle_api_kanban(b"")  # GET → returns full board
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

        # POST: s2-register - post-spawn registration (SilverHand calls this after each spawn)
        # Body: { "task_key": "handy-url-ingestion", "role": "dev", "session_key": "agent:dev:subagent:..." }
        if path == "/api/s2-register" and method == "POST":
            try:
                body = json.loads(post_body.decode("utf-8"))
                task_key = body.get("task_key", "")
                role = body.get("role", "")
                session_key = body.get("session_key", "")
                if not task_key or not role or not session_key:
                    data = json.dumps({"ok": False, "error": "task_key, role, session_key required"}).encode()
                else:
                    task_ids = _load_json(TASK_IDS_FILE)
                    # Store as task_key → {session_key, role, spawned_at}
                    task_ids[task_key] = {
                        "session_key": session_key,
                        "role": role,
                        "spawned_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
                    }
                    TASK_IDS_FILE.write_text(json.dumps(task_ids, indent=2))
                    data = json.dumps({"ok": True, "message": f"Registered {task_key} → {session_key}"}).encode()
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

        # POST: spawn-gate - check for duplicate before creating a session
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

        multi_chat_match = re.fullmatch(r"/api/multi-chat/([0-9a-fA-F-]+)", path)
        if multi_chat_match:
            thread_id = _validate_thread_id(multi_chat_match.group(1))
            if not thread_id:
                _json_response(sock, 400, {"error": "invalid thread_id"})
                return
            if method == "GET":
                handle_api_multi_chat_get(sock, thread_id)
                return
            if method == "DELETE":
                handle_api_multi_chat_delete(sock, thread_id)
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
    _ensure_multi_chat_dirs()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    server.bind((VIEWER_HOST, PORT))
    server.listen(50)
    print(f"Viewer running at http://127.0.0.1:{PORT}/viewer/")
    print(f"API: /api/health, /api/role-status, /api/openrouter-status, /api/help")
    try:
        while True:
            client_sock, _ = server.accept()
            t = threading.Thread(target=handle_request, args=(client_sock,), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
