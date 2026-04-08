from __future__ import annotations

from urllib.error import URLError

import pytest

from src import parsing
from src.parsing import JobParsingError, parse_job_from_text, parse_job_from_url


PASTED_JOB_TEXT = """
Senior Business Analyst
Example Co
Location: London
Salary: £60,000 - £70,000
Hybrid full-time role requiring 5 years experience.
You will lead stakeholder management, process mapping, SQL analysis, and Power BI reporting.
"""


def test_parse_job_from_text_prefills_expected_fields() -> None:
    payload = parse_job_from_text(PASTED_JOB_TEXT)

    assert payload["job_title"] == "Senior Business Analyst"
    assert payload["company"] == "Example Co"
    assert payload["location"] == "London"
    assert payload["work_mode"] == "hybrid"
    assert payload["employment_type"] == "full-time"
    assert payload["required_years_experience"] == 5.0
    assert payload["salary_min_gbp"] == 60000
    assert payload["salary_max_gbp"] == 70000
    assert payload["required_skills"] == ["SQL", "Power Bi", "Stakeholder Management", "Process Mapping"]
    assert payload["source_type"] == "copied_text"


def test_parse_job_from_url_fetches_html_and_converts_to_review_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeHeaders:
        @staticmethod
        def get_content_charset() -> str:
            return "utf-8"

    class FakeResponse:
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self) -> bytes:
            return b"<html><body><h1>Senior Business Analyst</h1><p>Example Co</p><p>Location: London</p><p>Hybrid role with SQL and stakeholder management.</p></body></html>"

    monkeypatch.setattr(parsing, "_is_fetch_allowed", lambda url: True)
    monkeypatch.setattr(parsing, "urlopen", lambda request, timeout=10: FakeResponse())

    payload = parse_job_from_url("https://example.com/jobs/123")

    assert payload["source_type"] == "url"
    assert payload["source_ref"] == "https://example.com/jobs/123"
    assert payload["job_title"] == "Senior Business Analyst"
    assert payload["company"] == "Example Co"


def test_parse_job_from_url_respects_robots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parsing, "_is_fetch_allowed", lambda url: False)

    with pytest.raises(JobParsingError, match="robots.txt"):
        parse_job_from_url("https://example.com/jobs/blocked")


def test_parse_job_from_url_raises_clean_error_when_fetch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parsing, "_is_fetch_allowed", lambda url: True)

    def raise_url_error(request, timeout=10):
        raise URLError("boom")

    monkeypatch.setattr(parsing, "urlopen", raise_url_error)

    with pytest.raises(JobParsingError, match="URL fetch failed"):
        parse_job_from_url("https://example.com/jobs/fail")
