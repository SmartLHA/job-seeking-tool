"""Swarm stage timing helpers and stage-derivation state machine."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "shared_memory.db"
VALID_STAGES = ("spec", "design", "build", "review", "qa", "ship")
STAGE_ORDINAL = {stage: index for index, stage in enumerate(VALID_STAGES, start=1)}
_ALLOWED_STAGE_TRANSITIONS = {
    "spec": {"design"},
    "design": {"build"},
    "build": {"review", "qa"},
    "review": {"qa"},
    "qa": {"ship"},
    "ship": set(),
}
_STAGE_ROLE_MAP = {"build": "coder", "review": "reviewer", "qa": "qa"}
_STAGE_PRIORITY = {"build": 1, "review": 2, "qa": 3}


def _conn(db_path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def add_swarm_tables(db_path: str | Path | None = None) -> None:
    conn = _conn(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stage_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_run_id TEXT    NOT NULL,
                stage           TEXT    NOT NULL,
                attempt_no      INTEGER NOT NULL DEFAULT 1,
                event_type      TEXT    NOT NULL CHECK(event_type IN (
                    'stage_started', 'stage_completed', 'stage_failed', 'stage_cancelled',
                    'review_submitted', 'review_approved', 'review_revised',
                    'retry_created', 'admin_override', 'pipeline_closed'
                )),
                agent_name      TEXT,
                occurred_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                meta_json       TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_stage_events_run_stage_attempt "
            "ON stage_events(pipeline_run_id, stage, attempt_no)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_stage_events_occurred ON stage_events(occurred_at)"
        )

        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(stage_handoff_docs)").fetchall()
        }
        if cols and "completed_at" not in cols:
            conn.execute("ALTER TABLE stage_handoff_docs ADD COLUMN completed_at TEXT")
        if cols and "attempt_no" not in cols:
            conn.execute("ALTER TABLE stage_handoff_docs ADD COLUMN attempt_no INTEGER NOT NULL DEFAULT 1")
        conn.commit()
    finally:
        conn.close()



def derive_pipeline_stage(agents: list[dict[str, Any]]) -> str:
    """Derive the current swarm stage from agent execution rows."""
    if not agents:
        return "spec"

    role_status = {agent["agent_role"]: agent["status"] for agent in agents}
    statuses = list(role_status.values())

    if any(status == "cancelled" for status in statuses):
        return "cancelled"
    if any(status in {"failed", "timed_out"} for status in statuses):
        return "failed"

    has_running = any(status == "running" for status in statuses)
    has_queued_or_spawning = any(status in {"queued", "spawning"} for status in statuses)
    any_done = any(status == "done" for status in statuses)

    if not has_running and any_done:
        return "ship"

    if role_status.get("qa") == "running":
        return "qa"
    if role_status.get("reviewer") == "running":
        return "review"
    if role_status.get("coder") == "running" and any_done:
        return "build"

    if has_running and not any_done:
        return "design"
    if has_running and has_queued_or_spawning:
        return "design"
    return "spec"



def _current_attempt_no(conn: sqlite3.Connection, pipeline_run_id: str, stage: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(attempt_no), 1) FROM stage_events WHERE pipeline_run_id = ? AND stage = ?",
        (pipeline_run_id, stage),
    ).fetchone()
    return int(row[0] or 1)



def advance_pipeline_stage(
    session_id: str,
    new_stage: str,
    agent: str,
    db_path: str | Path | None = None,
) -> bool:
    if new_stage not in STAGE_ORDINAL:
        raise ValueError(f"new_stage must be one of {VALID_STAGES}")

    conn = _conn(db_path)
    try:
        add_swarm_tables(db_path)
        run = conn.execute(
            "SELECT session_id, COALESCE(uuid, session_id), current_stage, current_agent FROM pipeline_runs WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if run is None:
            return False

        pipeline_run_id = run[1]
        current_stage = run[2]
        current_agent = run[3]
        if current_stage:
            new_ord = STAGE_ORDINAL[new_stage]
            current_ord = STAGE_ORDINAL[current_stage]
            if new_ord < current_ord:
                raise sqlite3.IntegrityError("stage transitions must be forward-only: no backward moves")
            if new_stage != current_stage and new_stage not in _ALLOWED_STAGE_TRANSITIONS.get(current_stage, set()):
                raise sqlite3.IntegrityError("stage transitions must follow the allowed pipeline flow")

        conn.execute("BEGIN IMMEDIATE")
        try:
            if current_stage and current_stage != new_stage:
                conn.execute(
                    "UPDATE stage_handoff_docs SET completed_at = datetime('now') WHERE pipeline_run_id = ? AND stage = ? AND version = (SELECT MAX(version) FROM stage_handoff_docs WHERE pipeline_run_id = ? AND stage = ?)",
                    (pipeline_run_id, current_stage, pipeline_run_id, current_stage),
                )
                conn.execute(
                    "INSERT INTO stage_events (pipeline_run_id, stage, attempt_no, event_type, agent_name) VALUES (?, ?, ?, 'stage_completed', ?)",
                    (pipeline_run_id, current_stage, _current_attempt_no(conn, pipeline_run_id, current_stage), current_agent or agent),
                )

            conn.execute(
                "UPDATE pipeline_runs SET current_stage = ?, current_agent = ?, updated_at = datetime('now') WHERE session_id = ?",
                (new_stage, agent, session_id),
            )
            conn.execute(
                "INSERT INTO stage_events (pipeline_run_id, stage, attempt_no, event_type, agent_name, meta_json) VALUES (?, ?, ?, 'stage_started', ?, ?)",
                (pipeline_run_id, new_stage, _current_attempt_no(conn, pipeline_run_id, new_stage), agent, json.dumps({"session_id": session_id})),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return True
    finally:
        conn.close()



def get_stage_timing(pipeline_run_id: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    conn = _conn(db_path)
    try:
        docs = conn.execute(
            "SELECT stage, producer_agent, generated_at, completed_at FROM stage_handoff_docs WHERE pipeline_run_id = ? ORDER BY generated_at ASC",
            (pipeline_run_id,),
        ).fetchall()
        if docs:
            return [
                {
                    "stage": row[0],
                    "agent_name": row[1],
                    "started_at": row[2],
                    "completed_at": row[3],
                }
                for row in docs
            ]

        rows = conn.execute(
            """
            SELECT stage,
                   MIN(CASE WHEN event_type = 'stage_started' THEN occurred_at END) AS started_at,
                   MAX(CASE WHEN event_type IN ('stage_completed', 'stage_failed', 'stage_cancelled', 'pipeline_closed') THEN occurred_at END) AS completed_at,
                   MAX(agent_name) AS agent_name
            FROM stage_events
            WHERE pipeline_run_id = ?
            GROUP BY stage, attempt_no
            ORDER BY MIN(occurred_at) ASC
            """,
            (pipeline_run_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

# ── Copied from main workspace shared_bus.py (v2 - full version) ─────────────

def get_pipeline_runs(
    db_path: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return recent pipeline_runs rows (most recent first)."""
    conn = _conn(db_path if db_path else str(DB_PATH))
    try:
        rows = conn.execute(
            "SELECT * FROM pipeline_runs ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            return []
        cols = [c[0] for c in conn.execute(
            "SELECT * FROM pipeline_runs LIMIT 0"
        ).description]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()

def get_active_pipelines(db_path: str | None = None) -> list[dict[str, Any]]:
    """Return pipeline_runs where status='active'."""
    conn = _conn(db_path if db_path else str(DB_PATH))
    try:
        rows = conn.execute(
            "SELECT * FROM pipeline_runs WHERE status = 'active' ORDER BY updated_at DESC"
        ).fetchall()
        if not rows:
            return []
        cols = [c[0] for c in conn.execute(
            "SELECT * FROM pipeline_runs LIMIT 0"
        ).description]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()

_lock = threading.Lock()

def _conn(path: str | None = None) -> sqlite3.Connection:
    path_str = str(path) if path else str(DB_PATH)
    is_uri = 'mode=memory' in path_str or path_str.startswith('file://')
    conn = sqlite3.connect(path_str, uri=is_uri, timeout=5.0, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA trusted_schema = OFF")
    return conn

DB_PATH = Path.home() / ".openclaw" / "workspace" / "shared_memory.db"

def get_agent_executions(
    pipeline_run_id: str,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Return all agent_executions rows for a pipeline_run_id, as dicts."""
    conn = _conn(db_path if db_path else str(DB_PATH))
    try:
        rows = conn.execute(
            "SELECT * FROM agent_executions WHERE pipeline_run_id = ? ORDER BY created_at",
            (pipeline_run_id,),
        ).fetchall()
        if not rows:
            return []
        cols = [c[0] for c in conn.execute(
            "SELECT * FROM agent_executions LIMIT 0"
        ).description]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()
