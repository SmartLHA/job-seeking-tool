from __future__ import annotations

from pathlib import Path

from src.job_hunt_config import TailoringPolicy
from src.job_hunt_evaluation import evaluate_reviewed_job
from src.job_hunt_models import CandidateProfile, JobAnalysis, JobPosting, ScoreBreakdown, ScoreComponent, Skill, TailoredCVResult
from src.job_hunt_tailoring import (
    save_tailored_cv,
    select_relevant_evidence,
    tailor_cv,
    validate_tailored_cv,
)


def build_profile() -> CandidateProfile:
    return CandidateProfile(
        candidate_id="cand-001",
        name="Mic",
        target_roles=["Business Analyst"],
        locations=["London"],
        remote_preference="remote_friendly",
        salary_floor_gbp=50000,
        right_to_work_uk=True,
        skills=[Skill(name="Stakeholder Management"), Skill(name="SQL"), Skill(name="Power BI"), Skill(name="Agile")],
        years_experience=5,
        industries=["finance"],
        achievements=["Improved reporting workflow by 20%"],
        certifications=["BCS Foundation"],
        master_cv_ref="docs/master_cv.md",
    )


def build_job(**overrides: object) -> JobPosting:
    payload: dict[str, object] = {
        "job_id": "job-001",
        "job_title": "Business Analyst",
        "company": "Example Co",
        "description_raw": "BA role needing stakeholder management, SQL, and Power BI.",
        "source_type": "copied_text",
        "source_ref": None,
        "location": "London",
        "work_mode": "hybrid",
        "employment_type": "full-time",
        "required_skills": ["stakeholder management", "SQL"],
        "preferred_skills": ["Power BI", "Prince2"],
        "required_years_experience": 3,
        "nice_to_have_years_experience": None,
        "domain": "finance",
        "notes": None,
        "salary_min_gbp": 50000,
        "salary_max_gbp": 60000,
    }
    payload.update(overrides)
    return JobPosting(**payload)


def build_analysis(job_id: str = "job-001") -> JobAnalysis:
    zero = ScoreComponent(value=0.0, reason="placeholder")
    return JobAnalysis(
        job_id=job_id,
        match_score=100.0,
        score_breakdown=ScoreBreakdown(
            skills_score=zero,
            experience_score=zero,
            location_score=zero,
            salary_score=zero,
            domain_score=zero,
            work_mode_score=zero,
            notes=[],
        ),
        decision="apply",
        decision_reason="placeholder",
        confidence="high",
        tailoring_ready=True,
        tailoring_notes="placeholder",
    )


def test_select_relevant_evidence_prioritises_required_then_preferred_then_experience() -> None:
    evidence = select_relevant_evidence(
        build_profile(),
        "# Master CV\n\nCore content",
        build_job(),
        build_analysis(),
    )

    assert evidence == [
        "Required skill: Stakeholder Management",
        "Required skill: SQL",
        "Preferred skill: Power BI",
        "Experience: 5 years",
    ]


def test_select_relevant_evidence_never_uses_achievements_or_certifications() -> None:
    evidence = select_relevant_evidence(
        build_profile(),
        "Improved reporting workflow\nBCS Foundation",
        build_job(required_skills=["BCS Foundation"], preferred_skills=["Improved reporting workflow"]),
        build_analysis(),
    )

    assert evidence == ["Experience: 5 years"]


def test_tailor_cv_builds_ats_friendly_output_without_inventing_sections() -> None:
    result = tailor_cv(
        "# Master CV\n\nBusiness analysis delivery.",
        ["Required skill: SQL", "Preferred skill: Power BI", "Experience: 5 years"],
        build_job(),
    )
    tailored = result.markdown

    assert "# Tailored CV - Business Analyst" in tailored
    assert "## Matching Evidence" in tailored
    assert "- Required skill: SQL" in tailored
    assert "Keywords: SQL, Power BI" in tailored
    assert "## Base CV\n# Master CV\n\nBusiness analysis delivery." in tailored


def test_validate_tailored_cv_accepts_supported_output_only() -> None:
    profile = build_profile()
    original_cv = "# Master CV\n\nBusiness analysis delivery."
    result = tailor_cv(
        original_cv,
        ["Required skill: SQL", "Preferred skill: Power BI", "Experience: 5 years"],
        build_job(),
    )

    assert validate_tailored_cv(original_cv, result, profile) is True


def test_validate_tailored_cv_rejects_invented_skill_or_modified_base_cv() -> None:
    profile = build_profile()
    original_cv = "# Master CV\n\nBusiness analysis delivery."
    invalid_skill = """# Tailored CV - Business Analyst

## Role Target
- Job title: Business Analyst
- Company: Example Co

## Matching Evidence
- Required skill: Python

## ATS Keywords
Keywords: Python

## Base CV
# Master CV

Business analysis delivery.
"""
    modified_base_cv_result = tailor_cv(
        original_cv,
        ["Required skill: SQL", "Experience: 5 years"],
        build_job(),
    )
    modified_base_cv_md = modified_base_cv_result.markdown.replace(
        "Business analysis delivery.", "Business analysis delivery with cloud architecture."
    )

    assert validate_tailored_cv(original_cv, invalid_skill, profile) is False
    assert validate_tailored_cv(original_cv, modified_base_cv_md, profile) is False


def test_validate_tailored_cv_rejects_unexpected_generated_section_before_base_cv() -> None:
    profile = build_profile()
    original_cv = "# Master CV\n\nBusiness analysis delivery."
    tailored_result = tailor_cv(original_cv, ["Required skill: SQL"], build_job())
    tailored_md = tailored_result.markdown.replace(
        "## Base CV",
        "## Hidden Claims\n- Certified cloud architect\n\n## Base CV",
    )

    assert validate_tailored_cv(original_cv, tailored_md, profile) is False


def test_validate_tailored_cv_rejects_extra_unsupported_ats_keyword_lines() -> None:
    profile = build_profile()
    original_cv = "# Master CV\n\nBusiness analysis delivery."
    tailored_result = tailor_cv(original_cv, ["Required skill: SQL"], build_job())
    tailored_md = tailored_result.markdown.replace(
        "Keywords: SQL",
        "Keywords: SQL\n- Cloud architecture",
    )

    assert validate_tailored_cv(original_cv, tailored_md, profile) is False


def test_validate_tailored_cv_rejects_malformed_role_target_content() -> None:
    profile = build_profile()
    original_cv = "# Master CV\n\nBusiness analysis delivery."
    tailored_result = tailor_cv(original_cv, ["Required skill: SQL"], build_job())
    tailored_md = tailored_result.markdown.replace(
        "- Job title: Business Analyst",
        "- Target role: Business Analyst",
    )

    assert validate_tailored_cv(original_cv, tailored_md, profile) is False


def test_save_tailored_cv_writes_output_in_expected_location(tmp_path: Path) -> None:
    output_path = save_tailored_cv(
        "job-123",
        "# Tailored CV - Business Analyst\n",
        "cand-001",
        policy=TailoringPolicy(output_dir=tmp_path / "output" / "tailored_cvs"),
    )

    assert output_path == tmp_path / "output" / "tailored_cvs" / "job-123.md"
    assert "profile_id: cand-001" in output_path.read_text(encoding="utf-8")


def test_tailor_cv_returns_tailored_cv_result() -> None:
    result = tailor_cv(
        "# Master CV\n\nBusiness analysis delivery.",
        ["Required skill: SQL"],
        build_job(),
    )

    assert isinstance(result, TailoredCVResult)


def test_tailor_cv_summary_is_non_empty_string() -> None:
    result = tailor_cv(
        "# Master CV\n\nBusiness analysis delivery.",
        ["Required skill: SQL"],
        build_job(),
        profile=build_profile(),
    )

    assert isinstance(result.summary, str)
    assert len(result.summary.strip()) > 0


def test_tailor_cv_promoted_contains_required_skill_bullets() -> None:
    result = tailor_cv(
        "# Master CV\n\nBusiness analysis delivery.",
        ["Required skill: SQL", "Required skill: Stakeholder Management"],
        build_job(),
    )

    # The markdown has "- Required skill: SQL" and "- Required skill: Stakeholder Management" bullets
    # which contain the required skill keywords "SQL" and "stakeholder management"
    assert len(result.promoted) > 0
    assert any("SQL" in bullet or "sql" in bullet.lower() for bullet in result.promoted)


def test_tailor_cv_matched_keywords_appear_in_markdown() -> None:
    result = tailor_cv(
        "# Master CV\n\nBusiness analysis delivery.",
        ["Required skill: SQL", "Preferred skill: Power BI", "Experience: 5 years"],
        build_job(),
    )

    for kw in result.matched:
        assert kw.lower() in result.markdown.lower(), f"Matched keyword '{kw}' not found in markdown"


def test_tailor_cv_missing_keywords_absent_from_markdown() -> None:
    result = tailor_cv(
        "# Master CV\n\nBusiness analysis delivery.",
        ["Required skill: SQL", "Preferred skill: Power BI", "Experience: 5 years"],
        build_job(),
    )

    for kw in result.missing:
        assert kw.lower() not in result.markdown.lower(), f"Missing keyword '{kw}' found in markdown"


def test_validate_tailored_cv_accepts_valid_result() -> None:
    profile = build_profile()
    original_cv = "# Master CV\n\nBusiness analysis delivery."
    result = tailor_cv(
        original_cv,
        ["Required skill: SQL", "Preferred skill: Power BI", "Experience: 5 years"],
        build_job(),
        profile=profile,
    )

    assert validate_tailored_cv(original_cv, result, profile) is True


def test_validate_tailored_cv_rejects_result_with_invented_summary() -> None:
    profile = build_profile()
    original_cv = "# Master CV\n\nBusiness analysis delivery."
    result = tailor_cv(
        original_cv,
        ["Required skill: SQL"],
        build_job(),
        profile=profile,
    )
    # Replace the summary with an invented claim
    invented_result = TailoredCVResult(
        summary="",  # Empty summary should fail validation
        promoted=result.promoted,
        matched=result.matched,
        missing=result.missing,
        markdown=result.markdown,
    )

    assert validate_tailored_cv(original_cv, invented_result, profile) is False


def test_evaluate_reviewed_job_allows_manual_review_selection_to_unlock_tailoring() -> None:
    analysis = evaluate_reviewed_job(
        build_profile(),
        build_job(required_skills=["stakeholder management", "Prince2"]),
        review_selected_for_tailoring=True,
    )

    assert analysis.decision == "review"
    assert analysis.tailoring_ready is True
    assert "manually selected" in analysis.tailoring_notes
