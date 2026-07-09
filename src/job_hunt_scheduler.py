"""Daily Job Digest — D3 pipeline (LLM-free deterministic scoring + LLM queueing).

``run_digest_pipeline`` runs one or more saved searches synchronously: fetch →
guard/dedup → convert → deterministic evaluate → index + digest metadata → queue
high-match jobs for the (D6) LLM worker. It NEVER calls the rate-limited Gemini
analysis itself — it only flips ``llm_status='pending'``. Local Ollama skill
extraction may run via ``extract_skills_from_text`` (user-chosen), bounded by
``digest_max_per_source``.

The background ``DigestScheduler`` daemon that calls this on a timer is D5; D3
only provides the callable pipeline + the per-search ``run-now`` trigger.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import islice
from pathlib import Path
from typing import Any, Callable

from src.job_hunt_index import (
    claim_batch,
    claim_eval_queue_row,
    clear_llm_queue,
    finish_eval_queue_row,
    incr_rpd_counter,
    is_eval_batch_cancel_requested,
    is_already_indexed,
    list_digest_jobs_for_reeval,
    open_db,
    pause_eval_batch_for_quota,
    release_qualitative_assessment_claim,
    requeue_eval_queue_row,
    return_eval_queue_row_to_pending,
    requeue_llm_if_eligible,
    reset_stale_eval_queue_running,
    reset_stale_llm_processing,
    resurface_digest_job,
    rpd_used_today,
    set_digest_meta,
    set_llm_status,
    source_job_id_from_ui_result,
    upsert_job,
    LLMQuotaExhausted,
)
from src.job_hunt_evaluation import evaluate_reviewed_job
from src.job_hunt_parsing import extract_skills_from_text
from src.job_hunt_reviewed_input import reviewed_job_from_dict
from src.job_hunt_storage import (
    StorageError,
    load_job_analysis,
    load_reviewed_job,
    save_job_analysis,
    save_reviewed_job,
)
from src.job_sources.source_registry import get_source
from src.ui_utils import reviewed_job_payload_from_ui_result

logger = logging.getLogger(__name__)

# Process-wide locks (single server process):
#  - _PIPELINE_LOCK serialises digest runs (scheduler vs manual "Run now") so two
#    runs never write the same job concurrently.
#  - _LLM_WORKER_LOCK serialises LLM drains (auto worker vs manual run-llm-batch) so
#    aggregate pacing stays within RPM and the RPD check/incr can't race.
_PIPELINE_LOCK = threading.Lock()
_LLM_WORKER_LOCK = threading.Lock()

# Skip reasons that get logged + counted (already-seen is neither — it's expected).
_SKIP_REASONS = {
    "missing_source_job_id",
    "missing_description_raw",
    "adapter_error",
    "evaluation_error",
}


@dataclass(frozen=True)
class DigestRunResult:
    started_at: str
    finished_at: str
    searches_run: int
    jobs_fetched: int
    jobs_new: int              # first-seen, indexed this run
    jobs_scored: int
    jobs_llm_queued: int       # D3 QUEUES only — it never calls the LLM
    jobs_skipped: int          # blank id / empty description / adapter / eval error
    jobs_already_seen: int     # dedup hits — expected, not errors (observability)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "searches_run": self.searches_run,
            "jobs_fetched": self.jobs_fetched,
            "jobs_new": self.jobs_new,
            "jobs_scored": self.jobs_scored,
            "jobs_llm_queued": self.jobs_llm_queued,
            "jobs_skipped": self.jobs_skipped,
            "jobs_already_seen": self.jobs_already_seen,
            "errors": list(self.errors),
        }


def _log_skipped(state_root: Path, run_date: str, *, source: str, saved_search_id: str,
                 reason: str, title: str, url: str) -> None:
    """Append one line to data/state/logs/digest_skipped_jobs_YYYY-MM-DD.jsonl.
    Never raises — a logging failure must not abort the run."""
    try:
        logs_dir = Path(state_root) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps({
            "source": source, "saved_search_id": saved_search_id, "reason": reason,
            "title": title, "url": url, "seen_at": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False)
        with (logs_dir / f"digest_skipped_jobs_{run_date}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:  # pragma: no cover - logging is best-effort
        logger.warning("digest: could not write skipped-job log: %s", exc)


def run_digest_pipeline(
    *,
    config: Any,
    saved_searches: list[Any],
    profile: Any,
    db_path: Path,
) -> DigestRunResult:
    """Run the deterministic digest pipeline, serialised by the process-wide
    pipeline lock so a scheduled run and a manual "Run now" can't write the same
    job concurrently (D5 review)."""
    with _PIPELINE_LOCK:
        return _run_digest_pipeline_locked(
            config=config, saved_searches=saved_searches, profile=profile, db_path=db_path
        )


def _run_digest_pipeline_locked(
    *,
    config: Any,
    saved_searches: list[Any],
    profile: Any,
    db_path: Path,
) -> DigestRunResult:
    """Run the deterministic digest pipeline over the given saved searches.

    Synchronous, no threading. Each result and each search is processed in its own
    try/except so one bad item never aborts the run. The LLM-queue cap
    (``digest_max_llm_per_run``) is a single counter spanning the whole run.
    """
    started_at = datetime.now().isoformat(timespec="seconds")
    run_date = datetime.now().date().isoformat()   # local date, computed ONCE
    state_root = Path(config.state_root)

    searches_run = jobs_fetched = jobs_new = jobs_scored = 0
    jobs_llm_queued = jobs_skipped = jobs_already_seen = 0
    newly_queued = 0                                 # global cap counter (across searches)
    errors: list[str] = []

    for ss in saved_searches:
        if not getattr(ss, "enabled", True):
            continue
        source_id = (ss.source_id or "").lower()
        source = get_source(source_id)
        if source is None:
            errors.append(f"{ss.search_id}: unknown source {source_id!r}")
            continue

        # Fetch (whole-search failure is logged, never aborts other searches)
        try:
            params = source.normalize_search_params(dict(ss.params))
            results = source.search_handler(params)
        except Exception as exc:
            errors.append(f"{ss.search_id}: fetch failed: {exc}")
            logger.warning("digest: fetch failed for %s: %s", ss.search_id, exc)
            continue

        searches_run += 1
        # islice so a huge/lazy adapter generator isn't fully materialised.
        for result in islice(results, profile.digest_max_per_source):
            jobs_fetched += 1
            # A non-dict adapter item must not abort the run (per-result isolation).
            if not isinstance(result, dict):
                _log_skipped(state_root, run_date, source=source_id,
                             saved_search_id=ss.search_id, reason="adapter_error",
                             title="", url="")
                jobs_skipped += 1
                continue
            title = str(result.get("title") or "")
            url = str(result.get("url") or "")

            # --- Guards + dedup (skips are input-level, counted as jobs_skipped) ---
            sjid = source_job_id_from_ui_result(result)
            if not sjid:
                _log_skipped(state_root, run_date, source=source_id,
                             saved_search_id=ss.search_id, reason="missing_source_job_id",
                             title=title, url=url)
                jobs_skipped += 1
                continue
            if not str(result.get("description_raw") or "").strip():
                _log_skipped(state_root, run_date, source=source_id,
                             saved_search_id=ss.search_id, reason="missing_description_raw",
                             title=title, url=url)
                jobs_skipped += 1
                continue
            if is_already_indexed(db_path, source_id, sjid):
                jobs_already_seen += 1               # expected — silent, not a skip
                continue

            # --- Convert + deterministic evaluate (failure here = a skip) ---
            try:
                payload = reviewed_job_payload_from_ui_result(result, source_id=source_id)
                required, preferred, _warn = extract_skills_from_text(payload["description_raw"])
                payload["required_skills"] = required
                payload["preferred_skills"] = preferred
                job = reviewed_job_from_dict(payload)
                analysis = evaluate_reviewed_job(profile, job)
            except Exception as exc:
                _log_skipped(state_root, run_date, source=source_id,
                             saved_search_id=ss.search_id, reason="evaluation_error",
                             title=title, url=url)
                jobs_skipped += 1
                errors.append(f"{ss.search_id}/{title[:40]}: eval failed: {exc}")
                logger.warning("digest: eval failed (%s): %s", ss.search_id, exc)
                continue
            jobs_scored += 1

            # --- Persist JSON, then index-write LAST. A failure here is an ERROR,
            # not a skip — the job WAS scored; it just isn't indexed yet (re-tried
            # next run since it stays not-already-indexed). ---
            try:
                save_reviewed_job(job, config.state_root)
                save_job_analysis(analysis, config.state_root)
                upsert_job(db_path, {
                    "job_id": job.job_id,
                    "job_title": job.job_title,
                    "company": job.company,
                    "location": job.location,
                    "source": source_id,
                    "source_job_id": sjid,
                    "apply_url": job.url or job.source_ref,
                    "match_score": analysis.match_score,
                    "decision": analysis.decision,
                    "user_decision": getattr(analysis, "user_decision", None),
                    "ats_score": getattr(analysis, "ats_score", None),
                    "tailoring_ready": getattr(analysis, "tailoring_ready", None),
                    "status": "not_applied",
                    "updated_at": run_date,
                    "salary_min": job.salary_min_gbp,
                    "salary_max": job.salary_max_gbp,
                })
            except Exception as exc:
                errors.append(f"{ss.search_id}/{job.job_id}: persist/index failed: {exc}")
                logger.warning("digest: persist/index failed (%s): %s", job.job_id, exc)
                continue
            jobs_new += 1

            # --- Digest metadata + LLM queue. Best-effort: a failure is an ERROR,
            # never un-counts the indexed job. One GLOBAL cap (across searches). ---
            try:
                set_digest_meta(db_path, job.job_id, digest_date=run_date,
                                saved_search_id=ss.search_id)
                score = analysis.match_score
                if (profile.digest_llm_enabled and score is not None
                        and score >= profile.digest_threshold
                        and newly_queued < profile.digest_max_llm_per_run):
                    set_llm_status(db_path, job.job_id, "pending")
                    newly_queued += 1
                    jobs_llm_queued += 1
            except Exception as exc:
                errors.append(f"{ss.search_id}/{job.job_id}: digest-meta/queue failed: {exc}")
                logger.warning("digest: meta/queue failed (%s): %s", job.job_id, exc)

    return DigestRunResult(
        started_at=started_at,
        finished_at=datetime.now().isoformat(timespec="seconds"),
        searches_run=searches_run,
        jobs_fetched=jobs_fetched,
        jobs_new=jobs_new,
        jobs_scored=jobs_scored,
        jobs_llm_queued=jobs_llm_queued,
        jobs_skipped=jobs_skipped,
        jobs_already_seen=jobs_already_seen,
        errors=errors,
    )


# ===========================================================================
# OQ-2 — Re-evaluate seen digest jobs (manual, deterministic re-score)
# ===========================================================================


@dataclass(frozen=True)
class ReevalResult:
    started_at: str
    finished_at: str
    jobs_examined: int        # digest rows considered
    jobs_rescored: int        # successfully re-scored + re-indexed
    jobs_resurfaced: int      # crossed up → digest_seen reset to 0
    jobs_llm_requeued: int    # crossed up → LLM re-queued (CAS succeeded, within cap)
    jobs_dequeued: int        # dropped below → un-started pending LLM job cleared
    jobs_missing: int         # indexed but reviewed_job JSON gone → skipped
    jobs_errored: int         # re-score raised → skipped
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "jobs_examined": self.jobs_examined,
            "jobs_rescored": self.jobs_rescored,
            "jobs_resurfaced": self.jobs_resurfaced,
            "jobs_llm_requeued": self.jobs_llm_requeued,
            "jobs_dequeued": self.jobs_dequeued,
            "jobs_missing": self.jobs_missing,
            "jobs_errored": self.jobs_errored,
            "errors": list(self.errors),
        }


def reevaluate_digest_jobs(*, config: Any, profile: Any, db_path: Path) -> ReevalResult:
    """Re-score every indexed digest job against the CURRENT profile/threshold and
    resurface the ones that newly qualify (OQ-2). Serialised by ``_PIPELINE_LOCK`` so
    it can't write a job concurrently with the scheduler or a manual Run-now.

    Purely local + deterministic: reloads each stored ``reviewed_job`` and re-runs
    ``evaluate_reviewed_job`` — no fetch, no skill re-extraction, no Gemini call here
    (crossed-up jobs are only *queued*; the paced D6 worker does the actual LLM work).
    """
    with _PIPELINE_LOCK:
        return _reevaluate_digest_jobs_locked(config=config, profile=profile, db_path=db_path)


def _reevaluate_digest_jobs_locked(*, config: Any, profile: Any, db_path: Path) -> ReevalResult:
    started_at = datetime.now().isoformat(timespec="seconds")
    run_date = datetime.now().date().isoformat()
    threshold = profile.digest_threshold
    llm_enabled = bool(getattr(profile, "digest_llm_enabled", False))
    requeue_cap = int(getattr(profile, "digest_max_llm_per_run", 0))

    rows = list_digest_jobs_for_reeval(db_path)
    examined = rescored = resurfaced = llm_requeued = dequeued = missing = errored = 0
    requeued = 0   # counts ACTUAL CAS successes against the cap (not stale snapshots)
    errors: list[str] = []

    for row in rows:
        examined += 1
        job_id = row["job_id"]
        old_score = row["old_score"]

        # --- Reload + deterministic re-score (per-job isolation) ---
        try:
            reviewed = load_reviewed_job(job_id, config.state_root)
        except (FileNotFoundError, StorageError):
            missing += 1
            continue
        try:
            analysis = evaluate_reviewed_job(profile, reviewed)
        except Exception as exc:
            errored += 1
            errors.append(f"{job_id}: re-score failed: {exc}")
            logger.warning("reeval: re-score failed for %s: %s", job_id, exc)
            continue

        new_score = analysis.match_score

        # --- Persist JSON, then index-write. A failure here is an error (the score
        # is computed; the row just isn't updated yet — a later run retries). ---
        try:
            save_job_analysis(analysis, config.state_root)
            upsert_job(db_path, {
                "job_id": job_id,
                "job_title": reviewed.job_title,
                "company": reviewed.company,
                "location": reviewed.location,
                "source": (reviewed.source_type or "").lower() or None,
                "source_job_id": reviewed.source_job_id,
                "apply_url": reviewed.url or reviewed.source_ref,
                "match_score": new_score,
                "decision": analysis.decision,
                "user_decision": getattr(analysis, "user_decision", None),
                "ats_score": getattr(analysis, "ats_score", None),
                "tailoring_ready": getattr(analysis, "tailoring_ready", None),
                # status/updated_at preserved by upsert when omitted? No — upsert sets
                # them. Re-score must NOT reset the user's pipeline status, so pass the
                # existing status through unchanged.
                "status": row_status(db_path, job_id),
                "updated_at": run_date,
                "salary_min": reviewed.salary_min_gbp,
                "salary_max": reviewed.salary_max_gbp,
            })
        except Exception as exc:
            errored += 1
            errors.append(f"{job_id}: persist/index failed: {exc}")
            logger.warning("reeval: persist/index failed for %s: %s", job_id, exc)
            continue
        rescored += 1

        # --- Surfacing decision ---
        # A job "crosses up" when it now qualifies (new_score >= threshold) AND it
        # was NOT a match before. "Was a match before" is detected two ways, so the
        # feature responds to BOTH triggers it's named for:
        #   - profile change raised the score across the bar  → old_score < threshold
        #   - threshold lowered (or AI enabled later)         → never queued for AI
        #     (llm_status IS NULL means the ingest pipeline never treated it as a
        #      match; a pure threshold change can't move the score, so the NULL
        #      signal is what makes threshold changes actually do something).
        # Jobs already handled as a match (llm pending/processing/done with an
        # unchanged-or-higher score) are left alone — no unread nag (OQ-2-A).
        old_below_by_score = (old_score is None) or (old_score < threshold)
        never_queued = row["llm_status"] is None
        new_above = (new_score is not None) and (new_score >= threshold)
        crossed_up = new_above and (old_below_by_score or never_queued)

        try:
            if crossed_up:
                # Resurface as unread, and re-queue for AI within the cap.
                if resurface_digest_job(db_path, job_id):
                    resurfaced += 1
                if llm_enabled and requeued < requeue_cap:
                    if requeue_llm_if_eligible(db_path, job_id) == 1:
                        requeued += 1
                        llm_requeued += 1
            elif not new_above:
                # DROPPED BELOW / stayed below → drop an un-started pending LLM job.
                if clear_llm_queue(db_path, job_id) == 1:
                    dequeued += 1
            # else: stayed above and already a match → score updated only.
        except Exception as exc:
            errors.append(f"{job_id}: surfacing failed: {exc}")
            logger.warning("reeval: surfacing failed for %s: %s", job_id, exc)

    return ReevalResult(
        started_at=started_at,
        finished_at=datetime.now().isoformat(timespec="seconds"),
        jobs_examined=examined,
        jobs_rescored=rescored,
        jobs_resurfaced=resurfaced,
        jobs_llm_requeued=llm_requeued,
        jobs_dequeued=dequeued,
        jobs_missing=missing,
        jobs_errored=errored,
        errors=errors,
    )


def row_status(db_path: Path, job_id: str) -> str:
    """Read the current pipeline ``status`` for a job (default ``not_applied``) so a
    re-score never resets where the user has moved the card on the board."""
    conn = open_db(db_path)
    try:
        row = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return (row["status"] if row and row["status"] else "not_applied")
    finally:
        conn.close()


# ===========================================================================
# D6 — Paced LLM worker (rate-limited Gemini enrichment of high-match jobs)
# ===========================================================================

_LLM_MAX_ATTEMPTS = 5
_LLM_BACKOFF_BASE = 60.0       # seconds: 60, 120, 240, ...
_LLM_MAX_BACKOFF = 3600.0      # cap a single backoff at 1 hour
_STALE_PROCESSING_MIN = 30     # recover claims stuck >30 min (crash recovery)
_EVAL_MAX_ATTEMPTS = 5
_EVAL_429_BACKOFF_SECONDS = 300.0


def rpd_date_key(now: datetime | None = None) -> str:
    """The date key for the daily-request counter, in Gemini's quota timezone
    (midnight Pacific), so the cap aligns with the provider reset (v7 decision 2).
    Falls back to the local date if the tz database isn't available."""
    now = now or datetime.now()
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt, timezone as _tz
        # Interpret a naive `now` as local time, then convert to Pacific.
        aware = now if now.tzinfo else now.astimezone()
        return aware.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:  # pragma: no cover - missing tzdata
        return now.date().isoformat()


def save_analysis_llm_fields(job_id: str, result: dict, state_root, db_path: Path) -> None:
    """Load the JobAnalysis, set the 5 D6 llm_* fields from the Gemini result, re-save,
    then mark the jobs row done (§14.5a). Raises if the analysis is missing so the
    caller can classify it as a terminal local-data error (not an infinite retry)."""
    analysis = load_job_analysis(job_id, state_root)   # FileNotFoundError → caller skips
    updated = dataclasses.replace(
        analysis,
        llm_fit_summary=(result.get("fit") or None),
        llm_risk_summary=(result.get("risk") or None),
        llm_recommended_action=(result.get("action") or None),
        llm_model=(result.get("model_used") or None),
        llm_generated_at=datetime.now().isoformat(timespec="seconds"),
    )
    save_job_analysis(updated, state_root)
    set_llm_status(db_path, job_id, "done")


def _fetch_full_description(source: str, source_job_id: str, fallback: str) -> str:
    """Source-aware detail fetch (§11). Reed has a per-job detail API; Adzuna does
    not, so it uses the stored search-result description."""
    if (source or "").lower() == "reed" and source_job_id:
        try:
            from src.job_sources.reed_client import fetch_reed_job_detail
            detail = fetch_reed_job_detail(source_job_id)
            if detail and detail.get("jobDescription"):
                from src.job_sources.normalize import strip_html
                return strip_html(detail["jobDescription"]).strip() or fallback
        except Exception as exc:   # detail fetch is best-effort; fall back to stored text
            logger.warning("llm worker: Reed detail fetch failed for %s: %s", source_job_id, exc)
    return fallback


@dataclass(frozen=True)
class LLMBatchResult:
    processed: int        # llm 'done'
    failed: int           # moved to 'failed' (max attempts or terminal)
    requeued: int         # put back to pending (backoff or unstarted-on-throttle)
    skipped_rpd: bool     # stopped because the daily cap was reached
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"processed": self.processed, "failed": self.failed, "requeued": self.requeued,
                "skipped_rpd": self.skipped_rpd, "errors": list(self.errors)}


def drain_llm_batch(*, config: Any, profile: Any, db_path: Path,
                    now: Callable[[], datetime] = datetime.now,
                    sleep: Callable[[float], None] = time.sleep) -> LLMBatchResult:
    """Claim and process ONE paced batch of pending LLM jobs. Serialised by the
    process-wide worker lock so the daemon and the manual route can't double-pace
    (D6 review). `now`/`sleep` are injectable for tests.

    On 429 or the daily cap, stop and requeue every UNSTARTED claimed row to pending
    immediately (no attempt bump) — never strand them for the 30-min stale reset.
    """
    from src.job_hunt_llm import RateLimited, explain_job_match_with_llm

    state_root = config.state_root
    with _LLM_WORKER_LOCK:
        if not getattr(profile, "digest_llm_enabled", False):
            return LLMBatchResult(0, 0, 0, False)
        date_key = rpd_date_key(now())
        if rpd_used_today(db_path, date_key) >= profile.digest_llm_rpd:
            return LLMBatchResult(0, 0, 0, True)

        reset_stale_llm_processing(db_path, now=now(), older_than_minutes=_STALE_PROCESSING_MIN)
        ready_iso = now().isoformat(timespec="seconds")
        batch = claim_batch(db_path, limit=profile.digest_llm_batch_size,
                            ready_before=ready_iso, now=ready_iso)

        min_gap = 60.0 / max(1, profile.digest_llm_rpm)
        processed = failed = requeued = 0
        errors: list[str] = []
        skipped_rpd = False
        index = 0
        try:
            for index, row in enumerate(batch):
                job_id = row["job_id"]
                attempts = int(row["llm_attempts"] or 0)

                if rpd_used_today(db_path, rpd_date_key(now())) >= profile.digest_llm_rpd:
                    skipped_rpd = True
                    break

                # Load local data; missing → TERMINAL skip (not infinite retry).
                try:
                    reviewed_job = load_reviewed_job(job_id, state_root)
                    analysis = load_job_analysis(job_id, state_root)
                except FileNotFoundError as exc:
                    set_llm_status(db_path, job_id, "skipped")
                    errors.append(f"{job_id}: missing local data ({exc})")
                    continue

                # Source-aware full description (best-effort; failure → fallback text).
                desc = _fetch_full_description(
                    row["source"], row["source_job_id"], reviewed_job.description_raw)
                job_for_llm = dataclasses.replace(reviewed_job, description_raw=desc)

                called = False
                try:
                    result, err = explain_job_match_with_llm(
                        profile, job_for_llm, analysis, raise_on_rate_limit=True)
                    called = True
                    if result is None:
                        # Non-429 failure (bad output / 404 / 503): retry with backoff.
                        raise RuntimeError(err or "LLM returned no result")
                    save_analysis_llm_fields(job_id, result, state_root, db_path)
                    incr_rpd_counter(db_path, rpd_date_key(now()))
                    processed += 1
                except RateLimited:
                    # Throttled: requeue THIS job with exponential backoff, then stop
                    # the batch and requeue the rest (see finally / break below).
                    backoff = min(_LLM_MAX_BACKOFF, _LLM_BACKOFF_BASE * (2 ** attempts))
                    nxt = (now() + timedelta(seconds=backoff)).isoformat(timespec="seconds")
                    new_attempts = attempts + 1
                    if new_attempts >= _LLM_MAX_ATTEMPTS:
                        set_llm_status(db_path, job_id, "failed", attempts=new_attempts)
                        failed += 1
                    else:
                        set_llm_status(db_path, job_id, "pending",
                                       attempts=new_attempts, next_attempt_at=nxt)
                        requeued += 1
                    index += 1   # this row is handled; only rows AFTER it are unstarted
                    break
                except Exception as exc:
                    # Non-rate error: single transition — failed if exhausted, else
                    # pending with a short gap (no double-write).
                    new_attempts = attempts + 1
                    if new_attempts >= _LLM_MAX_ATTEMPTS:
                        set_llm_status(db_path, job_id, "failed", attempts=new_attempts)
                        failed += 1
                    else:
                        nxt = (now() + timedelta(seconds=min_gap)).isoformat(timespec="seconds")
                        set_llm_status(db_path, job_id, "pending",
                                       attempts=new_attempts, next_attempt_at=nxt)
                        requeued += 1
                    errors.append(f"{job_id}: {exc}")
                finally:
                    if called:
                        sleep(min_gap)   # pace only when an API call was actually made
            else:
                index = len(batch)   # loop finished without break → all rows handled
        finally:
            # Requeue every UNSTARTED claimed row (still 'processing') immediately.
            for row in batch[index:]:
                try:
                    set_llm_status(db_path, row["job_id"], "pending")
                    requeued += 1
                except Exception as exc:   # pragma: no cover
                    logger.warning("llm worker: requeue failed for %s: %s", row["job_id"], exc)

        return LLMBatchResult(processed, failed, requeued, skipped_rpd, errors)


def llm_queue_stats(*, db_path: Path) -> dict:
    """Counts for GET /digest/llm-queue."""
    conn = open_db(db_path)
    try:
        def _n(where, params=()):
            return conn.execute(f"SELECT COUNT(*) AS n FROM jobs WHERE {where}", params).fetchone()["n"]
        nxt = conn.execute(
            "SELECT MIN(llm_next_attempt_at) AS m FROM jobs WHERE llm_status='pending' "
            "AND llm_next_attempt_at IS NOT NULL").fetchone()["m"]
        stats = {
            "pending": _n("llm_status='pending'"),
            "processing": _n("llm_status='processing'"),
            "done": _n("llm_status='done'"),
            "failed": _n("llm_status='failed'"),
            "skipped": _n("llm_status='skipped'"),
            "next_attempt_at": nxt,
        }
    finally:
        conn.close()
    stats["rpd_used_today"] = rpd_used_today(db_path, rpd_date_key())
    return stats


@dataclass(frozen=True)
class EvalQueuePollResult:
    processed: int = 0
    failed: int = 0
    cancelled: int = 0
    requeued: int = 0
    quota_paused: bool = False
    errors: list[str] = field(default_factory=list)


def process_eval_queue_once(
    *,
    config: Any,
    profile: Any,
    db_path: Path,
    now: Callable[[], datetime] = datetime.now,
    sleep: Callable[[float], None] = time.sleep,
    backoff_seconds: float = _EVAL_429_BACKOFF_SECONDS,
) -> EvalQueuePollResult:
    """Process at most one qualitative eval_queue row."""
    from src.job_hunt_index import claim_qualitative_assessment, finish_qualitative_assessment, get_qualitative_index_row
    from src.job_hunt_llm import RateLimited
    from src.job_hunt_qualitative import PROMPT_VERSION, run_qualitative_assessment_pipeline

    reset_stale_eval_queue_running(db_path, now=now(), older_than_minutes=_STALE_PROCESSING_MIN)
    ready_iso = now().isoformat(timespec="seconds")
    row = claim_eval_queue_row(db_path, now=ready_iso)
    if row is None:
        return EvalQueuePollResult()

    row_id = int(row["id"])
    batch_id = row["batch_id"]
    job_id = row["job_ref"]
    token = row["claim_token"]
    retries = int(row["retries"] or 0)
    force = bool(row.get("force"))
    errors: list[str] = []

    existing_qrow = get_qualitative_index_row(db_path, job_id)
    claim = claim_qualitative_assessment(
        db_path,
        job_id,
        now=ready_iso,
        force=force or bool(existing_qrow and existing_qrow.get("status") == "error"),
        model=None,
        prompt_version=PROMPT_VERSION,
    )
    if not claim.get("claimed"):
        qrow = claim.get("row") or {}
        if qrow.get("status") == "done":
            finish_eval_queue_row(db_path, row_id, token, status="done", now=now().isoformat(timespec="seconds"))
            return EvalQueuePollResult(processed=1)
        msg = "qualitative assessment already in flight"
        finish_eval_queue_row(db_path, row_id, token, status="error", now=now().isoformat(timespec="seconds"), error_text=msg)
        return EvalQueuePollResult(failed=1, errors=[f"{job_id}: {msg}"])

    try:
        result = run_qualitative_assessment_pipeline(
            job_id=job_id,
            profile=profile,
            state_root=config.state_root,
            db_path=db_path,
            before_persist=lambda: not is_eval_batch_cancel_requested(db_path, batch_id),
        )
    except LLMQuotaExhausted as exc:
        msg = str(exc) or "daily LLM quota exhausted - try tomorrow"
        release_qualitative_assessment_claim(db_path, job_id, previous_row=existing_qrow)
        return_eval_queue_row_to_pending(db_path, row_id, token, error_text=msg)
        pause_eval_batch_for_quota(db_path, batch_id, now=now().isoformat(timespec="seconds"), error_text=msg)
        return EvalQueuePollResult(quota_paused=True, errors=[f"{job_id}: {msg}"])
    except RateLimited as exc:
        msg = str(exc) or "Gemini rate limited (429)"
        new_retries = retries + 1
        if new_retries >= _EVAL_MAX_ATTEMPTS:
            finish_qualitative_assessment(db_path, job_id, status="error", prompt_version=PROMPT_VERSION, error_text=msg)
            finish_eval_queue_row(
                db_path, row_id, token, status="error", now=now().isoformat(timespec="seconds"),
                error_text=msg, retries=new_retries,
            )
            return EvalQueuePollResult(failed=1, errors=[f"{job_id}: {msg}"])
        requeue_eval_queue_row(
            db_path, row_id, token, now=now().isoformat(timespec="seconds"),
            retries=new_retries, error_text=msg,
        )
        finish_qualitative_assessment(db_path, job_id, status="error", prompt_version=PROMPT_VERSION, error_text=msg)
        sleep(backoff_seconds)
        return EvalQueuePollResult(requeued=1, errors=[f"{job_id}: {msg}"])
    except Exception as exc:
        msg = str(exc) or exc.__class__.__name__
        finish_qualitative_assessment(db_path, job_id, status="error", prompt_version=PROMPT_VERSION, error_text=msg)
        finish_eval_queue_row(db_path, row_id, token, status="error", now=now().isoformat(timespec="seconds"), error_text=msg)
        return EvalQueuePollResult(failed=1, errors=[f"{job_id}: {msg}"])

    if not result.ok and result.error == "cancelled before persist":
        finish_eval_queue_row(db_path, row_id, token, status="cancelled", now=now().isoformat(timespec="seconds"))
        return EvalQueuePollResult(cancelled=1)
    if result.ok:
        finish_eval_queue_row(db_path, row_id, token, status="done", now=now().isoformat(timespec="seconds"))
        return EvalQueuePollResult(processed=1)
    msg = result.error or "qualitative assessment failed"
    finish_eval_queue_row(db_path, row_id, token, status="error", now=now().isoformat(timespec="seconds"), error_text=msg)
    errors.append(f"{job_id}: {msg}")
    return EvalQueuePollResult(failed=1, errors=errors)


class LLMQueueWorker:
    """Daemon thread that drains the LLM queue in paced batches every
    ``digest_llm_batch_interval_min`` minutes. Reads fresh profile each cycle; an
    exception in a cycle never kills the thread. No-ops while disabled / no key."""

    def __init__(self, config: Any, *, get_profile: Callable[[], Any]):
        self._config = config
        self._get_profile = get_profile
        self._db_path = Path(config.state_root) / "job_hunt_index.db"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        # Recover any crashed claims from a previous run before polling.
        try:
            reset_stale_llm_processing(self._db_path, now=datetime.now(),
                                       older_than_minutes=_STALE_PROCESSING_MIN)
            reset_stale_eval_queue_running(self._db_path, now=datetime.now(),
                                           older_than_minutes=_STALE_PROCESSING_MIN)
        except Exception as exc:  # pragma: no cover
            logger.warning("llm worker: startup stale-reset failed: %s", exc)
        self._thread = threading.Thread(target=self._loop, name="LLMQueueWorker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _has_key(self) -> bool:
        import os
        return bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                profile = self._get_profile()
                if self._has_key():
                    if getattr(profile, "digest_llm_enabled", False):
                        drain_llm_batch(config=self._config, profile=profile, db_path=self._db_path)
                    process_eval_queue_once(config=self._config, profile=profile, db_path=self._db_path)
                interval = max(1, int(getattr(profile, "digest_llm_batch_interval_min", 15)))
            except Exception as exc:
                logger.warning("llm worker: cycle failed: %s", exc)
                interval = 15
            self._stop.wait(timeout=interval * 60)


# ===========================================================================
# D5 — DigestScheduler daemon (automatic daily fetch+score run)
# ===========================================================================

_SCHEDULER_POLL_SECONDS = 30   # poll cadence — picks up run_time/enable changes promptly


class DigestScheduler:
    """Daemon thread that runs ``run_digest_pipeline`` once per local calendar day
    at ``profile.digest_run_time``. Poll-based (every ~30s) so config changes apply
    promptly and an early/spurious wake can't double-run. An exception in a run is
    logged and never kills the thread (D5 review)."""

    def __init__(self, config: Any, *, get_profile: Callable[[], Any]):
        self._config = config
        self._get_profile = get_profile
        self._db_path = Path(config.state_root) / "job_hunt_index.db"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_run_date: str | None = None     # local date of the last run (once/day guard)
        self._last_result: DigestRunResult | None = None
        self._last_error: str | None = None
        self._running = False

    # -- lifecycle --
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="DigestScheduler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # -- status snapshot (lock-guarded; read by HTTP threads) --
    def status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "last_run": self._last_result.to_dict() if self._last_result else None,
                "last_run_date": self._last_run_date,
                "last_error": self._last_error,
                "next_run": self._compute_next_run_iso(),
            }

    def _compute_next_run_iso(self) -> str | None:
        try:
            profile = self._get_profile()
            hh, mm = (int(x) for x in str(profile.digest_run_time).split(":"))
        except Exception:
            return None
        now = datetime.now()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        # If today's slot already passed AND we already ran today, next is tomorrow.
        if target <= now and self._last_run_date == now.date().isoformat():
            target = target + timedelta(days=1)
        elif target <= now and self._last_run_date != now.date().isoformat():
            # slot passed but not yet run today → it's due now
            return now.isoformat(timespec="seconds")
        return target.isoformat(timespec="seconds")

    # -- main loop --
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._maybe_run()
            except Exception as exc:   # belt-and-braces: never let the daemon die
                logger.warning("digest scheduler: loop error: %s", exc)
            self._stop.wait(timeout=_SCHEDULER_POLL_SECONDS)

    def _maybe_run(self) -> None:
        now = datetime.now()
        today = now.date().isoformat()
        if self._last_run_date == today:
            return   # already ran today — exactly-once-per-day guard
        try:
            profile = self._get_profile()
        except Exception as exc:
            logger.warning("digest scheduler: could not load profile: %s", exc)
            return
        if not getattr(profile, "digest_enabled", False):
            return
        try:
            hh, mm = (int(x) for x in str(profile.digest_run_time).split(":"))
        except (ValueError, AttributeError):
            return   # invalid time (shouldn't happen — validated on save); wait for a fix
        if (now.hour, now.minute) < (hh, mm):
            return   # not yet time today

        # Reserve today's slot BEFORE running so a long run / fast loop can't double-fire.
        with self._lock:
            if self._last_run_date == today:
                return
            self._last_run_date = today
            self._running = True
        try:
            from src.job_hunt_saved_searches import list_saved_searches
            searches = [s for s in list_saved_searches(state_root=self._config.state_root)
                        if getattr(s, "enabled", True)]
            result = run_digest_pipeline(config=self._config, saved_searches=searches,
                                         profile=profile, db_path=self._db_path)
            with self._lock:
                self._last_result = result
                self._last_error = None
            logger.info("digest scheduler: ran %s searches, %s new jobs",
                        result.searches_run, result.jobs_new)
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            logger.warning("digest scheduler: run failed: %s", exc)
        finally:
            with self._lock:
                self._running = False
