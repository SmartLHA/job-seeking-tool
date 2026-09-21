"""Tests for Daily Job Digest phase D2 — schema migration, dedup, digest queries,
and LLM-queue primitives. Covers the design-council v6 additions: source_job_id
normalization, cross-source isolation, fail-loud unique-index invariant, and the
WAL/migration safety contract.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer

import pytest

from src.ui_state import UIServerConfig
from src.ui_routes import _build_handler

from src.job_hunt_index import (
    claim_batch,
    incr_rpd_counter,
    is_already_indexed,
    open_db,
    reset_stale_llm_processing,
    rpd_used_today,
    set_digest_meta,
    set_llm_status,
    upsert_job,
)
from src.job_hunt_digest import (
    DigestEntry,
    digest_stats,
    mark_all_seen,
    mark_seen,
    query_digest,
    unseen_count,
)
from src.ui_utils import digest_job_id
from src.job_hunt_reviewed_input import reviewed_job_from_dict, reviewed_job_to_dict


def _db(tmp_path):
    return tmp_path / "job_hunt_index.db"


def _row(job_id, source, source_job_id, score=80, **kw):
    base = {
        "job_id": job_id, "job_title": "BA", "company": "Co", "location": "London",
        "source": source, "source_job_id": source_job_id, "apply_url": f"https://x/{source_job_id}",
        "match_score": score, "decision": "apply", "status": "not_applied",
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
# Migration / schema
# --------------------------------------------------------------------------- #

def test_migration_adds_all_columns(tmp_path):
    conn = open_db(_db(tmp_path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    conn.close()
    for c in ("source_job_id", "apply_url", "digest_date", "digest_seen",
              "saved_search_id", "llm_status", "llm_attempts", "llm_next_attempt_at",
              "llm_claimed_at", "llm_claim_token"):
        assert c in cols


def test_migration_idempotent(tmp_path):
    db = _db(tmp_path)
    open_db(db).close()
    open_db(db).close()  # second open must not error
    conn = open_db(db)
    assert conn.execute("SELECT count FROM llm_rpd WHERE 0").fetchall() == []
    conn.close()


def test_migration_upgrades_legacy_db(tmp_path):
    db = _db(tmp_path)
    # legacy DB: the original 14-column base schema, no digest columns yet
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE jobs (job_id TEXT PRIMARY KEY, job_title TEXT, company TEXT, "
        "location TEXT, source TEXT, match_score REAL, decision TEXT, user_decision TEXT, "
        "ats_score INTEGER, tailoring_ready INTEGER, status TEXT NOT NULL DEFAULT 'not_applied', "
        "updated_at TEXT, salary_min INTEGER, salary_max INTEGER)"
    )
    conn.execute("INSERT INTO jobs (job_id, job_title, source) VALUES ('old-1', 'Legacy', 'reed')")
    conn.commit()
    conn.close()
    conn = open_db(db)
    try:
        row = conn.execute("SELECT digest_seen, source_job_id FROM jobs WHERE job_id='old-1'").fetchone()
        assert row["digest_seen"] == 0      # INTEGER DEFAULT 0 backfills to 0, not NULL
        assert row["source_job_id"] is None
    finally:
        conn.close()


def test_partial_unique_index_present(tmp_path):
    conn = open_db(_db(tmp_path))
    idx = {r[1] for r in conn.execute("PRAGMA index_list(jobs)")}
    conn.close()
    assert "idx_jobs_source_source_job_id" in idx


# --------------------------------------------------------------------------- #
# Dedup + normalization (Codex High)
# --------------------------------------------------------------------------- #

def test_is_already_indexed_after_upsert(tmp_path):
    db = _db(tmp_path)
    upsert_job(db, _row("reed-123", "reed", "123"))
    assert is_already_indexed(db, "reed", "123") is True
    assert is_already_indexed(db, "reed", "999") is False


def test_source_lowercased_for_dedup(tmp_path):
    db = _db(tmp_path)
    upsert_job(db, _row("reed-123", "Reed", "123"))   # mixed-case source
    assert is_already_indexed(db, "reed", "123") is True
    assert is_already_indexed(db, "REED", "123") is True


def test_source_job_id_int_and_str_collide(tmp_path):
    db = _db(tmp_path)
    upsert_job(db, _row("reed-123", "reed", 12345678))   # int id
    assert is_already_indexed(db, "reed", "12345678") is True  # stored as "12345678"


def test_source_job_id_whitespace_normalized(tmp_path):
    db = _db(tmp_path)
    upsert_job(db, _row("reed-123", "reed", "  123  "))
    assert is_already_indexed(db, "reed", "123") is True
    assert is_already_indexed(db, "reed", "  123  ") is True   # helper strips too


def test_blank_source_job_id_not_dedupable(tmp_path):
    db = _db(tmp_path)
    assert is_already_indexed(db, "reed", "") is False
    assert is_already_indexed(db, "reed", "   ") is False


def test_cross_source_same_id_are_distinct(tmp_path):
    db = _db(tmp_path)
    upsert_job(db, _row("reed-123", "reed", "123", score=90))
    upsert_job(db, _row("adzuna-123", "adzuna", "123", score=70))
    set_digest_meta(db, "reed-123", digest_date="2026-06-24")
    set_digest_meta(db, "adzuna-123", digest_date="2026-06-24")
    entries = query_digest(db_path=db)
    assert len(entries) == 2
    assert {e.job_id for e in entries} == {"reed-123", "adzuna-123"}
    assert {e.source_id for e in entries} == {"reed", "adzuna"}


def test_upsert_fail_loud_on_unique_violation(tmp_path):
    db = _db(tmp_path)
    upsert_job(db, _row("reed-123", "reed", "123"))
    # same (source, source_job_id) under a DIFFERENT job_id → canonical-id drift
    with pytest.raises(sqlite3.IntegrityError):
        upsert_job(db, _row("some-other-id", "reed", "123"))


# --------------------------------------------------------------------------- #
# upsert preserves digest + llm columns on re-index (C6)
# --------------------------------------------------------------------------- #

def test_reupsert_preserves_digest_and_llm_columns(tmp_path):
    db = _db(tmp_path)
    upsert_job(db, _row("reed-1", "reed", "1"))
    set_digest_meta(db, "reed-1", digest_date="2026-06-24", saved_search_id="ss-1")
    set_llm_status(db, "reed-1", "pending")
    # re-index the same job (e.g. user records an outcome) — must not wipe digest/llm
    upsert_job(db, _row("reed-1", "reed", "1", score=55, status="applied"))
    conn = open_db(db)
    try:
        r = conn.execute("SELECT * FROM jobs WHERE job_id='reed-1'").fetchone()
    finally:
        conn.close()
    assert r["digest_date"] == "2026-06-24"
    assert r["saved_search_id"] == "ss-1"
    assert r["llm_status"] == "pending"
    assert r["status"] == "applied"      # eval column DID update
    assert r["match_score"] == 55


# --------------------------------------------------------------------------- #
# digest_job_id
# --------------------------------------------------------------------------- #

def test_digest_job_id_canonical(tmp_path):
    assert digest_job_id("Reed", " 123 ") == "reed-123"
    assert digest_job_id("reed", "123") == digest_job_id("REED", "123")


def test_digest_job_id_blank_raises():
    with pytest.raises(ValueError):
        digest_job_id("", "123")
    with pytest.raises(ValueError):
        digest_job_id("reed", "  ")


# --------------------------------------------------------------------------- #
# digest queries
# --------------------------------------------------------------------------- #

def _seed_digest(db):
    upsert_job(db, _row("reed-1", "reed", "1", score=90))
    upsert_job(db, _row("reed-2", "reed", "2", score=60))
    upsert_job(db, _row("reed-3", "reed", "3", score=80))
    upsert_job(db, _row("manual-x", "manual", None))   # NOT a digest row
    set_digest_meta(db, "reed-1", digest_date="2026-06-24")
    set_digest_meta(db, "reed-2", digest_date="2026-06-24")
    set_digest_meta(db, "reed-3", digest_date="2026-06-23")


def test_query_digest_only_digest_rows_sorted(tmp_path):
    db = _db(tmp_path)
    _seed_digest(db)
    entries = query_digest(db_path=db)
    assert [e.job_id for e in entries] == ["reed-1", "reed-3", "reed-2"]  # score desc
    assert all(isinstance(e, DigestEntry) for e in entries)


def test_query_digest_filters(tmp_path):
    db = _db(tmp_path)
    _seed_digest(db)
    assert {e.job_id for e in query_digest(db_path=db, date="2026-06-24")} == {"reed-1", "reed-2"}
    assert {e.job_id for e in query_digest(db_path=db, min_score=80)} == {"reed-1", "reed-3"}


def test_query_digest_min_score_treats_null_as_zero(tmp_path):
    db = _db(tmp_path)
    upsert_job(db, _row("reed-high", "reed", "high", score=90))
    upsert_job(db, _row("reed-low", "reed", "low", score=40))
    upsert_job(db, _row("reed-unscored", "reed", "unscored", score=None))
    set_digest_meta(db, "reed-high", digest_date="2026-06-24")
    set_digest_meta(db, "reed-low", digest_date="2026-06-24")
    set_digest_meta(db, "reed-unscored", digest_date="2026-06-24")

    assert {e.job_id for e in query_digest(db_path=db, min_score=0)} == {
        "reed-high", "reed-low", "reed-unscored"
    }
    assert {e.job_id for e in query_digest(db_path=db, min_score=50)} == {"reed-high"}


def test_query_digest_negative_limit_returns_empty(tmp_path):
    db = _db(tmp_path)
    _seed_digest(db)
    assert query_digest(db_path=db, limit=-1) == []   # not "unbounded"


def test_mark_seen_dedups_ids(tmp_path):
    db = _db(tmp_path)
    _seed_digest(db)
    # duplicate + unknown ids; only the one real unseen row should count once
    assert mark_seen(["reed-1", "reed-1", "nope"], db_path=db) == 1
    assert unseen_count(db_path=db) == 2


def test_digest_entry_url_from_apply_url(tmp_path):
    db = _db(tmp_path)
    upsert_job(db, _row("reed-1", "reed", "1"))
    set_digest_meta(db, "reed-1", digest_date="2026-06-24")
    e = query_digest(db_path=db)[0]
    assert e.url == "https://x/1"      # apply_url, not source_ref


def test_mark_seen_and_unseen_count(tmp_path):
    db = _db(tmp_path)
    _seed_digest(db)
    assert unseen_count(db_path=db) == 3
    assert mark_seen(["reed-1"], db_path=db) == 1
    assert unseen_count(db_path=db) == 2
    assert mark_all_seen(db_path=db) == 2
    assert unseen_count(db_path=db) == 0


def test_digest_stats(tmp_path):
    db = _db(tmp_path)
    _seed_digest(db)
    mark_seen(["reed-1"], db_path=db)
    assert digest_stats(db_path=db) == {"total": 3, "unseen": 2, "seen": 1}


# --------------------------------------------------------------------------- #
# LLM-queue primitives
# --------------------------------------------------------------------------- #

def _now():
    return datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


def _queue(db, job_id, score=80):
    upsert_job(db, _row(job_id, "reed", job_id.split("-")[-1], score=score))
    set_llm_status(db, job_id, "pending")


def test_set_llm_status_rejects_processing(tmp_path):
    db = _db(tmp_path)
    upsert_job(db, _row("reed-1", "reed", "1"))
    with pytest.raises(ValueError):
        set_llm_status(db, "reed-1", "processing")


def test_set_llm_status_done_clears_gate(tmp_path):
    db = _db(tmp_path)
    upsert_job(db, _row("reed-1", "reed", "1"))
    set_llm_status(db, "reed-1", "pending", next_attempt_at="2026-06-24T13:00:00")
    set_llm_status(db, "reed-1", "done")
    conn = open_db(db)
    try:
        r = conn.execute("SELECT * FROM jobs WHERE job_id='reed-1'").fetchone()
    finally:
        conn.close()
    assert r["llm_status"] == "done"
    assert r["llm_next_attempt_at"] is None
    assert r["llm_claim_token"] is None


def test_claim_batch_claims_ready_pending(tmp_path):
    db = _db(tmp_path)
    _queue(db, "reed-1", score=90)
    _queue(db, "reed-2", score=70)
    now = _now().isoformat(timespec="seconds")
    claimed = claim_batch(db, limit=10, ready_before=now, now=now)
    assert [r["job_id"] for r in claimed] == ["reed-1", "reed-2"]  # score desc
    assert all(r["llm_status"] == "processing" for r in claimed)
    # a second claim finds nothing (rows already processing)
    assert claim_batch(db, limit=10, ready_before=now, now=now) == []


def test_claim_batch_respects_backoff_gate(tmp_path):
    db = _db(tmp_path)
    _queue(db, "reed-1")
    set_llm_status(db, "reed-1", "pending", next_attempt_at="2026-06-24T18:00:00")
    early = "2026-06-24T12:00:00"
    assert claim_batch(db, limit=10, ready_before=early, now=early) == []  # gated
    later = "2026-06-24T19:00:00"
    assert len(claim_batch(db, limit=10, ready_before=later, now=later)) == 1


def test_reset_stale_llm_processing(tmp_path):
    db = _db(tmp_path)
    _queue(db, "reed-1")
    old = _now().replace(hour=10).isoformat(timespec="seconds")  # claimed 2h ago
    claim_batch(db, limit=10, ready_before=old, now=old)
    n = reset_stale_llm_processing(db, now=_now(), older_than_minutes=30)
    assert n == 1
    conn = open_db(db)
    try:
        assert conn.execute("SELECT llm_status FROM jobs WHERE job_id='reed-1'").fetchone()["llm_status"] == "pending"
    finally:
        conn.close()


def test_rpd_counter_atomic_and_lazy_reset(tmp_path):
    db = _db(tmp_path)
    assert rpd_used_today(db, "2026-06-24") == 0
    assert incr_rpd_counter(db, "2026-06-24") == 1
    assert incr_rpd_counter(db, "2026-06-24") == 2
    assert rpd_used_today(db, "2026-06-24") == 2
    assert rpd_used_today(db, "2026-06-25") == 0   # different day → lazy reset


# --------------------------------------------------------------------------- #
# Serialisation round-trip (source_job_id)
# --------------------------------------------------------------------------- #

def test_reviewed_job_round_trip_preserves_source_job_id():
    payload = {
        "job_id": "reed-123", "job_title": "BA", "company": "Co",
        "description_raw": "desc", "source_type": "reed", "source_job_id": "123",
    }
    job = reviewed_job_from_dict(payload)
    assert job.source_job_id == "123"
    again = reviewed_job_from_dict(reviewed_job_to_dict(job))
    assert again.source_job_id == "123"


def test_reviewed_job_missing_source_job_id_is_none():
    payload = {
        "job_id": "x-1", "job_title": "BA", "company": "Co",
        "description_raw": "desc", "source_type": "manual",
    }
    assert reviewed_job_from_dict(payload).source_job_id is None


# --------------------------------------------------------------------------- #
# GET /digest/count route
# --------------------------------------------------------------------------- #

@contextmanager
def _server(tmp_path):
    config = UIServerConfig(
        profile_path=tmp_path / "profile.json",
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
        host="127.0.0.1", port=0,
    )
    srv = ThreadingHTTPServer((config.host, config.port), _build_handler(config))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", config
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_route_digest_count(tmp_path):
    with _server(tmp_path) as (base, config):
        with urllib.request.urlopen(base + "/digest/count") as r:
            assert json.loads(r.read())["unseen"] == 0
        # add an unseen digest row, then re-check the badge endpoint
        db = config.state_root / "job_hunt_index.db"
        upsert_job(db, _row("reed-1", "reed", "1"))
        set_digest_meta(db, "reed-1", digest_date="2026-06-24")
        with urllib.request.urlopen(base + "/digest/count") as r:
            assert json.loads(r.read())["unseen"] == 1
