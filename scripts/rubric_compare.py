"""Compare the old (1/3/5 anchor) and new (5 described levels, Slice 3) qualitative
rubric on N stored jobs. Read-only: nothing under data/ is written; results go to
archive/rubric-compare/. Uses the app's Gemini chain (job_hunt_llm), 2 calls per job.

Usage (repo root, project venv):
    venv/bin/python scripts/rubric_compare.py --profile data/<your-profile>.json --n 10
    venv/bin/python scripts/rubric_compare.py --profile ... --dry-run   # prompts only, no calls

Does NOT reserve the app's daily LLM quota counter (digest_llm_rpd); 2*N calls.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.job_hunt_profile import load_candidate_profile  # noqa: E402
from src.job_hunt_qualitative import DIMENSIONS, build_qualitative_prompt, parse_and_validate  # noqa: E402
from src.job_hunt_storage import load_reviewed_job  # noqa: E402

# Exact rubric block used before Slice 3 (commit 3f252e4^).
OLD_RUBRIC_BLOCK = """Rubrics:
- seniority_fit: 1 = clearly too junior/senior, 3 = unclear or partial match, 5 = strong seniority match.
- culture_signals: 1 = evidence of poor fit or unhealthy signals, 3 = little/no evidence, 5 = strong positive signals.
- red_flags: 1 = material red flags, 3 = limited/unclear warning signs, 5 = no meaningful red flags in the JD.
- role_archetype_alignment: 1 = poor alignment with target roles, 3 = mixed/unclear, 5 = strong archetype match.
"""
NEW_BLOCK_START = "Rubrics (every level is defined"
CAP_DIMENSIONS = ("culture_signals", "red_flags")   # derive_grade caps at score <= 2


def old_prompt(new_prompt: str) -> str:
    start = new_prompt.index(NEW_BLOCK_START)
    end = new_prompt.index("\nRules:", start)
    return new_prompt[:start] + OLD_RUBRIC_BLOCK + new_prompt[end:]


def pick_jobs(state_root: Path, n: int) -> list[str]:
    files = sorted((state_root / "reviewed_jobs").glob("*.json"))
    picked = []
    for f in files:
        try:
            job = load_reviewed_job(f.stem, state_root)
        except Exception:
            continue
        if len(job.description_raw or "") >= 500:
            picked.append(f.stem)
        if len(picked) >= n:
            break
    return picked


def scores(result) -> dict[str, int | None]:
    if not isinstance(result, dict):
        return {d: None for d in DIMENSIONS}
    dims = result.get("dimensions", {})
    return {d: (dims.get(d) or {}).get("score") if isinstance(dims.get(d), dict) else None for d in DIMENSIONS}


def run_one(prompt: str, jd: str, allow_unknown: bool) -> tuple[dict, str]:
    from src.job_hunt_llm import _call_gemini_reasoning
    raw, error, model, _all429 = _call_gemini_reasoning(prompt)
    if raw is None:
        return {d: None for d in DIMENSIONS}, f"error: {error}"
    parsed = parse_and_validate(raw, jd, allow_unknown_archetype=allow_unknown)
    if not isinstance(parsed, dict):
        return {d: None for d in DIMENSIONS}, f"invalid: {getattr(parsed, 'code', parsed)}"
    return scores(parsed), f"ok ({model})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--state-root", default="data/state")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--sleep", type=float, default=4.0, help="seconds between Gemini calls")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    state_root = Path(args.state_root)
    profile = load_candidate_profile(args.profile)
    allow_unknown = not [r for r in profile.target_roles if str(r).strip()]
    job_ids = pick_jobs(state_root, args.n)
    out_dir = ROOT / "archive" / "rubric-compare"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for job_id in job_ids:
        job = load_reviewed_job(job_id, state_root)
        new_p = build_qualitative_prompt(job.description_raw, profile)
        old_p = old_prompt(new_p)
        if args.dry_run:
            (out_dir / f"{job_id}.old.txt").write_text(old_p, encoding="utf-8")
            (out_dir / f"{job_id}.new.txt").write_text(new_p, encoding="utf-8")
            continue
        old_s, old_status = run_one(old_p, job.description_raw, allow_unknown)
        time.sleep(args.sleep)
        new_s, new_status = run_one(new_p, job.description_raw, allow_unknown)
        time.sleep(args.sleep)
        rows.append({"job_id": job_id, "title": job.job_title, "old": old_s, "new": new_s,
                     "old_status": old_status, "new_status": new_status})
        print(job_id, old_status, new_status, flush=True)

    if args.dry_run:
        print(f"dry run: wrote {2 * len(job_ids)} prompts to {out_dir}")
        return 0

    stamp = date.today().isoformat()
    (out_dir / f"results-{stamp}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    lines = [f"# Rubric comparison {stamp}", "",
             f"Jobs: {len(rows)} (first {args.n} stored jobs with description >= 500 chars). "
             "Old = pre-Slice-3 1/3/5 anchors; new = 5 described levels. One sample each — "
             "differences include normal model variance.", "",
             "| Job | Dimension | Old | New | Δ |", "|---|---|---|---|---|"]
    diffs = {d: [] for d in DIMENSIONS}
    cap_flips = 0
    for r in rows:
        for d in DIMENSIONS:
            o, n = r["old"][d], r["new"][d]
            delta = (n - o) if isinstance(o, int) and isinstance(n, int) else None
            if delta is not None:
                diffs[d].append(abs(delta))
                if d in CAP_DIMENSIONS and ((o <= 2) != (n <= 2)):
                    cap_flips += 1
            lines.append(f"| {r['job_id']} | {d} | {o} | {n} | {'' if delta is None else f'{delta:+d}'} |")
    lines += ["", "## Summary", ""]
    for d in DIMENSIONS:
        v = diffs[d]
        lines.append(f"- {d}: compared {len(v)}, mean |Δ| {sum(v) / len(v):.2f}, changed {sum(1 for x in v if x)}" if v
                     else f"- {d}: no comparable pairs")
    lines.append(f"- Grade-cap trigger flips (culture/red_flags crossing <= 2): {cap_flips}")
    errors = [r for r in rows if not (r['old_status'].startswith('ok') and r['new_status'].startswith('ok'))]
    lines.append(f"- Jobs with an error/invalid response: {len(errors)}")
    report = out_dir / f"report-{stamp}.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
