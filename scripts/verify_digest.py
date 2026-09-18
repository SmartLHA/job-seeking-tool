#!/usr/bin/env python3
"""Live check for the Daily Job Digest D3 pipeline (run on YOUR machine).

The sandbox can't reach the Reed/Adzuna APIs, so this script lets you confirm the
deterministic pipeline end-to-end against the real APIs locally. It fetches one
saved search, scores the new jobs, indexes them, and prints the DigestRunResult.

Usage:
    python3 scripts/verify_digest.py --profile data/<your_profile>.json \
        --source reed --keywords "business analyst" --location London [--max 5]

Or run an existing saved search by id:
    python3 scripts/verify_digest.py --profile data/<your_profile>.json \
        --saved-search <search_id>

Requires REED_API_KEY / ADZUNA_APP_ID+ADZUNA_APP_KEY in your environment or .env.
Nothing is submitted anywhere; this only reads job listings and writes local state.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `src` importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from src.job_hunt_profile import load_candidate_profile          # noqa: E402
from src.job_hunt_saved_searches import SavedSearch, load_saved_search  # noqa: E402
from src.job_hunt_storage import ensure_storage_layout            # noqa: E402
from src.job_hunt_scheduler import run_digest_pipeline            # noqa: E402
# Source registration side effects:
from src.job_sources import reed_source as _reed                 # noqa: E402,F401
from src.job_sources import adzuna_source as _adzuna             # noqa: E402,F401


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Live digest-pipeline check (local only).")
    p.add_argument("--profile", required=True, help="Path to candidate profile JSON")
    p.add_argument("--state-root", default="data/state")
    p.add_argument("--saved-search", help="Run an existing saved search by id")
    p.add_argument("--source", default="reed", help="reed | adzuna (when not using --saved-search)")
    p.add_argument("--keywords", default="business analyst")
    p.add_argument("--location", default="London")
    p.add_argument("--max", type=int, default=5, help="Cap jobs fetched (overrides profile for this run)")
    args = p.parse_args(argv)

    state_root = Path(args.state_root)
    ensure_storage_layout(state_root)
    db_path = state_root / "job_hunt_index.db"

    profile = load_candidate_profile(Path(args.profile))
    # Cap the fetch for a quick check without mutating the saved profile on disk.
    try:
        object.__setattr__(profile, "digest_max_per_source", min(args.max, profile.digest_max_per_source))
    except Exception:
        pass

    if args.saved_search:
        search = load_saved_search(args.saved_search, state_root=state_root)
    else:
        search = SavedSearch(
            search_id="live-check", name="live check", source_id=args.source,
            params={"keywords": args.keywords, "locationName": args.location},
            enabled=True, created_at="", last_run_at=None, last_run_count=0,
        )

    class _Cfg:
        pass
    cfg = _Cfg()
    cfg.state_root = state_root
    cfg.profile_path = Path(args.profile)

    print(f"Running digest for source={search.source_id!r} params={search.params} ...")
    result = run_digest_pipeline(config=cfg, saved_searches=[search], profile=profile, db_path=db_path)

    print("\n=== DigestRunResult ===")
    for k, v in result.to_dict().items():
        print(f"  {k}: {v}")
    print("\nOpen the app and visit /digest to see the feed (after D4), or query the index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
