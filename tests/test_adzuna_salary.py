"""Feature B (2026-09-22): Adzuna salary benchmark (advisory). No real network requests."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
import requests

import src.job_sources.adzuna_client as ac
from src import ui_handlers
from src.job_hunt_models import JobPosting
from src.job_hunt_salary_benchmark import clean_job_title, summarise_histogram
from src.job_hunt_storage import ensure_storage_layout, save_reviewed_job
from src.ui_render import JobPageViewModel, render_job_page
from src.ui_state import UIServerConfig

APP_ID = "test-app-id-XYZ"
APP_KEY = "SECRETKEY-do-not-leak-123"
T0 = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", APP_ID)
    monkeypatch.setenv("ADZUNA_APP_KEY", APP_KEY)


def _resp(status=200, payload=None, bad_json=False):
    r = MagicMock()
    r.status_code = status
    if bad_json:
        r.json.side_effect = ValueError("no json")
    else:
        r.json.return_value = payload
    return r


HIST = {"histogram": {"60000": "10", "40000": "30", "50000": "20"}}


def _fetch(tmp_path, what="business analyst", now=None, **kw):
    clock = now if now is not None else (lambda: T0)
    return ac.fetch_adzuna_salary_histogram(what, cache_dir=tmp_path / "c", now=clock, **kw)


def _no_secret(*texts):
    for t in texts:
        assert APP_KEY not in str(t) and APP_ID not in str(t)


# ── client ────────────────────────────────────────────────────────────────────

def test_ok_sorted_and_int(tmp_path):
    with patch("requests.get", return_value=_resp(payload=HIST)) as g:
        r = _fetch(tmp_path)
    assert r.status == "ok" and r.total == 60
    assert r.buckets == [(40000, 30), (50000, 20), (60000, 10)]
    assert g.call_args.kwargs["timeout"] == 10


def test_no_data(tmp_path):
    with patch("requests.get", return_value=_resp(payload={"histogram": {}})):
        r = _fetch(tmp_path)
    assert r.status == "no_data" and r.buckets == [] and r.total == 0


def test_429_error_no_secret(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    with patch("requests.get", return_value=_resp(status=429)):
        r = _fetch(tmp_path)
    assert r.status == "error" and "429" in r.error
    _no_secret(r.error, r.to_dict(), caplog.text)


def test_timeout_error_no_secret(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    exc = requests.exceptions.Timeout(f"https://x?app_key={APP_KEY}&app_id={APP_ID}")
    with patch("requests.get", side_effect=exc):
        r = _fetch(tmp_path)
    assert r.status == "error" and "timed out" in r.error
    _no_secret(r.error, r.to_dict(), caplog.text)


def test_connection_error_text_scrubbed(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    exc = requests.exceptions.ConnectionError(f"https://x?app_key={APP_KEY}")
    with patch("requests.get", side_effect=exc):
        r = _fetch(tmp_path)
    assert r.status == "error" and "ConnectionError" in r.error
    _no_secret(r.error, caplog.text)


def test_http_500_error(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    with patch("requests.get", return_value=_resp(status=500)):
        r = _fetch(tmp_path)
    assert r.status == "error" and "500" in r.error
    _no_secret(r.error, caplog.text)


@pytest.mark.parametrize("payload,bad", [(None, True), ({"nope": 1}, False), ({"histogram": {"x": "1"}}, False),
                                         ({"histogram": {"40000": "abc"}}, False), ([1], False)])
def test_malformed_json(tmp_path, payload, bad):
    with patch("requests.get", return_value=_resp(payload=payload, bad_json=bad)):
        r = _fetch(tmp_path)
    assert r.status == "error"
    _no_secret(r.error)


def test_missing_creds_no_http(tmp_path, monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_KEY")
    with patch("requests.get") as g:
        r = _fetch(tmp_path)
    assert r.status == "unavailable"
    g.assert_not_called()


def test_empty_query_no_http(tmp_path):
    with patch("requests.get") as g:
        r = _fetch(tmp_path, what="   ")
    assert r.status == "error"
    g.assert_not_called()


def test_cache_hit_avoids_second_call(tmp_path):
    with patch("requests.get", return_value=_resp(payload=HIST)) as g:
        a = _fetch(tmp_path)
        b = _fetch(tmp_path, what="  Business   ANALYST ")
    assert g.call_count == 1
    assert b.cached is True and b.buckets == a.buckets and b.status == "ok"


def test_cache_ttl_expiry_refetches(tmp_path):
    with patch("requests.get", return_value=_resp(payload=HIST)) as g:
        _fetch(tmp_path)
        _fetch(tmp_path, now=lambda: T0 + timedelta(hours=23))
        assert g.call_count == 1
        _fetch(tmp_path, now=lambda: T0 + timedelta(hours=25))
        assert g.call_count == 2


def test_errors_are_not_cached(tmp_path):
    with patch("requests.get", return_value=_resp(status=429)) as g:
        _fetch(tmp_path)
        _fetch(tmp_path)
    assert g.call_count == 2
    assert [f.name for f in (tmp_path / "c").glob("*.json")] == ["budget.json"]


def test_no_data_is_cached(tmp_path):
    with patch("requests.get", return_value=_resp(payload={"histogram": {}})) as g:
        _fetch(tmp_path)
        r = _fetch(tmp_path)
    assert g.call_count == 1 and r.status == "no_data" and r.cached


def test_daily_budget_stops_at_200(tmp_path):
    with patch("requests.get", return_value=_resp(payload=HIST)) as g:
        for i in range(200):
            assert _fetch(tmp_path, what=f"title {i}").status == "ok"
        assert g.call_count == 200
        r = _fetch(tmp_path, what="title 200")
        assert r.status == "error" and r.error == "daily Adzuna budget reached"
        assert g.call_count == 200
        # a cached title is still served after the budget is spent
        assert _fetch(tmp_path, what="title 3").status == "ok"
        # next day resets the counter
        nxt = _fetch(tmp_path, what="title 201", now=lambda: T0 + timedelta(days=1))
        assert nxt.status == "ok" and g.call_count == 201


def test_key_only_in_request_params_not_result(tmp_path):
    with patch("requests.get", return_value=_resp(payload=HIST)):
        r = _fetch(tmp_path)
    _no_secret(json.dumps(r.to_dict()))
    for f in (tmp_path / "c").glob("*"):
        _no_secret(f.read_text())


# ── pure helpers ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Senior Business Analyst (Contract)", "Senior Business Analyst"),
    ("Senior Business Analyst (Contract) - London", "Senior Business Analyst"),
    ("Lead BA | Acme", "Lead BA"),
    ("Junior Data Analyst, Acme Ltd", "Junior Data Analyst"),
    ("Head of Delivery - Remote", "Head of Delivery"),
    ("Principal Consultant", "Principal Consultant"),
    ("Business Analyst - London", "Business Analyst"),
    ("IT Project Manager, Acme Ltd", "IT Project Manager"),
    ("Project Manager at Foo Ltd", "Project Manager"),
    ("Data Analyst £500 - £600 per day Outside IR35", "Data Analyst"),
    ("Product Owner | Remote", "Product Owner"),
    ("  Delivery   Manager  ", "Delivery Manager"),
    ("(Contract)", "Contract"),
    ("", ""),
    (None, ""),
])
def test_clean_job_title(raw, expected):
    assert clean_job_title(raw) == expected


def test_clean_job_title_length_cap():
    assert len(clean_job_title("Analyst " * 40)) <= 80


def test_summarise_empty():
    s = summarise_histogram([], 50000, 40000)
    assert s["total"] == 0 and s["median_bucket_lower"] is None and s["job_percentile"] is None
    assert summarise_histogram(None, None, None)["total"] == 0


def test_summarise_single_bucket():
    s = summarise_histogram([(50000, 7)], 55000, 40000)
    assert s["total"] == 7 and s["median_bucket_lower"] == 50000 and s["median_bucket_upper"] is None
    assert s["job_percentile"] == 50.0 and s["floor_percentile"] == 0.0


def test_summarise_unsorted_dict_string_counts():
    s = summarise_histogram({"60000": "10", "40000": "30", "50000": "20"}, 55000, 45000)
    assert s["total"] == 60
    assert (s["median_bucket_lower"], s["median_bucket_upper"]) == (40000, 50000)
    assert s["job_percentile"] == 66.7 and s["floor_percentile"] == 25.0


def test_summarise_extremes_and_missing():
    b = [(40000, 10), (50000, 10)]
    s = summarise_histogram(b, 200000, None)
    assert s["job_percentile"] == 100.0 and s["floor_percentile"] is None
    assert summarise_histogram(b, 10000, 10000)["job_percentile"] == 0.0


# ── route handler ─────────────────────────────────────────────────────────────

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
    save_reviewed_job(JobPosting(
        job_id="job-1", job_title="Senior Business Analyst (Contract)", company="Acme",
        description_raw="d", source_type="copied_text", source_ref=None, location="London",
        work_mode=None, employment_type=None, salary_min_gbp=50000, salary_max_gbp=60000), cfg.state_root)
    return cfg


def test_route_regex_registered():
    import inspect
    from src import ui_routes
    assert "salary-benchmark" in inspect.getsource(ui_routes)
    assert ui_routes.handle_job_salary_benchmark is ui_handlers.handle_job_salary_benchmark


@pytest.mark.parametrize("bad", ["../etc/passwd", "a b", "a/b", "", "id;rm", "x%00"])
def test_route_400_bad_id_before_file_access(config, bad):
    r = _Resp()
    with patch.object(ui_handlers, "load_reviewed_job") as ld, patch("requests.get") as g:
        ui_handlers.handle_job_salary_benchmark(None, config, r, bad)
    assert r.status == HTTPStatus.BAD_REQUEST
    ld.assert_not_called()
    g.assert_not_called()


def test_route_404_unknown(config):
    r = _Resp()
    with patch("requests.get") as g:
        ui_handlers.handle_job_salary_benchmark(None, config, r, "nope-1")
    assert r.status == HTTPStatus.NOT_FOUND
    g.assert_not_called()


def test_route_200_mocked_http(config):
    r = _Resp()
    with patch("requests.get", return_value=_resp(payload=HIST)) as g:
        ui_handlers.handle_job_salary_benchmark(None, config, r, "job-1")
    assert r.status == HTTPStatus.OK
    p = r.json_sent
    assert p["ok"] and p["status"] == "ok" and p["query"] == "Senior Business Analyst"
    assert p["job_salary"] == 55000 and p["floor"] == 45000 and p["source"] == "Adzuna"
    assert p["summary"]["total"] == 60 and p["summary"]["job_percentile"] == 66.7
    assert g.call_args.kwargs["params"]["what"] == "senior business analyst"
    _no_secret(json.dumps(p))
    assert (config.state_root / "cache" / "adzuna_salary").is_dir()


def test_route_unavailable_creds(config, monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID")
    r = _Resp()
    with patch("requests.get") as g, patch("src.job_sources.adzuna_source._ensure_adzuna_env_loaded"):
        ui_handlers.handle_job_salary_benchmark(None, config, r, "job-1")
    assert r.status == HTTPStatus.OK and r.json_sent["status"] == "unavailable" and not r.json_sent["ok"]
    g.assert_not_called()


def test_route_upstream_error_is_502_without_secret(config):
    r = _Resp()
    with patch("requests.get", return_value=_resp(status=429)):
        ui_handlers.handle_job_salary_benchmark(None, config, r, "job-1")
    assert r.status == HTTPStatus.BAD_GATEWAY and r.json_sent["status"] == "error"
    _no_secret(json.dumps(r.json_sent))


def test_route_does_not_change_analysis_files(config):
    before = sorted(p.name for p in config.state_root.rglob("*.json") if "cache" not in p.parts)
    with patch("requests.get", return_value=_resp(payload=HIST)):
        ui_handlers.handle_job_salary_benchmark(None, config, _Resp(), "job-1")
    after = sorted(p.name for p in config.state_root.rglob("*.json") if "cache" not in p.parts)
    assert before == after


# ── rendered page ─────────────────────────────────────────────────────────────

def _vm(has_analysis=True, job_id="job-001"):
    import dataclasses
    values = {}
    for f in dataclasses.fields(JobPageViewModel):
        t = str(f.type)
        values[f.name] = [] if t.startswith("list") else False if t.startswith("bool") else (
            "" if t.startswith("str") and "None" not in t else None)
    values.update(job_id=job_id, job_title="BA", company="Example Co", has_analysis=has_analysis,
                  match_score=85.0, confidence="high", decision="apply", effective_decision="apply",
                  flash_kind="info", model_label="m", source_type="copied_text")
    return JobPageViewModel(**values)


@pytest.mark.parametrize("has_analysis", [True, False])
@pytest.mark.parametrize("embed", [True, False])
def test_job_page_has_panel_and_button(has_analysis, embed):
    import dataclasses
    vm = dataclasses.replace(_vm(has_analysis), embed=embed)
    html = render_job_page(vm)
    assert 'id="sb-panel"' in html and 'data-job-id="job-001"' in html
    assert "Check market salary" in html and "Salary benchmark" in html
    assert "/salary-benchmark" in html and "Source: Adzuna" in html
    assert "fetch(" in html and html.count('id="sb-panel"') == 1


def test_panel_escapes_job_id():
    from src.ui_render import render_salary_benchmark_panel
    html = render_salary_benchmark_panel('x"><script>alert(1)</script>')
    assert "<script>alert(1)</script>" not in html


def test_page_render_makes_no_http_call():
    with patch("requests.get") as g:
        render_job_page(_vm())
    g.assert_not_called()
