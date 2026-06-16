"""Domain safety gates for the browser enrichment POC."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from source_quality import calculate_quality_score


def extract_domain(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None

    parsed = urlparse(url.strip())
    hostname = parsed.hostname
    if not hostname and parsed.path and "://" not in url:
        hostname = urlparse(f"https://{url.strip()}").hostname
    if not hostname:
        return None

    hostname = hostname.lower().rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def _domain_matches(domain: str | None, policy_domains: list[str]) -> bool:
    if not domain:
        return False

    clean_domain = domain.lower().rstrip(".")
    for policy_domain in policy_domains:
        candidate = policy_domain.lower().strip().rstrip(".")
        if candidate.startswith("www."):
            candidate = candidate[4:]
        if clean_domain == candidate or clean_domain.endswith(f".{candidate}"):
            return True
    return False


def domain_is_blocked(domain: str | None, blocklist: list[str]) -> bool:
    return _domain_matches(domain, blocklist)


def domain_is_allowed(domain: str | None, allowlist: list[str]) -> bool:
    return _domain_matches(domain, allowlist)


def should_enrich(job: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str]:
    """Return whether a job is eligible before any browser/fetch work is attempted."""
    domain = extract_domain(job.get("apply_url"))
    if not domain:
        return False, "missing_or_invalid_apply_url"

    if domain_is_blocked(domain, config.get("blocklist", [])):
        return False, "domain_blocklisted"

    if not domain_is_allowed(domain, config.get("allowlist", [])):
        return False, "domain_not_allowlisted"

    score = calculate_quality_score(job)
    trigger = int(config.get("browser_enrichment_min_quality_trigger", 70))
    if score >= trigger:
        return False, "quality_sufficient"

    return True, "eligible_for_dry_run_enrichment"
