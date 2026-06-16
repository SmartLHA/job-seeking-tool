# PL-03 — Select Reed Job to Prefill Review/Evaluate Form Design

**Status:** Design draft — review pending
**Story:** PL-03 from `docs/tasks/reed-search-first-story-breakdown.md`
**Date:** 2026-05-13
**Owner:** SilverHand

## Problem

PL-02 lets the user search Reed and see results inside the app, but the result list is not yet connected to the existing Evaluate flow. The user still cannot choose a Reed job and have its details prefilled for review/evaluation.

PL-03 connects one selected Reed result to the existing reviewed job form. The user must still review/edit the fields and click Evaluate manually.

## Confirmed Decisions

- User flow: Search Reed → Select job → Review prefilled Evaluate form → user clicks Evaluate.
- No auto-evaluate after selection.
- Capture as much Reed data as possible.
- Raw Reed audit storage is PL-04, not this PL.
- Manual fallback remains available.
- Reed only in this phase.

## Confirmed Evidence

- PL-01 QA passed: app defaults to Search Jobs shell.
- PL-02 QA passed: app-native Reed search form, `/search/reed`, and result rendering work.
- Existing Evaluate form is rendered by `render_input_form(values)` inside `src/job_hunt_ui.py`.
- Existing evaluation path is `POST /evaluate`, which consumes reviewed form fields and stores reviewed job / analysis / raw input based on current form payload.

## Root Cause Claim / Proof Level

**Claim:** Search results are display-only; no selected Reed job is transformed into the existing Evaluate form values yet.

**Proof level:** PL-02 scope intentionally stopped at search/result rendering and explicitly left select→prefill to PL-03.

## Non-Goals

- Do not auto-run evaluation.
- Do not implement raw Reed audit storage; PL-04 handles separate original Reed response storage.
- Do not implement Adzuna/LinkedIn.
- Do not remove Manual Fallback.
- Do not alter scoring/decision logic.
- Do not build a full job details modal unless necessary for prefill.

## Architecture Decision

Add a selection action to each rendered Reed result that sends a safe encoded representation or stable result reference back to the app, then renders the existing Evaluate tab with prefilled `values`. The prefilled values must use the existing reviewed-job form contract so downstream `POST /evaluate` remains unchanged.

Because PL-04 will implement audit storage, PL-03 should avoid creating durable raw-response records. If the selected job payload must round-trip through the browser, keep it bounded and signed/escaped enough for local app usage, or use a temporary in-memory/session-light approach if already present. Simplicity and local-first safety matter more than persistence in this PL.

## Data Flow

```text
Search Jobs tab
  → Reed result card shows Select / Review this job
  → user clicks Select
  → app maps selected Reed normalized fields to existing Evaluate form values
  → app renders /?tab=evaluate with prefilled fields
  → user reviews/edits
  → user clicks Evaluate
  → existing POST /evaluate path runs unchanged
```

## Mapping Target

Verified existing form field names in `src/job_hunt_ui.py` before implementation:

- `job_id`
- `input_method`
- `job_url`
- `source_type`
- `source_ref`
- `job_title`
- `company`
- `location`
- `work_mode`
- `employment_type`
- `required_years_experience`
- `nice_to_have_years_experience`
- `domain`
- `salary_min_gbp`
- `salary_max_gbp`
- `copied_text`
- `description_raw`
- `required_skills`
- `preferred_skills`
- `notes`

Map best available Reed result fields into those existing Evaluate form values:

- `job_id`: deterministic local ID from Reed source/id/title/company where possible; avoid collisions where practical
- `job_title`: Reed title or Unknown
- `company`: Reed company or Unknown
- `location`: Reed location or blank/Unknown depending current form expectations
- `description_raw`: Reed description/preview or full description if available; max 500 chars with ellipsis if truncated in PL-03
- `salary_min_gbp` / `salary_max_gbp`: from Reed salary fields where parseable
- `employment_type`: Reed contract type where available
- `work_mode`: Reed remote/hybrid/onsite inference where available
- `source_type`: `reed`
- `source_ref`: Reed source job id/reference where available
- `job_url`: Reed URL if available
- `input_method`: `reed_search`
- `copied_text`: optional source snapshot/description text only; do not fabricate
- `required_skills` / `preferred_skills`: only if available/inferable from normalized data; otherwise leave blank

## Changed Files Expected

- `src/job_hunt_ui.py`
  - Add Select action/form/link to each Reed result card.
  - Add handler/route for selecting a Reed result, likely `POST /select/reed` or `GET /select/reed` depending payload safety.
  - Add mapper from Reed UI result/raw result into existing Evaluate form values.
  - Render Evaluate tab with prefilled values after selection.
- `tests/test_ui.py`
  - Test selected Reed result pre-fills Evaluate form fields.
  - Test user still must click Evaluate; selection alone does not write analysis/storage.
  - Test missing Reed fields do not crash and leave editable fields safe.
  - Regression: existing manual Evaluate and fallback still work.

## Implementation Plan

1. Inspect existing form field contract in `default_form_values()`, `render_input_form()`, and `reviewed_job_payload_from_form()`.
2. Use a small `POST /select/reed` form with hidden escaped fields from the displayed normalized result.
3. Add simple CSRF-style nonce protection suitable for this local stdlib app. If no existing session framework exists, use a short-lived in-memory token generated on the Search page and required by `/select/reed`; invalid/missing token returns a clear 400 error.
4. Validate all posted hidden fields: max lengths, numeric salary fields, allowed source/input method values, and HTML escaping on render.
5. Add Select button to each result card.
6. Implement `reed_result_to_form_values()` mapper.
7. On select, render home page with `tab="evaluate"` and `values=prefilled_values`.
8. Add visible note in Evaluate tab that the fields came from Reed and must be reviewed before evaluation.
9. Add deterministic tests using stubbed Reed result data.
10. Confirm selecting does not create analysis/raw files until `POST /evaluate`.

## Edge Cases Handled

- Missing title/company/location → prefill safe unknown/blank values and allow edit.
- Missing salary → leave salary fields blank.
- Bad/malicious HTML in Reed result → rendered and posted values are escaped safely.
- Very long description → truncate to 500 characters plus ellipsis and include a note that the user should review the source advert.
- Selection without required fields → still renders editable Evaluate form; final validation happens on Evaluate.
- User cancels/changes mind → can return to Search Jobs or Manual Fallback.

## Test Plan

### Unit / UI handler tests
- Stub a Reed search result, click/post select action, assert Evaluate tab renders with title/company/location/description/source URL prefilled.
- Assert selected page includes review-before-evaluate guidance.
- Assert no analysis/reviewed/raw files are created by selection alone.
- Missing optional Reed fields render safely.
- HTML special characters are escaped.

### Regression
- PL-01/PL-02 UI tests still pass.
- Existing `POST /evaluate` tests still pass.
- Orchestrator/integration tests still pass.

### Smoke
- Start app on temporary port.
- Use stubbed test or manual known result if available.
- Verify Search → Select renders Evaluate form.
- Do not require live Reed availability for deterministic QA.

## Validation Commands

```bash
cd "/Users/lhaclaw/AI-Project-Workspace/job_hunt_Job Seeking Tool"
python3 -m pytest tests/test_ui.py -v --tb=short
python3 -m pytest tests/test_orchestrator.py tests/test_integration_flow.py -v --tb=short
```

## Acceptance Criteria

- Each Reed result has a Select / Review action.
- Selecting a Reed result opens/renders the Evaluate form with best-available fields prefilled.
- User must manually click Evaluate; selection alone does not run evaluation.
- Selection alone does not create durable analysis/raw audit records.
- Missing/unsafe data is handled without crash or HTML injection.
- Manual Fallback remains available.

## Open Engineering Questions

1. Exact form field names for source URL/source type must be verified during build.
2. Final route method is `POST /select/reed` with local CSRF-style nonce and input validation.
3. If Reed result cards currently only have normalized preview, determine whether full description is available enough for useful prefill in PL-03 or deferred to PL-04/raw/detail fetch.
