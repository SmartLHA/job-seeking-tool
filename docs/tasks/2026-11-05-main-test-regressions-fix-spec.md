# Fix the 50 test failures on main after PR #3

Status: approved by Mike 2026-11-05 ("開分支修正"). Group M approved by Mike 2026-11-06 ("批准，push 開 PR").
Branch: `fix/main-test-regressions-2026-11-05`, cut from merge commit 6579980.

## Problem

Merging PR #3 (6579980) took main from 0 to 50 test failures on a clean extract:
before 1139 passed, 8 skipped; after 50 failed, 2716 passed, 17 skipped. 38 of the 50 are
tests that passed on old main; 12 are tests PR #3 added. PR #3's description says the
known failures predate the branch. For main, that is wrong.

GitHub CI did not catch this, because the workflow file PR #3 changed is invalid for
GitHub Actions, so runs fail in 0s with no jobs.

The diagnosis found no product regression. It was done on a scratch copy and has not been
independently verified; the verifier of this fix checks the claims that matter.

## Root causes

| Group | Tests | Cause | Evidence | Fix |
|---|---|---|---|---|
| A | 14 | Six test POST helpers send no Origin or Referer, so the origin guard returns 403 | `src/ui_routes.py:603-626`, commit 13ad3d0; intent in `docs/tasks/audit-remediation-2026-10-04.md:20` | Send a same-origin `Origin` header from the helpers |
| P | 29 | `tests/test_digest_pipeline.py` registers stub sources in the global registry and never restores it, so later search tests get blank pages | `tests/test_digest_pipeline.py:37,414`, `src/job_sources/source_registry.py:76-82`, commit d3e6695 | Autouse snapshot and restore fixture, as in `tests/test_digest_e2e.py:32-41` |
| T | 4 | `tests/test_market_position_route.py` seeds a cache at a fixed date and the handler reads it with the real clock and a 24h TTL, so it returns 409 | `src/adzuna_client.py:115,162,237`, commit a6a222d | Pin `ac._utc_now` in the tests |
| R | 2 | Two tests hide jobs after the first search; More now returns 409 "search expired or changed" by design | `src/ui_handlers.py:1161-1175`, commit 490c94d; intent in `docs/ui_scope.md:18`, `docs/tasks/p2-remediation-2026-10-23.md:182` | Move the `hide_jobs` block above the first GET |
| M | 1 | `test_multiselect_triage_contract` slices the JS before `function _upd`, and that slice now includes the new `_addSelection` helper | `src/job_sources/_multiselect.py:166`, commit cd46555; intent in `docs/tasks/audit-remediation-2026-10-04.md:23,152` | Assertion rewrite, approved 2026-11-06 |

CI cause: `.github/workflows/python-app.yml:20` uses `${{ runner.temp }}` in job-level
`env:`. The `runner` context is not allowed there. Commit de5521f.

## Scope

In scope: test setup in the test files below, and the one CI line.

Out of scope, do not change:
- Anything under `src/` or `viewer/`. The origin guard stays as it is.
- Any existing assertion, in any test, except group M's. Moving an assertion line unchanged is allowed in group R only.
- The main checkout and its uncommitted work.
- `INDEX.md`, `PROJECT_LOG.md`, `PROJECT_TODO.md`: the main checkout has uncommitted edits to them.

## Changes

- **A.** In `tests/test_bookmark_evaluate.py` (two helpers), `tests/test_digest_e2e.py`,
  `tests/test_digest_ui.py`, `tests/test_not_interested.py` and
  `tests/test_scoring_preset_ui.py`, send `Origin` built from the request URL's scheme and
  host. Use one small module-level helper per file rather than repeating the expression.
- **P.** Add the autouse snapshot and restore fixture to `tests/test_digest_pipeline.py`.
- **T.** In `tests/test_market_position_route.py`, add the clock pins with the same text as
  the main checkout's uncommitted hunks, so that work merges cleanly later: the `_env`
  fixture lines, and the `test_route_second_click_replaces_snapshot_with_new_date` signature
  and pin. Do not add the uncommitted `test_route_cached_benchmark_ttl_boundary` test.
- **R.** In `tests/test_relevance_ui.py`, in `test_more_looks_ahead_when_entire_requested_page_is_hidden`
  and `test_more_stops_hidden_page_lookahead_at_fixed_cap`, move the `hide_jobs` block above
  the first GET. Change nothing else.
- **CI.** Replace line 20 of `.github/workflows/python-app.yml` with the literal path
  `/tmp/job-tool-playwright`. Leave the step-level `runner.temp` uses at lines 48 and 53;
  they are allowed there.

## Group M (approved by Mike 2026-11-06)

This narrows the check: auto-select code added outside `_reg` is no longer caught. Mike was
told this before approving.

Change `tests/test_not_interested.py:245-247` from:

```python
assert "_sel.add(id)" not in M.MULTISELECT_JS.split("function _upd")[0].split(
    "window.jstSelectAll"
)[0].replace("window._jst_sel=window._jst_sel||new Set();", "")
```

to:

```python
_reg_body = M.MULTISELECT_JS.split("function _reg(c)")[1].split("function _upd")[0]
assert "_sel.add(" not in _reg_body and "_addSelection(" not in _reg_body
```

## Acceptance criteria

1. Full suite on a clean tree of the branch: 0 failed, 2766 passed, 17 skipped.
2. All 50 ids in the failing list pass in that same full-suite run.
3. `git diff --name-only 6579980...HEAD` lists only this spec, the test files named above and
   `.github/workflows/python-app.yml`. Nothing under `src/` or `viewer/`.
4. No existing `assert` line is changed or deleted, except group M's approved rewrite. The
   two moved `assert status == 200` lines in group R are unchanged text.
5. The moved setup in group R still tests look-ahead: disabling the look-ahead in a scratch
   copy makes both group R tests fail.
6. The Origin fix does not weaken the guard: in a scratch copy, a POST with no Origin or
   Referer, and a POST with a foreign Origin, both still get 403 from the server.
7. `.github/workflows/python-app.yml` parses as YAML and has no `runner` context at job level.
   Whether GitHub accepts it is only proven by a real run on the PR.

## Not covered locally

- Browser tests: Playwright is not installed locally (17 skipped).
- CI uses Python 3.10; the local venv is 3.14.
- flake8 is not in the venv.

These run for the first time since 2026-09-22 when CI works again, so the first CI run may
show failures this spec did not predict.
