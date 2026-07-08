from __future__ import annotations

from functools import partial
from typing import Any

from src.job_hunt_models import JobPosting
from src import job_hunt_validation as _v


class ReviewedInputValidationError(ValueError):
    """Raised when reviewed job input is structurally invalid."""


# This module is intentionally narrow: it turns already-reviewed user input into
# the structured job record that later scoring will consume. It does not fetch,
# crawl, or broadly parse sources. Raw input should remain stored separately.
REQUIRED_TEXT_FIELDS = (
    "job_title",
    "company",
    "description_raw",
    "source_type",
)

OPTIONAL_REVIEWED_JOB_FIELDS = {
    "job_title",
    "company",
    "description_raw",
    "source_type",
    "source_ref",
    "location",
    "work_mode",
    "employment_type",
    "required_skills",
    "preferred_skills",
    "required_years_experience",
    "nice_to_have_years_experience",
    "domain",
    "notes",
    "salary_min_gbp",
    "salary_max_gbp",
    "source_quality_score",
    "url",
    "source_job_id",
}


def reviewed_job_from_dict(
    payload: dict[str, Any],
    *,
    job_id: str | None = None,
) -> JobPosting:
    """Validate a reviewed job mapping and convert it into a JobPosting."""
    if not isinstance(payload, dict):
        raise ReviewedInputValidationError("reviewed job payload must be an object")

    unknown_fields = sorted(set(payload) - OPTIONAL_REVIEWED_JOB_FIELDS - {"job_id"})
    if unknown_fields:
        raise ReviewedInputValidationError(
            f"reviewed job contains unknown fields: {', '.join(unknown_fields)}"
        )

    resolved_job_id = job_id or payload.get("job_id")
    if not isinstance(resolved_job_id, str) or not resolved_job_id.strip():
        raise ReviewedInputValidationError("reviewed job must include a non-empty job_id")

    normalised_required: dict[str, str] = {}
    for field_name in REQUIRED_TEXT_FIELDS:
        normalised_required[field_name] = _required_string(payload.get(field_name), field_name)

    return JobPosting(
        job_id=resolved_job_id.strip(),
        job_title=normalised_required["job_title"],
        company=normalised_required["company"],
        description_raw=normalised_required["description_raw"],
        source_type=normalised_required["source_type"],
        source_ref=_optional_string(payload.get("source_ref"), "source_ref", empty_as_none=True),
        url=_optional_string(payload.get("url"), "url", empty_as_none=True),
        location=_optional_string(payload.get("location"), "location", empty_as_none=True),
        work_mode=_optional_string(payload.get("work_mode"), "work_mode", empty_as_none=True),
        employment_type=_optional_string(
            payload.get("employment_type"), "employment_type", empty_as_none=True
        ),
        required_skills=_normalise_string_list(
            payload.get("required_skills", []), "required_skills"
        ),
        preferred_skills=_normalise_string_list(
            payload.get("preferred_skills", []), "preferred_skills"
        ),
        required_years_experience=_optional_non_negative_float(
            payload.get("required_years_experience"), "required_years_experience"
        ),
        nice_to_have_years_experience=_optional_non_negative_float(
            payload.get("nice_to_have_years_experience"), "nice_to_have_years_experience"
        ),
        domain=_optional_string(payload.get("domain"), "domain", empty_as_none=True),
        notes=_optional_string(payload.get("notes"), "notes", empty_as_none=True),
        salary_min_gbp=_optional_non_negative_int(payload.get("salary_min_gbp"), "salary_min_gbp"),
        salary_max_gbp=_optional_non_negative_int(payload.get("salary_max_gbp"), "salary_max_gbp"),
        source_quality_score=_optional_non_negative_int(payload.get("source_quality_score"), "source_quality_score"),
        source_job_id=_optional_string(payload.get("source_job_id"), "source_job_id", empty_as_none=True),
    )


def reviewed_job_to_dict(job: JobPosting) -> dict[str, Any]:
    """Return a JSON-friendly mapping for the reviewed structured job record."""
    return {
        "job_id": job.job_id,
        "job_title": job.job_title,
        "company": job.company,
        "description_raw": job.description_raw,
        "source_type": job.source_type,
        "source_ref": job.source_ref,
        "url": job.url,
        "location": job.location,
        "work_mode": job.work_mode,
        "employment_type": job.employment_type,
        "required_skills": job.required_skills,
        "preferred_skills": job.preferred_skills,
        "required_years_experience": job.required_years_experience,
        "nice_to_have_years_experience": job.nice_to_have_years_experience,
        "domain": job.domain,
        "notes": job.notes,
        "salary_min_gbp": job.salary_min_gbp,
        "salary_max_gbp": job.salary_max_gbp,
        "source_quality_score": job.source_quality_score,
        "source_job_id": job.source_job_id,
    }


_required_string = partial(_v.required_string, error=ReviewedInputValidationError)


_optional_string = partial(_v.optional_string, error=ReviewedInputValidationError)


_normalise_string_list = partial(_v.string_list, strip=True, dedup=True, allow_empty_items=False, error=ReviewedInputValidationError)


_optional_non_negative_float = partial(_v.optional_non_negative_float, error=ReviewedInputValidationError)


_optional_non_negative_int = partial(_v.optional_int, non_negative=True, error=ReviewedInputValidationError)
