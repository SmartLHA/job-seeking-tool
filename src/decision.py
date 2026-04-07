from __future__ import annotations

from dataclasses import dataclass

from src.config import DEFAULT_DECISION_POLICY, DecisionPolicy
from src.models import Blocker, Decision, RiskFlag


@dataclass(frozen=True, slots=True)
class DecisionResult:
    decision: Decision
    decision_reason: str


def decide_application(
    match_score: float,
    blockers: list[Blocker] | None = None,
    risk_flags: list[RiskFlag] | None = None,
    policy: DecisionPolicy = DEFAULT_DECISION_POLICY,
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
        return DecisionResult(
            decision="apply",
            decision_reason=(
                f"Score {match_score:.0f} meets the apply threshold and no critical risks were found"
            ),
        )

    if policy.review_threshold <= match_score < policy.apply_threshold:
        return DecisionResult(
            decision="review",
            decision_reason=(
                f"Score {match_score:.0f} is promising but still needs manual review"
            ),
        )

    if critical_risks:
        return DecisionResult(
            decision="review",
            decision_reason=_build_critical_risk_reason(match_score, critical_risks),
        )

    return DecisionResult(
        decision="skip",
        decision_reason=f"Score {match_score:.0f} is below the review threshold",
    )


def _build_blocker_reason(blockers: list[Blocker]) -> str:
    labels = ", ".join(blocker.label for blocker in blockers)
    return f"Skipped because blocker rules were triggered: {labels}"


def _build_critical_risk_reason(match_score: float, critical_risks: list[RiskFlag]) -> str:
    labels = ", ".join(flag.label for flag in critical_risks)
    return (
        f"Score {match_score:.0f} would otherwise qualify for apply, but critical risks require review: {labels}"
    )
