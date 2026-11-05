from __future__ import annotations

import math
from dataclasses import dataclass

from src.job_hunt_config import DEFAULT_DECISION_POLICY, DecisionPolicy
from src.job_hunt_models import Blocker, ConfidenceLevel, Decision, RiskFlag


def format_score(match_score: float) -> str:
    """Single display rule for a match score: truncate, never round up.

    Truncation means a displayed score never crosses a decision threshold the
    real score has not reached (79.6 shows as 79, not 80). Used by decision
    reasons and the review queue so both show the same number.
    """
    return str(int(math.floor(match_score)))


@dataclass(frozen=True, slots=True)
class DecisionResult:
    decision: Decision
    decision_reason: str


def decide_application(
    match_score: float,
    blockers: list[Blocker] | None = None,
    risk_flags: list[RiskFlag] | None = None,
    policy: DecisionPolicy = DEFAULT_DECISION_POLICY,
    confidence: ConfidenceLevel = "high",
) -> DecisionResult:
    blockers = blockers or []
    risk_flags = risk_flags or []

    if blockers:
        return DecisionResult(
            decision="skip",
            decision_reason=_build_blocker_reason(blockers),
        )

    critical_risks = [flag for flag in risk_flags if flag.code in policy.critical_risk_codes]
    if match_score >= policy.apply_threshold and not critical_risks:
        # MT-3: a low-confidence score reflects incomplete job data (e.g. no
        # required skills listed). Never auto-recommend "apply" on thin data —
        # route to manual review so a human confirms before applying.
        if confidence == "low":
            return DecisionResult(
                decision="review",
                decision_reason=(
                    f"Score {format_score(match_score)} meets the apply threshold, but confidence is low "
                    f"due to incomplete job data — routed to review instead of apply"
                ),
            )
        return DecisionResult(
            decision="apply",
            decision_reason=(
                f"Score {format_score(match_score)} meets the apply threshold and no critical risks were found"
            ),
        )

    if policy.review_threshold <= match_score < policy.apply_threshold:
        if critical_risks:
            labels = ", ".join(flag.label for flag in critical_risks)
            return DecisionResult(
                decision="review",
                decision_reason=(
                    f"Score {format_score(match_score)} is in the review band and critical risks "
                    f"need checking: {labels}"
                ),
            )
        return DecisionResult(
            decision="review",
            decision_reason=(
                f"Score {format_score(match_score)} is promising but still needs manual review"
            ),
        )

    if critical_risks:
        return DecisionResult(
            decision="review",
            decision_reason=_build_critical_risk_reason(match_score, critical_risks, policy),
        )

    return DecisionResult(
        decision="skip",
        decision_reason=f"Score {format_score(match_score)} is below the review threshold",
    )


def _build_blocker_reason(blockers: list[Blocker]) -> str:
    labels = ", ".join(blocker.label for blocker in blockers)
    return f"Skipped because blocker rules were triggered: {labels}"


def _build_critical_risk_reason(
    match_score: float,
    critical_risks: list[RiskFlag],
    policy: DecisionPolicy = DEFAULT_DECISION_POLICY,
) -> str:
    labels = ", ".join(flag.label for flag in critical_risks)
    if match_score >= policy.apply_threshold:
        return (
            f"Score {format_score(match_score)} would otherwise qualify for apply, "
            f"but critical risks require review: {labels}"
        )
    return (
        f"Score {format_score(match_score)} is below the review threshold, "
        f"but critical risks require manual review: {labels}"
    )

__all__ = ["DecisionResult", "decide_application", "format_score"]
