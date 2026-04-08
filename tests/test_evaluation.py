from src.evaluation import evaluate_reviewed_job
from src.models import Blocker, CandidateProfile, JobPosting


def build_candidate() -> CandidateProfile:
    return CandidateProfile(
        candidate_id="cand-001",
        name="Mic",
        target_roles=["Business Analyst"],
        locations=["London", "Manchester"],
        remote_preference="remote_friendly",
        salary_floor_gbp=50000,
        right_to_work_uk=True,
        skills=["Stakeholder Management", "Process Mapping", "SQL", "Agile"],
        years_experience=5,
        industries=["finance", "technology"],
        achievements=[],
        certifications=[],
        master_cv_ref="data/cv.md",
    )


def build_job(**overrides: object) -> JobPosting:
    payload: dict[str, object] = {
        "job_id": "job-001",
        "job_title": "Business Analyst",
        "company": "Example Co",
        "description_raw": "Looking for a BA with stakeholder management and process mapping.",
        "source_type": "copied_text",
        "source_ref": None,
        "location": "London",
        "work_mode": "hybrid",
        "employment_type": "full-time",
        "required_skills": ["stakeholder management", "process mapping"],
        "preferred_skills": ["SQL", "Power BI"],
        "required_years_experience": 3,
        "nice_to_have_years_experience": None,
        "domain": "finance",
        "notes": None,
        "salary_min_gbp": 50000,
        "salary_max_gbp": 60000,
    }
    payload.update(overrides)
    return JobPosting(**payload)


def test_evaluate_reviewed_job_builds_apply_analysis_from_scoring_and_decision() -> None:
    analysis = evaluate_reviewed_job(build_candidate(), build_job())

    assert analysis.job_id == "job-001"
    assert analysis.match_score == 100.0
    assert analysis.confidence == "high"
    assert analysis.decision == "apply"
    assert analysis.blockers == []
    assert analysis.missing_required_skills == []
    assert analysis.missing_preferred_skills == ["Power BI"]
    assert analysis.tailoring_ready is True
    assert "approved profile and CV facts only" in analysis.tailoring_notes


def test_evaluate_reviewed_job_preserves_required_skill_gap_as_review() -> None:
    analysis = evaluate_reviewed_job(
        build_candidate(),
        build_job(required_skills=["stakeholder management", "Power BI"]),
    )

    assert analysis.match_score == 80.0
    assert analysis.decision == "review"
    assert analysis.missing_required_skills == ["Power BI"]
    assert any(flag.code == "missing-required-skills" for flag in analysis.risk_flags)
    assert analysis.tailoring_ready is False
    assert "Manual selection is required" in analysis.tailoring_notes


def test_evaluate_reviewed_job_allows_blockers_to_override_score() -> None:
    analysis = evaluate_reviewed_job(
        build_candidate(),
        build_job(),
        blockers=[
            Blocker(
                code="work_authorization",
                label="Work authorization",
                reason="Role requires sponsorship that is unavailable",
                severity="critical",
            )
        ],
    )

    assert analysis.match_score == 100.0
    assert analysis.decision == "skip"
    assert len(analysis.blockers) == 1
    assert analysis.blockers[0].code == "work_authorization"
    assert analysis.tailoring_ready is False
    assert analysis.tailoring_notes == "Skipped jobs are not tailoring-ready."


def test_evaluate_reviewed_job_keeps_confidence_separate_from_fit_score() -> None:
    analysis = evaluate_reviewed_job(
        build_candidate(),
        build_job(
            required_skills=[],
            required_years_experience=None,
            location=None,
            work_mode="unknown",
            salary_min_gbp=None,
            salary_max_gbp=None,
            domain=None,
        ),
    )

    assert analysis.match_score == 51.5
    assert analysis.confidence == "low"
    assert analysis.decision == "skip"
    assert any("did not include explicit required skills" in note for note in analysis.score_breakdown.notes)


def test_evaluate_reviewed_job_defaults_low_salary_mismatch_to_review() -> None:
    analysis = evaluate_reviewed_job(
        build_candidate(),
        build_job(salary_min_gbp=45000, salary_max_gbp=48000),
    )

    assert analysis.match_score == 91.0
    assert analysis.decision == "review"
    assert analysis.tailoring_ready is False
    assert any(flag.code == "salary-below-floor" for flag in analysis.risk_flags)
