"""B (2026-09-20): /scheduler/status must report an accurate state and reason.

Root cause of the "running:false although it ran at startup" report: `running` only
means "a digest run is in progress right now"; idle-between-runs is False by design and
the UI mislabelled it "not running". Now `state`/`reason`/`alive` explain it."""

from __future__ import annotations

import time
from datetime import datetime
from types import SimpleNamespace

from src import ui_handlers
from src.job_hunt_scheduler import DigestScheduler


def _sched(tmp_path, **profile_kw):
    cfg = SimpleNamespace(state_root=str(tmp_path))
    prof = SimpleNamespace(digest_enabled=True, digest_run_time="23:59", **profile_kw)
    sched = DigestScheduler(cfg, get_profile=lambda: prof)
    # Keep the daemon thread alive but never let it fire a real pipeline run (a real
    # run would depend on the wall clock, e.g. tests executed after 23:59).
    sched._maybe_run = lambda: None
    return sched, prof


def test_stopped_before_start(tmp_path):
    s, _ = _sched(tmp_path)
    st = s.status()
    assert st["state"] == "stopped" and st["alive"] is False and st["running"] is False
    assert st["enabled"] is True   # profile enables digest even though thread not started


def test_stopped_reports_disabled_profile(tmp_path):
    s, prof = _sched(tmp_path)
    prof.digest_enabled = False
    st = s.status()
    assert st["state"] == "stopped" and st["enabled"] is False


def test_profile_read_error_enabled_unknown(tmp_path):
    s, _ = _sched(tmp_path)
    def boom():
        raise RuntimeError("bad profile")
    s._get_profile = boom
    assert s.status()["enabled"] is None and s.status()["state"] == "stopped"
    s.start()
    try:
        st = s.status()
        assert st["state"] == "idle" and st["enabled"] is None and "bad profile" in st["reason"]
    finally:
        s.stop()


def test_disabled_reason(tmp_path):
    s, prof = _sched(tmp_path)
    prof.digest_enabled = False
    s.start()
    try:
        st = s.status()
        assert st["alive"] is True and st["state"] == "disabled"
        assert "disabled" in st["reason"].lower() and st["running"] is False
        assert st["enabled"] is False
    finally:
        s.stop()


def test_idle_after_run_reports_next_run(tmp_path):
    s, _ = _sched(tmp_path)
    s.start()
    try:
        s._last_run_date = datetime.now().date().isoformat()   # ran today
        st = s.status()
        assert st["alive"] is True and st["running"] is False
        assert st["state"] == "idle" and "already ran" in st["reason"] and st["enabled"] is True
        assert st["next_run"]
    finally:
        s.stop()


def test_running_state_while_run_in_progress(tmp_path):
    s, _ = _sched(tmp_path)
    s.start()
    try:
        s._running = True
        st = s.status()
        assert st["state"] == "running" and st["running"] is True and st["enabled"] is True
    finally:
        s._running = False
        s.stop()


class _Resp:
    def send_json(self, data, status=None):
        self.data = data


def test_endpoint_matches_scheduler_state(tmp_path):
    s, _ = _sched(tmp_path)
    s.start()
    try:
        ui_handlers.set_daemons(scheduler=s)
        r = _Resp()
        ui_handlers.handle_scheduler_status(None, None, r)
        assert r.data["state"] == s.status()["state"] == "idle"
        assert r.data["alive"] is True
    finally:
        ui_handlers.set_daemons(scheduler=None)
        s.stop()


def test_endpoint_without_daemon_says_stopped():
    ui_handlers.set_daemons(scheduler=None)
    r = _Resp()
    ui_handlers.handle_scheduler_status(None, None, r)
    assert r.data["state"] == "stopped" and r.data["running"] is False and r.data["reason"]
