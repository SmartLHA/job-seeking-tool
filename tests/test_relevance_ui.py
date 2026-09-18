"""Slice A (2026-07-21 search/score/filter plan): relevance bucketing wired
into the live /search/{source} endpoint. Fixture required by the plan:
searching "Business Analysis" keeps "Business Analyst"/"BA"/"Senior BA" in
the main results and buckets "Store Manager" into a collapsed "Other
results" section (never hard-dropped)."""
from __future__ import annotations

import json
import html
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

from src.ui_state import UIServerConfig
from src.ui_routes import _build_handler
from src.job_hunt_not_interested import hide_jobs


def _write_profile(tmp_path: Path) -> Path:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "docs").mkdir(parents=True, exist_ok=True)
    (profile_dir / "docs" / "master_cv.md").write_text("# Master CV\n", encoding="utf-8")
    profile_path = profile_dir / "candidate_profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "candidate_id": "cand-001",
                "name": "Mic",
                "target_roles": ["Business Analyst"],
                "locations": ["London"],
                "remote_preference": "remote_friendly",
                "salary_floor_gbp": 50000,
                "right_to_work_uk": True,
                "skills": ["Stakeholder Management", "Process Mapping", "SQL"],
                "years_experience": 5,
                "industries": ["finance"],
                "achievements": ["Improved reporting workflow"],
                "certifications": ["BCS Foundation"],
                "master_cv_ref": "docs/master_cv.md",
            }
        ),
        encoding="utf-8",
    )
    return profile_path


@contextmanager
def _running_ui_server(tmp_path: Path):
    profile_path = _write_profile(tmp_path)
    config = UIServerConfig(
        profile_path=profile_path,
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
        host="127.0.0.1",
        port=0,
    )
    server = ThreadingHTTPServer((config.host, config.port), _build_handler(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", config
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _http_get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _reed_job(job_id, title, description=None):
    return {
        "jobId": job_id,
        "jobTitle": title,
        "employerName": "Acme",
        "locationName": "London",
        "minimumSalary": 50000,
        "maximumSalary": 60000,
        "contractType": "Permanent",
        "jobUrl": f"https://reed.example/jobs/{job_id}",
        "jobDescription": description or f"<p>Role description for job {job_id}, nothing special.</p>",
        "fullTime": True,
    }


def test_search_buckets_store_manager_into_other_results(tmp_path: Path, monkeypatch) -> None:
    def fake_fetch_reed_jobs(keyword, location, max_results, *, skip=0, save_raw=True):
        return [
            _reed_job(1, "Business Analyst"),
            _reed_job(2, "BA"),
            _reed_job(3, "Senior BA"),
            _reed_job(4, "Store Manager"),
        ]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)
    query = urllib.parse.urlencode({"keywords": "Business Analysis", "locationName": "London"})
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed?{query}")

    assert status == 200
    assert "Other results (1)" in body
    # Main results section (before the "Other results" <details>) must show
    # the three BA-variant titles.
    other_marker = body.index("Other results (1)")
    main_html = body[:other_marker]
    other_html = body[other_marker:]
    assert "Business Analyst" in main_html
    assert ">BA<" in main_html or "BA" in main_html
    assert "Senior BA" in main_html
    assert "Store Manager" not in main_html
    assert "Store Manager" in other_html


def test_blank_query_shows_no_other_results_bucket(tmp_path: Path, monkeypatch) -> None:
    def fake_fetch_reed_jobs(keyword, location, max_results, *, skip=0, save_raw=True):
        return [_reed_job(1, "Store Manager")]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)
    query = urllib.parse.urlencode({"keywords": "", "locationName": "London"})
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed?{query}")

    assert status == 200
    assert "Other results" not in body
    assert "Store Manager" in body


def test_more_page_keeps_nonmatching_titles_in_other_results(tmp_path: Path, monkeypatch) -> None:
    def fake_fetch_reed_jobs(keyword, location, max_results, *, skip=0, save_raw=True):
        if skip == 0:
            return [_reed_job(index, "Business Analyst") for index in range(1, 11)]
        return [_reed_job(11, "Business Analyst"), _reed_job(12, "Store Manager")]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)
    query = urllib.parse.urlencode({"keywords": "Business Analysis", "locationName": "London"})
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed?{query}")
        assert status == 200
        next_url = html.unescape(re.search(r'data-next-url="([^"]+)"', body).group(1))
        status, more_body = _http_get(f"{base_url}{next_url}")

    assert status == 200
    payload = json.loads(more_body)
    assert "Business Analyst" in payload["cards_html"]
    assert "Store Manager" not in payload["cards_html"]
    assert "Store Manager" in payload["other_results_html"]
    assert 'id="jst-other-results"' in payload["other_results_html"]


def test_more_looks_ahead_when_entire_requested_page_is_hidden(tmp_path: Path, monkeypatch) -> None:
    calls: list[int] = []

    def fake_fetch_reed_jobs(keyword, location, max_results, *, skip=0, save_raw=True):
        calls.append(skip)
        jobs = [_reed_job(skip + index + 1, "Business Analyst") for index in range(10)]
        for index, job in enumerate(jobs):
            job["employerName"] = f"Acme {skip + index + 1}"
        return jobs

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)
    query = urllib.parse.urlencode({"keywords": "Business Analysis", "locationName": "London"})
    with _running_ui_server(tmp_path) as (base_url, config):
        status, body = _http_get(f"{base_url}/search/reed?{query}")
        assert status == 200
        hide_jobs(
            [
                {"source": "reed", "source_job_id": str(job_id), "title": "Business Analyst", "company": "Acme"}
                for job_id in range(11, 21)
            ],
            state_root=config.state_root,
        )
        next_url = html.unescape(re.search(r'data-next-url="([^"]+)"', body).group(1))
        status, more_body = _http_get(f"{base_url}{next_url}")

    payload = json.loads(more_body)
    assert status == 200
    assert calls == [0, 10, 20]
    assert "Business Analyst" in payload["cards_html"]
    assert payload["hidden_count"] == 10
    assert "resultsSkip=30" in payload["next_url"]


def test_more_stops_hidden_page_lookahead_at_fixed_cap(tmp_path: Path, monkeypatch) -> None:
    calls: list[int] = []

    def fake_fetch_reed_jobs(keyword, location, max_results, *, skip=0, save_raw=True):
        calls.append(skip)
        jobs = [_reed_job(skip + index + 1, "Business Analyst") for index in range(10)]
        for index, job in enumerate(jobs):
            job["employerName"] = f"Acme {skip + index + 1}"
        return jobs

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)
    query = urllib.parse.urlencode({"keywords": "Business Analysis", "locationName": "London"})
    with _running_ui_server(tmp_path) as (base_url, config):
        status, body = _http_get(f"{base_url}/search/reed?{query}")
        assert status == 200
        hide_jobs(
            [
                {"source": "reed", "source_job_id": str(job_id), "title": "Business Analyst", "company": "Acme"}
                for job_id in range(11, 51)
            ],
            state_root=config.state_root,
        )
        next_url = html.unescape(re.search(r'data-next-url="([^"]+)"', body).group(1))
        status, more_body = _http_get(f"{base_url}{next_url}")

    payload = json.loads(more_body)
    assert status == 200
    assert calls == [0, 10, 20, 30, 40]
    assert payload["visible_count"] == 0
    assert payload["hidden_count"] == 40
    assert payload["has_more"] is True
    assert "resultsSkip=50" in payload["next_url"]
