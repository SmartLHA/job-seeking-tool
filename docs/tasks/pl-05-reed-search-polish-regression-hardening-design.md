# PL-05 — Reed Search Polish, Fallback Safety, and Regression Hardening Design

**Status:** Design draft — review pending
**Story:** PL-05 from `docs/tasks/reed-search-first-story-breakdown.md`
**Date:** 2026-05-13
**Owner:** SilverHand

## Problem

PL-01 through PL-04 created the core Reed search-first journey:

```text
Open app → Search Reed → Select job → Review prefilled Evaluate form → Evaluate → raw source audit stored
```

The remaining slice is to harden the user experience and regression safety: clear empty/error states, fallback discoverability, documentation of limitations/future sources, and a final smoke/check that the full Reed-first MVP flow is coherent.

## Confirmed Decisions

- Manual input / URL / paste remains as fallback.
- Reed is the only source in this phase.
- Adzuna and LinkedIn are future sources only.
- Unsupported filters must be honest/best-effort, not fabricated.
- No auto-evaluate.
- No auto-apply.

## Confirmed Evidence

- PL-01 QA PASS: Search-first shell.
- PL-02 QA PASS: Reed search form and `/search/reed` result rendering.
- PL-03 QA PASS: Select Reed result → prefilled Evaluate; selection alone read-only.
- PL-04 QA PASS: Evaluating selected Reed job stores separate raw `source_snapshot`.

## Root Cause Claim / Proof Level

**Claim:** The technical flow is now implemented, but final user-facing polish and regression hardening are needed before treating the search-first Reed journey as ready to show/use.

**Proof level:** Prior PL QA passed each functional slice, but no final slice yet verifies combined usability, limitations text, future-source extension notes, and fallback safety as one product journey.

## Non-Goals

- Do not implement Adzuna.
- Do not implement LinkedIn.
- Do not auto-evaluate or auto-apply.
- Do not redesign the whole UI.
- Do not change scoring/decision logic.
- Do not require live Reed API credentials for deterministic QA.

## Architecture Decision

Keep PL-05 as a polish/hardening slice only. It should refine copy, empty/error states, fallback links, and docs/tests without changing the core architecture. If defects are found in prior PL behavior, fix only small targeted issues needed for the accepted Reed-first flow.

## Scope

### In
- Improve Search Jobs empty/error/loading-style copy where static app allows.
- Ensure Manual Fallback is visible from search, no-results, and Reed-error states.
- Ensure Evaluate page makes review-before-evaluate clear when prefilled from Reed.
- Add/refresh docs describing:
  - Reed-only current source
  - Adzuna/LinkedIn future extension points
  - optional filters are best-effort when Reed does not support/confirm them
  - manual fallback remains available
- Add/confirm tests for:
  - no-results state
  - Reed error state
  - fallback links from search/error/no-result paths
  - combined Search → Select → Evaluate storage path via deterministic stub tests
- Update story breakdown status if appropriate.

### Out
- New source adapters.
- Full visual redesign.
- Production deployment changes.
- Live Reed credentials handling.

## Data Flow

No new data flow is expected. PL-05 verifies and polishes the existing flow:

```text
/search/reed → results/empty/error → select → evaluate → raw/reviewed/analysis storage
```

## Changed Files Expected

- `src/job_hunt_ui.py`
  - Copy/state/fallback-link improvements only.
  - Small fixes if combined flow exposes a defect.
- `tests/test_ui.py`
  - Additional regression tests for state/fallback/full deterministic flow if missing.
- `README.md` and/or `docs/ui_scope.md`
  - Document current Reed-first workflow and limitations.
- `docs/tasks/reed-search-first-story-breakdown.md`
  - Mark PL statuses or add final implementation note if useful.
- `PROJECT_LOG.md` / `INDEX.md`
  - Update after completion.

## Implementation Plan

1. Inspect current UI copy and tests from PL-01 through PL-04.
2. Identify minimal polish gaps only.
3. Add or refine user-facing copy for:
   - no Reed results
   - Reed unavailable / API key missing / 401
   - optional filters as best-effort
   - manual fallback
   - review-before-evaluate
4. Add deterministic tests for final combined flow if not already present.
5. Update docs to describe the new first-page workflow and future source boundaries.
6. Run focused UI/storage/orchestrator/integration tests.
7. Run a final live smoke on a temporary port verifying home/search endpoints do not crash.

## Edge Cases Handled

- Reed returns no results → clear no-results message and fallback link.
- Reed API missing/401/unavailable → clear error/fallback, no crash.
- User wants manual input → reachable from search/no-results/error.
- Optional filters cannot be confirmed → visible filter notes.
- Selected Reed job evaluated → raw source snapshot remains separate.

## Test Plan

### Unit / UI tests
- No-results state contains fallback message/link.
- Reed error state contains fallback message/link.
- Search page includes best-effort filter note.
- Combined deterministic flow still proves source snapshot raw storage and reviewed/analysis separation.

### Regression
- `tests/test_ui.py`
- `tests/test_storage.py`
- `tests/test_orchestrator.py`
- `tests/test_integration_flow.py`

### Smoke
- Start app on temporary port.
- GET `/` → HTTP 200 and Search Jobs visible.
- GET `/search/reed?...` → HTTP 200 and either results/no-results/error state visible.
- Confirm temp process stopped.

## Validation Commands

```bash
cd "/Users/lhaclaw/AI-Project-Workspace/job_hunt_Job Seeking Tool"
python3 -m pytest tests/test_ui.py -v --tb=short
python3 -m pytest tests/test_storage.py tests/test_orchestrator.py tests/test_integration_flow.py -v --tb=short
```

## Acceptance Criteria

- Reed-first journey has clear UX for success, empty, and error states.
- Manual fallback remains visibly reachable from all relevant states.
- Current source limitations and future source boundaries are documented.
- Deterministic tests prove final combined flow and regression safety.
- Live smoke on temporary port passes without leaving a server running.

## Open Engineering Questions

None blocking. Keep this slice intentionally small.
