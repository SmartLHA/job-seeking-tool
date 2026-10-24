"""Synthetic lease, publication, reader and actual-caller race regressions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import io
import json
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import zipfile

import pytest

from src import job_hunt_index as index, job_hunt_qualitative_state as ownership, ui_handlers
from src.job_hunt_config import TailoringPolicy
from src.job_hunt_export import build_package
from src.job_hunt_qualitative import QualitativeRunResult
from src.job_hunt_scheduler import process_eval_queue_once, rpd_date_key
from src.job_hunt_storage import StorageError, load_qualitative_assessment, save_qualitative_assessment
from test_eval_queue import _config, _profile, _save_job, _llm_payload, _Responder, _analysis


@pytest.fixture
def env(tmp_path):
    config = _config(tmp_path)
    _save_job(config, "job-1")
    return SimpleNamespace(config=config, root=config.state_root, db=config.state_root / "job_hunt_index.db",
        now=[datetime(2026, 10, 24, 12, tzinfo=timezone.utc)], tmp=tmp_path)


def clock(env):
    return lambda: env.now[0]


def claim(env, *, queue=None, force=False):
    return index.claim_qualitative_assessment(env.db, "job-1", clock=clock(env), queue=queue, force=force)["owner"]


def pair(env):
    batch = index.enqueue_eval_batch(env.db, ["job-1"], now=env.now[0].isoformat())
    row = index.claim_eval_queue_row(env.db, clock=clock(env))
    return batch, row, claim(env, queue=row)


def payload(label="Accepted synthetic qualitative"):
    result = json.loads(_llm_payload())
    result["dimensions"]["culture_signals"]["reasoning"] = label
    return {**result, "job_id": "job-1", "model": "synthetic", "prompt_version": "test-v1", "created_at": "2026-10-24T12:00:00+00:00"}


def publish(env, owner, label="Accepted synthetic qualitative"):
    return ownership.publish(env.db, owner, payload(label), state_root=env.root,
        result=QualitativeRunResult(ok=True, grade="B", model="synthetic", legitimacy_tier="unknown_caution"), clock=clock(env))


def snapshots(env, batch):
    return index.get_qualitative_index_row(env.db, "job-1"), index.get_eval_batch(env.db, batch)


def rendered(env):
    responder = _Responder()
    ui_handlers.render_job(SimpleNamespace(path="/job/job-1"), env.config, responder, "job-1")
    data, _ = build_package("job-1", _profile(), state_root=env.root,
        policy=TailoringPolicy(output_dir=env.tmp / "output" / "tailored_cvs"), cover_letter_base=env.tmp / "output")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        exported = archive.read("analysis.md").decode()
    return responder.body, exported


def test_expiry_reclaim_fences_all_old_transitions_and_publication(env):
    batch, queue, old = pair(env)
    env.now[0] += timedelta(seconds=ownership.LEASE_SECONDS)
    assert index.reset_stale_eval_queue_running(env.db, clock=clock(env)) == 1
    replacement_queue = index.claim_eval_queue_row(env.db, clock=clock(env))
    replacement = claim(env, queue=replacement_queue)
    assert replacement.token != old.token
    before = snapshots(env, batch)
    for mode in ("quota", "release", "retry", "error", "cancel"):
        assert ownership.transition(env.db, old, mode=mode, error="obsolete", state_root=env.root,
                                    retries=5, clock=clock(env)) == "lost"
        assert snapshots(env, batch) == before
    assert ownership.checkpoint(env.db, old, state_root=env.root, clock=clock(env)) == "lost"
    assert ownership.archive_owned(env.db, old, state_root=env.root, clock=clock(env)) == "lost"
    assert publish(env, old, "STALE CONTENT") == "lost"
    assert publish(env, replacement) == "done"
    accepted = load_qualitative_assessment("job-1", env.root)
    assert accepted[ownership.PUBLICATION_KEY]["generation"] == replacement.generation
    assert "STALE CONTENT" not in json.dumps(accepted)
    row, queue_rows = snapshots(env, batch)
    assert row["claim_token"] is None and row["lease_until"] is None
    assert row["completed_generation"] == replacement.generation and queue_rows[0]["status"] == "done"
    path = env.root / "analyses" / "qualitative" / "job-1.json"
    before = path.read_bytes()
    assert ownership.archive_owned(env.db, old, state_root=env.root, clock=clock(env)) == "lost"
    assert publish(env, old, "STALE REPLACEMENT") == "lost" and path.read_bytes() == before
    index.finish_qualitative_assessment(env.db, "job-1", status="error", error_text="unowned")
    index.release_qualitative_assessment_claim(env.db, "job-1", previous_row=None)
    index.update_qualitative_grade(env.db, "job-1", "F")
    assert index.get_qualitative_index_row(env.db, "job-1") == row


def test_active_force_refused_and_expired_owner_cannot_renew(env):
    old = claim(env)
    assert not index.claim_qualitative_assessment(env.db, "job-1", force=True, clock=clock(env))["claimed"]
    env.now[0] += timedelta(seconds=ownership.LEASE_SECONDS)
    assert ownership.checkpoint(env.db, old, state_root=env.root, clock=clock(env)) == "lost"
    assert claim(env).token != old.token


def test_legacy_running_migration_is_recoverable_and_idempotent(env):
    with index.open_db(env.db) as conn:
        conn.execute("INSERT INTO qualitative_index(job_ref,status,created_at) VALUES('legacy','running','2026-01-01')")
    index.open_db(env.db).close()
    index.open_db(env.db).close()
    row = index.get_qualitative_index_row(env.db, "legacy")
    assert row["status"] == "pending" and row["claim_token"] is None and row["lease_until"] is None
    recovered = index.claim_qualitative_assessment(env.db, "legacy", clock=clock(env))
    assert recovered["claimed"] and recovered["owner"].previous is None


def test_queue_recovery_waits_for_longer_qualitative_lease_without_retry_budget(env, monkeypatch):
    batch, queue, owner = pair(env)
    with index.open_db(env.db) as conn:
        conn.execute("UPDATE qualitative_index SET lease_until=? WHERE job_ref='job-1'",
                     ((env.now[0] + timedelta(seconds=ownership.LEASE_SECONDS*2)).isoformat(),))
    env.now[0] += timedelta(seconds=ownership.LEASE_SECONDS)
    provider = Mock(side_effect=AssertionError("Waiting must not call provider"))
    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", provider)
    for _ in range(7):
        result = process_eval_queue_once(config=env.config, profile=_profile(), db_path=env.db, now=clock(env), sleep=lambda _: None)
        assert result.requeued == 1 and result.failed == 0
        assert index.get_eval_batch(env.db, batch)[0]["retries"] == 1
        assert index.get_qualitative_index_row(env.db, "job-1")["claim_token"] == owner.token
    provider.assert_not_called()
    env.now[0] += timedelta(seconds=ownership.LEASE_SECONDS)
    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", lambda *a, **kw: (_llm_payload(), None, "recovered", False))
    assert process_eval_queue_once(config=env.config, profile=_profile(), db_path=env.db, now=clock(env), sleep=lambda _: None).processed == 1


def test_renewal_prevents_started_at_based_stale_reset(env):
    batch, queue, owner = pair(env)
    env.now[0] += timedelta(minutes=20)
    assert ownership.checkpoint(env.db, owner, state_root=env.root, clock=clock(env)) == "active"
    env.now[0] += timedelta(minutes=11)
    assert index.reset_stale_eval_queue_running(env.db, clock=clock(env)) == 0
    assert index.get_eval_batch(env.db, batch)[0]["claim_token"] == queue["claim_token"]
    env.now[0] += timedelta(minutes=19)
    assert index.reset_stale_eval_queue_running(env.db, clock=clock(env)) == 1


@pytest.mark.parametrize("operation", ["renew", "reclaim"])
def test_clock_is_sampled_after_guard_acquisition_crosses_expiry(env, operation):
    old = claim(env)
    conn = index.open_db(env.db)
    conn.execute("BEGIN IMMEDIATE")
    started, sampled = threading.Event(), threading.Event()
    env.now[0] += timedelta(seconds=ownership.LEASE_SECONDS-1)

    def late_clock():
        sampled.set()
        return env.now[0]

    def run():
        started.set()
        if operation == "renew":
            return ownership.checkpoint(env.db, old, state_root=env.root, clock=late_clock)
        return index.claim_qualitative_assessment(env.db, "job-1", clock=late_clock)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(run)
            assert started.wait(5)
            assert not sampled.wait(0.05)
            env.now[0] += timedelta(seconds=1)
            conn.commit()
            result = pending.result(5)
        assert sampled.is_set()
        assert result == "lost" if operation == "renew" else result["claimed"] and result["owner"].token != old.token
    finally:
        conn.close()


def test_cancellation_before_publication_prevents_json(env):
    batch, queue, owner = pair(env)
    index.cancel_eval_batch(env.db, batch, now=env.now[0].isoformat())
    assert publish(env, owner) == "cancelled"
    assert not (env.root / "analyses" / "qualitative" / "job-1.json").exists()
    assert index.get_eval_batch(env.db, batch)[0]["status"] == "cancelled"


def test_cancellation_after_json_waits_for_publication_and_preserves_done(env, monkeypatch):
    import src.job_hunt_storage as storage
    batch, queue, owner = pair(env)
    original = storage.save_qualitative_assessment
    entered, finished = threading.Event(), threading.Event()

    def cancel():
        entered.set()
        index.cancel_eval_batch(env.db, batch, now=env.now[0].isoformat())
        finished.set()

    thread = threading.Thread(target=cancel)

    def save(*args, **kwargs):
        result = original(*args, **kwargs)
        thread.start()
        assert entered.wait(5) and not finished.wait(0.05)
        return result

    monkeypatch.setattr(storage, "save_qualitative_assessment", save)
    assert publish(env, owner) == "done"
    thread.join(5)
    assert finished.is_set() and index.get_eval_batch(env.db, batch)[0]["status"] == "done"
    assert load_qualitative_assessment("job-1", env.root)[ownership.PUBLICATION_KEY]["generation"] == owner.generation


def test_failure_between_sql_completions_rolls_back_and_readers_reject(env, monkeypatch):
    batch, queue, owner = pair(env)
    original = ownership._finish_queue
    monkeypatch.setattr(ownership, "_finish_queue", Mock(side_effect=sqlite3.OperationalError("Injected queue completion failure")))
    with pytest.raises(sqlite3.OperationalError):
        publish(env, owner, "UNCOMMITTED MARKER")
    row, rows = snapshots(env, batch)
    assert row["status"] == "running" and row["completed_generation"] is None and rows[0]["status"] == "running"
    with pytest.raises(StorageError):
        load_qualitative_assessment("job-1", env.root)
    assert all("UNCOMMITTED MARKER" not in document for document in rendered(env))
    monkeypatch.setattr(ownership, "_finish_queue", original)
    assert publish(env, owner) == "done"


@pytest.mark.parametrize("mode", ["quota", "retry", "error", "release"])
def test_transition_failure_rolls_back_both_claims_and_batch_annotations(env, monkeypatch, mode):
    batch, queue, owner = pair(env)
    before = snapshots(env, batch)
    monkeypatch.setattr(ownership, "_finish_queue", Mock(side_effect=sqlite3.OperationalError("Injected transition failure")))
    with pytest.raises(sqlite3.OperationalError):
        ownership.transition(env.db, owner, mode=mode, error="quota/retry marker", retries=2, state_root=env.root, clock=clock(env))
    assert snapshots(env, batch) == before


@pytest.mark.parametrize("table", ["qualitative_index", "eval_queue"])
@pytest.mark.parametrize("action", ["publish", "transition"])
def test_zero_affected_row_aborts_entire_owned_transaction(env, table, action):
    batch, queue, owner = pair(env)
    before = snapshots(env, batch)
    with index.open_db(env.db) as conn:
        conn.execute(f"""CREATE TRIGGER reject_completion BEFORE UPDATE ON {table}
            WHEN NEW.claim_token IS NULL BEGIN SELECT RAISE(IGNORE); END""")
    with pytest.raises(RuntimeError, match="ownership changed"):
        if action == "publish":
            publish(env, owner, "ZERO ROWCOUNT MARKER")
        else:
            ownership.transition(env.db, owner, mode="quota", error="quota", state_root=env.root, clock=clock(env))
    assert snapshots(env, batch) == before
    if action == "publish":
        with pytest.raises(StorageError):
            load_qualitative_assessment("job-1", env.root)


@pytest.mark.parametrize("prior", ["managed", "archived", "legacy", "expired-running"])
def test_quota_restoration_requires_present_accepted_managed_artifact(env, prior):
    if prior in {"managed", "archived"}:
        first = claim(env)
        assert publish(env, first) == "done"
    elif prior == "legacy":
        save_qualitative_assessment("job-1", payload(), env.root)
        with index.open_db(env.db) as conn:
            conn.execute("INSERT INTO qualitative_index(job_ref,status,grade) VALUES('job-1','done','B')")
    else:
        first = claim(env)
        env.now[0] += timedelta(seconds=ownership.LEASE_SECONDS)
    batch = index.enqueue_eval_batch(env.db, ["job-1"], now=env.now[0].isoformat(), force=True)
    queue = index.claim_eval_queue_row(env.db, clock=clock(env))
    owner = claim(env, queue=queue, force=True)
    if prior == "archived":
        assert ownership.archive_owned(env.db, owner, state_root=env.root, clock=clock(env)) == "active"
    assert ownership.transition(env.db, owner, mode="quota", error="quota exhausted", state_root=env.root, clock=clock(env)) == "quota"
    row, rows = snapshots(env, batch)
    assert row["claim_token"] is None and row["lease_until"] is None
    assert row["generation"] == owner.generation and "quota" in row["error_text"]
    assert row["status"] == ("done" if prior == "managed" else "pending")
    if prior == "managed":
        assert load_qualitative_assessment("job-1", env.root)[ownership.PUBLICATION_KEY]["generation"] == first.generation
    else:
        with pytest.raises((StorageError, FileNotFoundError)):
            load_qualitative_assessment("job-1", env.root)
    assert rows[0]["status"] == "pending" and rows[0]["retries"] == 0


@pytest.mark.parametrize("metadata", [None, {}, {"version": 1}, {"version": True, "generation": "x"}, "bad"])
def test_present_malformed_managed_metadata_never_uses_legacy_fallback(env, metadata):
    save_qualitative_assessment("job-1", {**payload("REJECTED MARKER"), ownership.PUBLICATION_KEY: metadata}, env.root)
    with pytest.raises(StorageError):
        load_qualitative_assessment("job-1", env.root)
    assert all("REJECTED MARKER" not in document for document in rendered(env))


def test_legacy_surviving_managed_claim_and_error_is_rejected_without_backfill(env):
    save_qualitative_assessment("job-1", payload("LEGACY MARKER"), env.root)
    assert "LEGACY MARKER" in json.dumps(load_qualitative_assessment("job-1", env.root))
    owner = claim(env)
    path = env.root / "analyses" / "qualitative" / "job-1.json"
    before = path.read_bytes()
    assert all("LEGACY MARKER" not in document for document in rendered(env))
    assert path.read_bytes() == before
    ownership.transition(env.db, owner, mode="error", error="synthetic failed run", state_root=env.root, clock=clock(env))
    assert all("LEGACY MARKER" not in document for document in rendered(env))
    assert path.read_bytes() == before


def test_index_failure_omits_managed_and_legacy_content_in_actual_ui_and_export(env, monkeypatch):
    owner = claim(env)
    publish(env, owner, "INDEX FAILURE MARKER")
    original = index.open_db
    monkeypatch.setattr(index, "open_db", Mock(side_effect=sqlite3.OperationalError("Injected index failure")))
    assert all("INDEX FAILURE MARKER" not in document for document in rendered(env))
    monkeypatch.setattr(index, "open_db", original)


@pytest.mark.parametrize("legacy", [True, False])
def test_backfill_json_then_sql_failure_is_fail_closed(env, monkeypatch, legacy):
    if legacy:
        save_qualitative_assessment("job-1", payload("BACKFILL MARKER"), env.root)
    else:
        publish(env, claim(env), "BACKFILL MARKER")
    monkeypatch.setattr(ownership, "_one", Mock(side_effect=sqlite3.OperationalError("Injected grade SQL failure")))
    with pytest.raises(sqlite3.OperationalError):
        ownership.backfill_grade(env.db, "job-1", state_root=env.root, analysis=_analysis("job-1"))
    with pytest.raises(StorageError):
        load_qualitative_assessment("job-1", env.root)
    assert all("BACKFILL MARKER" not in document for document in rendered(env))


def test_stale_get_rereads_replacement_before_backfill(env):
    publish(env, claim(env), "OLD GET MARKER")
    old, old_row = ownership.read_snapshot("job-1", env.root)
    replacement = claim(env, force=True)
    publish(env, replacement, "CURRENT GET MARKER")
    current, row, grade = ui_handlers._ensure_qualitative_grade(env.config, "job-1", _analysis("job-1"), old, old_row)
    assert "CURRENT GET MARKER" in json.dumps(current) and "OLD GET MARKER" not in json.dumps(current)
    assert load_qualitative_assessment("job-1", env.root) == current


def test_actual_get_backfill_sql_failure_omits_uncommitted_content(env, monkeypatch):
    publish(env, claim(env), "FAILED GET BACKFILL")
    monkeypatch.setattr(ownership, "_one", Mock(side_effect=sqlite3.OperationalError("Injected GET grade SQL failure")))
    assert all("FAILED GET BACKFILL" not in document for document in rendered(env))
    with pytest.raises(StorageError):
        load_qualitative_assessment("job-1", env.root)


def test_reader_guard_prevents_publication_replacement_between_index_and_json(env, monkeypatch):
    publish(env, claim(env), "FIRST SNAPSHOT")
    original = ownership._read_raw
    started, finished = threading.Event(), threading.Event()

    def replace():
        started.set()
        fresh = claim(env, force=True)
        publish(env, fresh, "SECOND SNAPSHOT")
        finished.set()

    thread = threading.Thread(target=replace)

    def read(*args):
        thread.start()
        assert started.wait(5) and not finished.wait(0.05)
        return original(*args)

    monkeypatch.setattr(ownership, "_read_raw", read)
    first = load_qualitative_assessment("job-1", env.root)
    thread.join(5)
    assert finished.is_set() and "FIRST SNAPSHOT" in json.dumps(first)
    monkeypatch.setattr(ownership, "_read_raw", original)
    assert "SECOND SNAPSHOT" in json.dumps(load_qualitative_assessment("job-1", env.root))


def test_actual_queued_old_provider_cannot_publish_or_quota_pause_replacement(env, monkeypatch):
    batch = index.enqueue_eval_batch(env.db, ["job-1"], now=env.now[0].isoformat())
    calls = []

    def provider(*args, **kwargs):
        calls.append("provider")
        if len(calls) == 1:
            env.now[0] += timedelta(seconds=ownership.LEASE_SECONDS)
            assert process_eval_queue_once(config=env.config, profile=_profile(), db_path=env.db,
                now=clock(env), sleep=lambda _: None).processed == 1
            raise index.LLMQuotaExhausted("obsolete quota error")
        return _llm_payload(), None, "replacement-provider", False

    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", provider)
    old = process_eval_queue_once(config=env.config, profile=_profile(), db_path=env.db, now=clock(env), sleep=lambda _: None)
    assert old.processed == old.failed == old.requeued == 0 and not old.quota_paused
    row, rows = snapshots(env, batch)
    assert row["status"] == "done" and rows[0]["status"] == "done" and rows[0]["error_text"] is None
    assert load_qualitative_assessment("job-1", env.root)["model"] == "replacement-provider"


@pytest.mark.parametrize("failure", ["expiry", "archive", "profile"])
def test_actual_on_demand_recovery_and_failure_cleanup(env, monkeypatch, failure):
    monkeypatch.setattr(ownership, "utc_now", clock(env))
    if failure == "expiry":
        old = claim(env)
        env.now[0] += timedelta(seconds=ownership.LEASE_SECONDS)
        monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", lambda *a, **kw: (_llm_payload(), None, "on-demand-recovery", False))
    else:
        import src.job_hunt_storage as storage
        if failure == "archive":
            monkeypatch.setattr(storage, "_archive_qualitative_assessment_raw", Mock(side_effect=OSError("Injected archive failure")))
        else:
            monkeypatch.setattr(ui_handlers, "load_candidate_profile", Mock(side_effect=ValueError("Injected profile failure")))
            monkeypatch.setattr(ui_handlers, "render_job", Mock())
    request = SimpleNamespace(path="/job/job-1/qualitative-assess", form={"force": "1"}, json_body=None)
    ui_handlers.handle_qualitative_assess(request, env.config, _Responder(), "job-1")
    row = index.get_qualitative_index_row(env.db, "job-1")
    assert row["claim_token"] is None and row["lease_until"] is None
    assert row["status"] == ("done" if failure == "expiry" else "error")
    if failure == "expiry":
        assert row["generation"] != old.generation
        assert load_qualitative_assessment("job-1", env.root)["model"] == "on-demand-recovery"


def test_actual_force_archive_then_quota_never_restores_unreadable_done(env, monkeypatch):
    monkeypatch.setattr(ownership, "utc_now", clock(env))
    provider = Mock(return_value=(_llm_payload(), None, "first-managed", False))
    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", provider)
    request = SimpleNamespace(path="/job/job-1/qualitative-assess", form={}, json_body=None)
    ui_handlers.handle_qualitative_assess(request, env.config, _Responder(), "job-1")
    assert load_qualitative_assessment("job-1", env.root)["model"] == "first-managed"
    profile = json.loads(env.config.profile_path.read_text())
    profile["digest_llm_rpd"] = 1
    env.config.profile_path.write_text(json.dumps(profile))
    index.incr_rpd_counter(env.db, rpd_date_key(env.now[0]))
    request.form = {"force": "1"}
    responder = _Responder()
    ui_handlers.handle_qualitative_assess(request, env.config, responder, "job-1")
    row = index.get_qualitative_index_row(env.db, "job-1")
    assert row["status"] == "error" and row["claim_token"] is None and "quota" in row["error_text"]
    assert provider.call_count == 1 and "daily LLM quota" in responder.body
    assert list((env.root / "analyses" / "qualitative" / "archive").glob("job-1__*.json"))
    with pytest.raises(FileNotFoundError):
        load_qualitative_assessment("job-1", env.root)


def test_shorter_qualitative_lease_recovers_on_demand_while_old_queue_waits(env, monkeypatch):
    batch, queue, old = pair(env)
    with index.open_db(env.db) as conn:
        conn.execute("UPDATE qualitative_index SET lease_until=? WHERE job_ref='job-1'",
                     ((env.now[0] + timedelta(minutes=10)).isoformat(),))
    env.now[0] += timedelta(minutes=10)
    monkeypatch.setattr(ownership, "utc_now", clock(env))
    provider = Mock(return_value=(_llm_payload(), None, "on-demand-short-lease", False))
    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", provider)
    ui_handlers.handle_qualitative_assess(SimpleNamespace(path="/job/job-1/qualitative-assess", form={}, json_body=None),
                                        env.config, _Responder(), "job-1")
    assert index.get_eval_batch(env.db, batch)[0]["status"] == "running"
    assert publish(env, old, "STALE QUEUED CONTENT") == "lost"
    env.now[0] += timedelta(minutes=20)
    result = process_eval_queue_once(config=env.config, profile=_profile(), db_path=env.db, now=clock(env), sleep=lambda _: None)
    assert result.processed == 1 and provider.call_count == 1
    assert index.get_eval_batch(env.db, batch)[0]["status"] == "done"


def test_pacific_quota_date_is_real_zoneinfo_not_utc_fallback():
    assert rpd_date_key(datetime(2026, 7, 1, 6, 30, tzinfo=timezone.utc)) == "2026-06-30"
    assert rpd_date_key(datetime(2026, 1, 1, 7, 30, tzinfo=timezone.utc)) == "2025-12-31"
