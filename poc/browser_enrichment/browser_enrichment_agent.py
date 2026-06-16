"""Dry-run Browserbase/browse.sh enrichment agent.

This POC deliberately performs no browser automation and no network requests.
The policy gate is evaluated before the dry-run extraction hook is called.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from domain_policy import extract_domain, should_enrich
from source_quality import attach_source_quality, calculate_completeness_score


class BrowserEnrichmentAgent:
    def __init__(self, config: dict[str, Any], base_dir: Path | None = None):
        self.config = config
        self.base_dir = base_dir or Path(__file__).resolve().parent
        self.browser_attempts: list[str] = []

    def enrich_jobs(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched_jobs = []
        for job in jobs:
            try:
                enriched_jobs.append(self.enrich_job(job))
            except Exception as exc:  # failure isolation is a POC requirement
                failed = attach_source_quality(job)
                failed["browser_enrichment"] = {
                    "attempted": True,
                    "status": "failed",
                    "reason": "extraction_failed;dry_run_not_verified",
                    "error": str(exc),
                    "dry_run": True,
                    "verified_from_live_page": False,
                    "extraction_confidence": 0,
                    "raw_page_fetched": False,
                    "network_requests_made": 0,
                    "manual_review_required": True,
                }
                failed = attach_source_quality(failed)
                enriched_jobs.append(failed)
        return enriched_jobs

    def enrich_job(self, job: dict[str, Any]) -> dict[str, Any]:
        current = attach_source_quality(job)
        eligible, reason = should_enrich(current, self.config)
        domain = extract_domain(current.get("apply_url"))

        if not eligible:
            current["browser_enrichment"] = {
                "attempted": False,
                "status": "skipped",
                "reason": reason,
                "domain": domain,
                "dry_run": True,
                "verified_from_live_page": False,
                "extraction_confidence": 0,
                "raw_page_fetched": False,
                "network_requests_made": 0,
                "manual_review_required": reason != "quality_sufficient",
            }
            return current

        if not self.config.get("browser_enrichment_enabled", True):
            current["browser_enrichment"] = {
                "attempted": False,
                "status": "skipped",
                "reason": "enrichment_disabled",
                "domain": domain,
                "dry_run": True,
                "verified_from_live_page": False,
                "extraction_confidence": 0,
                "raw_page_fetched": False,
                "network_requests_made": 0,
                "manual_review_required": True,
            }
            return current

        if not self.config.get("browser_enrichment_dry_run", True):
            current["browser_enrichment"] = {
                "attempted": False,
                "status": "skipped",
                "reason": "dry_run_required",
                "domain": domain,
                "dry_run": True,
                "verified_from_live_page": False,
                "extraction_confidence": 0,
                "raw_page_fetched": False,
                "network_requests_made": 0,
                "manual_review_required": True,
            }
            return current

        before_score = calculate_completeness_score(current)
        extracted = self._simulate_browser_extraction(current)
        extracted_status = extracted.pop("status", "success")
        reason_suffix = extracted.pop("reason", "dry_run_not_verified")
        updated = deepcopy(current)
        fields_improved = []

        for field, value in extracted.items():
            if field in {"screenshot_path", "snapshot_path"}:
                continue
            if value and not updated.get(field):
                updated[field] = value
                fields_improved.append(field)
            elif field == "description" and len(str(value)) > len(str(updated.get(field) or "")):
                updated[field] = value
                fields_improved.append(field)

        metadata = {
            "attempted": True,
            "status": extracted_status,
            "reason": f"{reason};{reason_suffix}",
            "domain": domain,
            "provider": self.config.get("browser_enrichment_provider", "browse_cli"),
            "dry_run": True,
            "verified_from_live_page": False,
            "extraction_confidence": 25 if extracted_status == "success" else 0,
            "raw_page_fetched": False,
            "network_requests_made": 0,
            "manual_review_required": True,
            "quality_before": before_score,
            "fields_improved": sorted(set(fields_improved)),
        }
        if self.config.get("browser_enrichment_save_screenshot", False) and extracted.get("screenshot_path"):
            metadata["screenshot_path"] = extracted["screenshot_path"]
        if self.config.get("browser_enrichment_save_snapshot", False) and extracted.get("snapshot_path"):
            metadata["snapshot_path"] = extracted["snapshot_path"]
        updated["browser_enrichment"] = metadata
        updated = attach_source_quality(updated)
        updated["browser_enrichment"]["quality_after"] = updated["source_quality"]["completeness_score"]
        return updated

    def _simulate_browser_extraction(self, job: dict[str, Any]) -> dict[str, Any]:
        """Local deterministic extraction stub. No browser/fetch call is made here."""
        external_id = str(job.get("external_id") or "unknown")
        if job.get("simulate_login_required"):
            return {
                "status": "failed",
                "reason": "login_required;dry_run_not_verified",
            }
        if job.get("simulate_extraction_failed"):
            return {
                "status": "failed",
                "reason": "extraction_failed;dry_run_not_verified",
            }
        if job.get("simulate_failure"):
            raise RuntimeError("simulated dry-run extraction failure")

        self.browser_attempts.append(external_id)
        title = job.get("title") or "Role"
        company = job.get("company") or "Hiring company"
        location = job.get("location") or "United Kingdom"
        description = (
            f"{title} at {company} is a dry-run enriched public job record for {location}. "
            "This simulated description stands in for content that a future approved "
            "browser enrichment pass might extract from an allowlisted public job page. "
            "It includes responsibilities, impact, collaboration expectations, delivery "
            "context, stakeholder communication, tooling, measurable outcomes, and review "
            "notes without contacting the target website. "
        ) * 5

        return {
            "description": description,
            "company": company,
            "location": location,
            "salary_text": job.get("salary_text") or "Salary not disclosed",
            "contract_type": job.get("contract_type") or job.get("job_type") or "Permanent",
            "screenshot_path": f"output/screenshots/{external_id}.png",
            "snapshot_path": f"output/snapshots/{external_id}.html",
        }
