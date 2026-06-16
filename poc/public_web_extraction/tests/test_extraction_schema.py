import json
import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

from content_extractor import build_page_record, parse_snapshot_output


def test_output_schema_validation():
    expected = json.loads((POC_DIR / "expected_schema.json").read_text())
    candidate = {"url": "https://example.com/product", "category": "product_homepage"}
    page_data = {
        "title": "Example",
        "h1": "Example",
        "meta_description": "Example product",
        "text": "Example product content. " * 80,
        "headings": ["Example", "Features"],
        "links": [{"text": "Docs", "url": "https://example.com/docs"}],
        "buttons": ["Get started"],
        "json_ld": [],
    }
    record = build_page_record(
        candidate,
        page_data,
        status="success",
        reason=None,
        screenshot_path="output/screenshots/example.png",
        snapshot_path="output/snapshots/example.txt",
        network_requests_made=3,
    )
    for field in expected["required_top_level_fields"]:
        assert field in record
    for field in expected["content_usefulness_fields"]:
        assert field in record["content_usefulness"]
    for field in expected["extraction_quality_fields"]:
        assert field in record["extraction_quality"]
    for field in expected["browser_metadata_fields"]:
        assert field in record["browser_metadata"]


def test_cookie_banner_seen_is_recorded_without_acceptance():
    candidate = {"url": "https://example.com", "category": "product_homepage"}
    record = build_page_record(
        candidate,
        {"text": "This website uses cookies. Product content. " * 50},
        status="success",
        reason=None,
        screenshot_path=None,
        snapshot_path=None,
        network_requests_made=1,
    )
    assert record["browser_metadata"]["cookie_banner_seen"] is True
    assert record["browser_metadata"]["cookies_accepted"] is False


def test_snapshot_output_can_feed_extraction_when_eval_text_empty():
    raw = '{"tree": "[0-1] RootWebArea: Example page\\n  [0-2] heading: Main heading\\n  [0-3] StaticText: Useful visible content\\n  [0-4] link: Docs\\n  [0-5] button: Get started"}'
    parsed = parse_snapshot_output(raw)
    assert parsed["title"] == "Example page"
    assert parsed["h1"] == "Main heading"
    assert "Useful visible content" in parsed["text"]
    assert parsed["links"] == [{"text": "Docs", "url": ""}]
    assert parsed["buttons"] == ["Get started"]
