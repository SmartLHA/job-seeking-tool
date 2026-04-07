from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.models import (
    ApplicationOutcome,
    Blocker,
    JobAnalysis,
    JobPosting,
    RiskFlag,
    ScoreBreakdown,
    ScoreComponent,
)
from src.outcomes import outcome_from_dict, outcome_to_dict
from src.reviewed_input import reviewed_job_from_dict, reviewed_job_to_dict


class StorageError(ValueError):
    """Raised when persisted storage content is invalid or incomplete."""


@dataclass(frozen=True, slots=True)
class StorageLayout:
    """Local folder layout for the three explicitly separate persistence states."""

    root: Path
    raw_inputs_dir: Path
    reviewed_jobs_dir: Path
    analyses_dir: Path
    outcomes_dir: Path
    logs_dir: Path


# Storage stays intentionally simple for MVP: local JSON files split by state.
# This preserves auditability and keeps raw input, reviewed job data, and derived
# analysis output from overwriting each other.
def ensure_storage_layout(root: str | Path) -> StorageLayout:
    root_path = Path(root)
    raw_inputs_dir = root_path / "raw_inputs"
    reviewed_jobs_dir = root_path / "reviewed_jobs"
    analyses_dir = root_path / "analyses"
    outcomes_dir = root_path / "outcomes"
    logs_dir = root_path / "logs"

    for directory in (raw_inputs_dir, reviewed_jobs_dir, analyses_dir, outcomes_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    return StorageLayout(
        root=root_path,
        raw_inputs_dir=raw_inputs_dir,
        reviewed_jobs_dir=reviewed_jobs_dir,
        analyses_dir=analyses_dir,
        outcomes_dir=outcomes_dir,
        logs_dir=logs_dir,
    )


def save_raw_input(payload: dict[str, Any], raw_input_id: str, root: str | Path) -> Path:
    """Persist a raw input payload without converting it into reviewed job data."""
    if not isinstance(payload, dict):
        raise StorageError("raw input payload must be an object")

    path = _state_file_path(root, "raw_inputs", raw_input_id)
    _write_json(path, payload)
    return path


def load_raw_input(raw_input_id: str, root: str | Path) -> dict[str, Any]:
    """Load a previously stored raw input payload as-is."""
    path = _state_file_path(root, "raw_inputs", raw_input_id)
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise StorageError("raw input file must contain an object")
    return payload


def save_reviewed_job(job: JobPosting, root: str | Path) -> Path:
    """Persist the reviewed structured job record used for evaluation."""
    path = _state_file_path(root, "reviewed_jobs", job.job_id)
    _write_json(path, reviewed_job_to_dict(job))
    return path


def load_reviewed_job(job_id: str, root: str | Path) -> JobPosting:
    """Load the reviewed structured job record for a specific job id."""
    path = _state_file_path(root, "reviewed_jobs", job_id)
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise StorageError("reviewed job file must contain an object")
    return reviewed_job_from_dict(payload, job_id=job_id)


def save_job_analysis(analysis: JobAnalysis, root: str | Path) -> Path:
    """Persist derived analysis separately from the reviewed structured job."""
    path = _state_file_path(root, "analyses", analysis.job_id)
    _write_json(path, job_analysis_to_dict(analysis))
    return path


def load_job_analysis(job_id: str, root: str | Path) -> JobAnalysis:
    """Load the derived analysis for a reviewed job."""
    path = _state_file_path(root, "analyses", job_id)
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise StorageError("analysis file must contain an object")
    return job_analysis_from_dict(payload, job_id=job_id)


def save_application_outcome(outcome: ApplicationOutcome, root: str | Path) -> Path:
    """Persist local application outcome state separately from job analysis."""
    path = _state_file_path(root, "outcomes", outcome.job_id)
    _write_json(path, outcome_to_dict(outcome))
    return path


def load_application_outcome(job_id: str, root: str | Path) -> ApplicationOutcome:
    """Load the local application outcome state for a specific job id."""
    path = _state_file_path(root, "outcomes", job_id)
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise StorageError("outcome file must contain an object")
    try:
        return outcome_from_dict(payload, job_id=job_id)
    except ValueError as exc:
        raise StorageError(f"invalid outcome payload: {exc}") from exc


def job_analysis_to_dict(analysis: JobAnalysis) -> dict[str, Any]:
    """Convert JobAnalysis into a JSON-friendly mapping."""
    return asdict(analysis)


def job_analysis_from_dict(payload: dict[str, Any], *, job_id: str | None = None) -> JobAnalysis:
    """Validate a stored analysis mapping and rebuild the typed model."""
    if not isinstance(payload, dict):
        raise StorageError("analysis payload must be an object")

    resolved_job_id = job_id or payload.get("job_id")
    if not isinstance(resolved_job_id, str) or not resolved_job_id.strip():
        raise StorageError("analysis payload must include a non-empty job_id")

    score_breakdown_payload = payload.get("score_breakdown")
    if not isinstance(score_breakdown_payload, dict):
        raise StorageError("analysis payload must include score_breakdown as an object")

    try:
        blockers = [_blocker_from_dict(item) for item in payload.get("blockers", [])]
        risk_flags = [_risk_flag_from_dict(item) for item in payload.get("risk_flags", [])]
        return JobAnalysis(
            job_id=resolved_job_id.strip(),
            match_score=_required_number(payload.get("match_score"), "match_score"),
            score_breakdown=_score_breakdown_from_dict(score_breakdown_payload),
            blockers=blockers,
            strengths=_string_list(payload.get("strengths", []), "strengths"),
            missing_required_skills=_string_list(
                payload.get("missing_required_skills", []), "missing_required_skills"
            ),
            missing_preferred_skills=_string_list(
                payload.get("missing_preferred_skills", []), "missing_preferred_skills"
            ),
            risk_flags=risk_flags,
            decision=_required_string(payload.get("decision"), "decision"),
            decision_reason=_required_string(payload.get("decision_reason"), "decision_reason"),
            confidence=_required_string(payload.get("confidence"), "confidence"),
            tailoring_ready=_optional_bool(payload.get("tailoring_ready"), "tailoring_ready"),
            tailoring_notes=_optional_string(payload.get("tailoring_notes"), "tailoring_notes"),
        )
    except (TypeError, ValueError) as exc:
        raise StorageError(f"invalid analysis payload: {exc}") from exc


def _score_breakdown_from_dict(payload: dict[str, Any]) -> ScoreBreakdown:
    return ScoreBreakdown(
        skills_score=_score_component_from_dict(payload.get("skills_score"), "skills_score"),
        experience_score=_score_component_from_dict(
            payload.get("experience_score"), "experience_score"
        ),
        location_score=_score_component_from_dict(payload.get("location_score"), "location_score"),
        salary_score=_score_component_from_dict(payload.get("salary_score"), "salary_score"),
        domain_score=_score_component_from_dict(payload.get("domain_score"), "domain_score"),
        work_mode_score=_score_component_from_dict(
            payload.get("work_mode_score"), "work_mode_score"
        ),
        notes=_string_list(payload.get("notes", []), "score_breakdown.notes"),
    )


def _score_component_from_dict(payload: Any, field_name: str) -> ScoreComponent:
    if not isinstance(payload, dict):
        raise StorageError(f"{field_name} must be an object")
    return ScoreComponent(
        value=_required_number(payload.get("value"), f"{field_name}.value"),
        reason=_required_string(payload.get("reason"), f"{field_name}.reason"),
    )


def _blocker_from_dict(payload: Any) -> Blocker:
    if not isinstance(payload, dict):
        raise StorageError("blockers must contain objects")
    return Blocker(
        code=_required_string(payload.get("code"), "blocker.code"),
        label=_required_string(payload.get("label"), "blocker.label"),
        reason=_required_string(payload.get("reason"), "blocker.reason"),
        severity=_required_string(payload.get("severity"), "blocker.severity"),
    )


def _risk_flag_from_dict(payload: Any) -> RiskFlag:
    if not isinstance(payload, dict):
        raise StorageError("risk_flags must contain objects")
    return RiskFlag(
        code=_required_string(payload.get("code"), "risk_flag.code"),
        label=_required_string(payload.get("label"), "risk_flag.label"),
        reason=_required_string(payload.get("reason"), "risk_flag.reason"),
    )


def _string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise StorageError(f"{field_name} must be a list of strings")

    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise StorageError(f"{field_name} must contain only strings")
        items.append(item)
    return items


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StorageError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StorageError(f"{field_name} must be a string when provided")
    cleaned = value.strip()
    if not cleaned:
        raise StorageError(f"{field_name} must not be empty when provided")
    return cleaned


def _required_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StorageError(f"{field_name} must be numeric")
    return float(value)


def _optional_bool(value: Any, field_name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise StorageError(f"{field_name} must be a boolean when provided")
    return value


def _state_file_path(root: str | Path, state_dir_name: str, record_id: str) -> Path:
    if not isinstance(record_id, str) or not record_id.strip():
        raise StorageError("record id must be a non-empty string")

    layout = ensure_storage_layout(root)
    state_dirs = {
        "raw_inputs": layout.raw_inputs_dir,
        "reviewed_jobs": layout.reviewed_jobs_dir,
        "analyses": layout.analyses_dir,
        "outcomes": layout.outcomes_dir,
        "logs": layout.logs_dir,
    }
    return state_dirs[state_dir_name] / f"{record_id.strip()}.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"stored file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StorageError(f"stored file is not valid JSON: {exc}") from exc
