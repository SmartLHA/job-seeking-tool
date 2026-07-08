from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.job_hunt_models import Skill
from src.job_hunt_profile import (
    ProfileValidationError,
    candidate_profile_from_dict,
    candidate_profile_to_dict,
    load_candidate_profile,
    load_master_cv,
    resolve_master_cv_path,
    save_candidate_profile,
    save_master_cv,
)


def _base_profile_payload(**extra):
    return {"candidate_id": "cand-001", **extra}


# --- Daily Digest (D3) preference fields ----------------------------------- #

def test_digest_prefs_default_when_absent():
    p = candidate_profile_from_dict(_base_profile_payload())
    assert p.digest_enabled is True
    assert p.digest_threshold == 70
    assert p.digest_run_time == "07:00"
    assert p.digest_max_per_source == 50
    assert p.digest_llm_enabled is True
    assert p.digest_max_llm_per_run == 10
    assert (p.digest_llm_rpm, p.digest_llm_rpd, p.digest_llm_batch_size, p.digest_llm_batch_interval_min) == (4, 200, 4, 15)


def test_digest_prefs_round_trip():
    payload = _base_profile_payload(
        digest_enabled=False, digest_threshold=85, digest_run_time="06:30",
        digest_max_per_source=25, digest_llm_enabled=False, digest_max_llm_per_run=0,
        digest_llm_rpm=12, digest_llm_rpd=500, digest_llm_batch_size=8,
        digest_llm_batch_interval_min=30,
    )
    p = candidate_profile_from_dict(payload)
    again = candidate_profile_from_dict(candidate_profile_to_dict(p))
    assert again.digest_enabled is False
    assert again.digest_threshold == 85
    assert again.digest_run_time == "06:30"
    assert again.digest_max_llm_per_run == 0


def test_parse_bool_handles_stringy_false():
    # bool("false") == True regression guard
    assert candidate_profile_from_dict(_base_profile_payload(digest_enabled="false")).digest_enabled is False
    assert candidate_profile_from_dict(_base_profile_payload(digest_enabled="0")).digest_enabled is False
    assert candidate_profile_from_dict(_base_profile_payload(digest_enabled="on")).digest_enabled is True


@pytest.mark.parametrize("field,value", [
    ("digest_threshold", 101), ("digest_threshold", -1),
    ("digest_max_per_source", 0), ("digest_max_per_source", 201),
    ("digest_llm_rpm", 0), ("digest_llm_rpm", 61),
    ("digest_llm_rpd", 0), ("digest_llm_rpd", 1001),
    ("digest_llm_batch_size", 0), ("digest_llm_batch_size", 51),
    ("digest_llm_batch_interval_min", 0), ("digest_llm_batch_interval_min", 1441),
])
def test_digest_int_ranges_rejected(field, value):
    with pytest.raises(ProfileValidationError):
        candidate_profile_from_dict(_base_profile_payload(**{field: value}))


def test_digest_max_llm_per_run_zero_allowed():
    assert candidate_profile_from_dict(_base_profile_payload(digest_max_llm_per_run=0)).digest_max_llm_per_run == 0


@pytest.mark.parametrize("bad", ["7:00", "24:00", "07:60", "abc", "0700"])
def test_digest_run_time_rejects_bad(bad):
    with pytest.raises(ProfileValidationError):
        candidate_profile_from_dict(_base_profile_payload(digest_run_time=bad))


@pytest.mark.parametrize("good", ["07:00", "23:59", "00:00"])
def test_digest_run_time_accepts_good(good):
    assert candidate_profile_from_dict(_base_profile_payload(digest_run_time=good)).digest_run_time == good


def test_digest_bool_rejects_garbage():
    with pytest.raises(ProfileValidationError):
        candidate_profile_from_dict(_base_profile_payload(digest_enabled="maybe"))


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
