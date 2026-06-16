"""Category-specific deterministic extraction profiles."""

from __future__ import annotations

import re
from typing import Any


PROFILE_CATEGORIES = {
    "product_homepage",
    "pricing_page",
    "blog_article",
    "careers_landing",
    "company_about",
    "documentation",
}

PATTERNS = {
    "key_claims": (
        "trusted",
        "leading",
        "all-in-one",
        "fastest",
        "secure",
        "scalable",
        "reliable",
        "ai",
        "automation",
    ),
    "features": (
        "feature",
        "workflow",
        "dashboard",
        "integration",
        "template",
        "analytics",
        "collaboration",
        "api",
        "automation",
        "security",
    ),
    "pricing_signals": (
        "pricing",
        "free",
        "trial",
        "enterprise",
        "per month",
        "per user",
        "$",
        "£",
        "plan",
    ),
    "job_career_signals": (
        "career",
        "job",
        "role",
        "open position",
        "benefit",
        "team",
        "remote",
        "location",
        "department",
    ),
}

CATEGORY_HINTS = {
    "product_homepage": ("feature", "platform", "workflow", "solution", "customer"),
    "pricing_page": ("pricing", "free", "enterprise", "plan", "per user"),
    "blog_article": ("published", "author", "read", "article", "learn"),
    "careers_landing": ("career", "job", "role", "benefit", "open position"),
    "company_about": ("mission", "company", "team", "founded", "customers"),
    "documentation": ("docs", "guide", "api", "reference", "install"),
}


def _sentences(text: str) -> list[str]:
    values = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [" ".join(value.split()) for value in values if len(value.split()) >= 4]


def find_matches(text: str, patterns: tuple[str, ...], limit: int = 8) -> list[str]:
    found: list[str] = []
    for sentence in _sentences(text):
        low = sentence.lower()
        if any(pattern in low for pattern in patterns) and sentence not in found:
            found.append(sentence[:220])
        if len(found) >= limit:
            break
    return found


def concise_summary(text: str, title: str | None = None, max_chars: int = 360) -> str:
    for sentence in _sentences(text):
        if title and sentence.lower() == title.lower():
            continue
        return sentence[:max_chars].rstrip()
    fallback = " ".join((text or "").split())
    return fallback[:max_chars].rstrip()


def extract_profile(category: str, text: str, links: list[dict[str, Any]], title: str | None = None) -> dict[str, Any]:
    effective_category = category if category in PROFILE_CATEGORIES else "product_homepage"
    link_types = {link.get("type") for link in links or []}
    category_hints = CATEGORY_HINTS.get(effective_category, ())
    category_signal_count = sum(1 for term in category_hints if term in (text or "").lower())

    profile = {
        "profile": effective_category,
        "concise_summary": concise_summary(text, title),
        "key_claims": find_matches(text, PATTERNS["key_claims"]),
        "features": find_matches(text, PATTERNS["features"]),
        "pricing_signals": find_matches(text, PATTERNS["pricing_signals"]),
        "job_career_signals": find_matches(text, PATTERNS["job_career_signals"]),
        "confidence_hints": {
            "category_signal_count": category_signal_count,
            "useful_link_types": sorted(value for value in link_types if value),
        },
    }

    if effective_category == "pricing_page" and not profile["pricing_signals"]:
        profile["pricing_signals"] = [link["text"] for link in links if link.get("type") == "pricing"][:5]
    if effective_category == "careers_landing" and not profile["job_career_signals"]:
        profile["job_career_signals"] = [link["text"] for link in links if link.get("type") == "careers"][:5]
    if effective_category == "documentation" and not profile["features"]:
        profile["features"] = [link["text"] for link in links if link.get("type") in {"documentation", "api"}][:5]
    return profile
