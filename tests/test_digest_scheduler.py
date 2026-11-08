"""Tests for Daily Job Digest phase D5 — the DigestScheduler daemon (once-per-day,
exception isolation, disabled/enabled gating, status snapshot). Drives `_maybe_run`
directly with an injected profile + monkeypatched pipeline (no real thread/sleep)."""
from __future__ import annotations

import types

import src.job_hunt_scheduler as scheduler
from src.job_hunt_scheduler import DigestRunResult, DigestScheduler
from src.job_hunt_profile import candidate_profile_from_dict
from src.job_hunt_storage import ensure_storage_layout


def _result():
    return DigestRunResult("s", "f", 1, 1, 1, 1, 0, 0, 0, [])


def _sched(tmp_path, *, enabled=True, run_time="00:00"):
    ensure_storage_layout(tmp_path)
    cfg = types.SimpleNamespace(state_root=tmp_path)
    profile = candidate_profile_from_dict({
        "candidate_id": "c", "digest_enabled": enabled, "digest_run_time": run_time,
    })
    return DigestScheduler(cfg, get_profile=lambda: profile)


def test_runs_once_per_day(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(1) or _result())
    s = _sched(tmp_path, run_time="00:00")   # always "past" so it's due
    s._maybe_run()
    s._maybe_run()   # same day → must NOT run again
    assert len(calls) == 1
    assert s.status()["last_run"]["jobs_new"] == 1


def test_disabled_does_not_run(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(1) or _result())
    s = _sched(tmp_path, enabled=False, run_time="00:00")
    s._maybe_run()
    assert calls == []


def test_not_yet_time_does_not_run(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(1) or _result())
    s = _sched(tmp_path, run_time="23:59")   # in the future for almost all of the day
    # only assert no-run when the current minute is before 23:59
    import datetime as _dt
    if (_dt.datetime.now().hour, _dt.datetime.now().minute) < (23, 59):
        s._maybe_run()
        assert calls == []


def test_pipeline_exception_does_not_break_scheduler(tmp_path, monkeypatch):
    def _boom(**k):
        raise RuntimeError("pipeline down")
    monkeypatch.setattr(scheduler, "run_digest_pipeline", _boom)
    s = _sched(tmp_path, run_time="00:00")
    s._maybe_run()   # must not raise
    st = s.status()
    assert st["last_error"] == "pipeline down"
    assert st["running"] is False
    # slot was reserved, so it won't retry today (no infinite loop)
    calls = []
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(1) or _result())
    s._maybe_run()
    assert calls == []


def test_status_snapshot_shape(tmp_path):
    s = _sched(tmp_path)
    st = s.status()
    assert set(st) >= {"running", "last_run", "last_run_date", "last_error", "next_run"}
    assert st["running"] is False and st["last_run"] is None


def test_start_stop_clean(tmp_path):
    s = _sched(tmp_path, run_time="23:59")
    s.start()
    s.stop(timeout=2)   # must return promptly
    assert not s._thread.is_alive()


# Issue16: drive the real scheduler and SQLite, with only pipeline/provider work stubbed.
import dataclasses
import sqlite3
import threading
from datetime import datetime, timedelta

import pytest

from src.job_hunt_index import claim_daily_digest_run, daily_digest_run_status, open_db


def _clock(monkeypatch, day="2026-10-12", hour=12):
    class Clock(datetime):
        current = datetime.fromisoformat(day).replace(hour=hour)

        @classmethod
        def now(cls):
            return cls.current
    monkeypatch.setattr(scheduler, "datetime", Clock)
    return Clock


@pytest.mark.parametrize("errors", [[], ["second source failed"]])
def test_restart_restores_success_or_partial(tmp_path, monkeypatch, errors):
    _clock(monkeypatch)
    result = dataclasses.replace(_result(), errors=errors)
    calls = []
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(1) or result)
    first = _sched(tmp_path)
    first._maybe_run()
    second = _sched(tmp_path)
    second._maybe_run()
    st = second.status()
    assert calls == [1]
    assert st["last_run"] == result.to_dict()
    assert st["last_run_date"] == "2026-10-12"
    assert st["last_outcome"] == ("partial" if errors else "success")
    assert st["last_error"] == (errors[0] if errors else None)
    assert st["last_success_date"] == (None if errors else "2026-10-12")
    assert st["outcome_durable"] is True
    assert st["next_run"].startswith("2026-10-13")


def test_failed_restart_and_next_day(tmp_path, monkeypatch):
    clock = _clock(monkeypatch)
    calls = []
    def boom(**kwargs):
        calls.append(1)
        raise RuntimeError("fetch exploded")
    monkeypatch.setattr(scheduler, "run_digest_pipeline", boom)
    _sched(tmp_path)._maybe_run()
    restarted = _sched(tmp_path)
    restarted._maybe_run()
    st = restarted.status()
    assert st["last_outcome"] == "failed" and st["last_error"] == "fetch exploded"
    assert st["last_success_date"] is None and st["last_run"] is None
    clock.current += timedelta(days=1)
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(1) or _result())
    restarted._maybe_run()
    restarted._maybe_run()
    assert calls == [1, 1]
    assert restarted.status()["last_success_date"] == "2026-10-13"
    conn = open_db(tmp_path / "job_hunt_index.db")
    try:
        assert [tuple(row) for row in conn.execute(
            "SELECT run_date, outcome, error_text FROM daily_digest_runs ORDER BY run_date"
        )] == [("2026-10-12", "failed", "fetch exploded"), ("2026-10-13", "success", None)]
    finally:
        conn.close()


def test_interrupted_claim_restart_requires_manual_retry(tmp_path, monkeypatch):
    _clock(monkeypatch)
    calls = []
    def interrupted(**kwargs):
        calls.append(1)
        raise KeyboardInterrupt()
    monkeypatch.setattr(scheduler, "run_digest_pipeline", interrupted)
    first = _sched(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        first._maybe_run()
    restarted = _sched(tmp_path)
    restarted._maybe_run()
    st = restarted.status()
    assert calls == [1]
    assert st["last_outcome"] == "interrupted" and st["outcome_durable"] is False
    assert "manual" in st["last_error"] and "unfinished" in st["last_error"]
    assert st["last_success_date"] is None
    assert st["next_run"].startswith("2026-10-13")


def test_claim_is_durable_before_pipeline_and_competing_instances(tmp_path, monkeypatch):
    _clock(monkeypatch)
    first, second = _sched(tmp_path), _sched(tmp_path)
    # Initialise migration separately; claims themselves still race on independent connections.
    open_db(tmp_path / "job_hunt_index.db").close()
    barrier = threading.Barrier(2)
    original = scheduler.claim_daily_digest_run
    def competing(*args, **kwargs):
        barrier.wait(timeout=5)
        return original(*args, **kwargs)
    monkeypatch.setattr(scheduler, "claim_daily_digest_run", competing)
    calls = []
    def pipeline(**kwargs):
        attempt, success = daily_digest_run_status(kwargs["db_path"])
        assert attempt["outcome"] == "running" and success is None
        calls.append(1)
        return _result()
    monkeypatch.setattr(scheduler, "run_digest_pipeline", pipeline)
    threads = [threading.Thread(target=s._maybe_run) for s in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert calls == [1]
    assert first.status()["last_outcome"] == second.status()["last_outcome"] == "success"


@pytest.mark.parametrize("helper", ["daily_digest_run_status", "claim_daily_digest_run"])
def test_prework_persistence_failure_blocks_pipeline(tmp_path, monkeypatch, helper):
    _clock(monkeypatch)
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("disk unavailable")
    calls = []
    monkeypatch.setattr(scheduler, helper, fail)
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(1) or _result())
    import src.job_hunt_saved_searches as searches
    monkeypatch.setattr(searches, "list_saved_searches", lambda **k: calls.append("search read"))
    s = _sched(tmp_path)
    s._maybe_run()
    assert calls == []
    assert "disk unavailable" in s.status()["last_error"]
    assert s.status()["last_success_date"] is None


def test_outcome_write_failure_retains_claim_and_useful_result(tmp_path, monkeypatch):
    _clock(monkeypatch)
    calls = []
    partial = dataclasses.replace(_result(), errors=["source timeout"])
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(1) or partial)
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("outcome write unavailable")
    monkeypatch.setattr(scheduler, "finish_daily_digest_run", fail)
    s = _sched(tmp_path)
    s._maybe_run()
    st = s.status()
    assert st["last_run"] == partial.to_dict()
    assert "source timeout" in st["last_error"] and "outcome write unavailable" in st["last_error"]
    assert st["outcome_durable"] is False and st["last_success_date"] is None
    restarted = _sched(tmp_path)
    restarted._maybe_run()
    assert calls == [1]
    assert restarted.status()["last_outcome"] == "interrupted"


def test_prior_success_is_not_new_failed_success(tmp_path, monkeypatch):
    clock = _clock(monkeypatch)
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: _result())
    s = _sched(tmp_path)
    s._maybe_run()
    clock.current += timedelta(days=1)
    monkeypatch.setattr(scheduler, "run_digest_pipeline",
                        lambda **k: dataclasses.replace(_result(), errors=["bad search"]))
    s._maybe_run()
    st = _sched(tmp_path).status()
    assert st["last_run_date"] == "2026-10-13" and st["last_success_date"] == "2026-10-12"
    assert st["last_outcome"] == "partial"


def test_next_run_tomorrow_even_if_time_changed_after_claim(tmp_path, monkeypatch):
    _clock(monkeypatch)
    s = _sched(tmp_path)
    claim_daily_digest_run(s._db_path, "2026-10-12", started_at="2026-10-12T09:00:00")
    s = _sched(tmp_path, run_time="23:59")
    assert s.status()["next_run"] == "2026-10-13T23:59:00"


def test_actual_sqlite_claim_failure_is_fail_closed(tmp_path, monkeypatch):
    _clock(monkeypatch)
    s = _sched(tmp_path)
    open_db(s._db_path).close()
    conn = sqlite3.connect(s._db_path)
    conn.execute("CREATE TRIGGER deny_daily_claim BEFORE INSERT ON daily_digest_runs "
                 "BEGIN SELECT RAISE(ABORT, 'claim denied'); END")
    conn.commit()
    conn.close()
    calls = []
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(1) or _result())
    s._maybe_run()
    assert calls == [] and "claim denied" in s.status()["last_error"]


@pytest.mark.parametrize("daily_errors", [[], ["daily source failed"]])
def test_manual_run_now_bypasses_daily_guard_without_changing_ledger(tmp_path, monkeypatch, daily_errors):
    _clock(monkeypatch)
    from src import ui_handlers
    from src.job_hunt_saved_searches import SavedSearch, save_saved_search
    search = SavedSearch("manual1", "Synthetic", "reed", {}, True, "2026-10-12", None, 0)
    save_saved_search(search, state_root=tmp_path)
    s = _sched(tmp_path)
    calls = []
    daily_result = dataclasses.replace(_result(), errors=daily_errors)
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(k) or daily_result)
    s._maybe_run()
    before = daily_digest_run_status(s._db_path)
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(k) or _result())
    monkeypatch.setattr(ui_handlers, "_load_active_profile", lambda cfg: s._get_profile())
    class Response:
        def send_json(self, payload, status=None):
            self.payload = payload
    response = Response()
    for _ in range(2):
        ui_handlers.handle_run_now(None, s._config, response, "manual1")
        assert response.payload["ok"] is True
    s._maybe_run()
    assert len(calls) == 3
    assert [item.search_id for item in calls[-1]["saved_searches"]] == [search.search_id]
    assert daily_digest_run_status(s._db_path) == before


def test_claim_failure_with_prior_success_remains_visible(tmp_path, monkeypatch):
    clock = _clock(monkeypatch)
    calls = []
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(1) or _result())
    s = _sched(tmp_path)
    s._maybe_run()
    clock.current += timedelta(days=1)
    original = scheduler.claim_daily_digest_run
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("next day disk error")
    monkeypatch.setattr(scheduler, "claim_daily_digest_run", fail)
    s._maybe_run()
    status = s.status()
    assert calls == [1]
    assert "next day disk error" in status["last_error"]
    assert status["last_success_date"] == "2026-10-12"
    monkeypatch.setattr(scheduler, "claim_daily_digest_run", original)
    s._maybe_run()
    assert calls == [1, 1]
    assert s.status()["last_error"] is None


def test_actual_sqlite_outcome_failure_retains_durable_claim(tmp_path, monkeypatch):
    _clock(monkeypatch)
    s = _sched(tmp_path)
    open_db(s._db_path).close()
    conn = sqlite3.connect(s._db_path)
    conn.execute("CREATE TRIGGER deny_daily_finish BEFORE UPDATE ON daily_digest_runs "
                 "BEGIN SELECT RAISE(ABORT, 'outcome denied'); END")
    conn.commit()
    conn.close()
    calls = []
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(1) or _result())
    s._maybe_run()
    st = s.status()
    assert st["last_run"]["jobs_new"] == 1
    assert "outcome denied" in st["last_error"]
    assert st["outcome_durable"] is False and st["last_success_date"] is None
    restarted = _sched(tmp_path)
    restarted._maybe_run()
    assert calls == [1]
    attempt, success = daily_digest_run_status(s._db_path)
    assert attempt["outcome"] == "running" and success is None


def test_actual_corrupt_ledger_result_blocks_new_work(tmp_path, monkeypatch):
    clock = _clock(monkeypatch)
    s = _sched(tmp_path)
    token = claim_daily_digest_run(s._db_path, "2026-10-12", started_at="synthetic")
    conn = sqlite3.connect(s._db_path)
    conn.execute("UPDATE daily_digest_runs SET result_json='invalid json' WHERE claim_token=?", (token,))
    conn.commit()
    conn.close()
    clock.current += timedelta(days=1)
    calls = []
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(1) or _result())
    s._maybe_run()
    assert calls == []
    assert "persistence read failed" in s.status()["last_error"]


@pytest.mark.parametrize("run_time", ["invalid", "24:00", "12:60", "-1:00"])
def test_invalid_schedule_does_not_claim(tmp_path, monkeypatch, run_time):
    _clock(monkeypatch)
    s = _sched(tmp_path)
    s._get_profile = lambda: types.SimpleNamespace(digest_enabled=True, digest_run_time=run_time)
    calls = []
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: calls.append(1) or _result())
    s._maybe_run()
    assert calls == [] and daily_digest_run_status(s._db_path) == (None, None)
    assert s.status()["next_run"] is None


def test_disabled_and_before_schedule_leave_date_unclaimed(tmp_path, monkeypatch):
    _clock(monkeypatch, hour=8)
    _sched(tmp_path, enabled=False)._maybe_run()
    _sched(tmp_path, run_time="09:00")._maybe_run()
    assert daily_digest_run_status(tmp_path / "job_hunt_index.db") == (None, None)
