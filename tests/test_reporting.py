from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.job_hunt_models import Blocker, JobAnalysis, JobPosting, RiskFlag, ScoreBreakdown, ScoreComponent
from src.job_hunt_outcomes import create_outcome_record, update_outcome
from src.job_hunt_reporting import (
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


def test_report_row_includes_engine_decision_and_user_decision_columns() -> None:
    """Report rows must export both engine_decision and user_decision."""
    import dataclasses
    analysis = dataclasses.replace(build_analysis(), user_decision="skip", user_decision_note="Changed mind")
    row = build_evaluated_job_report_row(build_job(), analysis)
    assert row.engine_decision == "apply"
    assert row.user_decision == "skip"

    flat = report_row_to_flat_dict(row)
    assert flat["engine_decision"] == "apply"
    assert flat["user_decision"] == "skip"


def test_report_row_user_decision_none_when_not_overridden() -> None:
    row = build_evaluated_job_report_row(build_job(), build_analysis())
    assert row.engine_decision == "apply"
    assert row.user_decision is None

    flat = report_row_to_flat_dict(row)
    assert flat["engine_decision"] == "apply"
    assert flat["user_decision"] is None


_CSV_TEXT_FIELDS = (
    "job_id", "job_title", "company", "location", "work_mode", "employment_type",
    "source_type", "source_ref", "confidence", "decision", "decision_reason",
    "engine_decision", "user_decision", "outcome_status", "outcome_updated_at", "outcome_notes",
)
_CSV_LIST_FIELDS = (
    "blockers", "risk_flags", "strengths", "missing_required_skills", "missing_preferred_skills",
)


def _read_csv_row(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return next(csv.DictReader(stream))


@pytest.mark.parametrize("operator", ["=", "+", "-", "@"])
@pytest.mark.parametrize("prefix", ["", " ", "\t", "\r\n", "\x00", "\x1f", "\x7f", "\x85", "\xa0", "\ufeff", "\u200b", " \t\x00\ufeff"])
def test_csv_formula_strings_are_escaped_in_every_text_column(tmp_path, operator, prefix):
    from dataclasses import asdict, replace
    value = prefix + operator + 'SUM(1,2),"quoted"\n中文'
    row = build_evaluated_job_report_row(build_job(), build_analysis(), build_outcome())
    changes = {name: value for name in _CSV_TEXT_FIELDS}
    changes.update({name: [value, "second"] for name in _CSV_LIST_FIELDS})
    row = replace(row, **changes, match_score=-12.5, tailoring_ready=False)
    before = asdict(row)
    flat_before = report_row_to_flat_dict(row)
    exported = _read_csv_row(export_report_csv([row], tmp_path / "safe.csv"))
    for field in _CSV_TEXT_FIELDS:
        assert exported[field] == "'" + value
    for field in _CSV_LIST_FIELDS:
        assert exported[field] == "'" + value + "; second"
    assert exported["match_score"] == "-12.5"
    assert exported["tailoring_ready"] == "False"
    assert asdict(row) == before and report_row_to_flat_dict(row) == flat_before
    payload = json.loads(export_report_json([row], tmp_path / "original.json").read_text())
    assert payload["rows"][0] == before


@pytest.mark.parametrize("text", ["", "normal", "中文", 'Title, "quoted"\nnext line',
    " normal\ttext", "\x00benign", "\t\r\n", "\ufeff中文", "'already literal", "text =1"])
def test_csv_benign_text_is_preserved_exactly(tmp_path, text):
    from dataclasses import replace
    row = replace(build_evaluated_job_report_row(build_job(), build_analysis()),
                  job_title=text, company=text, outcome_notes=text)
    exported = _read_csv_row(export_report_csv([row], tmp_path / "benign.csv"))
    assert exported["job_title"] == exported["company"] == exported["outcome_notes"] == text


@pytest.mark.parametrize("number,flag", [(0, True), (-12.5, False), (82.5, None)])
def test_csv_numeric_bool_and_missing_values_stay_scalar(tmp_path, number, flag):
    from dataclasses import replace
    row = replace(build_evaluated_job_report_row(build_job(), build_analysis()),
                  match_score=number, tailoring_ready=flag)
    flat = report_row_to_flat_dict(row)
    assert flat["match_score"] == number and flat["tailoring_ready"] is flag
    exported = _read_csv_row(export_report_csv([row], tmp_path / "scalar.csv"))
    assert exported["match_score"] == str(number)
    assert exported["tailoring_ready"] == ("" if flag is None else str(flag))
    assert exported["user_decision"] == exported["outcome_notes"] == ""
