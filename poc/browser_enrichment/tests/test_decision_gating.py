import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

from browser_enrichment_agent import BrowserEnrichmentAgent


CONFIG = {
    "browser_enrichment_provider": "browse_cli",
    "browser_enrichment_min_quality_trigger": 70,
    "browser_enrichment_save_screenshot": True,
    "browser_enrichment_save_snapshot": True,
    "allowlist": ["reed.co.uk", "adzuna.co.uk", "greenhouse.io", "lever.co"],
    "blocklist": ["linkedin.com", "indeed.com", "glassdoor.com"],
}


def test_full_quality_job_is_skipped():
    job = {
        "source": "reed",
        "external_id": "full",
        "title": "Full",
        "company": "Acme",
        "location": "London",
        "salary_text": "GBP 65,000",
        "contract_type": "Permanent",
        "description": "x" * 800,
        "apply_url": "https://reed.co.uk/jobs/1",
    }

    result = BrowserEnrichmentAgent(CONFIG).enrich_job(job)

    assert result["source_quality"]["quality_score"] == 100
    assert result["browser_enrichment"]["attempted"] is False
    assert result["browser_enrichment"]["reason"] == "quality_sufficient"


def test_low_quality_allowlisted_job_is_enriched_but_apply_review_required_in_dry_run():
    job = {
        "source": "reed",
        "external_id": "short",
        "title": "Short",
        "company": "Acme",
        "location": "London",
        "description": "short",
        "apply_url": "https://reed.co.uk/jobs/2",
    }

    result = BrowserEnrichmentAgent(CONFIG).enrich_job(job)

    assert result["browser_enrichment"]["attempted"] is True
    assert result["browser_enrichment"]["status"] == "success"
    assert result["source_quality"]["completeness_score"] >= 70
    assert result["source_quality"]["confidence_score"] < 70
    assert result["source_quality"]["apply_decision"] == "review_required"
    assert result["browser_enrichment"]["manual_review_required"] is True
    assert "dry_run_not_verified" in result["browser_enrichment"]["reason"]
    assert result["browser_enrichment"]["screenshot_path"] == "output/screenshots/short.png"
    assert result["browser_enrichment"]["snapshot_path"] == "output/snapshots/short.html"


def test_screenshot_and_snapshot_paths_only_set_when_configured():
    config = {
        **CONFIG,
        "browser_enrichment_save_screenshot": False,
        "browser_enrichment_save_snapshot": False,
    }
    job = {
        "source": "reed",
        "external_id": "no-artifacts",
        "title": "Short",
        "company": "Acme",
        "location": "London",
        "description": "short",
        "apply_url": "https://reed.co.uk/jobs/3",
    }

    result = BrowserEnrichmentAgent(config).enrich_job(job)

    assert result["browser_enrichment"]["status"] == "success"
    assert "screenshot_path" not in result["browser_enrichment"]
    assert "snapshot_path" not in result["browser_enrichment"]


def test_failure_is_isolated_during_full_run():
    jobs = [
        {
            "source": "reed",
            "external_id": "will-fail",
            "title": "Will Fail",
            "company": "Acme",
            "location": "London",
            "description": "short",
            "apply_url": "https://reed.co.uk/jobs/fail",
            "simulate_failure": True,
        },
        {
            "source": "lever",
            "external_id": "will-pass",
            "title": "Will Pass",
            "company": "",
            "location": "",
            "description": "short",
            "apply_url": "https://jobs.lever.co/example/pass",
        },
    ]

    results = BrowserEnrichmentAgent(CONFIG).enrich_jobs(jobs)

    assert len(results) == 2
    assert results[0]["browser_enrichment"]["status"] == "failed"
    assert "extraction_failed" in results[0]["browser_enrichment"]["reason"]
    assert results[1]["browser_enrichment"]["status"] == "success"


def test_linkedin_failure_case_does_not_create_browser_attempt():
    job = {
        "source": "manual",
        "external_id": "linkedin",
        "title": "Blocked",
        "company": "Blocked",
        "location": "London",
        "description": "short",
        "apply_url": "https://linkedin.com/jobs/view/1",
    }
    agent = BrowserEnrichmentAgent(CONFIG)

    result = agent.enrich_job(job)

    assert result["browser_enrichment"]["reason"] == "domain_blocklisted"
    assert result["browser_enrichment"]["attempted"] is False
    assert result["browser_enrichment"]["network_requests_made"] == 0
    assert agent.browser_attempts == []


def test_allowlisted_extraction_failed_forces_manual_review_without_stopping():
    jobs = [
        {
            "source": "manual",
            "external_id": "failed",
            "title": "Failed",
            "company": "",
            "location": "",
            "description": "short",
            "apply_url": "https://boards.greenhouse.io/example/jobs/1",
            "simulate_extraction_failed": True,
        },
        {
            "source": "manual",
            "external_id": "passing",
            "title": "Passing",
            "company": "",
            "location": "",
            "description": "short",
            "apply_url": "https://jobs.lever.co/example/2",
        },
    ]

    results = BrowserEnrichmentAgent(CONFIG).enrich_jobs(jobs)

    assert results[0]["browser_enrichment"]["status"] == "failed"
    assert "extraction_failed" in results[0]["browser_enrichment"]["reason"]
    assert results[0]["browser_enrichment"]["manual_review_required"] is True
    assert results[0]["source_quality"]["apply_decision"] == "review_required"
    assert results[1]["browser_enrichment"]["status"] == "success"


def test_login_required_page_becomes_manual_review():
    job = {
        "source": "manual",
        "external_id": "login",
        "title": "Login",
        "company": "",
        "location": "",
        "description": "short",
        "apply_url": "https://jobs.lever.co/example/login",
        "simulate_login_required": True,
    }

    result = BrowserEnrichmentAgent(CONFIG).enrich_job(job)

    assert result["browser_enrichment"]["status"] == "failed"
    assert "login_required" in result["browser_enrichment"]["reason"]
    assert result["browser_enrichment"]["manual_review_required"] is True
    assert result["browser_enrichment"]["network_requests_made"] == 0
    assert result["source_quality"]["apply_decision"] == "review_required"
