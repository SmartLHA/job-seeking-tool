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
