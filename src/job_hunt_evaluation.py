from __future__ import annotations

from src.job_hunt_config import (
    DEFAULT_DECISION_POLICY,
    DEFAULT_SCORING_POLICY,
    DEFAULT_TAILORING_POLICY,
    SOURCE_QUALITY_REVIEW_THRESHOLD,
    SOURCE_QUALITY_SKIP_THRESHOLD,
    DecisionPolicy,
    ScoringPolicy,
    TailoringPolicy,
)
from src.job_hunt_ats_scorer import score_cv
from src.job_hunt_decision import decide_application
from src.job_hunt_keyword_match import compute_keyword_match
from src.job_hunt_models import Blocker, CandidateProfile, JobAnalysis, JobPosting, RiskFlag
from src.job_hunt_scoring import score_job


def _source_quality_blockers_and_flags(job: JobPosting) -> tuple[list[Blocker], list[RiskFlag]]:
    sq = job.source_quality_score
    if sq is None:
        return [], []
    if sq < SOURCE_QUALITY_SKIP_THRESHOLD:
        return [Blocker(
            code="low-source-quality",
            label="Low source quality",
            reason=f"Source quality score {sq}/100 is below the minimum threshold ({SOURCE_QUALITY_SKIP_THRESHOLD}). Job data may be incomplete or unreliable.",
            severity="high",
        )], []
    if sq < SOURCE_QUALITY_REVIEW_THRESHOLD:
        return [], [RiskFlag(
            code="marginal-source-quality",
            label="Marginal source quality",
            reason=f"Source quality score {sq}/100. Review the extracted job fields carefully before applying.",
        )]
    return [], []


# This module is intentionally small: it composes the existing scoring and
# decision layers into a single derived JobAnalysis object without collapsing
# their responsibilities into one mixed implementation.
def evaluate_reviewed_job(
    profile: CandidateProfile,
    job: JobPosting,
    *,
    blockers: list[Blocker] | None = None,
    scoring_policy: ScoringPolicy = DEFAULT_SCORING_POLICY,
    decision_policy: DecisionPolicy = DEFAULT_DECISION_POLICY,
    tailoring_policy: TailoringPolicy = DEFAULT_TAILORING_POLICY,
    review_selected_for_tailoring: bool = False,
) -> JobAnalysis:
    scoring_result = score_job(profile, job, policy=scoring_policy)
    blocker_list = list(blockers or [])
    sq_blockers, sq_flags = _source_quality_blockers_and_flags(job)
    blocker_list.extend(sq_blockers)
    combined_risk_flags = list(scoring_result.risk_flags) + sq_flags
    decision_result = decide_application(
        match_score=scoring_result.match_score,
        blockers=blocker_list,
        risk_flags=combined_risk_flags,
        policy=decision_policy,
        confidence=scoring_result.confidence,
    )

    tailoring_ready, tailoring_notes = _derive_tailoring_state(
        decision_result.decision,
        tailoring_policy=tailoring_policy,
        review_selected_for_tailoring=review_selected_for_tailoring,
    )

    ats_score = None
    if profile.master_cv_text:
        job_keywords = list(job.required_skills) + list(job.preferred_skills)
        ats_result = score_cv(profile.master_cv_text, job_keywords)
        ats_score = ats_result["overall"]

    # F1 — per-job ATS keyword match (advisory/display only; does NOT feed the
    # decision above). Uses the master CV when present; None otherwise.
    keyword_match = compute_keyword_match(
        profile.master_cv_text, list(job.required_skills), list(job.preferred_skills)
    )

    return JobAnalysis(
        job_id=job.job_id,
        match_score=scoring_result.match_score,
        score_breakdown=scoring_result.score_breakdown,
        blockers=blocker_list,
        strengths=scoring_result.strengths,
        missing_required_skills=scoring_result.missing_required_skills,
        missing_preferred_skills=scoring_result.missing_preferred_skills,
        risk_flags=combined_risk_flags,
        decision=decision_result.decision,
        decision_reason=decision_result.decision_reason,
        confidence=scoring_result.confidence,
        tailoring_ready=tailoring_ready,
        tailoring_notes=tailoring_notes,
        ats_score=ats_score,
        keyword_match_rate=keyword_match.match_rate,
        keywords_required_missing=keyword_match.required_missing,
        keywords_preferred_missing=keyword_match.preferred_missing,
        keywords_overused=keyword_match.overused,
        # F1 v2 — a (re-)evaluation always resets provenance to the master CV and
        # recaptures the baseline from the fresh master-CV rate.
        keyword_match_baseline_rate=keyword_match.match_rate,
        keyword_match_source="master",
    )


# Tailoring stays downstream of evaluation. For MVP, apply decisions are ready
# by default; review decisions need explicit manual selection later.
def _derive_tailoring_state(
    decision: str,
    *,
    tailoring_policy: TailoringPolicy,
    review_selected_for_tailoring: bool,
) -> tuple[bool, str]:
    if decision == "apply":
        return True, "Evaluation supports tailoring from approved profile and CV facts only."
    if decision == "review":
        if tailoring_policy.require_manual_selection_for_review and not review_selected_for_tailoring:
            return False, "Manual selection is required before tailoring a review decision."
        return True, "Review decision was manually selected for tailoring from approved profile and CV facts only."
    return False, "Skipped jobs are not tailoring-ready."
__all__ = ["evaluate_reviewed_job"]
