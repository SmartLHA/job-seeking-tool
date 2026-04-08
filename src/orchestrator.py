from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.evaluation import evaluate_reviewed_job
from src.models import CandidateProfile, JobAnalysis, JobPosting
from src.profile import load_candidate_profile, load_master_cv, resolve_master_cv_path
from src.reporting import build_evaluated_job_report_row, export_report_csv, export_report_json
from src.reviewed_input import reviewed_job_from_dict
from src.storage import (
    ensure_storage_layout,
    save_job_analysis,
    save_raw_input,
    save_reviewed_job,
)


@dataclass(frozen=True, slots=True)
class LocalEvaluationRunResult:
    """Summary of one lightweight local evaluation run."""

    profile: CandidateProfile
    reviewed_job: JobPosting
    analysis: JobAnalysis
    storage_root: Path
    reviewed_job_path: Path
    analysis_path: Path
    raw_input_path: Path | None
    report_json_path: Path
    report_csv_path: Path
    master_cv_path: Path | None


# This composition layer intentionally stays thin. It wires together the
# existing modules for one local reviewed-job flow without hiding their module
# boundaries or turning MVP into a larger app framework.
def run_local_evaluation_flow(
    *,
    profile_path: str | Path,
    reviewed_job_path: str | Path,
    state_root: str | Path,
    report_dir: str | Path,
    raw_input_path: str | Path | None = None,
    raw_input_id: str | None = None,
) -> LocalEvaluationRunResult:
    reviewed_job = _load_reviewed_job_payload(reviewed_job_path)
    raw_input_payload = _load_optional_raw_input_payload(raw_input_path)
    return run_local_evaluation_flow_from_payload(
        profile_path=profile_path,
        reviewed_job_payload=_job_posting_to_payload(reviewed_job),
        state_root=state_root,
        report_dir=report_dir,
        raw_input_payload=raw_input_payload,
        raw_input_id=raw_input_id or reviewed_job.job_id,
    )


# This variant exists so the minimal local UI can stay a thin shell over the
# same orchestration path the CLI already uses, without writing temporary input
# files just to re-enter reviewed data through the browser.
def run_local_evaluation_flow_from_payload(
    *,
    profile_path: str | Path,
    reviewed_job_payload: dict[str, Any],
    state_root: str | Path,
    report_dir: str | Path,
    raw_input_payload: dict[str, Any] | None = None,
    raw_input_id: str | None = None,
) -> LocalEvaluationRunResult:
    if not isinstance(reviewed_job_payload, dict):
        raise ValueError("reviewed job payload must be a JSON object")
    if raw_input_payload is not None and not isinstance(raw_input_payload, dict):
        raise ValueError("raw input payload must be a JSON object")

    profile = load_candidate_profile(profile_path)
    master_cv_path = _load_master_cv_if_configured(profile, profile_path)
    reviewed_job = reviewed_job_from_dict(reviewed_job_payload)

    layout = ensure_storage_layout(state_root)
    stored_raw_input_path = None
    if raw_input_payload is not None:
        stored_raw_input_path = save_raw_input(
            raw_input_payload,
            raw_input_id or reviewed_job.job_id,
            layout.root,
        )

    stored_reviewed_job_path = save_reviewed_job(reviewed_job, layout.root)
    analysis = evaluate_reviewed_job(profile, reviewed_job)
    stored_analysis_path = save_job_analysis(analysis, layout.root)

    report_row = build_evaluated_job_report_row(reviewed_job, analysis)
    report_root = Path(report_dir)
    report_root.mkdir(parents=True, exist_ok=True)
    report_json_path = export_report_json([report_row], report_root / f"{reviewed_job.job_id}.json")
    report_csv_path = export_report_csv([report_row], report_root / f"{reviewed_job.job_id}.csv")

    result = LocalEvaluationRunResult(
        profile=profile,
        reviewed_job=reviewed_job,
        analysis=analysis,
        storage_root=layout.root,
        reviewed_job_path=stored_reviewed_job_path,
        analysis_path=stored_analysis_path,
        raw_input_path=stored_raw_input_path,
        report_json_path=report_json_path,
        report_csv_path=report_csv_path,
        master_cv_path=master_cv_path,
    )
    _log_run(result)
    return result


def _log_run(result: LocalEvaluationRunResult) -> None:
    """Write a timestamped run log to logs/ directory."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    layout = ensure_storage_layout(result.storage_root)
    log_file = layout.logs_dir / f"{ts}_{result.reviewed_job.job_id}.log"
    lines = [
        f"timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"job_id: {result.reviewed_job.job_id}",
        f"decision: {result.analysis.decision}",
        f"match_score: {result.analysis.match_score}",
        f"confidence: {result.analysis.confidence}",
        f"profile_id: {result.profile.candidate_id}",
        f"job_title: {result.reviewed_job.job_title}",
        f"company: {result.reviewed_job.company}",
        f"source_type: {result.reviewed_job.source_type}",
        f"input_reviewed_job: {result.reviewed_job_path}",
        f"output_analysis: {result.analysis_path}",
        f"output_reports: {result.report_json_path}, {result.report_csv_path}",
        f"master_cv: {result.master_cv_path or 'none'}",
        f"storage_root: {result.storage_root}",
    ]
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_reviewed_job_payload(path: str | Path) -> JobPosting:
    payload_path = Path(path)
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"reviewed job file not found: {payload_path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"reviewed job file is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("reviewed job file must contain a JSON object")
    return reviewed_job_from_dict(payload)


def _load_optional_raw_input_payload(raw_input_path: str | Path | None) -> dict[str, Any] | None:
    if raw_input_path is None:
        return None

    payload_path = Path(raw_input_path)
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"raw input file not found: {payload_path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"raw input file is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("raw input file must contain a JSON object")
    return payload


def _job_posting_to_payload(reviewed_job: JobPosting) -> dict[str, Any]:
    return {
        "job_id": reviewed_job.job_id,
        "job_title": reviewed_job.job_title,
        "company": reviewed_job.company,
        "description_raw": reviewed_job.description_raw,
        "source_type": reviewed_job.source_type,
        "source_ref": reviewed_job.source_ref,
        "location": reviewed_job.location,
        "work_mode": reviewed_job.work_mode,
        "employment_type": reviewed_job.employment_type,
        "required_skills": list(reviewed_job.required_skills),
        "preferred_skills": list(reviewed_job.preferred_skills),
        "required_years_experience": reviewed_job.required_years_experience,
        "nice_to_have_years_experience": reviewed_job.nice_to_have_years_experience,
        "domain": reviewed_job.domain,
        "notes": reviewed_job.notes,
        "salary_min_gbp": reviewed_job.salary_min_gbp,
        "salary_max_gbp": reviewed_job.salary_max_gbp,
    }

def _load_master_cv_if_configured(
    profile: CandidateProfile,
    profile_path: str | Path,
) -> Path | None:
    if not profile.master_cv_ref:
        return None

    # The CLI flow does not tailor yet, but validating the configured master CV
    # keeps the approved truth source wiring visible and catches bad local setup.
    resolved_path = resolve_master_cv_path(profile, profile_path)
    load_master_cv(resolved_path)
    return resolved_path
