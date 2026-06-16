import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

from markdown_exporter import write_markdown_exports


def test_markdown_export_writes_successful_pages(tmp_path):
    page = {
        "status": "success",
        "url": "https://example.com",
        "domain": "example.com",
        "category": "product_homepage",
        "title": "Example Product",
        "concise_summary": "A concise summary.",
        "key_claims": ["Trusted by teams."],
        "useful_links": [{"text": "Docs", "url": "https://example.com/docs", "type": "documentation"}],
        "main_content": "Cleaned page content.",
        "extraction_quality": {"confidence_score": 90},
    }
    paths = write_markdown_exports([page, {"status": "failed"}], tmp_path)
    assert len(paths) == 1
    content = Path(paths[0]).read_text(encoding="utf-8")
    assert "url: https://example.com" in content
    assert "## Useful Links" in content
    assert "[Docs](https://example.com/docs)" in content
