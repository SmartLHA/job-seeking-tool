"""Saved Searches — Daily Job Digest phase D1.

A *saved search* is a named, reusable job-search query (source + params) that the
daily digest pipeline (D3+) will run on a schedule. D1 only stores and manages
them — no auto-run yet.

Storage (design-council v6 decision 1): a ``saved_searches`` table inside the
existing ``<state_root>/job_hunt_index.db``. SQLite gives atomic writes and an
idempotent toggle (``UPDATE … SET enabled = NOT enabled``) for free — no
temp-file dance, no read-modify-write race, no directory scan, and no
"one corrupt file breaks the whole list" failure mode.

This module owns its table (``CREATE TABLE IF NOT EXISTS`` on every open), so D1
ships independently of the D2 schema migration.

``search_id`` is an opaque ``uuid4().hex`` (v6 decision 2) — collision-proof, so
two searches with the same ``name`` both save cleanly. No filesystem path is ever
built from ``search_id``, so there is no path-traversal vector; ``search_id`` is
still strictly validated on every operation as input hygiene.

Every public function takes ``state_root`` as a keyword-only argument.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.job_hunt_config import get_enabled_sources


# search_id allow-list: opaque tokens only. uuid4().hex matches; anything with a
# path separator, "..", whitespace, or odd characters is rejected before it
# reaches a query (input hygiene — not a path guard, since we never build a path).
_SEARCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9_-]+$")

_MAX_NAME_LEN = 200
_MAX_SOURCE_ID_LEN = 40
_MAX_PARAM_KEY_LEN = 60
_MAX_PARAM_VAL_LEN = 500
_MAX_PARAMS = 50

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS saved_searches (
    search_id      TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    params         TEXT NOT NULL,
    enabled        INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at     TEXT NOT NULL,
    last_run_at    TEXT,
    last_run_count INTEGER NOT NULL DEFAULT 0
);
"""


class SavedSearchError(ValueError):
    """Base class for saved-search validation/storage errors."""


class SavedSearchNotFound(SavedSearchError):
    """Raised when a search_id does not exist."""


@dataclass(frozen=True, slots=True)
class SavedSearch:
    search_id: str          # opaque uuid4().hex (NOT a slug)
    name: str               # user label, e.g. "BA roles, London"
    source_id: str          # "reed" | "adzuna" | ...  (lower-cased, registered source)
    params: dict[str, str]  # normalised search params
    enabled: bool           # False = skip in daily run
    created_at: str         # ISO datetime (UTC)
    last_run_at: str | None
    last_run_count: int      # new jobs found on last run


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #

def validate_search_id(search_id: Any) -> str:
    """Return the search_id if it is a well-formed opaque token, else raise.

    Applied on EVERY route (load / delete / toggle) as input hygiene so a
    malformed id is a clean 400 and never reaches a query.
    """
    if not isinstance(search_id, str) or not _SEARCH_ID_PATTERN.match(search_id):
        raise SavedSearchError(f"invalid search_id: {search_id!r}")
    return search_id


def _validate_name(name: Any) -> str:
    if not isinstance(name, str):
        raise SavedSearchError("name must be a string")
    cleaned = name.strip()
    if not cleaned:
        raise SavedSearchError("name must not be empty")
    if len(cleaned) > _MAX_NAME_LEN:
        raise SavedSearchError(f"name must be <= {_MAX_NAME_LEN} characters")
    return cleaned


def _validate_source_id(source_id: Any) -> str:
    if not isinstance(source_id, str):
        raise SavedSearchError("source_id must be a string")
    cleaned = source_id.strip().lower()
    if not cleaned:
        raise SavedSearchError("source_id must not be empty")
    if len(cleaned) > _MAX_SOURCE_ID_LEN:
        raise SavedSearchError(f"source_id must be <= {_MAX_SOURCE_ID_LEN} characters")
    if not _SOURCE_ID_PATTERN.match(cleaned):
        raise SavedSearchError("source_id contains invalid characters")
    enabled_sources = {source.lower() for source in get_enabled_sources()}
    if cleaned not in enabled_sources:
        raise SavedSearchError(f"source_id is not a registered/enabled source: {cleaned}")
    return cleaned


def _validate_params(params: Any) -> dict[str, str]:
    """Coerce params to a str->str mapping with per-field limits.

    Defensive copy (Codex: a frozen dataclass with a dict field is not truly
    immutable, so never alias the caller's dict).
    """
    if params is None:
        return {}
    if not isinstance(params, Mapping):
        raise SavedSearchError("params must be an object/mapping")
    if len(params) > _MAX_PARAMS:
        raise SavedSearchError(f"params must have <= {_MAX_PARAMS} keys")
    out: dict[str, str] = {}
    for key, value in params.items():
        if not isinstance(key, str) or not key.strip():
            raise SavedSearchError("param keys must be non-empty strings")
        if len(key) > _MAX_PARAM_KEY_LEN:
            raise SavedSearchError(f"param key too long: {key!r}")
        sval = "" if value is None else str(value)
        if len(sval) > _MAX_PARAM_VAL_LEN:
            raise SavedSearchError(f"param value too long for {key!r}")
        out[key] = sval
    return out


def validate_saved_search_fields(
    name: Any,
    source_id: Any,
    params: Any,
) -> tuple[str, str, dict[str, str]]:
    """Validate and normalize saved-search fields."""
    return (
        _validate_name(name),
        _validate_source_id(source_id),
        _validate_params(params),
    )


# --------------------------------------------------------------------------- #
# Storage plumbing
# --------------------------------------------------------------------------- #

def _db_path(state_root: str | Path) -> Path:
    return Path(state_root) / "job_hunt_index.db"


# Root cause of the flaky concurrent-create test (2026-09-21, 2 of 30 solo runs failed
# before this fix): on a fresh DB every thread ran `PRAGMA journal_mode=WAL` and
# `CREATE TABLE` at once. Switching the journal mode needs an exclusive lock and SQLite
# can return SQLITE_BUSY for it immediately, without consulting busy_timeout. So the
# setup is serialised in-process, skipped when the DB is already WAL, and retried
# briefly for cross-process contention.
_INIT_LOCK = threading.Lock()
_INIT_RETRY_SECONDS = 10.0


def _init_connection(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA busy_timeout=5000")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    if str(mode).lower() != "wal":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_TABLE_SQL)
    conn.commit()


def _connect(state_root: str | Path) -> sqlite3.Connection:
    db_path = _db_path(state_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        deadline = time.monotonic() + _INIT_RETRY_SECONDS
        delay = 0.01
        while True:
            try:
                with _INIT_LOCK:
                    _init_connection(conn)
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                if time.monotonic() >= deadline:
                    raise
                conn.rollback()
                time.sleep(delay)
                delay = min(delay * 2, 0.25)
    except Exception:
        conn.close()   # never leak a connection the caller never received
        raise
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_saved_search(row: sqlite3.Row) -> SavedSearch:
    try:
        params = json.loads(row["params"]) if row["params"] else {}
        if not isinstance(params, dict):
            params = {}
    except (json.JSONDecodeError, TypeError):
        params = {}
    return SavedSearch(
        search_id=row["search_id"],
        name=row["name"],
        source_id=row["source_id"],
        params={str(k): str(v) for k, v in params.items()},
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        last_run_at=row["last_run_at"],
        last_run_count=int(row["last_run_count"] or 0),
    )


# --------------------------------------------------------------------------- #
# Public CRUD API  (state_root keyword-only on every function)
# --------------------------------------------------------------------------- #

def create_saved_search(
    name: str,
    source_id: str,
    params: Mapping[str, Any] | None,
    *,
    state_root: str | Path,
) -> SavedSearch:
    """Create and persist a new saved search. Mints an opaque uuid4 id."""
    cleaned_name, cleaned_source_id, cleaned_params = validate_saved_search_fields(
        name, source_id, params
    )
    search = SavedSearch(
        search_id=uuid.uuid4().hex,
        name=cleaned_name,
        source_id=cleaned_source_id,
        params=cleaned_params,
        enabled=True,
        created_at=_now_iso(),
        last_run_at=None,
        last_run_count=0,
    )
    save_saved_search(search, state_root=state_root)
    return search


def save_saved_search(search: SavedSearch, *, state_root: str | Path) -> None:
    """Insert or replace a saved search by search_id (atomic)."""
    validate_search_id(search.search_id)
    cleaned_name, cleaned_source_id, cleaned_params = validate_saved_search_fields(
        search.name, search.source_id, search.params
    )
    conn = _connect(state_root)
    try:
        conn.execute(
            """
            INSERT INTO saved_searches
                (search_id, name, source_id, params, enabled, created_at,
                 last_run_at, last_run_count)
            VALUES
                (:search_id, :name, :source_id, :params, :enabled, :created_at,
                 :last_run_at, :last_run_count)
            ON CONFLICT(search_id) DO UPDATE SET
                name           = excluded.name,
                source_id      = excluded.source_id,
                params         = excluded.params,
                enabled        = excluded.enabled,
                created_at     = excluded.created_at,
                last_run_at    = excluded.last_run_at,
                last_run_count = excluded.last_run_count
            """,
            {
                "search_id": search.search_id,
                "name": cleaned_name,
                "source_id": cleaned_source_id,
                "params": json.dumps(cleaned_params),
                "enabled": 1 if search.enabled else 0,
                "created_at": search.created_at,
                "last_run_at": search.last_run_at,
                "last_run_count": int(search.last_run_count or 0),
            },
        )
        conn.commit()
    finally:
        conn.close()


def load_saved_search(search_id: str, *, state_root: str | Path) -> SavedSearch:
    """Load one saved search. Raises SavedSearchNotFound if absent."""
    validate_search_id(search_id)
    conn = _connect(state_root)
    try:
        row = conn.execute(
            "SELECT * FROM saved_searches WHERE search_id = ?", (search_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise SavedSearchNotFound(search_id)
    return _row_to_saved_search(row)


def list_saved_searches(*, state_root: str | Path) -> list[SavedSearch]:
    """All saved searches, newest first. A corrupt params blob never crashes the
    list — it degrades that one row to empty params."""
    conn = _connect(state_root)
    try:
        rows = conn.execute(
            "SELECT * FROM saved_searches ORDER BY created_at DESC, search_id ASC"
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_saved_search(r) for r in rows]


def delete_saved_search(search_id: str, *, state_root: str | Path) -> bool:
    """Delete a saved search. Returns True if a row was removed (idempotent:
    deleting an unknown id returns False, not an error)."""
    validate_search_id(search_id)
    conn = _connect(state_root)
    try:
        cur = conn.execute(
            "DELETE FROM saved_searches WHERE search_id = ?", (search_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def toggle_saved_search(search_id: str, *, state_root: str | Path) -> SavedSearch:
    """Flip enabled in a single atomic UPDATE, then return the new state.
    Raises SavedSearchNotFound if the id is unknown."""
    validate_search_id(search_id)
    conn = _connect(state_root)
    try:
        cur = conn.execute(
            "UPDATE saved_searches SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END "
            "WHERE search_id = ?",
            (search_id,),
        )
        if cur.rowcount == 0:
            raise SavedSearchNotFound(search_id)
        # Read inside the same (still-open) transaction so a concurrent delete
        # can't slip between commit and SELECT and hand us a None row (Codex HIGH).
        row = conn.execute(
            "SELECT * FROM saved_searches WHERE search_id = ?", (search_id,)
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    if row is None:                       # belt-and-braces: never crash on a race
        raise SavedSearchNotFound(search_id)
    return _row_to_saved_search(row)


def update_last_run(search_id: str, *, state_root: str | Path, count: int) -> None:
    """Record the result of a digest run (used from D3+). No-op on unknown id."""
    validate_search_id(search_id)
    conn = _connect(state_root)
    try:
        conn.execute(
            "UPDATE saved_searches SET last_run_at = ?, last_run_count = ? "
            "WHERE search_id = ?",
            (_now_iso(), int(count), search_id),
        )
        conn.commit()
    finally:
        conn.close()
