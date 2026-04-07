from src.models import Blocker, RiskFlag
from src.decision import decide_application


def test_blocker_overrides_score_and_forces_skip() -> None:
    result = decide_application(
        match_score=92,
        blockers=[
            Blocker(
                code="work_authorization",
                label="Work authorization",
                reason="Role requires sponsorship that is unavailable",
                severity="critical",
            )
        ],
    )

    assert result.decision == "skip"
    assert "blocker rules" in result.decision_reason
    assert "Work authorization" in result.decision_reason


def test_high_score_without_critical_risk_becomes_apply() -> None:
    result = decide_application(
        match_score=85,
        risk_flags=[
            RiskFlag(
                code="missing-preferred-skills",
                label="Preferred skill gap",
                reason="Power BI is not evidenced",
            )
        ],
    )

    assert result.decision == "apply"
    assert "apply threshold" in result.decision_reason


def test_high_score_with_critical_risk_becomes_review() -> None:
    result = decide_application(
        match_score=80,
        risk_flags=[
            RiskFlag(
                code="missing-required-skills",
                label="Required skill gap",
                reason="Power BI is required but not evidenced",
            )
        ],
    )

    assert result.decision == "review"
    assert "critical risks require review" in result.decision_reason


def test_high_score_with_salary_mismatch_becomes_review_by_default() -> None:
    result = decide_application(
        match_score=87.5,
        risk_flags=[
            RiskFlag(
                code="salary-below-floor",
                label="Salary below floor",
                reason="Known salary data appears below the candidate floor",
            )
        ],
    )

    assert result.decision == "review"
    assert "critical risks require review" in result.decision_reason


def test_midrange_score_becomes_review() -> None:
    result = decide_application(match_score=72)

    assert result.decision == "review"
    assert "needs manual review" in result.decision_reason


def test_low_score_becomes_skip() -> None:
    result = decide_application(match_score=64)

    assert result.decision == "skip"
    assert "below the review threshold" in result.decision_reason
