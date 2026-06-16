#!/usr/bin/env python3
"""
Minimal combined viewer + API server using raw sockets.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import re
import shutil
import sqlite3
import subprocess
import glob
import threading
import socket
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import kanban_store
import data_outcomes

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

import sys
# Add src/ to path so viewer_server.py can import shared_bus directly
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
import shared_bus
PORT = 8765
VIEWER_HOST = "0.0.0.0"
MAIN_SESSIONS_FILE = Path("/Users/lhaclaw/.openclaw/agents/main/sessions/sessions.json")
CONVERSATIONS_DIR = VIEWER_DIR / "conversations"
CONVERSATIONS_TMP_DIR = CONVERSATIONS_DIR / ".tmp"
CONVERSATIONS_CORRUPT_DIR = CONVERSATIONS_DIR / ".corrupt"
MULTI_CHAT_MODELS = ["minimax", "gemma", "gpt", "free"]
MULTI_CHAT_SCHEMA_VERSION = 1
MAX_TURNS = 40
MAX_RESPONSE_CHARS = 8000
MAX_THREAD_BYTES = 2 * 1024 * 1024

# ── Pipeline stage helpers (used by /api/swarm-status) ──────────────────────
_CANONIC_STAGES = ("design", "review", "build", "qa", "ship")
_ROLE_TO_STAGE = {"wiser": "review", "dev": "build", "qa": "qa"}
_TRIGGERED_EXECUTION_STATUSES = frozenset(
    ("spawning", "running", "waiting", "done", "failed", "timed_out", "cancelled", "stale")
)
_TRIGGERED_EVENT_TYPES = frozenset(
    ("stage_started", "stage_completed", "stage_failed", "stage_cancelled", "pipeline_closed")
)


def _triggered_stages_for_pipeline(pipeline_run_id: str, agents: list[dict], current_stage: str | None, db_path: str) -> list[str]:
    """Determine which pipeline stages have evidence of execution.

    Evidence is gathered from:
    1. stage_events rows (primary source)
    2. agent_executions with a triggered status (secondary, when stage_events is empty)
    3. current_stage fallback (only when no other evidence exists)

    Canonical/deduped order: design → review → build → qa → ship
    """
    triggered: list[str] = []
    try:
        conn = sqlite3.connect(db_path, uri=True, timeout=5.0)
        conn.execute("PRAGMA busy_timeout = 5000")
        placeholders = ','.join(repr(e) for e in _TRIGGERED_EVENT_TYPES)
        rows = conn.execute(
            f"SELECT stage FROM stage_events WHERE pipeline_run_id = ? AND event_type IN ({placeholders})",
            (pipeline_run_id,),
        ).fetchall()
        conn.close()
        for (stage,) in rows:
            if stage in _CANONIC_STAGES and stage not in triggered:
                triggered.append(stage)
    except Exception:
        pass

    # Always merge evidence from both sources (union), then canonical-order
    # agent_executions is secondary: only contributes stages NOT already found via stage_events
    for a in agents:
        role = a.get("agent_role", "")
        status = a.get("status", "")
        if role not in _ROLE_TO_STAGE:
            continue
        if status in _TRIGGERED_EXECUTION_STATUSES:
            st = _ROLE_TO_STAGE[role]
            if st not in triggered:
                triggered.append(st)

    # Canonical ordering + dedupe (preserve first-seen order within canonical positions)
    seen = set(triggered)
    result = [s for s in _CANONIC_STAGES if s in seen]


    # Fallback: use current_stage only when there is no evidence at all
    if not result and current_stage and current_stage in _CANONIC_STAGES:
        result = [current_stage]

    return result


def _llm_model_for_session(session_key: str | None, agent_role: str) -> str:
    """Look up LLM model name from sessions.json given a session_key and agent_role.

    session_key formats:
      agent:<agentId>:subagent:<session_id>  → sessions at ~/.openclaw/agents/<agentId>/sessions/sessions.json
      agent:<agentId>:<channel>:<id>          → same

    Returns model string or "?" if not found / session_key is None.
    """
    if not session_key:
        return "?"
    try:
        parts = session_key.split(":")
        if len(parts) >= 2 and parts[0] == "agent":
            agent = parts[1]
        else:
            # fallback: use agent_role as agent id
            agent = agent_role
        sessions_file = Path.home() / ".openclaw" / "agents" / agent / "sessions" / "sessions.json"
        if not sessions_file.exists():
            return "?"
        with open(sessions_file) as f:
            data = json.load(f)
        if session_key in data:
            model = data[session_key].get("model", "?")
            return model if model else "?"
        return "?"
    except Exception:
        return "?"


def _serialize_pipeline(p: dict, db_path: str) -> dict:
    """Serialize a pipeline_runs row into the dict shape required by the Swarm Panel."""
    pipeline_run_id = p.get("uuid") or p.get("pipeline_run_id", "")
    current_stage = p.get("current_stage") or p.get("stage") or "spec"

    # Pull agent executions for this pipeline
    try:
        agents_raw = shared_bus.get_agent_executions(pipeline_run_id, db_path)
    except Exception:
        agents_raw = []

    # Map agents to a flat list of dicts with agent_role, status, created_at, llm_model.
    # Show ALL executions (not deduplicated per role), sorted by created_at ascending.
    agents = []
    for a in agents_raw:
        role = a.get("agent_role", "")
        if not role:
            continue
        session_key = a.get("session_key")
        agents.append({
            "agent_role": role,
            "status": a.get("status", "queued"),
            "created_at": a.get("created_at", 0),
            "llm_model": _llm_model_for_session(session_key, role),
        })

    # Sort by created_at ascending (earliest first)
    def _sort_key(a):
        try:
            return float(a.get("created_at", 0))
        except (ValueError, TypeError):
            return 0.0
    agents.sort(key=_sort_key)

    triggered_stages = _triggered_stages_for_pipeline(pipeline_run_id, agents, current_stage, db_path)

    # Determine pipeline_number: prefer integer id from DB, fallback to session/uuid fragment
    pipeline_number = p.get("id")
    if pipeline_number is None:
        session_id = p.get("session_id", "")
        pipeline_number = session_id.split(":")[-1][:8] if session_id else (pipeline_run_id[:8] if pipeline_run_id else "?")

    return {
        "pipeline_run_id": pipeline_run_id,
        "pipeline_number": pipeline_number,
        "task_key": p.get("task_key", "?"),
        "stage": current_stage,
        "review_status": p.get("review_status") or "unknown",
        "status": p.get("status", "active"),
        "triggered_stages": triggered_stages,
        "agents": agents,
        "started_at": p.get("started_at"),
        "updated_at": p.get("updated_at"),
        "completed_at": p.get("completed_at"),
    }
def _load_gateway_config() -> dict:
    cfg_path = Path.home() / ".openclaw" / "openclaw.json"
    try:
        cfg = json.loads(cfg_path.read_text())
        gateway_cfg = cfg.get("gateway", {}) or {}
        # gateway.auth is {"mode": "token", "token": "..."}
        auth_cfg = gateway_cfg.get("auth", {}) or {}
        token = auth_cfg.get("token", "") if isinstance(auth_cfg, dict) else ""
        return {"token": token}
    except Exception:
        return {"token": ""}


_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()

# Cache for expensive health check (10s TTL)
_HEALTH_CACHE = {"data": None, "ts": 0.0}
_HEALTH_TTL = 10.0  # short — openclaw status is unreliable, 10s is fine

# ── Endpoint caches (thread-safe) ──────────────────────────────────────
_ROLE_STATUS_CACHE = {"data": None, "ts": 0.0}
_ROLE_STATUS_TTL = 10.0
_RECENT_SESSIONS_CACHE = {"data": None, "ts": 0.0}
_RECENT_SESSIONS_TTL = 10.0
_LATEST_MSG_CACHE = {"data": None, "ts": 0.0}
_LATEST_MSG_TTL = 10.0
_OPENROUTER_CACHE = {"ts": 0.0, "success": None}
_OPENROUTER_TTL = 60.0

# ── Codex usage cache (ChatGPT hourly/weekly limits via openclaw models status) ──
_CODEX_USAGE_CACHE = {"data": None, "ts": 0.0}
_CODEX_USAGE_TTL = 60.0

# ── Internal caches (sub-functions) ────────────────────────────────────
_ACTIVE_SESSIONS_CACHE = {"data": None, "ts": 0.0}
_ACTIVE_SESSIONS_TTL = 10.0
_MODEL_USAGE_CACHE = {"data": None, "ts": 0.0}
_MODEL_USAGE_TTL = 30.0
_OLLAMA_USAGE_CACHE = {"data": None, "ts": 0.0}
_OLLAMA_USAGE_TTL = 30.0
_QA_GEMMA_CACHE = {"data": None, "ts": 0.0}
_QA_GEMMA_TTL = 30.0

_SHARED_MEMORY_CACHE = {"data": None, "ts": 0.0}
_SHARED_MEMORY_TTL = 60.0
_MESSAGES_CACHE = {"data": None, "ts": 0.0}
_MESSAGES_TTL = 30.0

# ── Shared cache lock ─────────────────────────────────────────────────
_CACHE_LOCK = threading.Lock()


def _age(ms: int) -> str:
    if ms < 60000:
        return f"{ms/1000:.0f}s ago"
    elif ms < 3600000:
        return f"{ms/60000:.0f}m ago"
    elif ms < 86400000:
        return f"{ms/3600000:.1f}h ago"
    else:
        return f"{ms/86400000:.1f}d ago"


def _scrub_error_message_safe(msg: str) -> str:
    """Remove absolute paths from error messages for safe API responses."""
    import re
    ws = str(Path.home() / ".openclaw" / "workspace")
    msg = msg.replace(ws, "workspace")
    msg = re.sub(r'/Users/[^/\s]+', '[user]', msg)
    return msg[:200]


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
    """Build role status from agent sessions, ignoring stale historical sessions."""
    ROLE_AGENT_MAP = {
        "silverhand": "main",
        "handy": "dev",
        "scout": "qa",
        "wiser": "wiser",
        "freeman": "freeman",
        "helper": "helper",
    }
    now_ms = datetime.now().timestamp() * 1000
    RECENT_WINDOW_MS = 6 * 60 * 60 * 1000  # 6h; older sessions are not "current"

    def get_recent_session(agent: str) -> tuple:
        """Get most recent non-trajectory session for an agent, preferring current-window items."""
        sessions_file = Path(f"/Users/lhaclaw/.openclaw/agents/{agent}/sessions/sessions.json")
        if not sessions_file.exists():
            return None, None
        try:
            with open(sessions_file) as f:
                data = json.load(f)
            if not data:
                return None, None
            items = sorted(data.items(), key=lambda x: x[1].get("updatedAt", 0), reverse=True)
            recent_items = [it for it in items if (now_ms - it[1].get("updatedAt", 0)) <= RECENT_WINDOW_MS]
            if recent_items:
                return recent_items[0]
            return None, None
        except Exception:
            return None, None

    def build_role(key: str, label: str) -> dict:
        agent_id = ROLE_AGENT_MAP.get(key.lower(), key)
        session_key, session_val = get_recent_session(agent_id)
        if not session_key:
            return {
                "key": key,
                "label": label,
                "status": "gray",
                "age": "-",
                "summary": f"No current {label} session",
                "session_key": "-",
            }

        updated = session_val.get("updatedAt", 0)
        age_ms = now_ms - updated
        age_str = _age(age_ms)
        session_short = session_key.split(":")[-1][:12]
        sess_status = session_val.get("status", "")
        aborted = session_val.get("abortedLastRun", False)

        if aborted or sess_status in ("failed", "error"):
            status = "red"
            summary = f"Failed session {session_short}..."
        elif sess_status == "running" and age_ms < 5 * 60 * 1000:
            status = "green"
            summary = f"Running {session_short}..."
        else:
            status = "amber"
            summary = f"Recent session {session_short}..."

        return {
            "key": key,
            "label": label,
            "status": status,
            "age": age_str,
            "summary": summary,
            "session_key": session_key,
        }

    result = {
        "roles": [
            build_role("silverhand", "SilverHand"),
            build_role("handy", "Handy"),
            build_role("scout", "Scout"),
            build_role("wiser", "Wiser"),
            build_role("helper", "Helper"),
            build_role("freeman", "Freeman"),
        ],
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return result


def _openclaw_status() -> dict:
    try:
        result = subprocess.run(
            ["openclaw", "status", "--json"],
            capture_output=True, text=True, timeout=8,
            stdin=subprocess.DEVNULL,
            env=dict(os.environ, PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"),
        )
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout (8s exceeded)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _get_active_sessions() -> dict:
    """Get session counts per agent: total, active 2h, recent 5m."""
    global _ACTIVE_SESSIONS_CACHE
    now = time.time()
    with _CACHE_LOCK:
        if _ACTIVE_SESSIONS_CACHE["data"] is not None and (now - _ACTIVE_SESSIONS_CACHE["ts"]) < _ACTIVE_SESSIONS_TTL:
            return _ACTIVE_SESSIONS_CACHE["data"]
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
    with _CACHE_LOCK:
        _ACTIVE_SESSIONS_CACHE = {"data": result, "ts": now}
    return result

def _get_model_usage() -> dict:
    """Get token usage per model over the past 5 hours across all agents."""
    global _MODEL_USAGE_CACHE
    now = time.time()
    with _CACHE_LOCK:
        if _MODEL_USAGE_CACHE["data"] is not None and (now - _MODEL_USAGE_CACHE["ts"]) < _MODEL_USAGE_TTL:
            return _MODEL_USAGE_CACHE["data"]
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
    with _CACHE_LOCK:
        _MODEL_USAGE_CACHE = {"data": result, "ts": now}
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
    global _OLLAMA_USAGE_CACHE
    now = time.time()
    with _CACHE_LOCK:
        if _OLLAMA_USAGE_CACHE["data"] is not None and (now - _OLLAMA_USAGE_CACHE["ts"]) < _OLLAMA_USAGE_TTL:
            return _OLLAMA_USAGE_CACHE["data"]
    now_ms = datetime.now().timestamp() * 1000
    ONE_DAY = 86400000
    result = {}
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
                            if model not in result or result[model]["ago_ms"] > age:
                                result[model] = {
                                    "ago_ms": age,
                                    "input_tokens": val.get("inputTokens", 0),
                                    "output_tokens": val.get("outputTokens", 0)
                                }
            except Exception:
                pass
    with _CACHE_LOCK:
        _OLLAMA_USAGE_CACHE = {"data": result, "ts": now}
    return result


def _get_qa_gemma_sessions() -> list:
    """Get QA agent gemma sessions with lastUsed timestamps."""
    global _QA_GEMMA_CACHE
    now = time.time()
    with _CACHE_LOCK:
        if _QA_GEMMA_CACHE["data"] is not None and (now - _QA_GEMMA_CACHE["ts"]) < _QA_GEMMA_TTL:
            return _QA_GEMMA_CACHE["data"]
    sessions_file = Path("/Users/lhaclaw/.openclaw/agents/qa/sessions/sessions.json")
    if not sessions_file.exists():
        with _CACHE_LOCK:
            _QA_GEMMA_CACHE = {"data": [], "ts": now}
        return []
    try:
        data = json.loads(sessions_file.read_text())
        result = [
            {"model": v.get("model", ""), "lastUsed": v.get("updatedAt", 0)}
            for v in data.values()
            if "gemma" in v.get("model", "").lower()
        ]
        with _CACHE_LOCK:
            _QA_GEMMA_CACHE = {"data": result, "ts": now}
        return result
    except Exception:
        with _CACHE_LOCK:
            _QA_GEMMA_CACHE = {"data": [], "ts": now}
        return []


def _recent_sessions() -> dict:
    """Get the 5 most recent sessions across all agents."""
    now_ms = datetime.now().timestamp() * 1000
    ONE_WEEK = 604800000
    all_sessions = []

    for agent in ["main", "codex", "qa", "helper", "dev", "wiser"]:
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
    with _CACHE_LOCK:
        if _HEALTH_CACHE["data"] is not None and (now - _HEALTH_CACHE["ts"]) < _HEALTH_TTL:
            return _HEALTH_CACHE["data"]

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
        # DISABLED: openclaw status --json is unreliable (times out after 8s every time)
        # results["openclaw"] = {"default_model": None, "sessions": [], "error": "disabled"}
        results["openclaw"] = {"default_model": None, "sessions": [], "error": "disabled"}

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
    with _CACHE_LOCK:
        _HEALTH_CACHE = {"data": result, "ts": now}
    return result


def handle_api_role_status() -> bytes:
    global _ROLE_STATUS_CACHE
    now = time.time()
    with _CACHE_LOCK:
        if _ROLE_STATUS_CACHE["data"] is not None and (now - _ROLE_STATUS_CACHE["ts"]) < _ROLE_STATUS_TTL:
            return _ROLE_STATUS_CACHE["data"]
    data = _role_status()
    encoded = json.dumps(data).encode()
    with _CACHE_LOCK:
        _ROLE_STATUS_CACHE = {"data": encoded, "ts": now}
    return encoded


def handle_api_model_usage() -> bytes:
    return json.dumps(_get_model_usage()).encode()


def _get_cache_stats() -> dict:
    """Return current cache tier hit/miss stats from shared_memory.db."""
    try:
        sys.path.insert(0, '/Users/lhaclaw/.openclaw/workspace/src')
        from cache_layer import get_cache_stats
        return {"status": "ok", **get_cache_stats(db_path='/Users/lhaclaw/.openclaw/workspace/shared_memory.db')}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def handle_api_cache_stats() -> bytes:
    return json.dumps(_get_cache_stats()).encode()


def handle_api_openrouter_status() -> bytes:
    """Cache success only; errors do NOT overwrite last good cached result."""
    global _OPENROUTER_CACHE
    now = time.time()
    # Return fresh success if not expired
    with _CACHE_LOCK:
        if _OPENROUTER_CACHE["success"] is not None:
            if (now - _OPENROUTER_CACHE["ts"]) < _OPENROUTER_TTL:
                return _OPENROUTER_CACHE["success"]
    # Fetch fresh
    data = _get_openrouter_status()
    encoded = json.dumps(data).encode()
    # Cache only if successful; stale errors are returned but not stored
    if data.get("status") == "ok":
        with _CACHE_LOCK:
            _OPENROUTER_CACHE = {"ts": now, "success": encoded}
    return encoded


def handle_api_swarm_cleanup() -> bytes:
    """POST /api/swarm-cleanup — reconcile stale children, spawns, and outdated pipeline rows."""
    try:
        import sys as _sys
        workspace_root = "/Users/lhaclaw/.openclaw/workspace"
        if workspace_root not in _sys.path:
            _sys.path.insert(0, workspace_root)
        from src.swarm_router import (
            reconcile_outdated_pipeline_rows,
            reconcile_stale_running_children,
            reconcile_stale_unattached_spawns,
        )

        reconciled_stale_children = reconcile_stale_running_children()
        reconciled_unattached_spawns = reconcile_stale_unattached_spawns()
        reconciled_outdated_pipelines = reconcile_outdated_pipeline_rows()
        total = (
            reconciled_stale_children
            + reconciled_unattached_spawns
            + reconciled_outdated_pipelines
        )
        message = (
            "No stale pipeline entries needed reconciliation."
            if total == 0
            else (
                "Cleanup reconciled "
                f"{reconciled_stale_children} stale children, "
                f"{reconciled_unattached_spawns} unattached spawns, and "
                f"{reconciled_outdated_pipelines} outdated pipeline rows."
            )
        )
        return json.dumps({
            "ok": True,
            "reconciled_stale_children": reconciled_stale_children,
            "reconciled_unattached_spawns": reconciled_unattached_spawns,
            "reconciled_outdated_pipelines": reconciled_outdated_pipelines,
            "message": message,
        }).encode()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "message": "Swarm cleanup failed."}).encode()


def handle_api_codex_usage() -> bytes:
    """Parse 'openclaw models status' to extract ChatGPT/Codex hourly + weekly usage. Cached 60s."""
    global _CODEX_USAGE_CACHE
    now = time.time()
    with _CACHE_LOCK:
        if _CODEX_USAGE_CACHE["data"] is not None and (now - _CODEX_USAGE_CACHE["ts"]) < _CODEX_USAGE_TTL:
            return _CODEX_USAGE_CACHE["data"]

    try:
        result = subprocess.run(
            ["/opt/homebrew/bin/openclaw", "models", "status"],
            capture_output=True, text=True, timeout=15,
            stdin=subprocess.DEVNULL,
            env=dict(os.environ, PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"),
        )
        output = result.stdout
    except Exception as e:
        encoded = json.dumps({"error": str(e)}).encode()
        with _CACHE_LOCK:
            _CODEX_USAGE_CACHE = {"data": encoded, "ts": now}
        return encoded

    hourly_pct = None   # e.g. 85
    weekly_pct = None   # e.g. 70
    hourly_remain = None  # e.g. "3h 7m"
    weekly_remain = None  # e.g. "1d 16h"
    auth_status = None  # e.g. "ok", "expired", "missing"

    for line in output.split("\n"):
        stripped = line.strip()
        # Parse: "- openai-codex usage: 5h 85% left ⏱3h 7m · Week 70% left ⏱1d 16h"
        if "openai-codex usage:" in stripped and "left" in stripped:
            # Hourly: "5h 85% left" or similar
            m_hourly = re.search(r"(\d+)h\s+(\d+)%\s+left", stripped)
            if m_hourly:
                hourly_remain = m_hourly.group(1) + "h"
                hourly_pct = int(m_hourly.group(2))
            else:
                # Fallback: try just "% left" pattern
                m_h2 = re.search(r"(\d+)%\s+left", stripped)
                if m_h2:
                    hourly_pct = int(m_h2.group(1))
            # Weekly: "Week 70% left"
            m_weekly = re.search(r"Week\s+(\d+)%\s+left", stripped)
            if m_weekly:
                weekly_pct = int(m_weekly.group(1))
            # Parse remaining time tokens ⏱
            m_hr = re.search(r"⏱([^·]+)", stripped)
            if m_hr:
                hourly_remain = m_hr.group(1).strip()
            m_wr = re.search(r"⏱[^·]+·\s*Week\s+\d+%\s+left\s+⏱([^·]+)", stripped)
            if m_wr:
                weekly_remain = m_wr.group(1).strip()
        # Parse auth: "openai-codex:hksmartlha@gmail.com (hksmartlha@gmail.com) ok expires in 10d"
        if "openai-codex:hksmartlha@gmail.com" in stripped and ("ok" in stripped or "error" in stripped or "expired" in stripped):
            if "ok" in stripped:
                auth_status = "ok"
            elif "expired" in stripped:
                auth_status = "expired"
            else:
                auth_status = "error"

    encoded = json.dumps({
        "hourly_pct": hourly_pct,
        "weekly_pct": weekly_pct,
        "hourly_remain": hourly_remain,
        "weekly_remain": weekly_remain,
        "auth_status": auth_status,
    }).encode()

    with _CACHE_LOCK:
        _CODEX_USAGE_CACHE = {"data": encoded, "ts": now}
    return encoded


_TERMINAL_PIPELINE_STATUSES = {"done", "failed", "timed_out", "cancelled"}
_TERMINAL_EXECUTION_STATUSES = {"done", "failed", "timed_out", "cancelled"}
_RECONCILIATION_RESULT_REF_PREFIXES = (
    "orphan:",
    "session_terminal:",
)
_RECONCILIATION_BACKLOG_MIN_AGE = timedelta(hours=6)


def _parse_sqlite_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _latest_execution_by_pipeline(conn, pipeline_ids: list[str]) -> dict[str, dict]:
    if not pipeline_ids:
        return {}
    placeholders = ",".join("?" for _ in pipeline_ids)
    rows = conn.execute(
        f"""
        SELECT *
        FROM agent_executions
        WHERE pipeline_run_id IN ({placeholders})
        ORDER BY pipeline_run_id, updated_at DESC, created_at DESC, execution_id DESC
        """,
        pipeline_ids,
    ).fetchall()
    if not rows:
        return {}
    cols = [c[0] for c in conn.execute("SELECT * FROM agent_executions LIMIT 0").description]
    latest: dict[str, dict] = {}
    for row in rows:
        data = dict(zip(cols, row))
        latest.setdefault(data["pipeline_run_id"], data)
    return latest


def _is_recent_backlog_reconciliation_artifact(
    row: dict,
    latest_execution: dict | None,
    *,
    now_utc: datetime,
    window_hours: int,
) -> bool:
    if row.get("status") not in _TERMINAL_PIPELINE_STATUSES:
        return False
    if not latest_execution:
        return False
    if latest_execution.get("status") not in _TERMINAL_EXECUTION_STATUSES:
        return False

    result_ref = str(latest_execution.get("result_ref") or "")
    if not result_ref.startswith(_RECONCILIATION_RESULT_REF_PREFIXES):
        return False

    started_at = _parse_sqlite_datetime(row.get("started_at"))
    completed_at = _parse_sqlite_datetime(row.get("completed_at"))
    if started_at is None or completed_at is None:
        return False

    now_naive_utc = now_utc.astimezone(timezone.utc).replace(tzinfo=None)
    window_start = now_naive_utc - timedelta(hours=int(window_hours))
    started_materially_earlier = (
        started_at < window_start
        or (completed_at - started_at) >= _RECONCILIATION_BACKLOG_MIN_AGE
    )

    return started_materially_earlier and completed_at >= window_start


def _get_recent_non_active_pipeline_rows(
    db_path: str | None = None,
    limit: int = 10,
    window_hours: int = 24,
) -> list[dict]:
    """Return recent non-active pipeline rows within the default age window."""
    from shared_bus import DB_PATH, _conn

    conn = _conn(db_path if db_path else str(DB_PATH))
    try:
        recency_expr = "COALESCE(completed_at, updated_at)"
        rows = conn.execute(
            f"""
            SELECT *
            FROM pipeline_runs
            WHERE status != 'active'
              AND {recency_expr} >= datetime('now', ?)
            ORDER BY {recency_expr} DESC
            """,
            (f"-{int(window_hours)} hours",),
        ).fetchall()
        if not rows:
            return []
        cols = [c[0] for c in conn.execute("SELECT * FROM pipeline_runs LIMIT 0").description]
        pipelines = [dict(zip(cols, row)) for row in rows]
        latest_by_pipeline = _latest_execution_by_pipeline(
            conn,
            [row["uuid"] for row in pipelines if row.get("uuid")],
        )
        filtered = [
            row for row in pipelines
            if not _is_recent_backlog_reconciliation_artifact(
                row,
                latest_by_pipeline.get(row.get("uuid") or ""),
                now_utc=datetime.now(timezone.utc),
                window_hours=window_hours,
            )
        ]
        return filtered[:limit]
    finally:
        conn.close()


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
        for session_key, session_val in main_sessions[:6]:
            jsonl_path = session_val.get("sessionFile", "")
            if not jsonl_path or not Path(jsonl_path).exists():
                sid = session_val.get("sessionId", "")
                jsonl_pattern = f"/Users/lhaclaw/.openclaw/agents/main/sessions/{sid}.jsonl"
                files = glob.glob(jsonl_pattern)
                if not files:
                    continue
                jsonl_path = files[0]
            lines = Path(jsonl_path).read_text(encoding="utf-8", errors="replace").splitlines()
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
                        if not stripped:
                            continue
                        if stripped.startswith("<<<"):
                            continue
                        # Get age from the message timestamp in the jsonl
                        msg_ts = m.get("timestamp", "")
                        if msg_ts:
                            try:
                                msg_dt = datetime.fromisoformat(msg_ts.replace("Z", "+00:00"))
                                ago_ms = (datetime.now().astimezone() - msg_dt).total_seconds() * 1000
                                mins = int(ago_ms / 60000)
                                hours = int(ago_ms / 3600000)
                                days = int(ago_ms / 86400000)
                                if days > 0:
                                    age_str = f"{days}d ago"
                                elif hours > 0:
                                    age_str = f"{hours}h ago"
                                else:
                                    age_str = f"{mins}m ago"
                            except Exception:
                                age_str = "—"
                        else:
                            age_str = "—"
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
    global _LATEST_MSG_CACHE
    now = time.time()
    with _CACHE_LOCK:
        if _LATEST_MSG_CACHE["data"] is not None and (now - _LATEST_MSG_CACHE["ts"]) < _LATEST_MSG_TTL:
            return _LATEST_MSG_CACHE["data"]
    data = _latest_message()
    encoded = json.dumps(data).encode()
    with _CACHE_LOCK:
        _LATEST_MSG_CACHE = {"data": encoded, "ts": now}
    return encoded


def _shared_memory_entries() -> list[dict]:
    """Read recent entries from shared_memory.db approved_memory table."""
    import sqlite3
    try:
        conn = sqlite3.connect("file:///Users/lhaclaw/.openclaw/workspace/shared_memory.db", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, object_type, summary, source_ref, created_at, approved_by FROM approved_memory ORDER BY created_at DESC LIMIT 20"
        )
        rows = cur.fetchall()
        conn.close()
        result = []
        for r in rows:
            summary = r["summary"] or ""
            source = r["source_ref"] or ""
            result.append({
                "id": r["id"],
                "fact": summary[:120] + ("…" if len(summary) > 120 else ""),
                "source": source,
                "age": _age_str(r["created_at"]),
                "by": r["approved_by"] or "",
            })
        return result
    except Exception as e:
        return [{"fact": f"Error: {e}", "source": "", "age": "", "by": ""}]


def _age_str(dt_str: str) -> str:
    """Convert ISO datetime to human-readable age."""
    try:
        dt_str = dt_str.replace("Z", "+00:00").split(".")[0]
        # Add UTC timezone if none present (naive datetime)
        if not (dt_str.endswith("+") or dt_str.endswith("-") or "+" in dt_str or dt_str.endswith("Z")):
            dt_str = dt_str + "+00:00"
        dt = datetime.fromisoformat(dt_str)
        delta = datetime.now(timezone.utc) - dt
        total_sec = int(delta.total_seconds())
        if total_sec < 0:
            return dt_str[:16]
        if total_sec < 60:
            return f"{total_sec}s ago"
        if total_sec < 3600:
            return f"{total_sec // 60}m ago"
        if total_sec < 86400:
            return f"{total_sec // 3600}h ago"
        return f"{total_sec // 86400}d ago"
    except Exception:
        return dt_str[:16] if dt_str else ""


def handle_api_recent_sessions() -> bytes:
    """DEPRECATED — kept for backward compatibility. Use /api/shared-memory instead."""
    global _RECENT_SESSIONS_CACHE
    now = time.time()
    with _CACHE_LOCK:
        if _RECENT_SESSIONS_CACHE["data"] is not None and (now - _RECENT_SESSIONS_CACHE["ts"]) < _RECENT_SESSIONS_TTL:
            return _RECENT_SESSIONS_CACHE["data"]
    data = _recent_sessions()
    encoded = json.dumps(data).encode()
    with _CACHE_LOCK:
        _RECENT_SESSIONS_CACHE = {"data": encoded, "ts": now}
    return encoded


def handle_api_shared_memory() -> bytes:
    """Return recent entries from approved_memory table."""
    global _SHARED_MEMORY_CACHE
    now = time.time()
    with _CACHE_LOCK:
        if _SHARED_MEMORY_CACHE["data"] is not None and (now - _SHARED_MEMORY_CACHE["ts"]) < _SHARED_MEMORY_TTL:
            return _SHARED_MEMORY_CACHE["data"]
    data = _shared_memory_entries()
    encoded = json.dumps({"entries": data}).encode()
    with _CACHE_LOCK:
        _SHARED_MEMORY_CACHE = {"data": encoded, "ts": now}
    return encoded


def handle_api_suggested_memory() -> bytes:
    """Return the content of SUGGESTED_MEMORY.md."""
    suggested_file = Path.home() / ".openclaw" / "workspace" / "SUGGESTED_MEMORY.md"
    try:
        if not suggested_file.exists():
            return json.dumps({"content": "No suggested memory found."}).encode()
        content = suggested_file.read_text(encoding="utf-8")
        return json.dumps({"content": content}).encode()
    except Exception as e:
        return json.dumps({"error": str(e)}).encode()


def _messages_entries() -> list[dict]:
    import sqlite3
    try:
        conn = sqlite3.connect("file:///Users/lhaclaw/.openclaw/workspace/shared_memory.db", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # Blend newest operational messages with Mic decisions/rules so important
        # commands do not disappear behind high-volume daily-log output rows.
        cur.execute(
            """
            SELECT id, session_id, task_key, stage, agent_from, role, content, metadata, created_at,
                   0 AS priority
            FROM messages
            WHERE visibility = 'broadcast'
            ORDER BY created_at DESC, id DESC
            LIMIT 12
            """
        )
        latest_rows = cur.fetchall()
        cur.execute(
            """
            SELECT id, session_id, task_key, stage, agent_from, role, content, metadata, created_at,
                   1 AS priority
            FROM messages
            WHERE visibility = 'broadcast'
              AND (
                   role = 'decision'
                OR lower(content) LIKE '%rule%'
                OR content LIKE '%Mic%'
                OR content LIKE '%remember%'
              )
            ORDER BY created_at DESC, id DESC
            LIMIT 12
            """
        )
        decision_rows = cur.fetchall()
        conn.close()

        rows_by_id = {}
        for r in list(latest_rows) + list(decision_rows):
            rows_by_id[r["id"]] = r
        rows = sorted(rows_by_id.values(), key=lambda r: (r["priority"], r["created_at"], r["id"]), reverse=True)

        out = []
        for r in rows[:24]:
            content = (r["content"] or "").strip()
            metadata = {}
            try:
                metadata = json.loads(r["metadata"] or "{}")
            except Exception:
                metadata = {}
            is_mic_message = metadata.get("source_role") == "user" or metadata.get("kind") == "mic_decision"
            is_decision = (r["role"] == "decision") or ("rule" in content.lower()) or ("remember" in content.lower())
            owner_labels = {
                "main": "SilverHand",
                "dev": "Handy",
                "qa": "Scout",
                "wiser": "Wiser",
                "helper": "Helpo",
            }
            owner = "Mic" if is_mic_message else owner_labels.get(r["agent_from"], r["agent_from"] or "")
            out.append({
                "id": r["id"],
                "session_id": r["session_id"],
                "task_key": r["task_key"] or "",
                "stage": r["stage"] or "",
                "agent": r["agent_from"] or "",
                "owner": owner,
                "role": r["role"] or "",
                "kind": "decision/rule" if is_decision else "message",
                "content": content[:260] + ("…" if len(content) > 260 else ""),
                "age": _age_str(r["created_at"]),
            })
        return out
    except Exception as e:
        return [{"agent": "error", "owner": "error", "role": "", "kind": "error", "content": f"Error: {e}", "age": ""}]


def handle_api_messages() -> bytes:
    global _MESSAGES_CACHE
    now = time.time()
    with _CACHE_LOCK:
        if _MESSAGES_CACHE["data"] is not None and (now - _MESSAGES_CACHE["ts"]) < _MESSAGES_TTL:
            return _MESSAGES_CACHE["data"]
    data = _messages_entries()
    encoded = json.dumps({"entries": data}).encode()
    with _CACHE_LOCK:
        _MESSAGES_CACHE = {"data": encoded, "ts": now}
    return encoded


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


def handle_api_outcomes_summary() -> bytes:
    """GET /api/outcomes-summary — summary stats."""
    try:
        summary = data_outcomes.get_outcomes_summary()
        return json.dumps(summary).encode()
    except Exception as e:
        return json.dumps({"error": str(e)}).encode()


def handle_api_outcomes_timeline() -> bytes:
    """GET /api/outcomes-timeline — applications over time."""
    try:
        timeline = data_outcomes.get_applications_over_time("30d")
        return json.dumps(timeline).encode()
    except Exception as e:
        return json.dumps({"error": str(e)}).encode()


def handle_api_jobs(sock: socket.socket, method: str, post_body: bytes) -> bytes:
    """GET /api/jobs — list all jobs; POST /api/jobs — add job."""
    try:
        if method == "POST":
            body = json.loads(post_body.decode("utf-8"))
            job_id = data_outcomes.add_job(body)
            return json.dumps({"ok": True, "job_id": job_id}).encode()
        else:
            jobs = data_outcomes.load_jobs()
            return json.dumps(jobs).encode()
    except Exception as e:
        return json.dumps({"error": str(e)}).encode()


def handle_api_job_patch(job_id: str, post_body: bytes) -> bytes:
    """PATCH /api/jobs/<job_id> — update job status."""
    try:
        body = json.loads(post_body.decode("utf-8"))
        status = body.get("status", "")
        notes = body.get("notes", "")
        job = data_outcomes.update_job_status(job_id, status, notes)
        if job is None:
            return json.dumps({"error": "job not found"}).encode()
        return json.dumps({"ok": True, "job": job}).encode()
    except ValueError as e:
        return json.dumps({"error": str(e)}).encode()
    except Exception as e:
        return json.dumps({"error": str(e)}).encode()


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
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        for model, fn_model in (("gemma", _call_gemma), ("minimax", _call_minimax), ("gpt", _call_gpt), ("free", _call_free)):
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
        token = _load_gateway_config()["token"]
        payload = {
            "model": "openclaw",
            "messages": history,
            "max_tokens": 1024
        }

        r = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "http://127.0.0.1:18789/v1/chat/completions",
             "-H", "Content-Type: application/json",
             "-H", f"Authorization: Bearer {token}",
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
        token = _load_gateway_config()["token"]
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
             "-H", f"Authorization: Bearer {token}",
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




def _call_free(message: str, history: list, out_q: list) -> None:
    """Call OpenRouter free tier model via direct API."""
    try:
        # Load API key from openclaw.json
        import pathlib
        try:
            cfg = json.load(open(pathlib.Path.home() / ".openclaw/openclaw.json"))
            api_key = cfg.get("env", {}).get("OPENROUTER_API_KEY", "")
        except Exception:
            api_key = os.environ.get("OPENROUTER_API_KEY", "")

        if not api_key or api_key == "OPENROUTER_API_KEY":
            out_q.append({"model": "free", "content": "OpenRouter API key not configured", "done": True, "error": True})
            return

        # Build messages for OpenRouter
        messages = [{"role": "user", "content": message}]

        payload = {
            "model": "openrouter/auto",
            "messages": messages,
            "stream": False,
            "max_tokens": 1024
        }

        r = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "https://openrouter.ai/api/v1/chat/completions",
             "-H", "Content-Type: application/json",
             "-H", f"Authorization: Bearer {api_key}",
             "-H", "HTTP-Referer: http://localhost",
             "-H", "X-Title: OpenClaw-Viewer",
             "-d", json.dumps(payload),
             "--max-time", "60"],
            capture_output=True, text=True, timeout=65, stdin=subprocess.DEVNULL
        )

        if r.returncode == 0:
            try:
                data = json.loads(r.stdout)
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    out_q.append({"model": "free", "content": content, "done": True})
                else:
                    out_q.append({"model": "free", "content": f"No response: {r.stdout[:200]}", "done": True, "error": True})
            except json.JSONDecodeError:
                out_q.append({"model": "free", "content": f"Parse error: {r.stdout[:200]}", "done": True, "error": True})
        else:
            out_q.append({"model": "free", "content": f"curl error {r.returncode}: {r.stderr[:200]}", "done": True, "error": True})
    except Exception as e:
        out_q.append({"model": "free", "content": f"Error: {e}", "done": True, "error": True})

# ── URL Pre-fill API handlers ──────────────────────────────────────────────

def _import_ui_module():
    """Lazily import viewer.ui module to avoid circular imports."""
    ui_path = SRC_DIR / "job_hunt_paste_ui.py"
    spec = __import__('importlib.util').util.spec_from_file_location("viewer_ui", str(ui_path))
    module = __import__('importlib.util').module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _handle_api_url_parse(post_body: bytes) -> bytes:
    """POST /api/url-parse — parse a job URL."""
    try:
        body = json.loads(post_body.decode("utf-8"))
    except Exception:
        return json.dumps({"error": "bad request"}).encode()
    url = str(body.get("url", "")).strip()
    if not url:
        return json.dumps({"error": "url is required"}).encode()
    try:
        ui = _import_ui_module()
        result = ui.parse_job_url(url)
        return json.dumps(result).encode()
    except ValueError as e:
        return json.dumps({"error": str(e)}).encode()
    except Exception as e:
        return json.dumps({"error": f"Unexpected error: {e}"}).encode()


def _handle_api_text_parse(post_body: bytes) -> bytes:
    """POST /api/text-parse — parse pasted job text."""
    try:
        body = json.loads(post_body.decode("utf-8"))
    except Exception:
        return json.dumps({"error": "bad request"}).encode()
    text = str(body.get("text", "")).strip()
    if not text:
        return json.dumps({"error": "text is required"}).encode()
    try:
        ui = _import_ui_module()
        result = ui.parse_job_text(text)
        return json.dumps(result).encode()
    except ValueError as e:
        return json.dumps({"error": str(e)}).encode()
    except Exception as e:
        return json.dumps({"error": f"Unexpected error: {e}"}).encode()


def _handle_api_job_submit(post_body: bytes) -> bytes:
    """POST /api/job-submit — store a parsed/edited job."""
    try:
        data = json.loads(post_body.decode("utf-8"))
    except Exception:
        return json.dumps({"error": "bad request"}).encode()
    if not data.get("job_title") and not data.get("company"):
        return json.dumps({"error": "job_title or company is required"}).encode()
    try:
        ui = _import_ui_module()
        # Build a job_id if not provided
        if "job_id" not in data or not data["job_id"]:
            import re
            title = re.sub(r"[^a-z0-9]+", "-", (data.get("job_title") or "").lower())[:40]
            company = re.sub(r"[^a-z0-9]+", "-", (data.get("company") or "").lower())[:40]
            data["job_id"] = f"{title}-{company}"
        job_id = ui.submit_parsed_job(data)
        return json.dumps({"ok": True, "job_id": job_id}).encode()
    except Exception as e:
        return json.dumps({"error": str(e)}).encode()


def serve_file(sock: socket.socket, path: str) -> bool:
    # OpenClaw system pages live in workspace viewer, not job_hunt viewer
    _OC_SYSTEM_PAGES = {
        "/viewer/openclaw_status.html",
        "/viewer/openclaw_optimization_designs.html",
        "/viewer/openclaw_pulse_viewer.html",
        "/viewer/system_kanban.html",
        "/viewer/multi_llm_chat.html",
        "/viewer/swarm_panel.html",
        "/viewer/status_debug.html",
        "/viewer/swarm-v1-cheatsheet.html",
        "/viewer/trust_level.html",
        "/viewer/trust_log.json",
    }
    if path in _OC_SYSTEM_PAGES:
        workspace_viewer = Path.home() / ".openclaw" / "workspace" / "viewer"
        file_path = workspace_viewer / Path(path).name
        if not file_path.is_file():
            return False
        content = file_path.read_bytes()
        content_type = "text/html"
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: " + content_type.encode() + b"\r\n"
            b"Content-Length: " + str(len(content)).encode() + b"\r\n"
            b"Connection: close\r\n"
            b"\r\n" + content
        )
        sock.sendall(response)
        return True

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


# ── SSE / EventSource Support ──────────────────────────────────────────
_SSE_CONNECTIONS = 0
_SSE_CONNECTIONS_LOCK = threading.Lock()
_ALLOWED_TOPICS = {
    "health",
    "cache-stats",
    "latest-messages",
    "approved-memory",
    "shared-messages",
    "suggested-memory",
    "swarm-status",
}

def _get_topic_version(topic: str) -> float:
    """Return a deterministic version for a topic based on mtimes or DB state."""
    try:
        if topic == "suggested-memory":
            path = Path.home() / ".openclaw" / "workspace" / "SUGGESTED_MEMORY.md"
            return path.stat().st_mtime if path.exists() else 0.0
        if topic == "health":
            # Health is dynamic; return a version based on the most recent session update
            return _get_active_sessions().get("main", {}).get("recent_5m", 0) * 1.0
        if topic in {"cache-stats", "latest-messages", "approved-memory", "shared-messages", "swarm-status"}:
            # These all depend on shared_memory.db
            db_path = Path("/Users/lhaclaw/.openclaw/workspace/shared_memory.db")
            return db_path.stat().st_mtime if db_path.exists() else 0.0
    except Exception:
        pass
    return time.time() # Fallback

def handle_request(sock: socket.socket) -> None:
    global _SSE_CONNECTIONS
    try:
        request_bytes = sock.recv(8192)
        if not request_bytes:
            return
        # Read the complete HTTP header first.  The first recv may contain only
        # part of the headers, or headers plus part of the body.
        while b"\r\n\r\n" not in request_bytes and len(request_bytes) < 64 * 1024:
            chunk = sock.recv(8192)
            if not chunk:
                break
            request_bytes += chunk

        header_bytes, separator, body_bytes = request_bytes.partition(b"\r\n\r\n")
        if not separator:
            sock.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return

        request = header_bytes.decode("utf-8", errors="replace")
        lines = request.split("\r\n")
        if not lines:
            return
        method, raw_path, _ = lines[0].split(" ", 2)
        path = raw_path.split("?")[0].split(" ")[0]
        if method not in ("GET", "POST"):
            sock.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return

        # Build headers dict from request lines (for API handlers)
        headers = {}
        for line in lines[1:]:
            if line == "":
                break
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        # Extract POST body as bytes and honor the full Content-Length.  Keep
        # the body bytes-safe: decoding the whole request before slicing can
        # corrupt byte offsets and used to truncate bodies larger than the
        # initial recv(8192).
        post_body = b""
        if method == "POST":
            content_length = int(headers.get("content-length", 0) or 0)
            if content_length < 0:
                sock.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                return
            post_body = body_bytes
            # /api/safe-content-analysis enforces a 2MB request limit below. If
            # the client already exceeds it, avoid reading unnecessary payload
            # bytes before returning 413.
            should_read_body = not (path == "/api/safe-content-analysis" and content_length > 2 * 1024 * 1024)
            if should_read_body:
                while len(post_body) < content_length:
                    chunk = sock.recv(min(65536, content_length - len(post_body)))
                    if not chunk:
                        break
                    post_body += chunk
                post_body = post_body[:content_length]

        # Redirect known viewer pages (serve from /viewer/ subdirectory)
        _redirects = {
            "/openclaw_status.html": "/viewer/openclaw_status.html",
            "/swarm_panel.html": "/viewer/swarm_panel.html",
            "/job_list.html": "/viewer/job_list.html",
        }
        if path in _redirects:
            target = _redirects[path]
            resp = (
                b"HTTP/1.1 301 Moved Permanently\r\n"
                b"Location: " + target.encode() + b"\r\n"
                b"Connection: close\r\n"
                b"\r\n"
            )
            sock.sendall(resp)
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

        if path == "/api/swarm-cleanup" and method == "POST":
            data = handle_api_swarm_cleanup()
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

        if path == "/api/shared-memory":
            data = handle_api_shared_memory()
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

        if path == "/api/suggested-memory":
            data = handle_api_suggested_memory()
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

        if path == "/api/messages":
            data = handle_api_messages()
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

        if path == "/api/cache-stats":
            data = handle_api_cache_stats()
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

        if path == "/api/swarm-status":
            try:
                from datetime import datetime

                db_path = str(PROJECT_ROOT / "shared_memory.db")

                active = [_serialize_pipeline(p, db_path) for p in shared_bus.get_active_pipelines(db_path)]
                recent_source = _get_recent_non_active_pipeline_rows(limit=10, window_hours=24)
                recent = [_serialize_pipeline(p, db_path) for p in recent_source]
                data = json.dumps({
                    "ok": True,
                    "active_pipelines": active,
                    "recent_pipelines": recent,
                    "fetched_at": datetime.now().isoformat(),
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

        if path == "/api/codex-usage":
            data = handle_api_codex_usage()
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

        if path == "/api/system-kanban":
            if method == "POST":
                data = handle_api_system_kanban(post_body)
            else:
                data = handle_api_system_kanban(b"")  # GET → returns full board
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

                # SSE Event Stream: GET /api/viewer-events?topics=...
        if path == "/api/viewer-events" and method == "GET":
            # Extract topics from query string
            query_string = raw_path.split("?", 1)[1] if "?" in raw_path else ""
            requested_topics = []
            if query_string:
                for pair in query_string.split("&"):
                    if pair.startswith("topics="):
                        topics_raw = pair[7:]
                        requested_topics = [t.strip() for t in topics_raw.split(",") if t.strip()]
            
            # Filter by allowlist
            valid_topics = [t for t in requested_topics if t in _ALLOWED_TOPICS]
            rejected_topics = [t for t in requested_topics if t not in _ALLOWED_TOPICS]
            if rejected_topics:
                # Sanitize rejected topic logging (do not log raw unsafe strings unbounded)
                sanitized = [t[:50] for t in rejected_topics]
                print(f"SSE: Rejected topics: {sanitized}")

            # HTTP Response Header for SSE
            resp = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/event-stream\r\n"
                b"Cache-Control: no-cache\r\n"
                b"Connection: keep-alive\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"\r\n"
            )
            sse_counted = False
            try:
                sock.sendall(resp)
                
                with _SSE_CONNECTIONS_LOCK:
                    _SSE_CONNECTIONS += 1
                    sse_counted = True
                    count = _SSE_CONNECTIONS
                try:
                    fd_count = len(os.listdir('/dev/fd'))
                except Exception:
                    fd_count = "unknown"
                print(f"SSE: Connection opened. Active: {count}, FD: {fd_count}")

                # Track versions for this connection
                versions = {t: 0.0 for t in valid_topics}
                start_time = time.time()
                timeout = 300 # 5 minutes
                
                while True:
                    # Check for connection closure (non-blocking read attempt)
                    sock.setblocking(False)
                    try:
                        if sock.recv(1):
                            break # Client closed connection
                    except BlockingIOError:
                        pass
                    except Exception:
                        break
                    finally:
                        sock.setblocking(True)

                    # Check timeout
                    if time.time() - start_time > timeout:
                        break

                    # Check for updates
                    events_sent = 0
                    for t in valid_topics:
                        v = _get_topic_version(t)
                        if v > versions[t]:
                            # Send invalidation event metadata: {topic, version, reason}
                            payload = json.dumps({"topic": t, "version": v, "reason": "update"})
                            event = f"event: message\ndata: {payload}\n\n".encode("utf-8")
                            sock.sendall(event)
                            versions[t] = v
                            events_sent += 1
                    
                    # Heartbeat every 30s if no events sent
                    if events_sent == 0 and int(time.time()) % 30 == 0:
                        sock.sendall(b": heartbeat\n\n")
                    
                    time.sleep(2)
            except Exception as e:
                print(f"SSE stream error: {e}")
            finally:
                if sse_counted:
                    with _SSE_CONNECTIONS_LOCK:
                        _SSE_CONNECTIONS = max(0, _SSE_CONNECTIONS - 1)
                        count = _SSE_CONNECTIONS
                else:
                    with _SSE_CONNECTIONS_LOCK:
                        count = _SSE_CONNECTIONS
                try:
                    fd_count = len(os.listdir('/dev/fd'))
                except Exception:
                    fd_count = "unknown"
                print(f"SSE: Connection closed. Active: {count}, FD: {fd_count}")
                sock.close()
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

        # URL Pre-fill API
        if path == "/api/url-parse" and method == "POST":
            data = _handle_api_url_parse(post_body)
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

        if path == "/api/text-parse" and method == "POST":
            data = _handle_api_text_parse(post_body)
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

        if path == "/api/job-submit" and method == "POST":
            data = _handle_api_job_submit(post_body)
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

        # Outcomes API
        if path == "/api/outcomes-summary" and method == "GET":
            data = handle_api_outcomes_summary()
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

        if path == "/api/outcomes-timeline" and method == "GET":
            data = handle_api_outcomes_timeline()
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

        # Jobs API: GET /api/jobs, POST /api/jobs
        if path == "/api/jobs":
            data = handle_api_jobs(sock, method, post_body)
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

        # PATCH /api/jobs/<job_id>
        jobs_patch_match = re.fullmatch(r"/api/jobs/([\w-]+)", path)
        if jobs_patch_match and method == "PATCH":
            job_id = jobs_patch_match.group(1)
            data = handle_api_job_patch(job_id, post_body)
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

        # POST /api/safe-content-analysis — safe-content-to-analysis pasted text endpoint
        if path == "/api/safe-content-analysis" and method == "POST":
            try:
                body_len = int(headers.get("content-length", 0) or 0)
                if body_len > 2 * 1024 * 1024:
                    data = json.dumps({"error": "Request body too large (max 2MB)"}).encode()
                    resp = (
                        b"HTTP/1.1 413 Payload Too Large\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                        b"Connection: close\r\n\r\n" + data
                    )
                    sock.sendall(resp)
                    return
                body = post_body
                try:
                    parsed = json.loads(body.decode("utf-8"))
                except Exception:
                    data = json.dumps({"error": "Invalid JSON body"}).encode()
                    resp = (
                        b"HTTP/1.1 400 Bad Request\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                        b"Connection: close\r\n\r\n" + data
                    )
                    sock.sendall(resp)
                    return
                if not isinstance(parsed, dict):
                    data = json.dumps({"error": "Request body must be a JSON object"}).encode()
                    resp = (
                        b"HTTP/1.1 400 Bad Request\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                        b"Connection: close\r\n\r\n" + data
                    )
                    sock.sendall(resp)
                    return
                content = parsed.get("content", "")
                mode = parsed.get("mode", "simple")
                analysis_type = parsed.get("analysis_type", "source_digest")
                # Validate fields
                if not isinstance(content, str):
                    data = json.dumps({"error": "field 'content' must be a string"}).encode()
                    resp = (
                        b"HTTP/1.1 400 Bad Request\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                        b"Connection: close\r\n\r\n" + data
                    )
                    sock.sendall(resp)
                    return
                if mode not in ("simple", "standard", "deep"):
                    data = json.dumps({"error": f"Invalid mode '{mode}'. Allowed: simple, standard, deep"}).encode()
                    resp = (
                        b"HTTP/1.1 400 Bad Request\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                        b"Connection: close\r\n\r\n" + data
                    )
                    sock.sendall(resp)
                    return
                if analysis_type not in ("source_digest", "risk_review", "open_questions", "action_plan", "approval_review", "prompt_improvement"):
                    data = json.dumps({"error": f"Invalid analysis_type '{analysis_type}'"}).encode()
                    resp = (
                        b"HTTP/1.1 400 Bad Request\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                        b"Connection: close\r\n\r\n" + data
                    )
                    sock.sendall(resp)
                    return
                # Reject unknown keys that could imply file/URL/network sources
                known_keys = {"content", "mode", "analysis_type", "title"}
                unknown = [k for k in parsed.keys() if k not in known_keys]
                if unknown:
                    data = json.dumps({"error": f"Unknown field(s): {', '.join(unknown)}. Only content, mode, analysis_type, title are allowed."}).encode()
                    resp = (
                        b"HTTP/1.1 400 Bad Request\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                        b"Connection: close\r\n\r\n" + data
                    )
                    sock.sendall(resp)
                    return
                # Run analysis
                from safe_content_api import run_pasted_analysis
                title = parsed.get("title") if isinstance(parsed.get("title"), str) else None
                result = run_pasted_analysis(content=content, mode=mode, analysis_type=analysis_type, title=title)
                data = json.dumps(result, ensure_ascii=False).encode()
                resp = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                    b"Connection: close\r\n\r\n" + data
                )
                sock.sendall(resp)
                return
            except ValueError as ve:
                err_msg = _scrub_error_message_safe(str(ve))
                data = json.dumps({"error": err_msg}).encode()
                resp = (
                    b"HTTP/1.1 400 Bad Request\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                    b"Connection: close\r\n\r\n" + data
                )
                sock.sendall(resp)
                return
            except Exception as e:
                err_msg = _scrub_error_message_safe(str(e))
                data = json.dumps({"error": "Internal error", "detail": err_msg}).encode()
                resp = (
                    b"HTTP/1.1 500 Internal Server Error\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                    b"Connection: close\r\n\r\n" + data
                )
                sock.sendall(resp)
                return

        # Reed.co.uk API proxy — keeps API key server-side
        if path.startswith("/api/reed/"):
            import base64
            import ssl
            import urllib.request
            import urllib.error
            _api_key = os.environ.get("REED_API_KEY", "")
            if not _api_key:
                _env_file = (VIEWER_DIR / "../.." / ".env").resolve()
                if _env_file.is_file():
                    for _line in _env_file.read_text().splitlines():
                        if _line.startswith("REED_API_KEY="):
                            _api_key = _line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
            if not _api_key or _api_key in ("", "your_reed_api_key_here"):
                data = json.dumps({"error": "REED_API_KEY not configured. Add it to .env"}).encode()
                resp = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                    b"Access-Control-Allow-Origin: *\r\n"
                    b"Connection: close\r\n\r\n" + data
                )
                sock.sendall(resp)
                return
            _reed_path = path.replace("/api/reed/", "/api/1.0/")
            _query = raw_path.split("?", 1)[1] if "?" in raw_path else ""
            _target_url = "https://www.reed.co.uk" + _reed_path
            if _query:
                _target_url += "?" + _query
            _req = urllib.request.Request(_target_url)
            _req.add_header("Authorization", "Basic " + base64.b64encode((_api_key + ":").encode()).decode())
            _req.add_header("User-Agent", "Mozilla/5.0")
            try:
                _ctx = ssl.create_default_context()
                with urllib.request.urlopen(_req, timeout=15, context=_ctx) as _res:
                    data = _res.read()
            except urllib.error.HTTPError as _e:
                data = json.dumps({"error": f"Reed API HTTP {_e.code}"}).encode()
            except Exception as _ex:
                data = json.dumps({"error": str(_ex)}).encode()
            resp = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Connection: close\r\n\r\n" + data
            )
            sock.sendall(resp)
            return

        # LinkedIn Jobs API — search via paywall_bypass.sh
        if path.startswith("/api/linkedin-jobs"):
            import re as _re2, subprocess as _sub2, tempfile as _tempfile, os as _os
            import urllib.parse

            _q = raw_path.split("?", 1)[1] if "?" in raw_path else ""
            _params = {}
            for _kv in _q.split("&") if _q else []:
                if "=" in _kv:
                    _k, _v = _kv.split("=", 1)
                    _params[urllib.parse.unquote(_k)] = urllib.parse.unquote(_v)
            _kw   = _params.get("keyword", "Business Analyst")
            _loc  = _params.get("location", "Greater London")
            _days = int(_params.get("days", "7") or "7")
            _wm   = _params.get("work_mode", "remote,hybrid,onsite")
            _F_TPR = {1: "r86400", 7: "r604800", 14: "r1209600", 30: "r2592000"}
            _f_tpr = _F_TPR.get(_days, "r604800")
            _WT_MAP = {"remote": "1", "hybrid": "2", "onsite": "3"}
            _wms = [_wt.strip() for _wt in _wm.split(",") if _wt.strip()]
            _url = f"https://www.linkedin.com/jobs/search/?keywords={urllib.parse.quote(_kw)}&location={urllib.parse.quote(_loc)}&f_TPR={_f_tpr}&trk=public_jobs_search"
            for _w in _wms:
                if _w in _WT_MAP:
                    _url += f"&f_WT={_WT_MAP[_w]}"

            # Build the full paywall_bypass.sh command
            _script = str(Path(__file__).parent / ".." / "scripts" / "paywall_bypass.sh")

            # Capture script output — write to temp file (binary mode) to avoid stdout pipe deadlock.
            _tmp = _tempfile.NamedTemporaryFile(mode="wb+", suffix=".txt", delete=False)
            _tmp_path = _tmp.name
            _tmp.close()
            try:
                with open(_tmp_path, "wb") as _f:
                    _sub2.run(
                        ["bash", _script, _url],
                        stdout=_f,
                        stderr=_sub2.STDOUT,
                        stdin=_sub2.DEVNULL,
                        timeout=40,
                    )
                with open(_tmp_path, "rb") as _f:
                    _out = _f.read().decode("utf-8", errors="replace")
            except Exception as _ex:
                with open("/tmp/viewer_linkedin_err.txt", "a") as _ef:
                    _ef.write(f"Exception: {_ex}\n")
                _out = ""
            finally:
                try:
                    _os.unlink(_tmp_path)
                except Exception:
                    pass

            # -----------------------------------------------------------------
            # Parser: paywall_bypass.sh outputs markdown job listings:
            #   *   [Job Title](url)
            #       ### Job Title
            #       #### [Company Name](company_url)
            #       Location, Region  N day(s)/hour(s) ago
            # -----------------------------------------------------------------
            _jobs = []
            _lines = _out.split("\n")
            _n = len(_lines)
            _id_counter = [0]

            def _next_id():
                _id_counter[0] += 1
                return _id_counter[0]

            _i = 0
            while _i < _n:
                _line = _lines[_i].rstrip()

                # Every job starts with a list item: "*   [Job Title](url)..."
                if _line.startswith("*   ["):
                    # Extract job URL
                    _m_url = _re2.search(
                        r'(https://[a-z]+\.linkedin\.com/jobs/view/[a-zA-Z0-9_:-]+)',
                        _line
                    )
                    _job_url = _m_url.group(1) if _m_url else ""

                    # Extract title from the markdown link text: [*   [Title](url)...
                    _m_t = _re2.match(r"\*   \[(.+?)\]\(", _line)
                    _title = _m_t.group(1).strip() if _m_t else ""

                    _company = ""
                    _loc2 = ""
                    _posted = ""

                    # Look ahead up to 6 lines for company, location, posted time
                    for _j in range(_i + 1, min(_i + 7, _n)):
                        _s = _lines[_j].strip()

                        # "#### [Company Name](...)" — company
                        if _s.startswith("#### ["):
                            _m_c = _re2.match(r"#### \[(.+)\]\(", _s)
                            if _m_c:
                                _company = _m_c.group(1).strip()

                        # Posted time pattern
                        elif (_m_post := _re2.search(
                            r'(\d+)\s+(day|hour|week|month|minute)s?\s+ago',
                            _s
                        )):
                            _posted = _m_post.group(0)
                            _loc_candidate = _s[:_m_post.start()].strip()
                            _loc_candidate = _re2.sub(
                                r'\s+(Be an early applicant|Actively Hiring|Hiring multiple candidates)\s*$',
                                '',
                                _loc_candidate,
                                flags=_re2.I,
                            ).strip()
                            if _loc_candidate:
                                _loc2 = _loc_candidate

                        # Free text — fallback location candidate
                        elif (
                            not _posted
                            and _s
                            and not _s.startswith("#")
                            and not _s.startswith("!")
                            and not _s.startswith("[")
                            and not _s.startswith("http")
                        ):
                            _loc2 = _s

                    if _title and _title != "LinkedIn":
                        _jobs.append({
                            "id": f"job_{_next_id():04d}",
                            "title": _title,
                            "company": _company or "N/A",
                            "location": _loc2 or "N/A",
                            "posted_days_ago": _posted or "Recently posted",
                            "url": _job_url,
                        })

                _i += 1

            # Return top 50 jobs as JSON
            _data = json.dumps(
                {"count": len(_jobs), "jobs": _jobs[:50], "keyword": _kw, "location": _loc, "url": _url},
                ensure_ascii=False
            ).encode()
            _resp = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(_data)).encode() + b"\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Connection: close\r\n\r\n" + _data
            )
            sock.sendall(_resp)
            return

        # ── LinkedIn Job Detail API ──────────────────────────────────────────────
        if path.startswith("/api/linkedin-detail"):
            import re as _re3, subprocess as _sub2, tempfile as _tempfile, os as _os
            _dq = raw_path.split("?", 1)[1] if "?" in raw_path else ""
            _dparams = {}
            for _dkv in _dq.split("&") if _dq else []:
                if "=" in _dkv:
                    _dk, _dv = _dkv.split("=", 1)
                    import urllib.parse as _up
                    _dparams[_up.unquote(_dk)] = _up.unquote(_dv)
            _job_url = _dparams.get("url", "")
            if not _job_url:
                _derr = json.dumps({"error": "missing url param"}).encode()
                sock.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: " + str(len(_derr)).encode() + b"\r\n\r\n" + _derr)
                return

            _script = str(Path(__file__).parent / ".." / "scripts" / "paywall_bypass.sh")
            _tmp = _tempfile.NamedTemporaryFile(mode="wb+", suffix=".txt", delete=False)
            _tmp_path = _tmp.name
            _tmp.close()
            try:
                with open(_tmp_path, "wb") as _f:
                    _sub2.run(["bash", _script, _job_url], stdout=_f, stderr=_sub2.STDOUT, stdin=_sub2.DEVNULL, timeout=40)
                with open(_tmp_path, "rb") as _f:
                    _out = _f.read().decode("utf-8", errors="replace")
            except Exception as _dex:
                with open("/tmp/viewer_linkedin_detail_err.txt", "a") as _ef:
                    _ef.write(f"Exception: {_dex}\n")
                _out = ""
            finally:
                try: _os.unlink(_tmp_path)
                except Exception: pass

            # Extract title, company, description, posted, employment_type, seniority, job_function, industries
            _title = _re3.search(r"^#\s+(.+)", _out, _re3.MULTILINE)
            _title = _title.group(1).strip() if _title else ""
            _company = _re3.search(r"^####\s+\[(.+?)\]", _out, _re3.MULTILINE)
            _company = _company.group(1).strip() if _company else ""
            _posted = _re3.search(r"(\d+\s+(day|hour|week|month)s?\s+ago)", _out)
            _posted = _posted.group(1) if _posted else ""
            _emp_type = ""
            _seniority = ""
            _job_fn = ""
            _industries = ""

            # LinkedIn public detail pages returned by paywall_bypass.sh include
            # login-modal noise first, then the real job body (usually beginning
            # with a bold section such as **Our Mission:**) and then metadata.
            _desc_text = _out
            _start_match = _re3.search(r"\n\*\*(Our Mission|About|The Team|In This Role|What You'll Do|Responsibilities|Role Overview|Job Description)[^\n]*\*\*", _desc_text, _re3.IGNORECASE)
            if _start_match:
                _desc_text = _desc_text[_start_match.start():]
            _end_match = _re3.search(r"\n\s*Show more\s+Show less\s*\n\s*\*\s+### Seniority level", _desc_text, _re3.IGNORECASE)
            if _end_match:
                _desc_text = _desc_text[:_end_match.start()]

            _desc_blocks = []
            for _line in _desc_text.split("\n"):
                _ls = _line.strip()
                if not _ls:
                    continue
                if _ls.startswith("![") or _ls.startswith("[") or _ls.startswith("New to LinkedIn?"):
                    continue
                if _ls.lower() in {"apply", "save", "sign in", "password", "show"}:
                    continue
                _ls = _re3.sub(r"^\*\s+", "", _ls)
                _ls = _re3.sub(r"\*\*(.*?)\*\*", r"\1", _ls)
                _ls = _re3.sub(r"_([^_]+)_", r"\1", _ls)
                _ls = _ls.replace("&rarr;", "→").replace("&mdash;", "—").replace("&trade;", "™")
                _desc_blocks.append(_ls)

            _lines2 = _out.split("\n")
            for _idx, _line in enumerate(_lines2):
                _ls = _line.strip()
                def _next_nonempty(_start):
                    for _j in range(_start + 1, min(_start + 6, len(_lines2))):
                        _v = _lines2[_j].strip()
                        if _v and not _v.startswith("*"):
                            return _v
                    return ""
                if _ls.startswith("*   ### Seniority level"):
                    _seniority = _next_nonempty(_idx)
                if _ls.startswith("*   ### Employment type"):
                    _emp_type = _next_nonempty(_idx)
                if _ls.startswith("*   ### Job function"):
                    _job_fn = _next_nonempty(_idx)
                if _ls.startswith("*   ### Industries"):
                    _industries = _next_nonempty(_idx)

            _description = "\n".join(_desc_blocks).strip()
            _dd_data = json.dumps({
                "title": _title,
                "company": _company,
                "description": _description,
                "posted_days_ago": _posted,
                "employment_type": _emp_type,
                "seniority": _seniority,
                "job_function": _job_fn,
                "industries": _industries,
                "url": _job_url
            }, ensure_ascii=False).encode()
            sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(_dd_data)).encode() + b"\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n" + _dd_data)
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


# System Kanban (openclaw workspace)
_SYSTEM_KANBAN_STORE_PATH = Path.home() / ".openclaw" / "workspace" / "viewer" / "kanban_store.py"

import importlib.util
_spec = importlib.util.spec_from_file_location("system_kanban_store", str(_SYSTEM_KANBAN_STORE_PATH))
_system_kanban_store = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_system_kanban_store)
except Exception as e:
    _system_kanban_store = None
    _system_kanban_load_error = str(e)


def handle_api_system_kanban(post_body: bytes) -> bytes:
    """System Kanban board API — served from openclaw workspace."""
    if _system_kanban_store is None:
        return json.dumps({"error": f"system kanban store unavailable: {_system_kanban_load_error}"}).encode()
    try:
        body = json.loads(post_body.decode("utf-8"))
    except Exception:
        board = _system_kanban_store.get_board()
        return json.dumps(board).encode()

    action = body.get("action", "")

    if action == "upsert":
        card_data = body.get("card", {})
        column_id = body.get("column_id", "backlog")
        try:
            card = _system_kanban_store.upsert_card(column_id, card_data)
            board = _system_kanban_store.get_board()
            return json.dumps(board).encode()
        except (ValueError, IOError) as e:
            return json.dumps({"error": str(e)}).encode()
    elif action == "move":
        card_id = body.get("card_id", "")
        to_column = body.get("to_column", "")
        to_index = body.get("to_index")
        try:
            _system_kanban_store.move_card(card_id, to_column, to_index)
            board = _system_kanban_store.get_board()
            return json.dumps(board).encode()
        except (ValueError, IOError) as e:
            return json.dumps({"error": str(e)}).encode()
    elif action == "delete":
        card_id = body.get("card_id", "")
        _system_kanban_store.delete_card(card_id)
        board = _system_kanban_store.get_board()
        return json.dumps(board).encode()
    else:
        board = _system_kanban_store.get_board()
        return json.dumps(board).encode()
def main() -> None:
    os.chdir(PROJECT_ROOT)
    _ensure_multi_chat_dirs()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    server.bind((VIEWER_HOST, PORT))
    server.listen(50)
    print(f"Viewer running at http://127.0.0.1:{PORT}/viewer/ [SYSTEM_KANBAN_ENABLED]")
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


# ─── 
