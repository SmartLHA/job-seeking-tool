#!/usr/bin/env python3
"""
Session Guard — S2: one-session-per-role-per-task

Enforcement rules:
  - MAX_CONCURRENT_ACP_SESSIONS = 4  (global ACP limit)
  - Per role: at most 1 active session with the same task_id
  - task_id is stored in task_ids.json sidecar (written by agent at spawn time)
  - If task_id is missing for a session, it is treated as "no task" — deduplication
    is skipped for that session (safe: allows non-task sessions)

On duplicate found:
  - Kills the OLDER session (keeps newest)
  - Cleans up orphaned JSONL transcript files
"""

import json
import os
import re
import subprocess
import glob
import sys
from pathlib import Path
from datetime import datetime

# ─── Config ────────────────────────────────────────────────────────────────────
MAX_CONCURRENT_ACP = 4
SESSIONS_FILE = Path("/Users/lhaclaw/.openclaw/agents/main/sessions/sessions.json")
TASK_IDS_FILE = Path("/Users/lhaclaw/AI-Project-Workspace/Job Seeking Tool/viewer/task_ids.json")
AGENT_SESSIONS_DIR = Path("/Users/lhaclaw/.openclaw/agents")

# Roles managed by this guard (maps role label → agent id in sessions.json)
ROLES = {
    "planner": "main",
    "handy": "codex",
    "scout": "qa",
    "reviewer": "reviewer",  # placeholder — no reviewer agent yet
}

# Sessions older than this (in ms) that are still "running" are considered stale
STALE_THRESHOLD_MS = 30 * 60 * 1000  # 30 minutes


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


def _extract_role(session_key: str) -> str | None:
    """Infer role from session key pattern."""
    # agent:codex:acp:...  → handy
    # agent:qa:subagent:... → scout
    # agent:reviewer:...   → reviewer
    # agent:main:...        → planner
    if ":acp:" in session_key:
        return "handy"
    if ":subagent:" in session_key:
        return "scout"
    if ":reviewer:" in session_key:
        return "reviewer"
    if ":main:" in session_key:
        return "planner"
    return None


def _active_status(status: str) -> bool:
    """Return True if session status means actively running/waiting."""
    return status in ("running", "waiting", "active")


def run_guard() -> dict:
    """
    Main guard logic.
    Returns a dict with 'killed', 'files_cleaned', 'duplicates_found', 'errors'.
    """
    now_ms = datetime.now().timestamp() * 1000
    task_ids = _load_json(TASK_IDS_FILE)  # session_key → task_id
    sessions_data = _load_json(SESSIONS_FILE)

    # Build list of active ACP sessions per role
    # sessions_data: { session_key: { sessionId, status, updatedAt, ... } }
    by_role: dict[str, list[tuple]] = {}  # role → [(session_key, session_id, updatedAt, task_id, status)]

    for session_key, val in sessions_data.items():
        role = _extract_role(session_key)
        if role is None:
            continue
        status = val.get("status", "")
        if not _active_status(status):
            continue
        session_id = val.get("sessionId", "")
        updated_at = val.get("updatedAt", 0)
        task_id = task_ids.get(session_key, None)  # None if not set
        by_role.setdefault(role, []).append(
            (session_key, session_id, updated_at, task_id, status)
        )

    killed = []
    files_cleaned = 0
    errors = []
    duplicates_found = []

    # ── Rule S2: one-session-per-role-per-task ────────────────────────────────
    for role, sessions in by_role.items():
        # Group by task_id (None = no task assigned, allow multiple)
        by_task: dict[str | None, list] = {}
        for sess in sessions:
            task_id = sess[3]  # None if missing
            by_task.setdefault(task_id, []).append(sess)

        for task_id, task_sessions in by_task.items():
            if task_id is None:
                # No task_id — skip deduplication (open sessions without task tracking)
                continue
            if len(task_sessions) <= 1:
                continue

            # Duplicate found — keep newest, kill older ones
            task_sessions.sort(key=lambda x: x[2], reverse=True)  # sort by updatedAt desc
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
                            "task_id": task_id,
                            "role": role,
                            "age": age_str,
                            "files_cleaned": count,
                        }
                    )
                else:
                    errors.append(f"Failed to kill {sess_key} (task={task_id}, role={role})")
                duplicates_found.append(
                    {
                        "role": role,
                        "task_id": task_id,
                        "kept": keep[0],
                        "killed": [s[0] for s in to_kill],
                    }
                )

    # ── Rule: global ACP concurrent limit (oldest first to kill) ─────────────
    all_active = [
        (sess_key, val.get("sessionId", ""), val.get("updatedAt", 0), _extract_role(sess_key))
        for sess_key, val in sessions_data.items()
        if _active_status(val.get("status", ""))
        and _extract_role(sess_key) in [None]  # only roles we manage
    ]
    if len(all_active) > MAX_CONCURRENT_ACP:
        all_active.sort(key=lambda x: x[2])  # oldest first
        excess = all_active[MAX_CONCURRENT_ACP:]
        for sess_key, sess_id, updated_at, role in excess:
            # Skip if already killed by S2
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
                        "role": role or "unknown",
                        "age": age_str,
                        "files_cleaned": count,
                        "reason": f"global_limit ({len(all_active)} > {MAX_CONCURRENT_ACP})",
                    }
                )
            else:
                errors.append(f"Failed to kill {sess_key} (global limit)")

    # ── Prune task_ids.json: remove entries for deleted sessions ────────────────
    alive_keys = set(sessions_data.keys())
    pruned_task_ids = {k: v for k, v in task_ids.items() if k in alive_keys}
    if len(pruned_task_ids) != len(task_ids):
        _save_json(TASK_IDS_FILE, pruned_task_ids)

    return {
        "killed": killed,
        "files_cleaned": files_cleaned,
        "duplicates_found": duplicates_found,
        "errors": errors,
        "by_role": {r: len(s) for r, s in by_role.items()},
        "total_active": sum(len(s) for s in by_role.values()),
    }


def main() -> None:
    result = run_guard()
    killed = result["killed"]
    errors = result["errors"]
    dupes = result["duplicates_found"]

    if not killed and not errors:
        print(f"✓ Guard: {result['total_active']} active sessions, {len(dupes)} duplicate groups — no action needed.")
        return

    for k in killed:
        reason = k.get("reason", "S2 duplicate")
        print(
            f"✗ Killed {k['role']} session {k['session_key']} "
            f"(task={k.get('task_id','?')}, age={k['age']}, files={k['files_cleaned']}) "
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
