import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

from extraction_quality import score_extraction, usefulness


def test_quality_scoring_full_record_reaches_100():
    page = {
        "status": "success",
        "title": "Product",
        "main_content": "Feature content. " * 100,
        "headings": ["Overview"],
        "links": [{"text": "Docs", "url": "https://example.com/docs"}],
        "category": "product_homepage",
        "summary": "Feature content.",
        "feature_signals": ["Feature content"],
        "calls_to_action": [],
        "pricing_signals": [],
        "job_signals": [],
        "company_signals": [],
        "browser_metadata": {"login_required": False, "captcha_seen": False},
    }
    assert score_extraction(page)["quality_score"] == 100


def test_quality_scoring_low_value_record_stays_under_40():
    page = {
        "status": "failed",
        "title": "",
        "main_content": "",
        "headings": [],
        "links": [],
        "category": "unknown",
        "summary": "",
        "feature_signals": [],
        "calls_to_action": [],
        "pricing_signals": [],
        "job_signals": [],
        "company_signals": [],
        "browser_metadata": {"login_required": False, "captcha_seen": False},
    }
    assert score_extraction(page)["quality_score"] < 40


def test_usefulness_scores_by_category():
    assert usefulness({"category": "job_detail"})["for_job_seeking"] == 80
    assert usefulness({"category": "pricing_page"})["for_competitor_research"] == 80
