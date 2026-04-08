from src.models import CandidateProfile, JobPosting
from src.scoring import score_job


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


def test_score_job_rewards_strong_core_fit() -> None:
    result = score_job(build_candidate(), build_job())

    assert result.match_score == 100.0
    assert result.confidence == "high"
    assert result.missing_required_skills == []
    assert result.missing_preferred_skills == ["Power BI"]
    assert "SQL" in result.strengths
    assert result.score_breakdown.skills_score.value == 41.0
    assert result.score_breakdown.experience_score.value == 20.0


def test_score_job_treats_preferred_skills_as_soft_boosts() -> None:
    result = score_job(
        build_candidate(),
        build_job(preferred_skills=["Power BI", "Tableau"]),
    )

    assert result.match_score == 98.5
    assert result.missing_required_skills == []
    assert result.missing_preferred_skills == ["Power BI", "Tableau"]
    assert any(flag.code == "missing-preferred-skills" for flag in result.risk_flags)
    assert not any(flag.code == "missing-required-skills" for flag in result.risk_flags)


def test_unknown_job_data_lowers_confidence_before_score() -> None:
    rich_job = build_job()
    sparse_job = build_job(
        required_skills=[],
        required_years_experience=None,
        location=None,
        work_mode="unknown",
        salary_min_gbp=None,
        salary_max_gbp=None,
        domain=None,
    )

    rich_result = score_job(build_candidate(), rich_job)
    sparse_result = score_job(build_candidate(), sparse_job)

    assert rich_result.confidence == "high"
    assert sparse_result.confidence == "low"
    assert sparse_result.match_score == 51.5
    assert sparse_result.match_score > 0
    assert any("did not include explicit required skills" in note for note in sparse_result.notes)
    assert sparse_result.score_breakdown.experience_score.value == 20.0
    assert sparse_result.score_breakdown.salary_score.value == 10.0


def test_missing_required_skills_create_material_penalty() -> None:
    result = score_job(
        build_candidate(),
        build_job(required_skills=["stakeholder management", "Power BI"]),
    )

    assert result.match_score == 80.0
    assert result.missing_required_skills == ["Power BI"]
    assert any(flag.code == "missing-required-skills" for flag in result.risk_flags)
    assert any("Missing required skills reduce fit materially." in note for note in result.notes)


def test_required_skill_scoring_differentiates_full_matches() -> None:
    candidate = build_candidate()

    one_of_one = score_job(candidate, build_job(required_skills=["stakeholder management"], preferred_skills=[]))
    two_of_two = score_job(
        candidate,
        build_job(required_skills=["stakeholder management", "process mapping"], preferred_skills=[]),
    )
    three_of_three = score_job(
        candidate,
        build_job(required_skills=["stakeholder management", "process mapping", "sql"], preferred_skills=[]),
    )
    one_of_two = score_job(candidate, build_job(required_skills=["stakeholder management", "Power BI"], preferred_skills=[]))

    assert one_of_one.score_breakdown.skills_score.value == 35.0
    assert two_of_two.score_breakdown.skills_score.value == 38.5
    assert three_of_three.score_breakdown.skills_score.value == 42.0
    assert one_of_two.score_breakdown.skills_score.value == 17.5


def test_remote_only_preference_penalises_non_remote_roles() -> None:
    candidate = build_candidate()
    candidate.remote_preference = "remote_only"

    result = score_job(candidate, build_job(work_mode="onsite", location="London"))

    assert result.score_breakdown.work_mode_score.value == 0.0
    assert result.match_score == 91.0
    assert result.confidence == "high"


def test_low_salary_adds_review_risk_flag_without_needing_policy_hardcoding_in_scoring() -> None:
    result = score_job(
        build_candidate(),
        build_job(salary_min_gbp=45000, salary_max_gbp=48000),
    )

    assert result.score_breakdown.salary_score.value == 0.0
    assert any(flag.code == "salary-below-floor" for flag in result.risk_flags)
    assert any("below the candidate floor" in note for note in result.notes)
