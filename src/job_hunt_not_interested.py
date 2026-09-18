"""Persistent "not interested" job store (search-flow UX, 2026-07).

Jobs the user hides on the search results page are recorded here and filtered
out of every future search page (initial render and "Next page" fetches).

Identity: primary key ``"{source}:{source_job_id}"``. Because some sources
(LinkedIn scrape) have unstable job ids, every row also stores a secondary
fingerprint ``sha1("{source}|{title}|{company}")`` (lowercased, whitespace-
squashed) and the filter matches on key OR fingerprint. Rows older than
``_RETENTION_DAYS`` are pruned opportunistically on write — job adverts expire
long before that, so pruning cannot resurface a live advert in practice.

Storage: shares ``job_hunt_index.db`` with the saved-searches layer (same WAL /
busy-timeout settings), so writes are atomic and safe across threads/tabs.
All public functions take ``state_root`` keyword-only, mirroring
``job_hunt_saved_searches``.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

_RETENTION_DAYS = 180
_MAX_TEXT = 300
_MAX_BATCH = 50
_SOURCE_RE = re.compile(r"^[a-z0-9_-]{1,32}$")

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS not_interested_jobs (
    key         TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    company     TEXT NOT NULL DEFAULT '',
    hidden_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_not_interested_fp
    ON not_interested_jobs (fingerprint);
"""


# --------------------------------------------------------------------------- #
# Identity helpers
# --------------------------------------------------------------------------- #

def _squash(value: Any) -> str:
    return " ".join(str(value or "").split())


def make_fingerprint(source: str, title: str, company: str) -> str:
    """Stable secondary identity: survives unstable source job ids."""
    basis = f"{_squash(source).lower()}|{_squash(title).lower()}|{_squash(company).lower()}"
    return "fp:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()


def make_key(source: str, source_job_id: str, title: str = "", company: str = "") -> str:
    """Primary key ``source:job_id``; falls back to the fingerprint when the
    source produced no job id (possible for scraped results)."""
    sjid = _squash(source_job_id)
    if sjid:
        return f"{_squash(source).lower()}:{sjid}"
    return make_fingerprint(source, title, company)


def _clean_entry(entry: Mapping[str, Any]) -> dict[str, str]:
    """Validate/normalise one client-submitted hide entry. Raises ValueError."""
    source = _squash(entry.get("source")).lower()
    if not _SOURCE_RE.match(source):
        raise ValueError("invalid source")
    title = _squash(entry.get("title"))[:_MAX_TEXT]
    company = _squash(entry.get("company"))[:_MAX_TEXT]
    sjid = _squash(entry.get("source_job_id"))[:_MAX_TEXT]
    if not (sjid or title or company):
        raise ValueError("entry has no identity fields")
    return {
        "key": make_key(source, sjid, title, company),
        "fingerprint": make_fingerprint(source, title, company),
        "source": source,
        "title": title,
        "company": company,
    }


# --------------------------------------------------------------------------- #
# Storage plumbing (mirrors job_hunt_saved_searches)
# --------------------------------------------------------------------------- #

def _db_path(state_root: str | Path) -> Path:
    return Path(state_root) / "job_hunt_index.db"


def _connect(state_root: str | Path) -> sqlite3.Connection:
    db_path = _db_path(state_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_TABLE_SQL)
        conn.commit()
    except Exception:
        conn.close()
        raise
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _prune(conn: sqlite3.Connection) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)).isoformat(
        timespec="seconds"
    )
    conn.execute("DELETE FROM not_interested_jobs WHERE hidden_at < ?", (cutoff,))


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def hide_jobs(entries: Iterable[Mapping[str, Any]], *, state_root: str | Path) -> dict[str, Any]:
    """Persist entries as not-interested. Idempotent: re-hiding an existing key
    is reported in ``already_hidden`` and does not refresh its timestamp.

    Returns ``{"keys": [...], "hidden": [...], "already_hidden": [...]}`` where
    ``keys`` is the per-entry key list (input order) the client should retain
    for undo."""
    cleaned = [_clean_entry(e) for e in list(entries)[:_MAX_BATCH]]
    if not cleaned:
        raise ValueError("no entries to hide")
    now = _now_iso()
    keys: list[str] = []
    hidden: list[str] = []
    already: list[str] = []
    conn = _connect(state_root)
    try:
        _prune(conn)
        for row in cleaned:
            keys.append(row["key"])
            cur = conn.execute(
                """
                INSERT INTO not_interested_jobs
                    (key, fingerprint, source, title, company, hidden_at)
                VALUES (:key, :fingerprint, :source, :title, :company, :hidden_at)
                ON CONFLICT(key) DO NOTHING
                """,
                {**row, "hidden_at": now},
            )
            (hidden if cur.rowcount else already).append(row["key"])
        conn.commit()
    finally:
        conn.close()
    return {"keys": keys, "hidden": hidden, "already_hidden": already}


def unhide_jobs(keys: Iterable[str], *, state_root: str | Path) -> int:
    """Delete rows by key (used by both undo-toast and the Hidden jobs
    overlay). Unknown keys are ignored. Returns rows removed."""
    wanted = [str(k)[: _MAX_TEXT + 40] for k in list(keys)[:_MAX_BATCH] if str(k).strip()]
    if not wanted:
        return 0
    conn = _connect(state_root)
    try:
        cur = conn.execute(
            f"DELETE FROM not_interested_jobs WHERE key IN ({','.join('?' * len(wanted))})",
            wanted,
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def list_hidden(*, state_root: str | Path, limit: int = 1000) -> list[dict[str, str]]:
    """All hidden jobs, newest first, for the Hidden jobs overlay."""
    conn = _connect(state_root)
    try:
        rows = conn.execute(
            "SELECT key, source, title, company, hidden_at FROM not_interested_jobs"
            " ORDER BY hidden_at DESC, key LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_hidden(*, state_root: str | Path) -> int:
    conn = _connect(state_root)
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM not_interested_jobs").fetchone()
        return int(row["n"])
    finally:
        conn.close()


def hidden_lookup(*, state_root: str | Path) -> tuple[frozenset[str], frozenset[str]]:
    """(keys, fingerprints) sets for fast filtering — one read per request."""
    conn = _connect(state_root)
    try:
        rows = conn.execute("SELECT key, fingerprint FROM not_interested_jobs").fetchall()
        return (
            frozenset(r["key"] for r in rows),
            frozenset(r["fingerprint"] for r in rows),
        )
    finally:
        conn.close()


def filter_results(
    results: list[dict[str, Any]], *, state_root: str | Path
) -> tuple[list[dict[str, Any]], int]:
    """Drop not-interested jobs from a source's UI result dicts.

    Matches on key (``source:source_job_id``) OR fingerprint, so unstable ids
    still filter. Returns ``(visible_results, hidden_count)``. Display-only:
    callers must keep paging math (skip / has_more) based on the RAW count."""
    if not results:
        return results, 0
    keys, fps = hidden_lookup(state_root=state_root)
    if not keys and not fps:
        return results, 0
    visible: list[dict[str, Any]] = []
    hidden_count = 0
    for result in results:
        source = str(result.get("source") or "")
        key = make_key(
            source,
            str(result.get("source_job_id") or ""),
            str(result.get("title") or ""),
            str(result.get("company") or ""),
        )
        fp = make_fingerprint(
            source, str(result.get("title") or ""), str(result.get("company") or "")
        )
        if key in keys or fp in fps:
            hidden_count += 1
        else:
            visible.append(result)
    return visible, hidden_count
