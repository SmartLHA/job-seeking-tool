"""Deterministic source-quality scoring for normalized job records."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


NORMAL_ANALYSIS_THRESHOLD = 70
REVIEW_GATE_THRESHOLD = 40
LIVE_CONFIDENCE_THRESHOLD = 70


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def calculate_completeness_score(job: dict[str, Any]) -> int:
    """Return deterministic 0-100 field completeness for a normalized job."""
    score = 0
    description = job.get("description") or ""

    if isinstance(description, str) and len(description.strip()) >= 800:
        score += 30
    if _has_value(job.get("company")):
        score += 20
    if (
        _has_value(job.get("salary"))
        or _has_value(job.get("salary_min"))
        or _has_value(job.get("salary_max"))
        or _has_value(job.get("salary_text"))
    ):
        score += 15
    if _has_value(job.get("location")):
        score += 15
    if _has_value(job.get("apply_url")):
        score += 10
    if _has_value(job.get("contract_type")) or _has_value(job.get("job_type")):
        score += 10

    return score


def calculate_confidence_score(job: dict[str, Any]) -> int:
    """Return confidence that the current record can support Apply decisions."""
    enrichment = job.get("browser_enrichment") or {}
    if enrichment.get("verified_from_live_page") is True:
        return max(0, min(100, int(enrichment.get("extraction_confidence", 0))))
    if enrichment.get("dry_run") is True and enrichment.get("attempted") is True:
        return 25
    return calculate_completeness_score(job)


def calculate_quality_score(job: dict[str, Any]) -> int:
    """Return the score used for analysis gating, capped by source confidence."""
    return min(calculate_completeness_score(job), calculate_confidence_score(job))


def quality_band(score: int) -> str:
    if score >= NORMAL_ANALYSIS_THRESHOLD:
        return "normal_analysis"
    if score >= REVIEW_GATE_THRESHOLD:
        return "review_gated"
    return "skip_manual_enrichment"


def apply_decision(score: int, confidence_score: int | None = None) -> str:
    if confidence_score is not None and confidence_score < LIVE_CONFIDENCE_THRESHOLD:
        return "review_required" if score >= REVIEW_GATE_THRESHOLD else "manual_enrichment_required"
    if score >= NORMAL_ANALYSIS_THRESHOLD:
        return "allowed"
    if score >= REVIEW_GATE_THRESHOLD:
        return "review_required"
    return "manual_enrichment_required"


def attach_source_quality(job: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with refreshed source_quality metadata."""
    updated = deepcopy(job)
    completeness_score = calculate_completeness_score(updated)
    confidence_score = calculate_confidence_score(updated)
    score = min(completeness_score, confidence_score)
    enrichment = updated.get("browser_enrichment") or {}
    decision = apply_decision(score, confidence_score)
    if enrichment.get("dry_run") is True and enrichment.get("attempted") is True:
        decision = "review_required"
    updated["source_quality"] = {
        "quality_score": score,
        "completeness_score": completeness_score,
        "confidence_score": confidence_score,
        "quality_band": quality_band(score),
        "analysis_allowed": score >= REVIEW_GATE_THRESHOLD,
        "apply_decision": decision,
    }
    return updated


# Backward-friendly alias for quick local experiments.
calculate_quality = calculate_quality_score
