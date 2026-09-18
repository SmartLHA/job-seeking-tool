"""Tests for OQ-2 — re-evaluate seen digest jobs against the current profile/threshold.

Covers the surfacing logic (crossed-up resurface + LLM re-queue, stayed-above no-op,
dropped-below dequeue), the LLM re-queue cap, the compare-and-swap guards on the new
index helpers (so a concurrent worker can't be raced into double-processing), missing
local JSON handling, pipeline-status preservation, and the POST /digest/reevaluate route.

All deterministic + offline: jobs are seeded directly into the SQLite index with a real
reviewed_job JSON on disk, so the re-score can load + re-evaluate them with no network.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

from src.job_hunt_evaluation import evaluate_reviewed_job
from src.job_hunt_index import (
    clear_llm_queue,
    list_digest_jobs_for_reeval,
    open_db,
    requeue_llm_if_eligible,
    set_digest_meta,
    set_llm_status,
    upsert_job,
)
from src.job_hunt_profile import candidate_profile_from_dict, save_candidate_profile
from src.job_hunt_reviewed_input import reviewed_job_from_dict
from src.job_hunt_scheduler import reevaluate_digest_jobs
from src.job_hunt_storage import ensure_storage_layout, save_reviewed_job
from src.ui_routes import _build_handler
from src.ui_state import UIServerConfig


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

import types


def _profile(threshold, *, llm=True, cap=10, skills=("python", "sql")):
    return candidate_profile_from_dict({
        "candidate_id": "cand-001",
        "skills": list(skills),
        "target_roles": ["Data Analyst"],
        "locations": ["London"],
        "digest_threshold": threshold,
        "digest_llm_enabled": llm,
        "digest_max_llm_per_run": cap,
    })


def _setup(tmp_path):
    ensure_storage_layout(tmp_path)
    db = tmp_path / "job_hunt_index.db"
    open_db(db).close()
    config = types.SimpleNamespace(state_root=tmp_path, profile_path=tmp_path / "p.json")
    return config, db


def _reviewed(job_id, *, req=("python", "sql"), pref=("excel",), sjid=None):
    """Build + return a JobPosting (NOT yet saved)."""
    return reviewed_job_from_dict({
        "job_id": job_id,
        "job_title": "Data Analyst",
        "company": "Acme",
        "description_raw": "We need python and sql for analytics.",
        "source_type": "stub",
        "location": "London",
        "required_skills": list(req),
        "preferred_skills": list(pref),
        "salary_min_gbp": 50000,
        "salary_max_gbp": 60000,
        "url": f"https://acme/jobs/{job_id}",
        "source_job_id": sjid or job_id,
    })


def _seed(config, db, job_id, *, old_score, llm_status, seen, status="not_applied",
          req=("python", "sql"), save_json=True, ssid="s1"):
    """Seed one digest row + (optionally) its reviewed_job JSON, with full control over
    the OLD match_score, the llm_status, and the seen flag."""
    job = _reviewed(job_id, req=req)
    if save_json:
        save_reviewed_job(job, config.state_root)
    upsert_job(db, {
        "job_id": job_id, "job_title": job.job_title, "company": job.company,
        "location": job.location, "source": "stub", "source_job_id": job.source_job_id,
        "apply_url": job.url, "match_score": old_score, "decision": "review",
        "status": status,
    })
    set_digest_meta(db, job_id, digest_date="2026-06-20", seen=seen, saved_search_id=ssid)
    if llm_status is not None:
        if llm_status == "processing":
            # set_llm_status forbids 'processing' (owned by claim_batch) — set directly.
            conn = open_db(db)
            try:
                conn.execute("UPDATE jobs SET llm_status='processing' WHERE job_id=?", (job_id,))
                conn.commit()
            finally:
                conn.close()
        else:
            set_llm_status(db, job_id, llm_status)
    return job


def _read(db, job_id):
    conn = open_db(db)
    try:
        return dict(conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())
    finally:
        conn.close()


def _new_score(profile, job):
    return evaluate_reviewed_job(profile, job).match_score


# --------------------------------------------------------------------------- #
# Surfacing logic
# --------------------------------------------------------------------------- #

def test_crossed_up_via_never_queued_resurfaces_and_requeues(tmp_path):
    """Threshold-lowered / never-enriched case: a SEEN job that now qualifies and was
    never queued for AI (llm NULL) is resurfaced and re-queued."""
    config, db = _setup(tmp_path)
    job = _seed(config, db, "j1", old_score=88, llm_status=None, seen=True)
    prof = _profile(threshold=0)            # everything qualifies now
    r = reevaluate_digest_jobs(config=config, profile=prof, db_path=db)
    row = _read(db, "j1")
    assert r.jobs_rescored == 1
    assert r.jobs_resurfaced == 1 and row["digest_seen"] == 0
    assert r.jobs_llm_requeued == 1 and row["llm_status"] == "pending"


def test_crossed_up_via_score_with_prior_failed(tmp_path):
    """Score-based crossing independent of llm state: a previously-failed job whose
    OLD score sat below the bar but now scores at/above it is resurfaced + re-queued
    ('failed' is CAS-eligible)."""
    config, db = _setup(tmp_path)
    prof_skills = _profile(threshold=0)
    ns = _new_score(prof_skills, _reviewed("j1"))      # the score it will get now
    job = _seed(config, db, "j1", old_score=ns - 1, llm_status="failed", seen=True)
    prof = _profile(threshold=ns)                       # old (ns-1) below, new (ns) at bar
    r = reevaluate_digest_jobs(config=config, profile=prof, db_path=db)
    row = _read(db, "j1")
    assert r.jobs_resurfaced == 1 and row["digest_seen"] == 0
    assert r.jobs_llm_requeued == 1 and row["llm_status"] == "pending"
    assert row["llm_attempts"] == 0                     # retry budget reset


def test_stayed_above_done_not_resurfaced(tmp_path):
    """A job already handled as a match (llm 'done') that stays above threshold is left
    alone — no unread nag, no re-queue (OQ-2-A)."""
    config, db = _setup(tmp_path)
    _seed(config, db, "j1", old_score=88, llm_status="done", seen=True)
    prof = _profile(threshold=0)
    r = reevaluate_digest_jobs(config=config, profile=prof, db_path=db)
    row = _read(db, "j1")
    assert r.jobs_rescored == 1
    assert r.jobs_resurfaced == 0 and row["digest_seen"] == 1
    assert r.jobs_llm_requeued == 0 and row["llm_status"] == "done"


def test_dropped_below_dequeues_pending(tmp_path):
    """A job that no longer qualifies and had an un-started 'pending' AI job gets
    de-queued (llm -> NULL)."""
    config, db = _setup(tmp_path)
    # Non-matching skills → low score; threshold 100 keeps it below.
    _seed(config, db, "j1", old_score=40, llm_status="pending", seen=False, req=("cobol",))
    prof = _profile(threshold=100)
    r = reevaluate_digest_jobs(config=config, profile=prof, db_path=db)
    row = _read(db, "j1")
    assert r.jobs_dequeued == 1 and row["llm_status"] is None
    assert r.jobs_resurfaced == 0


def test_llm_requeue_cap_honoured(tmp_path):
    """All crossed-up jobs resurface, but only `digest_max_llm_per_run` get re-queued."""
    config, db = _setup(tmp_path)
    for i in range(3):
        _seed(config, db, f"j{i}", old_score=88, llm_status=None, seen=True)
    prof = _profile(threshold=0, cap=1)
    r = reevaluate_digest_jobs(config=config, profile=prof, db_path=db)
    assert r.jobs_resurfaced == 3
    assert r.jobs_llm_requeued == 1
    pending = sum(1 for jid in ("j0", "j1", "j2") if _read(db, jid)["llm_status"] == "pending")
    assert pending == 1


def test_llm_disabled_resurfaces_without_requeue(tmp_path):
    config, db = _setup(tmp_path)
    _seed(config, db, "j1", old_score=88, llm_status=None, seen=True)
    prof = _profile(threshold=0, llm=False)
    r = reevaluate_digest_jobs(config=config, profile=prof, db_path=db)
    row = _read(db, "j1")
    assert r.jobs_resurfaced == 1 and row["digest_seen"] == 0
    assert r.jobs_llm_requeued == 0 and row["llm_status"] is None


def test_missing_reviewed_json_skipped_others_rescored(tmp_path):
    config, db = _setup(tmp_path)
    _seed(config, db, "gone", old_score=88, llm_status=None, seen=True, save_json=False)
    _seed(config, db, "ok", old_score=88, llm_status=None, seen=True)
    prof = _profile(threshold=0)
    r = reevaluate_digest_jobs(config=config, profile=prof, db_path=db)
    assert r.jobs_missing == 1
    assert r.jobs_rescored == 1
    assert _read(db, "ok")["digest_seen"] == 0


def test_pipeline_status_preserved(tmp_path):
    """Re-score must not reset where the user moved the card on the board."""
    config, db = _setup(tmp_path)
    _seed(config, db, "j1", old_score=88, llm_status=None, seen=True, status="applied")
    prof = _profile(threshold=0)
    reevaluate_digest_jobs(config=config, profile=prof, db_path=db)
    assert _read(db, "j1")["status"] == "applied"


def test_non_digest_rows_untouched(tmp_path):
    """A plain (non-digest) job row is never examined."""
    config, db = _setup(tmp_path)
    upsert_job(db, {"job_id": "plain", "job_title": "X", "company": "Y", "source": "stub",
                    "match_score": 10, "status": "not_applied"})   # no digest_date
    _seed(config, db, "j1", old_score=88, llm_status=None, seen=True)
    prof = _profile(threshold=0)
    r = reevaluate_digest_jobs(config=config, profile=prof, db_path=db)
    assert r.jobs_examined == 1                      # only the digest row
    assert _read(db, "plain")["match_score"] == 10   # unchanged


# --------------------------------------------------------------------------- #
# Compare-and-swap guards (concurrency safety vs the LLM worker)
# --------------------------------------------------------------------------- #

def test_requeue_cas_eligible_states(tmp_path):
    config, db = _setup(tmp_path)
    for st in (None, "failed", "skipped", "done"):
        jid = f"j-{st}"
        _seed(config, db, jid, old_score=88, llm_status=st, seen=True)
        assert requeue_llm_if_eligible(db, jid) == 1
        assert _read(db, jid)["llm_status"] == "pending"


def test_requeue_cas_blocks_pending_and_processing(tmp_path):
    config, db = _setup(tmp_path)
    _seed(config, db, "p", old_score=88, llm_status="pending", seen=True)
    _seed(config, db, "x", old_score=88, llm_status="processing", seen=True)
    assert requeue_llm_if_eligible(db, "p") == 0
    assert requeue_llm_if_eligible(db, "x") == 0
    assert _read(db, "p")["llm_status"] == "pending"
    assert _read(db, "x")["llm_status"] == "processing"   # in-flight claim untouched


def test_clear_llm_queue_cas(tmp_path):
    config, db = _setup(tmp_path)
    _seed(config, db, "p", old_score=10, llm_status="pending", seen=False)
    _seed(config, db, "x", old_score=10, llm_status="processing", seen=False)
    assert clear_llm_queue(db, "p") == 1 and _read(db, "p")["llm_status"] is None
    assert clear_llm_queue(db, "x") == 0 and _read(db, "x")["llm_status"] == "processing"


def test_list_for_reeval_only_digest_rows_ordered(tmp_path):
    config, db = _setup(tmp_path)
    _seed(config, db, "low", old_score=10, llm_status=None, seen=True)
    _seed(config, db, "high", old_score=95, llm_status=None, seen=True)
    upsert_job(db, {"job_id": "plain", "job_title": "X", "company": "Y", "source": "stub",
                    "match_score": 99, "status": "not_applied"})
    rows = list_digest_jobs_for_reeval(db)
    assert [r["job_id"] for r in rows] == ["high", "low"]   # digest-only, score DESC


# --------------------------------------------------------------------------- #
# Route
# --------------------------------------------------------------------------- #

@contextmanager
def _server(tmp_path):
    config = UIServerConfig(profile_path=tmp_path / "p.json", state_root=tmp_path / "state",
                            report_dir=tmp_path / "rep", host="127.0.0.1", port=0)
    srv = ThreadingHTTPServer((config.host, config.port), _build_handler(config))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", config
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def _post(url, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_route_reevaluate_returns_counters(tmp_path):
    with _server(tmp_path) as (base, config):
        ensure_storage_layout(config.state_root)
        save_candidate_profile(_profile(threshold=0), config.profile_path)
        db = config.state_root / "job_hunt_index.db"
        cfg = types.SimpleNamespace(state_root=config.state_root)
        _seed(cfg, db, "j1", old_score=88, llm_status=None, seen=True)
        st, body = _post(base + "/digest/reevaluate", {})
        assert st == 200 and body["ok"] is True
        assert body["jobs_rescored"] == 1 and body["jobs_resurfaced"] == 1
        assert _read(db, "j1")["digest_seen"] == 0
