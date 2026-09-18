# Search Triage — Not-Interested Hide/Unhide + Page-Replace Pagination Design

<!-- STATUS -->
> **Implementation status:** ✅ Implemented 2026-07-02
> **Divergences from spec:** none — this spec was written retrospectively from the approved design-council plan and matches the shipped code.
> **Key functions:** `job_hunt_not_interested.py` (`hide_jobs`, `unhide_jobs`, `list_hidden`, `count_hidden`, `filter_results`, `make_key`, `make_fingerprint`); `ui_handlers` (`handle_jobs_hide`, `handle_jobs_unhide`, `handle_jobs_hidden_list`); `_multiselect.py` (`jstHide`, `jstUndoHide`, `jstHideUnticked`, `jstShowHidden`, `jstLoadMore`, `hide_attrs`)
> **Routes:** `POST /jobs/not-interested`, `POST /jobs/not-interested/undo`, `GET /jobs/not-interested`
<!-- /STATUS -->

**Status:** ✅ Implemented 2026-07-02 — design-council flow with independent read-only Codex review (18 findings); user approved the revised model.
**Date:** 2026-07-02
**Owner:** Mic
**Tests:** `tests/test_not_interested.py` (13) + `tests/test_multiselect_shared.py` regression suite.

## Problem

The Find Jobs results grid had three UX defects:

1. **Append-forever list** — "More jobs" appended every batch into the same container; a long session produced an unbounded list.
2. **Auto-select-all** — every card was ticked on load, so the tick carried no intent and batch evaluation started from "everything".
3. **No way to dismiss** — uninteresting jobs could not be removed and reappeared verbatim on every future search of the same criteria.

The user's initial ask was a "Next page" button plus a bulk "Remove selected" button.

## Codex review — why "Remove selected" was rejected

The independent Codex review (read-only, 18 findings) flagged the original model as unsafe:

- **Mode confusion (high):** one checkbox driving two opposite actions (evaluate vs remove) trains "tick = good" and will eventually delete a shortlist.
- **Invisible-state destruction (high):** with forward-only paging, "Remove selected" could act on ticked jobs from earlier pages the user can no longer see.
- **Broken-looking pages (high):** display-filtering with raw-count paging can produce a 0-card page with a live Next button — must be explained, never blank.
- **Concurrency (high):** a read-modify-write JSON store loses writes; SQLite is simpler and safer here.
- **Unstable ids (med):** LinkedIn scrape ids change between fetches; a key-only filter silently stops working.

## Confirmed decisions (user-approved)

- Cards start **unticked**; tick = "shortlist for evaluation" ONLY.
- Hiding is its own affordance: per-card **✕** and a bulk **"Hide unticked on this page"** (visible cards only — never off-page).
- Hidden jobs are **persisted** and filtered from all future searches; 10-second undo toast; **"Hidden jobs (N)"** overlay lists the store with per-row Unhide.
- **"Next page" replaces** the list (forward-only, no Previous). Shortlisted jobs survive page changes.
- Unhidden jobs reappear in *future* searches, not the current page (stated in the overlay).

## Design

### Store — `src/job_hunt_not_interested.py`

- Table `not_interested_jobs` in the shared `job_hunt_index.db` (same WAL/busy-timeout plumbing as `job_hunt_saved_searches`).
- Primary key `"{source}:{source_job_id}"`; when a source yields no id, the fingerprint is the key.
- Secondary **fingerprint** `sha1("{source}|{title}|{company}")` (lowercased, whitespace-squashed), indexed; the filter matches key OR fingerprint so unstable LinkedIn ids still filter. Both are source-scoped (`reed:101` ≠ `adzuna:101`).
- Rows older than **180 days** are pruned opportunistically on write (adverts expire long before that).
- `hide_jobs` is idempotent (`hidden` vs `already_hidden` in the response); input validated (`^[a-z0-9_-]{1,32}$` source, 300-char text caps, ≤50 per batch).

### HTTP surface

| Method | Path | Purpose |
|---|---|---|
| POST | `/jobs/not-interested` | Hide; body `{jobs:[{source, source_job_id, title, company}]}`; returns per-entry `keys` (client keeps them for undo) + `total_hidden`. |
| POST | `/jobs/not-interested/undo` | Delete keys; shared by the undo toast and the overlay's Unhide. |
| GET | `/jobs/not-interested` | Full list, newest first, for the overlay + footer count. |

`handle_source_search` and `handle_source_search_more` run `filter_results` **before rendering only** — `has_more` and the next skip cursor stay on the RAW count so the source-page cursor always advances one full page. `/more` JSON adds `visible_count` + `hidden_count`. A fully-filtered page renders an explanatory placeholder ("All N jobs on this page are hidden…"), never a blank page.

### Client — `src/job_sources/_multiselect.py`

- Registration no longer auto-adds cards to the selection; it injects the ✕ button (guarded, so re-running the script is safe).
- `jstHide(ids)` reads identity from card `data-jst-source`/`data-jst-sjid` attrs (emitted by `hide_attrs(result)` in all three card renderers), POSTs, removes the DOM nodes but keeps them in memory for `jstUndoHide` reinsertion.
- `jstLoadMore` (button label "Next page") clears `.jst-rc` cards; ticked cards' **form fields are captured into `_jobs[id].fields` first**, so `jstEvaluateAll` still evaluates cross-page shortlists (detached forms are not findable by `getElementById`). Unticked cards are dropped from memory. Action bar shows "· N from earlier pages".
- `STAGING_OVERLAY` constant also carries the hidden-jobs overlay + toast markup so the three source renderers needed no chrome edits; `more_button_html()` kept its name but renders the whole footer and always renders (Next button only when `more_url`).

## Non-goals

Previous-page navigation; look-ahead refill of fully-hidden pages (TRIAGE-F2); search/filter inside the overlay (TRIAGE-F3); digest integration of the hide store.

## Residual risks

- "Hide unticked on this page" can hide up to a whole page in one click — mitigated by whole-batch undo and the overlay; entries are never truly lost until pruned.
- Fingerprint ties hide-state to exact title+company; a retitled repost of the same job will reappear (acceptable — it is arguably a new advert).
- One POST per ✕ click — trivial for a local single-user app.

## Test map

`tests/test_not_interested.py`: hide/list round-trip · idempotent re-hide · unhide + unknown keys · fingerprint-fallback key · invalid source · filter by key / by fingerprint / noop / source-scoped keys · 180-day prune · live-server endpoint flow (hide→list→undo→re-hide) · bad request bodies · browser contract (no auto-select, ✕/overlay/Next wiring, footer without next page).
