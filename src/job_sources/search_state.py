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

from collections import OrderedDict
import copy
from dataclasses import dataclass
import json
import threading
import time
import uuid
from typing import Any, Callable

from src.job_sources.dedup import is_duplicate_job

_LOCK = threading.Lock()
_STATE: dict[str, dict[str, Any]] = {}

# A search-id is used across "Show more" clicks within one browser search; an
# hour is generous for a single sitting while keeping memory bounded.
SEARCH_STATE_TTL_SECONDS = 3600
# Belt-and-braces cap so a runaway client can't grow this dict unbounded even
# inside the TTL window.
MAX_TRACKED_SEARCHES = 500
MAX_REPLAY_PAGES_PER_SEARCH = 8
MAX_REPLAY_BYTES_PER_SEARCH = 2 * 1024 * 1024
MAX_TOTAL_REPLAY_BYTES = 32 * 1024 * 1024
MAX_SEEN_JOBS_PER_SEARCH = 2000

SearchCursor = tuple[int, tuple[int | None, ...]]
_SEEN_FIELDS = ("external_id", "source_job_id", "title", "company", "location_normalized",
                "location", "apply_url", "url", "description", "description_raw", "description_preview")


def _freeze_seen(jobs: list[dict]) -> list[dict]:
    """Retain only immutable scalar fields used by the existing dedup rule."""
    records = []
    for job in jobs:
        record = {key: job[key] for key in _SEEN_FIELDS if key in job}
        if any(value is not None and not isinstance(value, (str, int, float, bool))
               for value in record.values()):
            raise TypeError("Search identity fields must be scalar values")
        records.append(record)
    return records


class SearchRestartRequired(RuntimeError):
    """The search/cursor can no longer be replayed safely."""


@dataclass
class SearchPageDraft:
    """Request-local seen state; discarded unless the entire page commits."""
    seen: list[dict]

    def filter_new(self, jobs: list[dict]) -> list[dict]:
        result = []
        for job in jobs:
            if not any(is_duplicate_job(job, prior) for prior in self.seen):
                self.seen.append(job)
                result.append(job)
        return result


@dataclass(frozen=True)
class PreparedSearchPage:
    payload: dict[str, Any]
    next_cursor: SearchCursor | None


def _prune_locked(now: float, *, protected_id: str | None = None) -> None:
    """Must be called while holding `_LOCK`."""
    expired = [sid for sid, st in _STATE.items() if now - st["created"] >= SEARCH_STATE_TTL_SECONDS]
    for sid in expired:
        del _STATE[sid]
    if len(_STATE) > MAX_TRACKED_SEARCHES:
        by_age = sorted(((sid, st) for sid, st in _STATE.items() if sid != protected_id),
                        key=lambda kv: kv[1]["created"])
        for sid, _st in by_age[: len(_STATE) - MAX_TRACKED_SEARCHES]:
            del _STATE[sid]
    for sid, state in sorted(_STATE.items(), key=lambda pair: pair[1]["created"]):
        if sum(st.get("replay_bytes", 0) for st in _STATE.values()) <= MAX_TOTAL_REPLAY_BYTES:
            break
        if sid != protected_id:
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
        _prune_locked(now, protected_id=search_id)
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
            state["revision"] = state.get("revision", 0) + 1
        return result


def commit_initial_search(
    search_id: str, binding: str, seen_jobs: list[dict], next_cursor: SearchCursor | None,
) -> None:
    """Register a fully rendered initial page immediately before its send.

    Initial GETs intentionally create fresh searches. Pagination retries use the
    separate preparation API below; legacy dedup helper semantics stay intact.
    """
    if len(seen_jobs) > MAX_SEEN_JOBS_PER_SEARCH:
        raise SearchRestartRequired("Search is too large. Restart with narrower search criteria.")
    frozen_seen = _freeze_seen(seen_jobs)
    with _LOCK:
        now = time.time()
        _STATE[search_id] = {
            "seen": frozen_seen, "created": now, "binding": binding,
            "next_cursor": next_cursor, "page_lock": threading.Lock(),
            "replays": OrderedDict(), "replay_bytes": 0, "revision": 0,
        }
        _prune_locked(now, protected_id=search_id)


def prepare_page(
    search_id: str | None,
    binding: str,
    cursor: SearchCursor,
    producer: Callable[[SearchPageDraft], PreparedSearchPage],
    *,
    current_binding: Callable[[], str],
) -> dict[str, Any]:
    """Prepare once per cursor, then atomically commit response/seen/successor.

    Only the per-search lock spans provider work/rendering. Registry pruning
    never waits on that lock. Failed preparation/serialization consumes nothing;
    send failures occur later, leaving this exact JSON payload replayable.
    """
    def validate_locked(expected=None):
        _prune_locked(time.time(), protected_id=search_id)
        state = _STATE.get(search_id)
        if (state is None or state.get("binding") != binding
                or "page_lock" not in state or (expected is not None and state is not expected)):
            raise SearchRestartRequired("This search expired or changed. Restart the search to continue.")
        return state

    with _LOCK:
        state = validate_locked()
    with state["page_lock"]:
        with _LOCK:
            validate_locked(state)
            cached = state["replays"].get(cursor)
            if cached is None and cursor != state["next_cursor"]:
                raise SearchRestartRequired("This page is no longer available. Restart the search to continue.")
            seen = state["seen"]
            revision = state["revision"]
        if cached is not None:
            if current_binding() != binding:
                raise SearchRestartRequired("Search settings changed. Restart the search to continue.")
            with _LOCK:
                validate_locked(state)
            return json.loads(cached[0])
        draft = SearchPageDraft(copy.deepcopy(seen))
        prepared = producer(draft)
        if prepared.payload.get("ok") is not True:
            raise ValueError("Only successful search pages can be committed")
        encoded = json.dumps(prepared.payload, ensure_ascii=False, allow_nan=False)
        size = len(encoded.encode("utf-8"))
        if (size > min(MAX_REPLAY_BYTES_PER_SEARCH, MAX_TOTAL_REPLAY_BYTES)
                or len(draft.seen) > MAX_SEEN_JOBS_PER_SEARCH):
            raise SearchRestartRequired("Search is too large. Restart with narrower search criteria.")
        frozen_seen = _freeze_seen(draft.seen)
        if current_binding() != binding:
            raise SearchRestartRequired("Search settings changed. Restart the search to continue.")
        with _LOCK:
            validate_locked(state)
            if state["revision"] != revision:
                raise SearchRestartRequired("Search results changed. Restart the search to continue.")
            state["replays"][cursor] = (encoded, size)
            state["replay_bytes"] += size
            while (len(state["replays"]) > MAX_REPLAY_PAGES_PER_SEARCH
                   or state["replay_bytes"] > MAX_REPLAY_BYTES_PER_SEARCH):
                _old_cursor, (_old_payload, old_size) = state["replays"].popitem(last=False)
                state["replay_bytes"] -= old_size
            state["seen"] = frozen_seen
            state["next_cursor"] = prepared.next_cursor
            state["revision"] += 1
            _prune_locked(time.time(), protected_id=search_id)
        return json.loads(encoded)


def known_search(search_id: str | None) -> bool:
    with _LOCK:
        return bool(search_id) and search_id in _STATE


def _reset_for_tests() -> None:
    """Test-only helper: clear all tracked search state."""
    with _LOCK:
        _STATE.clear()
