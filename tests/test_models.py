from src.models import (
    Blocker,
    CandidateProfile,
    JobAnalysis,
    JobPosting,
    RiskFlag,
    ScoreBreakdown,
    ScoreComponent,
)


def build_score_breakdown() -> ScoreBreakdown:
    return ScoreBreakdown(
        skills_score=ScoreComponent(value=32, reason="Strong required skill overlap"),
        experience_score=ScoreComponent(value=18, reason="Experience level is suitable"),
        location_score=ScoreComponent(value=12, reason="Location is acceptable"),
        salary_score=ScoreComponent(value=8, reason="Salary range is acceptable"),
        domain_score=ScoreComponent(value=6, reason="Domain fit is neutral"),
        work_mode_score=ScoreComponent(value=4, reason="Work mode is acceptable"),
    )


def test_candidate_profile_allows_unknown_optional_fields() -> None:
    profile = CandidateProfile(candidate_id="cand-001")

    assert profile.name is None
    assert profile.target_roles == []
    assert profile.locations == []
    assert profile.salary_floor_gbp is None
    assert profile.right_to_work_uk is None
    assert profile.master_cv_ref is None


def test_job_posting_constructs_with_unknown_optional_values() -> None:
    job = JobPosting(
        job_id="job-001",
        job_title="Business Analyst",
        company="Example Co",
        description_raw="Looking for a BA with stakeholder management experience.",
        source_type="copied_text",
        source_ref=None,
        location=None,
        work_mode="unknown",
        employment_type=None,
        required_skills=["stakeholder management"],
        preferred_skills=[],
        required_years_experience=None,
        nice_to_have_years_experience=None,
        domain=None,
        notes=None,
        salary_min_gbp=None,
        salary_max_gbp=None,
    )

    assert job.location is None
    assert job.employment_type is None
    assert job.salary_min_gbp is None
    assert job.salary_max_gbp is None


def test_job_posting_rejects_invalid_salary_range() -> None:
    try:
        JobPosting(
            job_id="job-001",
            job_title="Business Analyst",
            company="Example Co",
            description_raw="Description",
            source_type="copied_text",
            source_ref=None,
            location="London",
            work_mode="hybrid",
            employment_type="full-time",
            required_skills=[],
            preferred_skills=[],
            required_years_experience=None,
            nice_to_have_years_experience=None,
            domain=None,
            notes=None,
            salary_min_gbp=60000,
            salary_max_gbp=50000,
        )
    except ValueError as exc:
        assert "salary_min_gbp" in str(exc)
    else:
        raise AssertionError("Expected invalid salary range to raise ValueError")


def test_job_analysis_keeps_confidence_separate_from_score_breakdown() -> None:
    breakdown = build_score_breakdown()
    analysis = JobAnalysis(
        job_id="job-001",
        match_score=78,
        score_breakdown=breakdown,
        blockers=[
            Blocker(
                code="salary_floor",
                label="Salary floor mismatch",
                reason="The role may be below salary expectations",
                severity="high",
            )
        ],
        strengths=["stakeholder management"],
        missing_required_skills=[],
        missing_preferred_skills=["SQL"],
        risk_flags=[
            RiskFlag(
                code="preferred-skill-gap",
                label="Preferred skill gap",
                reason="SQL is not currently evidenced",
            )
        ],
        decision="review",
        decision_reason="Strong core fit but needs a manual salary check",
        confidence="low",
        tailoring_ready=False,
        tailoring_notes="Wait for manual review before tailoring.",
    )

    assert analysis.match_score == 78
    assert analysis.confidence == "low"
    assert not hasattr(analysis.score_breakdown, "confidence")
    assert analysis.score_breakdown.skills_score.value == 32


def test_job_analysis_rejects_out_of_range_match_score() -> None:
    try:
        JobAnalysis(
            job_id="job-001",
            match_score=120,
            score_breakdown=build_score_breakdown(),
            decision_reason="Invalid score should fail",
        )
    except ValueError as exc:
        assert "match_score" in str(exc)
    else:
        raise AssertionError("Expected invalid match_score to raise ValueError")
