# PL-02 — Reed Search Form and API Adapter Wiring Design

**Status:** Design draft — review pending
**Story:** PL-02 from `docs/tasks/reed-search-first-story-breakdown.md`
**Date:** 2026-05-13
**Owner:** SilverHand

## Problem

PL-01 made the app landing page search-first, but the Search Jobs tab is only a shell. The user now needs to search Reed jobs directly inside the app using keyword/location and optional filters, then see results in the app style.

This PL wires Reed search into the app. It does **not** implement selecting a result into the Evaluate form; that is PL-03.

## Confirmed Decisions

- Reed is the only source in this phase.
- Future sources: Adzuna and LinkedIn, but not implemented now.
- Search fields required for this phase:
  - keywords/job title
  - location
  - optional salary
  - optional remote/hybrid
  - optional permanent/contract
- UI must be rebuilt inside `src/job_hunt_ui.py` app style.
- Do not iframe or directly embed `reed_jobs_v4.html`.
- Manual fallback must remain available.

## Confirmed Evidence

- PL-01 QA passed: `/` defaults to Search Jobs and fallback tabs work.
- Existing Reed UI reference exists at `viewer/reed_jobs_v4.html`, but it is reference only.
- Existing job source files exist under `src/job_sources/`, including Reed client/normalization code, but current wiring must be verified during build.
- Existing app server is stdlib `http.server` in `src/job_hunt_ui.py`.

## Root Cause Claim / Proof Level

**Claim:** Search-first shell exists, but the app has no real internal Reed search form or app-native results rendering yet.

**Proof level:** PL-01 intentionally added placeholder shell only; no PL-02 API wiring has been implemented.

## Non-Goals

- Do not implement Select → prefill Evaluate form. That is PL-03.
- Do not implement raw Reed response audit storage. That is PL-04.
- Do not implement Adzuna or LinkedIn.
- Do not auto-evaluate a job.
- Do not remove manual fallback.
- Do not modify scoring/decision logic.

## Architecture Decision

Add a Reed search endpoint to the app server and render results in the existing Search Jobs tab. The UI should submit search parameters to the app server, which calls the existing Reed job source adapter/orchestrator path where available. Results should be normalized for display but must not fabricate unsupported fields.

If optional filters are not directly supported by the existing Reed client/API, implement them as clearly documented best-effort filters or mark them as not applied in the user-facing result/status. Do not silently pretend unsupported filters worked.

## Data Flow

```text
GET / (Search Jobs tab)
  → user enters keywords/location/optional filters
  → app submits to Reed search endpoint
  → endpoint calls Reed source adapter/orchestrator
  → endpoint returns normalized result list
  → app renders result cards/list in Search Jobs tab
```

Manual fallback remains unchanged:

```text
/?tab=add_job → existing paste/URL fallback → existing prefill/review path
```

## API / UI Contract

### Endpoint

Use `GET /search/reed` for this PL so searches are bookmarkable, easy to test with `curl`, and consistent with read-only semantics. The endpoint must not mutate storage or evaluation state.

### Search inputs

Minimum fields:
- `keywords`: string, optional but at least one useful search term should be encouraged
- `locationName`: string
- `minimumSalary` or equivalent salary filter if supported
- `workMode`: enum-like UI value: any / remote / hybrid / onsite (best-effort)
- `employmentType`: enum-like UI value: any / permanent / contract (best-effort)
- `resultsToTake`: bounded integer, default small enough for UI responsiveness

Validation/sanitization requirements:
- HTML-escape all rendered input/result values.
- Clamp `resultsToTake` to a safe range, e.g. 1–50.
- Strip excessive whitespace from text inputs.
- Treat unsupported enum values as `any` or return a clear validation message.
- Never pass unbounded user input directly into rendered HTML.

### Normalized search response shape for UI

The endpoint/UI should use a stable normalized shape per result:

```json
{
  "source": "reed",
  "source_job_id": "string-or-null",
  "title": "string-or-Unknown",
  "company": "string-or-Unknown",
  "location": "string-or-Unknown",
  "salary_display": "string-or-Unknown",
  "employment_type": "string-or-Unknown",
  "work_mode": "string-or-Unknown",
  "url": "string-or-null",
  "description_preview": "string-or-empty",
  "filter_notes": ["string"]
}
```

Each displayed result should include best available values:
- source = Reed
- source job id / reference
- title
- company
- location
- salary display or unknown
- employment type if available
- work mode if inferable or unknown
- URL if available
- short description/summary if available
- filter notes when a requested filter was best-effort or unsupported

Result shape must tolerate missing values.

## Changed Files Expected

- `src/job_hunt_ui.py`
  - Add Reed search form in Search Jobs tab.
  - Add server endpoint for search, likely `POST /search/reed` or `GET /search/reed` depending existing conventions.
  - Render result list or return JSON used by existing app JS, whichever best fits current UI style.
- `tests/test_ui.py`
  - Test search form is present.
  - Test Reed search endpoint success with mocked/stubbed adapter response.
  - Test Reed search endpoint failure gives clear user-facing error.
  - Test optional unsupported/missing fields do not crash rendering.
- Possibly `src/job_sources/reed_client.py` / `src/job_sources/normalize.py` only if tiny adapter fixes are required; avoid broad backend refactor in PL-02.
- README/docs only if app navigation/startup instructions change.

## Implementation Plan

1. Inspect existing Reed source adapter/client and current `reed_jobs_v4.html` only as reference.
2. Add app-native search form fields to `_render_search_jobs_tab()`.
3. Add a bounded Reed search handler endpoint: `GET /search/reed`.
4. Validate and sanitize query parameters, including clamping `resultsToTake`.
5. Wire endpoint to existing Reed adapter/orchestrator integration if available.
6. Normalize returned jobs for display with explicit unknown values and `filter_notes`.
7. Render results in the Search tab after search submission.
8. Add tests using monkeypatch/mocking to avoid live Reed dependency.
9. Keep live Reed/network test as optional smoke only, not required for deterministic QA.

## Edge Cases Handled

- Reed API unavailable/network failure → show clear error; manual fallback remains available.
- No results → show empty state, not a crash.
- Missing salary/company/location/description → show Unknown/N/A honestly.
- Unsupported filters → either best-effort filtering or visible note; no silent fabrication.
- Large result count → cap results to safe maximum.
- Invalid `resultsToTake` → fall back to default or return clear validation feedback.
- Unsupported filter enum → treat as `any` or return clear validation feedback.
- Special characters in keyword/location → HTML-escaped output.

## Test Plan

### Unit / UI handler tests
- Search tab contains fields: keywords, location, salary, work mode, employment type.
- Search endpoint calls Reed adapter with expected parameters.
- Successful stubbed result renders app-native result card/list.
- Empty result renders empty state.
- Adapter failure renders clear error.
- Missing optional fields render without crash.

### Regression
- Existing PL-01 tests still pass.
- Evaluate and Manual Fallback tabs remain reachable.
- Existing evaluate/orchestrator/integration tests pass.

### Smoke
- Start app on non-conflicting port.
- Open `/` and confirm search form is visible.
- Submit deterministic mocked/stubbed search through test harness.
- Optional live Reed smoke only if credentials/network are available; do not make QA depend on external Reed availability.

## Validation Commands

```bash
cd "/Users/lhaclaw/AI-Project-Workspace/job_hunt_Job Seeking Tool"
python3 -m pytest tests/test_ui.py -v --tb=short
python3 -m pytest tests/test_orchestrator.py tests/test_integration_flow.py -v --tb=short
```

Optional manual smoke after tests:

```bash
PYTHONPATH=. python3 -m src.job_hunt_ui --profile data/demo_profile/candidate_profile.json --state-root data/state --report-dir output/reports --host 127.0.0.1 --port 8767
curl -s http://127.0.0.1:8767/ | grep -E "Search Jobs|keywords|location|salary|remote|contract"
```

## Acceptance Criteria

- User can search Reed from the Search Jobs tab using keyword/location and optional salary/work-mode/employment-type fields.
- Reed results render inside the app style.
- Missing/unsupported fields are handled honestly.
- Manual Fallback still works.
- Existing Evaluate/History/Profile behavior is not broken.
- No dependency on embedding `reed_jobs_v4.html`.

## Open Engineering Questions

1. Exact existing Reed adapter function/API must be verified during build.
2. Whether Reed API directly supports remote/hybrid and permanent/contract filters must be verified. If unsupported, build must use honest best-effort behavior or visible unsupported notes.
