"""Markdown reporting for the public web extraction POC."""

from __future__ import annotations

from statistics import mean
from typing import Any

from domain_policy import safety_violation


def recommendation_for(pages: list[dict[str, Any]], safety_violations_count: int) -> str:
    successes = [page for page in pages if page.get("status") == "success"]
    avg_quality = mean([(page.get("extraction_quality") or {}).get("quality_score", 0) for page in pages]) if pages else 0
    if safety_violations_count > 0 or not successes:
        return "STOP"
    if len(successes) >= 5 and avg_quality >= 70:
        return "GO"
    return "REVISE"


def summarize(pages: list[dict[str, Any]], total_candidates: int, preflight_passed_count: int) -> dict[str, Any]:
    attempted = len(pages)
    success_count = sum(1 for page in pages if page.get("status") == "success")
    failed_count = sum(1 for page in pages if page.get("status") == "failed")
    skipped_count = sum(1 for page in pages if page.get("status") == "skipped")
    quality_scores = [page["extraction_quality"]["quality_score"] for page in pages]
    confidence_scores = [page["extraction_quality"]["confidence_score"] for page in pages]
    safety_violations_count = sum(1 for page in pages if safety_violation(page))
    categories = sorted({page.get("category", "unknown") for page in pages})
    usefulness_by_category: dict[str, dict[str, float]] = {}
    for category in categories:
        category_pages = [page for page in pages if page.get("category") == category]
        if not category_pages:
            continue
        usefulness_by_category[category] = {
            key: round(mean([page["content_usefulness"][key] for page in category_pages]), 1)
            for key in (
                "for_job_seeking",
                "for_competitor_research",
                "for_market_research",
                "for_product_design",
            )
        }

    return {
        "total_candidate_pages": total_candidates,
        "preflight_passed_count": preflight_passed_count,
        "extraction_attempted_count": attempted,
        "extraction_success_count": success_count,
        "extraction_failed_count": failed_count,
        "extraction_skipped_count": skipped_count,
        "average_quality_score": round(mean(quality_scores), 1) if quality_scores else 0,
        "average_confidence_score": round(mean(confidence_scores), 1) if confidence_scores else 0,
        "page_categories_tested": categories,
        "usefulness_by_category": usefulness_by_category,
        "pages_with_screenshots": [page["url"] for page in pages if page["browser_metadata"].get("screenshot_path")],
        "pages_with_snapshots": [page["url"] for page in pages if page["browser_metadata"].get("snapshot_path")],
        "cookie_banners_seen_count": sum(1 for page in pages if page["browser_metadata"].get("cookie_banner_seen")),
        "login_required_count": sum(1 for page in pages if page["browser_metadata"].get("login_required")),
        "captcha_seen_count": sum(1 for page in pages if page["browser_metadata"].get("captcha_seen")),
        "safety_violations_count": safety_violations_count,
        "recommendation": recommendation_for(pages, safety_violations_count),
    }


def write_report(
    path,
    pages: list[dict[str, Any]],
    total_candidates: int,
    preflight_passed_count: int,
    commands_used: list[str],
    markdown_paths: list[str] | None = None,
    research_summary_count: int | None = None,
) -> dict[str, Any]:
    summary = summarize(pages, total_candidates, preflight_passed_count)
    lines = [
        "# Public Web Extraction POC v2 Report",
        "",
        "## Summary",
        f"- Total candidate pages: {summary['total_candidate_pages']}",
        f"- Preflight passed count: {summary['preflight_passed_count']}",
        f"- Extraction attempted count: {summary['extraction_attempted_count']}",
        f"- Extraction success count: {summary['extraction_success_count']}",
        f"- Extraction failed count: {summary['extraction_failed_count']}",
        f"- Extraction skipped count: {summary['extraction_skipped_count']}",
        f"- Average quality score: {summary['average_quality_score']}",
        f"- Average confidence score: {summary['average_confidence_score']}",
        f"- Page categories tested: {', '.join(summary['page_categories_tested'])}",
        f"- Cookie banners seen count: {summary['cookie_banners_seen_count']}",
        f"- Login required count: {summary['login_required_count']}",
        f"- Captcha seen count: {summary['captcha_seen_count']}",
        f"- Safety violations count: {summary['safety_violations_count']}",
        f"- Research summary entries: {research_summary_count if research_summary_count is not None else 'not written'}",
        f"- Markdown exports: {len(markdown_paths or [])}",
        f"- Recommendation: {summary['recommendation']}",
        "",
        "## Safety Model",
        "- Public pages were opened for observation and extraction only.",
        "- Cookie banners may be observed but are not clicked.",
        "- No login, form submission, file upload, cookie acceptance, persistent session, stealth mode, CAPTCHA solving, auto-apply, purchase, subscription, message, follow, like, comment, booking, or account action is allowed.",
        "- Only URLs explicitly listed in candidate_pages.json are eligible.",
        "",
        "## Pages",
    ]
    for page in pages:
        quality = page["extraction_quality"]
        meta = page["browser_metadata"]
        lines.extend(
            [
                f"### {page['category']} — {page['domain']}",
                f"- URL: {page['url']}",
                f"- Status: {page['status']}",
                f"- Reason: {page['reason'] or 'none'}",
                f"- Title: {page['title'] or 'none'}",
                f"- Concise summary: {page.get('concise_summary') or page.get('summary') or 'none'}",
                f"- Content length: {quality['content_length']}",
                f"- Quality/confidence: {quality['quality_score']} / {quality['confidence_score']}",
                f"- Useful links captured: {len(page.get('useful_links') or page.get('links') or [])}",
                f"- Key claims: {len(page.get('key_claims') or [])}",
                f"- Features: {len(page.get('features') or [])}",
                f"- Screenshot: {meta.get('screenshot_path') or 'none'}",
                f"- Snapshot: {meta.get('snapshot_path') or 'none'}",
                f"- Cookie banner seen: {meta.get('cookie_banner_seen')}",
                f"- Login required: {meta.get('login_required')}",
                f"- Captcha seen: {meta.get('captcha_seen')}",
                "",
            ]
        )

    lines.extend(["## Usefulness By Category"])
    for category, scores in summary["usefulness_by_category"].items():
        lines.append(f"- {category}: {scores}")

    lines.extend(["", "## Markdown Exports"])
    for markdown_path in markdown_paths or []:
        lines.append(f"- `{markdown_path}`")

    lines.extend(["", "## Commands Used"])
    for command in commands_used:
        lines.append(f"- `{command}`")

    lines.extend(["", "## Recommendation", f"- {summary['recommendation']}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
