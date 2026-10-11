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
import os
import re
import sys
import time
from datetime import date, datetime, timezone
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
DEFAULT_PROFILE = ROOT / "data" / "mic_profile.json"  # read only; target_roles
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

# Report rules.
MIN_OWNER_YES = 3  # a question with fewer owner "yes" labels is reported "not tested"
HARMFUL_GRADES = ("A", "B")
RESULTS_DIRNAME = "results"
SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Built-in sample ad for `run --smoke` (not a stored job).
SMOKE_JD = (
    "Business Analyst - Digital Onboarding (Manchester, hybrid). We are a mid-sized UK insurer "
    "looking for a Business Analyst to join our change team. You will run requirements workshops "
    "with operations and compliance stakeholders, map current and target processes, write user "
    "stories with acceptance criteria and support UAT for a new customer onboarding platform. "
    "Essential: 3+ years as a BA in financial services, strong stakeholder management, experience "
    "of agile delivery. Salary GBP 50,000-58,000 plus pension and 25 days holiday."
)
SMOKE_ROLES = ["Business Analyst"]

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
# Run: one request per job, results cached per job (resume)
# ---------------------------------------------------------------------------
def load_target_roles(profile_path: Path) -> list[str]:
    """target_roles from the candidate profile JSON, read directly. [] if unavailable."""
    data = _read_json(Path(profile_path))
    if data is None:
        print(f"warning: could not read profile {profile_path}; target_roles treated as empty", file=sys.stderr)
        return []
    roles = data.get("target_roles")
    return clean_roles(roles if isinstance(roles, list) else [])


def read_job_text(state_root: Path, job_id: str) -> str | None:
    data = _read_json(Path(state_root) / "reviewed_jobs" / f"{job_id}.json")
    if data is None or not isinstance(data.get("description_raw"), str):
        return None
    return data["description_raw"]


def result_path(results_dir: Path, job_id: str) -> Path:
    if not SAFE_JOB_ID.match(job_id):
        raise ValueError(f"unsafe job_id {job_id!r}")
    return Path(results_dir) / f"{job_id}.json"


def load_result(results_dir: Path, job_id: str) -> dict | None:
    try:
        return _read_json(result_path(results_dir, job_id))
    except ValueError:
        return None


def save_result(results_dir: Path, record: dict) -> None:
    refuse_data_path(results_dir)
    path = result_path(results_dir, record["job_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # a half-written file can never look like a finished result


def is_done(record: dict | None) -> bool:
    return bool(record) and record.get("status") == "ok"


def check_job(job_id: str, jd_text: str | None, target_roles, digest: str) -> dict:
    """Ask Nimble about one job. Returns a result record (status ok / error / skipped).
    OllamaUnavailable and ModelNotFound propagate: they stop the run."""
    base = {
        "job_id": job_id,
        "model_digest": digest,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if jd_text is None:
        return {**base, "status": "error", "error": "reviewed job file missing or unreadable"}
    if not jd_text.strip():
        return {**base, "status": "error", "error": "job description is empty"}
    if len(jd_text) > MAX_JD_CHARS:
        return {**base, "status": "skipped", "error": f"JD is {len(jd_text)} chars, over the {MAX_JD_CHARS} limit"}
    try:
        data, latency = post_systemone(build_request(jd_text, target_roles))
        parsed = parse_response(data, requested_dimensions(target_roles))
    except NimbleHTTPError as exc:
        return {**base, "status": "error", "error": str(exc)}
    except ShapeError as exc:
        return {**base, "status": "error", "error": f"unexpected response shape: {exc}"}
    return {
        **base,
        "status": "ok",
        "error": None,
        "rf": parsed["rf"],
        "cu": parsed["cu"],
        "scores_1to5": parsed["scores_1to5"],
        "tier": parsed["tier"],
        "input_tokens": parsed["input_tokens"],
        "output_tokens": parsed["output_tokens"],
        "latency_s": round(latency, 2),
        "token_flag": parsed["input_tokens"] > TOKEN_WARN,
    }


def run_checks(
    label_rows: list[dict],
    *,
    state_root: Path,
    results_dir: Path,
    target_roles,
    digest: str,
    force: bool = False,
    progress=print,
) -> dict[str, dict]:
    """Run every labelled row through Nimble. A job with a finished result is skipped
    unless force. Each result is written as soon as it exists, so a stopped run resumes."""
    results: dict[str, dict] = {}
    total = len(label_rows)
    for index, row in enumerate(label_rows, 1):
        job_id = row["job_id"]
        safe = bool(SAFE_JOB_ID.match(job_id))
        cached = load_result(results_dir, job_id) if safe else None
        if is_done(cached) and not force:
            results[job_id] = cached
            progress(f"[{index}/{total}] {job_id}: already done, skipped")
            continue
        if safe:
            record = check_job(job_id, read_job_text(state_root, job_id), target_roles, digest)
            save_result(results_dir, record)
        else:
            record = {"job_id": job_id, "status": "error", "error": "unsafe job_id; not run", "model_digest": digest}
        results[job_id] = record
        if record["status"] == "ok":
            progress(f"[{index}/{total}] {job_id}: ok ({record['input_tokens']} tokens, {record['latency_s']}s)")
        else:
            progress(f"[{index}/{total}] {job_id}: {record['status']} - {record['error']}")
    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def is_stub(row: dict) -> bool:
    try:
        return int(row.get("jd_chars", "")) <= STUB_MAX_CHARS
    except (TypeError, ValueError):
        return False


def nimble_yes(value: float, threshold: float = THRESHOLD) -> bool:
    """Nimble says yes when P(yes) is at or above the threshold (0.5 counts as yes)."""
    return value >= threshold


def count_question(rows: list[dict], question: str, threshold: float = THRESHOLD) -> dict:
    """Counts for 'RF' or 'CU'. Only rows with a valid owner label AND a Nimble answer
    are compared. Blank and invalid labels are counted apart, never guessed."""
    key = question.lower()
    c = dict(owner_yes=0, nimble_yes=0, both=0, neither=0, owner_only=0, nimble_only=0,
             unlabelled=0, invalid=0, no_result=0, compared=0)
    for row in rows:
        status = row[f"{question}_status"]
        if status == "blank":
            c["unlabelled"] += 1
            continue
        if status == "invalid":
            c["invalid"] += 1
            continue
        result = row.get("result")
        if not is_done(result):
            c["no_result"] += 1
            continue
        owner = row[f"{question}_value"] == "y"
        nimble = nimble_yes(result[key], threshold)
        c["compared"] += 1
        c["owner_yes"] += owner
        c["nimble_yes"] += nimble
        if owner and nimble:
            c["both"] += 1
        elif not owner and not nimble:
            c["neither"] += 1
        elif owner:
            c["owner_only"] += 1
        else:
            c["nimble_only"] += 1
    c["tested"] = c["owner_yes"] >= MIN_OWNER_YES
    return c


def harmful_cases(rows: list[dict], question: str, threshold: float = THRESHOLD) -> list[dict]:
    """Base grade A or B, Nimble says yes, owner says no."""
    key = question.lower()
    return [
        row for row in rows
        if row.get("base_grade") in HARMFUL_GRADES
        and row[f"{question}_value"] == "n"
        and is_done(row.get("result"))
        and nimble_yes(row["result"][key], threshold)
    ]


def _esc(text) -> str:
    return str("" if text is None else text).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _owner_cell(row: dict, question: str) -> str:
    status = row[f"{question}_status"]
    if status == "ok":
        return row[f"{question}_value"]
    return "blank" if status == "blank" else f"invalid: {row[question].strip()}"


def _nimble_cells(row: dict, question: str, threshold: float) -> tuple[str, str]:
    result = row.get("result")
    if not is_done(result):
        return "-", "-"
    value = result[question.lower()]
    return f"{value:.2f}", "yes" if nimble_yes(value, threshold) else "no"


JOB_TABLE_HEADER = [
    "job_id", "title", "company", "base grade", "decision", "JD chars",
    "RF owner", "RF Nimble P(yes)", "RF Nimble", "CU owner", "CU Nimble P(yes)", "CU Nimble",
    "seniority_fit (1-5)", "culture_signals (1-5)", "red_flags (1-5)", "role_archetype_alignment (1-5)",
    "posting tier (unvalidated)", "input_tokens", "latency (s)", "model digest", "flags",
]


def _job_table(rows: list[dict], threshold: float) -> list[str]:
    lines = ["| " + " | ".join(JOB_TABLE_HEADER) + " |", "|" + "---|" * len(JOB_TABLE_HEADER)]
    for row in rows:
        result = row.get("result")
        done = is_done(result)
        scores = result.get("scores_1to5", {}) if done else {}
        rf_p, rf_y = _nimble_cells(row, "RF", threshold)
        cu_p, cu_y = _nimble_cells(row, "CU", threshold)
        flags = []
        if result is None:
            flags.append("no result")
        elif not done:
            flags.append(f"{result.get('status')}: {result.get('error')}")
        elif result.get("token_flag") or result.get("input_tokens", 0) > TOKEN_WARN:
            flags.append(f"input_tokens > {TOKEN_WARN}")
        cells = [
            row["job_id"], row["title"], row["company"], row["base_grade"], row["decision"], row["jd_chars"],
            _owner_cell(row, "RF"), rf_p, rf_y, _owner_cell(row, "CU"), cu_p, cu_y,
            *[f"{scores[d]:.2f}" if d in scores else "-" for d in DIMENSIONS],
            result.get("tier", "-") if done else "-",
            result.get("input_tokens", "-") if done else "-",
            result.get("latency_s", "-") if done else "-",
            (result.get("model_digest") or "-")[:12] if result else "-",
            "; ".join(flags),
        ]
        lines.append("| " + " | ".join(_esc(c) for c in cells) + " |")
    return lines


def _count_table(c: dict) -> list[str]:
    rows = [
        ("Owner yes", c["owner_yes"]),
        ("Nimble yes", c["nimble_yes"]),
        ("Both yes", c["both"]),
        ("Neither (both no)", c["neither"]),
        ("Owner yes, Nimble no", c["owner_only"]),
        ("Owner no, Nimble yes", c["nimble_only"]),
        ("Unlabelled (blank)", c["unlabelled"]),
        ("Invalid label (not counted)", c["invalid"]),
        ("Labelled but no Nimble result", c["no_result"]),
        ("Compared (valid label and Nimble answer)", c["compared"]),
    ]
    return ["| Measure | Jobs |", "|---|---|", *[f"| {name} | {value} |" for name, value in rows]]


def _name(row: dict) -> str:
    return f"{row['title']} at {row['company']} (`{row['job_id']}`, base grade {row['base_grade']}, decision {row['decision']})"


def build_report(rows: list[dict], *, date_str: str, notes=(), threshold: float = THRESHOLD) -> str:
    """Markdown report from joined rows (label row + 'result')."""
    full = [r for r in rows if not is_stub(r)]
    stubs = [r for r in rows if is_stub(r)]
    digests = sorted({r["result"].get("model_digest") or "unknown" for r in rows if is_done(r.get("result"))})
    digest_text = ", ".join(f"`{d}`" for d in digests) if digests else "n/a (no Nimble results)"
    lines = [
        f"# Nimble blind check - report {date_str}",
        "",
        "**Indicative - small sample.** These counts show whether Nimble tends to agree with the "
        "owner on a handful of ads. They are not an accuracy figure.",
        "",
        f"- Date: {date_str}",
        f"- Model: `{MODEL}`, digest: {digest_text}",
        f"- Nimble yes threshold: P(yes) >= {threshold:.2f} (0.50 counts as yes)",
        f"- Jobs in labels.csv: {len(rows)} ({len(full)} full ads, {len(stubs)} stubs)",
        f"- Minimum owner yes labels for a question to be tested: {MIN_OWNER_YES}",
    ]
    if len(digests) > 1:
        lines.append("- WARNING: results come from more than one model digest; re-run with --force for a clean report.")
    for note in notes:
        lines.append(f"- Note: {note}")

    for question, title, wording in (
        ("RF", "RF - material red flags", RF_QUESTION),
        ("CU", "CU - culture clash", CU_QUESTION),
    ):
        c = count_question(full, question, threshold)
        lines += ["", f"## {title}", "", f"Question (frozen): {wording}", ""]
        lines += _count_table(c)
        lines.append("")
        if not c["tested"]:
            lines.append(
                f"**Not tested** - fewer than {MIN_OWNER_YES} owner yes labels ({c['owner_yes']}). "
                "The counts are shown for information only; no agreement is claimed."
            )
        else:
            lines.append(
                f"Agreement on yes/no: {c['both'] + c['neither']} of {c['compared']} compared jobs "
                f"(both yes {c['both']}, both no {c['neither']})."
            )

    lines += ["", "## Harmful cases (base grade A or B, Nimble yes, owner no)", ""]
    for question in ("RF", "CU"):
        cases = harmful_cases(rows, question, threshold)
        lines.append(f"**{question}:** " + ("none" if not cases else ""))
        for row in cases:
            stub = " [stub]" if is_stub(row) else ""
            lines.append(f"- {_name(row)}{stub}, Nimble P(yes) {row['result'][question.lower()]:.2f}")
        lines.append("")

    lines += ["## Stub jobs (JD of 520 characters or fewer)", ""]
    if not stubs:
        lines.append("No stub jobs.")
    else:
        for question in ("RF", "CU"):
            c = count_question(stubs, question, threshold)
            lines.append(
                f"- {question}: owner yes {c['owner_yes']}, Nimble yes {c['nimble_yes']}, both {c['both']}, "
                f"neither {c['neither']}, unlabelled {c['unlabelled']}, invalid {c['invalid']}, "
                f"no Nimble result {c['no_result']}"
            )
        lines.append("")
        lines += _job_table(stubs, threshold)

    lines += ["", "## Per-job table (full ads)", ""]
    lines += _job_table(full, threshold) if full else ["No full ads."]

    lines += ["", "## Label problems", ""]
    problems = False
    for question in ("RF", "CU"):
        blank = [r["job_id"] for r in rows if r[f"{question}_status"] == "blank"]
        invalid = [r for r in rows if r[f"{question}_status"] == "invalid"]
        if blank:
            problems = True
            lines.append(f"- {question} blank on {len(blank)} job(s): " + ", ".join(blank))
        for row in invalid:
            problems = True
            lines.append(f"- {question} invalid on `{row['job_id']}`: {row[question].strip()!r} (use y or n)")
    if not problems:
        lines.append("None.")

    lines += ["", "## Errors and skipped jobs", ""]
    bad = [r for r in rows if not is_done(r.get("result"))]
    if not bad:
        lines.append("None.")
    for row in bad:
        result = row.get("result")
        reason = "no result recorded" if result is None else f"{result.get('status')}: {result.get('error')}"
        lines.append(f"- `{row['job_id']}`: {reason}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def cmd_smoke(args: argparse.Namespace) -> int:
    """One built-in sample ad. Prints answer keys, input tokens and latency only."""
    try:
        data, latency = post_systemone(build_request(SMOKE_JD, SMOKE_ROLES))
    except (OllamaUnavailable, ModelNotFound, NimbleHTTPError) as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        return 1
    answers = data.get("answers")
    print(f"answer keys: {sorted(answers) if isinstance(answers, dict) else answers!r}")
    try:
        parsed = parse_response(data, requested_dimensions(SMOKE_ROLES))
    except ShapeError as exc:
        print(f"SHAPE MISMATCH: {exc}", file=sys.stderr)
        return 3
    print(f"input_tokens: {parsed['input_tokens']}")
    print(f"latency_s: {latency:.1f}")
    print("shape OK: noul, score and choice answers match the spec")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.smoke:
        return cmd_smoke(args)
    out_dir = Path(args.out_dir)
    try:
        refuse_data_path(out_dir)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    labels_path = out_dir / LABELS_NAME
    if not labels_path.exists():
        print(f"error: {labels_path} not found. Run `export` first, then label the jobs.", file=sys.stderr)
        return 2
    try:
        rows, notes = read_labels(labels_path)
    except LabelsFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not any(r["RF_status"] != "blank" or r["CU_status"] != "blank" for r in rows):
        print("warning: no labels found in labels.csv yet. Label the jobs blind BEFORE running.", file=sys.stderr)
    target_roles = load_target_roles(Path(args.profile))
    results_dir = out_dir / RESULTS_DIRNAME
    try:
        digest = fetch_model_digest()
        results = run_checks(
            rows,
            state_root=Path(args.state_root),
            results_dir=results_dir,
            target_roles=target_roles,
            digest=digest,
            force=args.force,
        )
    except (OllamaUnavailable, ModelNotFound) as exc:
        print(f"stopped: {exc}\nFinished results are saved; run again to resume.", file=sys.stderr)
        return 1
    today = date.today().isoformat()
    report_path = out_dir / f"report-{today}.md"
    refuse_data_path(report_path)
    report_path.write_text(build_report(join_rows(rows, results), date_str=today, notes=notes), encoding="utf-8")
    ok = sum(1 for r in results.values() if is_done(r))
    print(f"Report written to {report_path} ({ok} of {len(rows)} jobs have Nimble results)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Nimble blind check (local Ollama only).")
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="Write labels.csv for blind labelling")
    export.add_argument("--force", action="store_true", help="Overwrite an existing labels.csv")
    export.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT), help="Read-only state dir")
    export.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output dir (never under data/)")
    export.add_argument("--base-url", default=DEFAULT_BASE_URL, help="App UI base URL for job links")
    export.set_defaults(func=cmd_export)

    run = sub.add_parser("run", help="Ask Nimble and write the report (or --smoke)")
    run.add_argument("--smoke", action="store_true", help="Send ONE built-in sample ad; print keys/tokens/latency")
    run.add_argument("--force", action="store_true", help="Ignore cached results and ask again")
    run.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT), help="Read-only state dir")
    run.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output dir (never under data/)")
    run.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Candidate profile JSON (target_roles only)")
    run.set_defaults(func=cmd_run)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
