from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.profile import (
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
    assert profile.skills == ["Stakeholder Management", "SQL"]
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


def test_load_candidate_profile_rejects_invalid_list_values() -> None:
    with pytest.raises(ProfileValidationError, match="skills must contain only strings"):
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
