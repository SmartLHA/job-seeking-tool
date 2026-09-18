"""Tests for shared_bus getter functions — pipeline_runs and agent_executions queries."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src import shared_bus


def _init_test_db(db_path: Path) -> None:
    """Initialize test database with minimal pipeline_runs and agent_executions tables."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                uuid TEXT,
                status TEXT DEFAULT 'pending',
                current_stage TEXT,
                current_agent TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE agent_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_run_id TEXT NOT NULL,
                agent_role TEXT,
                status TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create an initialized test database."""
    db_path = tmp_path / "test.db"
    _init_test_db(db_path)
    return db_path


class TestGetPipelineRuns:
    def test_get_pipeline_runs_empty(self, test_db: Path) -> None:
        """get_pipeline_runs returns empty list when no runs exist."""
        runs = shared_bus.get_pipeline_runs(db_path=str(test_db))
        assert runs == []

    def test_get_pipeline_runs_single_run(self, test_db: Path) -> None:
        """get_pipeline_runs returns a single run as dict."""
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO pipeline_runs (session_id, status, current_stage) VALUES (?, ?, ?)",
            ("session-001", "active", "build"),
        )
        conn.commit()
        conn.close()

        runs = shared_bus.get_pipeline_runs(db_path=str(test_db))

        assert len(runs) == 1
        assert runs[0]["session_id"] == "session-001"
        assert runs[0]["status"] == "active"
        assert runs[0]["current_stage"] == "build"

    def test_get_pipeline_runs_multiple_runs_ordered_by_updated_at(self, test_db: Path) -> None:
        """get_pipeline_runs returns multiple runs, most recent first."""
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO pipeline_runs (session_id, status, updated_at) VALUES (?, ?, ?)",
            ("session-001", "completed", "2026-01-01T10:00:00Z"),
        )
        conn.execute(
            "INSERT INTO pipeline_runs (session_id, status, updated_at) VALUES (?, ?, ?)",
            ("session-002", "active", "2026-01-02T10:00:00Z"),
        )
        conn.execute(
            "INSERT INTO pipeline_runs (session_id, status, updated_at) VALUES (?, ?, ?)",
            ("session-003", "pending", "2026-01-03T10:00:00Z"),
        )
        conn.commit()
        conn.close()

        runs = shared_bus.get_pipeline_runs(db_path=str(test_db))

        assert len(runs) == 3
        # Most recent first
        assert runs[0]["session_id"] == "session-003"
        assert runs[1]["session_id"] == "session-002"
        assert runs[2]["session_id"] == "session-001"

    def test_get_pipeline_runs_respects_limit(self, test_db: Path) -> None:
        """get_pipeline_runs returns at most 'limit' rows."""
        conn = sqlite3.connect(str(test_db))
        for i in range(10):
            conn.execute(
                "INSERT INTO pipeline_runs (session_id, status) VALUES (?, ?)",
                (f"session-{i:03d}", "active"),
            )
        conn.commit()
        conn.close()

        runs = shared_bus.get_pipeline_runs(db_path=str(test_db), limit=5)

        assert len(runs) == 5

    def test_get_pipeline_runs_default_limit(self, test_db: Path) -> None:
        """get_pipeline_runs defaults to limit=20."""
        conn = sqlite3.connect(str(test_db))
        for i in range(25):
            conn.execute(
                "INSERT INTO pipeline_runs (session_id) VALUES (?)",
                (f"session-{i:03d}",),
            )
        conn.commit()
        conn.close()

        runs = shared_bus.get_pipeline_runs(db_path=str(test_db))

        assert len(runs) == 20


class TestGetActivePipelines:
    def test_get_active_pipelines_empty(self, test_db: Path) -> None:
        """get_active_pipelines returns empty list when no active runs exist."""
        runs = shared_bus.get_active_pipelines(db_path=str(test_db))
        assert runs == []

    def test_get_active_pipelines_filters_by_status(self, test_db: Path) -> None:
        """get_active_pipelines returns only status='active' runs."""
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO pipeline_runs (session_id, status) VALUES (?, ?)",
            ("session-001", "active"),
        )
        conn.execute(
            "INSERT INTO pipeline_runs (session_id, status) VALUES (?, ?)",
            ("session-002", "completed"),
        )
        conn.execute(
            "INSERT INTO pipeline_runs (session_id, status) VALUES (?, ?)",
            ("session-003", "active"),
        )
        conn.commit()
        conn.close()

        active = shared_bus.get_active_pipelines(db_path=str(test_db))

        assert len(active) == 2
        assert all(r["status"] == "active" for r in active)
        assert {r["session_id"] for r in active} == {"session-001", "session-003"}

    def test_get_active_pipelines_ordered_by_updated_at(self, test_db: Path) -> None:
        """get_active_pipelines returns most recent first."""
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO pipeline_runs (session_id, status, updated_at) VALUES (?, ?, ?)",
            ("session-001", "active", "2026-01-01T10:00:00Z"),
        )
        conn.execute(
            "INSERT INTO pipeline_runs (session_id, status, updated_at) VALUES (?, ?, ?)",
            ("session-002", "active", "2026-01-02T10:00:00Z"),
        )
        conn.commit()
        conn.close()

        active = shared_bus.get_active_pipelines(db_path=str(test_db))

        assert len(active) == 2
        assert active[0]["session_id"] == "session-002"
        assert active[1]["session_id"] == "session-001"


class TestGetAgentExecutions:
    def test_get_agent_executions_empty(self, test_db: Path) -> None:
        """get_agent_executions returns empty list when no executions exist."""
        execs = shared_bus.get_agent_executions(
            "run-001",
            db_path=str(test_db),
        )
        assert execs == []

    def test_get_agent_executions_filters_by_pipeline_run_id(self, test_db: Path) -> None:
        """get_agent_executions returns only executions for the given pipeline_run_id."""
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO agent_executions (pipeline_run_id, agent_role, status) VALUES (?, ?, ?)",
            ("run-001", "coder", "done"),
        )
        conn.execute(
            "INSERT INTO agent_executions (pipeline_run_id, agent_role, status) VALUES (?, ?, ?)",
            ("run-002", "reviewer", "done"),
        )
        conn.execute(
            "INSERT INTO agent_executions (pipeline_run_id, agent_role, status) VALUES (?, ?, ?)",
            ("run-001", "reviewer", "running"),
        )
        conn.commit()
        conn.close()

        execs = shared_bus.get_agent_executions(
            "run-001",
            db_path=str(test_db),
        )

        assert len(execs) == 2
        assert all(e["pipeline_run_id"] == "run-001" for e in execs)
        roles = {e["agent_role"] for e in execs}
        assert roles == {"coder", "reviewer"}

    def test_get_agent_executions_ordered_by_created_at(self, test_db: Path) -> None:
        """get_agent_executions returns executions ordered by created_at."""
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO agent_executions (pipeline_run_id, agent_role, created_at) VALUES (?, ?, ?)",
            ("run-001", "reviewer", "2026-01-02T10:00:00Z"),
        )
        conn.execute(
            "INSERT INTO agent_executions (pipeline_run_id, agent_role, created_at) VALUES (?, ?, ?)",
            ("run-001", "coder", "2026-01-01T10:00:00Z"),
        )
        conn.commit()
        conn.close()

        execs = shared_bus.get_agent_executions(
            "run-001",
            db_path=str(test_db),
        )

        assert len(execs) == 2
        assert execs[0]["agent_role"] == "coder"
        assert execs[1]["agent_role"] == "reviewer"

    def test_get_agent_executions_multiple_runs(self, test_db: Path) -> None:
        """get_agent_executions only returns data for the specified run."""
        conn = sqlite3.connect(str(test_db))
        for run_id in ["run-001", "run-002", "run-003"]:
            conn.execute(
                "INSERT INTO agent_executions (pipeline_run_id, agent_role) VALUES (?, ?)",
                (run_id, "coder"),
            )
        conn.commit()
        conn.close()

        execs = shared_bus.get_agent_executions(
            "run-002",
            db_path=str(test_db),
        )

        assert len(execs) == 1
        assert execs[0]["pipeline_run_id"] == "run-002"

    def test_get_agent_executions_empty_for_missing_run(self, test_db: Path) -> None:
        """get_agent_executions returns empty list for nonexistent run."""
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO agent_executions (pipeline_run_id, agent_role) VALUES (?, ?)",
            ("run-001", "coder"),
        )
        conn.commit()
        conn.close()

        execs = shared_bus.get_agent_executions(
            "run-999",
            db_path=str(test_db),
        )

        assert execs == []
