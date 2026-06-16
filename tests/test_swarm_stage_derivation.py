"""Tests for swarm stage derivation and stage timing helpers."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from shared_bus import add_swarm_tables, advance_pipeline_stage, derive_pipeline_stage, get_stage_timing


def _a(role: str, status: str) -> dict[str, str]:
    return {"agent_role": role, "status": status, "execution_id": "test-id"}


class TestStageDerivation:
    def test_cancelled_wins_over_all(self) -> None:
        assert derive_pipeline_stage([_a("researcher", "done"), _a("coder", "running"), _a("qa", "cancelled")]) == "cancelled"

    def test_failed_wins(self) -> None:
        assert derive_pipeline_stage([_a("researcher", "done"), _a("coder", "failed"), _a("qa", "done")]) == "failed"

    def test_ship_when_no_running_and_some_done(self) -> None:
        assert derive_pipeline_stage([_a("researcher", "done"), _a("coder", "queued")]) == "ship"

    def test_qa_wins_over_review_and_build(self) -> None:
        assert derive_pipeline_stage([_a("coder", "running"), _a("reviewer", "running"), _a("qa", "running")]) == "qa"

    def test_review_wins_over_build(self) -> None:
        assert derive_pipeline_stage([_a("researcher", "done"), _a("coder", "running"), _a("reviewer", "running")]) == "review"

    def test_design_when_all_running_without_done(self) -> None:
        assert derive_pipeline_stage([_a("researcher", "running"), _a("coder", "running")]) == "design"

    def test_spec_default(self) -> None:
        assert derive_pipeline_stage([]) == "spec"


class TestStageTimingStateMachine:
    def test_add_swarm_tables_adds_stage_events_and_handoff_columns(self, tmp_path: Path) -> None:
        db_path = tmp_path / "shared_memory.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE stage_handoff_docs (pipeline_run_id TEXT, stage TEXT, version INTEGER, generated_at TEXT, producer_agent TEXT)")
        conn.commit()
        conn.close()

        add_swarm_tables(db_path)

        conn = sqlite3.connect(db_path)
        handoff_cols = {row[1] for row in conn.execute("PRAGMA table_info(stage_handoff_docs)")}
        stage_event_cols = {row[1] for row in conn.execute("PRAGMA table_info(stage_events)")}
        conn.close()

        assert "completed_at" in handoff_cols
        assert "attempt_no" in handoff_cols
        assert {"pipeline_run_id", "stage", "event_type", "agent_name", "occurred_at"}.issubset(stage_event_cols)

    def test_advance_pipeline_stage_records_start_and_completion(self, tmp_path: Path) -> None:
        db_path = tmp_path / "shared_memory.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE pipeline_runs (session_id TEXT PRIMARY KEY, uuid TEXT, current_stage TEXT, current_agent TEXT, updated_at TEXT)")
        conn.execute(
            "CREATE TABLE stage_handoff_docs (pipeline_run_id TEXT, stage TEXT, version INTEGER, generated_at TEXT, producer_agent TEXT, completed_at TEXT, attempt_no INTEGER DEFAULT 1)"
        )
        conn.execute("INSERT INTO pipeline_runs VALUES ('sess-1', 'pipe-1', 'design', 'dev', datetime('now'))")
        conn.execute(
            "INSERT INTO stage_handoff_docs (pipeline_run_id, stage, version, generated_at, producer_agent, completed_at, attempt_no) VALUES ('pipe-1', 'design', 1, datetime('now', '-5 minutes'), 'dev', NULL, 1)"
        )
        conn.execute(
            "INSERT INTO stage_handoff_docs (pipeline_run_id, stage, version, generated_at, producer_agent, completed_at, attempt_no) VALUES ('pipe-1', 'build', 1, datetime('now'), 'dev', NULL, 1)"
        )
        conn.commit()
        conn.close()

        assert advance_pipeline_stage('sess-1', 'build', 'dev', db_path) is True

        conn = sqlite3.connect(db_path)
        completed_at = conn.execute(
            "SELECT completed_at FROM stage_handoff_docs WHERE pipeline_run_id = 'pipe-1' AND stage = 'design'"
        ).fetchone()[0]
        events = conn.execute(
            "SELECT stage, event_type, agent_name FROM stage_events WHERE pipeline_run_id = 'pipe-1' ORDER BY id"
        ).fetchall()
        conn.close()

        assert completed_at is not None
        assert events == [("design", "stage_completed", "dev"), ("build", "stage_started", "dev")]

    def test_get_stage_timing_prefers_handoff_docs(self, tmp_path: Path) -> None:
        db_path = tmp_path / "shared_memory.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE stage_handoff_docs (pipeline_run_id TEXT, stage TEXT, version INTEGER, generated_at TEXT, producer_agent TEXT, completed_at TEXT, attempt_no INTEGER DEFAULT 1)"
        )
        conn.execute(
            "INSERT INTO stage_handoff_docs VALUES ('pipe-1', 'build', 1, '2026-04-16 10:00:00', 'helpo', '2026-04-16 10:05:00', 1)"
        )
        conn.commit()
        conn.close()

        add_swarm_tables(db_path)
        timing = get_stage_timing('pipe-1', db_path)

        assert timing == [{"stage": "build", "agent_name": "helpo", "started_at": "2026-04-16 10:00:00", "completed_at": "2026-04-16 10:05:00"}]
