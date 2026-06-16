from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
VIEWER_DIR = REPO_ROOT / "viewer"
for path in (SRC_DIR, VIEWER_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import swarm_router
import shared_bus


def _make_db(db_path: Path, *, current_stage: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE pipeline_runs (session_id TEXT PRIMARY KEY, uuid TEXT, current_stage TEXT, current_agent TEXT, updated_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE stage_handoff_docs (pipeline_run_id TEXT, stage TEXT, version INTEGER, generated_at TEXT, producer_agent TEXT, completed_at TEXT, attempt_no INTEGER DEFAULT 1)"
    )
    conn.execute(
        "INSERT INTO pipeline_runs VALUES ('sess-1', 'pipe-1', ?, 'dev', datetime('now'))",
        (current_stage,),
    )
    conn.execute(
        "INSERT INTO stage_handoff_docs (pipeline_run_id, stage, version, generated_at, producer_agent, completed_at, attempt_no) VALUES ('pipe-1', ?, 1, datetime('now', '-5 minutes'), 'dev', NULL, 1)",
        (current_stage,),
    )
    conn.commit()
    conn.close()
    shared_bus.add_swarm_tables(db_path)


def test_handy_completion_advances_pipeline_to_qa(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "shared_memory.db"
    _make_db(db_path, current_stage="build")
    monkeypatch.setattr(shared_bus, "DB_PATH", db_path)
    monkeypatch.setattr(swarm_router._sb, "DB_PATH", db_path)

    swarm_router._advance_pipeline_stage_if_needed(
        "pipe-1",
        [{"agent_role": "coder", "status": "done", "execution_id": "exec-1"}],
    )

    conn = sqlite3.connect(db_path)
    stage = conn.execute("SELECT current_stage, current_agent FROM pipeline_runs WHERE session_id = 'sess-1'").fetchone()
    events = conn.execute(
        "SELECT stage, event_type, agent_name FROM stage_events WHERE pipeline_run_id = 'pipe-1' ORDER BY id"
    ).fetchall()
    conn.close()

    assert stage == ("qa", "handy")
    assert events == [("build", "stage_completed", "dev"), ("qa", "stage_started", "handy")]


def test_scout_completion_advances_pipeline_to_ship(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "shared_memory.db"
    _make_db(db_path, current_stage="qa")
    monkeypatch.setattr(shared_bus, "DB_PATH", db_path)
    monkeypatch.setattr(swarm_router._sb, "DB_PATH", db_path)

    swarm_router._advance_pipeline_stage_if_needed(
        "pipe-1",
        [{"agent_role": "qa", "status": "done", "execution_id": "exec-qa"}],
    )

    conn = sqlite3.connect(db_path)
    stage = conn.execute("SELECT current_stage, current_agent FROM pipeline_runs WHERE session_id = 'sess-1'").fetchone()
    events = conn.execute(
        "SELECT stage, event_type, agent_name FROM stage_events WHERE pipeline_run_id = 'pipe-1' ORDER BY id"
    ).fetchall()
    conn.close()

    assert stage == ("ship", "scout")
    assert events == [("qa", "stage_completed", "dev"), ("ship", "stage_started", "scout")]
