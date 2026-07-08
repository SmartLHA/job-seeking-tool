from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT PRIMARY KEY,
    job_title       TEXT,
    company         TEXT,
    location        TEXT,
    source          TEXT,
    match_score     REAL,
    decision        TEXT,
    user_decision   TEXT,
    ats_score       INTEGER,
    tailoring_ready INTEGER,
    status          TEXT NOT NULL DEFAULT 'not_applied',
    updated_at      TEXT,
    salary_min      INTEGER,
    salary_max      INTEGER
);
"""

# Daily Digest D2 — ten new columns added by idempotent migration (never in the
# base CREATE so existing DBs upgrade in place). See backlog-01 design §3.1/§3.2.
_MIGRATION_COLUMNS: list[tuple[str, str]] = [
    ("source_job_id",       "TEXT"),                 # dedup key (with lower(source)); C1
    ("apply_url",           "TEXT"),                 # apply/advert URL — display only, NEVER dedup
    ("digest_date",         "TEXT"),                 # ISO date; NULL = not from a digest run
    ("digest_seen",         "INTEGER DEFAULT 0"),    # 0=new, 1=seen
    ("saved_search_id",     "TEXT"),                 # which SavedSearch found it
    ("llm_status",          "TEXT"),                 # NULL|pending|processing|done|failed|skipped
    ("llm_attempts",        "INTEGER DEFAULT 0"),
    ("llm_next_attempt_at", "TEXT"),                 # ISO datetime backoff gate; NULL = ready
    ("llm_claimed_at",      "TEXT"),                 # ISO datetime a worker claimed the row
    ("llm_claim_token",     "TEXT"),                 # per-claim UUID; only the claimer processes it
]

# Daily-digest indexes (§3.1a). Partial UNIQUE is the dedup invariant guard; the
# rest are query-path perf indexes. All IF NOT EXISTS so the migration is idempotent.
_INDEX_SQL: list[str] = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_source_source_job_id "
    "ON jobs(source, source_job_id) WHERE source_job_id IS NOT NULL AND source_job_id != ''",
    "CREATE INDEX IF NOT EXISTS idx_jobs_digest_unseen "
    "ON jobs(digest_date, digest_seen, match_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_llm_queue "
    "ON jobs(llm_status, llm_next_attempt_at, match_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_saved_search ON jobs(saved_search_id)",
]

# Atomic per-day RPD counter for the paced LLM worker (§14.5). SQLite, not JSON
# (v6 decision), so concurrent increments can't lose counts.
_LLM_RPD_SQL = (
    "CREATE TABLE IF NOT EXISTS llm_rpd (date TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0)"
)

_QUALITATIVE_INDEX_SQL = """
CREATE TABLE IF NOT EXISTS qualitative_index (
    job_ref          TEXT PRIMARY KEY,
    status           TEXT NOT NULL,
    grade            TEXT,
    culture_flag     TEXT,
    legitimacy_tier  TEXT,
    model            TEXT,
    prompt_version   TEXT,
    error_text       TEXT,
    created_at       TEXT
);
"""

_ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    "not_applied": ["applied", "withdrawn"],
    "applied":     ["interview", "rejected", "withdrawn"],
    "interview":   ["offer", "rejected", "withdrawn"],
    "offer":       ["applied", "rejected", "withdrawn"],
    "rejected":    [],
    "withdrawn":   [],
}

_ALL_STATUSES = ["not_applied", "applied", "interview", "offer", "rejected", "withdrawn"]


def open_db(db_path: Path) -> sqlite3.Connection:
    """Open/create the SQLite DB, run schema + idempotent migration, return a
    connection with a row factory.

    WAL + busy_timeout (C4) let the request threads and the future LLM worker
    write concurrently without ``database is locked``. WAL keeps `-wal`/`-shm`
    sidecar files next to the DB, so `data/state` must stay on local disk (never a
    synced/networked folder) — see backlog-01 design §3.1 (v6 decision 3).
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:  # pragma: no cover - pragma failure is non-fatal
        pass
    conn.executescript(_SCHEMA_SQL)
    _migrate_schema(conn)
    conn.commit()
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add any missing digest columns, the llm_rpd table, and the digest indexes.

    Idempotent: each ALTER runs only when its column is absent, and every index /
    table uses IF NOT EXISTS. Existing rows get NULL/defaults for the new columns
    (``digest_seen`` backfills to 0, not NULL — SQLite supplies the column default
    for pre-existing rows), which is safe and backward-compatible.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    for col_name, col_type in _MIGRATION_COLUMNS:
        if col_name not in existing:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError as exc:
                # Two threads can both see the column missing on first run and race
                # to ALTER; the loser hits "duplicate column name". The column now
                # exists either way, so swallow that and re-raise anything else.
                if "duplicate column name" not in str(exc).lower():
                    raise
    conn.execute(_LLM_RPD_SQL)
    conn.execute(_QUALITATIVE_INDEX_SQL)
    for stmt in _INDEX_SQL:
        conn.execute(stmt)
    conn.commit()


_UPSERT_SQL = """
    INSERT INTO jobs
        (job_id, job_title, company, location, source, source_job_id, apply_url,
         match_score, decision, user_decision, ats_score,
         tailoring_ready, status, updated_at, salary_min, salary_max)
    VALUES
        (:job_id, :job_title, :company, :location, :source, :source_job_id, :apply_url,
         :match_score, :decision, :user_decision, :ats_score,
         :tailoring_ready, :status, :updated_at, :salary_min, :salary_max)
    ON CONFLICT(job_id) DO UPDATE SET
        job_title       = excluded.job_title,
        company         = excluded.company,
        location        = excluded.location,
        source          = excluded.source,
        source_job_id   = excluded.source_job_id,
        apply_url       = excluded.apply_url,
        match_score     = excluded.match_score,
        decision        = excluded.decision,
        user_decision   = excluded.user_decision,
        ats_score       = excluded.ats_score,
        tailoring_ready = excluded.tailoring_ready,
        status          = excluded.status,
        updated_at      = excluded.updated_at,
        salary_min      = excluded.salary_min,
        salary_max      = excluded.salary_max
    -- Deliberately NOT in the SET list, so preserved unchanged on conflict (C6):
    --   digest_date, digest_seen, saved_search_id,
    --   llm_status, llm_attempts, llm_next_attempt_at, llm_claimed_at, llm_claim_token
"""


def _norm_source_job_id(value: Any) -> str | None:
    """Normalise a provider id to a stripped string (never parse as a number).

    TEXT affinity means int 12345678 and "12345678" collide correctly, but
    whitespace or a leading-zero id parsed as int would split/merge identities —
    so the boundary rule is str().strip(), blank → None (Codex High, v6 dec. 5).
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def upsert_job(db_path: Path, row: dict[str, Any]) -> None:
    """Upsert evaluation/status columns keyed on the canonical job_id.

    Uses ``ON CONFLICT(job_id) DO UPDATE`` so digest and LLM-queue columns are
    never clobbered on a re-index (the old ``INSERT OR REPLACE`` wiped them).
    ``source`` is lower-cased to match the ``lower(source) + source_job_id`` dedup
    rule. **No IntegrityError fallback (v6 decision 4):** because job_id is
    canonical, a ``(source, source_job_id)`` unique-index violation under a
    *different* job_id means the canonical-id logic drifted — fail loud and log it
    as a defect rather than silently patch a non-canonical row.
    """
    tailoring_raw = row.get("tailoring_ready")
    tailoring_int = None if tailoring_raw is None else (1 if tailoring_raw else 0)

    params = {
        "job_id": row.get("job_id"),
        "job_title": row.get("job_title"),
        "company": row.get("company"),
        "location": row.get("location"),
        "source": (row.get("source") or "").lower() or None,   # V2: lower-cased
        "source_job_id": _norm_source_job_id(row.get("source_job_id")),  # dedup key (C1)
        "apply_url": row.get("apply_url"),                     # display metadata only
        "match_score": row.get("match_score"),
        "decision": row.get("decision"),
        "user_decision": row.get("user_decision"),
        "ats_score": row.get("ats_score"),
        "tailoring_ready": tailoring_int,
        "status": row.get("status") or "not_applied",
        "updated_at": row.get("updated_at"),
        "salary_min": row.get("salary_min"),
        "salary_max": row.get("salary_max"),
    }

    conn = open_db(db_path)
    try:
        conn.execute(_UPSERT_SQL, params)
        conn.commit()
    except sqlite3.IntegrityError as exc:
        # Fail loud (v6 dec. 4): ON CONFLICT(job_id) absorbs the PK case, so the
        # most likely cause is a (source, source_job_id) collision under a different
        # job_id — a canonical-id bug, not a routine condition. Log the actual error
        # text rather than asserting which constraint fired.
        logger.error(
            "upsert_job: IntegrityError for job_id=%r source=%r source_job_id=%r "
            "(likely UNIQUE(source, source_job_id) — canonical job_id drift; not patched): %s",
            params["job_id"], params["source"], params["source_job_id"], exc,
        )
        raise
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a dict and add allowed_transitions."""
    d = dict(row)
    status = d.get("status") or "not_applied"
    d["allowed_transitions"] = _ALLOWED_TRANSITIONS.get(status, [])
    return d


def query_jobs_list(db_path: Path) -> list[dict[str, Any]]:
    """Return all job rows as list of dicts with allowed_transitions."""
    conn = open_db(db_path)
    try:
        rows = conn.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def query_board(db_path: Path) -> dict[str, Any]:
    """Return board grouped by status with stats."""
    conn = open_db(db_path)
    try:
        rows = conn.execute("SELECT * FROM jobs").fetchall()
    finally:
        conn.close()

    columns: dict[str, list[dict[str, Any]]] = {s: [] for s in _ALL_STATUSES}
    for row in rows:
        d = _row_to_dict(row)
        status = d.get("status") or "not_applied"
        if status in columns:
            columns[status].append(d)

    terminal = {"rejected", "withdrawn"}
    active = sum(len(v) for k, v in columns.items() if k not in terminal)
    interviews = len(columns["interview"])
    offers = len(columns["offer"])
    applied_count = len(columns["applied"])
    rejected_count = len(columns["rejected"])
    denominator = applied_count + interviews + offers + rejected_count
    response_rate = (interviews + offers) / denominator if denominator > 0 else 0.0

    return {
        "columns": columns,
        "stats": {
            "active": active,
            "interviews": interviews,
            "offers": offers,
            "response_rate": response_rate,
        },
    }


def rebuild_index(storage_layout: Any, db_path: Path) -> int:
    """Wipe and rebuild the SQLite index from JSON files. Never crashes on bad files."""
    from src.job_hunt_storage import (
        load_application_outcome,
        load_job_analysis,
        load_reviewed_job,
        StorageError,
    )

    conn = open_db(db_path)
    try:
        conn.execute("DELETE FROM jobs")
        conn.commit()
    finally:
        conn.close()

    # Collect known job_ids from all outcome files (outcomes are created for every saved job)
    outcomes_dir: Path = storage_layout.outcomes_dir
    reviewed_jobs_dir: Path = storage_layout.reviewed_jobs_dir

    # Union of job IDs from outcomes + reviewed_jobs dirs
    job_ids: set[str] = set()
    for p in outcomes_dir.glob("*.json"):
        job_ids.add(p.stem)
    for p in reviewed_jobs_dir.glob("*.json"):
        job_ids.add(p.stem)

    count = 0
    root = storage_layout.root

    for job_id in sorted(job_ids):
        try:
            # Load outcome -> status, updated_at
            try:
                outcome = load_application_outcome(job_id, root)
                status = outcome.status
                updated_at = outcome.updated_at
            except (FileNotFoundError, StorageError, Exception) as exc:
                logger.warning("rebuild_index: skipping outcome for %s: %s", job_id, exc)
                status = "not_applied"
                updated_at = None

            # Load reviewed_job -> title, company, location, source, salary
            try:
                reviewed_job = load_reviewed_job(job_id, root)
                job_title = reviewed_job.job_title
                company = reviewed_job.company
                location = reviewed_job.location
                source = reviewed_job.source_type
                salary_min = reviewed_job.salary_min_gbp
                salary_max = reviewed_job.salary_max_gbp
                source_job_id = reviewed_job.source_job_id            # dedup key (C1)
                apply_url = reviewed_job.url or reviewed_job.source_ref  # display metadata only
            except (FileNotFoundError, StorageError, Exception) as exc:
                logger.warning("rebuild_index: skipping reviewed_job for %s: %s", job_id, exc)
                job_title = None
                company = None
                location = None
                source = None
                salary_min = None
                salary_max = None
                source_job_id = None
                apply_url = None

            # Load analysis (may not exist)
            match_score = None
            decision = None
            user_decision = None
            ats_score = None
            tailoring_ready = None
            try:
                analysis = load_job_analysis(job_id, root)
                match_score = analysis.match_score
                decision = analysis.decision
                user_decision = analysis.user_decision
                ats_score = analysis.ats_score
                tailoring_ready = analysis.tailoring_ready
            except FileNotFoundError:
                pass  # analysis is optional
            except (StorageError, Exception) as exc:
                logger.warning("rebuild_index: skipping analysis for %s: %s", job_id, exc)

            upsert_job(db_path, {
                "job_id": job_id,
                "job_title": job_title,
                "company": company,
                "location": location,
                "source": source,
                "source_job_id": source_job_id,
                "apply_url": apply_url,
                "match_score": match_score,
                "decision": decision,
                "user_decision": user_decision,
                "ats_score": ats_score,
                "tailoring_ready": tailoring_ready,
                "status": status,
                "updated_at": updated_at,
                "salary_min": salary_min,
                "salary_max": salary_max,
            })
            count += 1

        except Exception as exc:
            logger.warning("rebuild_index: skipping job %s entirely: %s", job_id, exc)
            continue

    return count


# ===========================================================================
# Daily Digest D2 — dedup, digest metadata, and LLM-queue primitives
# ===========================================================================

def source_job_id_from_ui_result(result: dict[str, Any]) -> str:
    """Stable dedup id from a source UI result dict. Empty string = not dedupable
    (C2 — caller must skip/quarantine these before indexing)."""
    return str(result.get("source_job_id") or "").strip()


def apply_url_from_ui_result(result: dict[str, Any]) -> str:
    """Apply/advert link — metadata only, never a dedup key."""
    return str(result.get("url") or "").strip()


def is_already_indexed(db_path: Path, source_id: str, source_job_id: str) -> bool:
    """True if a job with this (lower(source), source_job_id) already exists.

    Dedup key is the STABLE provider id (C1), not the URL. Blank id → False
    (caller should have quarantined it, C2)."""
    sjid = (source_job_id or "").strip()
    if not sjid:
        return False
    conn = open_db(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE source = ? AND source_job_id = ? LIMIT 1",
            ((source_id or "").lower(), sjid),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def set_digest_meta(
    db_path: Path,
    job_id: str,
    *,
    digest_date: str,
    seen: bool = False,
    saved_search_id: str | None = None,
) -> None:
    """Write digest tracking columns for a job. Never touches eval/status columns."""
    conn = open_db(db_path)
    try:
        conn.execute(
            """
            UPDATE jobs
               SET digest_date     = :digest_date,
                   digest_seen     = :seen,
                   saved_search_id = :saved_search_id
             WHERE job_id = :job_id
            """,
            {
                "job_id": job_id,
                "digest_date": digest_date,
                "seen": 1 if seen else 0,
                "saved_search_id": saved_search_id,
            },
        )
        conn.commit()
    finally:
        conn.close()


_VALID_LLM_STATUS = {"pending", "done", "failed", "skipped"}


def set_llm_status(
    db_path: Path,
    job_id: str,
    status: str,
    *,
    attempts: int | None = None,
    next_attempt_at: str | None = None,
) -> None:
    """The only status-transition writer (§14.3b). ``processing`` is owned by
    ``claim_batch`` and is NOT a valid value here. Clears claim columns on every
    terminal/queued transition; ``done`` also clears the backoff gate."""
    if status not in _VALID_LLM_STATUS:
        raise ValueError(f"invalid llm_status: {status!r} (processing is set only by claim_batch)")

    sets = ["llm_status = :status", "llm_claimed_at = NULL", "llm_claim_token = NULL"]
    params: dict[str, Any] = {"job_id": job_id, "status": status}
    if status == "done":
        sets.append("llm_next_attempt_at = NULL")
    elif status == "pending" and next_attempt_at is not None:
        sets.append("llm_next_attempt_at = :next_attempt_at")
        params["next_attempt_at"] = next_attempt_at
    if attempts is not None:
        sets.append("llm_attempts = :attempts")
        params["attempts"] = int(attempts)

    conn = open_db(db_path)
    try:
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = :job_id", params)
        conn.commit()
    finally:
        conn.close()


def claim_batch(db_path: Path, *, limit: int, ready_before: str, now: str) -> list[sqlite3.Row]:
    """Token-based atomic claim (§14.3a, C4/item 5). Marks up to ``limit`` ready
    ``pending`` rows as ``processing`` in a single immediate transaction and
    returns ONLY the rows this call actually claimed (guards against racing
    claimers). LLM calls happen outside this transaction in the worker (D6)."""
    limit = int(limit)
    if limit < 1:
        return []   # negative LIMIT means "unbounded" in SQLite — never claim all
    token = str(uuid.uuid4())
    conn = open_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        ids = [r["job_id"] for r in conn.execute(
            """SELECT job_id FROM jobs
                WHERE llm_status = 'pending'
                  AND (llm_next_attempt_at IS NULL OR llm_next_attempt_at <= ?)
                ORDER BY match_score DESC LIMIT ?""",
            (ready_before, int(limit)),
        ).fetchall()]
        if ids:
            conn.executemany(
                """UPDATE jobs
                      SET llm_status = 'processing', llm_claimed_at = ?, llm_claim_token = ?
                    WHERE job_id = ? AND llm_status = 'pending'""",
                [(now, token, i) for i in ids],
            )
        claimed = conn.execute(
            """SELECT * FROM jobs
                WHERE llm_claim_token = ?
                  AND llm_status = 'processing'
                ORDER BY match_score DESC""",
            (token,),
        ).fetchall()
        conn.commit()
        return claimed
    except Exception:
        conn.rollback()   # don't leave the immediate write-lock dangling
        raise
    finally:
        conn.close()


def reset_stale_llm_processing(db_path: Path, *, now: datetime, older_than_minutes: int = 30) -> int:
    """Recover rows stuck in ``processing`` (worker crashed mid-call, item 6).
    Returns them to ``pending`` and clears the claim. Called on startup and at the
    top of each worker cycle."""
    cutoff = (now - timedelta(minutes=older_than_minutes)).isoformat(timespec="seconds")
    conn = open_db(db_path)
    try:
        cur = conn.execute(
            """UPDATE jobs
                  SET llm_status = 'pending', llm_claimed_at = NULL, llm_claim_token = NULL
                WHERE llm_status = 'processing'
                  AND (llm_claimed_at IS NULL OR llm_claimed_at <= ?)""",
            (cutoff,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def rpd_used_today(db_path: Path, date: str) -> int:
    """LLM calls already made on ``date`` (local ISO date). 0 when no row → lazy
    reset (yesterday's row simply isn't read)."""
    conn = open_db(db_path)
    try:
        row = conn.execute("SELECT count FROM llm_rpd WHERE date = ?", (date,)).fetchone()
        return int(row["count"]) if row else 0
    finally:
        conn.close()


def incr_rpd_counter(db_path: Path, date: str) -> int:
    """Atomically bump the per-day RPD counter and return the new count (§14.5).
    Reuses SQLite locking, so concurrent worker + manual-drain increments can't
    lose counts."""
    conn = open_db(db_path)
    try:
        conn.execute(
            "INSERT INTO llm_rpd(date, count) VALUES(?, 1) "
            "ON CONFLICT(date) DO UPDATE SET count = count + 1",
            (date,),
        )
        conn.commit()
        row = conn.execute("SELECT count FROM llm_rpd WHERE date = ?", (date,)).fetchone()
        return int(row["count"]) if row else 0
    finally:
        conn.close()


class LLMQuotaExhausted(RuntimeError):
    """Raised when no Gemini attempt can be reserved under the daily cap."""


def reserve_llm_rpd_attempt(db_path: Path, date: str, daily_cap: int | None = None) -> int:
    """Reserve one Gemini attempt before the HTTP call.

    Kept separate from ``incr_rpd_counter`` so existing digest success-accounting
    behavior is unchanged in slice 1; qualitative assessments call this before
    each attempt so failures still consume quota.
    """
    if daily_cap is None:
        return incr_rpd_counter(db_path, date)
    conn = open_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT count FROM llm_rpd WHERE date = ?", (date,)).fetchone()
        current = int(row["count"]) if row else 0
        if current >= daily_cap:
            conn.rollback()
            raise LLMQuotaExhausted("daily LLM quota exhausted - try tomorrow")
        conn.execute(
            "INSERT INTO llm_rpd(date, count) VALUES(?, 1) "
            "ON CONFLICT(date) DO UPDATE SET count = count + 1",
            (date,),
        )
        conn.commit()
        row = conn.execute("SELECT count FROM llm_rpd WHERE date = ?", (date,)).fetchone()
        return int(row["count"]) if row else current + 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_qualitative_assessment(
    db_path: Path,
    job_ref: str,
    *,
    now: str,
    force: bool = False,
    model: str | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    """Atomic qualitative assessment compare-and-set.

    Returns ``{"claimed": True, "row": row}`` only for the request that owns the
    Gemini call. Existing pending/running rows are returned as in-flight; done and
    error rows are returned unless ``force`` is requested. Force never overrides a
    running row.
    """
    conn = open_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM qualitative_index WHERE job_ref = ?",
            (job_ref,),
        ).fetchone()
        if existing is not None:
            status = existing["status"]
            if status in {"pending", "running"}:
                conn.commit()
                return {"claimed": False, "row": dict(existing), "in_flight": True}
            if not force:
                conn.commit()
                return {"claimed": False, "row": dict(existing), "in_flight": False}
            conn.execute(
                """UPDATE qualitative_index
                      SET status = 'running',
                          grade = NULL,
                          culture_flag = NULL,
                          legitimacy_tier = NULL,
                          model = ?,
                          prompt_version = ?,
                          error_text = NULL,
                          created_at = ?
                    WHERE job_ref = ?
                      AND status NOT IN ('pending', 'running')""",
                (model, prompt_version, now, job_ref),
            )
        else:
            conn.execute(
                """INSERT INTO qualitative_index
                    (job_ref, status, grade, culture_flag, legitimacy_tier,
                     model, prompt_version, error_text, created_at)
                   VALUES (?, 'running', NULL, NULL, NULL, ?, ?, NULL, ?)""",
                (job_ref, model, prompt_version, now),
            )
        row = conn.execute(
            "SELECT * FROM qualitative_index WHERE job_ref = ?",
            (job_ref,),
        ).fetchone()
        conn.commit()
        return {"claimed": True, "row": dict(row), "in_flight": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finish_qualitative_assessment(
    db_path: Path,
    job_ref: str,
    *,
    status: str,
    legitimacy_tier: str | None = None,
    culture_flag: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    error_text: str | None = None,
) -> None:
    if status not in {"done", "error"}:
        raise ValueError(f"invalid qualitative status: {status!r}")
    conn = open_db(db_path)
    try:
        conn.execute(
            """UPDATE qualitative_index
                  SET status = ?,
                      culture_flag = ?,
                      legitimacy_tier = ?,
                      model = COALESCE(?, model),
                      prompt_version = COALESCE(?, prompt_version),
                      error_text = ?
                WHERE job_ref = ?""",
            (status, culture_flag, legitimacy_tier, model, prompt_version, error_text, job_ref),
        )
        conn.commit()
    finally:
        conn.close()


def get_qualitative_index_row(db_path: Path, job_ref: str) -> dict[str, Any] | None:
    conn = open_db(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM qualitative_index WHERE job_ref = ?",
            (job_ref,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ===========================================================================
# OQ-2 — Re-evaluate seen digest jobs (manual re-score against current profile)
# ===========================================================================
#
# Every LLM-status mutation below is a COMPARE-AND-SWAP: the eligibility guard
# lives in the SQL WHERE clause and the helper returns the affected rowcount.
# The re-eval runs under _PIPELINE_LOCK, which does NOT serialise against the
# daemon LLM worker (it uses _LLM_WORKER_LOCK + per-row claim tokens), so a
# Python-side snapshot of llm_status can be stale by the time we act. The CAS
# guard makes a stale write a no-op instead of clobbering a concurrent worker
# transition (e.g. yanking a 'processing' row back to 'pending' mid-call).

# LLM statuses a re-queue may overwrite. 'pending' (already queued) and
# 'processing' (claimed/in-flight) are deliberately excluded; 'done' is included
# so a crossed-up job's stale AI summary is refreshed (OQ-2-B).
_REQUEUE_ELIGIBLE_LLM_STATUS = ("failed", "skipped", "done")


def list_digest_jobs_for_reeval(db_path: Path) -> list[sqlite3.Row]:
    """All digest rows (``digest_date IS NOT NULL``) with the columns the re-eval
    needs: ``job_id``, ``match_score`` (the OLD score, read before the re-score
    overwrites it), and ``llm_status`` (a snapshot used only to decide whether the
    job was *ever a match before* — a NULL status means it was never queued for AI,
    i.e. it sat below the threshold in force at ingest). Ordered highest-score-first
    with a stable secondary key so a capped LLM re-queue picks the same top rows on
    repeated runs."""
    conn = open_db(db_path)
    try:
        return conn.execute(
            "SELECT job_id, match_score AS old_score, llm_status FROM jobs "
            "WHERE digest_date IS NOT NULL "
            "ORDER BY match_score DESC, job_id ASC"
        ).fetchall()
    finally:
        conn.close()


def resurface_digest_job(db_path: Path, job_id: str) -> int:
    """Mark a digest job unseen again (``digest_seen = 0``). Returns rowcount.
    Deliberately leaves ``digest_date`` and ``saved_search_id`` untouched (OQ-2-C:
    preserve the first-seen date), unlike ``set_digest_meta``."""
    conn = open_db(db_path)
    try:
        cur = conn.execute(
            "UPDATE jobs SET digest_seen = 0 "
            "WHERE job_id = ? AND digest_date IS NOT NULL",
            (job_id,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def requeue_llm_if_eligible(db_path: Path, job_id: str) -> int:
    """CAS re-queue for the LLM worker. Atomically flips the row to ``pending`` and
    resets the retry/claim state ONLY when the live ``llm_status`` is NULL or one of
    ``_REQUEUE_ELIGIBLE_LLM_STATUS`` (failed/skipped/done). Returns rowcount: 1 when
    it actually queued the job, 0 when a concurrent worker had already moved it to
    ``processing`` (or it was already ``pending``). ``llm_attempts`` resets to 0 so
    the refreshed call gets a full retry budget."""
    conn = open_db(db_path)
    try:
        placeholders = ",".join("?" for _ in _REQUEUE_ELIGIBLE_LLM_STATUS)
        cur = conn.execute(
            f"""UPDATE jobs
                   SET llm_status = 'pending',
                       llm_attempts = 0,
                       llm_next_attempt_at = NULL,
                       llm_claimed_at = NULL,
                       llm_claim_token = NULL
                 WHERE job_id = ?
                   AND digest_date IS NOT NULL
                   AND (llm_status IS NULL OR llm_status IN ({placeholders}))""",
            (job_id, *_REQUEUE_ELIGIBLE_LLM_STATUS),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def clear_llm_queue(db_path: Path, job_id: str) -> int:
    """CAS dequeue: remove an UN-STARTED ``pending`` job from the LLM queue
    (``llm_status -> NULL``). The ``WHERE llm_status = 'pending'`` guard makes it a
    no-op (returns 0) if the worker has already claimed the row to ``processing`` —
    so an in-flight call is never stranded. Scoped to digest rows
    (``digest_date IS NOT NULL``) to mirror the other helpers and resist misuse.
    Returns rowcount."""
    conn = open_db(db_path)
    try:
        cur = conn.execute(
            """UPDATE jobs
                  SET llm_status = NULL,
                      llm_next_attempt_at = NULL,
                      llm_claimed_at = NULL,
                      llm_claim_token = NULL
                WHERE job_id = ? AND digest_date IS NOT NULL AND llm_status = 'pending'""",
            (job_id,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
