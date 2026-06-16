from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.job_hunt_index import (
    open_db,
    query_board,
    query_jobs_list,
    rebuild_index,
    upsert_job,
)
from src.job_hunt_storage import ensure_storage_layout, save_application_outcome, save_reviewed_job
from src.job_hunt_outcomes import create_outcome_record, update_outcome
from src.job_hunt_models import JobPosting


def _minimal_row(
    job_id: str = "job-001",
    status: str = "not_applied",
    **kwargs,
) -> dict:
    base = {
        "job_id": job_id,
        "job_title": "Business Analyst",
        "company": "Example Co",
        "location": "London",
        "source": "copied_text",
        "match_score": 75.0,
        "decision": "apply",
        "user_decision": None,
        "ats_score": 80,
        "tailoring_ready": True,
        "status": status,
        "updated_at": "2026-01-01T00:00:00Z",
        "salary_min": 50000,
        "salary_max": 60000,
    }
    base.update(kwargs)
    return base


def test_upsert_and_query_jobs_list(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    upsert_job(db_path, _minimal_row("job-001"))
    upsert_job(db_path, _minimal_row("job-002", job_title="Data Analyst", company="Tech Corp"))

    jobs = query_jobs_list(db_path)
    assert len(jobs) == 2
    ids = {j["job_id"] for j in jobs}
    assert ids == {"job-001", "job-002"}

    # Check shape — each item must have allowed_transitions
    for job in jobs:
        assert "allowed_transitions" in job
        assert "job_id" in job
        assert "status" in job
        assert "job_title" in job
        assert "company" in job


def test_query_board_groups_by_status(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    upsert_job(db_path, _minimal_row("job-001", status="not_applied"))
    upsert_job(db_path, _minimal_row("job-002", status="applied"))
    upsert_job(db_path, _minimal_row("job-003", status="interview"))
    upsert_job(db_path, _minimal_row("job-004", status="offer"))
    upsert_job(db_path, _minimal_row("job-005", status="rejected"))
    upsert_job(db_path, _minimal_row("job-006", status="withdrawn"))

    board = query_board(db_path)
    assert "columns" in board
    cols = board["columns"]

    assert any(j["job_id"] == "job-001" for j in cols["not_applied"])
    assert any(j["job_id"] == "job-002" for j in cols["applied"])
    assert any(j["job_id"] == "job-003" for j in cols["interview"])
    assert any(j["job_id"] == "job-004" for j in cols["offer"])
    assert any(j["job_id"] == "job-005" for j in cols["rejected"])
    assert any(j["job_id"] == "job-006" for j in cols["withdrawn"])


def test_query_board_stats(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    # not_applied=2, applied=3, interview=2, offer=1, rejected=2, withdrawn=1
    for i in range(2):
        upsert_job(db_path, _minimal_row(f"na-{i}", status="not_applied"))
    for i in range(3):
        upsert_job(db_path, _minimal_row(f"ap-{i}", status="applied"))
    for i in range(2):
        upsert_job(db_path, _minimal_row(f"iv-{i}", status="interview"))
    upsert_job(db_path, _minimal_row("of-0", status="offer"))
    for i in range(2):
        upsert_job(db_path, _minimal_row(f"rj-{i}", status="rejected"))
    upsert_job(db_path, _minimal_row("wd-0", status="withdrawn"))

    board = query_board(db_path)
    stats = board["stats"]

    # active = not_applied(2) + applied(3) + interview(2) + offer(1) = 8
    assert stats["active"] == 8
    assert stats["interviews"] == 2
    assert stats["offers"] == 1
    # response_rate = (2 + 1) / (3 + 2 + 1 + 2) = 3/8 = 0.375
    assert abs(stats["response_rate"] - 3 / 8) < 1e-9


def test_query_board_stats_zero_denominator(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    upsert_job(db_path, _minimal_row("job-001", status="not_applied"))

    board = query_board(db_path)
    assert board["stats"]["response_rate"] == 0.0


def test_allowed_transitions_on_board_card(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    upsert_job(db_path, _minimal_row("job-001", status="applied"))

    board = query_board(db_path)
    cards = board["columns"]["applied"]
    assert len(cards) == 1
    assert set(cards[0]["allowed_transitions"]) == {"interview", "rejected", "withdrawn"}


def test_upsert_replaces_existing_row(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    upsert_job(db_path, _minimal_row("job-001", job_title="Old Title", status="not_applied"))
    upsert_job(db_path, _minimal_row("job-001", job_title="New Title", status="applied"))

    jobs = query_jobs_list(db_path)
    assert len(jobs) == 1
    assert jobs[0]["job_title"] == "New Title"
    assert jobs[0]["status"] == "applied"


def test_upsert_tailoring_ready_none_stores_null(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    row = _minimal_row("job-null")
    row["tailoring_ready"] = None
    upsert_job(db_path, row)

    jobs = query_jobs_list(db_path)
    assert len(jobs) == 1
    assert jobs[0]["tailoring_ready"] is None


def _build_test_job(job_id: str = "job-001") -> JobPosting:
    return JobPosting(
        job_id=job_id,
        job_title="Business Analyst",
        company="Example Co",
        description_raw="Job description for testing.",
        source_type="copied_text",
        source_ref=None,
        location="London",
        work_mode="hybrid",
        employment_type="full-time",
        salary_min_gbp=50000,
        salary_max_gbp=60000,
    )


def test_rebuild_index_from_json_files(tmp_path: Path) -> None:
    layout = ensure_storage_layout(tmp_path / "state")

    # Save two jobs with outcomes
    for job_id in ("job-001", "job-002"):
        job = _build_test_job(job_id)
        save_reviewed_job(job, layout.root)
        outcome = create_outcome_record(job_id)
        save_application_outcome(outcome, layout.root)

    db_path = tmp_path / "test.db"
    count = rebuild_index(layout, db_path)

    assert count == 2
    jobs = query_jobs_list(db_path)
    assert len(jobs) == 2
    ids = {j["job_id"] for j in jobs}
    assert ids == {"job-001", "job-002"}
    for job in jobs:
        assert job["status"] == "not_applied"
        assert job["job_title"] == "Business Analyst"
        assert job["company"] == "Example Co"


def test_rebuild_index_skips_bad_files(tmp_path: Path) -> None:
    layout = ensure_storage_layout(tmp_path / "state")

    # Write a valid job
    job = _build_test_job("job-good")
    save_reviewed_job(job, layout.root)
    outcome = create_outcome_record("job-good")
    save_application_outcome(outcome, layout.root)

    # Write a corrupt JSON file in the outcomes dir
    (layout.outcomes_dir / "job-bad.json").write_text("not valid json", encoding="utf-8")

    db_path = tmp_path / "test.db"
    # Should not crash
    count = rebuild_index(layout, db_path)

    # At least the good job gets indexed; the bad one gets skipped
    jobs = query_jobs_list(db_path)
    good_ids = {j["job_id"] for j in jobs if j["job_id"] == "job-good"}
    assert "job-good" in good_ids


def test_rebuild_wipes_existing_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    upsert_job(db_path, _minimal_row("stale-job"))

    layout = ensure_storage_layout(tmp_path / "state")
    count = rebuild_index(layout, db_path)

    jobs = query_jobs_list(db_path)
    assert all(j["job_id"] != "stale-job" for j in jobs)
    assert count == 0  # No JSON files exist
