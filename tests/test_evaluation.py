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


# ── Market-aware salary (2026-09-22, revision 2) ─────────────────────────────

_BOTTOM_SNAPSHOT = {
    "position": "bottom", "percentile": 12.5, "sample_total": 142,
    "histogram_date": "2026-09-20T10:00:00+00:00", "query": "business analyst",
    "salary_used": 47500.0, "reason": None, "source": "adzuna", "version": 1,
}
_TYPICAL_SNAPSHOT = {**_BOTTOM_SNAPSHOT, "position": "typical"}


def test_market_snapshot_carried_but_no_effect_when_switch_off() -> None:
    analysis = evaluate_reviewed_job(build_candidate(), build_job(), market_snapshot=_BOTTOM_SNAPSHOT)
    assert analysis.market_snapshot == _BOTTOM_SNAPSHOT
    assert analysis.market_adjustment is None
    assert analysis.match_score == 100.0        # unchanged golden value (switch OFF by default)
    assert analysis.decision == "apply"          # unchanged golden decision


def test_market_snapshot_none_when_no_prior_analysis() -> None:
    analysis = evaluate_reviewed_job(build_candidate(), build_job())
    assert analysis.market_snapshot is None and analysis.market_adjustment is None


def test_score_effect_switch_on_bottom_deducts_5_and_shifts_decision(monkeypatch) -> None:
    import src.job_hunt_config as config
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    analysis = evaluate_reviewed_job(build_candidate(), build_job(), market_snapshot=_BOTTOM_SNAPSHOT)
    assert analysis.match_score == 95.0          # 100 (raw, already clamped) - 5
    assert analysis.market_adjustment == -5.0
    assert analysis.decision == "apply"          # 95 still clears the apply threshold
    assert "Market adjustment" in " ".join(analysis.score_breakdown.notes)
    assert "Adzuna" in " ".join(analysis.score_breakdown.notes)
    # never folded into the salary component itself
    assert "market" not in analysis.score_breakdown.salary_score.reason.lower()


def test_score_effect_switch_on_typical_no_change(monkeypatch) -> None:
    import src.job_hunt_config as config
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    analysis = evaluate_reviewed_job(build_candidate(), build_job(), market_snapshot=_TYPICAL_SNAPSHOT)
    assert analysis.match_score == 100.0 and analysis.market_adjustment is None


def test_score_effect_grade_follows_adjusted_score_no_separate_cap(monkeypatch) -> None:
    """Grade must derive from the ALREADY-adjusted match_score/decision — no extra
    decision-grade cap layered on top (that would double-count the effect)."""
    import src.job_hunt_config as config
    from src.job_hunt_qualitative import derive_grade
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    off_analysis = evaluate_reviewed_job(build_candidate(), build_job(), market_snapshot=None)
    on_analysis = evaluate_reviewed_job(build_candidate(), build_job(), market_snapshot=_BOTTOM_SNAPSHOT)

    off_grade = derive_grade(off_analysis.match_score, None, effective_decision=off_analysis.decision,
                              has_blockers=False, confidence=off_analysis.confidence,
                              decision_reason=off_analysis.decision_reason)
    on_grade = derive_grade(on_analysis.match_score, None, effective_decision=on_analysis.decision,
                             has_blockers=False, confidence=on_analysis.confidence,
                             decision_reason=on_analysis.decision_reason)
    # Both scores (100 and 95) map to base grade "A" — the adjustment does not
    # move the grade here, which is the point: no separate grade cap is applied
    # on top of the score-derived grade, so nothing double-counts.
    assert off_grade["base_grade"] == on_grade["base_grade"] == "A"


def test_score_effect_never_enters_risk_flags_or_blockers(monkeypatch) -> None:
    import src.job_hunt_config as config
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    analysis = evaluate_reviewed_job(build_candidate(), build_job(), market_snapshot=_BOTTOM_SNAPSHOT)
    codes = " ".join(f.code for f in analysis.risk_flags).lower()
    assert "market" not in codes and "adzuna" not in codes
    assert analysis.blockers == []


def test_score_effect_fixed_5_independent_of_scoring_preset(monkeypatch) -> None:
    """The -5 is a FIXED absolute deduction, not a percentage or weight-scaled
    amount — it must be identical under every scoring preset even though the
    presets give the salary component a different weight (10 vs 25). Uses a
    partial-match fixture (not the fully-clamped 100 fixture above) so the two
    presets actually land on DIFFERENT off-scores — 72.5 (Balanced) vs 77.5
    (Salary-focused) — making "always -5" distinguishable from "some formula
    that happens to also give -5 on a clamped-to-100 case"."""
    import src.job_hunt_config as config
    from src.job_hunt_config import ScoringPolicy
    from src.job_hunt_scoring_presets import PRESET_BALANCED, PRESET_SALARY_FOCUSED, PRESET_WEIGHTS
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)

    # matches only 2 of 4 required skills (partial, non-bonus, non-clamped) so the
    # two presets' different weights show up in genuinely different off-scores.
    candidate = dataclasses.replace(
        build_candidate(),
        skills=[s for s in build_candidate().skills if s.name in ("Stakeholder Management", "Process Mapping")],
    )
    job = build_job(required_skills=["Stakeholder Management", "Process Mapping", "C", "D"],
                     preferred_skills=[], required_years_experience=None, domain=None)

    off_by_preset = {}
    on_by_preset = {}
    for preset_name in (PRESET_BALANCED, PRESET_SALARY_FOCUSED):
        policy = ScoringPolicy(weights=PRESET_WEIGHTS[preset_name])
        off_by_preset[preset_name] = evaluate_reviewed_job(
            candidate, job, scoring_policy=policy, market_snapshot=None,
        )
        on_by_preset[preset_name] = evaluate_reviewed_job(
            candidate, job, scoring_policy=policy, market_snapshot=_BOTTOM_SNAPSHOT,
        )

    # sanity: the two presets actually land on different off-scores for this
    # fixture (no clamp collapsing them to the same 100.0) — otherwise this test
    # could not distinguish "fixed -5" from "coincidentally always -5".
    balanced_off = off_by_preset[PRESET_BALANCED].match_score
    salary_focused_off = off_by_preset[PRESET_SALARY_FOCUSED].match_score
    assert balanced_off != salary_focused_off
    assert balanced_off < 100.0 and salary_focused_off < 100.0

    for preset_name in (PRESET_BALANCED, PRESET_SALARY_FOCUSED):
        off_score = off_by_preset[preset_name].match_score
        on_score = on_by_preset[preset_name].match_score
        on_analysis = on_by_preset[preset_name]
        # the deduction itself is always exactly -5, regardless of preset/weights
        assert on_analysis.market_adjustment == -5.0, preset_name
        assert on_score == max(0.0, off_score - 5.0), preset_name


def test_score_effect_applies_after_clamp_on_genuine_raw_over_100(monkeypatch) -> None:
    """build_candidate()/build_job() score a RAW (pre-clamp) weighted sum of 101.0
    under the Balanced preset (skills 41.0 + experience 20 + location 10 + salary 10
    + domain 10 + work_mode 10) — real scoring, not a synthetic 100.0 fed straight to
    the helper. Proves the -5 is applied to the CLAMPED 100, not the raw 101 (which
    would wrongly give 96 instead of the correct 95)."""
    import src.job_hunt_config as config
    from src.job_hunt_scoring import score_job

    raw_result = score_job(build_candidate(), build_job())
    sb = raw_result.score_breakdown
    raw_sum = (
        sb.skills_score.value + sb.experience_score.value + sb.location_score.value
        + sb.salary_score.value + sb.domain_score.value + sb.work_mode_score.value
    )
    assert raw_sum == 101.0          # genuine pre-clamp weighted sum, verified
    assert raw_result.match_score == 100.0  # score_job() already clamped it

    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    analysis = evaluate_reviewed_job(build_candidate(), build_job(), market_snapshot=_BOTTOM_SNAPSHOT)
    assert analysis.match_score == 95.0     # 100 (clamped) - 5, NOT 101 - 5 = 96
    assert analysis.market_adjustment == -5.0
