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
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import requests

# Make `src` importable when run from the repo root (same pattern as scripts/verify_digest.py).
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.job_hunt_models import effective_decision  # noqa: E402
from src.job_hunt_qualitative import DIMENSIONS, POSTING_QUALITY_TIERS, derive_base_grade  # noqa: E402

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

# Nimble (Ollama) API. Local only.
MODEL = "nimble:9b-q4_K_M"
OLLAMA_URL = "http://127.0.0.1:11434"
SYSTEMONE_PATH = "/v1/systemone"
TAGS_PATH = "/api/tags"
KEEP_ALIVE = "30m"
REQUEST_TIMEOUT_S = 300  # first call may have to load the 9B model
TAGS_TIMEOUT_S = 10
MAX_BODY_BYTES = 64 * 1024  # Nimble request body limit
TOKEN_WARN = 7000  # context limit is 8,192 tokens (job text + all questions)

# Threshold for "Nimble yes" on the noul questions (P(yes) >= 0.5). Set before any live run.
THRESHOLD = 0.5

# Level 1 / 3 / 5 wording of the four dimension rubrics, copied from
# build_qualitative_prompt in src/job_hunt_qualitative.py (a test guards against drift).
DIMENSION_RUBRIC = {
    "seniority_fit": ("clearly too junior/senior", "unclear or partial match", "strong seniority match"),
    "culture_signals": ("evidence of poor fit or unhealthy signals", "little/no evidence", "strong positive signals"),
    "red_flags": ("material red flags", "limited/unclear warning signs", "no meaningful red flags in the JD"),
    "role_archetype_alignment": ("poor alignment with target roles", "mixed/unclear", "strong archetype match"),
}
DIMENSION_INSTRUCTIONS = {
    "seniority_fit": "Rate how well the seniority asked for in this job ad fits the candidate.",
    "culture_signals": "Rate the culture and working-style signals in this job ad.",
    "red_flags": "Rate the warning signs (red flags) in this job ad. A higher level means fewer red flags.",
    "role_archetype_alignment": "Rate how well this role aligns with the candidate's target roles.",
}
TIER_QUESTION = "Classify how trustworthy this job posting looks."
TIER_CRITERIA = {
    "high_confidence": "The posting looks genuine and well specified.",
    "unknown_caution": "There is not enough information to tell whether the posting is genuine.",
    "suspicious": "The posting shows signs of being fake, misleading or low quality.",
}

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
# Nimble client: request building, response parsing, HTTP errors
# ---------------------------------------------------------------------------
class OllamaUnavailable(Exception):
    """Connection refused or unreachable: stop the run."""


class ModelNotFound(Exception):
    """Ollama does not have the Nimble model: stop the run."""


class NimbleHTTPError(Exception):
    """Any other per-job HTTP/transport problem: recorded, the run continues."""


class ShapeError(ValueError):
    """The response does not have the shape described in the spec Background."""


def score_levels(name: str) -> list[str]:
    """Five level texts, lowest first: levels 1/3/5 from the existing rubric,
    levels 2/4 worded as 'between'."""
    low, mid, high = DIMENSION_RUBRIC[name]
    return [low, f"Between: {low} and {mid}", mid, f"Between: {mid} and {high}", high]


def clean_roles(target_roles) -> list[str]:
    return [str(r).strip() for r in (target_roles or []) if str(r).strip()]


def requested_dimensions(target_roles=None) -> tuple[str, ...]:
    """The score dimensions a request asks for (alignment needs target roles)."""
    has_roles = bool(clean_roles(target_roles))
    return tuple(d for d in DIMENSIONS if has_roles or d != "role_archetype_alignment")


def build_request(jd_text: str, target_roles=None) -> dict:
    """One request per job. State is the JD text. The rf and cu wording is frozen.
    With no target_roles the role_archetype_alignment question is left out, as the app
    does not guess alignment without target roles (build_qualitative_prompt)."""
    roles = clean_roles(target_roles)
    roles_text = ", ".join(roles)
    questions: dict[str, dict] = {
        "rf": {"type": "noul", "instructions": RF_QUESTION},
        "cu": {"type": "noul", "instructions": CU_QUESTION},
    }
    for name in requested_dimensions(roles):
        instructions = DIMENSION_INSTRUCTIONS[name]
        if roles and name in ("seniority_fit", "role_archetype_alignment"):
            instructions += f" Candidate target roles: {roles_text}."
        questions[name] = {"type": "score", "instructions": instructions, "criteria": score_levels(name)}
    questions["posting_tier"] = {
        "type": "choice",
        "instructions": TIER_QUESTION,
        "criteria": dict(TIER_CRITERIA),
    }
    return {"model": MODEL, "state": jd_text, "questions": questions, "keep_alive": KEEP_ALIVE}


def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_response(resp: dict, dimensions=DIMENSIONS) -> dict:
    """Pull the recorded fields out of a /v1/systemone response.
    noul -> P(yes) 0-1. score -> zero-based expected level, shown on the 1-5 scale (+1).
    choice -> the chosen key. Raises ShapeError if the shape differs from the spec."""
    answers = resp.get("answers") if isinstance(resp, dict) else None
    if not isinstance(answers, dict):
        raise ShapeError("response has no 'answers' object")

    def answer(name: str, kind: str, field: str):
        item = answers.get(name)
        if not isinstance(item, dict) or item.get("type") != kind or field not in item:
            raise ShapeError(f"answer '{name}' is not a {kind} answer with '{field}'")
        return item[field]

    out: dict = {"scores_1to5": {}}
    for name in ("rf", "cu"):
        value = _num(answer(name, "noul", "noul"))
        if value is None or not 0.0 <= value <= 1.0:
            raise ShapeError(f"answer '{name}' noul value is not a number in 0-1")
        out[name] = value
    for name in dimensions:
        value = _num(answer(name, "score", "score"))
        if value is None:
            raise ShapeError(f"answer '{name}' score is not a number")
        out["scores_1to5"][name] = value + 1.0  # zero-based level -> 1-5 scale
    tier = answer("posting_tier", "choice", "choice")
    if not isinstance(tier, str):
        raise ShapeError("answer 'posting_tier' choice is not a string")
    out["tier"] = tier
    usage = resp.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    input_tokens = usage.get("input_tokens")
    if isinstance(input_tokens, bool) or not isinstance(input_tokens, int):
        raise ShapeError("response usage has no integer input_tokens")
    out["input_tokens"] = input_tokens
    output_tokens = usage.get("output_tokens")
    out["output_tokens"] = output_tokens if isinstance(output_tokens, int) and not isinstance(output_tokens, bool) else None
    out["answer_keys"] = sorted(answers)
    return out


def _error_text(resp) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])
    except ValueError:
        pass
    return (getattr(resp, "text", "") or "")[:200]


def _transport(call, what: str, timeout: float):
    try:
        return call()
    except requests.exceptions.ConnectionError as exc:  # includes ConnectTimeout
        raise OllamaUnavailable(
            f"Cannot reach Ollama at {OLLAMA_URL}. Is Ollama running? ({type(exc).__name__})"
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise NimbleHTTPError(f"{what} timed out after {timeout:g}s") from exc
    except requests.exceptions.RequestException as exc:
        raise NimbleHTTPError(f"{what} failed: {type(exc).__name__}: {exc}") from exc


def post_systemone(payload: dict, *, base_url: str = OLLAMA_URL, timeout: float = REQUEST_TIMEOUT_S):
    """POST one request. Returns (response_json, latency_seconds).
    Raises OllamaUnavailable, ModelNotFound (both stop the run) or NimbleHTTPError."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_BODY_BYTES:
        raise NimbleHTTPError(f"request body is {len(body)} bytes, over the {MAX_BODY_BYTES} byte limit")
    url = base_url.rstrip("/") + SYSTEMONE_PATH
    start = time.perf_counter()
    resp = _transport(
        lambda: requests.post(url, data=body, headers={"Content-Type": "application/json"}, timeout=timeout),
        "request",
        timeout,
    )
    latency = time.perf_counter() - start
    if resp.status_code != 200:
        text = _error_text(resp)
        if resp.status_code == 404 and "model" in text.lower() and "not found" in text.lower():
            raise ModelNotFound(f"Model {MODEL} was not found in Ollama ({text}). Pull it first.")
        raise NimbleHTTPError(f"HTTP {resp.status_code}: {text}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise NimbleHTTPError("response body is not JSON") from exc
    if not isinstance(data, dict):
        raise NimbleHTTPError("response JSON is not an object")
    return data, latency


def fetch_model_digest(model: str = MODEL, *, base_url: str = OLLAMA_URL) -> str:
    """Digest of the Nimble model from GET /api/tags. Stops the run if Ollama is down
    or the model is not listed."""
    resp = _transport(
        lambda: requests.get(base_url.rstrip("/") + TAGS_PATH, timeout=TAGS_TIMEOUT_S),
        "tags request",
        TAGS_TIMEOUT_S,
    )
    if resp.status_code != 200:
        raise NimbleHTTPError(f"HTTP {resp.status_code} from {TAGS_PATH}: {_error_text(resp)}")
    try:
        models = resp.json().get("models", [])
    except (ValueError, AttributeError) as exc:
        raise NimbleHTTPError(f"{TAGS_PATH} response is not the expected JSON") from exc
    for entry in models:
        if isinstance(entry, dict) and model in (entry.get("name"), entry.get("model")):
            return str(entry.get("digest") or "")
    raise ModelNotFound(f"Model {model} is not listed by Ollama. Pull it first.")


# ---------------------------------------------------------------------------
# Labels: parse Mike's filled-in labels.csv and join to results
# ---------------------------------------------------------------------------
class LabelsFormatError(ValueError):
    """labels.csv is missing its column header or required columns."""


def parse_label(raw) -> tuple[str | None, str]:
    """('y'|'n', 'ok') for y/yes/n/no (any case); (None, 'blank'); (None, 'invalid').
    Anything else is reported, never guessed."""
    value = (raw or "").strip().lower()
    if not value:
        return None, "blank"
    if value in ("y", "yes"):
        return "y", "ok"
    if value in ("n", "no"):
        return "n", "ok"
    return None, "invalid"


def read_labels(path: Path) -> tuple[list[dict], list[str]]:
    """Read labels.csv. Comment lines (first cell starts with #) and empty rows are skipped.
    Returns (rows, notes). Each row has the CSV columns as text plus RF_value / RF_status and
    CU_value / CU_status. A repeated job_id is skipped and noted."""
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        table = [
            r for r in csv.reader(handle)
            if any(c.strip() for c in r) and not r[0].lstrip().startswith("#")
        ]
    if not table:
        raise LabelsFormatError("labels.csv has no column header row")
    header = [c.strip() for c in table[0]]
    missing = [c for c in CSV_COLUMNS if c not in header]
    if missing:
        raise LabelsFormatError(f"labels.csv is missing columns: {', '.join(missing)}")
    rows: list[dict] = []
    notes: list[str] = []
    seen: set[str] = set()
    for raw_row in table[1:]:
        cells = list(raw_row) + [""] * (len(header) - len(raw_row))
        row = {name: cells[i].strip() if name not in ("RF", "CU") else cells[i] for i, name in enumerate(header)}
        if not row["job_id"]:
            notes.append("a row without job_id was skipped")
            continue
        if row["job_id"] in seen:
            notes.append(f"duplicate job_id {row['job_id']}: later row skipped")
            continue
        seen.add(row["job_id"])
        for question in ("RF", "CU"):
            row[f"{question}_value"], row[f"{question}_status"] = parse_label(row[question])
        rows.append(row)
    return rows, notes


def join_rows(label_rows: list[dict], results: dict[str, dict]) -> list[dict]:
    """Attach each job's Nimble result (or None) to its label row, by job_id."""
    return [{**row, "result": results.get(row["job_id"])} for row in label_rows]


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
