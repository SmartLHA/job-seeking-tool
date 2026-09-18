"""Tests for Daily Job Digest phase D6 — the paced LLM worker (drain_llm_batch) and
the RateLimited client signal. Gemini is always monkeypatched (no network)."""
from __future__ import annotations

import types
from datetime import datetime

import pytest

import src.job_hunt_llm as llm
import src.job_hunt_scheduler as scheduler
from src.job_hunt_scheduler import drain_llm_batch, llm_queue_stats, rpd_date_key
from src.job_hunt_evaluation import evaluate_reviewed_job
from src.job_hunt_index import incr_rpd_counter, open_db, set_llm_status, upsert_job
from src.job_hunt_models import JobPosting
from src.job_hunt_profile import candidate_profile_from_dict
from src.job_hunt_storage import (
    ensure_storage_layout,
    load_job_analysis,
    save_job_analysis,
    save_reviewed_job,
)

NOW = lambda: datetime(2026, 6, 24, 12, 0, 0)
NOSLEEP = lambda s: None


def _profile(**kw):
    base = dict(candidate_id="cand-001", skills=["python"], digest_llm_enabled=True,
                digest_llm_rpd=200, digest_llm_batch_size=4, digest_llm_rpm=4)
    base.update(kw)
    return candidate_profile_from_dict(base)


def _cfg(tmp_path):
    ensure_storage_layout(tmp_path)
    db = tmp_path / "job_hunt_index.db"
    open_db(db).close()
    return types.SimpleNamespace(state_root=tmp_path), db


def _seed(state_root, db, job_id="reed-1", source="reed", sjid="1", score=85, on_disk=True):
    if on_disk:
        job = JobPosting(job_id=job_id, job_title="BA", company="Co",
                         description_raw="Need python and sql.", source_type=source,
                         source_ref=None, location="London", work_mode=None,
                         employment_type=None, source_job_id=sjid)
        save_reviewed_job(job, state_root)
        analysis = evaluate_reviewed_job(_profile(), job)
        save_job_analysis(analysis, state_root)
    upsert_job(db, {"job_id": job_id, "job_title": "BA", "company": "Co", "source": source,
                    "source_job_id": sjid, "match_score": score, "status": "not_applied"})
    set_llm_status(db, job_id, "pending")


def _patch_llm(monkeypatch, fn):
    monkeypatch.setattr(llm, "explain_job_match_with_llm", fn)


def _ok_result(*a, **k):
    return {"fit": "Strong fit", "risk": "Low", "action": "Apply", "model_used": "gemini-x"}, None


# --------------------------------------------------------------------------- #

def test_drain_processes_and_saves_llm_fields(tmp_path, monkeypatch):
    cfg, db = _cfg(tmp_path)
    _seed(cfg.state_root, db)
    _patch_llm(monkeypatch, _ok_result)
    r = drain_llm_batch(config=cfg, profile=_profile(), db_path=db, now=NOW, sleep=NOSLEEP)
    assert r.processed == 1 and r.failed == 0
    a = load_job_analysis("reed-1", cfg.state_root)
    assert a.llm_fit_summary == "Strong fit" and a.llm_model == "gemini-x"
    conn = open_db(db)
    try:
        assert conn.execute("SELECT llm_status FROM jobs WHERE job_id='reed-1'").fetchone()["llm_status"] == "done"
    finally:
        conn.close()
    assert llm_queue_stats(db_path=db)["done"] == 1


def test_drain_paces_with_min_gap(tmp_path, monkeypatch):
    cfg, db = _cfg(tmp_path)
    _seed(cfg.state_root, db, "reed-1", sjid="1")
    _seed(cfg.state_root, db, "reed-2", sjid="2")
    _patch_llm(monkeypatch, _ok_result)
    sleeps = []
    drain_llm_batch(config=cfg, profile=_profile(digest_llm_rpm=4), db_path=db,
                    now=NOW, sleep=lambda s: sleeps.append(s))
    assert sleeps and all(abs(s - 15.0) < 0.001 for s in sleeps)  # 60/4 = 15s


def test_drain_disabled_noop(tmp_path, monkeypatch):
    cfg, db = _cfg(tmp_path)
    _seed(cfg.state_root, db)
    r = drain_llm_batch(config=cfg, profile=_profile(digest_llm_enabled=False), db_path=db, now=NOW, sleep=NOSLEEP)
    assert r.processed == 0


def test_drain_daily_cap_stops(tmp_path, monkeypatch):
    cfg, db = _cfg(tmp_path)
    _seed(cfg.state_root, db)
    for _ in range(5):
        incr_rpd_counter(db, rpd_date_key(NOW()))
    _patch_llm(monkeypatch, _ok_result)
    r = drain_llm_batch(config=cfg, profile=_profile(digest_llm_rpd=5), db_path=db, now=NOW, sleep=NOSLEEP)
    assert r.skipped_rpd is True and r.processed == 0


def test_rate_limited_backoff_and_requeue_unstarted(tmp_path, monkeypatch):
    cfg, db = _cfg(tmp_path)
    _seed(cfg.state_root, db, "reed-1", sjid="1", score=90)
    _seed(cfg.state_root, db, "reed-2", sjid="2", score=80)
    def _raise(*a, **k):
        raise llm.RateLimited("429")
    _patch_llm(monkeypatch, _raise)
    r = drain_llm_batch(config=cfg, profile=_profile(), db_path=db, now=NOW, sleep=NOSLEEP)
    assert r.processed == 0
    # both back to pending (the throttled one with backoff, the unstarted one immediately)
    conn = open_db(db)
    try:
        rows = {x["job_id"]: x for x in conn.execute("SELECT * FROM jobs").fetchall()}
    finally:
        conn.close()
    assert rows["reed-1"]["llm_status"] == "pending" and rows["reed-1"]["llm_attempts"] == 1
    assert rows["reed-1"]["llm_next_attempt_at"] is not None        # backoff gate set
    assert rows["reed-2"]["llm_status"] == "pending" and rows["reed-2"]["llm_attempts"] == 0  # not bumped


def test_rate_limited_max_attempts_fails(tmp_path, monkeypatch):
    cfg, db = _cfg(tmp_path)
    _seed(cfg.state_root, db, "reed-1", sjid="1")
    # pre-set attempts to one below the cap
    conn = open_db(db)
    conn.execute("UPDATE jobs SET llm_attempts=4 WHERE job_id='reed-1'")
    conn.commit(); conn.close()
    def _raise(*a, **k):
        raise llm.RateLimited("429")
    _patch_llm(monkeypatch, _raise)
    r = drain_llm_batch(config=cfg, profile=_profile(), db_path=db, now=NOW, sleep=NOSLEEP)
    assert r.failed == 1
    conn = open_db(db)
    try:
        assert conn.execute("SELECT llm_status FROM jobs WHERE job_id='reed-1'").fetchone()["llm_status"] == "failed"
    finally:
        conn.close()


def test_missing_local_data_is_terminal_skip(tmp_path, monkeypatch):
    cfg, db = _cfg(tmp_path)
    _seed(cfg.state_root, db, "reed-1", sjid="1", on_disk=False)   # indexed + pending, no JSON
    _patch_llm(monkeypatch, _ok_result)
    r = drain_llm_batch(config=cfg, profile=_profile(), db_path=db, now=NOW, sleep=NOSLEEP)
    conn = open_db(db)
    try:
        assert conn.execute("SELECT llm_status FROM jobs WHERE job_id='reed-1'").fetchone()["llm_status"] == "skipped"
    finally:
        conn.close()
    assert r.processed == 0


def test_non_rate_error_requeues_then_retryable(tmp_path, monkeypatch):
    cfg, db = _cfg(tmp_path)
    _seed(cfg.state_root, db, "reed-1", sjid="1")
    _patch_llm(monkeypatch, lambda *a, **k: (None, "bad output"))   # non-429 failure
    r = drain_llm_batch(config=cfg, profile=_profile(), db_path=db, now=NOW, sleep=NOSLEEP)
    assert r.requeued >= 1
    conn = open_db(db)
    try:
        row = conn.execute("SELECT * FROM jobs WHERE job_id='reed-1'").fetchone()
    finally:
        conn.close()
    assert row["llm_status"] == "pending" and row["llm_attempts"] == 1


def test_source_aware_detail_reed_vs_adzuna(tmp_path, monkeypatch):
    cfg, db = _cfg(tmp_path)
    _seed(cfg.state_root, db, "reed-1", source="reed", sjid="99")
    _seed(cfg.state_root, db, "adzuna-1", source="adzuna", sjid="99")
    called = {"reed": 0}
    monkeypatch.setattr("src.job_sources.reed_client.fetch_reed_job_detail",
                        lambda sjid: called.__setitem__("reed", called["reed"] + 1) or {"jobDescription": "<p>full reed desc</p>"})
    _patch_llm(monkeypatch, _ok_result)
    drain_llm_batch(config=cfg, profile=_profile(digest_llm_batch_size=4), db_path=db, now=NOW, sleep=NOSLEEP)
    assert called["reed"] == 1   # Reed fetched detail; Adzuna did not (no extra call)


# --------------------------------------------------------------------------- #
# RateLimited client signal
# --------------------------------------------------------------------------- #

def test_explain_raises_ratelimited_only_when_all_429(monkeypatch):
    prof = _profile(); job = JobPosting(job_id="x-1", job_title="BA", company="Co",
        description_raw="d", source_type="reed", source_ref=None, location=None,
        work_mode=None, employment_type=None)
    analysis = evaluate_reviewed_job(prof, job)
    # all attempts 429 → raises with raise_on_rate_limit
    monkeypatch.setattr(llm, "_call_gemini_reasoning", lambda p: (None, "rate limited", None, True))
    with pytest.raises(llm.RateLimited):
        llm.explain_job_match_with_llm(prof, job, analysis, raise_on_rate_limit=True)
    # mixed failure (all_rate_limited False) → returns error, no raise
    monkeypatch.setattr(llm, "_call_gemini_reasoning", lambda p: (None, "503", None, False))
    result, err = llm.explain_job_match_with_llm(prof, job, analysis, raise_on_rate_limit=True)
    assert result is None and err == "503"
