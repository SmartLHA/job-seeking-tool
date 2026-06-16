"""Per-page markdown export for public web extraction results."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def slugify(value: str, fallback: str = "page") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return (slug or fallback)[:80]


def write_markdown_exports(pages: list[dict[str, Any]], output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_file in output_dir.glob("*.md"):
        old_file.unlink()
    paths: list[str] = []
    for index, page in enumerate([item for item in pages if item.get("status") == "success"], 1):
        filename = f"{index:02d}_{slugify(page.get('domain') or 'domain')}_{slugify(page.get('category') or 'category')}.md"
        path = output_dir / filename
        useful_links = page.get("useful_links") or page.get("links") or []
        lines = [
            "---",
            f"url: {page.get('url')}",
            f"domain: {page.get('domain')}",
            f"category: {page.get('category')}",
            f"title: {page.get('title') or ''}",
            f"confidence_score: {(page.get('extraction_quality') or {}).get('confidence_score', 0)}",
            "---",
            "",
            f"# {page.get('title') or page.get('domain') or 'Untitled'}",
            "",
            "## Summary",
            page.get("concise_summary") or page.get("summary") or "",
            "",
            "## Key Claims",
        ]
        lines.extend(f"- {item}" for item in (page.get("key_claims") or [])[:8])
        lines.extend(["", "## Useful Links"])
        lines.extend(f"- [{link.get('text')}]({link.get('url')}) ({link.get('type', 'other')})" for link in useful_links[:15])
        lines.extend(["", "## Cleaned Content Excerpt", "", (page.get("main_content") or "")[:4000].strip()])
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        paths.append(str(path))
    return paths
