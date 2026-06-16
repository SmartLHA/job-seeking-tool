# JOB-002 — Reed Orchestrator Integration Design

**Status:** Draft for Wiser review  
**Owner:** SilverHand design → Wiser review → Handy build → Scout QA  
**Date:** 2026-05-13  
**Scope decision:** Reed only. Adzuna is explicitly out of scope for this implementation.

## Problem

`src/job_sources/reed_client.py`, `src/job_sources/normalize.py`, and `src/job_sources/dedup.py` exist, but Reed API results are not wired into the main orchestration path in `src/job_hunt_orchestrator.py`.

Current orchestrator flow only accepts an already-reviewed `JobPosting` payload/file and then evaluates/stores/reports a single job. JOB-002 should add a Reed ingestion path that can fetch Reed jobs, normalize them, deduplicate them, convert them into the internal `JobPosting` shape, then run the existing evaluation/storage/reporting flow.

## Revised Scope

### In scope

- Reed API only.
- Add a thin Reed ingestion orchestration path in `src/job_hunt_orchestrator.py` or a small helper module if Handy judges that cleaner.
- Reuse existing modules:
  - `job_sources.reed_client.fetch_reed_jobs`
  - `job_sources.normalize.normalize_reed`
  - `job_sources.dedup.deduplicate_jobs`
  - existing evaluation/storage/reporting modules
- Add tests using monkeypatch/fakes — no real Reed network call in tests.
- Handle missing `REED_API_KEY` through the existing Reed client behaviour or a clear orchestration result; do not crash unexpectedly.
- Preserve existing manual/local evaluation flow.

### Out of scope

- Adzuna integration.
- Parallel multi-source fetching.
- Pagination beyond one Reed fetch call.
- Generic URL scraping/paste fetch decision.
- UI changes unless strictly required by tests.
- Live API credential validation against Reed.

## Proposed API / Data Flow

Add a Reed-specific orchestrator function, recommended name:

```python
def run_reed_evaluation_flow(
    *,
    profile_path: str | Path,
    keyword: str,
    location: str,
    state_root: str | Path,
    report_dir: str | Path,
    max_results: int = 50,
) -> ReedEvaluationRunResult:
    ...
```

Recommended result dataclass:

```python
@dataclass(frozen=True, slots=True)
class ReedEvaluationRunResult:
    profile: CandidateProfile
    fetched_count: int
    normalized_count: int
    deduped_count: int
    evaluated_jobs: list[LocalEvaluationRunResult]
```

Flow:

1. Validate `keyword`, `location`, and `max_results`.
2. Load candidate profile once.
3. Call `fetch_reed_jobs(keyword, location, max_results)`.
4. Normalize each raw Reed job with `normalize_reed()`.
5. Deduplicate with `deduplicate_jobs()`.
6. Convert each `NormalizedJob` into a `JobPosting` payload.
7. For each converted job, reuse `run_local_evaluation_flow_from_payload()` with:
   - `profile_path`
   - converted reviewed job payload
   - `state_root`
   - `report_dir`
   - `raw_input_payload` containing source metadata and raw/normalized job data
   - `raw_input_id` based on Reed job id, e.g. `reed-<external_id>`
8. Return aggregate result.

## NormalizedJob → JobPosting Mapping

| JobPosting field | Source |
|---|---|
| `job_id` | `reed-<external_id>` |
| `job_title` | `title` |
| `company` | `company` or `Unknown company` fallback only if Reed field missing |
| `description_raw` | `description` |
| `source_type` | `reed_api` |
| `source_ref` | `original_url` or `apply_url` |
| `location` | `location` |
| `work_mode` | `remote_type` |
| `employment_type` | map `job_type` / `contract_type` to readable internal value |
| `required_skills` | empty list for MVP Reed ingestion unless parser exists; do not invent skills |
| `preferred_skills` | empty list for MVP Reed ingestion unless parser exists; do not invent skills |
| `required_years_experience` | `None` |
| `nice_to_have_years_experience` | `None` |
| `domain` | `None` |
| `notes` | include source quality summary if useful |
| `salary_min_gbp` | integer `salary_min` if present |
| `salary_max_gbp` | integer `salary_max` if present |

Important: do not infer skills/years/domain from free text in this task unless an existing deterministic parser already exists and tests cover it. It is safer to evaluate with empty skill lists than invent structure.

## Error Handling

- Empty Reed result should return a valid `ReedEvaluationRunResult` with zero evaluated jobs, not an exception.
- Missing API key currently makes `fetch_reed_jobs()` return `[]`; orchestrator may preserve this behaviour but should make counts clear.
- Invalid `keyword` or `location` should raise `ValueError` before calling the client.
- `max_results` should be positive; reject zero/negative values.
- One malformed Reed job should not necessarily kill the full run if other jobs can be evaluated; Handy may choose fail-fast if simpler, but tests must document the chosen behaviour.

## Testing Plan

Add focused tests, likely in `tests/test_orchestrator.py` or a new `tests/test_reed_orchestrator.py`:

1. Monkeypatch `fetch_reed_jobs()` to return two Reed raw jobs.
2. Verify `run_reed_evaluation_flow()` stores reviewed jobs, analyses, raw inputs, and reports for deduped Reed jobs.
3. Verify `source_type == "reed_api"` and job IDs are stable (`reed-<external_id>`).
4. Verify duplicate Reed IDs deduplicate before evaluation.
5. Verify empty Reed results return zero evaluated jobs without crashing.
6. Verify invalid keyword/location/max_results raise `ValueError`.

Required validation command:

```bash
python3 -m pytest tests/test_orchestrator.py tests/test_normalize.py tests/test_dedup.py -v
```

If Handy creates a new test file, include it in the command, e.g.:

```bash
python3 -m pytest tests/test_reed_orchestrator.py tests/test_orchestrator.py tests/test_normalize.py tests/test_dedup.py -v
```

## Acceptance Criteria

- Reed-only orchestration path exists and is callable from Python.
- Existing `run_local_evaluation_flow()` behaviour remains unchanged.
- Reed raw jobs are fetched, normalized, deduplicated, converted to `JobPosting`, evaluated, stored, and reported.
- No Adzuna dependency is required for this task.
- No real network calls occur in tests.
- Focused orchestration/normalization/dedup tests pass.

## Expected Changed Files

- `src/job_hunt_orchestrator.py`
- `tests/test_orchestrator.py` or `tests/test_reed_orchestrator.py`
- `docs/tasks/job-ingestion-api-design.md` only to note Reed-only implementation scope if needed
- `PROJECT_TODO.md` and `viewer/kanban_data.json` after QA passes
