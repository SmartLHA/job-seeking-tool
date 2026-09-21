"""Feature C: export one job's application package as an in-memory zip.

Stdlib only. The zip holds FIXED entry names (README.txt, cv.md, cover_letter.txt,
analysis.md, job.json). A missing part gives a partial bundle listed in the
manifest, never an error; only a missing/invalid job raises.

Never included: .env, raw_inputs, profile personal fields, other jobs.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.job_hunt_config import DEFAULT_TAILORING_POLICY, TailoringPolicy
from src.job_hunt_cover_letter import load_cover_letter
from src.job_hunt_qualitative import derive_grade
from src.job_hunt_storage import (
    StorageError,
    load_job_analysis,
    load_qualitative_assessment,
    load_reviewed_job,
)
from src.job_hunt_tailoring import EmptyTailoredCVError, load_latest_tailored_cv

_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_JOB_ID_LEN = 128
ENTRY_README = "README.txt"
ENTRY_CV = "cv.md"
ENTRY_COVER = "cover_letter.txt"
ENTRY_ANALYSIS = "analysis.md"
ENTRY_JOB = "job.json"
_PART_ENTRIES = (ENTRY_CV, ENTRY_COVER, ENTRY_ANALYSIS, ENTRY_JOB)
_LOAD_ERRORS = (FileNotFoundError, StorageError, ValueError, KeyError, TypeError)


def validate_job_id(job_id: Any) -> str:
    """Return job_id if it is safe to use for file access, else raise ValueError."""
    if (
        not isinstance(job_id, str)
        or not job_id
        or len(job_id) > MAX_JOB_ID_LEN
        or not _SAFE_JOB_ID.match(job_id)
        or job_id in (".", "..")
    ):
        raise ValueError("invalid job_id")
    return job_id


def package_filename(job_id: str) -> str:
    """Download filename from a VALIDATED job id only (never from title/company)."""
    return f"application-package-{validate_job_id(job_id)}.zip"


def _md(value: Any) -> str:
    """Single-line markdown-safe text: collapse whitespace, escape markdown syntax."""
    text = " ".join(str(value if value is not None else "").split())
    text = re.sub(r"([\\`*_\[\]<>|#])", r"\\\1", text)
    return text


def _bullets(items: list[str]) -> list[str]:
    return [f"- {_md(i)}" for i in items] or ["- None"]


def render_analysis_md(job: Any, analysis: Any, assessment: dict | None) -> str:
    decision = analysis.user_decision or analysis.decision
    grade = derive_grade(
        analysis.match_score,
        assessment,
        effective_decision=decision,
        has_blockers=bool(analysis.blockers),
        confidence=analysis.confidence,
        decision_reason=analysis.decision_reason,
    )
    missing_req = {s.strip().lower() for s in analysis.missing_required_skills}
    matched = [s for s in job.required_skills if s.strip().lower() not in missing_req]
    lines = [
        f"# Analysis: {_md(job.job_title)} at {_md(job.company)}",
        "",
        f"- Decision: {_md(decision)}",
        f"- Match score: {analysis.match_score:.1f}",
        f"- Grade: {_md(grade['display_grade'])}"
        + (f" (base {_md(grade['base_grade'])}, capped: {_md(grade['cap_reason'])})" if grade["is_capped"] else ""),
        f"- Confidence: {_md(analysis.confidence)}",
    ]
    if analysis.decision_reason:
        lines.append(f"- Reason: {_md(analysis.decision_reason)}")
    lines += ["", "## Matched required skills", *_bullets(matched)]
    lines += ["", "## Missing required skills", *_bullets(analysis.missing_required_skills)]
    lines += ["", "## Blockers"]
    lines += [f"- {_md(b.label)} ({_md(b.severity)}): {_md(b.reason)}" for b in analysis.blockers] or ["- None"]
    lines += ["", "## Risk flags"]
    lines += [f"- {_md(r.label)}: {_md(r.reason)}" for r in analysis.risk_flags] or ["- None"]
    if isinstance(assessment, dict):
        lines += ["", "## Qualitative assessment (AI, advisory)"]
        dims = assessment.get("dimensions")
        for key, dim in (dims.items() if isinstance(dims, dict) else []):
            if not isinstance(dim, dict):
                continue
            score = dim.get("score")
            detail = _md(dim.get("reasoning") or dim.get("warning") or "")
            lines.append(f"- {_md(key)}: {_md(score if score is not None else dim.get('tier', 'n/a'))} - {detail}")
        pq = assessment.get("posting_quality")
        if isinstance(pq, dict) and pq.get("signals"):
            lines.append("- Posting quality signals: " + "; ".join(_md(s) for s in pq["signals"]))
    return "\n".join(lines) + "\n"


def _job_json(job: Any) -> str:
    source_ref = job.source_ref if isinstance(job.source_ref, str) and job.source_ref.startswith(("http://", "https://")) else None
    payload = {
        "job_id": job.job_id,
        "title": job.job_title,
        "company": job.company,
        "location": job.location,
        "work_mode": job.work_mode,
        "employment_type": job.employment_type,
        "salary_min_gbp": job.salary_min_gbp,
        "salary_max_gbp": job.salary_max_gbp,
        "source_url": job.url or source_ref,
        "required_skills": list(job.required_skills),
        "preferred_skills": list(job.preferred_skills),
        "description": job.description_raw,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _readme(manifest: dict) -> str:
    lines = [
        "Application package",
        f"Job: {manifest['title']} at {manifest['company']}",
        f"Job id: {manifest['job_id']}",
        f"Generated: {manifest['generated']}",
        "",
        "Included:",
        *[f"  {n}" for n in manifest["included"]],
    ]
    if manifest["missing"]:
        lines += ["", "Missing:", *[f"  {n}: {why}" for n, why in manifest["missing"].items()]]
    return "\n".join(lines) + "\n"


def build_package(
    job_id: str,
    profile: Any | None,
    *,
    state_root: str | Path,
    policy: TailoringPolicy = DEFAULT_TAILORING_POLICY,
    cover_letter_base: str | Path | None = None,
    now: datetime | None = None,
) -> tuple[bytes, dict]:
    """Build the zip for one job. Returns (zip_bytes, manifest).

    Raises ValueError for an invalid job id (before ANY file access) and
    FileNotFoundError/StorageError if the job itself does not exist or is unreadable.
    Every other part that is absent is recorded in ``manifest["missing"]``.
    """
    validate_job_id(job_id)
    job = load_reviewed_job(job_id, state_root)
    parts: dict[str, str] = {ENTRY_JOB: _job_json(job)}
    missing: dict[str, str] = {}

    profile_id = getattr(profile, "candidate_id", None)
    if not profile_id:
        missing[ENTRY_CV] = "no profile available to match the CV against"
    else:
        try:
            cv = load_latest_tailored_cv(job_id, expected_profile_id=profile_id, policy=policy)
        except EmptyTailoredCVError:
            cv, why = None, "saved CV is empty"
        except ValueError:
            cv, why = None, "invalid job id for CV"
        else:
            why = "not generated yet, or generated for a different profile"
        if cv:
            parts[ENTRY_CV] = cv + "\n"
        else:
            missing[ENTRY_CV] = why

    letter = load_cover_letter(job_id, cover_letter_base)
    if letter and letter.strip():
        parts[ENTRY_COVER] = letter if letter.endswith("\n") else letter + "\n"
    else:
        missing[ENTRY_COVER] = "not generated yet"

    try:
        analysis = load_job_analysis(job_id, state_root)
    except _LOAD_ERRORS:
        analysis = None
        missing[ENTRY_ANALYSIS] = "job has not been evaluated yet"
    if analysis is not None:
        try:
            assessment = load_qualitative_assessment(job_id, state_root)
        except _LOAD_ERRORS:
            assessment = None
        parts[ENTRY_ANALYSIS] = render_analysis_md(job, analysis, assessment)

    generated = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    included = [n for n in _PART_ENTRIES if n in parts]
    manifest = {
        "job_id": job_id,
        "title": job.job_title,
        "company": job.company,
        "generated": generated,
        "included": [ENTRY_README, *included],
        "missing": {n: missing[n] for n in _PART_ENTRIES if n in missing},
    }
    parts_out = {ENTRY_README: _readme(manifest), **{n: parts[n] for n in included}}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in parts_out.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            zf.writestr(info, text.encode("utf-8"))
    return buf.getvalue(), manifest
