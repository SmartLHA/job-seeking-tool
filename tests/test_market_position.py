"""Market-aware salary, revision 2 (2026-09-22): classify_market_position + config.

Pure-function tests only. No network. Route/storage/UI tests live in
tests/test_market_position_route.py and tests/test_storage.py.
"""
from __future__ import annotations

import src.job_hunt_config as config
import src.job_hunt_salary_benchmark as smod
from src.job_hunt_salary_benchmark import (
    apply_market_score_effect,
    build_market_snapshot,
    classify_market_position,
    market_adjustment_reason,
    market_badge_text,
)

HIST_30_5 = {
    "what": "business analyst",
    "fetched_at": "2026-09-20T10:00:00+00:00",
    "buckets": [[10000, 6], [30000, 6], [50000, 6], [70000, 6], [90000, 6]],  # total 30, 5 buckets
}


def _hist(buckets, **extra):
    d = {"what": "business analyst", "fetched_at": "2026-09-20T10:00:00+00:00", "buckets": buckets}
    d.update(extra)
    return d


# ── classify_market_position: guards ─────────────────────────────────────────

def test_missing_salary_is_unknown():
    r = classify_market_position(None, None, HIST_30_5)
    assert r["position"] == "unknown" and r["salary_used"] is None
    assert "no salary" in r["reason"]


def test_day_rate_salary_is_unknown():
    r = classify_market_position(400, 550, HIST_30_5)
    assert r["position"] == "unknown"
    assert "day/hourly" in r["reason"]


def test_only_one_bound_known_is_unknown():
    r = classify_market_position(60000, None, HIST_30_5)
    assert r["position"] == "unknown"


def test_annual_range_uses_midpoint():
    r = classify_market_position(60000, 80000, HIST_30_5)
    assert r["salary_used"] == 70000.0
    assert r["position"] == "typical"  # 70000 is the 60th percentile of HIST_30_5


def test_sample_below_30_is_unknown():
    hist = _hist([[10000, 5], [30000, 5], [50000, 5], [70000, 5], [90000, 5]])  # total 25, 5 buckets
    r = classify_market_position(60000, 80000, hist)
    assert r["position"] == "unknown" and "sample size" in r["reason"]


def test_fewer_than_5_buckets_is_unknown():
    hist = _hist([[10000, 10], [30000, 10], [50000, 10], [70000, 10]])  # total 40, 4 buckets
    r = classify_market_position(60000, 80000, hist)
    assert r["position"] == "unknown" and "buckets" in r["reason"]


def test_no_histogram_data_is_unknown():
    r = classify_market_position(60000, 80000, None)
    assert r["position"] == "unknown"


def test_contract_employment_type_is_unknown_even_with_good_salary_and_histogram():
    r = classify_market_position(60000, 80000, HIST_30_5, employment_type="contract")
    assert r["position"] == "unknown"
    assert "employment type" in r["reason"]


def test_part_time_and_temp_employment_type_are_unknown():
    for et in ("part_time", "part-time", "temporary", "temp"):
        r = classify_market_position(60000, 80000, HIST_30_5, employment_type=et)
        assert r["position"] == "unknown", et


def test_permanent_and_full_time_are_not_excluded():
    for et in ("permanent", "full_time", None, ""):
        r = classify_market_position(60000, 80000, HIST_30_5, employment_type=et)
        assert r["position"] == "typical", et  # 70000 midpoint sits at the 60th percentile of HIST_30_5


# ── classify_market_position: percentile boundaries (24.9 / 25 / 75 / 75.1) ──
# The percentile computation itself is exercised elsewhere (test_adzuna_salary.py
# via summarise_histogram); here we isolate JUST the threshold branching by
# monkeypatching the internal percentile function.

def test_boundary_24_9_is_bottom(monkeypatch):
    monkeypatch.setattr(smod, "_percentile", lambda *a, **k: 24.9)
    r = classify_market_position(60000, 80000, HIST_30_5)
    assert r["position"] == "bottom"


def test_boundary_25_is_typical(monkeypatch):
    monkeypatch.setattr(smod, "_percentile", lambda *a, **k: 25.0)
    r = classify_market_position(60000, 80000, HIST_30_5)
    assert r["position"] == "typical"


def test_boundary_75_is_typical(monkeypatch):
    monkeypatch.setattr(smod, "_percentile", lambda *a, **k: 75.0)
    r = classify_market_position(60000, 80000, HIST_30_5)
    assert r["position"] == "typical"


def test_boundary_75_1_is_top(monkeypatch):
    monkeypatch.setattr(smod, "_percentile", lambda *a, **k: 75.1)
    r = classify_market_position(60000, 80000, HIST_30_5)
    assert r["position"] == "top"


# ── build_market_snapshot / market_badge_text / market_adjustment_reason ────

def test_build_market_snapshot_shape():
    snap = build_market_snapshot(20000, 25000, HIST_30_5, query="business analyst")
    assert snap["source"] == "adzuna" and snap["version"] == 1
    assert snap["histogram_date"] == HIST_30_5["fetched_at"]
    assert snap["query"] == "business analyst"
    assert set(snap) == {"position", "percentile", "sample_total", "histogram_date", "query",
                          "salary_used", "reason", "source", "version"}


def test_market_badge_text_none_for_unknown_or_missing():
    assert market_badge_text(None) is None
    assert market_badge_text({"position": "unknown"}) is None


def test_market_badge_text_for_bottom():
    snap = {"position": "bottom", "sample_total": 142, "histogram_date": "2026-09-20T10:00:00+00:00"}
    text = market_badge_text(snap)
    assert text == "Market: bottom quarter (n=142, as of 2026-09-20, Adzuna)"


# ── apply_market_score_effect: threshold crossings ───────────────────────────

BOTTOM_SNAPSHOT = {"position": "bottom", "sample_total": 100, "histogram_date": "2026-09-20T10:00:00+00:00"}
TYPICAL_SNAPSHOT = {"position": "typical", "sample_total": 100, "histogram_date": "2026-09-20T10:00:00+00:00"}


def test_switch_off_never_adjusts(monkeypatch):
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", False)
    score, adj, reason = apply_market_score_effect(90.0, BOTTOM_SNAPSHOT)
    assert score == 90.0 and adj is None and reason is None


def test_switch_on_no_snapshot_no_adjustment(monkeypatch):
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    score, adj, reason = apply_market_score_effect(90.0, None)
    assert score == 90.0 and adj is None and reason is None


def test_switch_on_typical_no_adjustment(monkeypatch):
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    score, adj, reason = apply_market_score_effect(90.0, TYPICAL_SNAPSHOT)
    assert score == 90.0 and adj is None and reason is None


def test_switch_on_bottom_deducts_5(monkeypatch):
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    score, adj, reason = apply_market_score_effect(90.0, BOTTOM_SNAPSHOT)
    assert score == 85.0 and adj == -5.0
    assert reason == "Market adjustment: −5 (bottom quarter of market, Adzuna n=100, date 2026-09-20)"


def test_switch_on_floors_at_zero(monkeypatch):
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    score, adj, reason = apply_market_score_effect(3.0, BOTTOM_SNAPSHOT)
    assert score == 0.0 and adj == -5.0


def test_switch_on_applies_after_raw_over_100_clamp(monkeypatch):
    # A caller that clamps raw>100 down to 100 before calling this helper — the
    # effect must still bite on the clamped value, not be a no-op above 100.
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    score, adj, reason = apply_market_score_effect(100.0, BOTTOM_SNAPSHOT)
    assert score == 95.0 and adj == -5.0


# Threshold-crossing table (documented in the task report): Apply(>=80)->Review
def test_crossing_apply_to_review_boundary(monkeypatch):
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    for raw in (80.0, 84.9):
        score, _, _ = apply_market_score_effect(raw, BOTTOM_SNAPSHOT)
        assert score < 80.0, raw


def test_crossing_review_to_skip_boundary(monkeypatch):
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    for raw in (65.0, 69.9):
        score, _, _ = apply_market_score_effect(raw, BOTTOM_SNAPSHOT)
        assert score < 65.0, raw


def test_crossing_digest_threshold_70_boundary(monkeypatch):
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    for raw in (70.0, 74.9):
        score, _, _ = apply_market_score_effect(raw, BOTTOM_SNAPSHOT)
        assert score < 70.0, raw


# ── config ────────────────────────────────────────────────────────────────────

def test_market_score_effect_enabled_default_false():
    assert config.market_score_effect_enabled() is False


def test_market_score_effect_enabled_reads_through_module_flag(monkeypatch):
    monkeypatch.setattr(config, "MARKET_SCORE_EFFECT", True)
    assert config.market_score_effect_enabled() is True
