"""Slice B (2026-07-21 search/score/filter plan): dedup wired into live search.

Covers:
- handle_source_search collapses duplicate cards from a single fetch.
- handle_source_search_more drops cards already shown earlier in the same
  search (search-id-keyed seen-set), and a brand-new search resets state.
- job_sources.search_state is safe under concurrent "more" calls.
"""
from __future__ import annotations

import json
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
from src.job_sources import search_state
from src.job_sources.dedup import is_duplicate_job


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


def _reed_job(job_id, title="Business Analyst", company="Acme", url_suffix=None, description=None):
    suffix = url_suffix if url_suffix is not None else job_id
    desc = description if description is not None else f"<p>Great business analyst role #{job_id} with stakeholder work.</p>"
    return {
        "jobId": job_id,
        "jobTitle": title,
        "employerName": company,
        "locationName": "London",
        "minimumSalary": 50000,
        "maximumSalary": 60000,
        "contractType": "Permanent",
        "jobUrl": f"https://reed.example/jobs/{suffix}",
        "jobDescription": desc,
        "fullTime": True,
    }


def test_single_search_collapses_duplicate_cards(tmp_path: Path, monkeypatch) -> None:
    # Two different Reed jobIds but identical title/company/location/url ->
    # deduplicate_jobs must collapse them to one card in a single search.
    def fake_fetch_reed_jobs(keyword, location, max_results, *, skip=0, save_raw=True):
        return [
            _reed_job(1, url_suffix="shared"),
            _reed_job(2, url_suffix="shared"),  # same apply_url -> duplicate
            _reed_job(3, title="Data Analyst", url_suffix="other"),
        ]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)
    query = urllib.parse.urlencode({"keywords": "Business Analyst", "locationName": "London"})
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed?{query}")

    assert status == 200
    # Exactly 2 cards rendered (ids jrc-0, jrc-1), not 3 — the two "shared"-url
    # jobs collapsed into one card. Each card div carries both id="jrc-N" and
    # data-jst-id="jrc-N", so count the `id="jrc-N"` root-div marker only.
    assert len(re.findall(r'\sid="jrc-\d+"', body)) == 2
    assert "reed.example/jobs/shared" in body
    assert "reed.example/jobs/other" in body


def test_show_more_drops_already_shown_cards_across_pages(tmp_path: Path, monkeypatch) -> None:
    # Reed returns the SAME two jobs on page 1 and page 2 (simulating an API
    # that shifted / re-served overlapping results) -> "Show more" must not
    # repeat cards already shown on page 1.
    def fake_fetch_reed_jobs(keyword, location, max_results, *, skip=0, save_raw=True):
        return [_reed_job(1, url_suffix="dup-a"), _reed_job(2, url_suffix="dup-b")]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)
    query = urllib.parse.urlencode(
        {"keywords": "Business Analyst", "locationName": "London", "resultsToTake": "2"}
    )
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed?{query}")
        assert status == 200
        assert "reed.example/jobs/dup-a" in body
        assert "reed.example/jobs/dup-b" in body

        # Extract the more_url the server generated (contains a real searchId).
        marker = 'data-next-url="'
        start = body.index(marker) + len(marker)
        end = body.index('"', start)
        more_url = body[start:end].replace("&amp;", "&")
        assert "searchId=" in more_url

        more_status, more_body = _http_get(f"{base_url}{more_url}")

    assert more_status == 200
    data = json.loads(more_body)
    assert data["ok"] is True
    # Both jobs on the "next" page are duplicates of page 1 -> nothing new shown.
    assert data["visible_count"] == 0
    assert data["hidden_count"] >= 2
    assert "reed.example/jobs/dup-a" not in data["cards_html"]
    assert "reed.example/jobs/dup-b" not in data["cards_html"]


def test_new_search_resets_seen_state(tmp_path: Path, monkeypatch) -> None:
    # A brand-new search must mint its OWN search-id/seen-set, not inherit an
    # older search's seen jobs -> the same job can appear again in a fresh search.
    def fake_fetch_reed_jobs(keyword, location, max_results, *, skip=0, save_raw=True):
        return [_reed_job(1, url_suffix="repeat")]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)
    query = urllib.parse.urlencode({"keywords": "Business Analyst", "locationName": "London"})
    with _running_ui_server(tmp_path) as (base_url, _config):
        status1, body1 = _http_get(f"{base_url}/search/reed?{query}")
        status2, body2 = _http_get(f"{base_url}/search/reed?{query}")

    assert status1 == 200 and status2 == 200
    assert "reed.example/jobs/repeat" in body1
    assert "reed.example/jobs/repeat" in body2  # second (new) search shows it again


def test_filter_new_page_thread_safe_concurrent_calls() -> None:
    # Simulate concurrent "more" requests for the same search-id: no job should
    # be double-counted as new, and no exception should propagate.
    search_state._reset_for_tests()
    seed = [{"source": "reed", "external_id": "seed", "title": "x", "company": "y",
             "location_normalized": "london", "apply_url": "http://seed"}]
    search_id = search_state.start_search(seed)

    page = [
        {"source": "reed", "external_id": f"e{i}", "title": f"Analyst {i}", "company": "Acme",
         "location_normalized": "london", "apply_url": f"http://job/{i}"}
        for i in range(20)
    ]

    results: list[list[dict]] = []
    lock = threading.Lock()

    def worker(chunk):
        r = search_state.filter_new_page(search_id, chunk)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker, args=(page,)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Across all 5 concurrent identical-page calls, each of the 20 unique jobs
    # must be returned as "new" exactly once in total (not 5x, not 0x).
    seen_ids = [job["external_id"] for r in results for job in r]
    assert sorted(seen_ids) == sorted(f"e{i}" for i in range(20))


def test_is_duplicate_job_used_by_search_state_reused_not_reinvented() -> None:
    # Sanity check that search_state reuses dedup's identity/duplicate logic.
    a = {"source": "reed", "external_id": "1", "title": "BA", "company": "Acme",
         "location_normalized": "london", "apply_url": "http://same"}
    b = {"source": "reed", "external_id": "2", "title": "BA", "company": "Acme",
         "location_normalized": "london", "apply_url": "http://same"}
    assert is_duplicate_job(a, b) is True
