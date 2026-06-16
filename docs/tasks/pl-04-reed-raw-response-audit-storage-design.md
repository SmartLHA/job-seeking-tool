# PL-04 — Reed Raw Response Audit Storage Design

**Status:** Design draft — review pending
**Story:** PL-04 from `docs/tasks/reed-search-first-story-breakdown.md`
**Date:** 2026-05-13
**Owner:** SilverHand

## Problem

PL-03 allows a user to select a Reed job and prefill the Evaluate form, but original Reed source data is still not stored as a separate audit record for selected/evaluated jobs. The project invariant requires raw input, reviewed job, and analysis to remain separate.

PL-04 adds truthful source audit storage for Reed-selected jobs without changing scoring logic or auto-evaluating behavior.

## Confirmed Decisions

- Store original Reed raw response separately for audit.
- Preserve existing separation:
  - raw input/source snapshot
  - reviewed job
  - analysis
- Selection still must not auto-evaluate.
- User still reviews before clicking Evaluate.
- Reed only in this phase.
- Adzuna/LinkedIn later.

## Confirmed Evidence

- PL-01 QA PASS: search-first shell.
- PL-02 QA PASS: Reed search form and `/search/reed` endpoint work; UI search uses `save_raw=False` to avoid premature raw writes.
- PL-03 QA PASS: selecting Reed result prefills Evaluate; selection alone does not create durable reviewed/raw/analysis files.
- Existing evaluation path `POST /evaluate` already builds `raw_input_payload_from_form()` from submitted form data.
- Existing storage layout has `raw_inputs/`, `reviewed_jobs/`, and `analyses/` folders.

## Root Cause Claim / Proof Level

**Claim:** The current selected Reed job can be evaluated from prefilled form values, but the original Reed payload/source snapshot is not yet preserved separately at the point of evaluation.

**Proof level:** PL-03 QA explicitly verified selection alone creates no raw/reviewed/analysis files, and PL-02 intentionally used `save_raw=False` for UI search.

## Non-Goals

- Do not auto-evaluate.
- Do not store raw audit data on search alone unless explicitly selected/evaluated.
- Do not implement Adzuna/LinkedIn.
- Do not remove manual fallback.
- Do not alter scoring/decision logic.
- Do not introduce a database migration unless absolutely necessary.

## Architecture Decision

Attach a bounded Reed `source_snapshot` JSON object to the hidden selected-job payload and carry it through the existing Evaluate form to `POST /evaluate`, where `raw_input_payload_from_form()` must include it in the raw input payload. The existing `save_raw_input()` already persists raw input payload dictionaries as-is, so a storage-layer schema migration is not expected; implementation must verify this with tests.

Required approach:
1. On Reed result rendering, build a compact structured `source_snapshot` object from the selected Reed result.
2. Include `source_snapshot_json` in the select form as a bounded hidden payload.
3. On `/select/reed`, validate the `source_snapshot_json`, enforce a 20KB serialized-size cap, and carry it into the Evaluate form as `source_snapshot_json`, without writing durable files yet.
4. On `/evaluate`, if `input_method == reed_search` / `source_type == reed`, `raw_input_payload_from_form()` must parse and validate `source_snapshot_json`, then include it as `source_snapshot` in the raw input payload.
5. Existing `save_raw_input()` must store `source_snapshot` under `raw_inputs/<job_id>.json` while reviewed job and analysis remain separate files.

This keeps selection read-only and makes audit storage happen only when the user confirms by clicking Evaluate.

## Data Flow

```text
Search Reed
  → normalized result card includes bounded source snapshot
  → Select / Review this job
  → /select/reed validates hidden fields + snapshot
  → Evaluate form prefilled + hidden source snapshot carried forward
  → user reviews and clicks Evaluate
  → POST /evaluate
  → reviewed job saved separately
  → raw Reed/source snapshot saved separately
  → analysis saved separately
```

## Audit Payload Shape

Raw input payload must include enough to trace the source without fabricating fields. For Reed-selected evaluations, `raw_inputs/<job_id>.json` must contain a top-level `source_snapshot` object:

```json
{
  "input_method": "reed_search",
  "source_type": "reed",
  "source_ref": "reed-job-id-or-url",
  "job_url": "https://...",
  "copied_text": "optional selected description text",
  "description_raw": "reviewed description used for scoring",
  "source_snapshot": {
    "source": "reed",
    "source_job_id": "...",
    "title": "...",
    "company": "...",
    "location": "...",
    "salary_min_gbp": "...",
    "salary_max_gbp": "...",
    "employment_type": "...",
    "work_mode": "...",
    "url": "...",
    "description_raw": "bounded source description",
    "captured_at": "ISO timestamp",
    "capture_stage": "select",
    "snapshot_version": "pl-04-v1"
  }
}
```

Required snapshot fields:
- `source` must equal `reed`
- `captured_at` must be present as an ISO timestamp string
- `capture_stage` must be `select`
- `description_raw` must represent the selected Reed source description/preview, bounded by implementation limits
- at least one source reference must exist: `source_job_id` or `url`

Existing storage tolerance check: `save_raw_input()` persists any dict payload as-is and only validates that payload is an object. Tests must prove `source_snapshot` round-trips through `save_raw_input()` / `load_raw_input()`.

## Changed Files Expected

- `src/job_hunt_ui.py`
  - Include bounded Reed `source_snapshot_json` in select form/result payload.
  - Validate structured source snapshot on `/select/reed`.
  - Carry source snapshot into Evaluate form.
  - Extend `raw_input_payload_from_form()` to include parsed `source_snapshot` for Reed search evaluations.
  - Enforce a 20KB serialized JSON cap for `source_snapshot_json`.
- `tests/test_ui.py`
  - Test selection alone still writes no files.
  - Test after selecting and submitting Evaluate, `raw_inputs/<job_id>.json` includes top-level `source_snapshot` with required fields.
  - Test reviewed job and analysis remain separate and do not absorb `source_snapshot`.
  - Test malformed/oversized source snapshot is rejected with clear validation failure.
- `tests/test_storage.py`
  - Add or confirm round-trip coverage for raw input payload containing nested `source_snapshot`.
- `src/job_hunt_storage.py`
  - Change only if current raw input storage cannot round-trip `source_snapshot`; source inspection suggests it likely can already store arbitrary dict payloads.

## Implementation Plan

1. Inspect existing raw input persistence expectations and tests.
2. Add a compact source snapshot builder from selected Reed result fields.
3. Bound snapshot size and field lengths; no full unbounded API response in hidden form.
4. Add hidden form field `source_snapshot_json` to the selected/prefilled Evaluate form for Reed-selected jobs.
5. Validate JSON, `source == "reed"`, required fields, at least one source reference, and 20KB serialized-size cap before accepting it.
6. Update `raw_input_payload_from_form()` to include validated snapshot only for Reed source/evaluation.
7. Ensure `save_raw_input()` writes the resulting raw payload as `raw_inputs/<job_id>.json`; add storage round-trip test if needed.
8. Add tests proving:
   - selection alone still writes nothing
   - evaluation after selection writes raw input with top-level `source_snapshot`
   - `source_snapshot` includes required audit fields including `captured_at` and `description_raw`
   - reviewed job and analysis remain separate and do not contain `source_snapshot`
   - malformed/oversized snapshot fails safely
9. Do not require live Reed availability; use deterministic stubbed result tests.

## Edge Cases Handled

- Missing source snapshot for `reed_search` → clear validation error; Reed audit is required once a Reed-selected job is evaluated.
- Oversized snapshot (>20KB serialized JSON) → reject with clear validation error; do not store unbounded hidden payload.
- Malformed JSON → clear validation error on Evaluate.
- HTML/script content in snapshot → stored as data and escaped when rendered.
- Reed URL missing → source_ref falls back to job id.
- User edits form after selection → reviewed job reflects edited fields; source snapshot remains original selected source context.

## Test Plan

### Unit / UI handler tests
- Select Reed result → no files written.
- Select Reed result → submit Evaluate → raw input file contains source snapshot.
- Reviewed job file contains reviewed/editable fields.
- Analysis file exists separately after Evaluate.
- Malformed `source_snapshot_json` returns clear validation failure.
- Oversized source snapshot (>20KB) is rejected with clear validation failure.
- Raw input storage round-trips nested `source_snapshot`.

### Regression
- Existing manual Evaluate path still stores raw input as before.
- PL-01/PL-02/PL-03 UI tests still pass.
- Orchestrator/integration tests still pass.

### Smoke
- Start app on temporary port.
- Deterministic test should prove full flow; live Reed not required because API key/network may be absent.

## Validation Commands

```bash
cd "/Users/lhaclaw/AI-Project-Workspace/job_hunt_Job Seeking Tool"
python3 -m pytest tests/test_ui.py -v --tb=short
python3 -m pytest tests/test_storage.py tests/test_orchestrator.py tests/test_integration_flow.py -v --tb=short
```

## Acceptance Criteria

- Evaluating a selected Reed job stores a separate raw input/source snapshot.
- Selection alone remains read-only and creates no files.
- Reviewed job and analysis remain separate from raw source snapshot.
- Manual fallback/evaluate still work.
- Bad or oversized snapshot data is handled safely.
- No live Reed dependency in deterministic tests.

## Open Engineering Questions

1. Does raw input storage currently tolerate extra fields like `source_snapshot`? Verify before implementation.
2. Should malformed source snapshot block evaluation or proceed with a warning? Recommended: block for Reed-selected jobs if the snapshot field is present but malformed.
3. What exact max snapshot size should be enforced? Recommended initial cap: 20KB JSON.
