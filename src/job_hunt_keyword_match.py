"""Per-job ATS keyword match (feature F1).

Computes how well a CV covers a specific job's keywords (its `required_skills` /
`preferred_skills`), returning a 0–100 **match rate** plus present/missing
breakdowns and an anti-stuffing signal. Deterministic, local, no LLM.

This is distinct from `job_hunt_ats_scorer.score_cv` (ATS *parse-friendliness*):
this answers "does the CV cover *this job's* keywords?". See
`docs/tasks/f1-ats-match-rate-design.md`.

Design notes:
- **Edge-aware boundaries** so punctuation keywords (`C#`, `C++`, `.NET`,
  `Node.js`, `CI/CD`) match as whole tokens while `R` ≠ `React`, `BA` ≠ `database`.
- **Canonical key** = casefold + whitespace-collapse; **required wins** if a
  keyword is in both lists (counted once, suppressed from preferred).
- **Null contract:** no keywords *or* no CV → `match_rate = None` (never 100).
- Advisory only: callers must NOT feed `match_rate` into the apply/skip decision.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_STUFFING_THRESHOLD = 4  # a keyword repeated more than this many times is "overused"


@dataclass(frozen=True)
class KeywordMatchResult:
    match_rate: int | None = None          # 0–100; None when nothing to assess
    required_matched: list[str] = field(default_factory=list)
    required_missing: list[str] = field(default_factory=list)
    preferred_matched: list[str] = field(default_factory=list)
    preferred_missing: list[str] = field(default_factory=list)
    overused: list[str] = field(default_factory=list)


def _norm(value: str | None) -> str:
    """Lowercase + collapse internal whitespace (matches job_hunt_scoring._normalize_text)."""
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def _dedupe(keywords: list[str], *, seen: set[str]) -> list[str]:
    """Keep first-seen display casing; drop entries whose canonical key is already seen."""
    out: list[str] = []
    for kw in keywords:
        key = _norm(kw)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(kw)
    return out


def _boundary_pattern(keyword_norm: str) -> re.Pattern[str]:
    """Edge-aware whole-token matcher for a normalised keyword.

    A word boundary is required only on an edge whose character is alphanumeric, so
    `.NET` / `C#` / `C++` match even adjacent to their own punctuation, while `R`
    and `BA` still need alnum boundaries (so `React` / `database` don't match).
    """
    left = r"(?<![a-z0-9])" if keyword_norm[:1].isalnum() else ""
    right = r"(?![a-z0-9])" if keyword_norm[-1:].isalnum() else ""
    return re.compile(left + re.escape(keyword_norm) + right)


def _count(keyword_norm: str, cv_norm: str) -> int:
    if not keyword_norm:
        return 0
    return len(_boundary_pattern(keyword_norm).findall(cv_norm))


def compute_keyword_match(
    cv_text: str | None,
    required_skills: list[str],
    preferred_skills: list[str],
) -> KeywordMatchResult:
    # Dedupe within and across lists; required wins over preferred.
    seen: set[str] = set()
    required = _dedupe(list(required_skills or []), seen=seen)
    preferred = _dedupe(list(preferred_skills or []), seen=seen)

    total = len(required) + len(preferred)

    # Null contract: nothing to assess (no keywords) or no CV to assess against.
    if total == 0 or not (cv_text and cv_text.strip()):
        return KeywordMatchResult(
            match_rate=None,
            required_matched=[],
            required_missing=list(required),
            preferred_matched=[],
            preferred_missing=list(preferred),
            overused=[],
        )

    cv_norm = _norm(cv_text)

    req_matched, req_missing = _split(required, cv_norm)
    pref_matched, pref_missing = _split(preferred, cv_norm)

    present = len(req_matched) + len(pref_matched)
    match_rate = round(100 * present / total)

    overused = [
        kw for kw in (required + preferred)
        if _count(_norm(kw), cv_norm) > _STUFFING_THRESHOLD
    ]

    return KeywordMatchResult(
        match_rate=match_rate,
        required_matched=req_matched,
        required_missing=req_missing,
        preferred_matched=pref_matched,
        preferred_missing=pref_missing,
        overused=overused,
    )


def _split(keywords: list[str], cv_norm: str) -> tuple[list[str], list[str]]:
    matched: list[str] = []
    missing: list[str] = []
    for kw in keywords:
        key = _norm(kw)
        if key and _boundary_pattern(key).search(cv_norm):
            matched.append(kw)
        else:
            missing.append(kw)
    return matched, missing


__all__ = ["KeywordMatchResult", "compute_keyword_match"]
