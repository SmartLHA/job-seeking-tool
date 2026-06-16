import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

from research_summary import RESEARCH_SUMMARY_FIELDS, build_research_summary, write_research_summary


def test_research_summary_schema_and_success_filter(tmp_path):
    pages = [
        {
            "status": "success",
            "url": "https://example.com",
            "domain": "example.com",
            "category": "product_homepage",
            "title": "Example",
            "concise_summary": "Summary",
            "key_claims": ["Claim"],
            "features": ["Feature"],
            "pricing_signals": [],
            "job_career_signals": [],
            "useful_links": [{"text": "Docs", "url": "https://example.com/docs", "type": "documentation"}],
            "extraction_quality": {"confidence_score": 88},
        },
        {"status": "failed", "url": "https://failed.example"},
    ]
    summary = build_research_summary(pages)
    assert len(summary) == 1
    assert set(RESEARCH_SUMMARY_FIELDS) == set(summary[0])
    assert summary[0]["confidence_score"] == 88

    path = tmp_path / "research_summary.json"
    written = write_research_summary(path, pages)
    assert written == summary
    assert path.exists()
