# Test isolation: stop tests writing into real data/ and output/ (2026-10-13)

## Problem
A full-suite run (`PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m pytest tests -q -p no:cacheprovider`)
creates or overwrites real project files. Both are git-ignored, so an overwrite loses
whatever was there. Observed on 2026-10-12 and again on 2026-10-13 (baseline run with a
per-test mtime watcher). Writers, one per line:

| Real file written | Test | How the path is chosen in src (read-only) |
|---|---|---|
| `data/raw/adzuna/raw_<ts>.json` | `tests/test_reed_adzuna_clients.py` `TestFetchAdzunaJobs`: `test_fetch_adzuna_jobs_success`, `_empty`, `_rate_limit_429`, `_malformed_json`, `_pagination_calculation`, `_skip_zero_gives_page_one` | literal CWD-relative path in `src/job_sources/adzuna_client.py` `save_raw_response`, called from `fetch_adzuna_jobs`; no switch |
| `output/tailored_cvs/tailor-apply-001.md` | `tests/test_ui.py::test_post_tailor_returns_tailored_cv_result_for_apply_job` | `src.ui_handlers.DEFAULT_TAILORING_POLICY.output_dir` = relative `output/tailored_cvs` |
| `output/cover_letters/cand-001/cover-apply-001.txt` | `tests/test_ui.py::test_post_cover_letter_returns_letter_for_apply_job` | `handle_cover_letter` passes no `base_dir`, so relative `output/` fallback |
| `output/tailored_cvs/job-review-cv_ai_reviewed.md` | `tests/test_ui_handlers_uncovered.py::TestHandleAiReviewCv::test_handle_ai_review_cv_success_with_mock_llm` | `src.ui_handlers.DEFAULT_TAILORING_POLICY.output_dir` |

All four paths are relative to the current working directory, resolved at call time.

## Fix (test code only)
Redirect these 9 tests to pytest `tmp_path`, without changing what they assert.
- Preferred: `monkeypatch.chdir(tmp_path)` (already used for the same handler in
  `tests/test_cover_letter_form.py`), because the relative paths in asserts stay identical.
  If a test needs files relative to the project root after the chdir, create them under
  `tmp_path` or use `monkeypatch.setattr("src.ui_handlers.DEFAULT_TAILORING_POLICY",
  TailoringPolicy(output_dir=tmp_path / ...))` (pattern in `tests/test_ui.py`).
- Do not mock out the save itself unless no other option works; the save path must still run.
- A class-level or module-level fixture is fine, scoped to the affected tests only.

## Out of scope
- No change to `src/`. If a writer cannot be redirected from test code, stop and propose
  the smallest injectable-root change instead (owner approval needed).
- No change to `tests/conftest.py` (global effect), no change to unrelated tests.

## Acceptance criteria
1. After the change, a full-suite run with the exact command above leaves every file and
   directory under `data/` and `output/` with an unchanged mtime (snapshot before and after).
2. Failing-test set identical to the pre-change baseline (21 failed, 1803 passed, 8 skipped
   on 2026-10-13); the same FAILED/ERROR node IDs.
3. No `assert` line in the edited test files is removed or changed (`git diff` shows only
   additions or signature/fixture changes).
4. The 9 tests above pass when run alone.
5. Only the three test files above are edited.

## Result (2026-10-13)
All 9 tests use `monkeypatch.chdir(tmp_path)`; the saves still run, into tmp. Criteria 2-5 met.
Criterion 1: the four paths above stay unchanged. The only mtime that moved was the
`data/state` directory, written every 30 s by a live UI server (scheduler poll), not by pytest
(audit hook in the pytest process saw no writes there; an isolated copy with no server was clean).
Open: `TestReedSaveRawResponse` (2 tests) still calls a real `mkdir data/raw/reed` (no-op while it exists).
