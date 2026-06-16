#!/usr/bin/env python3
"""
Session Guard — S2: one-session-per-role-per-task

Enforcement rules:
  - MAX_CONCURRENT_ACP_SESSIONS = 4  (global ACP limit)
  - Per role: at most 1 active session with the same task_key
  - task_key is parsed from session label (oc_task=<...>;oc_role=<...>;title=<...>)
  - task_ids.json is rebuilt from sessions.json each run (Wiser Option B)
  - Source of truth = sessions.json labels; task_ids.json = derived auxiliary index

On duplicate found:
  - Kills the OLDER session (keeps newest)
  - Cleans up orphaned JSONL transcript files
"""

import json
import os
import re
import sqlite3
import subprocess
import glob
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from shared_bus import DB_PATH as SHARED_MEMORY_DB_PATH
except Exception:
    SHARED_MEMORY_DB_PATH = Path.home() / ".openclaw" / "workspace" / "shared_memory.db"

# ─── Config ────────────────────────────────────────────────────────────────────
MAX_CONCURRENT_ACP = 4
SESSIONS_FILE = Path("/Users/lhaclaw/.openclaw/agents/main/sessions/sessions.json")
TASK_IDS_FILE = Path("/Users/lhaclaw/AI-Project-Workspace/Job Seeking Tool/viewer/task_ids.json")
AGENT_SESSIONS_DIR = Path("/Users/lhaclaw/.openclaw/agents")
SEARXNG_CONTAINER = "searxng"

# Role → agent folder mapping (for scanning all agents)
ROLE_TO_AGENT = {
    "dev": "dev",
    "qa": "qa",
    "reviewer": "wiser",
    "helper": "helper",
}

# Sessions older than this (in ms) that are still "running" are considered stale
STALE_THRESHOLD_MS = 30 * 60 * 1000  # 30 minutes


def _cleanup_cancelled_pipeline_agent_executions(db_path: Path | None = None) -> dict:
    """Delete agent_executions rows attached to cancelled pipeline_runs."""
    db_path = db_path or SHARED_MEMORY_DB_PATH
    if not db_path.exists():
        return {"deleted": 0, "pipelines": 0, "db_path": str(db_path)}

    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('pipeline_runs', 'agent_executions')"
            )
        }
        if {"pipeline_runs", "agent_executions"} - tables:
            return {"deleted": 0, "pipelines": 0, "db_path": str(db_path)}

        pipeline_count = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(uuid, session_id)) FROM pipeline_runs WHERE status = 'cancelled'"
        ).fetchone()[0] or 0
        deleted = conn.execute(
            """
            DELETE FROM agent_executions
            WHERE pipeline_run_id IN (
                SELECT COALESCE(uuid, session_id)
                FROM pipeline_runs
                WHERE status = 'cancelled'
            )
            """
        ).rowcount
        conn.commit()
        return {
            "deleted": max(deleted, 0),
            "pipelines": int(pipeline_count),
            "db_path": str(db_path),
        }
    finally:
        conn.close()


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2))


def _age(ms: int) -> str:
    if ms < 60000:
        return f"{ms/1000:.0f}s"
    elif ms < 3600000:
        return f"{ms/60000:.0f}m"
    else:
        return f"{ms/3600000:.1f}h"


def _kill_session(session_key: str, session_id: str) -> bool:
    """Kill a session via subagents kill, return True on success."""
    try:
        result = subprocess.run(
            ["openclaw", "subagents", "kill", session_key],
            capture_output=True,
            text=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except Exception:
        return False


def _clean_jsonl(session_id: str) -> int:
    """Remove orphaned JSONL files for a session. Returns count deleted."""
    count = 0
    for agent_dir in AGENT_SESSIONS_DIR.iterdir():
        if not agent_dir.is_dir():
            continue
        sessions_dir = agent_dir / "sessions"
        if not sessions_dir.is_dir():
            continue
        for p in sessions_dir.glob(f"{session_id}*.jsonl"):
            try:
                p.unlink()
                count += 1
            except Exception:
                pass
    return count


def parse_label(label: str) -> dict | None:
    """Parse 'oc_task=<task_key>;oc_role=<role>;title=<title>' from session label."""
    if not label:
        return None
    m = re.match(r"oc_task=([^;]+);oc_role=([^;]+);title=(.+)", label)
    if m:
        return {"task_key": m.group(1), "role": m.group(2), "title": m.group(3)}
    return None


def _active_status(status: str) -> bool:
    """Return True if session status means actively running/waiting."""
    return status in ("running", "waiting", "active")


def _searxng_active() -> bool:
    """Check if SearXNG container is currently running."""
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
        )
        return SEARXNG_CONTAINER in r.stdout
    except Exception:
        return False


def _qa_active() -> bool:
    """Check if any QA (ollama) session is currently active."""
    for agent_name in ["qa", "dev"]:
        sessions_file = AGENT_SESSIONS_DIR / agent_name / "sessions" / "sessions.json"
        if not sessions_file.exists():
            continue
        try:
            data = json.loads(sessions_file.read_text())
            for sv in data.values():
                if sv.get("status", "") in ("running", "waiting", "active"):
                    model = sv.get("model", "")
                    if "ollama" in model.lower() or "gemma" in model.lower():
                        return True
        except Exception:
            pass
    return False


def manage_searxng_ram() -> str:
    """
    RAM management: QA (Ollama) and SearXNG should NOT run simultaneously.
    QA takes ~8-16GB RAM, SearXNG takes ~200MB.
    If QA is active → stop SearXNG to free RAM.
    If QA is not active → ensure SearXNG is running.
    Returns action description string.
    """
    qa = _qa_active()
    sxng = _searxng_active()

    if qa and sxng:
        # QA needs RAM, stop SearXNG
        try:
            subprocess.run(["docker", "stop", SEARXNG_CONTAINER], capture_output=True, timeout=10, stdin=subprocess.DEVNULL)
            return f"Stopped {SEARXNG_CONTAINER} (QA active, freeing RAM)"
        except Exception:
            return f"Failed to stop {SEARXNG_CONTAINER}"
    elif not qa and not sxng:
        # QA idle, ensure SearXNG is running
        try:
            subprocess.run(["docker", "start", SEARXNG_CONTAINER], capture_output=True, timeout=10, stdin=subprocess.DEVNULL)
            return f"Started {SEARXNG_CONTAINER} (QA idle)"
        except Exception:
            return f"Failed to start {SEARXNG_CONTAINER}"
    else:
        return "No change needed"


def run_guard() -> dict:
    """
    Main guard logic.
    Returns a dict with 'killed', 'files_cleaned', 'duplicates_found', 'errors'.

    Per Wiser Option B: task_ids.json is rebuilt from sessions.json each run.
    Source of truth = sessions.json labels (oc_task, oc_role parsed from label).
    task_ids.json = derived auxiliary index (not source of truth).
    """
    now_ms = datetime.now().timestamp() * 1000

    # ── Phase 1: Scan all agent sessions, parse labels, rebuild task_ids.json ─
    all_sessions: dict[str, dict] = {}  # session_key → {sessionId, status, updatedAt, label, agent}
    for role, agent_name in ROLE_TO_AGENT.items():
        sessions_file = AGENT_SESSIONS_DIR / agent_name / "sessions" / "sessions.json"
        if not sessions_file.exists():
            continue
        agent_sessions = _load_json(sessions_file)
        for sk, sv in agent_sessions.items():
            sv["agent"] = agent_name
            sv["role_from_key"] = role
            all_sessions[sk] = sv

    # Also include main agent sessions
    main_sessions = _load_json(SESSIONS_FILE)
    for sk, sv in main_sessions.items():
        sv["agent"] = "main"
        sv["role_from_key"] = "planner"
        all_sessions[sk] = sv

    # Rebuild task_ids.json: task_key → {session_key, role, spawned_at}
    new_task_ids: dict[str, dict] = {}
    for session_key, val in all_sessions.items():
        status = val.get("status", "")
        if not _active_status(status):
            continue
        label = val.get("label", "")
        parsed = parse_label(label)
        if not parsed:
            continue
        task_key = parsed["task_key"]
        role = parsed["role"]
        spawned_at = val.get("createdAt", datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"))
        new_task_ids[task_key] = {
            "session_key": session_key,
            "role": role,
            "spawned_at": spawned_at,
        }

    # Write rebuilt index
    _save_json(TASK_IDS_FILE, new_task_ids)

    # Build list of active sessions per oc_role (from label) + per agent role (from key)
    # oc_role is the canonical S2 deduplication key
    by_oc_role: dict[str, list[tuple]] = {}  # role from label → [(session_key, session_id, updatedAt, task_key, status)]
    by_key_role: dict[str, list[tuple]] = {}  # role from key → [(session_key, session_id, updatedAt, task_key, status)]

    for session_key, val in all_sessions.items():
        status = val.get("status", "")
        if not _active_status(status):
            continue
        session_id = val.get("sessionId", "")
        updated_at = val.get("updatedAt", 0)
        role_from_key = val.get("role_from_key", "")
        label = val.get("label", "")
        parsed = parse_label(label)
        task_key = parsed["task_key"] if parsed else None
        oc_role = parsed["role"] if parsed else None

        if oc_role:
            by_oc_role.setdefault(oc_role, []).append(
                (session_key, session_id, updated_at, task_key, status)
            )
        if role_from_key:
            by_key_role.setdefault(role_from_key, []).append(
                (session_key, session_id, updated_at, task_key, status)
            )

    killed = []
    files_cleaned = 0
    errors = []
    duplicates_found = []
    cleanup = _cleanup_cancelled_pipeline_agent_executions()

    # ── Rule S2 (by oc_role): one-session-per-role-per-task ─────────────────
    for oc_role, sessions in by_oc_role.items():
        by_task: dict[str | None, list] = {}
        for sess in sessions:
            task_key = sess[3]
            by_task.setdefault(task_key, []).append(sess)

        for task_key, task_sessions in by_task.items():
            if task_key is None:
                continue  # No task_key — skip deduplication
            if len(task_sessions) <= 1:
                continue

            # Duplicate found — keep newest, kill older ones
            task_sessions.sort(key=lambda x: x[2], reverse=True)
            keep, *to_kill = task_sessions

            for sess_key, sess_id, updated_at, _, _ in to_kill:
                age_str = _age(now_ms - updated_at)
                ok = _kill_session(sess_key, sess_id)
                if ok:
                    count = _clean_jsonl(sess_id)
                    files_cleaned += count
                    killed.append(
                        {
                            "session_key": sess_key,
                            "task_key": task_key,
                            "oc_role": oc_role,
                            "age": age_str,
                            "files_cleaned": count,
                        }
                    )
                else:
                    errors.append(f"Failed to kill {sess_key} (task={task_key}, role={oc_role})")
                duplicates_found.append(
                    {
                        "oc_role": oc_role,
                        "task_key": task_key,
                        "kept": keep[0],
                        "killed": [s[0] for s in to_kill],
                    }
                )

    # ── Rule: global ACP concurrent limit (oldest first to kill) ─────────────
    all_active = [
        (sess_key, val.get("sessionId", ""), val.get("updatedAt", 0), val.get("role_from_key"))
        for sess_key, val in all_sessions.items()
        if _active_status(val.get("status", ""))
    ]
    if len(all_active) > MAX_CONCURRENT_ACP:
        all_active.sort(key=lambda x: x[2])  # oldest first
        excess = all_active[MAX_CONCURRENT_ACP:]
        for sess_key, sess_id, updated_at, role in excess:
            if any(k["session_key"] == sess_key for k in killed):
                continue
            age_str = _age(now_ms - updated_at)
            ok = _kill_session(sess_key, sess_id)
            if ok:
                count = _clean_jsonl(sess_id)
                files_cleaned += count
                killed.append(
                    {
                        "session_key": sess_key,
                        "oc_role": role or "unknown",
                        "age": age_str,
                        "files_cleaned": count,
                        "reason": f"global_limit ({len(all_active)} > {MAX_CONCURRENT_ACP})",
                    }
                )
            else:
                errors.append(f"Failed to kill {sess_key} (global limit)")

    return {
        "killed": killed,
        "files_cleaned": files_cleaned,
        "duplicates_found": duplicates_found,
        "errors": errors,
        "by_oc_role": {r: len(s) for r, s in by_oc_role.items()},
        "total_active": sum(len(s) for s in by_oc_role.values()),
        "searxng_action": manage_searxng_ram(),
        "cancelled_pipeline_cleanup": cleanup,
    }


def main() -> None:
    result = run_guard()
    killed = result["killed"]
    errors = result["errors"]
    dupes = result["duplicates_found"]

    if not killed and not errors:
        sxng_msg = result.get("searxng_action", "")
        if sxng_msg and sxng_msg != "No change needed":
            print(f"✓ Guard: {result['total_active']} active sessions — {sxng_msg}")
        else:
            print(f"✓ Guard: {result['total_active']} active sessions, {len(dupes)} duplicate groups — no action needed.")
        return

    for k in killed:
        reason = k.get("reason", "S2 duplicate")
        print(
            f"✗ Killed {k.get('oc_role','?')} session {k['session_key']} "
            f"(task={k.get('task_key','?')}, age={k['age']}, files={k['files_cleaned']}) "
            f"[{reason}]"
        )

    for e in errors:
        print(f"! Error: {e}")

    # Write last-run summary
    summary_file = Path("/Users/lhaclaw/AI-Project-Workspace/Job Seeking Tool/viewer/session_guard_last_run.json")
    _save_json(summary_file, {
        **result,
        "ran_at": datetime.now().isoformat(),
    })


if __name__ == "__main__":
    main()
