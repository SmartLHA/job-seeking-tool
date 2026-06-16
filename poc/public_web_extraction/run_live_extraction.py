#!/usr/bin/env python3
"""Run the read-only public web extraction POC with Browse CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from content_extractor import extract_with_browse
from domain_policy import validate_candidate_url
from markdown_exporter import write_markdown_exports
from report_writer import write_report
from research_summary import write_research_summary


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_preflight() -> dict:
    path = BASE_DIR / "output" / "candidate_preflight.json"
    if not path.exists():
        from run_preflight import run as run_preflight

        return run_preflight()
    return load_json(path)


def run() -> dict:
    config = load_json(BASE_DIR / "config.example.json")
    candidates = load_json(BASE_DIR / "candidate_pages.json")
    preflight = load_preflight()
    passed_urls = {item["url"] for item in preflight["results"] if item["status"] == "passed"}
    max_pages = int(config.get("max_pages_per_run", 10))
    if max_pages < 1:
        raise RuntimeError("max_pages_per_run must be at least 1")

    selected = []
    for candidate in candidates:
        policy = validate_candidate_url(candidate.get("url"), candidates, config)
        if policy.allowed and candidate["url"] in passed_urls:
            selected.append(candidate)
        if len(selected) >= max_pages:
            break

    pages = []
    commands_used = ["python3.14 poc/public_web_extraction/run_preflight.py"]
    for index, candidate in enumerate(selected, 1):
        page, commands = extract_with_browse(candidate, config, index)
        pages.append(page)
        commands_used.extend(commands)

    payload = {
        "total_candidate_pages": len(candidates),
        "preflight_passed_count": len(passed_urls),
        "max_pages_per_run": max_pages,
        "extracted_pages": pages,
    }
    output_path = BASE_DIR / "output" / "extracted_pages.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_paths = write_markdown_exports(pages, BASE_DIR / "output" / "markdown")
    research_summary = write_research_summary(BASE_DIR / "output" / "research_summary.json", pages)
    summary = write_report(
        BASE_DIR / "output" / "extraction_report_v2.md",
        pages,
        total_candidates=len(candidates),
        preflight_passed_count=len(passed_urls),
        commands_used=commands_used,
        markdown_paths=markdown_paths,
        research_summary_count=len(research_summary),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


if __name__ == "__main__":
    run()
