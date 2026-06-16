"""
Network fetcher for job pages — fetches HTML from a URL within a strict budget.

Architecture:
- fetch_job_page(url) — main entry point
- AllowedDomains — set of allowed domains
- NetworkBudget — tracks wall-clock time, fails fast when exhausted
- RobotsCache — dict caching robots.txt per host (5 min TTL)
- detect_redirect_loop(visited_urls) — detects canonicalized URL loops

Error types (returned to ui.py for display):
    unsupported_domain | timeout | redirect_loop | blocked | fetch_error

Budget: 10s total (caller allocates 8s for network, 2s for parse)
"""

from __future__ import annotations

import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_DOMAINS: frozenset[str] = frozenset({
    "indeed.com",
    "www.indeed.com",
    "linkedin.com",
    "www.linkedin.com",
    "jobs.linkedin.com",
    "reed.co.uk",
    "www.reed.co.uk",
    "glassdoor.com",
    "www.glassdoor.com",
    "guardianjobs.com",
    "www.guardianjobs.com",
    "cwjobs.co.uk",
    "www.cwjobs.co.uk",
    "cv-library.co.uk",
    "www.cv-library.co.uk",
})

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

MAX_REDIRECTS = 3          # max hops before giving up
ROBOTS_CACHE_TTL = 300     # 5 minutes
NETWORK_TIMEOUT = 8.0      # seconds — shared across all hops

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _is_allowed_domain(url: str) -> bool:
    domain = _domain(url)
    # Exact match or subdomain of an allowed domain
    return domain in ALLOWED_DOMAINS or any(
        domain.endswith(f".{ad}") for ad in ALLOWED_DOMAINS
    )


def _canonical_url(url: str) -> str:
    """Return a normalised URL for loop detection (no fragment, trailing slash stripped)."""
    parsed = urlparse(url)
    return (
        f"{parsed.scheme}://{parsed.netloc.lower()}"
        f"{parsed.path.rstrip('/')}"
        f"?{parsed.query}" if parsed.query else ""
    )


def detect_redirect_loop(visited_urls: list[str]) -> bool:
    """
    Detect a redirect loop by comparing canonicalised URLs.

    A loop exists if the same canonical URL appears more than once
    in the visited chain.
    """
    canonicals = [_canonical_url(u) for u in visited_urls]
    return len(canonicals) != len(set(canonicals))


# ---------------------------------------------------------------------------
# Robots Cache
# ---------------------------------------------------------------------------

class RobotsCache:
    """
    Caches robots.txt fetch results per host, with a 5-minute TTL.

    Thread-safe for single-threaded use; does not need locking in our context.
    """

    __slots__ = ("_cache",)

    def __init__(self) -> None:
        self._cache: dict[str, tuple[bool, float]] = {}  # host → (allowed, fetched_at)

    def is_allowed(self, url: str) -> bool | None:
        """
        Returns True/False if we have a cached robots.txt decision for this host,
        or None if the host is not yet cached.
        """
        from urllib import robotparser

        host = _domain(url)
        entry = self._cache.get(host)
        now = time.time()

        if entry is not None:
            allowed, fetched_at = entry
            if now - fetched_at < ROBOTS_CACHE_TTL:
                return allowed
            # Expired — drop and re-fetch below

        # Fetch /robots.txt
        robots_url = f"{urlparse(url).scheme}://{host}/robots.txt"
        parser = robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.read()
        except Exception:
            # On any error (timeout, connection, parse), optimistically allow
            self._cache[host] = (True, now)
            return True

        allowed = parser.can_fetch(USER_AGENT, url)
        self._cache[host] = (allowed, now)
        return allowed


# ---------------------------------------------------------------------------
# Network Budget
# ---------------------------------------------------------------------------

class NetworkBudget:
    """
    Tracks wall-clock time across multiple network ops.

    Fails fast once the allocated window is exhausted.
    """

    __slots__ = ("_start", "_limit")

    def __init__(self, limit: float = NETWORK_TIMEOUT) -> None:
        self._start = time.time()
        self._limit = limit

    @property
    def remaining(self) -> float:
        return max(0.0, self._limit - (time.time() - self._start))

    @property
    def exhausted(self) -> bool:
        return time.time() - self._start >= self._limit

    def error(self) -> dict[str, str]:
        return {
            "success": False,
            "error": "Request timed out",
            "error_type": "timeout",
        }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def fetch_job_page(url: str) -> dict:
    """
    Fetch a job page from URL within the allocated network budget.

    Args:
        url: Job posting URL (must be from an allowed domain)

    Returns:
        {"success": True, "html": "...", "final_url": "...", "source": "indeed"}
        {"success": False, "error": "...", "error_type": "timeout|blocked|redirect_loop|unsupported_domain|fetch_error"}
    """
    url = url.strip()
    if not url:
        return {"success": False, "error": "URL is required", "error_type": "fetch_error"}

    if not _is_allowed_domain(url):
        return {
            "success": False,
            "error": f"Domain not supported. Allowed: {', '.join(sorted(ALLOWED_DOMAINS))}",
            "error_type": "unsupported_domain",
        }

    budget = NetworkBudget()
    robots_cache = RobotsCache()
    visited: list[str] = []
    current_url = url

    for hop in range(MAX_REDIRECTS + 1):
        # ---- Budget check ----
        if budget.exhausted:
            return budget.error()

        # ---- Robots check (per-hop) ----
        allowed = robots_cache.is_allowed(current_url)
        if allowed is False:
            return {
                "success": False,
                "error": "Fetching this URL is disallowed by robots.txt",
                "error_type": "blocked",
            }

        # ---- Loop detection ----
        visited.append(current_url)
        if detect_redirect_loop(visited):
            return {
                "success": False,
                "error": "Redirect loop detected",
                "error_type": "redirect_loop",
            }

        # ---- Fetch (with remaining budget as timeout) ----
        remaining = budget.remaining
        if remaining <= 0:
            return budget.error()

        request = Request(current_url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=remaining) as response:
                final_url = response.geturl()
                html = response.read()

                # Decode with fallback
                charset = response.headers.get_content_charset() or "utf-8"
                try:
                    html_text = html.decode(charset, errors="strict")
                except UnicodeDecodeError:
                    html_text = html.decode("utf-8", errors="replace")

        except HTTPError as exc:
            return {
                "success": False,
                "error": f"HTTP error {exc.code}",
                "error_type": "fetch_error",
            }
        except URLError as exc:
            return {
                "success": False,
                "error": str(exc.reason),
                "error_type": "fetch_error",
            }
        except TimeoutError:
            return budget.error()

        # ---- Handle redirect ----
        if final_url != current_url:
            current_url = final_url
            # Clear loop detection for new host (redirects to different domain aren't loops)
            # but keep path cycle detection via canonicalisation in detect_redirect_loop
            continue
        else:
            # Success — got final page
            source = _source_from_url(final_url)
            return {
                "success": True,
                "html": html_text,
                "final_url": final_url,
                "source": source,
            }

    # Exceeded MAX_REDIRECTS
    return {
        "success": False,
        "error": f"Too many redirects (>{MAX_REDIRECTS})",
        "error_type": "redirect_loop",
    }


def _source_from_url(url: str) -> str:
    """Derive a short source name from the URL."""
    domain = _domain(url)
    # Strip www. prefix
    source = domain.removeprefix("www.")
    # Known short names
    if "indeed" in source:
        return "indeed"
    if "linkedin" in source:
        return "linkedin"
    if "reed" in source:
        return "reed"
    if "glassdoor" in source:
        return "glassdoor"
    if "guardian" in source:
        return "guardianjobs"
    if "cwjobs" in source:
        return "cwjobs"
    if "cv-library" in source:
        return "cvlibrary"
    return source.split(".")[0]