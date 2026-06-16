import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

import run_live_extraction
from domain_policy import safety_violation
from report_writer import recommendation_for


def test_max_pages_per_run_enforcement(monkeypatch, tmp_path):
    config = {"max_pages_per_run": 2, "candidate_url_only_mode": True, "blocklist": []}
    candidates = [
        {"url": "https://example.com/1", "category": "product_homepage"},
        {"url": "https://example.com/2", "category": "pricing_page"},
        {"url": "https://example.com/3", "category": "documentation"},
    ]
    preflight = {
        "results": [
            {"url": "https://example.com/1", "status": "passed"},
            {"url": "https://example.com/2", "status": "passed"},
            {"url": "https://example.com/3", "status": "passed"},
        ]
    }
    extracted = []

    monkeypatch.setattr(run_live_extraction, "load_json", lambda path: config if path.name == "config.example.json" else candidates)
    monkeypatch.setattr(run_live_extraction, "load_preflight", lambda: preflight)
    monkeypatch.setattr(run_live_extraction, "BASE_DIR", tmp_path)

    def fake_extract(candidate, config, index):
        extracted.append(candidate["url"])
        page = {
            "url": candidate["url"],
            "domain": "example.com",
            "category": candidate["category"],
            "status": "success",
            "reason": None,
            "title": "Title",
            "meta_description": None,
            "main_content": "Content. " * 200,
            "summary": "Content.",
            "headings": ["Title"],
            "links": [{"text": "A", "url": "https://example.com"}],
            "calls_to_action": [],
            "pricing_signals": [],
            "feature_signals": ["Feature"],
            "job_signals": [],
            "company_signals": [],
            "date_published": None,
            "author": None,
            "content_usefulness": {
                "for_job_seeking": 0,
                "for_competitor_research": 80,
                "for_market_research": 0,
                "for_product_design": 80,
            },
            "extraction_quality": {
                "content_length": 1600,
                "has_title": True,
                "has_headings": True,
                "has_main_content": True,
                "has_links": True,
                "quality_score": 90,
                "confidence_score": 90,
            },
            "browser_metadata": {
                "verified_from_live_page": True,
                "network_requests_made": 1,
                "screenshot_path": None,
                "snapshot_path": None,
                "cookie_banner_seen": False,
                "cookies_accepted": False,
                "login_required": False,
                "forms_present": False,
                "form_submission_required_to_view_content": False,
                "form_interaction_performed": False,
                "persistent_session_used": False,
                "stealth_mode_used": False,
                "captcha_seen": False,
                "captcha_solved": False,
            },
        }
        return page, ["fake browse open"]

    monkeypatch.setattr(run_live_extraction, "extract_with_browse", fake_extract)
    monkeypatch.setattr(run_live_extraction, "write_report", lambda *args, **kwargs: {"recommendation": "REVISE"})
    run_live_extraction.run()
    assert extracted == ["https://example.com/1", "https://example.com/2"]


def test_safety_violation_triggers_stop():
    page = {
        "status": "success",
        "extraction_quality": {"quality_score": 100},
        "browser_metadata": {"cookies_accepted": True},
    }
    assert safety_violation(page)
    assert recommendation_for([page], safety_violations_count=1) == "STOP"
