"""Salary benchmark helpers (Feature B, 2026-09-22): pure, advisory only.

Nothing here feeds scoring, decision or grade.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

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
