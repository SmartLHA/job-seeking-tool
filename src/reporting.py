from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from src.models import ApplicationOutcome, JobAnalysis, JobPosting


class ReportingError(ValueError):
    """Raised when report/export input is incomplete or inconsistent."""


# Reporting stays intentionally lightweight for MVP.
# These helpers flatten already-reviewed job data plus derived analysis and
# optional outcomes into simple local exports that are easy to inspect in a
# spreadsheet or plain JSON file.
@dataclass(frozen=True, slots=True)
class EvaluatedJobReportRow:
    job_id: str
    job_title: str
    company: str
    location: str | None
    work_mode: str | None
    employment_type: str | None
    source_type: str
    source_ref: str | None
    match_score: float
    confidence: str
    decision: str
    decision_reason: str
    blockers: list[str]
    risk_flags: list[str]
    strengths: list[str]
    missing_required_skills: list[str]
    missing_preferred_skills: list[str]
    outcome_status: str | None
    outcome_updated_at: str | None
    outcome_notes: str | None
    tailoring_ready: bool | None


@dataclass(frozen=True, slots=True)
class ReportSummary:
    total_jobs: int
    decision_counts: dict[str, int]
    outcome_counts: dict[str, int]


def build_evaluated_job_report_row(
    job: JobPosting,
    analysis: JobAnalysis,
    outcome: ApplicationOutcome | None = None,
) -> EvaluatedJobReportRow:
    """Flatten reviewed job, analysis, and optional outcome into one export row."""
    if job.job_id != analysis.job_id:
        raise ReportingError("job and analysis must refer to the same job_id")
    if outcome is not None and outcome.job_id != job.job_id:
        raise ReportingError("outcome must refer to the same job_id as the job")

    return EvaluatedJobReportRow(
        job_id=job.job_id,
        job_title=job.job_title,
        company=job.company,
        location=job.location,
        work_mode=job.work_mode,
        employment_type=job.employment_type,
        source_type=job.source_type,
        source_ref=job.source_ref,
        match_score=analysis.match_score,
        confidence=analysis.confidence,
        decision=analysis.decision,
        decision_reason=analysis.decision_reason,
        blockers=[blocker.label for blocker in analysis.blockers],
        risk_flags=[risk.label for risk in analysis.risk_flags],
        strengths=list(analysis.strengths),
        missing_required_skills=list(analysis.missing_required_skills),
        missing_preferred_skills=list(analysis.missing_preferred_skills),
        outcome_status=outcome.status if outcome is not None else None,
        outcome_updated_at=outcome.updated_at if outcome is not None else None,
        outcome_notes=outcome.notes if outcome is not None else None,
        tailoring_ready=analysis.tailoring_ready,
    )


def summarise_report_rows(rows: Iterable[EvaluatedJobReportRow]) -> ReportSummary:
    """Build small deterministic counts for export metadata and local inspection."""
    materialised_rows = list(rows)
    decision_counts: dict[str, int] = {}
    outcome_counts: dict[str, int] = {}

    for row in materialised_rows:
        decision_counts[row.decision] = decision_counts.get(row.decision, 0) + 1
        if row.outcome_status is not None:
            outcome_counts[row.outcome_status] = outcome_counts.get(row.outcome_status, 0) + 1

    return ReportSummary(
        total_jobs=len(materialised_rows),
        decision_counts=decision_counts,
        outcome_counts=outcome_counts,
    )


def export_report_json(rows: Iterable[EvaluatedJobReportRow], destination: str | Path) -> Path:
    """Write a local JSON export containing summary metadata and flattened rows."""
    materialised_rows = list(rows)
    payload = {
        "generated_at": _timestamp_now(),
        "summary": asdict(summarise_report_rows(materialised_rows)),
        "rows": [report_row_to_dict(row) for row in materialised_rows],
    }
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def export_report_csv(rows: Iterable[EvaluatedJobReportRow], destination: str | Path) -> Path:
    """Write a spreadsheet-friendly CSV export for evaluated jobs and outcomes."""
    materialised_rows = list(rows)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(report_row_to_flat_dict(_empty_report_row()).keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in materialised_rows:
            writer.writerow(report_row_to_flat_dict(row))
    return path


def report_row_to_dict(row: EvaluatedJobReportRow) -> dict[str, Any]:
    """Convert a report row into a structured JSON-friendly mapping."""
    return asdict(row)


def report_row_to_flat_dict(row: EvaluatedJobReportRow) -> dict[str, Any]:
    """Convert a report row into CSV-safe scalar values."""
    return {
        "job_id": row.job_id,
        "job_title": row.job_title,
        "company": row.company,
        "location": row.location,
        "work_mode": row.work_mode,
        "employment_type": row.employment_type,
        "source_type": row.source_type,
        "source_ref": row.source_ref,
        "match_score": row.match_score,
        "confidence": row.confidence,
        "decision": row.decision,
        "decision_reason": row.decision_reason,
        "blockers": "; ".join(row.blockers),
        "risk_flags": "; ".join(row.risk_flags),
        "strengths": "; ".join(row.strengths),
        "missing_required_skills": "; ".join(row.missing_required_skills),
        "missing_preferred_skills": "; ".join(row.missing_preferred_skills),
        "outcome_status": row.outcome_status,
        "outcome_updated_at": row.outcome_updated_at,
        "outcome_notes": row.outcome_notes,
        "tailoring_ready": row.tailoring_ready,
    }


def _timestamp_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _empty_report_row() -> EvaluatedJobReportRow:
    return EvaluatedJobReportRow(
        job_id="",
        job_title="",
        company="",
        location=None,
        work_mode=None,
        employment_type=None,
        source_type="",
        source_ref=None,
        match_score=0.0,
        confidence="",
        decision="",
        decision_reason="",
        blockers=[],
        risk_flags=[],
        strengths=[],
        missing_required_skills=[],
        missing_preferred_skills=[],
        outcome_status=None,
        outcome_updated_at=None,
        outcome_notes=None,
        tailoring_ready=None,
    )
