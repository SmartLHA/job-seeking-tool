from __future__ import annotations

from pathlib import Path

from src.config import TailoringPolicy
from src.evaluation import evaluate_reviewed_job
from src.models import CandidateProfile, JobAnalysis, JobPosting, ScoreBreakdown, ScoreComponent
from src.tailoring import (
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
        skills=["Stakeholder Management", "SQL", "Power BI", "Agile"],
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
    tailored = tailor_cv(
        "# Master CV\n\nBusiness analysis delivery.",
        ["Required skill: SQL", "Preferred skill: Power BI", "Experience: 5 years"],
        build_job(),
    )

    assert "# Tailored CV - Business Analyst" in tailored
    assert "## Matching Evidence" in tailored
    assert "- Required skill: SQL" in tailored
    assert "Keywords: SQL, Power BI" in tailored
    assert "## Base CV\n# Master CV\n\nBusiness analysis delivery." in tailored


def test_validate_tailored_cv_accepts_supported_output_only() -> None:
    profile = build_profile()
    original_cv = "# Master CV\n\nBusiness analysis delivery."
    tailored = tailor_cv(
        original_cv,
        ["Required skill: SQL", "Preferred skill: Power BI", "Experience: 5 years"],
        build_job(),
    )

    assert validate_tailored_cv(original_cv, tailored, profile) is True


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
    modified_base_cv = tailor_cv(
        original_cv,
        ["Required skill: SQL", "Experience: 5 years"],
        build_job(),
    ).replace("Business analysis delivery.", "Business analysis delivery with cloud architecture.")

    assert validate_tailored_cv(original_cv, invalid_skill, profile) is False
    assert validate_tailored_cv(original_cv, modified_base_cv, profile) is False


def test_save_tailored_cv_writes_output_in_expected_location(tmp_path: Path) -> None:
    output_path = save_tailored_cv(
        "job-123",
        "# Tailored CV - Business Analyst\n",
        "cand-001",
        policy=TailoringPolicy(output_dir=tmp_path / "output" / "tailored_cvs"),
    )

    assert output_path == tmp_path / "output" / "tailored_cvs" / "job-123.md"
    assert "profile_id: cand-001" in output_path.read_text(encoding="utf-8")


def test_evaluate_reviewed_job_allows_manual_review_selection_to_unlock_tailoring() -> None:
    analysis = evaluate_reviewed_job(
        build_profile(),
        build_job(required_skills=["stakeholder management", "Prince2"]),
        review_selected_for_tailoring=True,
    )

    assert analysis.decision == "review"
    assert analysis.tailoring_ready is True
    assert "manually selected" in analysis.tailoring_notes
