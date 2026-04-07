from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models import CandidateProfile


class ProfileValidationError(ValueError):
    """Raised when profile or CV input is structurally invalid."""


# The candidate profile is one of the two approved truth sources for MVP.
# Keep this module focused on loading and validating that source-of-truth data,
# not on any scoring or decision logic.
REQUIRED_PROFILE_LIST_FIELDS = (
    "target_roles",
    "locations",
    "skills",
    "industries",
    "achievements",
    "certifications",
)

OPTIONAL_PROFILE_FIELDS = {
    "name",
    "target_roles",
    "locations",
    "remote_preference",
    "salary_floor_gbp",
    "right_to_work_uk",
    "skills",
    "years_experience",
    "industries",
    "achievements",
    "certifications",
    "master_cv_ref",
}


def load_candidate_profile(path: str | Path, *, candidate_id: str | None = None) -> CandidateProfile:
    """Load a candidate profile from a local JSON file."""
    payload = _read_json_file(path)
    return candidate_profile_from_dict(payload, candidate_id=candidate_id, source_path=path)


def save_candidate_profile(profile: CandidateProfile, path: str | Path) -> Path:
    """Persist a candidate profile as local JSON for audit-friendly storage."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(candidate_profile_to_dict(profile), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


def candidate_profile_from_dict(
    payload: dict[str, Any],
    *,
    candidate_id: str | None = None,
    source_path: str | Path | None = None,
) -> CandidateProfile:
    """Validate a raw mapping and convert it into a CandidateProfile."""
    if not isinstance(payload, dict):
        raise ProfileValidationError("candidate profile payload must be a JSON object")

    unknown_fields = sorted(set(payload) - OPTIONAL_PROFILE_FIELDS - {"candidate_id"})
    if unknown_fields:
        raise ProfileValidationError(
            f"candidate profile contains unknown fields: {', '.join(unknown_fields)}"
        )

    resolved_candidate_id = candidate_id or payload.get("candidate_id")
    if not isinstance(resolved_candidate_id, str) or not resolved_candidate_id.strip():
        raise ProfileValidationError("candidate profile must include a non-empty candidate_id")

    normalised_lists = {
        field_name: _normalise_string_list(payload.get(field_name, []), field_name)
        for field_name in REQUIRED_PROFILE_LIST_FIELDS
    }

    name = _optional_string(payload.get("name"), "name")
    remote_preference = _optional_string(payload.get("remote_preference"), "remote_preference")
    master_cv_ref = _optional_string(payload.get("master_cv_ref"), "master_cv_ref")
    salary_floor_gbp = _optional_non_negative_int(payload.get("salary_floor_gbp"), "salary_floor_gbp")
    right_to_work_uk = _optional_bool(payload.get("right_to_work_uk"), "right_to_work_uk")
    years_experience = _optional_non_negative_float(
        payload.get("years_experience"), "years_experience"
    )

    profile = CandidateProfile(
        candidate_id=resolved_candidate_id.strip(),
        name=name,
        target_roles=normalised_lists["target_roles"],
        locations=normalised_lists["locations"],
        remote_preference=remote_preference,
        salary_floor_gbp=salary_floor_gbp,
        right_to_work_uk=right_to_work_uk,
        skills=normalised_lists["skills"],
        years_experience=years_experience,
        industries=normalised_lists["industries"],
        achievements=normalised_lists["achievements"],
        certifications=normalised_lists["certifications"],
        master_cv_ref=master_cv_ref,
    )

    if source_path is not None and profile.master_cv_ref:
        _resolve_local_path(source_path, profile.master_cv_ref)

    return profile


def candidate_profile_to_dict(profile: CandidateProfile) -> dict[str, Any]:
    return {
        "candidate_id": profile.candidate_id,
        "name": profile.name,
        "target_roles": profile.target_roles,
        "locations": profile.locations,
        "remote_preference": profile.remote_preference,
        "salary_floor_gbp": profile.salary_floor_gbp,
        "right_to_work_uk": profile.right_to_work_uk,
        "skills": profile.skills,
        "years_experience": profile.years_experience,
        "industries": profile.industries,
        "achievements": profile.achievements,
        "certifications": profile.certifications,
        "master_cv_ref": profile.master_cv_ref,
    }


def load_master_cv(path: str | Path) -> str:
    """Load a local master CV file as plain text or markdown."""
    cv_path = Path(path)
    if not cv_path.exists():
        raise FileNotFoundError(f"master CV file not found: {cv_path}")
    if not cv_path.is_file():
        raise ProfileValidationError(f"master CV path must point to a file: {cv_path}")

    content = cv_path.read_text(encoding="utf-8")
    if not content.strip():
        raise ProfileValidationError("master CV file must not be empty")
    return content


def save_master_cv(content: str, path: str | Path) -> Path:
    if not isinstance(content, str) or not content.strip():
        raise ProfileValidationError("master CV content must be a non-empty string")

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")
    return destination


def resolve_master_cv_path(profile: CandidateProfile, profile_path: str | Path) -> Path:
    if not profile.master_cv_ref:
        raise ProfileValidationError("candidate profile does not include master_cv_ref")
    return _resolve_local_path(profile_path, profile.master_cv_ref)


def _read_json_file(path: str | Path) -> dict[str, Any]:
    json_path = Path(path)
    if not json_path.exists():
        raise FileNotFoundError(f"candidate profile file not found: {json_path}")
    if not json_path.is_file():
        raise ProfileValidationError(f"candidate profile path must point to a file: {json_path}")

    try:
        raw_payload = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileValidationError(f"candidate profile file is not valid JSON: {exc}") from exc

    if not isinstance(raw_payload, dict):
        raise ProfileValidationError("candidate profile JSON must contain an object at the top level")
    return raw_payload


def _normalise_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProfileValidationError(f"{field_name} must be a list of strings")

    normalised_items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ProfileValidationError(f"{field_name} must contain only strings")
        cleaned = item.strip()
        if not cleaned:
            raise ProfileValidationError(f"{field_name} must not contain empty strings")
        normalised_items.append(cleaned)
    return normalised_items


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProfileValidationError(f"{field_name} must be a string when provided")
    cleaned = value.strip()
    if not cleaned:
        raise ProfileValidationError(f"{field_name} must not be empty when provided")
    return cleaned


def _optional_non_negative_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfileValidationError(f"{field_name} must be an integer when provided")
    if value < 0:
        raise ProfileValidationError(f"{field_name} must be non-negative when provided")
    return value


def _optional_non_negative_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileValidationError(f"{field_name} must be numeric when provided")
    if value < 0:
        raise ProfileValidationError(f"{field_name} must be non-negative when provided")
    return float(value)


def _optional_bool(value: Any, field_name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ProfileValidationError(f"{field_name} must be a boolean when provided")
    return value


def _resolve_local_path(base_path: str | Path, relative_or_absolute_path: str) -> Path:
    candidate_path = Path(relative_or_absolute_path)
    if candidate_path.is_absolute():
        return candidate_path
    return (Path(base_path).expanduser().resolve().parent / candidate_path).resolve()
