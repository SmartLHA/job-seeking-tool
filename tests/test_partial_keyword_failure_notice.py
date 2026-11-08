"""Offline coverage for the partly failed multi-keyword search notice (AC1-AC10 and
AC12-AC15 of docs/tasks/2026-11-06-partial-keyword-failure-notice-spec.md).
Synthetic data and fake keys only; any unexpected requests.get call fails the test."""
import dataclasses
import html
import json
import re
import subprocess
import urllib.parse
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from src.job_sources import adzuna_client, adzuna_source, reed_client, reed_source
import src.job_sources.source_registry as registry
import src.ui_handlers as handlers
from test_ui import _running_ui_server, _http_get

FAKE_REED = "fake-secret-reed-key"
FAKE_ADZUNA = "fake-adzuna-key-in-url"
NOTE_ID = 'id="jst-keyword-failure-note"'
LEAK = f"private failure https://api.example.test/x?app_key={FAKE_ADZUNA}&k={FAKE_REED}"


@pytest.fixture(autouse=True)
def _restore_source_registry():
    snapshot = dict(registry._REGISTRY)
    reed_source._register()
    adzuna_source._register()
    try:
        yield
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(snapshot)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", FAKE_REED)
    monkeypatch.setenv("ADZUNA_APP_ID", "fake-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", FAKE_ADZUNA)
    monkeypatch.setattr(reed_client, "_ensure_env_loaded", lambda: None)
    monkeypatch.setattr(reed_client, "save_raw_response", lambda content, source: None)
    monkeypatch.setattr(adzuna_client, "save_raw_response", lambda content, source: None)

    def _no_network(*args, **kwargs):
        raise AssertionError("unmocked requests.get call")

    monkeypatch.setattr(requests, "get", _no_network)


# ── fake upstream, one adapter per source ─────────────────────────────────────

def _reed_job(n):
    return {"jobId": n, "jobTitle": "Business Analyst", "employerName": "Acme",
            "locationName": "London", "jobDescription": "python sql analytics",
            "jobUrl": f"https://example.test/{n}"}


def _adzuna_job(n):
    return {"id": str(n), "title": "Business Analyst", "company": {"display_name": "Acme"},
            "location": {"display_name": "London"}, "description": "python sql analytics",
            "redirect_url": f"https://example.test/{n}", "salary_min": 50000, "salary_max": 60000}


def _ok(payload):
    return Mock(status_code=200, text="{}", json=lambda: payload)


class Upstream:
    """Fake requests.get. `behave(keyword, skip)` returns "timeout", "leak", an
    int (number of jobs) or raises. Records every (keyword, skip)."""

    def __init__(self, source_id, behave):
        self.source_id, self.behave, self.calls = source_id, behave, []

    def __call__(self, url, params=None, **kwargs):
        if self.source_id == "reed":
            keyword, skip = params["keywords"], int(params["resultsToSkip"])
        else:
            keyword = params["what"]
            skip = (int(re.search(r"/search/(\d+)$", url).group(1)) - 1) * int(params["results_per_page"])
        self.calls.append((keyword, skip))
        outcome = self.behave(keyword, skip)
        if outcome == "timeout":
            raise requests.exceptions.Timeout(LEAK)
        if outcome == "leak":
            raise requests.exceptions.ConnectionError(LEAK)
        make = _reed_job if self.source_id == "reed" else _adzuna_job
        rows = [make(abs(hash((keyword, skip))) % 10**6 * 100 + i) for i in range(outcome)]
        return _ok({"results": rows})


SOURCES = [
    pytest.param("reed", "Reed request timed out", id="reed"),
    pytest.param("adzuna", "Adzuna request timed out", id="adzuna"),
]


def _install(monkeypatch, source_id, behave):
    upstream = Upstream(source_id, behave)
    monkeypatch.setattr(requests, "get", upstream)
    return upstream


def _first(base, source_id, keywords, extra=""):
    q = urllib.parse.urlencode({"keywords": keywords, "locationName": "London", "resultsToTake": "10"})
    return _http_get(f"{base}/search/{source_id}?{q}{extra}")


def _more_url(page):
    return html.unescape(re.search(r'data-next-url="([^"]+)"', page).group(1))


def _more(base, url):
    status, body = _http_get(base + url)
    assert status == 200
    return json.loads(body)


# ── first page: AC1-AC5 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("source_id,message", SOURCES)
def test_ac1_ac2_first_page_names_failed_keyword(tmp_path, monkeypatch, source_id, message):
    _install(monkeypatch, source_id, lambda kw, skip: "timeout" if kw == "broken" else 1)
    with _running_ui_server(tmp_path) as (base, _):
        status, body = _first(base, source_id, "broken, analyst")
    assert status == 200
    assert "Business Analyst" in body and "Acme" in body
    assert NOTE_ID in body and "Some keywords could not be searched" in body
    assert f"<strong>broken</strong>: {message}" in body
    assert "Next page tries these keywords again." in body
    assert "Search again to try these keywords again." not in body
    assert body.index(NOTE_ID) < body.index('id="jst-cards-container"')
    assert "_partial_error_count" not in body


@pytest.mark.parametrize("source_id,message", SOURCES)
def test_ac3_one_row_per_failed_keyword_in_order(tmp_path, monkeypatch, source_id, message):
    _install(monkeypatch, source_id, lambda kw, skip: 1 if kw == "analyst" else "timeout")
    with _running_ui_server(tmp_path) as (base, _):
        status, body = _first(base, source_id, "zeta, analyst, alpha")
    note = body[body.index(NOTE_ID):]
    note = note[:note.index("Next page tries")]
    assert note.count("<li>") == 2
    assert note.index("<strong>zeta</strong>") < note.index("<strong>alpha</strong>")
    assert note.count(message) == 2
    assert "<strong>analyst</strong>" not in note


@pytest.mark.parametrize("source_id,message", SOURCES)
def test_ac4_failed_plus_empty_keyword_keeps_notice_and_next_button(tmp_path, monkeypatch, source_id, message):
    _install(monkeypatch, source_id, lambda kw, skip: "timeout" if kw == "broken" else 0)
    with _running_ui_server(tmp_path) as (base, _):
        status, body = _first(base, source_id, "broken, empty")
    assert status == 200
    assert NOTE_ID in body and f"<strong>broken</strong>: {message}" in body
    assert "Next page tries these keywords again." in body
    assert 'data-next-url="' in body and 'id="jst-cards-container"' in body
    assert "search unavailable" not in body


def test_ac4_search_again_line_without_more_url():
    page = handlers._render_search_jobs_tab(
        search_values={"_source_id": "reed", "_keyword_failures": [{"keyword": "broken", "message": "Reed request timed out"}]},
        reed_results=[])
    assert NOTE_ID in page
    assert "Search again to try these keywords again." in page
    assert "Next page tries these keywords again." not in page
    with_url = handlers._render_search_jobs_tab(
        search_values={"_source_id": "reed", "_more_url": "/synthetic",
                       "_keyword_failures": [{"keyword": "broken", "message": "m"}]},
        reed_results=[])
    assert "Next page tries these keywords again." in with_url


@pytest.mark.parametrize("source_id,message", SOURCES)
def test_ac5_no_failure_no_notice(tmp_path, monkeypatch, source_id, message):
    _install(monkeypatch, source_id, lambda kw, skip: 1)
    with _running_ui_server(tmp_path) as (base, _):
        status, body = _first(base, source_id, "one, two")
    assert status == 200 and "Business Analyst" in body
    assert NOTE_ID not in body


@pytest.mark.parametrize("source_id,message", SOURCES)
@pytest.mark.parametrize("keywords", ["broken", "broken, worse"], ids=["single", "all-failed"])
def test_ac5_single_or_all_failed_keeps_banner_without_notice(tmp_path, monkeypatch, source_id, message, keywords):
    _install(monkeypatch, source_id, lambda kw, skip: "timeout")
    with _running_ui_server(tmp_path) as (base, _):
        status, body = _first(base, source_id, keywords)
    name = "Reed" if source_id == "reed" else "Adzuna"
    assert status == 200
    assert f"{name} search unavailable" in body
    assert f"{name} search failed: " in body and message in body
    assert NOTE_ID not in body


def test_ac5_banner_wins_over_notice_in_direct_render():
    page = handlers._render_search_jobs_tab(
        search_values={"_source_id": "reed", "_more_url": "/x",
                       "_keyword_failures": [{"keyword": "broken", "message": "m"}]},
        reed_results=[], reed_error="Search settings changed. Run the search again.")
    assert "Search settings changed" in page
    assert NOTE_ID not in page


# ── More route: AC6-AC10 ──────────────────────────────────────────────────────

def _more_setup(monkeypatch, source_id, behave):
    """First page works for both keywords (full pages), so a More URL exists."""
    return _install(monkeypatch, source_id, behave)


@pytest.mark.parametrize("source_id,message", SOURCES)
def test_ac6_more_partial_failure_then_retry(tmp_path, monkeypatch, source_id, message):
    state = {"broken_ok": True}

    def behave(kw, skip):
        if kw == "broken":
            return 10 if (skip == 0 or state["broken_ok"]) else "timeout"
        return 10

    upstream = _more_setup(monkeypatch, source_id, behave)
    with _running_ui_server(tmp_path) as (base, _):
        status, page = _first(base, source_id, "broken, analyst")
        assert NOTE_ID not in page
        state["broken_ok"] = False
        payload = _more(base, _more_url(page))
        assert payload["ok"] is True and payload["has_more"] is True
        assert "keyword_failure_html" in payload
        note = payload["keyword_failure_html"]
        assert f"<strong>broken</strong>: {message}" in note
        assert "Next page tries these keywords again." in note
        cursors = urllib.parse.parse_qs(urllib.parse.urlsplit(payload["next_url"]).query)["keywordCursors"][0]
        assert cursors == "10,20"
        state["broken_ok"] = True
        retry = _more(base, payload["next_url"])
        assert retry["ok"] is True and "keyword_failure_html" not in retry
    assert ("broken", 10) in upstream.calls and upstream.calls.count(("broken", 10)) == 2


@pytest.mark.parametrize("source_id,message", SOURCES)
def test_ac7_more_failed_plus_empty_keyword(tmp_path, monkeypatch, source_id, message):
    def behave(kw, skip):
        if skip == 0:
            return 10
        return "timeout" if kw == "broken" else 0

    _more_setup(monkeypatch, source_id, behave)
    with _running_ui_server(tmp_path) as (base, _):
        status, page = _first(base, source_id, "broken, analyst")
        payload = _more(base, _more_url(page))
    assert payload["ok"] is True and payload["visible_count"] == 0
    assert "<strong>broken</strong>" in payload["keyword_failure_html"]
    assert payload["has_more"] is True


@pytest.mark.parametrize("source_id,message", SOURCES)
def test_ac8_more_all_failed_keeps_existing_error(tmp_path, monkeypatch, source_id, message):
    def behave(kw, skip):
        return 10 if skip == 0 else "timeout"

    _more_setup(monkeypatch, source_id, behave)
    with _running_ui_server(tmp_path) as (base, _):
        status, page = _first(base, source_id, "broken, analyst")
        url = _more_url(page)
        payload = _more(base, url)
        assert payload["ok"] is False and message in payload["error"]
        assert "keyword_failure_html" not in payload
        again = _more(base, url)  # cursor did not advance: same URL is still valid
        assert again["ok"] is False


@pytest.mark.parametrize("source_id,message", SOURCES)
def test_ac9_replay_returns_same_payload_without_new_call(tmp_path, monkeypatch, source_id, message):
    def behave(kw, skip):
        return "timeout" if (kw == "broken" and skip > 0) else 10

    upstream = _more_setup(monkeypatch, source_id, behave)
    with _running_ui_server(tmp_path) as (base, _):
        status, page = _first(base, source_id, "broken, analyst")
        url = _more_url(page)
        first = _more(base, url)
        calls = len(upstream.calls)
        second = _more(base, url)
    assert "keyword_failure_html" in first
    assert second == first
    assert len(upstream.calls) == calls


@pytest.mark.parametrize("source_id,message", SOURCES)
def test_ac10_no_failure_payload_has_no_field(tmp_path, monkeypatch, source_id, message):
    _more_setup(monkeypatch, source_id, lambda kw, skip: 10)
    with _running_ui_server(tmp_path) as (base, _):
        status, page = _first(base, source_id, "broken, analyst")
        payload = _more(base, _more_url(page))
    assert payload["ok"] is True
    assert "keyword_failure_html" not in payload


# ── safety: AC12-AC14 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("source_id,message", SOURCES)
def test_ac12_keys_never_reach_page_or_json(tmp_path, monkeypatch, source_id, message):
    def behave(kw, skip):
        if kw == "broken":
            return "leak" if skip > 0 else 10
        return 10

    _more_setup(monkeypatch, source_id, lambda kw, skip: ("leak" if kw == "broken" else 1) if skip == 0 else behave(kw, skip))
    with _running_ui_server(tmp_path) as (base, _):
        status, page = _first(base, source_id, "broken, analyst")
        assert NOTE_ID in page
    for secret in (FAKE_REED, FAKE_ADZUNA, "api.example.test", "private failure"):
        assert secret not in page

    _more_setup(monkeypatch, source_id, behave)
    with _running_ui_server(tmp_path) as (base, _):
        status, page = _first(base, source_id, "broken, analyst")
        raw_status, raw = _http_get(base + _more_url(page))
    assert raw_status == 200 and "keyword_failure_html" in json.loads(raw)
    for secret in (FAKE_REED, FAKE_ADZUNA, "api.example.test", "private failure"):
        assert secret not in raw and secret not in page


def _untyped_source(source_id, handler):
    real = registry.get_source(source_id)
    return dataclasses.replace(real, search_handler=handler)


def test_ac13_untyped_exception_shows_fixed_text(tmp_path, monkeypatch):
    def handler(values):
        if values["keywords"] == "broken":
            raise ValueError(LEAK)
        return [{"source": "reed", "source_job_id": "1", "title": "Business Analyst",
                 "company": "Acme", "location": "London"}]

    source = _untyped_source("reed", handler)
    real_get = registry.get_source
    monkeypatch.setattr(registry, "get_source", lambda sid: source if sid == "reed" else real_get(sid))
    with _running_ui_server(tmp_path) as (base, _):
        status, body = _first(base, "reed", "broken, analyst")
    assert status == 200
    assert NOTE_ID in body
    assert "<strong>broken</strong>: Reed search failed" in body
    for secret in (FAKE_REED, FAKE_ADZUNA, "api.example.test", "private failure"):
        assert secret not in body


def test_ac13_linkedin_runtime_error_uses_fixed_text():
    calls = []

    def handler(values):
        calls.append(values["keywords"])
        if values["keywords"] == "broken":
            raise RuntimeError(f"LinkedIn request error: {LEAK}")
        return [{"source": "linkedin", "source_job_id": "1", "title": "Analyst"}]

    source = _untyped_source("linkedin", handler)
    failures = []
    results, _full, sub_errors, offsets = handlers._run_multi_keyword_search(
        source, {"keywords": "", "resultsSkip": "0", "resultsToTake": "10"}, ["broken", "analyst"], failures=failures)
    assert failures == [{"keyword": "broken", "message": f"{source.display_name} search failed"}]
    assert len(results) == 1 and offsets[0] == 0
    assert sub_errors and "private failure" in sub_errors[0]  # existing strings are unchanged
    note = handlers._render_keyword_failure_notice(failures, True)
    assert f"{source.display_name} search failed" in note
    for secret in (FAKE_REED, FAKE_ADZUNA, "api.example.test", "private failure"):
        assert secret not in note


@pytest.mark.parametrize("source_id,message", SOURCES)
def test_ac14_keyword_is_escaped(tmp_path, monkeypatch, source_id, message):
    evil = "<img src=x onerror=alert(1)>"

    def behave(kw, skip):
        if kw == evil:
            return "timeout"
        return 10

    _more_setup(monkeypatch, source_id, behave)
    with _running_ui_server(tmp_path) as (base, _):
        status, page = _first(base, source_id, f"{evil}, analyst")
        assert status == 200
        note_html = page[page.index(NOTE_ID):]
        note_html = note_html[:note_html.index("Next page tries")]
        assert "<img src=x" not in note_html
        assert "&lt;img src=x onerror=alert(1)&gt;" in note_html
        payload = _more(base, _more_url(page))
    assert payload["ok"] is True
    note = payload["keyword_failure_html"] if "keyword_failure_html" in payload else ""
    # The failed term is retried on More and fails again, so the field is present.
    assert "<img src=x" not in note and "&lt;img src=x" in note


def test_ac14_direct_render_escapes_keyword_and_message():
    note = handlers._render_keyword_failure_notice(
        [{"keyword": "<script>x</script>", "message": "<b>m</b>"}], True)
    assert "<script>" not in note and "<b>m</b>" not in note
    assert "&lt;script&gt;" in note and "&lt;b&gt;m&lt;/b&gt;" in note


# ── AC15 ──────────────────────────────────────────────────────────────────────

def test_ac15_partial_error_count_removed_from_src():
    root = Path(__file__).resolve().parent.parent
    hits = [str(p) for p in (root / "src").rglob("*.py") if "_partial_error_count" in p.read_text(encoding="utf-8")]
    assert hits == []
