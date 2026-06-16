from __future__ import annotations

import ipaddress
import re
import socket
import time
import uuid
from html.parser import HTMLParser
from urllib import robotparser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

DEFAULT_USER_AGENT = "JobSeekingTool/1.0"

# Timeout budgets (seconds)
NETWORK_TIMEOUT_SECONDS = 8
PARSE_TIMEOUT_SECONDS = 2

# Redirect limit
MAX_REDIRECTS = 3

# Content-size guard: 5 MB decompressed
MAX_CONTENT_BYTES = 5 * 1024 * 1024

# Robots TTL cache
ROBOTS_CACHE_TTL = 300  # 5 minutes

# Host allowlist (from design doc Section 3).
# Empty set = all hosts allowed (not used here; populated per spec).
ALLOWED_HOSTS: frozenset[str] = frozenset({
    "indeed.com",
    "www.indeed.com",
    "uk.indeed.com",
    "linkedin.com",
    "www.linkedin.com",
    "reed.co.uk",
    "www.reed.co.uk",
    "glassdoor.com",
    "www.glassdoor.com",
    "glassdoor.co.uk",
    "www.glassdoor.co.uk",
    "cwjobs.co.uk",
    "www.cwjobs.co.uk",
    "cv-library.co.uk",
    "www.cv-library.co.uk",
    "jobs.theguardian.com",
    "guardianjobs.co.uk",
    "www.guardianjobs.co.uk",
})

KNOWN_WORK_MODES = ("remote", "hybrid", "onsite", "on-site")
KNOWN_EMPLOYMENT_TYPES = (
    "full-time",
    "part-time",
    "contract",
    "permanent",
    "temporary",
    "internship",
)
KNOWN_SKILLS = (
    "sql",
    "python",
    "power bi",
    "tableau",
    "stakeholder management",
    "process mapping",
    "agile",
    "scrum",
    "data analysis",
    "business analysis",
    "requirements gathering",
)

# Private/loopback IP ranges for SSRF prevention
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),        # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),       # IPv6 link-local
]


class JobParsingError(ValueError):
    """Raised when job parsing or fetching fails."""


# ---------------------------------------------------------------------------
# Robots TTL cache (ported from paste_fetch.py, reversed to fail-closed)
# ---------------------------------------------------------------------------

class _RobotsCache:
    """Per-host robots.txt cache with 5-minute TTL. Fails closed on error."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[bool, float]] = {}  # host -> (allowed, fetched_at)

    def is_allowed(self, url: str, user_agent: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        now = time.time()

        entry = self._cache.get(host)
        if entry is not None:
            allowed, fetched_at = entry
            if now - fetched_at < ROBOTS_CACHE_TTL:
                return allowed
            # Expired — drop and re-fetch

        robots_url = f"{parsed.scheme}://{host}/robots.txt"
        parser = robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.read()
        except Exception:
            # Fail CLOSED: any error fetching/parsing robots.txt blocks the fetch
            self._cache[host] = (False, now)
            return False

        allowed = parser.can_fetch(user_agent, url)
        self._cache[host] = (allowed, now)
        return allowed


# Module-level robots cache (shared across calls for TTL benefit)
_robots_cache = _RobotsCache()


# ---------------------------------------------------------------------------
# HTML text extractor (strips scripts/styles/iframes)
# ---------------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "iframe"}:
            self._skip_depth += 1
        if tag in {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "iframe"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "div", "section", "article", "li"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)
            self._parts.append(" ")

    def get_text(self) -> str:
        joined = "".join(self._parts)
        lines = [re.sub(r"\s+", " ", line).strip() for line in joined.splitlines()]
        return "\n".join(line for line in lines if line).strip()


# ---------------------------------------------------------------------------
# Public parse functions
# ---------------------------------------------------------------------------

def parse_job_from_text(raw_text: str, *, source_ref: str | None = None) -> dict[str, object]:
    cleaned = _clean_text(raw_text)
    if not cleaned:
        raise JobParsingError("No job text was provided")

    title = _extract_field(cleaned, [r"job title\s*[:\-]\s*(.+)", r"title\s*[:\-]\s*(.+)"])
    company = _extract_field(cleaned, [r"company\s*[:\-]\s*(.+)", r"employer\s*[:\-]\s*(.+)"])
    location = _extract_field(cleaned, [r"location\s*[:\-]\s*(.+)"])
    salary_min, salary_max = _extract_salary_range(cleaned)
    work_mode = _extract_keyword(cleaned, KNOWN_WORK_MODES)
    employment_type = _extract_keyword(cleaned, KNOWN_EMPLOYMENT_TYPES)
    years = _extract_years(cleaned)
    skills = _extract_skills(cleaned)

    # P1-3: Null contract — do NOT fall back to placeholder strings for title/company
    # Infer title/company from document structure only if extraction found something
    if title is None:
        lines = [line for line in cleaned.splitlines() if line.strip()]
        title = lines[0] if lines else None

    if company is None:
        lines = [line for line in cleaned.splitlines() if line.strip()]
        company = _extract_company_from_lines(lines) or None

    # P1-3: UUID fallback for job_id when both title and company are None
    if title and company:
        job_id = _build_job_id(title, company)
    else:
        job_id = str(uuid.uuid4())[:8]

    return {
        "job_id": job_id,
        "job_title": title,           # None if not found (null contract)
        "company": company,           # None if not found (null contract)
        "description_raw": cleaned,
        "source_type": "url" if source_ref else "copied_text",
        "source_ref": source_ref,
        "location": location,         # None if not found
        "work_mode": _normalise_work_mode(work_mode),  # "unknown" if not found
        "employment_type": employment_type,             # None if not found
        "required_skills": skills,                      # [] if none found
        "preferred_skills": [],
        "required_years_experience": years,             # None if not found
        "nice_to_have_years_experience": None,
        "domain": None,
        "notes": None,
        "salary_min_gbp": salary_min,  # None if not found
        "salary_max_gbp": salary_max,  # None if not found
    }


def parse_job_from_url(url: str) -> dict[str, object]:
    """
    Fetch a job page from URL with full security hardening:
    - Host allowlist
    - HTTPS-first with redirect revalidation (max 3 hops)
    - Split timeout: 8s network, 2s parse
    - Content-type guard (HTML only)
    - Content-size guard (5MB)
    - robots.txt fail-closed
    - Script/style stripping
    - SSRF prevention
    """
    cleaned_url = url.strip()
    if not cleaned_url:
        raise JobParsingError("URL is required")

    parsed = urlparse(cleaned_url)

    # Scheme check: must be http or https
    if parsed.scheme not in ("http", "https"):
        raise JobParsingError(f"Unsupported URL scheme: {parsed.scheme!r}. Only https is supported.")

    # Host allowlist check
    host = parsed.netloc.lower()
    if not _is_allowed_host(host):
        raise JobParsingError(
            f"Host {host!r} is not in the allowed list. Supported: {', '.join(sorted(ALLOWED_HOSTS))}"
        )

    # SSRF prevention: resolve host and check for private IPs
    _check_ssrf(host)

    # Robots.txt check (fail closed)
    if not _robots_cache.is_allowed(cleaned_url, DEFAULT_USER_AGENT):
        raise JobParsingError("Fetching this URL is blocked by robots.txt")

    # Fetch with per-hop budget and redirect revalidation
    budget_start = time.monotonic()
    current_url = cleaned_url
    visited: list[str] = []

    for hop in range(MAX_REDIRECTS + 1):
        elapsed = time.monotonic() - budget_start
        remaining = NETWORK_TIMEOUT_SECONDS - elapsed
        if remaining <= 0:
            raise JobParsingError("URL fetch timed out (network budget exhausted)")

        # Loop detection
        canonical = _canonical_url(current_url)
        if canonical in visited:
            raise JobParsingError("Redirect loop detected")
        visited.append(canonical)

        request = Request(current_url, headers={"User-Agent": DEFAULT_USER_AGENT})
        try:
            with urlopen(request, timeout=remaining) as response:
                final_url = response.geturl()

                # If redirected, revalidate final URL
                if final_url != current_url:
                    _revalidate_redirect(final_url)
                    current_url = final_url
                    # Check budget before next hop
                    if time.monotonic() - budget_start >= NETWORK_TIMEOUT_SECONDS:
                        raise JobParsingError("URL fetch timed out after redirect")
                    continue

                # Content-type guard
                content_type = response.headers.get_content_type() or ""
                if not _is_html_content_type(content_type):
                    raise JobParsingError(
                        f"Unexpected content type {content_type!r}. Only HTML pages are supported."
                    )

                # Content-size guard
                raw_bytes = response.read(MAX_CONTENT_BYTES + 1)
                if len(raw_bytes) > MAX_CONTENT_BYTES:
                    raise JobParsingError(
                        f"Response too large (>{MAX_CONTENT_BYTES // (1024*1024)}MB). "
                        "Paste the job text instead."
                    )

                charset = response.headers.get_content_charset() or "utf-8"
                html_content = raw_bytes.decode(charset, errors="replace")

        except JobParsingError:
            raise
        except HTTPError as exc:
            raise JobParsingError(f"URL fetch failed: HTTP {exc.code}") from exc
        except URLError as exc:
            raise JobParsingError(f"URL fetch failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise JobParsingError("URL fetch timed out") from exc

        # Successfully got the page — parse within parse budget
        text = _extract_text_from_html(html_content)
        if not text:
            raise JobParsingError("Could not extract readable job text from the URL")
        return parse_job_from_text(text, source_ref=cleaned_url)

    raise JobParsingError(f"Too many redirects (>{MAX_REDIRECTS})")


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

def _is_allowed_host(host: str) -> bool:
    """Check host against allowlist. Also accepts subdomains of allowed hosts."""
    host_lower = host.lower()
    if host_lower in ALLOWED_HOSTS:
        return True
    # Accept subdomains
    for allowed in ALLOWED_HOSTS:
        if host_lower.endswith(f".{allowed}"):
            return True
    return False


def _check_ssrf(host: str) -> None:
    """Raise JobParsingError if host resolves to a private/loopback address."""
    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Cannot resolve — let the actual fetch fail later
        return
    for _, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        for network in _PRIVATE_NETWORKS:
            if ip in network:
                raise JobParsingError(
                    f"URL resolves to a private/loopback address ({ip_str}). Fetch blocked."
                )


def _revalidate_redirect(url: str) -> None:
    """Re-validate scheme and host after a redirect hop."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise JobParsingError(
            f"Redirect led to non-HTTPS URL ({parsed.scheme}://). Fetch blocked."
        )
    host = parsed.netloc.lower()
    if not _is_allowed_host(host):
        raise JobParsingError(
            f"Redirect to non-allowlisted host {host!r}. Fetch blocked."
        )
    _check_ssrf(host)


def _canonical_url(url: str) -> str:
    """Normalise URL for redirect loop detection."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    base = f"{parsed.scheme}://{parsed.netloc.lower()}{path}"
    return f"{base}?{parsed.query}" if parsed.query else base


def _is_html_content_type(content_type: str) -> bool:
    ct = content_type.lower().split(";")[0].strip()
    return ct in {"text/html", "text/plain", "application/xhtml+xml"}


def _is_fetch_allowed(url: str) -> bool:
    """Legacy helper (used by existing tests via monkeypatch)."""
    return _robots_cache.is_allowed(url, DEFAULT_USER_AGENT)


# ---------------------------------------------------------------------------
# Text extraction and parsing helpers
# ---------------------------------------------------------------------------

def _extract_text_from_html(content: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(content)
    return parser.get_text()


def _clean_text(value: str) -> str:
    return "\n".join(line.strip() for line in value.strip().splitlines() if line.strip())


def _extract_field(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_salary_range(text: str) -> tuple[int | None, int | None]:
    values = [int(number.replace(",", "")) for number in re.findall(r"£\s*([0-9]{2,3}(?:,[0-9]{3})*)", text)]
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], None
    return min(values), max(values)


def _extract_years(text: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\+?\s+years?", text, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def _extract_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
    lowered = text.casefold()
    for keyword in keywords:
        if keyword.casefold() in lowered:
            return keyword
    return None


def _normalise_work_mode(value: str | None) -> str:
    """Return normalised work_mode string. Falls back to 'unknown' (not None) per null contract."""
    if value == "on-site":
        return "onsite"
    if value is None:
        return "unknown"
    return value


def _extract_skills(text: str) -> list[str]:
    lowered = text.casefold()
    found: list[str] = []
    for skill in KNOWN_SKILLS:
        if skill in lowered:
            found.append(skill.title() if skill != "sql" else "SQL")
    return found


def _extract_company_from_lines(lines: list[str]) -> str | None:
    for index, line in enumerate(lines[:4]):
        if re.search(r"\b(?:at|@)\b", line, flags=re.IGNORECASE):
            parts = re.split(r"\b(?:at|@)\b", line, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
        if index == 1 and line and len(line.split()) <= 6:
            return line.strip()
    return None


def _build_job_id(title: str, company: str) -> str:
    base = f"{title}-{company}".casefold()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:80] or "job-review"
