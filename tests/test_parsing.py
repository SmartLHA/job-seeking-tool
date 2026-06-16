from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from src import job_hunt_parsing as parsing
from src.job_hunt_parsing import JobParsingError, parse_job_from_text, parse_job_from_url


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


# ---------------------------------------------------------------------------
# Helper: fake response for URL tests
# ---------------------------------------------------------------------------

class _FakeHtmlHeaders:
    def get_content_type(self) -> str:
        return "text/html"
    def get_content_charset(self) -> str:
        return "utf-8"
    def get(self, name: str, default: str = "") -> str:
        return default


class _FakeHtmlResponse:
    headers = _FakeHtmlHeaders()

    def __init__(self, url: str, body: bytes = b"<html><body><h1>Senior Business Analyst</h1><p>Example Co</p><p>Location: London</p><p>Hybrid role with SQL and stakeholder management.</p></body></html>"):
        self._url = url
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, max_bytes: int = -1) -> bytes:
        if max_bytes > 0:
            return self._body[:max_bytes]
        return self._body


def _no_ssrf(host: str) -> None:
    pass


def test_parse_job_from_url_fetches_html_and_converts_to_review_payload() -> None:
    fake_resp = _FakeHtmlResponse("https://reed.co.uk/jobs/123")
    with patch.object(parsing._robots_cache, "is_allowed", return_value=True), \
         patch.object(parsing, "_check_ssrf", _no_ssrf), \
         patch.object(parsing, "urlopen", return_value=fake_resp):
        payload = parse_job_from_url("https://reed.co.uk/jobs/123")

    assert payload["source_type"] == "url"
    assert payload["source_ref"] == "https://reed.co.uk/jobs/123"
    assert payload["job_title"] == "Senior Business Analyst"
    assert payload["company"] == "Example Co"


def test_parse_job_from_url_respects_robots() -> None:
    with patch.object(parsing._robots_cache, "is_allowed", return_value=False), \
         patch.object(parsing, "_check_ssrf", _no_ssrf):
        with pytest.raises(JobParsingError, match="robots.txt"):
            parse_job_from_url("https://reed.co.uk/jobs/blocked")


def test_parse_job_from_url_raises_clean_error_when_fetch_fails() -> None:
    from urllib.error import URLError

    def raise_url_error(request, timeout=None):
        raise URLError("boom")

    with patch.object(parsing._robots_cache, "is_allowed", return_value=True), \
         patch.object(parsing, "_check_ssrf", _no_ssrf), \
         patch.object(parsing, "urlopen", raise_url_error):
        with pytest.raises(JobParsingError, match="URL fetch failed"):
            parse_job_from_url("https://reed.co.uk/jobs/fail")


# ---------------------------------------------------------------------------
# P1-3: Null contract tests
# ---------------------------------------------------------------------------

def test_null_contract_location_is_none_when_absent() -> None:
    payload = parse_job_from_text("Some job text with no location info")
    assert payload["location"] is None


def test_null_contract_salary_is_none_when_absent() -> None:
    payload = parse_job_from_text("A job with no salary information")
    assert payload["salary_min_gbp"] is None
    assert payload["salary_max_gbp"] is None


def test_null_contract_work_mode_is_unknown_when_absent() -> None:
    # Use text that contains none of: remote, hybrid, onsite, on-site
    payload = parse_job_from_text("A job posting that does not mention working arrangement or location preference")
    assert payload["work_mode"] == "unknown"


def test_null_contract_employment_type_is_none_when_absent() -> None:
    payload = parse_job_from_text("A job posting with no type mentioned")
    assert payload["employment_type"] is None


def test_null_contract_required_skills_is_empty_list_when_absent() -> None:
    payload = parse_job_from_text("A job posting with no known skills listed")
    assert payload["required_skills"] == []


def test_null_contract_preferred_skills_is_always_empty_list() -> None:
    payload = parse_job_from_text("A job posting text")
    assert payload["preferred_skills"] == []


def test_null_contract_years_experience_is_none_when_absent() -> None:
    payload = parse_job_from_text("A job with no duration requirement")
    assert payload["required_years_experience"] is None


def test_null_contract_nice_to_have_years_is_always_none() -> None:
    payload = parse_job_from_text("Some job text")
    assert payload["nice_to_have_years_experience"] is None


def test_null_contract_domain_is_always_none() -> None:
    payload = parse_job_from_text("Some job text")
    assert payload["domain"] is None


def test_null_contract_notes_is_always_none() -> None:
    payload = parse_job_from_text("Some job text")
    assert payload["notes"] is None


def test_null_contract_job_title_is_none_when_no_text() -> None:
    # job_title falls back to lines[0] — must not be a placeholder like "Unknown title"
    payload = parse_job_from_text("xyz")
    assert payload["job_title"] != "Unknown title"
    assert payload["job_title"] != "Unknown"


def test_null_contract_company_not_a_placeholder_when_absent() -> None:
    payload = parse_job_from_text("Software Developer role")
    assert payload["company"] != "Unknown company"
    assert payload["company"] != "Unknown"


def test_null_contract_job_id_is_short_uuid_when_company_none() -> None:
    """When company is None, job_id must be a UUID rather than a slug."""
    def mock_no_company(lines):
        return None

    with patch.object(parsing, "_extract_company_from_lines", mock_no_company), \
         patch.object(parsing, "_extract_field", return_value=None):
        payload = parse_job_from_text("xyz")

    assert payload["company"] is None
    # job_id should be UUID-style: 8 hex chars
    assert len(payload["job_id"]) == 8


def test_work_mode_onsite_normalised_from_on_site() -> None:
    payload = parse_job_from_text("This is an on-site role in central London")
    assert payload["work_mode"] == "onsite"


def test_null_contract_no_placeholder_strings_in_any_field() -> None:
    """None of the scalar fields should return placeholder strings when absent."""
    payload = parse_job_from_text("A minimalist job post")
    forbidden_placeholders = {"Unknown", "N/A", "n/a", "unknown company", "Unknown company",
                              "Unknown title", "unknown title", ""}
    for field_name in ("location", "employment_type", "domain", "notes"):
        val = payload[field_name]
        assert val is None or val not in forbidden_placeholders, \
            f"{field_name} returned placeholder {val!r}"


# ---------------------------------------------------------------------------
# P1-4: URL hardening tests
# ---------------------------------------------------------------------------

def test_url_hardening_rejects_non_https_scheme() -> None:
    """Non-http/https schemes are rejected before any network access."""
    with pytest.raises(JobParsingError, match="scheme"):
        parse_job_from_url("ftp://reed.co.uk/jobs/1")


def test_url_hardening_rejects_non_allowlisted_host() -> None:
    """Host not in allowlist is rejected before network access."""
    with pytest.raises(JobParsingError, match="not in the allowed list"):
        parse_job_from_url("https://evil.com/jobs/1")


def test_url_hardening_rejects_loopback_ip() -> None:
    """SSRF: loopback address is rejected."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    with patch.object(parsing._robots_cache, "is_allowed", return_value=True), \
         patch("socket.getaddrinfo", fake_getaddrinfo):
        with pytest.raises(JobParsingError, match="private/loopback"):
            parse_job_from_url("https://reed.co.uk/jobs/1")


def test_url_hardening_rejects_private_ip_10_x() -> None:
    """SSRF: 10.x.x.x range is rejected."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0))]

    with patch.object(parsing._robots_cache, "is_allowed", return_value=True), \
         patch("socket.getaddrinfo", fake_getaddrinfo):
        with pytest.raises(JobParsingError, match="private/loopback"):
            parse_job_from_url("https://reed.co.uk/jobs/1")


def test_url_hardening_rejects_private_ip_192_168() -> None:
    """SSRF: 192.168.x.x range is rejected."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.100", 0))]

    with patch.object(parsing._robots_cache, "is_allowed", return_value=True), \
         patch("socket.getaddrinfo", fake_getaddrinfo):
        with pytest.raises(JobParsingError, match="private/loopback"):
            parse_job_from_url("https://reed.co.uk/jobs/1")


def test_url_hardening_robots_txt_fail_closed() -> None:
    """robots.txt blocking causes fetch to be rejected (fail closed)."""
    with patch.object(parsing._robots_cache, "is_allowed", return_value=False), \
         patch.object(parsing, "_check_ssrf", _no_ssrf):
        with pytest.raises(JobParsingError, match="robots.txt"):
            parse_job_from_url("https://reed.co.uk/jobs/blocked")


def test_url_hardening_robots_txt_error_is_fail_closed() -> None:
    """robots.txt fetch error causes fail-closed (returns False, not True)."""
    cache = parsing._RobotsCache()
    with patch("urllib.robotparser.RobotFileParser.read", side_effect=Exception("timeout")):
        result = cache.is_allowed("https://reed.co.uk/jobs/1", parsing.DEFAULT_USER_AGENT)
    assert result is False, "Expected fail-closed (False) on robots.txt error"


def test_url_hardening_content_type_rejection() -> None:
    """Non-HTML content type causes rejection."""
    class FakePdfHeaders:
        def get_content_type(self) -> str: return "application/pdf"
        def get_content_charset(self) -> str: return "utf-8"
        def get(self, name: str, default: str = "") -> str: return default

    class FakePdfResponse:
        headers = FakePdfHeaders()
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def geturl(self) -> str: return "https://reed.co.uk/jobs/pdf"
        def read(self, max_bytes: int = -1) -> bytes: return b"%PDF-1.4 binary content"

    with patch.object(parsing._robots_cache, "is_allowed", return_value=True), \
         patch.object(parsing, "_check_ssrf", _no_ssrf), \
         patch.object(parsing, "urlopen", return_value=FakePdfResponse()):
        with pytest.raises(JobParsingError, match="content type"):
            parse_job_from_url("https://reed.co.uk/jobs/pdf")


def test_url_hardening_content_size_rejection() -> None:
    """Response larger than MAX_CONTENT_BYTES causes rejection."""
    oversized = b"x" * (parsing.MAX_CONTENT_BYTES + 1)

    class FakeLargeHeaders:
        def get_content_type(self) -> str: return "text/html"
        def get_content_charset(self) -> str: return "utf-8"
        def get(self, name: str, default: str = "") -> str: return default

    class FakeLargeResponse:
        headers = FakeLargeHeaders()
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def geturl(self) -> str: return "https://reed.co.uk/jobs/big"
        def read(self, max_bytes: int = -1) -> bytes:
            if max_bytes > 0:
                return oversized[:max_bytes]
            return oversized

    with patch.object(parsing._robots_cache, "is_allowed", return_value=True), \
         patch.object(parsing, "_check_ssrf", _no_ssrf), \
         patch.object(parsing, "urlopen", return_value=FakeLargeResponse()):
        with pytest.raises(JobParsingError, match="too large"):
            parse_job_from_url("https://reed.co.uk/jobs/big")


def test_url_hardening_redirect_to_http_rejected() -> None:
    """Redirect to HTTP (non-HTTPS) final URL is rejected."""
    class FakeRedirectHeaders:
        def get_content_type(self) -> str: return "text/html"
        def get_content_charset(self) -> str: return "utf-8"
        def get(self, name: str, default: str = "") -> str: return default

    class FakeRedirectResponse:
        headers = FakeRedirectHeaders()
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def geturl(self) -> str: return "http://reed.co.uk/jobs/redirected"
        def read(self, max_bytes: int = -1) -> bytes: return b"<html><body>redirected</body></html>"

    with patch.object(parsing._robots_cache, "is_allowed", return_value=True), \
         patch.object(parsing, "_check_ssrf", _no_ssrf), \
         patch.object(parsing, "urlopen", return_value=FakeRedirectResponse()):
        with pytest.raises(JobParsingError, match="non-HTTPS"):
            parse_job_from_url("https://reed.co.uk/jobs/1")


def test_url_hardening_redirect_to_non_allowlisted_host_rejected() -> None:
    """Redirect to non-allowlisted host is rejected."""
    class FakeCrossRedirectHeaders:
        def get_content_type(self) -> str: return "text/html"
        def get_content_charset(self) -> str: return "utf-8"
        def get(self, name: str, default: str = "") -> str: return default

    class FakeCrossRedirectResponse:
        headers = FakeCrossRedirectHeaders()
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def geturl(self) -> str: return "https://evil.com/steal-credentials"
        def read(self, max_bytes: int = -1) -> bytes: return b""

    with patch.object(parsing._robots_cache, "is_allowed", return_value=True), \
         patch.object(parsing, "_check_ssrf", _no_ssrf), \
         patch.object(parsing, "urlopen", return_value=FakeCrossRedirectResponse()):
        with pytest.raises(JobParsingError, match="non-allowlisted host"):
            parse_job_from_url("https://reed.co.uk/jobs/1")


def test_url_hardening_http_only_scheme_blocked() -> None:
    """file:// and javascript:// schemes are rejected early."""
    with pytest.raises(JobParsingError, match="scheme"):
        parse_job_from_url("file:///etc/passwd")
    with pytest.raises(JobParsingError, match="scheme"):
        parse_job_from_url("javascript:alert(1)")


def test_url_hardening_max_redirects_exceeded() -> None:
    """More than MAX_REDIRECTS hops causes rejection."""
    hop_count = {"n": 0}

    class FakeRedirectChainHeaders:
        def get_content_type(self) -> str: return "text/html"
        def get_content_charset(self) -> str: return "utf-8"
        def get(self, name: str, default: str = "") -> str: return default

    class FakeRedirectChainResponse:
        headers = FakeRedirectChainHeaders()
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def geturl(self) -> str:
            hop_count["n"] += 1
            return f"https://reed.co.uk/jobs/hop{hop_count['n']}"
        def read(self, max_bytes: int = -1) -> bytes: return b""

    def make_response(req, timeout=None):
        return FakeRedirectChainResponse()

    with patch.object(parsing._robots_cache, "is_allowed", return_value=True), \
         patch.object(parsing, "_check_ssrf", _no_ssrf), \
         patch.object(parsing, "urlopen", make_response):
        with pytest.raises(JobParsingError, match="redirect"):
            parse_job_from_url("https://reed.co.uk/jobs/start")


def test_url_hardening_empty_url_rejected() -> None:
    with pytest.raises(JobParsingError, match="URL is required"):
        parse_job_from_url("")
    with pytest.raises(JobParsingError, match="URL is required"):
        parse_job_from_url("   ")
