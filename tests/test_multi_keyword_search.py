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
import pytest
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
    assert len(re.findall(r'<div class="jst-rc"', body)) == 2
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


from types import SimpleNamespace
from unittest.mock import Mock
from src.ui_handlers import _prepare_keyword_search, handle_source_search, handle_source_search_more
from src.job_sources.reed_source import normalize_reed_search_params
from src.job_sources.adzuna_source import normalize_adzuna_search_params
from src.job_sources.linkedin_source import normalize_search_params as normalize_linkedin


@pytest.mark.parametrize('source_id,normalizer', [
    ('reed', normalize_reed_search_params), ('adzuna', normalize_adzuna_search_params),
    ('linkedin', normalize_linkedin)])
@pytest.mark.parametrize('raw,expected', [
    (', BA  analyst , ba analyst, , Data analyst,', ['BA analyst', 'Data analyst']),
    ('A' * 121 + ', ' + 'B' * 121, ['A' * 120, 'B' * 120]),
    ('X' * 120 + 'a, ' + 'X' * 120 + 'b, unique', ['X' * 120, 'unique']),
    (', ,', []),
    (', '.join(['Q' * 120 + str(i) for i in range(6)] + ['outside cap']), ['Q' * 120]),
    (' '.join(['word'] * 40), [(' '.join(['word'] * 40))[:120].strip()]),
    (', '.join('term' + str(i) for i in range(8)), ['term' + str(i) for i in range(6)])])
def test_prepared_source_terms_round_trip(source_id, normalizer, raw, expected):
    source = SimpleNamespace(normalize_search_params=normalizer)
    values, terms = _prepare_keyword_search(source, {'keywords': raw})
    assert terms == expected
    assert values['keywords'] == ', '.join(expected)
    assert _prepare_keyword_search(source, values)[1] == expected
    if len(_parse_keyword_terms(raw)) > 6:
        assert values['_keyword_capped'] == '6'


@pytest.mark.parametrize('source_id,normalizer', [
    ('reed', normalize_reed_search_params), ('adzuna', normalize_adzuna_search_params),
    ('linkedin', normalize_linkedin)])
def test_actual_initial_more_keep_long_vector(tmp_path, monkeypatch, source_id, normalizer):
    calls = []
    take_key, skip_key = ('results_to_take', 'results_skip') if source_id == 'linkedin' else ('resultsToTake', 'resultsSkip')
    def search(values):
        calls.append((values['keywords'], int(values[skip_key])))
        return [{'source': source_id, 'source_job_id': values['keywords'] + str(values[skip_key]),
                 'title': values['keywords'], 'company': 'Synthetic', 'location': 'Test'}]
    source = SimpleNamespace(source_id=source_id, display_name=source_id,
        normalize_search_params=normalizer, search_handler=search,
        render_cards_fragment=lambda *args, **kwargs: 'synthetic cards')
    monkeypatch.setattr('src.job_sources.source_registry.get_source', lambda _: source)
    monkeypatch.setattr('src.job_sources.relevance.bucket_jobs_by_relevance', lambda rows, _: (rows, []))
    monkeypatch.setattr('src.job_sources.dedup.deduplicate_jobs', lambda rows: rows)
    monkeypatch.setattr('src.job_hunt_not_interested.filter_results', lambda rows, **kw: (rows, 0))
    captured = []
    monkeypatch.setattr('src.ui_handlers.render_home', lambda *args, **kw: captured.append(kw['search_values']))
    terms = ['A' * 120, 'B' * 120, 'C' * 120]
    req = SimpleNamespace(query={'keywords': ', '.join(terms), take_key: '1'})
    config = UIServerConfig(profile_path=tmp_path/'profile.json', state_root=tmp_path/'state', report_dir=tmp_path/'reports')
    responder = Mock()
    handle_source_search(req, config, responder, source_id)
    assert captured[0]['keywords'] == ', '.join(terms)
    url = captured[0]['_more_url']
    for offset in (1, 2):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        assert query['keywords'] == ', '.join(terms)
        assert query['keywordCursors'] == ','.join([str(offset)] * 3)
        handle_source_search_more(SimpleNamespace(query=query), config, responder, source_id)
        body = responder.send_json.call_args.args[0]
        assert body['ok'] is True
        url = body['next_url']
    assert calls == [(term, offset) for offset in (0, 1, 2) for term in terms]
    query['keywordCursors'] = '3,5,7'
    handle_source_search_more(SimpleNamespace(query=query), config, responder, source_id)
    assert calls[-3:] == list(zip(terms, (3, 5, 7)))
    next_query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(responder.send_json.call_args.args[0]['next_url']).query))
    assert next_query['keywordCursors'] == '4,6,8'
    for cursor in ('-1,1,1', '1,1'):
        query['keywordCursors'] = cursor
        before = len(calls)
        handle_source_search_more(SimpleNamespace(query=query), config, responder, source_id)
        assert responder.send_json.call_args.kwargs['status'] == 400
        assert len(calls) == before
    query.pop('keywordCursors')
    query[skip_key] = '-1'
    handle_source_search_more(SimpleNamespace(query=query), config, responder, source_id)
    assert responder.send_json.call_args.kwargs['status'] == 400


@pytest.mark.parametrize('source_id,normalizer', [
    ('reed', normalize_reed_search_params), ('adzuna', normalize_adzuna_search_params),
    ('linkedin', normalize_linkedin)])
@pytest.mark.parametrize('initial_count,later_count', [(0, 0), (1, 0), (2, 0), (2, 1)])
def test_failed_initial_term_remains_retryable_with_short_or_full_success(tmp_path, monkeypatch, source_id, normalizer, initial_count, later_count):
    calls, phase, captured = [], [0], []
    terms = ['F' * 120, 'G' * 120]
    take_key, skip_key = ('results_to_take', 'results_skip') if source_id == 'linkedin' else ('resultsToTake', 'resultsSkip')
    def search(values):
        term, offset = values['keywords'], int(values[skip_key]); calls.append((phase[0], term, offset))
        if term == terms[0] and phase[0] < 3:
            raise ValueError('Synthetic retryable failure')
        count = initial_count if phase[0] == 0 else (later_count if phase[0] == 1 else 1)
        return [{'source': source_id, 'source_job_id': f'{phase[0]}-{term}-{i}',
                 'title': term, 'company': 'Synthetic'} for i in range(count)]
    source = SimpleNamespace(source_id=source_id, display_name=source_id,
        normalize_search_params=normalizer, search_handler=search,
        render_cards_fragment=lambda *args, **kwargs: 'synthetic cards')
    monkeypatch.setattr('src.job_sources.source_registry.get_source', lambda _: source)
    monkeypatch.setattr('src.job_sources.relevance.bucket_jobs_by_relevance', lambda rows, _: (rows, []))
    monkeypatch.setattr('src.job_sources.dedup.deduplicate_jobs', lambda rows: rows)
    monkeypatch.setattr('src.job_hunt_not_interested.filter_results', lambda rows, **kw: (rows, 0))
    monkeypatch.setattr('src.ui_handlers.render_home', lambda *args, **kw: captured.append(kw['search_values']))
    config = UIServerConfig(profile_path=tmp_path/'profile.json', state_root=tmp_path/'state', report_dir=tmp_path/'reports')
    responder = Mock()
    handle_source_search(SimpleNamespace(query={'keywords': terms[0]+'x, '+terms[1]+'x', take_key: '2'}), config, responder, source_id)
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(captured[0]['_more_url']).query))
    assert query['keywords'] == ', '.join(terms)
    assert query['keywordCursors'] == ('0,2' if initial_count == 2 else '0,x')
    phase[0] = 1
    handle_source_search_more(SimpleNamespace(query=query), config, responder, source_id)
    body = responder.send_json.call_args.args[0]
    if initial_count == 2:
        assert body['ok'] and body['has_more']  # Failed term survives even though the other page is short.
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(body['next_url']).query))
        assert query['keywordCursors'] == '0,x'
    else:
        assert body['ok'] is False
    retry_query = dict(query)
    phase[0] = 2; before = len(calls)
    handle_source_search_more(SimpleNamespace(query=query), config, responder, source_id)
    assert responder.send_json.call_args.args[0]['ok'] is False
    assert query == retry_query and calls[before:] == [(2, terms[0], 0)]
    phase[0] = 3; before = len(calls)
    handle_source_search_more(SimpleNamespace(query=query), config, responder, source_id)
    body = responder.send_json.call_args.args[0]
    assert body['ok'] and body['has_more'] is False
    assert calls[before:] == [(3, terms[0], 0)]
    assert dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(body['next_url']).query))['keywordCursors'] == 'x,x'


def test_later_keyword_failure_preserves_nonzero_requested_offset():
    from src.ui_handlers import _run_multi_keyword_search
    calls = []
    def search(values):
        calls.append((values['keywords'], values['resultsSkip']))
        if values['keywords'] == 'Fail':
            raise ValueError('Synthetic later failure')
        return []
    _, full, errors, offsets = _run_multi_keyword_search(SimpleNamespace(search_handler=search),
        {'resultsToTake': '2', 'resultsSkip': '0'}, ['Fail', 'Done'], offsets=[5, 7])
    assert calls == [('Fail', '5'), ('Done', '7')] and offsets == [5, None]
    assert errors and full is False


@pytest.mark.parametrize('empty_success', [False, True])
def test_http_initial_partial_failure_with_short_success_exposes_retry(tmp_path, monkeypatch, empty_success):
    calls = []
    def fetch(keyword, location, max_results, *, skip=0, save_raw=True):
        calls.append((keyword, skip))
        if keyword == 'Business Analyst' and len(calls) == 1:
            raise ValueError('Synthetic first failure')
        if empty_success and keyword == 'Data Analyst':
            return []
        return [{'jobId': 100+len(calls), 'jobTitle': keyword, 'employerName': 'Synthetic',
                 'locationName': 'London', 'jobUrl': f'https://example.test/{len(calls)}',
                 'jobDescription': '<p>Synthetic role.</p>'}]
    monkeypatch.setattr('src.job_sources.reed_source.fetch_reed_jobs', fetch)
    query = urllib.parse.urlencode({'keywords': 'Business Analyst, Data Analyst', 'resultsToTake': '2'})
    with _running_ui_server(tmp_path) as (base, _):
        status, page = _http_get(base+'/search/reed?'+query)
        assert status == 200
        assert 'id="jst-cards-container"' in page and 'window.jstLoadMore=function(btn)' in page
        url = html.unescape(re.search(r'data-next-url="([^"]+)"', page).group(1))
        assert dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))['keywordCursors'] == '0,x'
        status, response = _http_get(base+url)
    assert status == 200 and json.loads(response)['ok'] is True
    assert calls == [('Business Analyst', 0), ('Data Analyst', 0), ('Business Analyst', 0)]


@pytest.mark.parametrize('source_id', ['reed', 'adzuna', 'linkedin'])
def test_empty_retry_page_renders_shared_paging_target(source_id, monkeypatch):
    from src.ui_handlers import _render_search_jobs_tab
    monkeypatch.setattr('src.ui_handlers.get_enabled_sources', lambda: ['reed', 'adzuna', 'linkedin'])
    page = _render_search_jobs_tab(search_values={'_source_id': source_id, '_more_url': '/synthetic-retry'}, reed_results=[])
    assert 'id="jst-cards-container"' in page and 'data-next-url="/synthetic-retry"' in page
    assert 'window.jstLoadMore=function(btn)' in page
