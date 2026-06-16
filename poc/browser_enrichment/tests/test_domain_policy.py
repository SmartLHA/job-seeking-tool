import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

from browser_enrichment_agent import BrowserEnrichmentAgent
from domain_policy import domain_is_allowed, domain_is_blocked, extract_domain, should_enrich


def test_extract_domain_normalizes_www_and_paths():
    assert extract_domain("https://www.reed.co.uk/jobs/123?x=1") == "reed.co.uk"
    assert extract_domain("jobs.lever.co/example/123") == "jobs.lever.co"


def test_domain_policy_supports_subdomains_without_substring_false_positive():
    assert domain_is_allowed("boards.greenhouse.io", ["greenhouse.io"])
    assert domain_is_blocked("uk.linkedin.com", ["linkedin.com"])
    assert not domain_is_allowed("fakegreenhouse.io", ["greenhouse.io"])
    assert not domain_is_blocked("notlinkedin.com", ["linkedin.com"])


def test_linkedin_blocklisted_before_browser_attempt():
    config = {
        "allowlist": ["linkedin.com", "reed.co.uk"],
        "blocklist": ["linkedin.com"],
        "browser_enrichment_min_quality_trigger": 70,
    }
    job = {
        "source": "manual",
        "external_id": "blocked",
        "title": "Blocked",
        "company": "Blocked Co",
        "location": "London",
        "description": "short",
        "apply_url": "https://www.linkedin.com/jobs/view/123",
    }

    eligible, reason = should_enrich(job, config)
    assert eligible is False
    assert reason == "domain_blocklisted"

    agent = BrowserEnrichmentAgent(config)
    result = agent.enrich_job(job)
    assert result["browser_enrichment"]["attempted"] is False
    assert result["browser_enrichment"]["network_requests_made"] == 0
    assert agent.browser_attempts == []


def test_unknown_domain_is_allowlist_blocked():
    config = {
        "allowlist": ["reed.co.uk"],
        "blocklist": ["linkedin.com", "indeed.com", "glassdoor.com"],
        "browser_enrichment_min_quality_trigger": 70,
    }
    job = {"apply_url": "https://careers.unknown-example.test/jobs/1", "description": "short"}

    assert should_enrich(job, config) == (False, "domain_not_allowlisted")
