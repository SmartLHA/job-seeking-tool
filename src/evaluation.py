from __future__ import annotations

from src.config import (
    DEFAULT_DECISION_POLICY,
    DEFAULT_SCORING_POLICY,
    DecisionPolicy,
    ScoringPolicy,
)
from src.decision import decide_application
from src.models import Blocker, CandidateProfile, JobAnalysis, JobPosting
from src.scoring import score_job


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
) -> JobAnalysis:
    scoring_result = score_job(profile, job, policy=scoring_policy)
    blocker_list = list(blockers or [])
    decision_result = decide_application(
        match_score=scoring_result.match_score,
        blockers=blocker_list,
        risk_flags=scoring_result.risk_flags,
        policy=decision_policy,
    )

    tailoring_ready, tailoring_notes = _derive_tailoring_state(decision_result.decision)

    return JobAnalysis(
        job_id=job.job_id,
        match_score=scoring_result.match_score,
        score_breakdown=scoring_result.score_breakdown,
        blockers=blocker_list,
        strengths=scoring_result.strengths,
        missing_required_skills=scoring_result.missing_required_skills,
        missing_preferred_skills=scoring_result.missing_preferred_skills,
        risk_flags=scoring_result.risk_flags,
        decision=decision_result.decision,
        decision_reason=decision_result.decision_reason,
        confidence=scoring_result.confidence,
        tailoring_ready=tailoring_ready,
        tailoring_notes=tailoring_notes,
    )


# Tailoring stays downstream of evaluation. For MVP, apply decisions are ready
# by default; review decisions need explicit manual selection later.
def _derive_tailoring_state(decision: str) -> tuple[bool, str]:
    if decision == "apply":
        return True, "Evaluation supports tailoring from approved profile and CV facts only."
    if decision == "review":
        return False, "Manual selection is required before tailoring a review decision."
    return False, "Skipped jobs are not tailoring-ready."
