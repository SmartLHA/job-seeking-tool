import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

from text_cleanup import clean_main_content, deduplicate_headings


def test_cleanup_removes_cookie_text_and_letter_spacing():
    text = "This website uses cookies to improve service.\nN o t i o n helps teams."
    cleaned = clean_main_content(text)
    assert "uses cookies" not in cleaned.lower()
    assert "Notion helps teams" in cleaned


def test_headings_and_repeated_nav_lines_are_deduplicated():
    headings = deduplicate_headings(["Features", "Features", "Pricing"])
    cleaned = clean_main_content("Product\nPricing\nPricing\nFeatures\nFeatures\nBody copy with useful details.")
    assert headings == ["Features", "Pricing"]
    assert cleaned.count("Pricing") == 1
    assert cleaned.count("Features") == 1
