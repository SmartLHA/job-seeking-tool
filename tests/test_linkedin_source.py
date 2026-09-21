"""Tests for src/job_sources/linkedin_source.py.

Uses unittest.mock to patch HTTP calls (no real network).
All tests are isolated: a fresh temp SQLite DB is used per test where caching
is relevant, and the module-level _cache_db_path is restored after each test.
"""
from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

# Import the module under test.  The import triggers _register(), which is fine.
import src.job_sources.linkedin_source as li


# ── helpers ───────────────────────────────────────────────────────────────────

def _html_with_cards(cards: list[dict]) -> str:
    """Build a minimal LinkedIn search-result HTML with the given card data."""
    card_html = ""
    for card in cards:
        card_html += (
            f'<div class="base-card">'
            f'<a href="{card.get("url", "https://www.linkedin.com/jobs/view/12345/")}"></a>'
            f'<h3 class="base-search-card__title">{card.get("title", "Test Job")}</h3>'
            f'<h4 class="base-search-card__subtitle">{card.get("company", "Test Co")}</h4>'
            f'<span class="job-search-card__location">{card.get("location", "London")}</span>'
            f"</div>"
        )
    # Pad to >5000 chars so the length check passes
    padding = "x" * 6000
    return f"<html><body>{padding}{card_html}</body></html>"


def _blocked_login_html() -> str:
    """HTML that looks like LinkedIn's login redirect page."""
    return "x" * 3000  # Short page — triggers length < 5000 check


def _mock_response(
    *,
    status_code: int = 200,
    text: str = "",
    url: str = "https://www.linkedin.com/jobs/search/",
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.url = url
    return resp


@pytest.fixture(autouse=True)
def isolate_cache_db(tmp_path: Path) -> Generator[None, None, None]:
    """Use a fresh temp DB for every test; restore the original path after."""
    original = li._cache_db_path
    li.set_cache_db_path(tmp_path / "test_li_cache.db")
    yield
    li.set_cache_db_path(original)
    # Also clear any in-memory state carried over
    li._cache_db_path = original


# ── test 1: normal search → cards parsed correctly ────────────────────────────

def test_normal_search_parses_cards(tmp_path: Path) -> None:
    """25 well-formed cards should come back as 25 result dicts."""
    cards = [
        {
            "title": f"Job {i}",
            "company": f"Company {i}",
            "location": "London",
            "url": f"https://www.linkedin.com/jobs/view/{10000 + i}/",
        }
        for i in range(25)
    ]
    html = _html_with_cards(cards)

    with patch("requests.get", return_value=_mock_response(text=html)) as mock_get:
        results = li.search_handler({"keywords": "BA", "location": "London", "work_mode": "", "results_to_take": 25})

    assert mock_get.called
    assert len(results) == 25
    assert results[0]["source"] == "linkedin"
    assert results[0]["title"] == "Job 0"
    assert results[0]["company"] == "Company 0"
    assert results[0]["location"] == "London"
    assert results[0]["source_job_id"] == "10000"
    assert results[0]["salary_display"] == ""
    assert results[0]["salary_min_gbp"] is None
    assert results[0]["salary_max_gbp"] is None
    assert results[0]["employment_type"] == ""
    assert results[0]["description_raw"] == ""
    assert results[0]["filter_notes"] == "LinkedIn does not provide salary. Results may vary."


# ── test 2: login wall page → LinkedInBlockedError ────────────────────────────

def test_login_wall_raises_blocked_error() -> None:
    """A login-redirect final URL should raise LinkedInBlockedError."""
    with patch(
        "requests.get",
        return_value=_mock_response(
            # Long-enough HTML so length check passes; the URL is the decisive signal.
            text="x" * 6000,
            url="https://www.linkedin.com/login?session_redirect=jobs%2Fsearch",
        ),
    ):
        with pytest.raises(li.LinkedInBlockedError, match="blocking"):
            li.search_handler({"keywords": "BA", "location": "UK", "work_mode": "", "results_to_take": 25})


def test_short_page_raises_blocked_error() -> None:
    """An unusually short page (< 5000 chars) should be treated as blocked."""
    with patch(
        "requests.get",
        return_value=_mock_response(text="x" * 100),
    ):
        with pytest.raises(li.LinkedInBlockedError, match="blocking"):
            li.search_handler({"keywords": "BA", "location": "UK", "work_mode": "", "results_to_take": 25})


def test_authwall_raises_blocked_error() -> None:
    """linkedin.com/authwall redirect must be treated as blocked (HIGH #4)."""
    with patch(
        "requests.get",
        return_value=_mock_response(
            text="x" * 6000,
            url="https://www.linkedin.com/authwall?trk=something",
        ),
    ):
        with pytest.raises(li.LinkedInBlockedError, match="blocking"):
            li.search_handler({"keywords": "BA", "location": "UK", "work_mode": "", "results_to_take": 25})


# ── test 3: empty results page → returns [] ───────────────────────────────────

def test_empty_results_returns_empty_list() -> None:
    """A valid page with no .base-card elements returns an empty list."""
    # Page is long enough and URL is clean, but has no cards
    empty_html = "<html><body>" + "x" * 6000 + "</body></html>"
    with patch("requests.get", return_value=_mock_response(text=empty_html)):
        results = li.search_handler({"keywords": "XYZ", "location": "UK", "work_mode": "", "results_to_take": 25})
    assert results == []


# ── test 4: HTTP 429 → LinkedInBlockedError ───────────────────────────────────

def test_http_429_raises_blocked_error() -> None:
    with patch("requests.get", return_value=_mock_response(status_code=429, text="x" * 6000)):
        with pytest.raises(li.LinkedInBlockedError):
            li.search_handler({"keywords": "BA", "location": "UK", "work_mode": "", "results_to_take": 25})


# ── test 5: HTTP 403 → LinkedInBlockedError ───────────────────────────────────

def test_http_403_raises_blocked_error() -> None:
    with patch("requests.get", return_value=_mock_response(status_code=403, text="x" * 6000)):
        with pytest.raises(li.LinkedInBlockedError):
            li.search_handler({"keywords": "BA", "location": "UK", "work_mode": "", "results_to_take": 25})


# ── test 6: timeout → TimeoutError ───────────────────────────────────────────

def test_timeout_raises_timeout_error() -> None:
    import requests as req_lib

    with patch("requests.get", side_effect=req_lib.exceptions.Timeout("read timed out")):
        with pytest.raises(TimeoutError, match="timed out"):
            li.search_handler({"keywords": "BA", "location": "UK", "work_mode": "", "results_to_take": 25})


# ── test 7: malicious HTML in title → escaped in render_results ───────────────

def test_xss_title_escaped_in_render() -> None:
    """<script> in a title must be HTML-escaped in the output, never executed."""
    malicious = "<script>alert(1)</script>"
    result = {
        "source": "linkedin",
        "source_job_id": "99999",
        "title": malicious,
        "company": "Evil Co",
        "location": "London",
        "salary_display": "",
        "salary_min_gbp": None,
        "salary_max_gbp": None,
        "employment_type": "",
        "work_mode": "",
        "url": "https://www.linkedin.com/jobs/view/99999/",
        "description_preview": "",
        "description_raw": "",
        "filter_notes": "LinkedIn does not provide salary. Results may vary.",
    }
    html = li.render_results([result], error=None, nonce="abc123")
    # The malicious title must be escaped, not injected. (The page legitimately
    # contains a static multi-select <script> block, so assert on the payload
    # itself — matching the convention in test_ui / test_digest_e2e.)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_javascript_url_not_rendered_as_link() -> None:
    """A javascript: URL must not produce a clickable <a> href — XSS prevention."""
    result = {
        "source": "linkedin",
        "source_job_id": "88888",
        "title": "Bad Job",
        "company": "Evil Co",
        "location": "London",
        "salary_display": "",
        "salary_min_gbp": None,
        "salary_max_gbp": None,
        "employment_type": "",
        "work_mode": "",
        "url": "javascript:alert(1)",
        "description_preview": "",
        "description_raw": "",
        "filter_notes": "",
    }
    html = li.render_results([result], error=None, nonce="abc123")
    # The dangerous value may appear in the hidden <input> (data, not executable).
    # The critical check: it must NOT appear as an <a href> — that's the XSS vector.
    assert 'href="javascript:' not in html
    assert "href='javascript:" not in html
    # The card itself should still render; it just has no "View" link
    assert "Bad Job" in html


# ── test 8: duplicate job IDs → deduped ──────────────────────────────────────

def test_duplicate_job_ids_are_deduped() -> None:
    """If the same job URL appears twice, only one result should be returned."""
    same_url = "https://www.linkedin.com/jobs/view/77777/"
    cards = [
        {"title": "BA", "company": "Co", "location": "London", "url": same_url},
        {"title": "BA copy", "company": "Co", "location": "London", "url": same_url},
    ]
    html = _html_with_cards(cards)
    with patch("requests.get", return_value=_mock_response(text=html)):
        results = li.search_handler({"keywords": "BA", "location": "UK", "work_mode": "", "results_to_take": 25})
    ids = [r["source_job_id"] for r in results]
    assert len(ids) == len(set(ids)), "Duplicate job IDs should have been removed"


# ── test 9: normalize_search_params({}) → valid defaults ─────────────────────

def test_normalize_search_params_defaults() -> None:
    params = li.normalize_search_params({})
    assert params["keywords"] == ""
    assert params["location"] == "United Kingdom"
    assert params["work_mode"] == ""
    assert params["results_to_take"] == 25


def test_normalize_search_params_clamps_results() -> None:
    params = li.normalize_search_params({"results_to_take": "999"})
    assert params["results_to_take"] == 50  # clamped to max


def test_normalize_search_params_invalid_work_mode() -> None:
    params = li.normalize_search_params({"work_mode": "bad"})
    assert params["work_mode"] == ""


# ── test 10: SQLite cache hit → no HTTP request made ─────────────────────────

def test_cache_hit_skips_http(tmp_path: Path) -> None:
    """When cached results exist within TTL, no HTTP request should be made."""
    li.set_cache_db_path(tmp_path / "cache_hit_test.db")

    # Pre-populate the cache
    key = li._cache_key("analyst", "London", "2")
    fake_results = [
        {
            "source": "linkedin",
            "source_job_id": "55555",
            "title": "Cached Job",
            "company": "Cache Co",
            "location": "London",
            "salary_display": "",
            "salary_min_gbp": None,
            "salary_max_gbp": None,
            "employment_type": "",
            "work_mode": "remote",
            "url": "https://www.linkedin.com/jobs/view/55555/",
            "description_preview": "Cached",
            "description_raw": "",
            "filter_notes": "LinkedIn does not provide salary. Results may vary.",
        }
    ]
    li._cache_set(key, fake_results)

    with patch("requests.get") as mock_get:
        results = li.search_handler({
            "keywords": "analyst",
            "location": "London",
            "work_mode": "2",
            "results_to_take": 25,
        })

    mock_get.assert_not_called()
    assert len(results) == 1
    assert results[0]["title"] == "Cached Job"


# ── cache TTL expiry ──────────────────────────────────────────────────────────

def test_cache_ttl_expired_triggers_new_http_request(tmp_path: Path) -> None:
    """A cache entry older than _CACHE_TTL must be ignored; a fresh HTTP call is made."""
    li.set_cache_db_path(tmp_path / "ttl_test.db")

    key = li._cache_key("analyst", "London", "")
    fake = [{"source": "linkedin", "source_job_id": "1", "title": "Old Job",
             "company": "C", "location": "L", "salary_display": "",
             "salary_min_gbp": None, "salary_max_gbp": None,
             "employment_type": "", "work_mode": "", "url": "",
             "description_preview": "", "description_raw": "",
             "filter_notes": ""}]
    li._cache_set(key, fake)

    fresh_html = _html_with_cards([{
        "title": "Fresh Job", "company": "New Co",
        "location": "London", "url": "https://www.linkedin.com/jobs/view/99999/",
    }])

    # Wind time forward past TTL
    future = time.time() + li._CACHE_TTL + 10
    with patch("src.job_sources.linkedin_source.time") as mock_time:
        mock_time.time.return_value = future
        with patch("requests.get", return_value=_mock_response(text=fresh_html)) as mock_get:
            results = li.search_handler({
                "keywords": "analyst", "location": "London",
                "work_mode": "", "results_to_take": 25,
            })

    mock_get.assert_called_once()
    assert results[0]["title"] == "Fresh Job"


# ── render_results error escaping ─────────────────────────────────────────────

def test_render_results_error_content_is_escaped() -> None:
    """HTML special chars in the error message must be escaped, not rendered raw."""
    html = li.render_results(None, "<b>rate & limited</b>", None)
    assert "<b>" not in html
    assert "&lt;b&gt;" in html
    assert "&amp;" in html


# ── normalize_search_params None safety ───────────────────────────────────────

def test_normalize_search_params_keywords_none_does_not_crash() -> None:
    """Explicitly passing keywords=None must not raise AttributeError."""
    params = li.normalize_search_params({"keywords": None})
    assert params["keywords"] == ""


def test_normalize_search_params_location_none_uses_default() -> None:
    """Explicitly passing location=None must fall back to 'United Kingdom'."""
    params = li.normalize_search_params({"location": None})
    assert params["location"] == "United Kingdom"


# ── bonus: render_results edge cases ─────────────────────────────────────────

def test_render_results_none_returns_empty() -> None:
    assert li.render_results(None, None, None) == ""


def test_render_results_error_shows_message() -> None:
    html = li.render_results(None, "rate limited", None)
    assert "unavailable" in html.lower()
    assert "rate limited" in html


def test_render_results_empty_list_shows_no_results() -> None:
    html = li.render_results([], None, None)
    assert "No LinkedIn results" in html


# ── select_handler ────────────────────────────────────────────────────────────

def _valid_select_form(**overrides: str) -> dict:
    """Minimal valid POST form for select_handler."""
    base: dict = {
        "source": "linkedin",
        "source_job_id": "12345",
        "title": "Business Analyst",
        "company": "Acme Ltd",
        "location": "London",
        "work_mode": "remote",
        "employment_type": "permanent",
        "url": "https://www.linkedin.com/jobs/view/12345/",
        "description_raw": "We need a BA with SQL skills.",
        "salary_min_gbp": "",
        "salary_max_gbp": "",
    }
    base.update(overrides)
    return base


@pytest.fixture()
def _patch_skills():
    """Suppress real NLP in skill extraction for select_handler tests."""
    with patch(
        "src.job_sources.linkedin_source.extract_skills_from_text",
        return_value=(["SQL"], ["Python"], None),
    ):
        yield


# ── 1. Happy path ─────────────────────────────────────────────────────────────

def test_select_handler_happy_path(_patch_skills) -> None:
    """Valid form → returns dict with all default_form_values keys populated."""
    values = li.select_handler(_valid_select_form(), config=None)

    # Structural: all default_form_values keys must be present
    from src.ui_utils import default_form_values
    for key in default_form_values():
        assert key in values, f"Missing key: {key}"

    # Spot-check mapped fields
    assert values["job_title"] == "Business Analyst"
    assert values["company"] == "Acme Ltd"
    assert values["location"] == "London"
    assert values["work_mode"] == "remote"
    assert values["employment_type"] == "permanent"
    assert values["input_method"] == "linkedin_search"
    assert values["source_type"] == "linkedin"
    assert values["source_ref"] == "https://www.linkedin.com/jobs/view/12345/"
    assert values["source_job_id"] == "12345"
    assert values["job_id"].startswith("linkedin-")
    assert values["required_skills"] == "SQL"
    assert values["preferred_skills"] == "Python"


# ── 2. Wrong source → ValueError ─────────────────────────────────────────────

def test_select_handler_wrong_source_raises(_patch_skills) -> None:
    with pytest.raises(ValueError, match="only processes LinkedIn"):
        li.select_handler(_valid_select_form(source="reed"), config=None)


# ── 3. Field too long → ValueError ───────────────────────────────────────────

def test_select_handler_title_too_long_raises(_patch_skills) -> None:
    """title limit is 180 chars."""
    with pytest.raises(ValueError, match="title"):
        li.select_handler(_valid_select_form(title="x" * 181), config=None)


def test_select_handler_url_too_long_raises(_patch_skills) -> None:
    """url limit is 500 chars."""
    long_url = "https://www.linkedin.com/jobs/view/" + "1" * 470
    with pytest.raises(ValueError, match="url"):
        li.select_handler(_valid_select_form(url=long_url), config=None)


# ── 4. work_mode / employment_type normalisation ─────────────────────────────

def test_select_handler_invalid_work_mode_normalized(_patch_skills) -> None:
    values = li.select_handler(_valid_select_form(work_mode="gibberish"), config=None)
    assert values["work_mode"] == ""


def test_select_handler_unknown_work_mode_cleared(_patch_skills) -> None:
    """'unknown' is in _ALLOWED_WORK_MODES but must be cleared to '' in output."""
    values = li.select_handler(_valid_select_form(work_mode="unknown"), config=None)
    assert values["work_mode"] == ""


def test_select_handler_valid_work_mode_preserved(_patch_skills) -> None:
    values = li.select_handler(_valid_select_form(work_mode="hybrid"), config=None)
    assert values["work_mode"] == "hybrid"


def test_select_handler_invalid_employment_type_normalized(_patch_skills) -> None:
    values = li.select_handler(_valid_select_form(employment_type="wizard"), config=None)
    assert values["employment_type"] == ""


# ── 5. Lazy description fetch — triggered ────────────────────────────────────

def test_select_handler_lazy_fetch_triggered_when_description_blank(_patch_skills) -> None:
    """Blank description + numeric job_id → _fetch_description is called."""
    with patch(
        "src.job_sources.linkedin_source._fetch_description",
        return_value="Fetched description text.",
    ) as mock_fetch:
        values = li.select_handler(
            _valid_select_form(description_raw="", source_job_id="99999"),
            config=None,
        )

    mock_fetch.assert_called_once_with("99999")
    assert values["description_raw"] == "Fetched description text."
    assert values["copied_text"] == "Fetched description text."


# ── 6. Lazy fetch skipped — description already present ──────────────────────

def test_select_handler_lazy_fetch_skipped_if_description_present(_patch_skills) -> None:
    with patch(
        "src.job_sources.linkedin_source._fetch_description"
    ) as mock_fetch:
        li.select_handler(
            _valid_select_form(description_raw="Already here."),
            config=None,
        )

    mock_fetch.assert_not_called()


# ── 7. Lazy fetch skipped — non-numeric job_id (UUID fallback) ───────────────

def test_select_handler_lazy_fetch_skipped_for_non_numeric_job_id(_patch_skills) -> None:
    with patch(
        "src.job_sources.linkedin_source._fetch_description"
    ) as mock_fetch:
        li.select_handler(
            _valid_select_form(
                description_raw="",
                source_job_id="abc123notanumber",
            ),
            config=None,
        )

    mock_fetch.assert_not_called()


# ── 8. Lazy fetch failure → still returns values, no exception ───────────────

def test_select_handler_fetch_failure_still_returns_values(_patch_skills) -> None:
    """_fetch_description returning '' must not crash select_handler."""
    with patch(
        "src.job_sources.linkedin_source._fetch_description",
        return_value="",
    ):
        values = li.select_handler(
            _valid_select_form(description_raw="", source_job_id="77777"),
            config=None,
        )

    # Should return a valid dict; description stays empty
    assert isinstance(values, dict)
    assert values["description_raw"] == ""


# ── 9. config=None → no crash ────────────────────────────────────────────────

def test_select_handler_config_none_no_crash(_patch_skills) -> None:
    values = li.select_handler(_valid_select_form(), config=None)
    assert values["job_title"] == "Business Analyst"


# ── 10. config.state_root → cache DB path updated ────────────────────────────

def test_select_handler_config_state_root_sets_cache_path(
    _patch_skills, tmp_path: Path
) -> None:
    config = MagicMock()
    config.state_root = str(tmp_path)
    li.select_handler(_valid_select_form(), config=config)
    assert li._cache_db_path == tmp_path / "job_hunt_index.db"


# ── 11. source_ref uses url when present; falls back to job_id ───────────────

def test_select_handler_source_ref_from_url(_patch_skills) -> None:
    values = li.select_handler(_valid_select_form(), config=None)
    assert values["source_ref"] == "https://www.linkedin.com/jobs/view/12345/"


def test_select_handler_source_ref_falls_back_to_job_id(_patch_skills) -> None:
    values = li.select_handler(
        _valid_select_form(url=""), config=None
    )
    assert values["source_ref"] == "12345"


# ── 12. job_id format ────────────────────────────────────────────────────────

def test_select_handler_job_id_uses_numeric_source_job_id(_patch_skills) -> None:
    values = li.select_handler(_valid_select_form(source_job_id="98765"), config=None)
    assert values["job_id"] == "linkedin-98765"


def test_select_handler_job_id_falls_back_to_title_company(_patch_skills) -> None:
    """Non-numeric source_job_id → slug from title+company."""
    values = li.select_handler(
        _valid_select_form(source_job_id="not-numeric"),
        config=None,
    )
    # source_job_id "not-numeric" is not numeric but it IS a valid slug source
    assert values["job_id"].startswith("linkedin-")


# ── select_handler URL origin check (HIGH #3) ─────────────────────────────────

def test_select_handler_non_linkedin_url_raises(_patch_skills) -> None:
    """A URL not on linkedin.com must be rejected (tampered form)."""
    with pytest.raises(ValueError, match="linkedin.com"):
        li.select_handler(
            _valid_select_form(url="https://evil.com/steal"),
            config=None,
        )


def test_select_handler_http_non_linkedin_url_raises(_patch_skills) -> None:
    """http:// non-LinkedIn URL also rejected."""
    with pytest.raises(ValueError, match="linkedin.com"):
        li.select_handler(
            _valid_select_form(url="http://notlinkedin.com/jobs/view/1/"),
            config=None,
        )


def test_select_handler_empty_url_accepted(_patch_skills) -> None:
    """Empty URL is valid — source_ref falls back to job_id."""
    values = li.select_handler(_valid_select_form(url=""), config=None)
    assert values["source_ref"] == "12345"


def test_select_handler_valid_linkedin_url_accepted(_patch_skills) -> None:
    """Well-formed linkedin.com URL passes the origin check."""
    values = li.select_handler(
        _valid_select_form(url="https://www.linkedin.com/jobs/view/12345/"),
        config=None,
    )
    assert values["job_url"] == "https://www.linkedin.com/jobs/view/12345/"


def test_select_handler_empty_url_rebuilds_apply_link_from_numeric_id(
    _patch_skills,
) -> None:
    """Missing scraped href → job_url rebuilt from the numeric id so the
    saved job keeps a clickable apply link. source_ref still falls back to the
    bare job_id (unchanged, tamper guard untouched)."""
    values = li.select_handler(_valid_select_form(url=""), config=None)
    assert values["job_url"] == "https://www.linkedin.com/jobs/view/12345"
    assert values["source_ref"] == "12345"


def test_select_handler_empty_url_non_numeric_id_no_apply_link(
    _patch_skills,
) -> None:
    """No numeric id → cannot fabricate a valid advert URL; job_url stays
    empty rather than pointing somewhere that 404s."""
    values = li.select_handler(
        _valid_select_form(url="", source_job_id="not-numeric"),
        config=None,
    )
    assert values["job_url"] == ""
