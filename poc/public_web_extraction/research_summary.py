"""Build compact research_summary.json artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RESEARCH_SUMMARY_FIELDS = (
    "url",
    "domain",
    "category",
    "title",
    "concise_summary",
    "key_claims",
    "features",
    "pricing_signals",
    "job_career_signals",
    "useful_links",
    "confidence_score",
)


def page_to_summary(page: dict[str, Any]) -> dict[str, Any]:
    quality = page.get("extraction_quality") or {}
    return {
        "url": page.get("url"),
        "domain": page.get("domain"),
        "category": page.get("category"),
        "title": page.get("title"),
        "concise_summary": page.get("concise_summary") or page.get("summary"),
        "key_claims": page.get("key_claims") or [],
        "features": page.get("features") or [],
        "pricing_signals": page.get("pricing_signals") or [],
        "job_career_signals": page.get("job_career_signals") or [],
        "useful_links": page.get("useful_links") or page.get("links") or [],
        "confidence_score": quality.get("confidence_score", 0),
    }


def build_research_summary(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [page_to_summary(page) for page in pages if page.get("status") == "success"]


def write_research_summary(path: Path, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = build_research_summary(pages)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary
