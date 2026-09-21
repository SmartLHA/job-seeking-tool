"""Slice D (2026-07-21 search/score/filter plan): multi-keyword search +
chip entry. ONE location + radius only (no multi-location cross-product).

Covers:
- 2 keywords + 1 location -> one merged, deduped list (one search per
  keyword, merged, then Slice B dedup reused).
- Keyword count is capped and the cap is surfaced in the page.
- Chip fields render a real name-carrying <input> so the no-JS fallback
  (comma-joined submission) works; _parse_keyword_terms parses it back.
"""
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
from src.ui_handlers import _MAX_KEYWORD_SEARCHES, _parse_keyword_terms
from src.ui_chip_field import render_chip_field


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


def test_parse_keyword_terms_splits_trims_dedupes_preserves_case():
    assert _parse_keyword_terms("Business Analyst, Data Analyst") == ["Business Analyst", "Data Analyst"]
    # Case-insensitive dedupe (avoids running the same effective search
    # twice): first occurrence's casing wins.
    assert _parse_keyword_terms(" ba , , BA ,ba") == ["ba"]
    assert _parse_keyword_terms("") == []
    assert _parse_keyword_terms("  ,  ,  ") == []


def test_two_keywords_one_location_merge_into_one_deduped_list(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_fetch_reed_jobs(keyword, location, max_results, *, skip=0, save_raw=True):
        calls.append(keyword)
        if keyword == "Business Analyst":
            return [{
                "jobId": 1, "jobTitle": "Business Analyst", "employerName": "Acme",
                "locationName": "London", "minimumSalary": 50000, "maximumSalary": 60000,
                "contractType": "Permanent", "jobUrl": "https://reed.example/jobs/1",
                "jobDescription": "<p>BA role one.</p>", "fullTime": True,
            }]
        if keyword == "Data Analyst":
            return [
                {
                    "jobId": 2, "jobTitle": "Data Analyst", "employerName": "Beta",
                    "locationName": "London", "minimumSalary": 50000, "maximumSalary": 60000,
                    "contractType": "Permanent", "jobUrl": "https://reed.example/jobs/2",
                    "jobDescription": "<p>DA role two.</p>", "fullTime": True,
                },
                # Same apply_url/title/company/location as job 1 -> should
                # dedup away even though it came from a different keyword's
                # sub-search.
                {
                    "jobId": 1, "jobTitle": "Business Analyst", "employerName": "Acme",
                    "locationName": "London", "minimumSalary": 50000, "maximumSalary": 60000,
                    "contractType": "Permanent", "jobUrl": "https://reed.example/jobs/1",
                    "jobDescription": "<p>BA role one, cross-listed.</p>", "fullTime": True,
                },
            ]
        return []

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)
    query = urllib.parse.urlencode({
        "keywords": "Business Analyst, Data Analyst",
        "locationName": "London",
    })
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed?{query}")

    assert status == 200
    # One search per keyword actually ran.
    assert calls == ["Business Analyst", "Data Analyst"]
    # Merged + deduped: exactly 2 distinct cards (job 1 shown once, job 2 once).
    import re
    assert len(re.findall(r'\sid="jrc-\d+"', body)) == 2
    assert "reed.example/jobs/1" in body
    assert "reed.example/jobs/2" in body


def test_keyword_count_is_capped_and_surfaced(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_fetch_reed_jobs(keyword, location, max_results, *, skip=0, save_raw=True):
        calls.append(keyword)
        return []

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)
    many_keywords = ", ".join(f"kw{i}" for i in range(_MAX_KEYWORD_SEARCHES + 4))
    query = urllib.parse.urlencode({"keywords": many_keywords, "locationName": "London"})
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed?{query}")

    assert status == 200
    assert len(calls) == _MAX_KEYWORD_SEARCHES
    assert f"Only the first {_MAX_KEYWORD_SEARCHES} keywords were searched" in body


def test_single_location_only_no_multi_location_cross_product(tmp_path: Path, monkeypatch) -> None:
    # There is no server-side multi-location parsing at all — a comma-joined
    # locationName is passed straight through as ONE literal location string
    # (chip UI enforces max 1 chip client-side); confirms no N x M explosion.
    calls = []

    def fake_fetch_reed_jobs(keyword, location, max_results, *, skip=0, save_raw=True):
        calls.append((keyword, location))
        return []

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)
    query = urllib.parse.urlencode({
        "keywords": "Business Analyst, Data Analyst",
        "locationName": "London, Manchester",  # even if a user bypasses the client-side chip cap
    })
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, _body = _http_get(f"{base_url}/search/reed?{query}")

    assert status == 200
    # 2 keywords x 1 (single, unsplit) location string = 2 calls, never 4.
    assert len(calls) == 2
    assert all(loc == "London, Manchester" for _kw, loc in calls)


def test_chip_field_renders_real_named_input_for_no_js_fallback():
    html = render_chip_field(
        name="keywords", label="Keywords", value="Business Analyst, Data Analyst",
        placeholder="x", max_chips=6,
    )
    assert 'name="keywords"' in html
    assert 'value="Business Analyst, Data Analyst"' in html
    # No JS: this is a fully functional plain input a user can type
    # comma-separated values into directly.
    assert "<input" in html and "</label>" in html


def test_search_page_renders_chip_fields_for_keywords_location_exclude(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/")

    assert status == 200
    assert 'class="chip-field"' in body
    assert 'name="keywords"' in body
    assert 'name="locationName"' in body
    assert 'name="excludeKeywords"' in body
    assert "CHIP_FIELD_JS" not in body  # sanity: the JS is embedded, not the constant name
    assert "chip-real-input" in body


def test_multi_keyword_more_advances_each_term_independently(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake_fetch_reed_jobs(keyword, location, max_results, *, skip=0, save_raw=True):
        calls.append((keyword, skip))
        if skip == 0:
            start = 1 if keyword == "Business Analyst" else 101
            return [{
                "jobId": start + index, "jobTitle": keyword, "employerName": "Acme",
                "locationName": "London", "minimumSalary": 50000, "maximumSalary": 60000,
                "contractType": "Permanent", "jobUrl": f"https://reed.example/{keyword}/{start + index}",
                "jobDescription": "<p>Analytics role.</p>", "fullTime": True,
            } for index in range(10)]
        if keyword == "Business Analyst":
            return []
        return [{
            "jobId": 200 + skip + index, "jobTitle": "Data Analyst", "employerName": "Beta",
            "locationName": "London", "minimumSalary": 50000, "maximumSalary": 60000,
            "contractType": "Permanent", "jobUrl": f"https://reed.example/data/{skip + index}",
            "jobDescription": "<p>Analytics role.</p>", "fullTime": True,
        } for index in range(10)]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)
    query = urllib.parse.urlencode({"keywords": "Business Analyst, Data Analyst", "locationName": "London"})
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed?{query}")
        assert status == 200
        first_next = html.unescape(re.search(r'data-next-url="([^"]+)"', body).group(1))
        status, first_more = _http_get(f"{base_url}{first_next}")
        assert status == 200
        second_next = json.loads(first_more)["next_url"]
        status, _second_more = _http_get(f"{base_url}{second_next}")

    assert status == 200
    assert calls == [
        ("Business Analyst", 0), ("Data Analyst", 0),
        ("Business Analyst", 10), ("Data Analyst", 10),
        ("Data Analyst", 20),
    ]
