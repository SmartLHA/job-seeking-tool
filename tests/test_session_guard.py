from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VIEWER_DIR = REPO_ROOT / "viewer"
if str(VIEWER_DIR) not in sys.path:
    sys.path.insert(0, str(VIEWER_DIR))

import session_guard


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE pipeline_runs (session_id TEXT PRIMARY KEY, uuid TEXT, status TEXT)"
    )
    conn.execute(
        "CREATE TABLE agent_executions (execution_id TEXT PRIMARY KEY, pipeline_run_id TEXT, status TEXT, created_at TEXT)"
    )
    conn.executemany(
        "INSERT INTO pipeline_runs (session_id, uuid, status) VALUES (?, ?, ?)",
        [
            ("sess-cancelled", "pipe-cancelled", "cancelled"),
            ("sess-active", "pipe-active", "active"),
            ("sess-null-uuid", None, "cancelled"),
        ],
    )
    conn.executemany(
        "INSERT INTO agent_executions (execution_id, pipeline_run_id, status, created_at) VALUES (?, ?, ?, datetime('now'))",
        [
            ("exec-1", "pipe-cancelled", "cancelled"),
            ("exec-2", "pipe-cancelled", "queued"),
            ("exec-3", "pipe-active", "running"),
            ("exec-4", "sess-null-uuid", "queued"),
        ],
    )
    conn.commit()
    conn.close()


def test_cleanup_cancelled_pipeline_agent_executions_deletes_all_pipeline_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "shared_memory.db"
    _make_db(db_path)

    result = session_guard._cleanup_cancelled_pipeline_agent_executions(db_path)

    conn = sqlite3.connect(db_path)
    remaining = conn.execute(
        "SELECT execution_id, pipeline_run_id FROM agent_executions ORDER BY execution_id"
    ).fetchall()
    conn.close()

    assert result == {
        "deleted": 3,
        "pipelines": 2,
        "db_path": str(db_path),
    }
    assert remaining == [("exec-3", "pipe-active")]


def test_run_guard_reports_cancelled_pipeline_cleanup(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "shared_memory.db"
    _make_db(db_path)

    task_ids_file = tmp_path / "viewer" / "task_ids.json"
    task_ids_file.parent.mkdir(parents=True, exist_ok=True)
    agent_sessions_dir = tmp_path / "agents"
    agent_sessions_dir.mkdir()
    main_sessions_file = tmp_path / "sessions.json"

    monkeypatch.setattr(session_guard, "SHARED_MEMORY_DB_PATH", db_path)
    monkeypatch.setattr(session_guard, "TASK_IDS_FILE", task_ids_file)
    monkeypatch.setattr(session_guard, "AGENT_SESSIONS_DIR", agent_sessions_dir)
    monkeypatch.setattr(session_guard, "SESSIONS_FILE", main_sessions_file)
    monkeypatch.setattr(session_guard, "manage_searxng_ram", lambda: "No change needed")

    result = session_guard.run_guard()

    assert result["cancelled_pipeline_cleanup"] == {
        "deleted": 3,
        "pipelines": 2,
        "db_path": str(db_path),
    }
    assert result["killed"] == []
    assert result["errors"] == []
    assert task_ids_file.read_text() == "{}"
