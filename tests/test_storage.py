from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models import Blocker, JobAnalysis, JobPosting, RiskFlag, ScoreBreakdown, ScoreComponent
from src.outcomes import create_outcome_record, update_outcome
from src.storage import (
    StorageError,
    ensure_storage_layout,
    job_analysis_from_dict,
    load_application_outcome,
    load_job_analysis,
    load_raw_input,
    load_reviewed_job,
    save_application_outcome,
    save_job_analysis,
    save_raw_input,
    save_reviewed_job,
)


def build_job() -> JobPosting:
    return JobPosting(
        job_id="job-001",
        job_title="Business Analyst",
        company="Example Co",
        description_raw="Need stakeholder management and process mapping.",
        source_type="copied_text",
        source_ref=None,
        location="London",
        work_mode="hybrid",
        employment_type="full-time",
        required_skills=["stakeholder management", "process mapping"],
        preferred_skills=["SQL"],
        required_years_experience=3,
        nice_to_have_years_experience=None,
        domain="technology",
        notes="Reviewed by user",
        salary_min_gbp=50000,
        salary_max_gbp=60000,
    )


def build_analysis(job_id: str = "job-001") -> JobAnalysis:
    return JobAnalysis(
        job_id=job_id,
        match_score=82,
        score_breakdown=ScoreBreakdown(
            skills_score=ScoreComponent(value=35, reason="Strong required skill overlap"),
            experience_score=ScoreComponent(value=18, reason="Experience lines up well"),
            location_score=ScoreComponent(value=12, reason="Location is acceptable"),
            salary_score=ScoreComponent(value=9, reason="Salary meets floor"),
            domain_score=ScoreComponent(value=4, reason="Domain fit is acceptable"),
            work_mode_score=ScoreComponent(value=4, reason="Hybrid is acceptable"),
            notes=["Confidence depends on reviewed inputs"],
        ),
        blockers=[
            Blocker(
                code="salary_floor",
                label="Salary floor check",
                reason="Needs confirmation against full package",
                severity="low",
            )
        ],
        strengths=["stakeholder management", "process mapping"],
        missing_required_skills=[],
        missing_preferred_skills=["SQL"],
        risk_flags=[
            RiskFlag(
                code="preferred-skill-gap",
                label="Preferred skill gap",
                reason="SQL is preferred but not clearly evidenced",
            )
        ],
        decision="apply",
        decision_reason="Strong fit with no critical blockers.",
        confidence="medium",
        tailoring_ready=True,
        tailoring_notes="Safe to tailor from approved truth sources.",
    )


def test_ensure_storage_layout_creates_separate_state_directories(tmp_path: Path) -> None:
    layout = ensure_storage_layout(tmp_path / "state")

    assert layout.raw_inputs_dir.is_dir()
    assert layout.reviewed_jobs_dir.is_dir()
    assert layout.analyses_dir.is_dir()
    assert layout.outcomes_dir.is_dir()


def test_save_and_load_raw_input_round_trips_without_touching_reviewed_or_analysis_state(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    raw_payload = {
        "source_type": "copied_text",
        "source_ref": None,
        "payload": "Raw job description text",
        "notes": {"captured_by": "manual"},
    }

    path = save_raw_input(raw_payload, "raw-001", root)
    loaded = load_raw_input("raw-001", root)

    assert path == root / "raw_inputs" / "raw-001.json"
    assert loaded == raw_payload
    assert not (root / "reviewed_jobs" / "raw-001.json").exists()
    assert not (root / "analyses" / "raw-001.json").exists()


def test_save_and_load_reviewed_job_uses_reviewed_state_directory(tmp_path: Path) -> None:
    root = tmp_path / "state"
    job = build_job()

    path = save_reviewed_job(job, root)
    loaded = load_reviewed_job(job.job_id, root)

    assert path == root / "reviewed_jobs" / "job-001.json"
    assert loaded == job
    assert not (root / "raw_inputs" / "job-001.json").exists()
    assert not (root / "analyses" / "job-001.json").exists()


def test_save_and_load_job_analysis_uses_analysis_state_directory(tmp_path: Path) -> None:
    root = tmp_path / "state"
    analysis = build_analysis()

    path = save_job_analysis(analysis, root)
    loaded = load_job_analysis(analysis.job_id, root)

    assert path == root / "analyses" / "job-001.json"
    assert loaded == analysis
    assert not (root / "raw_inputs" / "job-001.json").exists()
    assert not (root / "reviewed_jobs" / "job-001.json").exists()


def test_save_and_load_application_outcome_uses_outcomes_state_directory(tmp_path: Path) -> None:
    root = tmp_path / "state"
    outcome = update_outcome(
        create_outcome_record("job-001", updated_at="2026-04-04T20:40:00Z"),
        status="applied",
        updated_at="2026-04-05T09:15:00Z",
        notes="Submitted tailored CV",
    )

    path = save_application_outcome(outcome, root)
    loaded = load_application_outcome(outcome.job_id, root)

    assert path == root / "outcomes" / "job-001.json"
    assert loaded == outcome
    assert not (root / "raw_inputs" / "job-001.json").exists()
    assert not (root / "reviewed_jobs" / "job-001.json").exists()
    assert not (root / "analyses" / "job-001.json").exists()


def test_storage_allows_same_identifier_across_separate_state_layers(tmp_path: Path) -> None:
    root = tmp_path / "state"
    job = build_job()
    analysis = build_analysis(job.job_id)
    outcome = update_outcome(
        create_outcome_record(job.job_id, updated_at="2026-04-04T20:40:00Z"),
        status="applied",
        updated_at="2026-04-05T09:15:00Z",
    )
    raw_payload = {"payload": "Original raw text", "source_type": "copied_text"}

    save_raw_input(raw_payload, job.job_id, root)
    save_reviewed_job(job, root)
    save_job_analysis(analysis, root)
    save_application_outcome(outcome, root)

    assert load_raw_input(job.job_id, root) == raw_payload
    assert load_reviewed_job(job.job_id, root) == job
    assert load_job_analysis(job.job_id, root) == analysis
    assert load_application_outcome(job.job_id, root) == outcome


def test_load_job_analysis_rejects_invalid_nested_payloads(tmp_path: Path) -> None:
    analysis_path = tmp_path / "state" / "analyses" / "job-001.json"
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_path.write_text(
        json.dumps(
            {
                "job_id": "job-001",
                "match_score": 70,
                "score_breakdown": {
                    "skills_score": {"value": 30, "reason": "Good"},
                    "experience_score": {"value": 15, "reason": "Fine"},
                    "location_score": {"value": 10, "reason": "Fine"},
                    "salary_score": {"value": 5, "reason": "Fine"},
                    "domain_score": {"value": 5, "reason": "Fine"},
                    "work_mode_score": {"value": 5, "reason": "Fine"},
                    "notes": ["ok"],
                },
                "blockers": [],
                "strengths": ["analysis"],
                "missing_required_skills": [],
                "missing_preferred_skills": [],
                "risk_flags": ["not-an-object"],
                "decision": "review",
                "decision_reason": "Needs review",
                "confidence": "medium",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(StorageError, match="invalid analysis payload"):
        load_job_analysis("job-001", tmp_path / "state")


def test_job_analysis_from_dict_rejects_missing_job_id() -> None:
    with pytest.raises(StorageError, match="job_id"):
        job_analysis_from_dict({"match_score": 50, "score_breakdown": {}})
