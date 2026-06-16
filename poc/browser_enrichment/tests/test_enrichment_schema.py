import json
import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

from run_poc import dry_run_runtime_config, run


def test_example_config_defaults_disabled_but_runner_enables_dry_run_only():
    config = json.loads((POC_DIR / "config.example.json").read_text(encoding="utf-8"))

    assert config["browser_enrichment_enabled"] is False
    assert config["browser_enrichment_dry_run"] is True

    runtime_config = dry_run_runtime_config(config)
    assert runtime_config["browser_enrichment_enabled"] is True
    assert runtime_config["runner_enabled_dry_run_only"] is True
    assert runtime_config["browser_enrichment_dry_run"] is True


def test_run_output_conforms_to_expected_schema():
    summary = run()
    assert summary["total_jobs"] == 10
    assert summary["network_requests_made"] == 0
    assert summary["dry_run_records_promoted_to_apply"] == 0
    assert summary["live_verified_records"] == 0
    assert summary["login_required_count"] >= 1
    assert summary["extraction_failed_count"] >= 1
    assert summary["safety_violations_count"] == 0

    schema = json.loads((POC_DIR / "expected_schema.json").read_text(encoding="utf-8"))
    jobs = json.loads((POC_DIR / "output" / "enriched_jobs.json").read_text(encoding="utf-8"))

    for job in jobs:
        for field in schema["required_fields"]:
            assert field in job
        for field in schema["source_quality"]["required_fields"]:
            assert field in job["source_quality"]
        for field in schema["browser_enrichment"]["required_fields"]:
            assert field in job["browser_enrichment"]
        assert job["source_quality"]["quality_band"] in schema["source_quality"]["quality_bands"]
        assert job["source_quality"]["apply_decision"] in schema["source_quality"]["apply_decisions"]
        assert job["browser_enrichment"]["status"] in schema["browser_enrichment"]["statuses"]
        assert job["browser_enrichment"]["dry_run"] is True
        assert job["browser_enrichment"]["network_requests_made"] == 0
        if job["browser_enrichment"]["attempted"] is True:
            assert job["source_quality"]["apply_decision"] != "allowed"


def test_sample_jobs_cover_required_cases():
    jobs = json.loads((POC_DIR / "sample_jobs.json").read_text(encoding="utf-8"))
    external_ids = {job["external_id"] for job in jobs}

    assert {
        "reed-full-skip",
        "reed-short-enrich",
        "adzuna-full-skip",
        "adzuna-short-enrich",
        "greenhouse-enrich",
        "lever-enrich",
        "greenhouse-extraction-failed",
        "lever-login-required",
        "linkedin-blocked-skip",
        "unknown-domain-skip",
    } <= external_ids
