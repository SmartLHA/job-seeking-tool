# Development Rules

## File Naming Convention

- All source files in `src/` must use `job_hunt_` as a prefix, followed by a feature-specific name. Never use a bare category name like `ui.py` or `fetch.py` — there can be hundreds of UIs.
- Pattern: `job_hunt_<feature>_<module>.py`
- Examples:
  - `job_hunt_paste_ui.py` (not `ui.py`)
  - `job_hunt_paste_fetch.py` (not `fetch.py`)
  - `job_hunt_track_outcomes.py` (not `outcomes.py`)
  - `job_hunt_score_scoring.py` (not `scoring.py`)
  - `job_hunt_job_models.py` (not `models.py`)
- Feature prefixes used so far: `paste_` (URL/text input), `track_` (outcomes/tracking), `score_` (scoring engine)
- **Exception (LT-01 UI split, 2026):** the UI-layer modules use a `ui_` prefix without `job_hunt_` — `ui_routes.py`, `ui_handlers.py`, `ui_render.py`, `ui_state.py`, `ui_utils.py` — and `src/job_sources/` adapters use `<source>_source.py` / `<source>_client.py`. These are the accepted current conventions; the `job_hunt_` rule still applies to top-level domain modules.

## Technical Rules

- Python backend only for MVP
- Local-first storage only
- SQLite + JSON/JSONL preferred
- No auto-apply in v1
- No browser automation in v1
- Deterministic scoring before LLM generation
- All generated CV/cover letter content must be truthful
- No invented skills, years, titles, achievements, or certifications
- Every core logic module must have tests
- Do not refactor unrelated files
- Keep dependencies light
- Prefer modular, explicit code over clever abstractions

## Lessons Learned

### Why naming matters
A project can have hundreds of files. `ui.py` tells you nothing about what it does. `job_hunt_paste_ui.py` says: this is the job-hunt project's paste/input UI module. The prefix makes files discoverable and unambiguous.

### Why phase-by-phase matters
Building all phases at once leads to integration gaps. Each phase has a clear exit criterion and QA gate. Skipping QA to go faster usually means re-doing work.

### Tests must not write real project files (2026-10-13)
`src/` saves to paths relative to the current directory (`output/...`, `data/raw/...`). The folders those tests wrote to (`output/tailored_cvs/`, `output/cover_letters/`, `data/raw/`) are git-ignored, so a test that reaches save code can add or overwrite real files that git cannot restore. Observed on 2026-10-12 and 2026-10-13: 9 tests wrote real files (fixed in commit 6b0c720). Also found on 2026-10-13: 2 Reed tests ran a real `mkdir` (fixed in the same commit as this note). Details: `docs/tasks/test-isolation-tmp-path-2026-10-13.md`.
- Any test that reaches save code calls `monkeypatch.chdir(tmp_path)` first.
- Patching `pathlib.Path` or constants in `src/job_hunt_config.py` does not redirect modules that already imported the name (`from x import Path` / `DEFAULT_TAILORING_POLICY`). Patch the name where it is used, or use `chdir`.
- When checking that a test run leaves `data/` unchanged, exclude `data/state` or stop the UI server first: a running UI server updated `data/state` during test runs (observed once, 2026-10-13).
