#!/usr/bin/env python3
"""Nimble blind check (spec: docs/tasks/2026-10-11-nimble-check-spec.md).

Does the local Nimble 9B decision model judge job ads the way Mike does?

    export   writes archive/nimble-check/labels.csv; Mike fills RF and CU blind (y or n).
    run      asks the local Nimble the same two questions and writes
             archive/nimble-check/report-<YYYY-MM-DD>.md.
    run --smoke   sends ONE built-in sample ad and prints answer keys, input tokens and
                  latency only (confirms the live API shape).

Read-only on app state: stored jobs are read as plain JSON files. This script NEVER writes
under data/, opens the SQLite database, or calls storage helpers that create directories.
Local Ollama only (127.0.0.1). No Gemini.

Usage (from the project root):
    venv/bin/python scripts/nimble_check.py export [--force]
    venv/bin/python scripts/nimble_check.py run --smoke
    venv/bin/python scripts/nimble_check.py run [--force]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

# Make `src` importable when run from the repo root (same pattern as scripts/verify_digest.py).
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.job_hunt_models import effective_decision  # noqa: E402
from src.job_hunt_qualitative import derive_base_grade  # noqa: E402

# ---------------------------------------------------------------------------
# Frozen test definition. These two questions ARE the test: do not reword them
# after any live run. Wording is taken from the red_flags and culture_signals
# rubric in src/job_hunt_qualitative.py (build_qualitative_prompt).
# ---------------------------------------------------------------------------
RF_QUESTION = "Does this job ad show material red flags?"
CU_QUESTION = "Does the ad's culture or working style clash with what the role requires?"

# Paths. State is read-only; output goes only under archive/nimble-check/.
DEFAULT_STATE_ROOT = ROOT / "data" / "state"
DEFAULT_OUT_DIR = ROOT / "archive" / "nimble-check"
DATA_DIR = ROOT / "data"
LABELS_NAME = "labels.csv"

# The app's local UI (start.command default port); used only to build the job page link.
DEFAULT_BASE_URL = "http://127.0.0.1:9000"

# Job selection (export).
EXCLUDED_PREFIXES = ("demo-", "test-", "edge-")
MIN_JD_CHARS = 1000
MAX_JD_CHARS = 14000
STUB_MAX_CHARS = 520
STUB_COUNT = 5

CSV_COLUMNS = ["job_id", "title", "company", "jd_chars", "base_grade", "decision", "link", "RF", "CU"]
LABELS_COMMENT = (
    "# Blind labels: type y or n in the RF and CU columns for each job (leave blank to skip). "
    f"RF = {RF_QUESTION[0].lower()}{RF_QUESTION[1:]} "
    f"CU = {CU_QUESTION[0].lower()}{CU_QUESTION[1:]} "
    "Do not look at Nimble answers before labelling."
)


class LabelsExist(Exception):
    """labels.csv already exists and --force was not given."""


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------
def refuse_data_path(path: Path, data_dir: Path | None = None) -> None:
    """Hard constraint: never write under data/. Raise if `path` is inside it."""
    resolved = Path(path).resolve()
    data_resolved = Path(DATA_DIR if data_dir is None else data_dir).resolve()
    if resolved == data_resolved or data_resolved in resolved.parents:
        raise ValueError(f"refusing to write under data/: {resolved}")


# ---------------------------------------------------------------------------
# Reading stored jobs (plain JSON files, read-only)
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_reviewed_jobs(state_root: Path) -> list[dict]:
    """Read <state_root>/reviewed_jobs/*.json directly. job_id is the file stem
    (the app stores each job as reviewed_jobs/<job_id>.json)."""
    jobs: list[dict] = []
    for path in sorted((Path(state_root) / "reviewed_jobs").glob("*.json")):
        data = _read_json(path)
        if data is None:
            print(f"warning: could not read {path.name}; skipped", file=sys.stderr)
            continue
        jd = data.get("description_raw")
        jobs.append(
            {
                "job_id": path.stem,
                "title": str(data.get("job_title") or ""),
                "company": str(data.get("company") or ""),
                "jd": jd if isinstance(jd, str) else "",
            }
        )
    return jobs


def load_analysis(state_root: Path, job_id: str) -> dict | None:
    return _read_json(Path(state_root) / "analyses" / f"{job_id}.json")


def grade_and_decision(analysis: dict | None) -> tuple[str, str]:
    """base_grade via the existing derive_base_grade; decision via effective_decision
    (user_decision if set, else the engine decision). Blank strings if no usable analysis."""
    if not analysis:
        return "", ""
    base_grade = ""
    score = analysis.get("match_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        base_grade = derive_base_grade(score)
    decision = effective_decision(
        SimpleNamespace(
            user_decision=analysis.get("user_decision"),
            decision=analysis.get("decision"),
        )
    )
    return base_grade, str(decision or "")


def job_link(job_id: str, base_url: str = DEFAULT_BASE_URL) -> str:
    """Local job page URL used by the app's UI (/job/<id>, see src/ui_render.py)."""
    return f"{base_url.rstrip('/')}/job/{quote(job_id, safe='')}"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def select_jobs(jobs: list[dict]) -> list[dict]:
    """All jobs with 1,000-14,000 char JDs, then the first STUB_COUNT stubs
    (JD <= 520 chars, non-blank) by job_id. demo-/test-/edge- fixtures are excluded.
    Jobs over 14,000 chars are excluded so Mike never labels a job `run` would skip."""
    candidates = sorted(
        (j for j in jobs if not j["job_id"].startswith(EXCLUDED_PREFIXES)),
        key=lambda j: j["job_id"],
    )
    main = [j for j in candidates if MIN_JD_CHARS <= len(j["jd"]) <= MAX_JD_CHARS]
    stubs = [j for j in candidates if j["jd"].strip() and len(j["jd"]) <= STUB_MAX_CHARS]
    return main + stubs[:STUB_COUNT]


def build_export_rows(
    jobs: list[dict], state_root: Path, base_url: str = DEFAULT_BASE_URL
) -> list[list]:
    rows = []
    for job in select_jobs(jobs):
        base_grade, decision = grade_and_decision(load_analysis(state_root, job["job_id"]))
        rows.append(
            [
                job["job_id"],
                job["title"],
                job["company"],
                len(job["jd"]),
                base_grade,
                decision,
                job_link(job["job_id"], base_url),
                "",
                "",
            ]
        )
    return rows


def write_labels_csv(path: Path, rows: list[list], *, force: bool = False) -> None:
    """Write labels.csv (one comment line, column header, rows). Refuses to overwrite
    an existing file unless force=True."""
    path = Path(path)
    refuse_data_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # "x" fails if the file exists, so a labelled file can never be clobbered by accident.
        handle = path.open("w" if force else "x", newline="", encoding="utf-8-sig")
    except FileExistsError as exc:
        raise LabelsExist(
            f"{path} already exists; it may hold your labels. Use --force to overwrite."
        ) from exc
    with handle:
        handle.write(LABELS_COMMENT + "\n")
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)


def cmd_export(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    jobs = load_reviewed_jobs(Path(args.state_root))
    rows = build_export_rows(jobs, Path(args.state_root), args.base_url)
    path = out_dir / LABELS_NAME
    try:
        write_labels_csv(path, rows, force=args.force)
    except (LabelsExist, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    stubs = sum(1 for r in rows if r[3] <= STUB_MAX_CHARS)
    print(f"Wrote {len(rows)} rows ({len(rows) - stubs} full ads + {stubs} stubs) to {path}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Nimble blind check (local Ollama only).")
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="Write labels.csv for blind labelling")
    export.add_argument("--force", action="store_true", help="Overwrite an existing labels.csv")
    export.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT), help="Read-only state dir")
    export.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output dir (never under data/)")
    export.add_argument("--base-url", default=DEFAULT_BASE_URL, help="App UI base URL for job links")
    export.set_defaults(func=cmd_export)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
