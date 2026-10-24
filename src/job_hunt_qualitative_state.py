"""Short SQLite guards for qualitative ownership, publication and readers.

Provider work never holds this guard. JSON and SQLite are not crash-atomic:
readers accept a managed artifact only after its generation completed in SQL.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
import copy
import uuid

LEASE_SECONDS = 30 * 60
PUBLICATION_KEY = "_publication"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
        # Compatibility with persisted pre-lease timestamps and fixed fixtures.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("qualitative lease clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def clock_for(*, clock=None, now=None):
    return clock if clock is not None else (lambda: _utc(now)) if now is not None else utc_now


@contextmanager
def guard(db_path: Path, *, clock: Callable[[], datetime] = utc_now):
    from src.job_hunt_index import open_db
    conn = open_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Never sample wall time before waiting for another writer's guard.
        now = _utc(clock())
        yield conn, now
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@dataclass(frozen=True)
class QualitativeClaim:
    job_ref: str
    token: str
    generation: str
    previous: dict | None
    queue: dict | None = None


class QualitativeOwnershipStopped(RuntimeError):
    def __init__(self, outcome):
        super().__init__("qualitative ownership " + outcome)
        self.outcome = outcome


def _active(row, now):
    try:
        return bool(row and row["claim_token"] and row["lease_until"] and now < _utc(row["lease_until"]))
    except (ValueError, TypeError):
        return False


def _queue_row(conn, queue, now):
    if queue is None:
        return None
    row = conn.execute("SELECT * FROM eval_queue WHERE id=?", (queue["id"],)).fetchone()
    if (row is None or row["status"] != "running" or row["claim_token"] != queue["claim_token"]
            or row["job_ref"] != queue["job_ref"] or row["batch_id"] != queue["batch_id"] or not _active(row, now)):
        return None
    return row


def _cancelled(conn, queue):
    return bool(queue and conn.execute(
        "SELECT 1 FROM eval_batch WHERE batch_id=? AND cancel_requested_at IS NOT NULL",
        (queue["batch_id"],)).fetchone())


def _owned(conn, claim, now):
    row = conn.execute("SELECT * FROM qualitative_index WHERE job_ref=?", (claim.job_ref,)).fetchone()
    if (row is None or row["status"] != "running" or row["claim_token"] != claim.token
            or row["generation"] != claim.generation or not _active(row, now)):
        return None
    if claim.queue is not None and (claim.queue["job_ref"] != claim.job_ref or _queue_row(conn, claim.queue, now) is None):
        return None
    return row


def _one(cursor):
    if cursor.rowcount != 1:
        raise RuntimeError("qualitative ownership changed inside publication guard")


def _finish_queue(conn, queue, *, status, now, error=None, retries=None):
    if queue is None:
        return
    _one(conn.execute("""UPDATE eval_queue SET status=?, claim_token=NULL, lease_until=NULL,
        error_text=?, retries=COALESCE(?,retries),
        started_at=CASE WHEN ?='pending' THEN NULL ELSE started_at END,
        finished_at=CASE WHEN ?='pending' THEN NULL ELSE ? END
        WHERE id=? AND status='running' AND claim_token=?""",
        (status, error, retries, status, status, now.isoformat(timespec="microseconds"),
         queue["id"], queue["claim_token"])))


def defer_queue(db_path, queue, *, clock=utc_now, reason="qualitative assessment already in flight", done=False):
    """Waiting consumes no provider retry budget and does not touch its owner."""
    with guard(db_path, clock=clock) as (conn, now):
        if _queue_row(conn, queue, now) is None:
            return "lost"
        cancelled = _cancelled(conn, queue)
        status = "cancelled" if cancelled else "done" if done else "pending"
        _finish_queue(conn, queue, status=status, now=now, error=None if cancelled or done else reason)
        return status


def acquire(db_path, job_ref, *, force=False, retry_errors=False, model=None, prompt_version=None, clock=utc_now, queue=None):
    with guard(db_path, clock=clock) as (conn, now):
        if queue is not None:
            if queue["job_ref"] != job_ref or _queue_row(conn, queue, now) is None:
                return {"claimed": False, "outcome": "lost", "row": None}
            if _cancelled(conn, queue):
                _finish_queue(conn, queue, status="cancelled", now=now)
                return {"claimed": False, "outcome": "cancelled", "row": None}
        existing = conn.execute("SELECT * FROM qualitative_index WHERE job_ref=?", (job_ref,)).fetchone()
        previous = dict(existing) if existing is not None else None
        if existing is not None:
            if existing["status"] == "running" and _active(existing, now):
                return {"claimed": False, "in_flight": True, "outcome": "waiting", "row": previous}
            if existing["status"] in {"done", "error"} and not force and not (retry_errors and existing["status"] == "error"):
                return {"claimed": False, "in_flight": False, "outcome": existing["status"], "row": previous}
            if existing["status"] in {"running", "pending"}:
                previous = None  # A crashed owner is never a restorable state.
        token = uuid.uuid4().hex
        lease = (now + timedelta(seconds=LEASE_SECONDS)).isoformat(timespec="microseconds")
        stamp = now.isoformat(timespec="microseconds")
        conn.execute("""INSERT INTO qualitative_index
            (job_ref,status,model,prompt_version,created_at,claim_token,lease_until,generation)
            VALUES(?,'running',?,?,?,?,?,?) ON CONFLICT(job_ref) DO UPDATE SET
            status='running',grade=NULL,culture_flag=NULL,legitimacy_tier=NULL,model=excluded.model,
            prompt_version=excluded.prompt_version,error_text=NULL,created_at=excluded.created_at,
            claim_token=excluded.claim_token,lease_until=excluded.lease_until,generation=excluded.generation""",
            (job_ref, model, prompt_version, stamp, token, lease, token))
        row = dict(conn.execute("SELECT * FROM qualitative_index WHERE job_ref=?", (job_ref,)).fetchone())
        owner = QualitativeClaim(job_ref, token, token, copy.deepcopy(previous), copy.deepcopy(queue))
        return {"claimed": True, "in_flight": True, "outcome": "claimed", "row": row, "owner": owner}


def accepted(payload, row):
    """No fallback from present-but-malformed managed publication metadata."""
    if not isinstance(payload, dict):
        return False
    if PUBLICATION_KEY in payload:
        meta = payload[PUBLICATION_KEY]
        return bool(isinstance(meta, dict) and type(meta.get("version")) is int and meta["version"] == 1
                    and isinstance(meta.get("generation"), str) and bool(meta["generation"])
                    and row and row["status"] == "done"
                    and row["generation"] and not row["claim_token"] and not row["lease_until"]
                    and row["completed_generation"] == meta["generation"])
    return row is None or (not row["generation"] and not row["claim_token"] and not row["lease_until"] and row["status"] == "done")


def _read_raw(job_ref, state_root):
    from src.job_hunt_storage import _load_qualitative_assessment_raw
    return _load_qualitative_assessment_raw(job_ref, state_root)


def read_accepted(job_ref, state_root, *, db_path=None):
    from src.job_hunt_storage import StorageError
    db_path = Path(db_path) if db_path is not None else Path(state_root) / "job_hunt_index.db"
    try:
        with guard(db_path) as (conn, _now):
            row = conn.execute("SELECT * FROM qualitative_index WHERE job_ref=?", (job_ref,)).fetchone()
            payload = _read_raw(job_ref, state_root)
            if not accepted(payload, row):
                raise StorageError("qualitative publication is incomplete or unavailable")
            return payload
    except FileNotFoundError:
        raise
    except StorageError:
        raise
    except Exception as exc:
        raise StorageError("qualitative publication index is unavailable") from exc


def read_snapshot(job_ref, state_root, *, db_path=None):
    """One coherent UI snapshot; rejected content never escapes to backfill."""
    from src.job_hunt_storage import StorageError
    db_path = Path(db_path) if db_path is not None else Path(state_root) / "job_hunt_index.db"
    with guard(db_path) as (conn, now):
        row = conn.execute("SELECT * FROM qualitative_index WHERE job_ref=?", (job_ref,)).fetchone()
        try:
            payload = _read_raw(job_ref, state_root)
        except (OSError, ValueError, StorageError):
            payload = None
        return (payload if accepted(payload, row) else None), dict(row) if row is not None else None


def _restorable(previous, job_ref, state_root):
    if not previous or previous.get("status") != "done" or not previous.get("completed_generation"):
        return False
    try:
        return accepted(_read_raw(job_ref, state_root), previous)
    except (OSError, ValueError):
        return False


def _transition_locked(conn, claim, now, *, mode, error, state_root, retries=None):
    cancelled = _cancelled(conn, claim.queue)
    if cancelled or mode == "cancel":
        status, queue_status, error = "error", "cancelled", "cancelled"
    elif mode in {"quota", "release"}:
        if _restorable(claim.previous, claim.job_ref, state_root):
            status = "done"
        else:
            status = "pending" if claim.queue else "error"
        queue_status = "pending"
    else:
        status, queue_status = "error", "pending" if mode == "retry" else "error"
    prior = claim.previous if status == "done" else {}
    _one(conn.execute("""UPDATE qualitative_index SET status=?,grade=?,culture_flag=?,legitimacy_tier=?,
        model=COALESCE(?,model),prompt_version=COALESCE(?,prompt_version),error_text=?,
        created_at=CASE WHEN ?='done' THEN ? ELSE created_at END,
        claim_token=NULL,lease_until=NULL WHERE job_ref=? AND status='running' AND claim_token=? AND generation=?""",
        (status, prior.get("grade"), prior.get("culture_flag"), prior.get("legitimacy_tier"),
         prior.get("model"), prior.get("prompt_version"), error, status, prior.get("created_at"), claim.job_ref, claim.token, claim.generation)))
    _finish_queue(conn, claim.queue, status=queue_status, now=now,
                  error=None if queue_status == "cancelled" else error,
                  retries=None if cancelled else retries)
    if mode == "quota" and not cancelled and claim.queue:
        conn.execute("""UPDATE eval_queue SET error_text=? WHERE batch_id=? AND status='pending'
            AND NOT EXISTS(SELECT 1 FROM eval_batch b WHERE b.batch_id=eval_queue.batch_id
                AND b.cancel_requested_at IS NOT NULL)""", (error, claim.queue["batch_id"]))
    return "cancelled" if cancelled or mode == "cancel" else mode


def transition(db_path, claim, *, mode, error=None, state_root, retries=None, clock=utc_now):
    if mode not in {"quota", "release", "retry", "error", "cancel"}:
        raise ValueError("invalid qualitative transition")
    with guard(db_path, clock=clock) as (conn, now):
        if _owned(conn, claim, now) is None:
            return "lost"
        return _transition_locked(conn, claim, now, mode=mode, error=error,
                                  state_root=state_root, retries=retries)


def checkpoint(db_path, claim, *, state_root, clock=utc_now):
    """Validate intent and renew both live leases before each provider attempt."""
    with guard(db_path, clock=clock) as (conn, now):
        if _owned(conn, claim, now) is None:
            return "lost"
        if _cancelled(conn, claim.queue):
            return _transition_locked(conn, claim, now, mode="cancel", error="cancelled", state_root=state_root)
        lease = (now + timedelta(seconds=LEASE_SECONDS)).isoformat(timespec="microseconds")
        _one(conn.execute("UPDATE qualitative_index SET lease_until=? WHERE job_ref=? AND claim_token=? AND status='running'",
                          (lease, claim.job_ref, claim.token)))
        if claim.queue:
            _one(conn.execute("UPDATE eval_queue SET lease_until=? WHERE id=? AND claim_token=? AND status='running'",
                              (lease, claim.queue["id"], claim.queue["claim_token"])))
        return "active"


def queue_transition(db_path, row_id, token, *, status, clock=utc_now, error=None, retries=None):
    """Standalone queue CAS compatibility; expired tokens cannot transition."""
    with guard(db_path, clock=clock) as (conn, now):
        queue = conn.execute("SELECT * FROM eval_queue WHERE id=?", (row_id,)).fetchone()
        if queue is None or queue["claim_token"] != token or queue["status"] != "running" or not _active(queue, now):
            return False
        cancelled = _cancelled(conn, queue)
        _finish_queue(conn, queue, status="cancelled" if cancelled else status, now=now,
                      error=None if cancelled else error, retries=None if cancelled else retries)
        return True


def publish(db_path, claim, assessment, *, state_root, result, clock=utc_now):
    from src.job_hunt_storage import save_qualitative_assessment
    with guard(db_path, clock=clock) as (conn, now):
        if _owned(conn, claim, now) is None:
            return "lost"
        if _cancelled(conn, claim.queue):
            return _transition_locked(conn, claim, now, mode="cancel", error="cancelled", state_root=state_root)
        payload = {**assessment, PUBLICATION_KEY: {"version": 1, "generation": claim.generation}}
        save_qualitative_assessment(claim.job_ref, payload, state_root)
        _one(conn.execute("""UPDATE qualitative_index SET status='done',grade=?,legitimacy_tier=?,
            culture_flag=?,model=?,prompt_version=?,error_text=NULL,completed_generation=?,
            claim_token=NULL,lease_until=NULL WHERE job_ref=? AND claim_token=? AND generation=? AND status='running'""",
            (result.grade, result.legitimacy_tier, result.culture_flag, result.model, assessment.get("prompt_version"),
             claim.generation, claim.job_ref, claim.token, claim.generation)))
        _finish_queue(conn, claim.queue, status="done", now=now)
        return "done"


def archive_owned(db_path, claim, *, state_root, clock=utc_now):
    from src.job_hunt_storage import _archive_qualitative_assessment_raw
    with guard(db_path, clock=clock) as (conn, now):
        if _owned(conn, claim, now) is None:
            return "lost"
        if _cancelled(conn, claim.queue):
            return _transition_locked(conn, claim, now, mode="cancel", error="cancelled", state_root=state_root)
        _archive_qualitative_assessment_raw(claim.job_ref, state_root)
        return "active"


def backfill_grade(db_path, job_ref, *, state_root, analysis):
    from src.job_hunt_qualitative import apply_grade_to_assessment
    from src.job_hunt_models import effective_decision
    from src.job_hunt_storage import save_qualitative_assessment
    with guard(db_path) as (conn, now):
        row = conn.execute("SELECT * FROM qualitative_index WHERE job_ref=?", (job_ref,)).fetchone()
        payload = _read_raw(job_ref, state_root)
        if not accepted(payload, row):
            return None
        before = copy.deepcopy(payload)
        grade = apply_grade_to_assessment(analysis.match_score, payload,
            effective_decision=effective_decision(analysis), has_blockers=bool(analysis.blockers),
            confidence=analysis.confidence, decision_reason=analysis.decision_reason)
        if payload != before:
            # A grade rewrite is a new publication, even for a legacy artifact.
            # If SQL fails after replacement, the new JSON generation is not
            # accepted against the previous completed row (or absent row).
            generation = uuid.uuid4().hex
            payload[PUBLICATION_KEY] = {"version": 1, "generation": generation}
            save_qualitative_assessment(job_ref, payload, state_root)
            if row is None:
                _one(conn.execute("""INSERT INTO qualitative_index
                    (job_ref,status,grade,model,prompt_version,created_at,generation,completed_generation)
                    VALUES(?,'done',?,?,?,?,?,?)""",
                    (job_ref,grade["display_grade"],payload.get("model"),payload.get("prompt_version"),
                     now.isoformat(timespec="microseconds"),generation,generation)))
            else:
                _one(conn.execute("""UPDATE qualitative_index SET grade=?,completed_generation=?,
                    generation=COALESCE(generation,?) WHERE job_ref=? AND status='done'
                    AND generation IS ? AND completed_generation IS ?""",
                    (grade["display_grade"],generation,generation,job_ref,row["generation"],row["completed_generation"])))
        elif row is not None and row["grade"] != grade["display_grade"]:
            _one(conn.execute("""UPDATE qualitative_index SET grade=? WHERE job_ref=? AND status='done'
                AND generation IS ? AND completed_generation IS ?""",
                (grade["display_grade"], job_ref, row["generation"], row["completed_generation"])))
        current = conn.execute("SELECT * FROM qualitative_index WHERE job_ref=?", (job_ref,)).fetchone()
        return payload, grade, dict(current) if current is not None else None
