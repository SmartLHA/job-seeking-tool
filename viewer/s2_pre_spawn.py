#!/usr/bin/env python3
"""
S2 Pre-Spawn Check — Child Session Protocol Option B

Run this before sessions_spawn to check for duplicates.

Usage:
    python3 s2_pre_spawn.py <task_key> <role>

    task_key: unique identifier, e.g. handy-url-ingestion, scout-cv-tailoring
    role: dev | qa | reviewer

Output:
    EXISTING:<session_key>  — duplicate found, reuse this session
    SPAWN                       — no duplicate, proceed with spawn
    ERROR:<message>             — something went wrong, proceed with spawn

Examples:
    python3 s2_pre_spawn.py handy-url-ingestion dev
    python3 s2_pre_spawn.py scout-cv-tailoring qa
"""

import json
import re
import sys
from pathlib import Path

# ─── Config ────────────────────────────────────────────────────────────────────
AGENTS_DIR = Path("/Users/lhaclaw/.openclaw/agents")
TASK_IDS_FILE = Path("/Users/lhaclaw/AI-Project-Workspace/Job Seeking Tool/viewer/task_ids.json")

# Role → agent directory mapping
ROLE_TO_AGENT = {
    "dev": "dev",
    "qa": "qa",
    "reviewer": "wiser",
}

# Active statuses — sessions with these statuses are considered "alive"
ACTIVE_STATUSES = {"running", "waiting"}


def parse_label(label: str) -> dict | None:
    """Parse 'oc_task=<task_key>;oc_role=<role>;title=<title>' from session label."""
    if not label:
        return None
    m = re.match(r"oc_task=([^;]+);oc_role=([^;]+);title=(.+)", label)
    if m:
        return {"task_key": m.group(1), "role": m.group(2), "title": m.group(3)}
    return None


def load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def save_json(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=2))
    except Exception:
        pass  # Non-fatal — task_ids.json is for cron cleanup only


def check_duplicate(task_key: str, role: str) -> str:
    """
    Check if an active session exists for task_key + role.
    Returns:
        'EXISTING:<session_key>'  if duplicate found
        'SPAWN'                   if no duplicate
        'ERROR:<message>'          if something went wrong
    """
    agent_name = ROLE_TO_AGENT.get(role)
    if not agent_name:
        return f"ERROR: Unknown role '{role}'"

    sessions_file = AGENTS_DIR / agent_name / "sessions" / "sessions.json"
    if not sessions_file.exists():
        return "SPAWN"

    sessions = load_json(sessions_file)

    for session_key, val in sessions.items():
        status = val.get("status", "")
        if status not in ACTIVE_STATUSES:
            continue

        label = val.get("label", "")
        parsed = parse_label(label)
        if not parsed:
            continue

        if parsed["task_key"] == task_key and parsed["role"] == role:
            return f"EXISTING:{session_key}"

    return "SPAWN"


def register_session(session_key: str, task_id: str) -> None:
    """Write session_key → task_id mapping to task_ids.json."""
    data = load_json(TASK_IDS_FILE)
    data[session_key] = task_id
    save_json(TASK_IDS_FILE, data)


# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: s2_pre_spawn.py <task_key> <role>")
        sys.exit(1)

    task_key = sys.argv[1]
    role = sys.argv[2]

    result = check_duplicate(task_key, role)
    print(result)
