from __future__ import annotations

import logging
import sqlite3
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
    """Open/create the SQLite DB, run schema, return connection with row_factory."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    return conn


def upsert_job(db_path: Path, row: dict[str, Any]) -> None:
    """INSERT OR REPLACE a job row into the index."""
    tailoring_raw = row.get("tailoring_ready")
    if tailoring_raw is None:
        tailoring_int = None
    else:
        tailoring_int = 1 if tailoring_raw else 0

    conn = open_db(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO jobs
                (job_id, job_title, company, location, source,
                 match_score, decision, user_decision, ats_score,
                 tailoring_ready, status, updated_at, salary_min, salary_max)
            VALUES
                (:job_id, :job_title, :company, :location, :source,
                 :match_score, :decision, :user_decision, :ats_score,
                 :tailoring_ready, :status, :updated_at, :salary_min, :salary_max)
            """,
            {
                "job_id": row.get("job_id"),
                "job_title": row.get("job_title"),
                "company": row.get("company"),
                "location": row.get("location"),
                "source": row.get("source"),
                "match_score": row.get("match_score"),
                "decision": row.get("decision"),
                "user_decision": row.get("user_decision"),
                "ats_score": row.get("ats_score"),
                "tailoring_ready": tailoring_int,
                "status": row.get("status") or "not_applied",
                "updated_at": row.get("updated_at"),
                "salary_min": row.get("salary_min"),
                "salary_max": row.get("salary_max"),
            },
        )
        conn.commit()
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
            except (FileNotFoundError, StorageError, Exception) as exc:
                logger.warning("rebuild_index: skipping reviewed_job for %s: %s", job_id, exc)
                job_title = None
                company = None
                location = None
                source = None
                salary_min = None
                salary_max = None

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
