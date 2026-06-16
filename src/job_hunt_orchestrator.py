from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.job_hunt_evaluation import evaluate_reviewed_job
from src.job_hunt_models import CandidateProfile, JobAnalysis, JobPosting
from src.job_hunt_profile import load_candidate_profile, load_master_cv, resolve_master_cv_path
from src.job_hunt_reporting import build_evaluated_job_report_row, export_report_csv, export_report_json
from src.job_hunt_reviewed_input import reviewed_job_from_dict
from src.job_hunt_storage import (
    ensure_storage_layout,
    save_job_analysis,
    save_raw_input,
    save_reviewed_job,
)
from src.job_sources.dedup import deduplicate_jobs
from src.job_sources.normalize import NormalizedJob, normalize_reed
from src.job_sources.reed_client import fetch_reed_jobs


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


@dataclass(frozen=True, slots=True)
class ReedEvaluationRunResult:
    """Summary of one Reed ingestion and evaluation run."""

    profile: CandidateProfile
    fetched_count: int
    normalized_count: int
    deduped_count: int
    evaluated_jobs: list[LocalEvaluationRunResult]


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


def run_reed_evaluation_flow(
    *,
    profile_path: str | Path,
    keyword: str,
    location: str,
    state_root: str | Path,
    report_dir: str | Path,
    max_results: int = 50,
) -> ReedEvaluationRunResult:
    """Fetch Reed jobs, normalize/deduplicate them, then evaluate each job locally."""
    cleaned_keyword = _required_search_text(keyword, "keyword")
    cleaned_location = _required_search_text(location, "location")
    if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results <= 0:
        raise ValueError("max_results must be a positive integer")

    profile = load_candidate_profile(profile_path)
    raw_jobs = fetch_reed_jobs(cleaned_keyword, cleaned_location, max_results=max_results)
    normalized_jobs = [normalize_reed(raw_job) for raw_job in raw_jobs]
    raw_jobs_by_reviewed_id = _raw_reed_jobs_by_reviewed_id(raw_jobs, normalized_jobs)
    deduped_jobs = deduplicate_jobs(normalized_jobs)

    evaluated_jobs = [
        run_local_evaluation_flow_from_payload(
            profile_path=profile_path,
            reviewed_job_payload=_normalized_reed_job_to_reviewed_payload(job),
            state_root=state_root,
            report_dir=report_dir,
            raw_input_payload=_reed_raw_input_payload(
                job,
                raw_job=raw_jobs_by_reviewed_id.get(_normalized_reed_job_id(job)),
            ),
            raw_input_id=_normalized_reed_job_id(job),
        )
        for job in deduped_jobs
    ]

    return ReedEvaluationRunResult(
        profile=profile,
        fetched_count=len(raw_jobs),
        normalized_count=len(normalized_jobs),
        deduped_count=len(deduped_jobs),
        evaluated_jobs=evaluated_jobs,
    )


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
        "source_quality_score": reviewed_job.source_quality_score,
    }


def _required_search_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a non-empty string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be a non-empty string")
    return cleaned


def _normalized_reed_job_to_reviewed_payload(job: NormalizedJob) -> dict[str, Any]:
    return {
        "job_id": _normalized_reed_job_id(job),
        "job_title": _required_normalized_text(job.get("title"), "title"),
        "company": _optional_normalized_text(job.get("company")) or "Unknown company",
        "description_raw": _optional_normalized_text(job.get("description"))
        or "No description provided by Reed.",
        "source_type": "reed_api",
        "source_ref": _optional_normalized_text(job.get("original_url"))
        or _optional_normalized_text(job.get("apply_url")),
        "location": _optional_normalized_text(job.get("location")),
        "work_mode": _reed_work_mode_from_remote_type(job.get("remote_type")),
        "employment_type": _reed_employment_type(job),
        "required_skills": [],
        "preferred_skills": [],
        "required_years_experience": None,
        "nice_to_have_years_experience": None,
        "domain": None,
        "notes": _reed_notes(job),
        "salary_min_gbp": _optional_salary_int(job.get("salary_min")),
        "salary_max_gbp": _optional_salary_int(job.get("salary_max")),
        "source_quality_score": (job.get("source_quality") or {}).get("quality_score"),
    }


def _normalized_reed_job_id(job: NormalizedJob) -> str:
    external_id = _required_normalized_text(job.get("external_id"), "external_id")
    return f"reed-{external_id}"


def _raw_reed_jobs_by_reviewed_id(
    raw_jobs: list[dict[str, Any]], normalized_jobs: list[NormalizedJob]
) -> dict[str, dict[str, Any]]:
    raw_by_id: dict[str, dict[str, Any]] = {}
    for raw_job, normalized_job in zip(raw_jobs, normalized_jobs, strict=True):
        reviewed_id = _normalized_reed_job_id(normalized_job)
        existing = raw_by_id.get(reviewed_id)
        if existing is None or len(str(raw_job.get("jobDescription", ""))) > len(
            str(existing.get("jobDescription", ""))
        ):
            raw_by_id[reviewed_id] = raw_job
    return raw_by_id


def _reed_raw_input_payload(
    job: NormalizedJob,
    *,
    raw_job: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "source_type": "reed_api",
        "source_ref": job.get("original_url") or job.get("apply_url"),
        "raw_job": raw_job,
        "normalized_job": dict(job),
    }


def _reed_work_mode_from_remote_type(remote_type: object) -> str | None:
    """Map NormalizedJob remote_type to JobPosting work_mode explicitly."""
    if remote_type is None:
        return None
    if not isinstance(remote_type, str):
        raise ValueError("remote_type must be a string when provided")
    mapping = {
        "remote": "remote",
        "hybrid": "hybrid",
        "onsite": "onsite",
        "unknown": None,
    }
    cleaned = remote_type.strip().lower()
    if cleaned not in mapping:
        raise ValueError(f"unsupported Reed remote_type: {remote_type}")
    return mapping[cleaned]


def _reed_employment_type(job: NormalizedJob) -> str | None:
    job_type = _optional_normalized_text(job.get("job_type"))
    contract_type = _optional_normalized_text(job.get("contract_type"))
    if job_type in {"full_time", "part_time"} and contract_type and contract_type != "unknown":
        return f"{job_type.replace('_', '-')}, {contract_type}"
    if job_type in {"full_time", "part_time"}:
        return job_type.replace("_", "-")
    if contract_type and contract_type != "unknown":
        return contract_type
    return None


def _reed_notes(job: NormalizedJob) -> str | None:
    quality = job.get("source_quality") or {}
    score = quality.get("quality_score") if isinstance(quality, dict) else None
    if score is None:
        return None
    return f"Reed source quality score: {score}"


def _optional_salary_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("salary values must be numeric when provided")
    if value < 0:
        raise ValueError("salary values must be non-negative when provided")
    return int(value)


def _required_normalized_text(value: object, field_name: str) -> str:
    cleaned = _optional_normalized_text(value)
    if cleaned is None:
        raise ValueError(f"normalized Reed job must include non-empty {field_name}")
    return cleaned


def _optional_normalized_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("normalized Reed text fields must be strings when provided")
    cleaned = value.strip()
    return cleaned or None


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
