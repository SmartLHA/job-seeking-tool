# Audit fixes — 2026-09-20 (from docs/audits/ui-functions-audit-2026-09-19.md)

Goal: fix the audit's top findings 1-4. Why: cover letter is broken by default; digest health is invisible; dead code and stale docs mislead planning. Finding 5 (swarm code) is a decision for Mike; do NOT touch it.

## F1 Cover-letter form/code mismatch
- Form (src/ui_render.py ~1451-1457, JS default ~1560) must offer exactly the values src/job_hunt_cover_letter.py accepts (`_VALID_TONES`, `_VALID_LENGTHS`, lines 16-17), with JS default matching the server default (`professional`, `standard`, src/ui_handlers.py ~2527). Change the FORM, not the validator.
- Labels stay human-friendly (e.g. "Brief", "Standard", "Detailed").
- AC: new test in tests/ posts every form option value through the real handler/generator (LLM mocked) and none raises ValueError; test also asserts the rendered HTML options equal the module's valid sets (import the sets, don't duplicate).

## F2 Digest health visible on /digest
- On the digest page (render_digest_page, src/ui_render.py ~2464-2615) add a small status strip: Gemini quota used/limit (from llm_queue_stats, src/job_hunt_scheduler.py ~653 via handle_llm_queue) and scheduler daemon alive/not (handle_scheduler_status, src/ui_handlers.py ~2356), loaded with fetch on page load with loading and error states, plus a "Run LLM batch" button posting to /digest/run-llm-batch with a confirm-free spinner and result text. Reuse existing handlers; no new routes.
- AC: page HTML contains the strip and button; test asserts the strip's fetch targets and the button's target route are in the rendered HTML; existing digest tests still pass.

## F3 Dead code
- Delete src/job_hunt_paste_fetch.py (0 bytes) and src/job_hunt_paste_ui.py after grep proves no importer in src/ or tests/.
- Remove handle_search_reed_more (src/ui_handlers.py ~1771) and its import in src/ui_routes.py ~70; update tests/test_ui_handlers_uncovered.py to drop only the tests of that function.
- DO NOT delete generate_cover_letter (used by src/job_hunt_tailoring.py:490).
- AC: grep shows no remaining references to the removed names; full test run shows no new failures vs baseline (baseline: 10 failed = bs4/dotenv missing, 1015 passed, 1 skipped).

## F4 Stale docs
- Add missing test files to the INDEX.md tests table (61 files in tests/, table lists 25) with one-line purpose each; add a dated PROJECT_TODO.md entry summarising 2026-09-18 commits 63a055e and d25394e (read `git show --stat` for facts) and this fix batch; add a docs/function_list.md entry for the same. Follow docs/docs-update-checklist.md.
- AC: every tests/*.py appears in INDEX.md; every path named in new text exists.

## Rules
Backup each existing doc/source file to backups/ before editing (timestamped). Nothing new at project root. Run `python3 -m pytest tests/ -q`; report the final tally line. Do not commit.
