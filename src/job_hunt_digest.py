"""Daily Job Digest — read model and seen-state mutations (phase D2, §6.2).

Reads the digest feed out of the SQLite ``jobs`` index (rows with a non-NULL
``digest_date``) and toggles the per-job ``digest_seen`` flag. Scoring and
ingestion live in the D3 pipeline; this module only queries and marks.

``DigestEntry.url`` is read from ``jobs.apply_url`` (the apply/advert/display URL),
never from ``source_ref`` (legacy metadata only).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.job_hunt_index import open_db
from src.ui_utils import format_salary_range


@dataclass(frozen=True, slots=True)
class DigestEntry:
    job_id: str
    title: str
    company: str
    match_score: int
    decision: str
    source_id: str
    saved_search_id: str | None
    digest_date: str
    seen: bool
    salary_display: str | None
    location: str | None
    url: str | None          # read from jobs.apply_url
    llm_status: str | None    # NULL | pending | processing | done | failed | skipped


def _row_to_entry(row: Any) -> DigestEntry:
    d = dict(row)
    salary_min = d.get("salary_min")
    salary_max = d.get("salary_max")
    salary_display = (
        format_salary_range(salary_min, salary_max)
        if (salary_min is not None or salary_max is not None)
        else None
    )
    score = d.get("match_score")
    return DigestEntry(
        job_id=d["job_id"],
        title=d.get("job_title") or "",
        company=d.get("company") or "",
        match_score=int(score) if score is not None else 0,
        decision=d.get("decision") or "",
        source_id=d.get("source") or "",
        saved_search_id=d.get("saved_search_id"),
        digest_date=d.get("digest_date") or "",
        seen=bool(d.get("digest_seen")),
        salary_display=salary_display,
        location=d.get("location"),
        url=d.get("apply_url"),          # NOT source_ref
        llm_status=d.get("llm_status"),
    )


def _digest_filter_clauses(
    *, date, source_id, saved_search_id, seen, min_score,
) -> tuple[list[str], list[Any]]:
    """Build the SQL-level WHERE for the digest feed. All values parameter-bound.

    ``seen``: None = all, False = unseen only, True = seen only.
    ``match_score`` NULL is treated as 0; ``min_score=0`` returns all digest
    rows including unscored, ``min_score>=1`` excludes unscored.
    """
    clauses = ["digest_date IS NOT NULL"]
    params: list[Any] = []
    if date is not None:
        clauses.append("digest_date = ?")
        params.append(date)
    if source_id:
        clauses.append("source = ?")
        params.append(source_id.lower())
    if saved_search_id:
        clauses.append("saved_search_id = ?")
        params.append(saved_search_id)
    if seen is True:
        clauses.append("COALESCE(digest_seen, 0) = 1")
    elif seen is False:
        clauses.append("COALESCE(digest_seen, 0) = 0")
    if min_score:
        clauses.append("COALESCE(match_score, 0) >= ?")
        params.append(min_score)
    return clauses, params


def query_digest(
    *,
    db_path: Path,
    date: str | None = None,
    unseen_only: bool = False,
    seen: bool | None = None,
    source_id: str | None = None,
    saved_search_id: str | None = None,
    min_score: int = 0,
    limit: int = 100,
) -> list[DigestEntry]:
    """Digest feed: digest rows only, highest match first.

    Filters (all SQL-level, parameter-bound): exact ``date`` (ISO), ``source_id``,
    ``saved_search_id``, ``min_score``, and seen state. ``match_score`` NULL is
    treated as 0; ``min_score=0`` returns all digest rows including unscored,
    ``min_score>=1`` excludes unscored. ``seen`` (None/True/False) is the general
    control; ``unseen_only=True`` is kept as a back-compat alias for ``seen=False``.
    """
    if unseen_only and seen is None:
        seen = False
    clauses, params = _digest_filter_clauses(
        date=date, source_id=source_id, saved_search_id=saved_search_id,
        seen=seen, min_score=min_score,
    )
    where = " AND ".join(clauses)
    # A negative LIMIT means "unbounded" in SQLite, so a bad caller value would
    # dump the whole table — clamp it to a safe empty result instead.
    safe_limit = int(limit)
    if safe_limit < 0:
        safe_limit = 0
    params.append(safe_limit)

    conn = open_db(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM jobs WHERE {where} "
            f"ORDER BY match_score DESC, digest_date DESC, job_id DESC LIMIT ?",
            params,
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_entry(r) for r in rows]


_MARK_SEEN_CHUNK = 500   # well under SQLite's bound-variable limit (999/32766)


def mark_seen(job_ids: list[str], *, db_path: Path) -> int:
    """Mark the given job_ids seen. Returns the number of rows updated.

    De-duplicates and chunks the IN(...) list so a large batch can't hit
    ``too many SQL variables`` (Codex MED)."""
    ids = list(dict.fromkeys(j for j in (job_ids or []) if j))   # dedup, keep order
    if not ids:
        return 0
    total = 0
    conn = open_db(db_path)
    try:
        for start in range(0, len(ids), _MARK_SEEN_CHUNK):
            chunk = ids[start:start + _MARK_SEEN_CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            cur = conn.execute(
                f"UPDATE jobs SET digest_seen = 1 "
                f"WHERE job_id IN ({placeholders}) AND digest_date IS NOT NULL",
                chunk,
            )
            total += cur.rowcount
        conn.commit()
        return total
    finally:
        conn.close()


def mark_all_seen(
    *,
    db_path: Path,
    date: str | None = None,
    source_id: str | None = None,
    saved_search_id: str | None = None,
) -> int:
    """Mark unseen digest rows seen, scoped to the SAME filters the feed is showing
    (Codex: an unfiltered "mark all" while the user has a filter applied would mark
    unrelated entries). Always restricted to currently-unseen rows."""
    clauses, params = _digest_filter_clauses(
        date=date, source_id=source_id, saved_search_id=saved_search_id,
        seen=False, min_score=0,
    )
    conn = open_db(db_path)
    try:
        cur = conn.execute(
            f"UPDATE jobs SET digest_seen = 1 WHERE {' AND '.join(clauses)}", params
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def unseen_count(*, db_path: Path) -> int:
    """Count of unseen digest rows — drives the sidebar badge."""
    conn = open_db(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs "
            "WHERE digest_date IS NOT NULL AND COALESCE(digest_seen, 0) = 0"
        ).fetchone()
        return int(row["n"]) if row else 0
    finally:
        conn.close()


def digest_stats(*, db_path: Path) -> dict[str, int]:
    """Aggregate counts for the digest page / status endpoints."""
    conn = open_db(db_path)
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE digest_date IS NOT NULL"
        ).fetchone()["n"]
        unseen = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs "
            "WHERE digest_date IS NOT NULL AND COALESCE(digest_seen, 0) = 0"
        ).fetchone()["n"]
    finally:
        conn.close()
    return {"total": int(total), "unseen": int(unseen), "seen": int(total) - int(unseen)}
