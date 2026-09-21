"""In-memory per-search dedup state for paginated ("Show more") search results.

Slice B of the 2026-07-21 search/score/filter plan (docs/tasks/2026-07-21-
search-score-filter-plan.md): dedup must survive across ``/search/{source}/
more`` pages without a single global seen-set, because the server is a
``ThreadingHTTPServer`` and two concurrent searches (or two tabs) must not
share state. State is keyed by a random search-id minted on the FIRST page of
a search, guarded by a lock, and expired after a TTL so memory does not grow
unbounded across a long-running process. A brand-new search always mints a
fresh search-id, so it never inherits another search's seen-set.

Reuses ``job_sources.dedup.is_duplicate_job`` for the identity check rather
than reimplementing it.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from src.job_sources.dedup import is_duplicate_job

_LOCK = threading.Lock()
_STATE: dict[str, dict[str, Any]] = {}

# A search-id is used across "Show more" clicks within one browser search; an
# hour is generous for a single sitting while keeping memory bounded.
SEARCH_STATE_TTL_SECONDS = 3600
# Belt-and-braces cap so a runaway client can't grow this dict unbounded even
# inside the TTL window.
MAX_TRACKED_SEARCHES = 500


def _prune_locked(now: float) -> None:
    """Must be called while holding `_LOCK`."""
    expired = [sid for sid, st in _STATE.items() if now - st["created"] > SEARCH_STATE_TTL_SECONDS]
    for sid in expired:
        del _STATE[sid]
    if len(_STATE) > MAX_TRACKED_SEARCHES:
        by_age = sorted(_STATE.items(), key=lambda kv: kv[1]["created"])
        for sid, _st in by_age[: len(_STATE) - MAX_TRACKED_SEARCHES]:
            del _STATE[sid]


def start_search(seen_jobs: list[dict]) -> str:
    """Register a NEW search (its first page) and return a fresh search-id.

    `seen_jobs` are the jobs already rendered on the first page; later
    "Show more" pages for this search-id are filtered against them (and
    against each other) via `filter_new_page`.
    """
    with _LOCK:
        now = time.time()
        _prune_locked(now)
        search_id = uuid.uuid4().hex
        _STATE[search_id] = {"seen": list(seen_jobs), "created": now}
        return search_id


def filter_new_page(search_id: str | None, page_jobs: list[dict]) -> list[dict]:
    """Return the subset of `page_jobs` not already shown for `search_id`.

    Safe for concurrent calls (guarded by `_LOCK`). If `search_id` is
    unknown (expired, or a "more" link followed after a process restart)
    this fails open: nothing from `page_jobs` is dropped for being "already
    seen" across pages, but the page is still deduplicated against itself so
    a single response never repeats a card.
    """
    with _LOCK:
        state = _STATE.get(search_id) if search_id else None
        seen: list[dict] = state["seen"] if state is not None else []
        combined = list(seen)
        result: list[dict] = []
        for job in page_jobs:
            if not any(is_duplicate_job(job, prior) for prior in combined):
                combined.append(job)
                result.append(job)
        if state is not None:
            state["seen"] = combined
        return result


def known_search(search_id: str | None) -> bool:
    with _LOCK:
        return bool(search_id) and search_id in _STATE


def _reset_for_tests() -> None:
    """Test-only helper: clear all tracked search state."""
    with _LOCK:
        _STATE.clear()
