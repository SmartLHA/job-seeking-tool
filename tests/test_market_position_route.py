"""Market-aware salary, revision 2 (2026-09-22): POST /job/{id}/market-position
(+/clear) routes and storage effects. No real network — the Adzuna cache is
pre-seeded via the client's own cache writer (fetch_adzuna_salary_histogram with
requests.get mocked), matching the panel's own write path exactly."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

import src.job_sources.adzuna_client as ac
from src import ui_handlers
from src.job_hunt_evaluation import evaluate_reviewed_job
from src.job_hunt_models import CandidateProfile, JobPosting
from src.job_hunt_storage import ensure_storage_layout, load_job_analysis, save_job_analysis, save_reviewed_job
from src.ui_state import UIServerConfig

APP_ID = "test-app-id"
APP_KEY = "test-app-key"
T0 = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
HIST_30_5 = {"histogram": {"10000": "6", "30000": "6", "50000": "6", "70000": "6", "90000": "6"}}  # total 30


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", APP_ID)
    monkeypatch.setenv("ADZUNA_APP_KEY", APP_KEY)


def _resp(payload):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload
    return r


def _profile():
    return CandidateProfile(
        candidate_id="c1", name="T", target_roles=["BA"], locations=["London"],
        remote_preference="remote_friendly", salary_floor_gbp=45000, right_to_work_uk=True,
        skills=[], years_experience=3, industries=[],
    )


def _job(**overrides):
    payload = dict(
        job_id="job-1", job_title="Senior Business Analyst", company="Acme",
        description_raw="d", source_type="copied_text", source_ref=None, location="London",
        work_mode="hybrid", employment_type="full-time",
        required_skills=[], preferred_skills=[], salary_min_gbp=60000, salary_max_gbp=80000,
    )
    payload.update(overrides)
    return JobPosting(**payload)


class _Resp:
    def __init__(self):
        self.json_sent = None
        self.status = None

    def send_json(self, payload, status=HTTPStatus.OK):
        self.json_sent, self.status = payload, status


@pytest.fixture
def config(tmp_path):
    prof = tmp_path / "profile.json"
    prof.write_text(json.dumps({
        "candidate_id": "c1", "name": "T", "target_roles": ["BA"], "locations": ["London"],
        "remote_preference": "remote_friendly", "salary_floor_gbp": 45000, "right_to_work_uk": True,
        "skills": [], "years_experience": 3, "industries": []}))
    cfg = UIServerConfig(profile_path=prof, state_root=tmp_path / "state", report_dir=tmp_path / "r")
    ensure_storage_layout(cfg.state_root)
    job = _job()
    save_reviewed_job(job, cfg.state_root)
    analysis = evaluate_reviewed_job(_profile(), job)
    save_job_analysis(analysis, cfg.state_root)
    return cfg


def _seed_cache(config, *, what="senior business analyst", payload=HIST_30_5):
    cache_dir = config.state_root / "cache" / "adzuna_salary"
    with patch("requests.get", return_value=_resp(payload)):
        ac.fetch_adzuna_salary_histogram(what, cache_dir=cache_dir, now=lambda: T0)


# ── route registration ────────────────────────────────────────────────────────

def test_routes_registered():
    import inspect
    from src import ui_routes
    src_text = inspect.getsource(ui_routes)
    assert "market-position" in src_text
    assert ui_routes.handle_set_market_position is ui_handlers.handle_set_market_position
    assert ui_routes.handle_clear_market_position is ui_handlers.handle_clear_market_position


# ── 400 / 404 / 422 / 409 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [".", "..", "x" * 129, "a%2Fb"])
def test_route_400_bad_id(config, bad):
    r = _Resp()
    with patch.object(ui_handlers, "load_reviewed_job") as ld:
        ui_handlers.handle_set_market_position(None, config, r, bad)
    assert r.status == HTTPStatus.BAD_REQUEST
    ld.assert_not_called()


def test_route_404_unknown_job(config):
    r = _Resp()
    ui_handlers.handle_set_market_position(None, config, r, "nope-1")
    assert r.status == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize("content,expected", [
    ("{not json", HTTPStatus.NOT_FOUND),
    ('{"job_title": 5, "bogus_field": 1}', HTTPStatus.UNPROCESSABLE_ENTITY),
])
def test_route_corrupt_job_never_500(config, content, expected):
    next(config.state_root.rglob("reviewed_jobs/job-1.json")).write_text(content)
    r = _Resp()
    ui_handlers.handle_set_market_position(None, config, r, "job-1")
    assert r.status == expected and r.json_sent["ok"] is False


def test_route_409_no_cached_benchmark(config):
    r = _Resp()
    with patch("requests.get") as g:
        ui_handlers.handle_set_market_position(None, config, r, "job-1")
    assert r.status == HTTPStatus.CONFLICT
    assert "not fetched yet" in r.json_sent["error"]
    g.assert_not_called()


# ── 200 save / badge / clear ─────────────────────────────────────────────────

def test_route_200_saves_snapshot(config):
    _seed_cache(config)
    r = _Resp()
    ui_handlers.handle_set_market_position(None, config, r, "job-1")
    assert r.status == HTTPStatus.OK and r.json_sent["ok"] is True
    snap = r.json_sent["market_snapshot"]
    assert snap["source"] == "adzuna" and snap["version"] == 1
    assert snap["salary_used"] == 70000.0

    stored = load_job_analysis("job-1", config.state_root)
    assert stored.market_snapshot == snap


def test_route_200_shows_up_on_job_page(config):
    _seed_cache(config)
    ui_handlers.handle_set_market_position(None, config, _Resp(), "job-1")
    from src.ui_handlers import _build_job_page_vm
    from src.job_hunt_storage import load_application_outcome, load_reviewed_job
    from src.ui_render import render_job_page
    reviewed_job = load_reviewed_job("job-1", config.state_root)
    analysis = load_job_analysis("job-1", config.state_root)
    try:
        outcome = load_application_outcome("job-1", config.state_root)
    except FileNotFoundError:
        outcome = None
    vm = _build_job_page_vm(reviewed_job, analysis, outcome, flash=None, model_label="m")
    html = render_job_page(vm)
    assert "Market:" in html


def test_route_second_click_replaces_snapshot_with_new_date(config):
    _seed_cache(config)
    ui_handlers.handle_set_market_position(None, config, _Resp(), "job-1")
    first = load_job_analysis("job-1", config.state_root).market_snapshot

    later = T0 + timedelta(hours=25)  # past the 24h cache TTL -> a genuinely new fetch
    cache_dir = config.state_root / "cache" / "adzuna_salary"
    with patch("requests.get", return_value=_resp(HIST_30_5)):
        ac.fetch_adzuna_salary_histogram(
            "senior business analyst", cache_dir=cache_dir, now=lambda: later,
        )
    r2 = _Resp()
    ui_handlers.handle_set_market_position(None, config, r2, "job-1")
    second = load_job_analysis("job-1", config.state_root).market_snapshot
    assert second["histogram_date"] != first["histogram_date"]


def test_route_clear_removes_snapshot(config):
    _seed_cache(config)
    ui_handlers.handle_set_market_position(None, config, _Resp(), "job-1")
    assert load_job_analysis("job-1", config.state_root).market_snapshot is not None

    r = _Resp()
    ui_handlers.handle_clear_market_position(None, config, r, "job-1")
    assert r.status == HTTPStatus.OK and r.json_sent["ok"] is True
    assert load_job_analysis("job-1", config.state_root).market_snapshot is None


def test_route_clear_404_unknown_job(config):
    r = _Resp()
    ui_handlers.handle_clear_market_position(None, config, r, "nope-1")
    assert r.status == HTTPStatus.NOT_FOUND


# ── never enters risk_flags / critical_risk_codes / blockers ────────────────

def test_saved_snapshot_never_enters_risk_flags_or_blockers(config):
    _seed_cache(config)
    ui_handlers.handle_set_market_position(None, config, _Resp(), "job-1")
    analysis = load_job_analysis("job-1", config.state_root)
    codes = [f.code for f in analysis.risk_flags]
    assert "market" not in " ".join(codes).lower() and "adzuna" not in " ".join(codes).lower()
    assert analysis.blockers == []


# ── does not change score/decision/grade when the switch is off ────────────

def test_saving_snapshot_does_not_change_match_score_or_decision(config):
    before = load_job_analysis("job-1", config.state_root)
    _seed_cache(config)
    ui_handlers.handle_set_market_position(None, config, _Resp(), "job-1")
    after = load_job_analysis("job-1", config.state_root)
    assert after.match_score == before.match_score
    assert after.decision == before.decision


# ── inline JS syntax (Save/Remove buttons) ───────────────────────────────────

def test_salary_benchmark_js_is_valid_js(tmp_path):
    import re
    import shutil
    import subprocess
    from src import ui_render

    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    m = re.search(r"<script>(.*)</script>", ui_render._SALARY_BENCHMARK_JS, re.S)
    f = tmp_path / "s.js"
    f.write_text(m.group(1))
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_panel_shows_saved_badge_and_remove_button(config):
    from src.ui_render import render_salary_benchmark_panel
    snapshot = {"position": "bottom", "sample_total": 100, "histogram_date": "2026-09-20T10:00:00+00:00"}
    html = render_salary_benchmark_panel("job-1", market_snapshot=snapshot)
    assert "Saved:" in html and "Market: bottom quarter" in html
    assert 'id="sb-clear-btn"' in html and "Remove market position" in html


def test_panel_no_saved_block_when_no_snapshot():
    from src.ui_render import render_salary_benchmark_panel
    html = render_salary_benchmark_panel("job-1", market_snapshot=None)
    assert "Saved:" not in html and 'id="sb-clear-btn"' not in html
