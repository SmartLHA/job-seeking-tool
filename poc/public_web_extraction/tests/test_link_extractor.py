import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

from link_extractor import extract_useful_links


def test_useful_links_are_retained_and_classified():
    links = extract_useful_links(
        [
            {"text": "Pricing", "href": "/pricing"},
            {"text": "", "href": "/pricing/enterprise"},
            {"text": "Developer docs", "href": "https://example.com/docs"},
            {"text": "Careers", "href": "/careers"},
        ],
        "https://example.com/product",
    )
    assert {item["type"] for item in links} >= {"pricing", "documentation", "careers"}
    assert any(item["text"] == "Pricing" for item in links)
    assert any(item["text"] == "Pricing" for item in links if item["url"].endswith("/pricing/enterprise"))
    assert links[0]["url"].startswith("https://example.com/")


def test_duplicate_unsafe_and_low_value_links_are_removed():
    links = extract_useful_links(
        [
            {"text": "Pricing", "href": "/pricing#plans"},
            {"text": "Pricing", "href": "/pricing#faq"},
            {"text": "Email", "href": "mailto:test@example.com"},
            {"text": "Skip to content", "href": "#main"},
            {"text": "Privacy", "href": "/privacy"},
            {"text": "Share on LinkedIn", "href": "/post?share=linkedin"},
        ],
        "https://example.com/",
    )
    assert links == [{"text": "Pricing", "url": "https://example.com/pricing", "type": "pricing"}]
