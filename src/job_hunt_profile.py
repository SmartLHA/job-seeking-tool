from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any

from src.job_hunt_models import CandidateProfile, Skill
from src import job_hunt_validation as _v


def parse_cv_file(path: Path) -> str:
    """Extract text from .txt, .pdf, .docx files."""
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        return "\n".join(page.extract_text() for page in reader.pages)
    elif suffix == ".docx":
        from docx import Document

        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


class ProfileValidationError(ValueError):
    """Raised when profile or CV input is structurally invalid."""


# The candidate profile is one of the two approved truth sources for MVP.
# Keep this module focused on loading and validating that source-of-truth data,
# not on any scoring or decision logic.
REQUIRED_PROFILE_LIST_FIELDS = (
    "target_roles",
    "locations",
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
    "master_cv_text",
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

    skills = _load_skills(payload.get("skills", []))

    name = _optional_string(payload.get("name"), "name")
    remote_preference = _optional_string(payload.get("remote_preference"), "remote_preference")
    master_cv_ref = _optional_string(payload.get("master_cv_ref"), "master_cv_ref")
    master_cv_text = _optional_text_or_empty(payload.get("master_cv_text"), "master_cv_text")
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
        skills=skills,
        years_experience=years_experience,
        industries=normalised_lists["industries"],
        achievements=normalised_lists["achievements"],
        certifications=normalised_lists["certifications"],
        master_cv_ref=master_cv_ref,
        master_cv_text=master_cv_text,
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
        "skills": [_skill_to_dict(s) for s in profile.skills],
        "years_experience": profile.years_experience,
        "industries": profile.industries,
        "achievements": profile.achievements,
        "certifications": profile.certifications,
        "master_cv_ref": profile.master_cv_ref,
        "master_cv_text": profile.master_cv_text,
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


def _coerce_skill(raw: Any) -> Skill:
    """Coerce a plain string or dict into a Skill. Raises ProfileValidationError on bad input."""
    if isinstance(raw, str):
        name = raw.strip()
        if not name:
            raise ProfileValidationError("skills contains an empty string entry")
        return Skill(name=name)
    if isinstance(raw, dict):
        if "name" not in raw:
            raise ProfileValidationError(f"skill dict missing 'name' key: {raw!r}")
        known_keys = {"name", "level", "years", "evidence_type"}
        filtered = {k: v for k, v in raw.items() if k in known_keys}
        try:
            return Skill(**filtered)
        except (TypeError, ValueError) as exc:
            raise ProfileValidationError(f"invalid skill entry {raw!r}: {exc}") from exc
    raise ProfileValidationError(
        f"invalid skill entry type {type(raw).__name__!r}: {raw!r}; expected str or dict"
    )


def _load_skills(value: Any) -> list[Skill]:
    """Load the skills list from raw payload, coercing strings and dicts."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProfileValidationError("skills must be a list")
    return [_coerce_skill(item) for item in value]


def _skill_to_dict(skill: Skill) -> dict[str, Any]:
    return {
        "name": skill.name,
        "level": skill.level,
        "years": skill.years,
        "evidence_type": skill.evidence_type,
    }


_normalise_string_list = partial(_v.string_list, strip=True, dedup=False, allow_empty_items=False, error=ProfileValidationError)


_optional_string = partial(_v.optional_string, error=ProfileValidationError)


_optional_text_or_empty = partial(_v.optional_text_or_empty, error=ProfileValidationError)


_optional_non_negative_int = partial(_v.optional_int, non_negative=True, error=ProfileValidationError)


_optional_non_negative_float = partial(_v.optional_non_negative_float, error=ProfileValidationError)


_optional_bool = partial(_v.optional_bool, error=ProfileValidationError)


def _resolve_local_path(base_path: str | Path, relative_or_absolute_path: str) -> Path:
    candidate_path = Path(relative_or_absolute_path)
    if candidate_path.is_absolute():
        return candidate_path
    return (Path(base_path).expanduser().resolve().parent / candidate_path).resolve()
