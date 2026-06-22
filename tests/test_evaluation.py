import dataclasses

from src.job_hunt_evaluation import evaluate_reviewed_job
from src.job_hunt_models import Blocker, CandidateProfile, JobPosting, Skill


def build_candidate() -> CandidateProfile:
    return CandidateProfile(
        candidate_id="cand-001",
        name="Mic",
        target_roles=["Business Analyst"],
        locations=["London", "Manchester"],
        remote_preference="remote_friendly",
        salary_floor_gbp=50000,
        right_to_work_uk=True,
        skills=[Skill(name="Stakeholder Management"), Skill(name="Process Mapping"), Skill(name="SQL"), Skill(name="Agile")],
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

    # MT-3: neutral scoring lifts the fit score (86.5), confidence stays low, and
    # the low-confidence gate routes the sparse job to manual review — it is never
    # auto-"apply" on thin data, and no longer wrongly auto-"skip" either.
    assert analysis.match_score == 86.5
    assert analysis.confidence == "low"
    assert analysis.decision == "review"
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


def test_source_quality_none_applies_no_gate() -> None:
    analysis = evaluate_reviewed_job(
        build_candidate(),
        build_job(source_quality_score=None),
    )

    assert analysis.decision == "apply"
    assert not any(b.code == "low-source-quality" for b in analysis.blockers)
    assert not any(f.code in ("low-source-quality", "marginal-source-quality") for f in analysis.risk_flags)


def test_source_quality_below_skip_threshold_produces_skip() -> None:
    analysis = evaluate_reviewed_job(
        build_candidate(),
        build_job(source_quality_score=30),
    )

    assert analysis.decision == "skip"
    assert any(b.code == "low-source-quality" for b in analysis.blockers)


def test_source_quality_marginal_forces_review() -> None:
    analysis = evaluate_reviewed_job(
        build_candidate(),
        build_job(source_quality_score=55),
    )

    assert analysis.decision == "review"
    assert any(f.code == "marginal-source-quality" for f in analysis.risk_flags)
    assert not any(b.code == "low-source-quality" for b in analysis.blockers)


def test_source_quality_above_threshold_has_no_effect() -> None:
    analysis = evaluate_reviewed_job(
        build_candidate(),
        build_job(source_quality_score=80),
    )

    assert analysis.decision == "apply"
    assert not any(b.code == "low-source-quality" for b in analysis.blockers)
    assert not any(f.code == "marginal-source-quality" for f in analysis.risk_flags)


def test_ats_score_populated_when_cv_present() -> None:
    candidate = build_candidate()
    candidate = dataclasses.replace(
        candidate,
        master_cv_text="Summary\n\nExperience\n\nSkills\n\nstakeholder management process mapping SQL Agile " * 10,
    )
    analysis = evaluate_reviewed_job(candidate, build_job())
    assert isinstance(analysis.ats_score, int)
    assert 0 <= analysis.ats_score <= 100
    # ATS score must not affect the match score or decision
    assert analysis.match_score == 100.0
    assert analysis.decision == "apply"


def test_ats_score_none_when_cv_absent() -> None:
    analysis = evaluate_reviewed_job(build_candidate(), build_job())
    assert analysis.ats_score is None


def test_evaluate_reviewed_job_sets_user_decision_to_none() -> None:
    analysis = evaluate_reviewed_job(build_candidate(), build_job())
    assert analysis.user_decision is None
    assert analysis.user_decision_note is None


def test_evaluate_populates_keyword_match_with_cv_and_none_without() -> None:
    # F1: keyword_match_rate is populated when a master CV is present, None otherwise,
    # and it does NOT change the decision (advisory only).
    profile = dataclasses.replace(
        build_candidate(),
        master_cv_text="Business analyst experienced in SQL and Python, plus Tableau dashboards.",
    )
    profile_no_cv = dataclasses.replace(profile, master_cv_text=None, master_cv_ref=None)
    job = build_job(required_skills=["SQL", "Python"], preferred_skills=["Tableau"])

    with_cv = evaluate_reviewed_job(profile, job)
    without_cv = evaluate_reviewed_job(profile_no_cv, job)

    assert with_cv.keyword_match_rate is not None
    assert 0 <= with_cv.keyword_match_rate <= 100
    assert without_cv.keyword_match_rate is None
    # advisory only: removing the CV must not change the engine decision
    assert with_cv.decision == without_cv.decision
