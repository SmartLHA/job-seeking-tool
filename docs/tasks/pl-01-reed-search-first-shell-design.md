# PL-01 — App Landing Restructure: Search-First Shell Design

**Status:** Design draft — review pending
**Story:** PL-01 from `docs/tasks/reed-search-first-story-breakdown.md`
**Date:** 2026-05-13
**Owner:** SilverHand

## Problem

The current app journey opens on the manual Evaluate flow. Mic wants the app first/main page to start with job-source search, beginning with Reed, so the user can search/select a real job before entering the Evaluate step.

This PL is only the first shell restructure. It does **not** implement the full Reed search integration; it prepares the app navigation and primary flow so later PLs can wire search, selection, and audit storage cleanly.

## Confirmed Evidence

- Current real app server is `src/job_hunt_ui.py`.
- `GET /` currently renders `render_home_page(... tab="evaluate" ...)` by default.
- Existing app tabs are Evaluate, History, Add Job, My Profile.
- Mic confirmed:
  - Main page should be search-first.
  - Reed is the only source for this phase.
  - Manual/URL/paste should remain as fallback.
  - `reed_jobs_v4.html` should not be embedded; rebuild inside app style.

## Root Cause Claim / Proof Level

**Claim:** The current app navigation makes manual Evaluate the primary user journey because `/` defaults to `evaluate` and the search/source flow is not represented as the first-class app entry point.

**Proof level:** Direct source inspection of `src/job_hunt_ui.py` showed `GET /` reads `tab` and calls `_render_home(tab=tab)`, while `render_home_page()` renders top tabs with Evaluate as the first/default workflow.

## Non-Goals

- Do not implement full Reed API search in this PL.
- Do not implement result selection/prefill in this PL.
- Do not implement raw Reed audit storage in this PL.
- Do not remove manual/URL/paste fallback.
- Do not change scoring/decision logic.
- Do not change `reed_jobs_v4.html`; it is reference only.

## Architecture Decision

Change the app shell so `GET /` defaults to a new `search` tab/section. The new tab will present a Reed-search-first landing panel and route the manual flow into a fallback tab. This preserves existing evaluation internals while creating the correct product entry point for PL-02/PL-03.

## Data Flow

PL-01 data flow is mostly unchanged:

```text
GET / → render home page → default tab = search → user sees source-search shell
```

Existing evaluation flow remains available:

```text
Manual Fallback tab → existing form → POST /evaluate → existing evaluation/storage/reporting path
```

## Changed Files Expected

- `src/job_hunt_ui.py`
  - Add `search` as default tab.
  - Add Search Jobs tab before Evaluate/Manual fallback.
  - Rename or reposition current manual Add Job / Evaluate content as fallback where needed.
  - Add placeholder Reed search shell with clear “Reed only in this phase” copy.
- `tests/test_ui.py`
  - Add/adjust tests proving `/` renders search-first shell.
  - Add regression tests proving manual Evaluate/fallback still exists.
- `README.md` or relevant docs only if startup/navigation docs become stale.

## Implementation Plan

1. Update `do_GET /` default tab from `evaluate` to `search`.
2. Update `render_home_page()` tab navigation to include:
   - Search Jobs — default first tab
   - Evaluate / Review Selected Job — may initially point to existing Evaluate content
   - Manual Fallback — preserves manual/URL/paste input path
   - History
   - My Profile
3. Add `_render_search_jobs_tab()` or equivalent helper.
4. Keep all existing `POST /evaluate`, `/prefill`, `/job-submit`, `/profile`, `/outcome` behavior unchanged.
5. Add tests for default page content and fallback availability.

## Edge Cases Handled

- Unknown tab query parameter should not break rendering; app should fall back to search or existing safe behavior.
- Existing direct links like `/?tab=evaluate` should still work if feasible.
- Manual fallback remains reachable if Reed search is unavailable.
- Profile page routing remains separate and unaffected.

## Test Plan

### Unit / UI handler tests
- `GET /` returns 200 and includes Search Jobs / Reed-first shell.
- `GET /?tab=evaluate` or equivalent still exposes evaluation/review form.
- Manual fallback content is present/reachable.
- History/Profile navigation labels remain present.

### Integration / regression
- Existing UI tests for `POST /evaluate`, `GET /job/<id>`, `POST /outcome`, profile parse/save should remain passing.

### Smoke
- Start app on non-conflicting port, e.g. 8766.
- Open `/` and confirm search-first shell appears.
- Open fallback/evaluate tab and confirm manual evaluation form appears.

## Validation Commands

```bash
cd "/Users/lhaclaw/AI-Project-Workspace/job_hunt_Job Seeking Tool"
python3 -m pytest tests/test_ui.py -v --tb=short
python3 -m pytest tests/test_orchestrator.py tests/test_integration_flow.py -v --tb=short
PYTHONPATH=. python3 -m src.job_hunt_ui --profile data/demo_profile/candidate_profile.json --state-root data/state --report-dir output/reports --host 127.0.0.1 --port 8766
curl -s http://127.0.0.1:8766/ | grep -E "Search Jobs|Reed|Manual"
```

## Acceptance Criteria

- `GET /` opens Search Jobs by default.
- The first visible product direction is Reed job search, not manual job entry.
- Manual input remains reachable as fallback.
- Existing Evaluate/History/Profile functionality is not broken.
- No code path depends on `reed_jobs_v4.html` being embedded.

## Open Engineering Questions

None blocking for PL-01. PL-02 must decide exact API adapter contract and filter support truthfulness.
