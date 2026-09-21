"""Local lexical relevance filter (Slice A, 2026-07-21 search/score/filter
plan: docs/tasks/2026-07-21-search-score-filter-plan.md).

Buckets fetched jobs into (matches, other) by comparing the search query
against each job's TITLE using a role-family rule: tokens are normalised
(punctuation stripped, a coarse suffix-stem collapses common grammatical/
derivational variants of one role word — e.g. analyst/analysts/analysis/
analyses all stem to "analy"), and a small acronym is derived from the
query's OWN significant words (e.g. "Business Analysis" -> "ba") so common
role abbreviations are recognised without a hardcoded, growable alias table.

Title is the primary signal; the description is checked only as a weak,
stricter (unstemmed, exact-word) secondary signal when the title alone does
not match. This never hard-drops a job — every job ends up in either the
`matches` or `other` bucket for the UI to render (main results vs a
collapsed "Other results" section).
"""
from __future__ import annotations

import re

# Generic stopwords + search-boilerplate words to ignore when deriving role
# terms from a query. Deliberately small and generic (not a role-alias list).
_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "in", "on", "at", "to", "with",
    "role", "roles", "job", "jobs", "position", "positions", "vacancy", "vacancies",
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split into alphanumeric tokens."""
    return _WORD_RE.findall((text or "").lower())


def _stem(token: str) -> str:
    """Coarse suffix-stem so grammatical/derivational variants of one role
    word collapse together (e.g. analyst/analysts/analysis/analyses ->
    'analy'; manager/managing/management -> 'manag'). Short tokens (<=4
    chars — including abbreviations like 'ba') are returned unchanged so
    they match exactly rather than being over-truncated."""
    if len(token) <= 4:
        return token
    return token[:5]


def _derive_role_terms(query: str) -> set[str]:
    """Derive the 'strong role term' set for a query: stemmed content words
    plus an acronym built from the initials of the query's own significant
    words (so "Business Analysis" yields the term "ba" without a hardcoded
    alias table)."""
    tokens = [t for t in _tokenize(query) if t and t not in _STOPWORDS]
    terms = {_stem(t) for t in tokens}
    if len(tokens) >= 2:
        acronym = "".join(t[0] for t in tokens if t)
        if acronym:
            terms.add(acronym)
    return terms


def is_relevant_title(title: str, query: str) -> bool:
    """True if `title` shares at least one strong role term with `query`.

    An empty/blank query means "no filter requested": everything is treated
    as relevant."""
    if not (query or "").strip():
        return True
    query_terms = _derive_role_terms(query)
    if not query_terms:
        return True
    title_tokens = [t for t in _tokenize(title) if t not in _STOPWORDS]
    title_terms = {_stem(t) for t in title_tokens} | set(title_tokens)
    return bool(query_terms & title_terms)


def is_relevant_description(description: str, query: str) -> bool:
    """Weak secondary signal: True if a FULL (unstemmed) content word of the
    query appears in the description. Deliberately stricter than the title
    check (exact-token match, no stemming) since description text is noisy
    and should not aggressively rescue a title mismatch."""
    if not (query or "").strip():
        return True
    tokens = [t for t in _tokenize(query) if t not in _STOPWORDS]
    if not tokens:
        return True
    desc_tokens = set(_tokenize(description))
    return any(t in desc_tokens for t in tokens)


def bucket_jobs_by_relevance(jobs: list[dict], query: str) -> tuple[list[dict], list[dict]]:
    """Split `jobs` into (matches, other) against `query`.

    Title is the primary signal; if the title doesn't match, the description
    is checked as a weak secondary signal before a job is bucketed into
    `other`. Never drops a job outright — every job ends up in one of the
    two returned lists, for the UI to render matches as main results and
    `other` as a collapsed "Other results" section."""
    matches: list[dict] = []
    other: list[dict] = []
    for job in jobs:
        title = job.get("title") or ""
        if is_relevant_title(title, query):
            matches.append(job)
            continue
        description = (
            job.get("description")
            or job.get("description_raw")
            or job.get("description_preview")
            or ""
        )
        if is_relevant_description(description, query):
            matches.append(job)
        else:
            other.append(job)
    return matches, other
