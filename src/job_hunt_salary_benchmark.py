"""Salary benchmark helpers (Feature B, 2026-09-22; revision 2, market-aware salary).

`clean_job_title` / `summarise_histogram` stay pure and advisory-only, feeding
nothing but the salary-benchmark panel. `classify_market_position` and the STICKY
market snapshot it builds are also pure/advisory by default. Only when a human
explicitly saves a snapshot (POST /job/{id}/market-position) AND the opt-in
`market_score_effect_enabled()` switch in job_hunt_config.py is turned on does a
fixed -5 apply — see `apply_market_score_effect`. Both stay OFF unless a human acts.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from src.job_hunt_config import (
    MARKET_ANNUAL_SALARY_FLOOR,
    MARKET_EXCLUDED_EMPLOYMENT_TYPES,
    MARKET_MIN_BUCKETS,
    MARKET_MIN_SAMPLE_TOTAL,
    MARKET_POSITION_BOTTOM_PERCENTILE,
    MARKET_POSITION_TOP_PERCENTILE,
    market_score_effect_enabled,
)

_MAX_QUERY_CHARS = 80

_PAREN_RE = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
# Trailing company / location separators: " - X", " | X", " @ X", " at X", ", X"
_SPLIT_RE = re.compile(r"\s+[-–—|@]\s+|\s+at\s+|,\s*|\s*/\s*(?=\s)", re.IGNORECASE)
_NOISE_RE = re.compile(
    r"\b(?:contract|contractor|permanent|perm|temporary|temp|"
    r"fixed[- ]term|ftc|part[- ]time|full[- ]time|remote|hybrid|"
    r"(?:inside|outside)\s+ir35|ir35|per\s+(?:day|annum|hour|year))\b\.?",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(r"[£$]\s?\d[\d,.]*\s?[kK]?(?:\s*(?:-|to)\s*[£$]?\s?\d[\d,.]*\s?[kK]?)?")


def clean_job_title(title: str | None) -> str:
    """Reduce a job title to a plain role query for the Adzuna histogram `what` parameter."""
    original = " ".join((title or "").split())
    text = _PAREN_RE.sub(" ", original)
    text = _MONEY_RE.sub(" ", text)
    text = _SPLIT_RE.split(text, maxsplit=1)[0]
    text = _NOISE_RE.sub(" ", text)
    text = re.sub(r"[^\w\s+#&./]", " ", text)
    text = " ".join(text.split())
    if not text:
        text = " ".join(re.sub(r"[^\w\s+#&./]", " ", original).split())
    return text[:_MAX_QUERY_CHARS].strip()


def _normalise_buckets(buckets: Any) -> list[tuple[int, int]]:
    items: Iterable[Any]
    items = buckets.items() if isinstance(buckets, Mapping) else (buckets or [])
    out: list[tuple[int, int]] = []
    for pair in items:
        try:
            lo, n = pair
            lo_i, n_i = int(float(lo)), int(float(n))
        except (TypeError, ValueError):
            continue
        if n_i > 0:
            out.append((lo_i, n_i))
    out.sort()
    return out


def _percentile(value: float | None, buckets: list[tuple[int, int]], total: int) -> float | None:
    """Share (0-100) of vacancies advertised below `value`, interpolating inside a bucket.

    Bucket upper bound = next bucket's lower bound; the last bucket reuses the previous
    bucket's width (a lone bucket has no width, so a value inside it counts as half).
    """
    if value is None or total <= 0:
        return None
    below = 0.0
    for i, (lo, n) in enumerate(buckets):
        if i + 1 < len(buckets):
            hi = buckets[i + 1][0]
        elif i > 0:
            hi = lo + (lo - buckets[i - 1][0])
        else:
            hi = lo
        if value >= hi and hi > lo:
            below += n
        elif value >= lo:
            frac = (value - lo) / (hi - lo) if hi > lo else 0.5
            below += n * min(frac, 1.0)
            break
        else:
            break
    return round(100.0 * below / total, 1)


def summarise_histogram(buckets: Any, job_salary: float | None, floor: float | None) -> dict[str, Any]:
    """Median bucket, total sample and percentile rank of a job salary / salary floor."""
    norm = _normalise_buckets(buckets)
    total = sum(n for _, n in norm)
    if total <= 0:
        return {"total": 0, "median_bucket_lower": None, "median_bucket_upper": None,
                "job_percentile": None, "floor_percentile": None}
    running = 0
    median_i = len(norm) - 1
    for i, (_, n) in enumerate(norm):
        running += n
        if running * 2 >= total:
            median_i = i
            break
    upper = norm[median_i + 1][0] if median_i + 1 < len(norm) else None
    return {
        "total": total,
        "median_bucket_lower": norm[median_i][0],
        "median_bucket_upper": upper,
        "job_percentile": _percentile(job_salary, norm, total),
        "floor_percentile": _percentile(floor, norm, total),
    }


# ── Market position (revision 2, 2026-09-22) ─────────────────────────────────
# Pure classification. Callers decide whether/when to persist the result — this
# function never reads or writes storage, cache, or the network.

def _annual_salary_used(job_salary_min: Any, job_salary_max: Any) -> float | None:
    """Midpoint of min/max, but ONLY when both are present and look like an annual
    figure (>= MARKET_ANNUAL_SALARY_FLOOR). A day/hourly rate, or a single-sided
    salary, is not "clearly annual" so it is treated the same as no salary."""
    try:
        lo = float(job_salary_min) if job_salary_min is not None else None
        hi = float(job_salary_max) if job_salary_max is not None else None
    except (TypeError, ValueError):
        return None
    if lo is None or hi is None:
        return None
    if lo < MARKET_ANNUAL_SALARY_FLOOR or hi < MARKET_ANNUAL_SALARY_FLOOR:
        return None
    return (lo + hi) / 2.0


def _excludes_employment_type(employment_type: str | None) -> bool:
    if not employment_type:
        return False
    token = str(employment_type).strip().lower().replace(" ", "_").replace("-", "_")
    return token in MARKET_EXCLUDED_EMPLOYMENT_TYPES


def _unknown_position(reason: str, *, sample_total: int | None = None, salary_used: float | None = None) -> dict[str, Any]:
    return {
        "position": "unknown",
        "percentile": None,
        "sample_total": sample_total,
        "salary_used": salary_used,
        "reason": reason,
    }


def classify_market_position(
    job_salary_min: Any,
    job_salary_max: Any,
    histogram_summary: Mapping[str, Any] | None,
    *,
    employment_type: str | None = None,
) -> dict[str, Any]:
    """Classify a job's salary against an Adzuna histogram for the same role query.

    ``histogram_summary`` is the dict form of a ``SalaryHistogramResult`` (has
    ``buckets``/``total``) for this job's cleaned title — NOT the ``summarise_histogram``
    output. Returns {"position": "bottom"|"typical"|"top"|"unknown", "percentile",
    "sample_total", "salary_used", "reason"} — ``reason`` explains an "unknown"
    result and is None otherwise. Pure: never touches storage/cache/network.
    """
    if _excludes_employment_type(employment_type):
        return _unknown_position("employment type is not clearly a full annual salary (contract/temp/part-time)")

    salary_used = _annual_salary_used(job_salary_min, job_salary_max)
    if salary_used is None:
        if job_salary_min is None and job_salary_max is None:
            return _unknown_position("no salary was recorded for this job")
        return _unknown_position("salary is not clearly an annual figure (looks like a day/hourly rate, or only one bound is known)")

    if not isinstance(histogram_summary, Mapping):
        return _unknown_position("no histogram data available", salary_used=salary_used)

    buckets = _normalise_buckets(histogram_summary.get("buckets"))
    total = sum(n for _, n in buckets)
    if total < MARKET_MIN_SAMPLE_TOTAL:
        return _unknown_position(
            f"sample size ({total}) is below the minimum of {MARKET_MIN_SAMPLE_TOTAL} vacancies",
            sample_total=total, salary_used=salary_used,
        )
    if len(buckets) < MARKET_MIN_BUCKETS:
        return _unknown_position(
            f"histogram has fewer than {MARKET_MIN_BUCKETS} salary buckets",
            sample_total=total, salary_used=salary_used,
        )

    percentile = _percentile(salary_used, buckets, total)
    if percentile is None:
        return _unknown_position("could not compute a percentile", sample_total=total, salary_used=salary_used)

    if percentile < MARKET_POSITION_BOTTOM_PERCENTILE:
        position = "bottom"
    elif percentile > MARKET_POSITION_TOP_PERCENTILE:
        position = "top"
    else:
        position = "typical"

    return {
        "position": position,
        "percentile": percentile,
        "sample_total": total,
        "salary_used": salary_used,
        "reason": None,
    }


def build_market_snapshot(
    job_salary_min: Any,
    job_salary_max: Any,
    histogram_payload: Mapping[str, Any] | None,
    *,
    employment_type: str | None = None,
    query: str = "",
) -> dict[str, Any]:
    """Build the full STICKY snapshot dict for storage on ``JobAnalysis.market_snapshot``.

    Only ever called from the explicit "Save market position" route — never from a
    pipeline/re-evaluation path. ``histogram_payload`` is a fresh ``SalaryHistogramResult
    .to_dict()`` for this job's cleaned title (read from cache only, see
    adzuna_client.read_cached_salary_histogram).
    """
    classification = classify_market_position(
        job_salary_min, job_salary_max, histogram_payload, employment_type=employment_type,
    )
    payload = histogram_payload or {}
    return {
        "position": classification["position"],
        "percentile": classification["percentile"],
        "sample_total": classification["sample_total"],
        "histogram_date": payload.get("fetched_at"),
        "query": query or payload.get("what") or "",
        "salary_used": classification["salary_used"],
        "reason": classification["reason"],
        "source": "adzuna",
        "version": 1,
    }


_POSITION_LABELS = {"bottom": "bottom quarter", "typical": "typical range", "top": "top quartile"}


def market_badge_text(snapshot: Mapping[str, Any] | None) -> str | None:
    """Badge text for a STICKY snapshot, or None when there is nothing to show
    (no snapshot, or position is "unknown")."""
    if not isinstance(snapshot, Mapping):
        return None
    position = snapshot.get("position")
    label = _POSITION_LABELS.get(position)
    if label is None:
        return None
    n = snapshot.get("sample_total")
    date = str(snapshot.get("histogram_date") or "")[:10] or "unknown date"
    n_text = f"n={n}" if n is not None else "n=?"
    return f"Market: {label} ({n_text}, as of {date}, Adzuna)"


def market_adjustment_reason(snapshot: Mapping[str, Any]) -> str:
    """The single audit-trail line for the optional -5 score effect. Shared by the
    scoring helper (stored in score_breakdown.notes) and the UI (rendered as-is),
    so the two never drift apart."""
    n = snapshot.get("sample_total")
    date = str(snapshot.get("histogram_date") or "")[:10] or "unknown date"
    n_text = f"n={n}" if n is not None else "n=?"
    return f"Market adjustment: −5 (bottom quarter of market, Adzuna {n_text}, date {date})"


MARKET_SCORE_ADJUSTMENT = -5.0


def apply_market_score_effect(
    match_score: float,
    market_snapshot: Mapping[str, Any] | None,
) -> tuple[float, float | None, str | None]:
    """Apply the OPTIONAL, OFF-by-default market-position score effect.

    Called ONCE, after the caller's own score_job() clamp to [0, 100], using ONLY the
    already-stored ``market_snapshot`` (never the network or cache). When enabled AND
    the snapshot's position is "bottom": deducts a fixed absolute 5 points, floored at
    0. Returns (adjusted_score, market_adjustment, reason) — the last two are None
    when the effect does not apply (switch off, no snapshot, or position != bottom).
    """
    if not market_score_effect_enabled():
        return match_score, None, None
    if not isinstance(market_snapshot, Mapping) or market_snapshot.get("position") != "bottom":
        return match_score, None, None
    adjusted = max(0.0, match_score + MARKET_SCORE_ADJUSTMENT)
    return round(adjusted, 2), MARKET_SCORE_ADJUSTMENT, market_adjustment_reason(market_snapshot)
