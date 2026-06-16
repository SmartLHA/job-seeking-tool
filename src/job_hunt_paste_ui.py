"""
URL Pre-fill UI module for the Job Seeking Tool viewer.

Provides:
- parse_job_url(url) — call src/parsing.py via subprocess to parse a job URL
- parse_job_text(text) — call src/parsing.py via subprocess to parse pasted job text
- submit_parsed_job(data) — store/submit the parsed job data
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# Path to the src/parsing.py module (relative to viewer/)
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
PARSING_MODULE = PROJECT_ROOT / "src" / "parsing.py"
DATA_DIR = PROJECT_ROOT / "data"


def parse_job_url(url: str) -> dict:
    """
    Fetch and parse a job posting from a URL.

    Calls src/parsing.py via subprocess and returns the structured job dict.

    Args:
        url: Job posting URL (e.g. from Indeed, LinkedIn, etc.)

    Returns:
        dict with job fields: job_title, company, location, salary_min_gbp,
        salary_max_gbp, description_raw, required_skills, work_mode,
        employment_type, required_years_experience, source_ref, job_id

    Raises:
        ValueError: on parse failure or if URL cannot be fetched
    """
    url = url.strip()
    if not url:
        raise ValueError("URL is required")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                f"import sys; sys.path.insert(0, '{PARSING_MODULE.parent}'); "
                f"from parsing import parse_job_from_url; "
                f"import json; "
                f"result = parse_job_from_url('{url}'); "
                f"print(json.dumps(result))"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(PROJECT_ROOT),
    )

    if result.returncode != 0:
        raise ValueError(f"Parse failed: {result.stderr.strip()}")

    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse output: {exc}") from exc


def parse_job_text(raw_text: str) -> dict:
    """
    Parse a job posting from pasted text.

    Args:
        raw_text: Raw job posting text

    Returns:
        dict with structured job fields (same shape as parse_job_url)

    Raises:
        ValueError: on parse failure
    """
    raw_text = raw_text.strip()
    if not raw_text:
        raise ValueError("Job text is required")

    # Escape single quotes for shell safety
    escaped = raw_text.replace("'", "'\"'\"'")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                f"import sys; sys.path.insert(0, '{PARSING_MODULE.parent}'); "
                f"from parsing import parse_job_from_text; "
                f"import json; "
                f"result = parse_job_from_text('{escaped}'); "
                f"print(json.dumps(result))"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        cwd=str(PROJECT_ROOT),
    )

    if result.returncode != 0:
        raise ValueError(f"Parse failed: {result.stderr.strip()}")

    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse output: {exc}") from exc


def submit_parsed_job(data: dict) -> str:
    """
    Store a parsed job to the data directory.

    Saves as data/<job_id>.json

    Args:
        data: Structured job dict (must contain job_id)

    Returns:
        The job_id of the saved job
    """
    job_id = data.get("job_id") or f"job-{data.get('job_title', 'unknown')}-{data.get('company', 'unknown')}"
    out_path = DATA_DIR / f"{job_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return job_id
