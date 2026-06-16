from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.job_hunt_models import Skill
from src.job_hunt_profile import (
    ProfileValidationError,
    candidate_profile_from_dict,
    load_candidate_profile,
    load_master_cv,
    resolve_master_cv_path,
    save_candidate_profile,
    save_master_cv,
)


def test_load_candidate_profile_reads_local_json_file(tmp_path: Path) -> None:
    profile_path = tmp_path / "candidate_profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "candidate_id": "cand-001",
                "name": "Mic",
                "target_roles": [" Business Analyst ", "Product Analyst"],
                "locations": [" London ", "Manchester"],
                "remote_preference": " remote_friendly ",
                "salary_floor_gbp": 50000,
                "right_to_work_uk": True,
                "skills": [" Stakeholder Management ", "SQL"],
                "years_experience": 5,
                "industries": ["finance"],
                "achievements": ["Improved reporting workflow"],
                "certifications": ["PSM I"],
                "master_cv_ref": "docs/master_cv.md",
            }
        ),
        encoding="utf-8",
    )

    profile = load_candidate_profile(profile_path)

    assert profile.candidate_id == "cand-001"
    assert profile.target_roles == ["Business Analyst", "Product Analyst"]
    assert profile.locations == ["London", "Manchester"]
    assert profile.remote_preference == "remote_friendly"
    assert profile.skills == [Skill(name="Stakeholder Management"), Skill(name="SQL")]
    assert profile.years_experience == 5.0
    assert profile.master_cv_ref == "docs/master_cv.md"


def test_load_candidate_profile_rejects_unknown_fields() -> None:
    with pytest.raises(ProfileValidationError, match="unknown fields"):
        candidate_profile_from_dict(
            {
                "candidate_id": "cand-001",
                "target_roles": [],
                "locations": [],
                "skills": [],
                "industries": [],
                "achievements": [],
                "certifications": [],
                "unexpected": "value",
            }
        )


def test_load_candidate_profile_rejects_invalid_skill_type() -> None:
    with pytest.raises(ProfileValidationError, match="invalid skill entry type"):
        candidate_profile_from_dict(
            {
                "candidate_id": "cand-001",
                "target_roles": [],
                "locations": [],
                "skills": ["SQL", 123],
                "industries": [],
                "achievements": [],
                "certifications": [],
            }
        )


def test_load_candidate_profile_rejects_invalid_boolean_field() -> None:
    with pytest.raises(ProfileValidationError, match="right_to_work_uk must be a boolean"):
        candidate_profile_from_dict(
            {
                "candidate_id": "cand-001",
                "target_roles": [],
                "locations": [],
                "skills": [],
                "industries": [],
                "achievements": [],
                "certifications": [],
                "right_to_work_uk": "yes",
            }
        )


def test_save_candidate_profile_round_trips_cleanly(tmp_path: Path) -> None:
    profile = candidate_profile_from_dict(
        {
            "candidate_id": "cand-001",
            "name": "Mic",
            "target_roles": ["Business Analyst"],
            "locations": ["London"],
            "skills": ["SQL"],
            "industries": ["finance"],
            "achievements": ["Built reporting dashboards"],
            "certifications": [],
            "master_cv_ref": "cv/master_cv.md",
        }
    )

    output_path = tmp_path / "saved" / "candidate_profile.json"
    save_candidate_profile(profile, output_path)
    reloaded = load_candidate_profile(output_path)

    assert reloaded == profile


def test_resolve_master_cv_path_uses_profile_file_location(tmp_path: Path) -> None:
    profile_path = tmp_path / "profiles" / "candidate_profile.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        json.dumps(
            {
                "candidate_id": "cand-001",
                "target_roles": [],
                "locations": [],
                "skills": [],
                "industries": [],
                "achievements": [],
                "certifications": [],
                "master_cv_ref": "../cv/master_cv.md",
            }
        ),
        encoding="utf-8",
    )

    profile = load_candidate_profile(profile_path)

    assert resolve_master_cv_path(profile, profile_path) == tmp_path / "cv" / "master_cv.md"


def test_load_master_cv_reads_non_empty_text(tmp_path: Path) -> None:
    cv_path = tmp_path / "master_cv.md"
    cv_path.write_text("# Mic\n\nBusiness Analyst experience", encoding="utf-8")

    content = load_master_cv(cv_path)

    assert "Business Analyst" in content


def test_load_master_cv_rejects_empty_files(tmp_path: Path) -> None:
    cv_path = tmp_path / "master_cv.md"
    cv_path.write_text("   \n", encoding="utf-8")

    with pytest.raises(ProfileValidationError, match="must not be empty"):
        load_master_cv(cv_path)


def test_save_master_cv_rejects_blank_content(tmp_path: Path) -> None:
    with pytest.raises(ProfileValidationError, match="non-empty string"):
        save_master_cv("   ", tmp_path / "master_cv.md")


# --- Skill coercion tests ---

def test_plain_string_skills_coerced_to_skill_objects() -> None:
    profile = candidate_profile_from_dict(
        {
            "candidate_id": "cand-001",
            "target_roles": [],
            "locations": [],
            "skills": ["Python", "SQL"],
            "industries": [],
            "achievements": [],
            "certifications": [],
        }
    )
    assert profile.skills == [Skill(name="Python"), Skill(name="SQL")]
    assert profile.skills[0].level == "unspecified"
    assert profile.skills[0].evidence_type == "self-reported"


def test_skill_dict_round_trips_with_all_fields() -> None:
    profile = candidate_profile_from_dict(
        {
            "candidate_id": "cand-001",
            "target_roles": [],
            "locations": [],
            "skills": [{"name": "SQL", "level": "senior", "years": 7, "evidence_type": "evidenced"}],
            "industries": [],
            "achievements": [],
            "certifications": [],
        }
    )
    assert profile.skills == [Skill(name="SQL", level="senior", years=7, evidence_type="evidenced")]


def test_skill_dict_missing_name_raises() -> None:
    with pytest.raises(ProfileValidationError, match="missing 'name' key"):
        candidate_profile_from_dict(
            {
                "candidate_id": "cand-001",
                "target_roles": [],
                "locations": [],
                "skills": [{"level": "mid"}],
                "industries": [],
                "achievements": [],
                "certifications": [],
            }
        )


def test_skill_invalid_level_raises() -> None:
    with pytest.raises(ProfileValidationError, match="invalid skill"):
        candidate_profile_from_dict(
            {
                "candidate_id": "cand-001",
                "target_roles": [],
                "locations": [],
                "skills": [{"name": "SQL", "level": "beginner"}],
                "industries": [],
                "achievements": [],
                "certifications": [],
            }
        )


def test_skill_saves_and_reloads_as_dict(tmp_path: Path) -> None:
    profile = candidate_profile_from_dict(
        {
            "candidate_id": "cand-001",
            "target_roles": [],
            "locations": [],
            "skills": [{"name": "SQL", "level": "senior", "years": 5, "evidence_type": "evidenced"}],
            "industries": [],
            "achievements": [],
            "certifications": [],
        }
    )
    path = tmp_path / "p.json"
    save_candidate_profile(profile, path)
    reloaded = load_candidate_profile(path)
    assert reloaded.skills == [Skill(name="SQL", level="senior", years=5, evidence_type="evidenced")]
