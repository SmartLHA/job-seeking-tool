import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

from extraction_profiles import extract_profile


def test_pricing_profile_extracts_pricing_signals():
    profile = extract_profile(
        "pricing_page",
        "Pricing plans include a free trial. Enterprise customers can contact sales. Plans are billed per user.",
        [{"text": "Enterprise pricing", "url": "https://example.com/pricing", "type": "pricing"}],
        "Pricing",
    )
    assert profile["profile"] == "pricing_page"
    assert profile["pricing_signals"]


def test_careers_profile_extracts_job_signals():
    profile = extract_profile(
        "careers_landing",
        "Explore careers and open positions. Remote roles include benefits and team events.",
        [{"text": "Open roles", "url": "https://example.com/careers", "type": "careers"}],
        "Careers",
    )
    assert profile["job_career_signals"]


def test_documentation_profile_uses_docs_links_as_features():
    profile = extract_profile(
        "documentation",
        "Start with the install guide.",
        [{"text": "API reference", "url": "https://example.com/docs/api", "type": "api"}],
        "Docs",
    )
    assert "API reference" in profile["features"]
