"""Useful link extraction and classification for public web pages."""

from __future__ import annotations

from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse


LOW_VALUE_TEXT = {
    "",
    "skip to content",
    "menu",
    "close",
    "open menu",
    "facebook",
    "instagram",
    "linkedin",
    "x",
    "youtube",
}

LOW_VALUE_PATH_PARTS = (
    "/privacy",
    "/terms",
    "/legal",
    "/cookies",
    "/cookie",
    "/login",
    "/signin",
    "/sign-in",
)

LOW_VALUE_HOST_PARTS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "youtube.com",
)

CLASSIFIERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pricing", ("pricing", "plans", "enterprise")),
    ("careers", ("careers", "jobs", "open roles", "life at")),
    ("documentation", ("docs", "documentation", "developer", "guide", "reference")),
    ("api", ("api", "sdk", "graphql", "webhook")),
    ("about", ("about", "company", "mission", "team")),
    ("support", ("support", "help", "contact", "sales")),
    ("blog", ("blog", "article", "news", "resources")),
    ("product", ("product", "features", "solutions", "platform", "customers")),
    ("legal", ("privacy", "terms", "legal", "cookie")),
)


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())[:160]


def classify_link(text: str, url: str) -> str:
    hay = f"{text} {urlparse(url).path}".lower()
    for label, terms in CLASSIFIERS:
        if any(term in hay for term in terms):
            return label
    return "other"


def _is_low_value(text: str, url: str, classification: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    host = parsed.netloc.lower()
    query = parsed.query.lower()
    if text.lower() in LOW_VALUE_TEXT and classification == "other":
        return True
    if any(part in host for part in LOW_VALUE_HOST_PARTS):
        return True
    if "share=" in query or "utm_" in query:
        return True
    if text.lower().startswith(("share on ", "opens in new window")):
        return True
    if classification == "legal" and any(part in path for part in LOW_VALUE_PATH_PARTS):
        return True
    if parsed.scheme not in {"http", "https"}:
        return True
    return False


def extract_useful_links(raw_links: list[dict[str, Any]], base_url: str, limit: int = 50) -> list[dict[str, str]]:
    seen: set[str] = set()
    useful: list[dict[str, str]] = []
    overflow: list[dict[str, str]] = []

    for item in raw_links or []:
        text = _clean_text(item.get("text") or item.get("aria_label") or item.get("title"))
        href = item.get("url") or item.get("href")
        if not href:
            continue
        resolved, _fragment = urldefrag(urljoin(base_url, str(href).strip()))
        if resolved in seen:
            continue
        seen.add(resolved)
        classification = classify_link(text, resolved)
        if _is_low_value(text, resolved, classification):
            continue
        record = {"text": text or classification.title(), "url": resolved, "type": classification}
        if classification == "other":
            overflow.append(record)
        else:
            useful.append(record)

    useful.sort(key=lambda item: (item["type"] == "other", item["type"], item["text"].lower()))
    return (useful + overflow)[:limit]
