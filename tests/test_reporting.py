from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.models import Blocker, JobAnalysis, JobPosting, RiskFlag, ScoreBreakdown, ScoreComponent
from src.outcomes import create_outcome_record, update_outcome
from src.reporting import (
    ReportingError,
    build_evaluated_job_report_row,
    export_report_csv,
    export_report_json,
    report_row_to_flat_dict,
    summarise_report_rows,
)


def build_job(job_id: str = "job-001", *, title: str = "Business Analyst") -> JobPosting:
    return JobPosting(
        job_id=job_id,
        job_title=title,
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


def build_analysis(job_id: str = "job-001", *, decision: str = "apply") -> JobAnalysis:
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
        decision=decision,
        decision_reason="Strong fit with no critical blockers.",
        confidence="medium",
        tailoring_ready=decision == "apply",
        tailoring_notes="Safe to tailor from approved truth sources.",
    )


def build_outcome(job_id: str = "job-001"):
    return update_outcome(
        create_outcome_record(job_id, updated_at="2026-04-04T20:40:00Z"),
        status="applied",
        updated_at="2026-04-05T09:15:00Z",
        notes="Submitted tailored CV",
    )


def test_build_evaluated_job_report_row_flattens_core_fields() -> None:
    row = build_evaluated_job_report_row(build_job(), build_analysis(), build_outcome())

    assert row.job_id == "job-001"
    assert row.decision == "apply"
    assert row.blockers == ["Salary floor check"]
    assert row.risk_flags == ["Preferred skill gap"]
    assert row.outcome_status == "applied"
    assert row.outcome_notes == "Submitted tailored CV"


def test_build_evaluated_job_report_row_rejects_mismatched_ids() -> None:
    with pytest.raises(ReportingError, match="same job_id"):
        build_evaluated_job_report_row(build_job("job-001"), build_analysis("job-999"))


def test_summarise_report_rows_counts_decisions_and_outcomes() -> None:
    rows = [
        build_evaluated_job_report_row(build_job("job-001"), build_analysis("job-001", decision="apply"), build_outcome("job-001")),
        build_evaluated_job_report_row(build_job("job-002", title="Data Analyst"), build_analysis("job-002", decision="review")),
    ]

    summary = summarise_report_rows(rows)

    assert summary.total_jobs == 2
    assert summary.decision_counts == {"apply": 1, "review": 1}
    assert summary.outcome_counts == {"applied": 1}


def test_report_row_to_flat_dict_joins_list_fields_for_csv() -> None:
    row = build_evaluated_job_report_row(build_job(), build_analysis(), build_outcome())

    flat = report_row_to_flat_dict(row)

    assert flat["blockers"] == "Salary floor check"
    assert flat["risk_flags"] == "Preferred skill gap"
    assert flat["strengths"] == "stakeholder management; process mapping"
    assert flat["missing_preferred_skills"] == "SQL"


def test_export_report_json_writes_summary_and_rows(tmp_path: Path) -> None:
    destination = tmp_path / "reports" / "jobs-report.json"
    rows = [build_evaluated_job_report_row(build_job(), build_analysis(), build_outcome())]

    path = export_report_json(rows, destination)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path == destination
    assert payload["summary"]["total_jobs"] == 1
    assert payload["summary"]["decision_counts"] == {"apply": 1}
    assert payload["summary"]["outcome_counts"] == {"applied": 1}
    assert payload["rows"][0]["job_id"] == "job-001"
    assert payload["rows"][0]["blockers"] == ["Salary floor check"]


def test_export_report_csv_writes_flat_rows(tmp_path: Path) -> None:
    destination = tmp_path / "reports" / "jobs-report.csv"
    rows = [build_evaluated_job_report_row(build_job(), build_analysis(), build_outcome())]

    path = export_report_csv(rows, destination)

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        exported_rows = list(reader)

    assert path == destination
    assert len(exported_rows) == 1
    assert exported_rows[0]["job_id"] == "job-001"
    assert exported_rows[0]["decision"] == "apply"
    assert exported_rows[0]["blockers"] == "Salary floor check"
    assert exported_rows[0]["strengths"] == "stakeholder management; process mapping"
    assert exported_rows[0]["outcome_status"] == "applied"
