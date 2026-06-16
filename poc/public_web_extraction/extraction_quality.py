"""Deterministic scoring for public web extraction results."""

from __future__ import annotations

from typing import Any


def useful_signal_count(page: dict[str, Any]) -> int:
    return sum(
        len(page.get(name) or [])
        for name in ("calls_to_action", "pricing_signals", "feature_signals", "job_signals", "company_signals")
    )


def score_extraction(page: dict[str, Any]) -> dict[str, Any]:
    title = page.get("title")
    main_content = page.get("main_content") or ""
    headings = page.get("headings") or []
    links = page.get("links") or []
    category = page.get("category")
    summary = page.get("summary") or ""

    score = 0
    if title:
        score += 20
    if len(main_content) >= 1000:
        score += 20
    if headings:
        score += 15
    if links:
        score += 15
    if category and category != "unknown":
        score += 10
    if useful_signal_count(page) > 0:
        score += 10
    if summary and summary in main_content[: max(len(main_content), 1)] or summary:
        score += 10

    confidence = score
    metadata = page.get("browser_metadata") or {}
    if metadata.get("login_required") or metadata.get("captcha_seen"):
        confidence = min(confidence, 35)
    if page.get("status") != "success":
        confidence = min(confidence, 30)

    return {
        "content_length": len(main_content),
        "has_title": bool(title),
        "has_headings": bool(headings),
        "has_main_content": bool(main_content),
        "has_links": bool(links),
        "quality_score": min(score, 100),
        "confidence_score": min(confidence, 100),
    }


def usefulness(page: dict[str, Any]) -> dict[str, int]:
    category = page.get("category")
    scores = {
        "for_job_seeking": 0,
        "for_competitor_research": 0,
        "for_market_research": 0,
        "for_product_design": 0,
    }
    if category in {"careers_landing", "job_detail", "job_search_results", "company_about"}:
        scores["for_job_seeking"] = 80
    if category in {"product_homepage", "pricing_page", "company_about", "directory_listing"}:
        scores["for_competitor_research"] = 80
    if category in {"blog_article", "news_article", "directory_listing", "company_about"}:
        scores["for_market_research"] = 75
    if category in {"product_homepage", "pricing_page", "documentation", "api_docs"}:
        scores["for_product_design"] = 80
    return scores
