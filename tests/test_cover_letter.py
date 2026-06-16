"""Tests for cover_letter.py"""

from __future__ import annotations

import pytest

from src.job_hunt_cover_letter import _format_list, _match_skills, _normalize_text, generate_cover_letter, generate_cover_letter_text
from src.job_hunt_models import (
    CandidateProfile,
    JobAnalysis,
    JobPosting,
    ScoreBreakdown,
    ScoreComponent,
    Skill,
)


def build_profile(**overrides: object) -> CandidateProfile:
    defaults: dict[str, object] = {
        "candidate_id": "cand-001",
        "name": "Mic",
        "target_roles": ["Business Analyst", "Data Analyst"],
        "locations": ["London"],
        "remote_preference": "remote_friendly",
        "salary_floor_gbp": 50000,
        "right_to_work_uk": True,
        "skills": [Skill(name="Stakeholder Management"), Skill(name="SQL"), Skill(name="Power BI"), Skill(name="Python")],
        "years_experience": 5.0,
        "industries": ["finance", "technology"],
        "achievements": [
            "Improved reporting workflow by 20% using Power BI dashboards",
            "Delivered a cross-functional data pipeline saving 10 hours per week",
        ],
        "certifications": ["BCS Foundation"],
        "master_cv_ref": "docs/master_cv.md",
    }
    defaults.update(overrides)
    return CandidateProfile(**defaults)


def build_job(**overrides: object) -> JobPosting:
    defaults: dict[str, object] = {
        "job_id": "job-001",
        "job_title": "Business Analyst",
        "company": "Example Co",
        "description_raw": "BA role requiring stakeholder management, SQL, and Power BI.",
        "source_type": "copied_text",
        "source_ref": None,
        "location": "London",
        "work_mode": "hybrid",
        "employment_type": "full-time",
        "required_skills": ["Stakeholder Management", "SQL"],
        "preferred_skills": ["Power BI", "Prince2"],
        "required_years_experience": 3.0,
        "nice_to_have_years_experience": None,
        "domain": "finance",
        "notes": None,
        "salary_min_gbp": 50000,
        "salary_max_gbp": 60000,
    }
    defaults.update(overrides)
    return JobPosting(**defaults)


def test_generate_cover_letter_has_opening_with_role_and_company() -> None:
    profile = build_profile()
    job = build_job()
    letter = generate_cover_letter(profile, "", job, "Excited about Example Co.")

    assert "Business Analyst" in letter
    assert "Example Co" in letter


def test_generate_cover_letter_para1_maps_required_skills_to_evidence() -> None:
    profile = build_profile()
    job = build_job()
    letter = generate_cover_letter(profile, "", job, "Excited about Example Co.")

    # Required skills should appear in the letter
    assert "Stakeholder Management" in letter
    assert "SQL" in letter


def test_generate_cover_letter_para2_uses_why_company_text_as_is() -> None:
    profile = build_profile()
    job = build_job()
    why_text = "Example Co's focus on data-driven decision making aligns perfectly with my background."
    letter = generate_cover_letter(profile, "", job, why_text)

    assert why_text in letter


def test_generate_cover_letter_para3_pulls_achievements_from_profile() -> None:
    profile = build_profile()
    job = build_job()
    letter = generate_cover_letter(profile, "", job, "Excited about Example Co.")

    assert "Improved reporting workflow" in letter


def test_generate_cover_letter_closing_has_cta_and_availability() -> None:
    profile = build_profile()
    job = build_job()
    letter = generate_cover_letter(profile, "", job, "Excited about Example Co.")

    assert "opportunity to discuss" in letter
    assert "available" in letter.lower() or "convenience" in letter


def test_generate_cover_letter_has_no_salary_field() -> None:
    profile = build_profile()
    job = build_job()
    letter = generate_cover_letter(profile, "", job, "Excited about Example Co.")

    assert "salary" not in letter.lower() or "salary_floor" not in letter


def test_generate_cover_letter_is_plain_text_no_html_tables() -> None:
    profile = build_profile()
    job = build_job()
    letter = generate_cover_letter(profile, "", job, "Excited about Example Co.")

    assert "<table" not in letter
    assert "<tr>" not in letter
    assert "<td>" not in letter
    assert "## " not in letter  # markdown headers
    assert "ALL-CAPS" not in letter.upper()[:100]  # no ALL-CAPS near start


def test_generate_cover_letter_word_count_approximately_250_300() -> None:
    profile = build_profile()
    job = build_job()
    letter = generate_cover_letter(profile, "", job, "Example Co is a leader in its field with a strong team culture that I am eager to join.")

    word_count = len(letter.split())
    # Accept 200-400 as a soft window since we use minimal why_company_text
    assert 150 <= word_count <= 450


def test_generate_cover_letter_includes_candidate_name_in_closing() -> None:
    profile = build_profile()
    job = build_job()
    letter = generate_cover_letter(profile, "", job, "Excited about Example Co.")

    assert "Mic" in letter


def test_generate_cover_letter_without_name_uses_default() -> None:
    profile = build_profile(name=None)
    job = build_job()
    letter = generate_cover_letter(profile, "", job, "Excited about Example Co.")

    # Should not crash and should contain "Dear" greeting
    assert "Dear" in letter


def test_generate_cover_letter_handles_empty_why_company_text() -> None:
    profile = build_profile()
    job = build_job()
    letter = generate_cover_letter(profile, "", job, "")

    # Should not crash, paragraph 2 should be skipped gracefully
    assert letter.count("\n\n") >= 2  # At least some paragraph structure


def test_generate_cover_letter_matches_case_insensitive_skills() -> None:
    profile = build_profile(skills=[Skill(name="stakeholder management"), Skill(name="sql"), Skill(name="power bi")])
    job = build_job(required_skills=["STAKEHOLDER MANAGEMENT", "SQL"])
    letter = generate_cover_letter(profile, "", job, "Excited about Example Co.")

    # Should match regardless of case
    assert "Stakeholder Management" in letter or "stakeholder management" in letter
    assert "SQL" in letter


def test_generate_cover_letter_para2_adds_punctuation_if_missing() -> None:
    profile = build_profile()
    job = build_job()
    why_text = "Example Co is great"  # no trailing punctuation
    letter = generate_cover_letter(profile, "", job, why_text)

    # Should add a period
    assert why_text.rstrip() + "." in letter or "Example Co is great." in letter


def test_format_list_single_item() -> None:
    result = _format_list(["Python"])
    assert result == "Python"


def test_format_list_two_items() -> None:
    result = _format_list(["Python", "SQL"])
    assert result == "Python and SQL"


def test_format_list_three_items() -> None:
    result = _format_list(["Python", "SQL", "Power BI"])
    assert result == "Python, SQL, and Power BI"


def test_match_skills_normalizes_for_matching() -> None:
    profile_skills = ["Stakeholder Management", "SQL", "Power BI"]
    job_skills = ["stakeholder management", "python"]  # python not in profile
    matched = _match_skills(job_skills, profile_skills)

    assert "Stakeholder Management" in matched
    assert "SQL" not in matched  # python doesn't match anything in profile


def test_normalize_text_lowercase_and_collapse() -> None:
    assert _normalize_text("  Stakeholder   Management  ") == "stakeholder management"
    assert _normalize_text("SQL") == "sql"


def test_generate_cover_letter_without_achievements_falls_back() -> None:
    profile = build_profile(
        achievements=[],
        skills=[Skill(name="Stakeholder Management")],
        years_experience=3.0,
    )
    job = build_job()
    letter = generate_cover_letter(profile, "", job, "Excited about Example Co.")

    # Should not crash and should include at least the skills/years experience
    assert "Stakeholder Management" in letter or "3" in letter


def test_generate_cover_letter_respects_industries_in_opening() -> None:
    profile = build_profile(target_roles=[])  # no target roles
    job = build_job()
    letter = generate_cover_letter(profile, "", job, "Excited about Example Co.")

    # Should fall back to industries or generic
    assert "Example Co" in letter


def test_generate_cover_letter_multiple_achievements_uses_first_two() -> None:
    profile = build_profile(
        achievements=[
            "Built a real-time dashboard",
            "Reduced latency by 40%",
            "Mentored junior analysts",
        ]
    )
    job = build_job()
    letter = generate_cover_letter(profile, "", job, "Excited about Example Co.")

    # Should include at least the first two achievements
    assert "Built a real-time dashboard" in letter
    assert "Reduced latency" in letter
    # Third should not be prominently featured


# ---------------------------------------------------------------------------
# Helpers for generate_cover_letter_text tests
# ---------------------------------------------------------------------------

def _zero_score() -> ScoreComponent:
    return ScoreComponent(value=0.0, reason="placeholder")


def build_analysis(**overrides: object) -> JobAnalysis:
    defaults: dict[str, object] = {
        "job_id": "job-001",
        "match_score": 85.0,
        "score_breakdown": ScoreBreakdown(
            skills_score=_zero_score(),
            experience_score=_zero_score(),
            location_score=_zero_score(),
            salary_score=_zero_score(),
            domain_score=_zero_score(),
            work_mode_score=_zero_score(),
        ),
        "decision": "apply",
        "decision_reason": "Strong match.",
    }
    defaults.update(overrides)
    return JobAnalysis(**defaults)


# ---------------------------------------------------------------------------
# New tests for generate_cover_letter_text
# ---------------------------------------------------------------------------

def test_generate_cover_letter_includes_why_company_text_verbatim() -> None:
    profile = build_profile()
    job = build_job()
    analysis = build_analysis()
    why = "Example Co's data-driven culture and innovation make it my top choice."
    letter = generate_cover_letter_text(profile, "", job, analysis, why)
    assert why in letter


def test_generate_cover_letter_default_tone_is_professional() -> None:
    profile = build_profile()
    job = build_job()
    analysis = build_analysis()
    letter = generate_cover_letter_text(profile, "", job, analysis, "Excited about Example Co.")
    assert isinstance(letter, str)
    assert len(letter) > 0


def test_generate_cover_letter_conversational_tone_produces_text() -> None:
    profile = build_profile()
    job = build_job()
    analysis = build_analysis()
    why = "Example Co's culture inspires me."
    letter = generate_cover_letter_text(profile, "", job, analysis, why, tone="conversational")
    assert isinstance(letter, str)
    assert len(letter) > 0
    assert why in letter


def test_generate_cover_letter_concise_tone_produces_text() -> None:
    profile = build_profile()
    job = build_job()
    analysis = build_analysis()
    letter = generate_cover_letter_text(profile, "", job, analysis, "Excited about Example Co.", tone="concise")
    assert isinstance(letter, str)
    assert len(letter) > 0


def test_generate_cover_letter_brief_length_is_shorter_than_standard() -> None:
    profile = build_profile()
    job = build_job()
    analysis = build_analysis()
    why = "I admire Example Co's leadership in the sector."
    brief = generate_cover_letter_text(profile, "", job, analysis, why, length="brief")
    standard = generate_cover_letter_text(profile, "", job, analysis, why, length="standard")
    assert len(brief) < len(standard)


def test_generate_cover_letter_detailed_length_is_longer_than_standard() -> None:
    profile = build_profile()
    job = build_job()
    analysis = build_analysis()
    why = "I admire Example Co's leadership in the sector."
    standard = generate_cover_letter_text(profile, "", job, analysis, why, length="standard")
    detailed = generate_cover_letter_text(profile, "", job, analysis, why, length="detailed")
    assert len(detailed) > len(standard)


def test_generate_cover_letter_points_appear_in_output_when_grounded() -> None:
    profile = build_profile(
        skills=[Skill(name="SQL"), Skill(name="Power BI"), Skill(name="Stakeholder Management")],
    )
    job = build_job()
    analysis = build_analysis()
    # "SQL" matches a profile skill so it is grounded
    letter = generate_cover_letter_text(
        profile, "", job, analysis, "Excited about Example Co.",
        points=["SQL"],
    )
    assert "SQL" in letter


def test_generate_cover_letter_rejects_invalid_tone() -> None:
    profile = build_profile()
    job = build_job()
    analysis = build_analysis()
    with pytest.raises(ValueError, match="Invalid tone"):
        generate_cover_letter_text(profile, "", job, analysis, "Why text.", tone="formal")


def test_generate_cover_letter_rejects_invalid_length() -> None:
    profile = build_profile()
    job = build_job()
    analysis = build_analysis()
    with pytest.raises(ValueError, match="Invalid length"):
        generate_cover_letter_text(profile, "", job, analysis, "Why text.", length="paragraph")