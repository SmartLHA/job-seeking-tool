"""Slice 1 (2026-10-19): decision boundaries, reason text, and one source of
truth for match-score thresholds (decision policy -> grades and queue colour).
Design: docs/tasks/2026-10-19-scoring-consistency-slice1.md
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.job_hunt_config import (
    DEFAULT_DECISION_POLICY,
    GRADE_B_THRESHOLD,
    GRADE_D_THRESHOLD,
    DecisionPolicy,
)
from src.job_hunt_decision import decide_application, format_score
from src.job_hunt_models import RiskFlag
from src.job_hunt_qualitative import derive_base_grade
from src.ui_render import ReviewQueueViewModel, score_tone
from src.ui_utils import format_score_display

APPLY = DEFAULT_DECISION_POLICY.apply_threshold
REVIEW = DEFAULT_DECISION_POLICY.review_threshold


def _critical(code: str = "missing-required-skills", label: str = "Required skill gap") -> RiskFlag:
    return RiskFlag(code=code, label=label, reason="test reason")


# --- exact decision boundaries -------------------------------------------
@pytest.mark.parametrize(
    "score,expected",
    [(80.0, "apply"), (79.99, "review"), (65.0, "review"), (64.99, "skip"), (100.0, "apply"), (0.0, "skip")],
)
def test_decision_boundaries(score: float, expected: str) -> None:
    assert decide_application(match_score=score).decision == expected


def test_default_thresholds_are_80_and_65() -> None:
    assert (APPLY, REVIEW) == (80.0, 65.0)


def test_low_confidence_at_apply_threshold_routes_to_review() -> None:
    result = decide_application(match_score=80.0, confidence="low")
    assert result.decision == "review"
    assert "confidence is low" in result.decision_reason


def test_medium_confidence_at_apply_threshold_still_applies() -> None:
    assert decide_application(match_score=80.0, confidence="medium").decision == "apply"


# --- critical-risk reason text by band -------------------------------------
def test_critical_risk_at_or_above_apply_threshold_says_would_qualify() -> None:
    result = decide_application(match_score=85, risk_flags=[_critical()])
    assert result.decision == "review"
    assert "would otherwise qualify for apply" in result.decision_reason
    assert "Required skill gap" in result.decision_reason


def test_critical_risk_in_review_band_mentions_the_risk() -> None:
    result = decide_application(match_score=70, risk_flags=[_critical()])
    assert result.decision == "review"
    assert "Required skill gap" in result.decision_reason
    assert "would otherwise qualify" not in result.decision_reason


def test_critical_risk_below_review_threshold_is_review_without_false_claim() -> None:
    result = decide_application(match_score=30, risk_flags=[_critical()])
    assert result.decision == "review"  # behaviour unchanged (product_spec.md)
    assert "would otherwise qualify" not in result.decision_reason
    assert "below the review threshold" in result.decision_reason
    assert "Required skill gap" in result.decision_reason


def test_marginal_source_quality_is_critical_in_default_policy_only() -> None:
    flag = _critical(code="marginal-source-quality", label="Marginal source")
    assert decide_application(match_score=90, risk_flags=[flag]).decision == "review"
    assert decide_application(match_score=90, risk_flags=[flag], policy=DecisionPolicy()).decision == "apply"


# --- one display rule for scores -------------------------------------------
@pytest.mark.parametrize("score,text", [(79.6, "79"), (79.99, "79"), (80.0, "80"), (64.5, "64"), (65.0, "65"), (0.0, "0")])
def test_format_score_truncates_so_display_never_crosses_a_threshold(score: float, text: str) -> None:
    assert format_score(score) == text


def test_reason_uses_same_display_rule_as_queue() -> None:
    result = decide_application(match_score=79.6)
    assert result.decision == "review"
    assert "Score 79 " in result.decision_reason


# --- grades follow the decision policy for A and C -------------------------
def test_grade_a_and_c_follow_decision_policy() -> None:
    assert derive_base_grade(APPLY) == "A"
    assert derive_base_grade(APPLY - 0.01) == "B"
    assert derive_base_grade(REVIEW) == "C"
    assert derive_base_grade(REVIEW - 0.01) == "D"


def test_grade_b_and_d_bands_are_config_constants() -> None:
    assert (GRADE_B_THRESHOLD, GRADE_D_THRESHOLD) == (72.0, 50.0)
    assert derive_base_grade(GRADE_B_THRESHOLD) == "B"
    assert derive_base_grade(GRADE_D_THRESHOLD) == "D"
    assert derive_base_grade(GRADE_D_THRESHOLD - 0.01) == "F"


# --- queue colour follows the decision policy ------------------------------
@pytest.mark.parametrize(
    "score,tone",
    [(80.0, "var(--apply)"), (79.99, "var(--review)"), (75.0, "var(--review)"),
     (65.0, "var(--review)"), (64.99, "var(--skip)"), (50.0, "var(--skip)"), (None, "var(--ink-faint)")],
)
def test_queue_score_tone_matches_decision_policy(score, tone) -> None:
    assert score_tone(score) == tone


@pytest.mark.parametrize("score", [0.0, 30.0, 64.99, 65.0, 72.0, 79.99, 80.0, 95.0])
def test_queue_tone_agrees_with_decision_without_risks(score: float) -> None:
    decision = decide_application(match_score=score).decision
    assert score_tone(score) == f"var(--{decision})"


# --- ui_render stays pure: thresholds come in via the view model -----------
def test_review_queue_view_model_defaults_match_decision_policy() -> None:
    vm = ReviewQueueViewModel(jobs=[], active_id="", ids_csv="")
    assert (vm.apply_threshold, vm.review_threshold) == (APPLY, REVIEW)


def test_score_tone_defaults_match_decision_policy() -> None:
    assert score_tone(APPLY) == "var(--apply)"
    assert score_tone(APPLY - 0.01) == "var(--review)"
    assert score_tone(REVIEW - 0.01) == "var(--skip)"


@pytest.mark.parametrize("score", [0.0, 0.5, 64.5, 64.99, 65.0, 79.6, 79.99, 80.0, 99.9, 100.0])
def test_ui_display_rule_matches_decision_reason_rule(score: float) -> None:
    assert format_score_display(score) == format_score(score)


def test_ui_render_has_no_module_level_domain_imports() -> None:
    # Module-level check; tests/test_ui_render_purity.py also checks
    # function-local imports (removed 2026-10-19).
    tree = ast.parse(Path("src/ui_render.py").read_text(encoding="utf-8"))
    imported = [
        node.module for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    ]
    assert not [m for m in imported if m.startswith("src.job_hunt_")], imported


# --- Slice 1b: digest_threshold label says what it does ----------------------
def test_digest_threshold_label_describes_ai_queue_not_feed_filter() -> None:
    from src.ui_render import ProfilePageViewModel, render_profile_page
    vm = ProfilePageViewModel(has_profile=True, name="Synthetic", target_roles=[], locations=[],
        remote_preference="hybrid", salary_floor_gbp=0, right_to_work_uk=True, skills=[],
        years_experience=0, industries=[], certifications=[], achievements=[],
        master_cv_ref="", master_cv_text="")
    html = render_profile_page(profile_id="synthetic", vm=vm, parsed_cv_text=None,
                               parsed_filename=None, errors={}, form_values=None)
    assert "AI analysis for jobs scoring ≥ (0–100)" in html
    assert "Show jobs scoring" not in html
