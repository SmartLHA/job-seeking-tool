"""Offline regression coverage for explicit Reed search failures (AC9–AC11)."""
import html
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from src.job_sources import reed_client, reed_source
import src.job_sources.source_registry as registry
import src.job_hunt_scheduler as scheduler
from src.job_hunt_index import open_db, is_already_indexed
from src.job_hunt_profile import candidate_profile_from_dict
from src.job_hunt_saved_searches import SavedSearch
from src.job_hunt_storage import ensure_storage_layout
from test_ui import _running_ui_server, _http_get


@pytest.fixture(autouse=True)
def _restore_source_registry():
    snapshot = dict(registry._REGISTRY)
    try:
        yield
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(snapshot)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "fake-secret-reed-key")
    monkeypatch.setattr(reed_client, "_ensure_env_loaded", lambda: None)
    monkeypatch.setattr(scheduler, "extract_skills_from_text",
                        lambda text: (["python", "sql"], ["excel"], None))


@pytest.mark.parametrize("failure,message", [
    ("missing", "Reed API key is not set"),
    (429, "Reed rate limit reached (HTTP 429)"),
    (401, "Reed returned HTTP 401: check the API key"),
    (403, "Reed returned HTTP 403: check the API key"),
    (500, "Reed returned HTTP 500"),
    (requests.exceptions.Timeout("fake-secret-reed-key"), "Reed request timed out"),
    (requests.exceptions.ConnectionError("fake-secret-reed-key"), "Reed request failed (ConnectionError)"),
    (json.JSONDecodeError("fake-secret-reed-key", "x", 0), "Reed returned invalid JSON"),
    (requests.exceptions.JSONDecodeError("fake-secret-reed-key", "x", 0), "Reed returned invalid JSON"),
])
def test_failure_messages(failure, message, monkeypatch):
    response = Mock(status_code=200)
    get = Mock(return_value=response)
    if failure == "missing":
        monkeypatch.delenv("REED_API_KEY")
    elif isinstance(failure, int):
        response.status_code = failure
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "fake-secret-reed-key", response=response)
    elif isinstance(failure, (json.JSONDecodeError, requests.exceptions.JSONDecodeError)):
        response.json.side_effect = failure
    else:
        get.side_effect = failure
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(reed_client.ReedFetchError) as error:
        reed_client.fetch_reed_jobs("BA", "London", save_raw=False)
    assert isinstance(error.value, RuntimeError)
    assert str(error.value) == message
    assert "fake-secret-reed-key" not in str(error.value)
    if failure == "missing":
        get.assert_not_called()


@pytest.mark.parametrize("payload", [{}, {"error": "x"}, {"results": None}, {"results": "x"}, None, "x"])
def test_unexpected_response(payload, monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(return_value=Mock(status_code=200, json=lambda: payload)))
    with pytest.raises(reed_client.ReedFetchError) as error:
        reed_client.fetch_reed_jobs("BA", "London", save_raw=False)
    assert str(error.value) == "Reed returned an unexpected response"
    assert "fake-secret-reed-key" not in str(error.value)


@pytest.mark.parametrize("payload", [[], {"results": []}])
def test_valid_empty_response(payload, monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(return_value=Mock(status_code=200, json=lambda: payload)))
    assert reed_client.fetch_reed_jobs("BA", "London", save_raw=False) == []


def test_pipeline_continues_after_reed_failure(tmp_path, monkeypatch):
    ensure_storage_layout(tmp_path)
    db = tmp_path / "job_hunt_index.db"
    open_db(db).close()
    calls = []

    def fetch(keyword, location, max_results, *, skip=0, save_raw=True):
        calls.append(keyword)
        if keyword == "fail":
            raise reed_client.ReedFetchError("Reed request timed out")
        return [{"jobId": 123, "jobTitle": "Business Analyst", "employerName": "Acme",
                 "locationName": "London", "jobDescription": "python sql analytics",
                 "jobUrl": "https://example.test/123"}]

    monkeypatch.setattr(reed_source, "fetch_reed_jobs", fetch)
    # The real normaliser and adapter exercise the production caller boundary.
    source = registry.get_source("reed")
    assert source is not None
    searches = [SavedSearch(sid, sid, "reed", {"keywords": kw}, True,
                            "2026-11-05T00:00:00", None, 0)
                for sid, kw in [("broken", "fail"), ("working", "work")]]
    profile = candidate_profile_from_dict({"candidate_id": "synthetic", "skills": ["python"],
                                          "target_roles": ["Business Analyst"], "digest_threshold": 0})
    result = scheduler.run_digest_pipeline(
        config=SimpleNamespace(state_root=tmp_path, profile_path=tmp_path / "profile.json"),
        saved_searches=searches, profile=profile, db_path=db)
    assert calls == ["fail", "work"]
    assert result.errors == ["broken: fetch failed: Reed request timed out"]
    assert result.searches_run == 1
    assert result.jobs_new == 1
    assert is_already_indexed(db, "reed", "123")


def test_reed_page_displays_fetch_error(tmp_path, monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(side_effect=requests.exceptions.Timeout("private")))
    with _running_ui_server(tmp_path) as (base, _):
        status, body = _http_get(base + "/search/reed?keywords=analyst&locationName=London")
    assert status == 200
    assert "Reed request timed out" in body
    assert "No Reed results found" not in body


def test_reed_more_failure_preserves_offset_for_retry(tmp_path, monkeypatch):
    skips = []

    def fetch(keyword, location, max_results, *, skip=0, save_raw=True):
        skips.append(skip)
        if len(skips) == 2:
            raise reed_client.ReedFetchError("Reed request timed out")
        return [{"jobId": skip + i, "jobTitle": "Analyst", "employerName": "Acme",
                 "locationName": "London", "jobDescription": "python sql",
                 "jobUrl": f"https://example.test/{skip + i}"} for i in range(max_results)]

    monkeypatch.setattr(reed_source, "fetch_reed_jobs", fetch)
    with _running_ui_server(tmp_path) as (base, _):
        status, body = _http_get(base + "/search/reed?keywords=analyst&resultsToTake=10")
        assert status == 200
        more_url = html.unescape(body.split('data-next-url="', 1)[1].split('"', 1)[0])
        assert "resultsSkip=10" in more_url
        status, body = _http_get(base + more_url)
        assert status == 200
        assert json.loads(body) == {"ok": False, "error": "Reed request timed out"}
        status, body = _http_get(base + more_url)
        assert status == 200
        result = json.loads(body)
        assert result["ok"] is True
        assert result["count"] == 10
        assert "resultsSkip=20" in result["next_url"]
    assert skips == [0, 10, 10]
