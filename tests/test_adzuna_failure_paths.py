"""Offline regression coverage for explicit Adzuna search failures (AC1-AC11 of
docs/tasks/2026-11-06-adzuna-search-failure-spec.md). Synthetic data and fake keys only."""
import html
import json
import logging
import re
import threading
import traceback
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from src.job_sources import adzuna_client, adzuna_source
import src.job_sources.source_registry as registry
import src.job_hunt_scheduler as scheduler
import src.job_hunt_saved_searches as searches
import src.ui_handlers as handlers
from src.job_hunt_index import open_db, is_already_indexed
from src.job_hunt_profile import candidate_profile_from_dict
from src.job_hunt_saved_searches import SavedSearch
from src.job_hunt_storage import ensure_storage_layout
from src.ui_routes import _build_handler
from src.ui_state import UIServerConfig
from test_ui import _running_ui_server, _http_get

FAKE_KEY = "fake-adzuna-key-in-url"
URL = f"https://api.adzuna.com/v1/api/jobs/gb/search/1?app_id=fake-id&app_key={FAKE_KEY}"
LEAK_TEXT = f"private failure for url: {URL}"


@pytest.fixture(autouse=True)
def _restore_source_registry():
    snapshot = dict(registry._REGISTRY)
    # Earlier test modules can leave a stub registered under "adzuna"; these tests need the real one.
    adzuna_source._register()
    try:
        yield
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(snapshot)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "fake-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", FAKE_KEY)
    # Nothing may be written to data/, and an unmocked request must fail the test.
    monkeypatch.setattr(adzuna_client, "save_raw_response", lambda content, source: None)
    monkeypatch.setattr(scheduler, "extract_skills_from_text",
                        lambda text: (["python", "sql"], ["excel"], None))

    def _no_network(*args, **kwargs):
        raise AssertionError("unmocked requests.get call")

    monkeypatch.setattr(requests, "get", _no_network)


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    response.url = URL
    return requests.exceptions.HTTPError(LEAK_TEXT, response=response)


# (id, failure, message, expected log text or None for no-log, raised-in-except)
CLIENT_CASES = [
    ("id-missing", "no-id", "Adzuna API keys are not set", None, False),
    ("key-missing", "no-key", "Adzuna API keys are not set", None, False),
    ("both-missing", "no-both", "Adzuna API keys are not set", None, False),
    ("429", 429, "Adzuna rate limit reached (HTTP 429)",
     "Adzuna API rate limit exceeded (429). Raising AdzunaFetchError.", False),
    ("401", 401, "Adzuna returned HTTP 401: check the API keys",
     "HTTP error occurred while fetching from Adzuna (status 401).", True),
    ("403", 403, "Adzuna returned HTTP 403: check the API keys",
     "HTTP error occurred while fetching from Adzuna (status 403).", True),
    ("500", 500, "Adzuna returned HTTP 500",
     "HTTP error occurred while fetching from Adzuna (status 500).", True),
    ("timeout", requests.exceptions.Timeout(LEAK_TEXT), "Adzuna request timed out",
     "Request error occurred while fetching from Adzuna (Timeout).", True),
    ("connection", requests.exceptions.ConnectionError(LEAK_TEXT),
     "Adzuna request failed (ConnectionError)",
     "Request error occurred while fetching from Adzuna (ConnectionError).", True),
    ("request", requests.exceptions.RequestException(LEAK_TEXT),
     "Adzuna request failed (RequestException)",
     "Request error occurred while fetching from Adzuna (RequestException).", True),
    ("json-stdlib", json.JSONDecodeError(LEAK_TEXT, "x", 0), "Adzuna returned invalid JSON",
     "Failed to decode JSON response from Adzuna.", True),
    ("json-requests", requests.exceptions.JSONDecodeError(LEAK_TEXT, "x", 0),
     "Adzuna returned invalid JSON", "Failed to decode JSON response from Adzuna.", True),
    ("status-none", None, "Adzuna returned an HTTP error",
     "HTTP error occurred while fetching from Adzuna.", True),
    ("status-str", FAKE_KEY, "Adzuna returned an HTTP error",
     "HTTP error occurred while fetching from Adzuna.", True),
    ("status-bool", True, "Adzuna returned an HTTP error",
     "HTTP error occurred while fetching from Adzuna.", True),
    ("status-600", 600, "Adzuna returned an HTTP error",
     "HTTP error occurred while fetching from Adzuna.", True),
]
# Statuses that go through an HTTPError carrying a response object with that status value.
HTTP_STATUS_IDS = {"401", "403", "500", "status-none", "status-str", "status-bool", "status-600"}


def _arm(case_id, failure, monkeypatch):
    """Install the mock for one failure and return the requests.get mock."""
    response = Mock(status_code=200, url=URL, text="{}")
    get = Mock(return_value=response)
    if case_id == "id-missing":
        monkeypatch.delenv("ADZUNA_APP_ID")
    elif case_id == "key-missing":
        monkeypatch.delenv("ADZUNA_APP_KEY")
    elif case_id == "both-missing":
        monkeypatch.delenv("ADZUNA_APP_ID")
        monkeypatch.delenv("ADZUNA_APP_KEY")
    elif case_id == "429":
        response.status_code = 429
    elif case_id in HTTP_STATUS_IDS:
        error_response = Mock(status_code=failure, url=URL)
        response.status_code = failure if isinstance(failure, int) and not isinstance(failure, bool) else 500
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            LEAK_TEXT, response=error_response)
    elif isinstance(failure, (json.JSONDecodeError, requests.exceptions.JSONDecodeError)):
        response.json.side_effect = failure
    else:
        get.side_effect = failure
    monkeypatch.setattr(requests, "get", get)
    return get


@pytest.mark.parametrize("case_id,failure,message,log_text,in_except", CLIENT_CASES,
                         ids=[c[0] for c in CLIENT_CASES])
def test_failure_message_log_and_key_safety(case_id, failure, message, log_text, in_except,
                                            monkeypatch, caplog):
    """AC1, AC2, AC5, AC6: exact message, fixed log text, and no key anywhere."""
    caplog.set_level(logging.DEBUG)
    get = _arm(case_id, failure, monkeypatch)
    with pytest.raises(adzuna_client.AdzunaFetchError) as error:
        adzuna_client.fetch_adzuna_jobs("BA", "London")
    exc = error.value
    assert isinstance(exc, RuntimeError)
    assert str(exc) == message
    if case_id.endswith("missing"):
        get.assert_not_called()

    trace = "".join(traceback.format_exception(exc))
    for text in (str(exc), trace, caplog.text):
        assert FAKE_KEY not in text
        assert URL not in text
        assert "private failure" not in text
    assert all(record.exc_info is None for record in caplog.records)
    if in_except:
        assert exc.__cause__ is None
        assert exc.__suppress_context__ is True
    else:
        assert exc.__cause__ is None

    adzuna_records = [r.getMessage() for r in caplog.records if r.name == adzuna_client.logger.name]
    if log_text is None:
        assert adzuna_records == ["ADZUNA_APP_ID or ADZUNA_APP_KEY not found in environment variables."]
    else:
        assert adzuna_records == [log_text]
    assert "Returning empty list" not in caplog.text


@pytest.mark.parametrize("payload", [
    {}, {"error": "x"}, {"results": None}, {"results": "x"}, {"results": ["x"]}, None, "x", [],
], ids=["empty-dict", "error-key", "results-null", "results-str", "results-str-item",
        "null", "string", "list"])
def test_unexpected_response(payload, monkeypatch):
    """AC3."""
    monkeypatch.setattr(requests, "get", Mock(return_value=Mock(
        status_code=200, url=URL, text="{}", json=lambda: payload)))
    with pytest.raises(adzuna_client.AdzunaFetchError) as error:
        adzuna_client.fetch_adzuna_jobs("BA", "London")
    assert str(error.value) == "Adzuna returned an unexpected response"
    assert FAKE_KEY not in str(error.value)


@pytest.mark.parametrize("payload", [
    {"results": []},
    {"__CLASS__": "x", "count": 0, "mean": 0, "results": []},
], ids=["bare", "full"])
def test_valid_empty_response(payload, monkeypatch):
    """AC4."""
    monkeypatch.setattr(requests, "get", Mock(return_value=Mock(
        status_code=200, url=URL, text="{}", json=lambda: payload)))
    assert adzuna_client.fetch_adzuna_jobs("BA", "London") == []


def test_results_returned_unchanged(monkeypatch):
    """AC4."""
    payload = {"results": [{"id": "1"}]}
    monkeypatch.setattr(requests, "get", Mock(return_value=Mock(
        status_code=200, url=URL, text="{}", json=lambda: payload)))
    assert adzuna_client.fetch_adzuna_jobs("BA", "London") == [{"id": "1"}]


# ── Callers (AC7-AC11) ────────────────────────────────────────────────────────

TIMEOUT_MESSAGE = "Adzuna request timed out"
TIMEOUT_SUMMARY = f"Run failed: fetch failed: {TIMEOUT_MESSAGE}. No jobs were fetched."


def _timeout():
    return requests.exceptions.Timeout(LEAK_TEXT)


def _ok_response(payload):
    return Mock(status_code=200, url=URL, text="{}", json=lambda: payload)


def _raw_job(job_id):
    return {"id": str(job_id), "title": "Business Analyst", "company": {"display_name": "Acme"},
            "location": {"display_name": "London"}, "description": "python sql analytics",
            "redirect_url": f"https://example.test/{job_id}", "salary_min": 50000, "salary_max": 60000}


def _search(sid, keywords="analyst"):
    return SavedSearch(sid, sid, "adzuna", {"keywords": keywords}, True, "2026-11-06T00:00:00", None, 0)


def _setup(tmp_path):
    ensure_storage_layout(tmp_path)
    db = tmp_path / "job_hunt_index.db"
    open_db(db).close()
    return SimpleNamespace(state_root=tmp_path, profile_path=tmp_path / "profile.json"), db


def _profile():
    return candidate_profile_from_dict({"candidate_id": "synthetic", "skills": ["python"],
                                        "target_roles": ["Business Analyst"], "digest_threshold": 0})


def test_pipeline_continues_after_adzuna_failure(tmp_path, monkeypatch):
    """AC7."""
    config, db = _setup(tmp_path)

    def get(url, params=None, **kwargs):
        if params["what"] == "fail":
            raise _timeout()
        return _ok_response({"results": [_raw_job(123)]})

    monkeypatch.setattr(requests, "get", get)
    result = scheduler.run_digest_pipeline(
        config=config, saved_searches=[_search("broken", "fail"), _search("working", "work")],
        profile=_profile(), db_path=db)
    assert result.errors == [f"broken: fetch failed: {TIMEOUT_MESSAGE}"]
    assert result.searches_run == 1
    assert result.jobs_new == 1
    assert is_already_indexed(db, "adzuna", "123")


def _run_one(tmp_path, monkeypatch, get):
    config, db = _setup(tmp_path)
    monkeypatch.setattr(requests, "get", get)
    scheduler.run_digest_pipeline(config=config, saved_searches=[_search("s1")],
                                  profile=_profile(), db_path=db, trigger="manual")
    row = searches.list_search_runs("s1", state_root=tmp_path)[0]
    # The list route adds the summary on read (ui_handlers.py), so do the same here.
    return {**row, **searches.search_run_summary(row, search_id="s1", source_name="Adzuna")}


def test_run_record_timeout(tmp_path, monkeypatch):
    """AC8a."""
    row = _run_one(tmp_path, monkeypatch, Mock(side_effect=_timeout()))
    assert row["status"] == "failed"
    assert row["errors"] == [f"fetch failed: {TIMEOUT_MESSAGE}"]
    assert row["summary"] == TIMEOUT_SUMMARY
    assert "returned no jobs" not in row["summary"]


def test_run_record_real_empty_result(tmp_path, monkeypatch):
    """AC8b."""
    row = _run_one(tmp_path, monkeypatch, Mock(return_value=_ok_response({"results": []})))
    assert row["status"] == "ok"
    assert row["summary"] == "Run done: Adzuna returned no jobs for this search."


def test_run_record_missing_keys(tmp_path, monkeypatch):
    """AC8c."""
    monkeypatch.delenv("ADZUNA_APP_ID")
    monkeypatch.delenv("ADZUNA_APP_KEY")
    get = Mock()
    row = _run_one(tmp_path, monkeypatch, get)
    get.assert_not_called()
    assert row["status"] == "failed"
    assert row["errors"] == ["fetch failed: Adzuna API keys are not set"]


def test_run_now_http_reports_failure(tmp_path, monkeypatch):
    """AC8d."""
    monkeypatch.setattr(requests, "get", Mock(side_effect=_timeout()))
    state = tmp_path / "state"
    ensure_storage_layout(state)
    monkeypatch.setattr(searches, "get_enabled_sources", lambda: ["adzuna"])
    monkeypatch.setattr(handlers, "get_enabled_sources", lambda: ["adzuna"])
    searches.save_saved_search(_search("s1"), state_root=state)
    monkeypatch.setattr(handlers, "_load_active_profile", lambda c:
                        candidate_profile_from_dict({"candidate_id": "synthetic"}))
    config = UIServerConfig(profile_path=tmp_path / "unused.json", state_root=state,
                            report_dir=tmp_path / "reports", host="127.0.0.1", port=0)
    server = ThreadingHTTPServer((config.host, config.port), _build_handler(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = urllib.request.Request(base + "/saved-searches/s1/run-now", method="POST",
                                         headers={"Origin": base})
        with urllib.request.urlopen(request) as response:
            raw = response.read().decode()
        payload = json.loads(raw)
        assert payload["ok"] is True
        assert payload["run_status"] == "failed"
        assert payload["summary"] == TIMEOUT_SUMMARY
        assert FAKE_KEY not in raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_page_shows_failure_not_no_results(tmp_path, monkeypatch):
    """AC9, failure half."""
    monkeypatch.setattr(requests, "get", Mock(side_effect=_timeout()))
    with _running_ui_server(tmp_path) as (base, _):
        status, body = _http_get(base + "/search/adzuna?keywords=analyst&locationName=London")
    assert status == 200
    assert "Adzuna search unavailable" in body
    assert "Adzuna search failed: Adzuna request timed out" in body
    assert "No Adzuna results found" not in body
    assert FAKE_KEY not in body


def test_page_shows_no_results_for_real_empty(tmp_path, monkeypatch):
    """AC9, empty half."""
    monkeypatch.setattr(requests, "get", Mock(return_value=_ok_response({"results": []})))
    with _running_ui_server(tmp_path) as (base, _):
        status, body = _http_get(base + "/search/adzuna?keywords=analyst&locationName=London")
    assert status == 200
    assert "No Adzuna results found" in body
    assert "Adzuna search unavailable" not in body


def test_more_failure_preserves_page_for_retry(tmp_path, monkeypatch):
    """AC10."""
    pages = []

    def get(url, params=None, **kwargs):
        pages.append(int(re.search(r"/search/(\d+)$", url).group(1)))
        if len(pages) == 2:
            raise _timeout()
        return _ok_response({"results": [_raw_job(len(pages) * 100 + i) for i in range(10)]})

    monkeypatch.setattr(requests, "get", get)
    with _running_ui_server(tmp_path) as (base, _):
        status, body = _http_get(base + "/search/adzuna?keywords=analyst&locationName=London&resultsToTake=10")
        assert status == 200
        more_url = html.unescape(body.split('data-next-url="', 1)[1].split('"', 1)[0])
        status, body = _http_get(base + more_url)
        assert status == 200
        assert json.loads(body) == {"ok": False, "error": TIMEOUT_MESSAGE}
        status, body = _http_get(base + more_url)
        assert status == 200
        assert json.loads(body)["ok"] is True
    assert pages == [1, 2, 2]


def test_multi_keyword_page_keeps_working_keyword(tmp_path, monkeypatch):
    """AC11."""
    def get(url, params=None, **kwargs):
        if params["what"] == "fail":
            raise _timeout()
        return _ok_response({"results": [_raw_job(777)]})

    monkeypatch.setattr(requests, "get", get)
    with _running_ui_server(tmp_path) as (base, _):
        status, body = _http_get(base + "/search/adzuna?keywords=fail%2C+work&locationName=London")
    assert status == 200
    assert "Business Analyst" in body
    assert "Acme" in body
