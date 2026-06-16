"""Safety and URL policy gates for public web extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


ALLOWED_CATEGORIES = {
    "product_homepage",
    "pricing_page",
    "documentation",
    "api_docs",
    "blog_article",
    "careers_landing",
    "job_detail",
    "job_search_results",
    "company_about",
    "directory_listing",
    "news_article",
    "unknown",
}

LOGIN_WALL_TERMS = (
    "login required",
    "sign in required",
    "log in to view",
    "sign in to view",
    "create an account to view",
    "you need to sign in",
    "please sign in to continue",
)
UNAVAILABLE_TERMS = ("404", "not found", "expired", "removed", "blocked", "access denied", "rate limit")
FORM_TERMS = ("submit application", "upload cv", "upload resume", "checkout", "payment")
COOKIE_TERMS = ("cookie banner", "uses cookies", "cookie consent", "accept all cookies")


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    reason: str | None = None


def normalize_url(url: str | None) -> str:
    if not url or not isinstance(url, str):
        return ""
    value = url.strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    return value


def extract_domain(url: str | None) -> str | None:
    normalized = normalize_url(url)
    if not normalized:
        return None
    hostname = urlparse(normalized).hostname
    if not hostname:
        return None
    hostname = hostname.lower().rstrip(".")
    return hostname[4:] if hostname.startswith("www.") else hostname


def _domain_matches(domain: str | None, policy_domains: list[str]) -> bool:
    if not domain:
        return False
    clean = domain.lower().rstrip(".")
    for value in policy_domains:
        candidate = value.lower().strip().rstrip(".")
        if candidate.startswith("www."):
            candidate = candidate[4:]
        if clean == candidate or clean.endswith(f".{candidate}"):
            return True
    return False


def is_blocklisted(url: str, config: dict[str, Any]) -> bool:
    return _domain_matches(extract_domain(url), config.get("blocklist", []))


def candidate_urls(candidates: list[dict[str, Any]]) -> set[str]:
    return {normalize_url(item.get("url")) for item in candidates if normalize_url(item.get("url"))}


def validate_candidate_url(url: str, candidates: list[dict[str, Any]], config: dict[str, Any]) -> PolicyResult:
    normalized = normalize_url(url)
    if not normalized:
        return PolicyResult(False, "missing_or_invalid_url")
    if urlparse(normalized).scheme not in {"http", "https"}:
        return PolicyResult(False, "unsupported_url_scheme")
    if is_blocklisted(normalized, config):
        return PolicyResult(False, "domain_blocklisted")
    if config.get("candidate_url_only_mode", True) and normalized not in candidate_urls(candidates):
        return PolicyResult(False, "url_not_in_candidate_pages")
    return PolicyResult(True)


def detect_category(url: str, text: str, assigned: str | None = None) -> str:
    if assigned in ALLOWED_CATEGORIES:
        return assigned
    hay = f"{url} {text}".lower()
    if "pricing" in hay:
        return "pricing_page"
    if "/docs" in hay or "documentation" in hay:
        return "documentation"
    if "/api" in hay or "api reference" in hay:
        return "api_docs"
    if "/blog" in hay or "article" in hay:
        return "blog_article"
    if "careers" in hay:
        return "careers_landing"
    if "job" in hay and ("location" in hay or "employment type" in hay):
        return "job_detail"
    if "open roles" in hay or "job board" in hay:
        return "job_search_results"
    if "about" in hay or "company" in hay:
        return "company_about"
    if "directory" in hay or "companies" in hay:
        return "directory_listing"
    return "unknown"


def inspect_visible_text(text: str) -> dict[str, bool]:
    hay = (text or "").lower()
    stripped = (text or "").strip()
    meaningful_text = len(stripped) >= 250
    first_screen = hay[:1500]
    login_wall_seen = any(term in hay for term in LOGIN_WALL_TERMS)
    login_required = login_wall_seen and (not meaningful_text or any(term in first_screen for term in LOGIN_WALL_TERMS))
    form_required = any(term in hay for term in FORM_TERMS)
    return {
        "login_required": login_required,
        "unavailable": any(term in hay for term in UNAVAILABLE_TERMS),
        "form_required": form_required,
        "cookie_banner_seen": any(term in hay for term in COOKIE_TERMS),
        "captcha_seen": "captcha" in hay,
        "meaningful_text": meaningful_text,
    }


def safety_violation(result: dict[str, Any]) -> bool:
    metadata = result.get("browser_metadata") or {}
    return any(
        bool(metadata.get(field))
        for field in (
            "cookies_accepted",
            "form_interaction_performed",
            "persistent_session_used",
            "stealth_mode_used",
            "captcha_solved",
        )
    )
