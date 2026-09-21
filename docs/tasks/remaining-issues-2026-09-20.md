# Remaining issues — 2026-09-20 (goal: fix all remaining issues, cap 5 turns)

Tests must run with the project venv: `venv/bin/python -m pytest tests/ -q` (baseline: 1045 passed, 5 skipped, 0 failed). Do not pip install anything. Back up each edited file to backups/ (timestamped). Do not commit. Do not touch src/shared_bus.py, swarm/session_guard, or anything under ~/.openclaw.

## A Start scripts use system python3
restart.sh:18 and start.command:30 run `python3 -m src.job_hunt_ui`; system Python lacks bs4/dotenv so LinkedIn and .env loading break. Make both use `venv/bin/python` (resolve relative to the script dir), and fail with a clear message if venv/bin/python is missing. AC: `bash -n` on both; show the changed lines; a dry run that only prints the resolved interpreter path and `--version` (do NOT start or restart any server on port 8765 or the live UI).

## B /scheduler/status says running:false although scheduler ran at startup
Find why (handle_scheduler_status in src/ui_handlers.py ~2356; DigestScheduler in src/job_hunt_scheduler.py ~836; how the server starts/stores the scheduler in src/job_hunt_ui.py / ui_routes.py). Determine whether it is a real bug (flag never set, wrong object, reads a different instance, thread not alive check wrong) or correct behaviour (e.g. scheduler disabled by config or between runs). If bug: fix with a regression test. If correct: make the endpoint and the digest strip report an accurate reason (e.g. "disabled" vs "idle, next run at ...") with a test. AC: root cause stated with path:line; test proves the reported state matches the real scheduler state.

## C Flaky tests/test_ui.py::test_hidden_jobs_filter_browser_smoke
Failed intermittently (2 of ~6 full/alone runs seen). Run it 10 times alone with the venv (`-p no:cacheprovider`), record pass/fail count, find the cause (timing, port reuse, waits) and make it deterministic without weakening assertions or skipping it. AC: 10 of 10 consecutive passes after the fix, and the before count is reported. Also report why 5 tests are skipped (pytest -rs) — only fix if a skip hides a real gap.

## D Small UI issues from docs/audits/ui-functions-audit-2026-09-19.md section 6.3
1. Qualitative assess (src/ui_render.py ~1008) is a full-page form POST; give it fetch + loading/error state like Tailor/AI-review (keep the route and response handling; if the route returns a redirect/HTML, handle that).
2. Replace alert() at ~1540 with an inline message.
3. Add ARIA tab roles (role=tablist/tab, aria-selected) to the outer home tab strip ~208-233 without breaking existing tests/JS.
4. Review queue (~250-385): add a link to it from the sidebar only if a queue exists is NOT required; instead make its layout usable at <=640px (stack panels) and add a "Back to search results" link. 
AC per item: a test asserting the rendered HTML/JS; `node --check` on extracted inline scripts; existing tests pass.

Final AC: `venv/bin/python -m pytest tests/ -q` tally with 0 failures; report per chunk files changed.
