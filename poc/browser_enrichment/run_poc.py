#!/usr/bin/env python3
"""Run the dry-run browser enrichment POC."""

from __future__ import annotations

import json
from pathlib import Path

from browser_enrichment_agent import BrowserEnrichmentAgent
from report_writer import write_report


BASE_DIR = Path(__file__).resolve().parent


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_config() -> dict:
    local_config = BASE_DIR / "config.local.json"
    config_path = local_config if local_config.exists() else BASE_DIR / "config.example.json"
    return load_json(config_path)


def dry_run_runtime_config(config: dict) -> dict:
    """Enable only the local dry-run simulation path for this standalone POC."""
    runtime_config = dict(config)
    if runtime_config.get("browser_enrichment_dry_run", True):
        runtime_config["browser_enrichment_enabled"] = True
        runtime_config["runner_enabled_dry_run_only"] = True
    return runtime_config


def run() -> dict:
    config = dry_run_runtime_config(load_config())
    jobs = load_json(BASE_DIR / "sample_jobs.json")

    agent = BrowserEnrichmentAgent(config=config, base_dir=BASE_DIR)
    enriched_jobs = agent.enrich_jobs(jobs)

    output_dir = BASE_DIR / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "screenshots").mkdir(exist_ok=True)
    (output_dir / "snapshots").mkdir(exist_ok=True)

    enriched_path = output_dir / "enriched_jobs.json"
    enriched_path.write_text(json.dumps(enriched_jobs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = write_report(enriched_jobs, output_dir / "poc_report.md", config)
    return summary


if __name__ == "__main__":
    result = run()
    print(
        "Browser enrichment dry-run complete: "
        f"{result['total_jobs']} jobs, "
        f"{result['browser_attempts']} simulated enrichments, "
        f"{result['network_requests_made']} network requests."
    )
