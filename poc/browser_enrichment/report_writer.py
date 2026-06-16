"""Report writer for browser enrichment dry-run output."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any


def summarize_jobs(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter((job.get("browser_enrichment") or {}).get("status", "missing") for job in jobs)
    reasons = Counter((job.get("browser_enrichment") or {}).get("reason", "missing") for job in jobs)
    before_scores = [
        int((job.get("browser_enrichment") or {}).get("quality_before", (job.get("source_quality") or {}).get("quality_score", 0)))
        for job in jobs
    ]
    after_scores = [int((job.get("source_quality") or {}).get("completeness_score", 0)) for job in jobs]
    dry_run_promoted_to_apply = sum(
        1
        for job in jobs
        if (job.get("browser_enrichment") or {}).get("dry_run") is True
        and (job.get("browser_enrichment") or {}).get("attempted") is True
        and (job.get("source_quality") or {}).get("apply_decision") == "allowed"
    )
    safety_violations = dry_run_promoted_to_apply + sum(
        1
        for job in jobs
        if (job.get("browser_enrichment") or {}).get("reason") in {"domain_blocklisted", "domain_not_allowlisted"}
        and int((job.get("browser_enrichment") or {}).get("network_requests_made", 0)) != 0
    )
    live_verified_records = sum(
        1 for job in jobs if (job.get("browser_enrichment") or {}).get("verified_from_live_page") is True
    )
    login_required_count = sum(
        1 for job in jobs if "login_required" in str((job.get("browser_enrichment") or {}).get("reason", ""))
    )
    extraction_failed_count = sum(
        1 for job in jobs if "extraction_failed" in str((job.get("browser_enrichment") or {}).get("reason", ""))
    )
    recommendation = "GO"
    if safety_violations:
        recommendation = "STOP"
    elif dry_run_promoted_to_apply or live_verified_records:
        recommendation = "REVISE"
    return {
        "total_jobs": len(jobs),
        "status_counts": dict(sorted(statuses.items())),
        "reason_counts": dict(sorted(reasons.items())),
        "browser_attempts": sum(
            1 for job in jobs if (job.get("browser_enrichment") or {}).get("attempted") is True
        ),
        "network_requests_made": sum(
            int((job.get("browser_enrichment") or {}).get("network_requests_made", 0)) for job in jobs
        ),
        "average_quality_before": round(sum(before_scores) / len(before_scores), 2) if before_scores else 0,
        "average_quality_after": round(sum(after_scores) / len(after_scores), 2) if after_scores else 0,
        "average_uplift": round((sum(after_scores) - sum(before_scores)) / len(after_scores), 2)
        if after_scores
        else 0,
        "dry_run_records_promoted_to_apply": dry_run_promoted_to_apply,
        "live_verified_records": live_verified_records,
        "login_required_count": login_required_count,
        "extraction_failed_count": extraction_failed_count,
        "safety_violations_count": safety_violations,
        "final_recommendation": recommendation,
    }


def write_report(jobs: list[dict[str, Any]], output_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    summary = summarize_jobs(jobs)
    lines = [
        "# Browser Enrichment POC Report",
        "",
        "## Safety Mode",
        "",
        "- Mode: dry-run simulation only",
        "- Actual browser automation: not run",
        "- Network requests made: 0",
        "- Auto-apply / CV upload / form submission: disabled",
        "- LinkedIn, Indeed, and Glassdoor: blocklisted",
        "",
        "## Summary",
        "",
        f"- Total jobs: {summary['total_jobs']}",
        f"- Browser attempts simulated: {summary['browser_attempts']}",
        f"- Network requests made: {summary['network_requests_made']}",
        f"- Quality trigger: below {config.get('browser_enrichment_min_quality_trigger', 70)}",
        f"- Average quality before: {summary['average_quality_before']}",
        f"- Average quality after: {summary['average_quality_after']}",
        f"- Average uplift: {summary['average_uplift']}",
        f"- Dry-run records promoted to Apply: {summary['dry_run_records_promoted_to_apply']}",
        f"- Live verified records: {summary['live_verified_records']}",
        f"- Login-required count: {summary['login_required_count']}",
        f"- Extraction-failed count: {summary['extraction_failed_count']}",
        f"- Safety violations count: {summary['safety_violations_count']}",
        f"- Final recommendation: {summary['final_recommendation']}",
        "",
        "This run proves control flow only, not real extraction quality.",
        "",
        "## Status Counts",
        "",
    ]
    for status, count in summary["status_counts"].items():
        lines.append(f"- {status}: {count}")

    lines.extend(["", "## Reason Counts", ""])
    for reason, count in summary["reason_counts"].items():
        lines.append(f"- {reason}: {count}")

    lines.extend(["", "## Job Results", ""])
    for job in jobs:
        enrichment = job.get("browser_enrichment") or {}
        quality = job.get("source_quality") or {}
        lines.append(
            "- {external_id} | {source} | {status} | {reason} | completeness {completeness} | confidence {confidence} | quality {score} | apply {apply_decision}".format(
                external_id=job.get("external_id"),
                source=job.get("source"),
                status=enrichment.get("status"),
                reason=enrichment.get("reason"),
                completeness=quality.get("completeness_score"),
                confidence=quality.get("confidence_score"),
                score=quality.get("quality_score"),
                apply_decision=quality.get("apply_decision"),
            )
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
