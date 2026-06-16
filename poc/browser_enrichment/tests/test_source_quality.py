import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

from source_quality import attach_source_quality, calculate_completeness_score, calculate_quality_score


def test_quality_score_full_record_reaches_100():
    job = {
        "description": "x" * 800,
        "company": "Acme",
        "salary_text": "GBP 60,000",
        "location": "London",
        "apply_url": "https://reed.co.uk/jobs/1",
        "contract_type": "Permanent",
    }

    assert calculate_completeness_score(job) == 100
    assert calculate_quality_score(job) == 100


def test_quality_score_review_gate_and_apply_decision():
    job = {
        "description": "short",
        "company": "Acme",
        "location": "London",
        "apply_url": "https://reed.co.uk/jobs/1",
    }

    result = attach_source_quality(job)
    assert result["source_quality"]["quality_score"] == 45
    assert result["source_quality"]["completeness_score"] == 45
    assert result["source_quality"]["confidence_score"] == 45
    assert result["source_quality"]["quality_band"] == "review_gated"
    assert result["source_quality"]["analysis_allowed"] is True
    assert result["source_quality"]["apply_decision"] == "review_required"


def test_quality_score_under_40_requires_manual_enrichment():
    result = attach_source_quality({"description": "short", "apply_url": "https://reed.co.uk/jobs/1"})

    assert result["source_quality"]["quality_score"] == 10
    assert result["source_quality"]["completeness_score"] == 10
    assert result["source_quality"]["confidence_score"] == 10
    assert result["source_quality"]["quality_band"] == "skip_manual_enrichment"
    assert result["source_quality"]["analysis_allowed"] is False
    assert result["source_quality"]["apply_decision"] == "manual_enrichment_required"


def test_dry_run_enrichment_caps_confidence_and_forces_review():
    result = attach_source_quality(
        {
            "description": "x" * 800,
            "company": "Acme",
            "salary_text": "GBP 60,000",
            "location": "London",
            "apply_url": "https://reed.co.uk/jobs/1",
            "contract_type": "Permanent",
            "browser_enrichment": {
                "attempted": True,
                "dry_run": True,
                "verified_from_live_page": False,
            },
        }
    )

    assert result["source_quality"]["completeness_score"] == 100
    assert result["source_quality"]["confidence_score"] < 70
    assert result["source_quality"]["quality_score"] < 70
    assert result["source_quality"]["apply_decision"] == "review_required"


def test_live_verified_false_forces_review_even_with_complete_record():
    result = attach_source_quality(
        {
            "description": "x" * 800,
            "company": "Acme",
            "salary_text": "GBP 60,000",
            "location": "London",
            "apply_url": "https://reed.co.uk/jobs/1",
            "contract_type": "Permanent",
            "browser_enrichment": {
                "attempted": True,
                "dry_run": True,
                "verified_from_live_page": False,
                "extraction_confidence": 100,
            },
        }
    )

    assert result["source_quality"]["apply_decision"] == "review_required"
