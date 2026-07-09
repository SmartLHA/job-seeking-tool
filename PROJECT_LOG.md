## 2026-07-09

### A-F grade badge with decision-aware and culture caps (career-ops absorption slice 2)
- **Status:** ✅ COMPLETE — see `docs/tasks/career-ops-absorption-design.md` §5 for the derivation rules (amended this session after a Codex HIGH finding).
- **Motivation:** Continue the career-ops absorption plan (Mike-approved 2026-07-08): give the existing 0-100 `match_score` a letter-grade presentation layer, without creating a second authoritative signal alongside Apply/Review/Skip.
- **Changes:**
  - `src/job_hunt_qualitative.py` — `derive_base_grade(match_score)` (score-only band: A≥80, B 72-79, C 65-71, D 50-64, F<50); `derive_grade(...)` composes the base grade with the effective-decision cap and the qualitative culture/red-flags cap; `apply_grade_to_assessment(...)`; `_grade_is_better_than`, `_apply_grade_cap`, `_decision_grade_cap` helpers.
  - `src/job_hunt_index.py` — `update_qualitative_grade(db_path, job_ref, grade)`; grade persisted to the `qualitative_index` table with stale-row backfill so older rows compute a grade on next read.
  - `src/ui_render.py` — `_grade_badge()` and `_grade_warning_banner()` nested render helpers inside the job page renderer: always shows base → capped grade + the capping reason when they differ (never a bare capped letter); warning banner triggers on base A/B combined with a culture/red-flags score ≤2.
  - `src/ui_handlers.py` — wiring so the job-page view model carries the derived grade alongside the qualitative assessment.
- **Key facts:** AMENDED design rule (2026-07-09, Codex HIGH from the slice-2 review): the grade is NOT purely score-banded — it is capped to the maximum letter of the EFFECTIVE decision band (Apply→A, Review→B, Skip→D, Skip-due-to-blocker→F), because `decide_application()` can override a high score (hard blockers, low confidence), and a score-only grade could otherwise show "A" beside a Skip decision. `score_job()`/`decide_application()` themselves are untouched — the cap is pure presentation.

### Persisted batch assessment queue with progress UI (career-ops absorption slice 3)
- **Status:** ✅ COMPLETE — `tests/test_eval_queue.py` (10 tests, includes concurrency/cancel/restart-resume cases per the design's Codex LOW risk note).
- **Motivation:** Continue the career-ops absorption plan — port the "queue + resumable state" idea from career-ops' batch conductor (not its parallel workers, which are useless against a free-tier Gemini rate limit) so a whole review-queue selection can be sent for qualitative assessment without blocking the request thread.
- **Changes:**
  - `src/job_hunt_index.py` — new `eval_queue` / `eval_batch` tables (force column, `cancel_requested_at`); `enqueue_eval_batch`, `claim_eval_queue_row`, `finish_eval_queue_row`, `requeue_eval_queue_row`, `return_eval_queue_row_to_pending`, `cancel_eval_batch`, `is_eval_queue_row_cancelled`, `is_eval_batch_cancel_requested`, `reset_stale_eval_queue_running`, `pause_eval_batch_for_quota`, `get_eval_batch`, `get_eval_queue_stats`.
  - `src/job_hunt_scheduler.py` — `process_eval_queue_once(...)` / `EvalQueuePollResult` folded into the existing `LLMQueueWorker` loop as a single shared dispatcher (per the design's Codex HIGH finding): digest tasks are polled first, then at most one `eval_queue` row per cycle; quota-pause returns the row to `pending` rather than losing it; stale `running` claims are reset every poll (not just at worker startup); crash recovery re-derives batch state from the DB rather than in-memory.
  - `src/ui_handlers.py` — `_batch_assess_selected_ids`, `handle_batch_assess` (`POST /jobs/batch-assess` — enqueues the review-queue's selected job ids; rejects duplicate enqueue within a batch, per the design's eligibility rules), `handle_get_batch` (`GET /batch/{batch_id}` — server-rendered progress: N done / M total, per-job status, failures with error text), `handle_cancel_batch` (`POST /batch/{batch_id}/cancel` — pending rows only; a running job finishes its in-flight Gemini call, with a pre-persist cancel check so cancellation never silently drops a completed result).
  - `src/ui_routes.py` — routes for `POST /jobs/batch-assess`, `GET /batch/{batch_id}`, `POST /batch/{batch_id}/cancel`.
  - `src/ui_render.py` — review-queue checkboxes so jobs can be selected for a batch-assess request.
  - `tests/test_eval_queue.py` — **NEW.** 10 tests: queue state machine (pending→running→done/error/cancelled), duplicate-enqueue rejection, cancel-while-running honours the final cancel check before persisting, stale-claim reset per poll, restart resume, route-level enqueue/progress/cancel flow.
- **Key facts:** `src/job_hunt_scheduler.py` entered version control for the first time in this commit (it existed on disk from earlier Daily Digest work but had not previously been committed). Batch v1 input is review-queue selection only (Mike-approved 2026-07-08); bulk URL/JD paste is deferred (tracked as a follow-up below).

### Qualitative assessment layer — LLM-judged dimensions, legitimacy tier, idempotent on-demand route (career-ops absorption slice 1)
- **Status:** ✅ COMPLETE — `tests/test_qualitative.py` (18 tests) + qualitative route tests in `tests/test_ui.py` (10 tests).
- **Motivation:** career-ops (santifer/career-ops, MIT) research found the tool's real value was a qualitative dimension layer (culture fit, archetype alignment, red flags, posting-legitimacy signals) that the existing deterministic `score_job()` doesn't cover — see `docs/tasks/career-ops-absorption-design.md` for the full mapping, corrections to the original brief (target stack is this Python tool, not Next.js/Supabase), and the Codex design review (3 HIGH findings, all incorporated: shared LLM quota gate, on-demand route idempotency, separate storage from `JobAnalysis`).
- **Changes:**
  - `src/job_hunt_qualitative.py` — **NEW.** `build_qualitative_prompt(jd_text, profile)`, `parse_and_validate(...)` (strict-JSON schema validation, fail-closed on malformed LLM output), `run_qualitative_assessment_pipeline(...)`, `QualitativeRunResult`/`QualitativeValidationFailure`/`QualitativeValidationError`.
  - `src/text_grounding.py` — **NEW.** `normalize_grounding_text(text)` and `quote_in_text(quote, source_text)` — shared quote-validation helpers (whitespace/casing/Unicode-punctuation folding) so evidence-quote checks don't fail on formatting noise; reused by CV tailoring's existing bullet validator rather than duplicating it.
  - `src/job_hunt_index.py` — new `qualitative_index` table; `claim_qualitative_assessment(...)` / `finish_qualitative_assessment(...)` (atomic CAS claim — `BEGIN IMMEDIATE` + `INSERT ... ON CONFLICT DO NOTHING` / conditional `UPDATE`, so concurrent requests can never double-claim the same job); `reserve_llm_rpd_attempt(db_path, date, daily_cap)` — quota now reserved per Gemini attempt (incl. failures/429s/fallback retries), not only on success, raising `LLMQuotaExhausted` when the daily cap is hit.
  - `src/ui_handlers.py` — `handle_qualitative_assess` (`POST /job/{id}/qualitative-assess` — idempotent: an in-flight claim returns its running status instead of calling Gemini; `force` is honoured only when no claim is running, and archives the prior assessment by prompt_version/created_at).
  - `src/ui_render.py` — assessment panel (dimensions, evidence quotes, legitimacy tier) with a one-line Gemini privacy disclosure (JD + a minimised profile summary — not the raw CV — is sent to the API).
  - `src/job_hunt_llm.py` — `before_attempt` hook threaded through `_call_gemini_reasoning` so every Gemini attempt (digest enrichment and qualitative assessment alike) reserves quota before the call, closing the undercounting gap the design flagged.
  - `src/ui_routes.py` — route for `POST /job/{id}/qualitative-assess`.
  - `tests/test_qualitative.py` — **NEW.** 18 tests: prompt building, schema validation (valid + malformed fixtures), pipeline happy-path and failure-closed paths.
- **Key facts:** Assessment JSON is stored at `analyses/qualitative/{job_id}.json` — a separate subdirectory from the existing `analyses/{job_id}.json` `JobAnalysis` documents, per the design's storage-collision HIGH finding; the qualitative layer never changes `match_score` or the Apply/Review/Skip decision, only an advisory panel plus (slice 2) a capped grade.

### Environment fix — venv rebuild + missing `beautifulsoup4` dependency declared
- **Status:** ✅ COMPLETE — full suite: 919 passed, 2 failed (both pre-existing, unrelated to this session — see below), 1 skipped.
- **Motivation:** The local venv's `pyvenv.cfg` still pointed at an old folder name, and `src/job_sources/linkedin_source.py` imports `bs4` (BeautifulSoup) without it being a declared dependency anywhere.
- **Changes:**
  - venv rebuilt against the current project folder path (uncommitted, machine-local; not a repo file).
  - `requirements-dev.txt` — added `beautifulsoup4>=4,<5`.
- **Key facts:** The 2 pre-existing failures are unrelated WIP, not caused by this session: `tests/test_digest_pipeline.py::test_run_now_route` (stub-source registration) and `tests/test_ui.py::test_post_tailor_returns_tailored_cv_result_for_apply_job` (422 — already tracked as `TRIAGE-F1` in `PROJECT_TODO.md`, first logged 2026-07-02).

## 2026-07-08

### Test-coverage audit + 10 new test files (257 tests) — zero-coverage functions 60 → 3
- **Status:** ✅ COMPLETE — all 257 new tests green (`test_track_store.py` 22, `test_llm_queue_worker.py` 14, `test_shared_bus_getters.py` 13, `test_misc_uncovered.py` 34, `test_reed_adzuna_clients.py` 24, `test_source_forms.py` 59, `test_ui_handlers_uncovered.py` 28, `test_ui_render_uncovered.py` 26, `test_ui_routes_uncovered.py` 17, `test_llm_wrappers_uncovered.py` 20). Regression batches clean (`test_linkedin_source`, `test_reviewed_input`, `test_storage`, `test_index`, `test_parsing`, `test_outcomes`).
- **Motivation:** Full-suite coverage audit (79% lines: 6953 stmts / 1453 miss) found 60 functions in `src/` with ZERO executed body lines — including the whole `job_hunt_track_store.py` module, both API clients, 9 UI handlers, and `LLMQueueWorker`.
- **Changes:**
  - `tests/` — 10 NEW test files listed above; no existing test file edited; no `src/` changes in this item.
- **Key facts:** Built by cheap-model (Haiku) subagents, each batch independently verified by a fresh-context verifier agent per dispatch.md §6 (per-function body-line coverage re-derived from coverage JSON + AST; network-safety audit confirmed all `requests.get` patched, `.env` untouched, missing-cred tests assert no HTTP call). Remaining untested by design: `ui_routes.main` (HTTPServer/serve_forever coupling — needs src refactor), `job_sources/test_fetch.py` (manual scratch script). Known debt logged in PROJECT_TODO (TEST-F1..F3): 6 vacuous no-assert tests, one reed env test reads the real `.env` via unpatched `load_dotenv` (no leak; env restored), 14 functions still <50% covered (`handle_batch_evaluate` 22%, `parse_cv_file` 25%, `do_GET`/`do_POST` 25%…).

### track_store.delete() persistence bug — found by new tests, fixed
- **Status:** ✅ COMPLETE — `test_track_store.py` + `test_outcomes.py` 28/28 green; the 2 delete-persistence tests (skipped at discovery) unskipped and pass.
- **Motivation:** New tests exposed that `delete()` in `src/job_hunt_track_store.py` returned True without persisting: the list comprehension rebound the local `jobs`, so `_save_data(data)` saved the ORIGINAL list — deletions silently lost. Independently confirmed by a verifier with a /tmp repro before fixing.
- **Changes:**
  - `src/job_hunt_track_store.py` — `delete()`: added `data["jobs"] = jobs` before `_save_data(data)` (one line).
  - `tests/test_track_store.py` — removed the 2 `@pytest.mark.skip` markers documenting the bug.
- **Key facts:** `job_hunt_track_store.py` had no test coverage, no `docs/function_list.md` entry, and no Feature Map row before today — module documented in function_list.md as part of this session.

## 2026-07-07

### Outcome tracking UX fix — "Save outcome" felt dead: filtered status dropdown, inline card feedback, embed preserved on POST
- **Status:** ✅ COMPLETE — `tests/test_outcomes.py` 6/6, `tests/test_ui.py` 57/58 green (the 1 failure is the pre-existing `test_post_tailor_returns_tailored_cv_result_for_apply_job`, fails on unmodified code too). Verified end-to-end in sandbox: filtered options rendered per status, valid save shows inline ✓, invalid direct POST shows inline ✕, `embed=1` survives the POST.
- **Motivation:** User reported "Save outcome" on the job detail page appeared to do nothing. Investigation: backend (`POST /outcome`) worked fine; the *feel* of breakage came from (a) the Status dropdown listing all 6 statuses while the state machine rejects most jumps, failing with only a small top banner easy to miss below the fold, and (b) in the Review Queue iframe the POST response dropped `embed=1` and re-rendered the full page (with sidebar) inside the panel.
- **Changes:**
  - `src/job_hunt_outcomes.py` — new public `allowed_next_statuses(current_status)` returning valid next statuses in state-machine order (`None` → treated as `not_applied`; current status always included since same-status re-save updates notes). Added to `__all__`.
  - `src/ui_handlers.py` — job page view model now sets `outcome_status_options=allowed_next_statuses(...)` instead of all `ALLOWED_OUTCOME_STATUSES`; `render_job` gained keyword `embed=None` override (POST paths have no query string); `handle_outcome` reads hidden `embed` form field and passes it to both success and error `render_job` calls.
  - `src/ui_render.py` — Outcome tracking card: options pre-selected on *current* status; hint line "Allowed next: …" or "**X** is a final status — only notes can be updated"; outcome-related flash duplicated *inside* the card as a bold green ✓ / red ✕ box; card has `id="outcome-card"` and a small script scrolls it into view when an outcome flash is present; form gains hidden `embed=1` input in embed mode.
- **Key facts:** State machine unchanged — `not_applied→{applied,withdrawn}`, `applied→{interview,rejected,offer,withdrawn}`, `interview→{rejected,offer,withdrawn}`, `rejected`/`withdrawn` terminal. Known trade-off (user informed): with the filtered dropdown there is no UI way to undo a wrongly-saved terminal status — only hand-editing `data/state/outcomes/<job_id>.json`; an undo/reset affordance is a possible follow-up. Server restart required.

## 2026-07-02

### Search-flow triage UX — untick default, per-card ✕ hide (persistent), "Next page" replaces list, Hidden jobs overlay (design-council + Codex)
- **Status:** ✅ COMPLETE — planned via design-council with independent read-only Codex review (18 findings; highs folded in); 13 new tests (`tests/test_not_interested.py`) + 139 existing tests in the affected batches green (`test_multiselect_shared`, `test_saved_searches`, `test_linkedin_source`, `test_ui` 57/58, `test_digest_ui`, `test_integration_flow`, `test_bookmark_evaluate`, `test_index`); shared JS syntax-checked with node.
- **Motivation:** Search results appended forever and every card was auto-ticked; uninteresting jobs could not be dismissed and reappeared on every search. User asked for "next page" batching and a way to remove jobs. Codex review rejected the initial bulk "Remove selected" (one tick driving two opposite intents + acting on off-page selections); revised model user-approved: tick = shortlist ONLY, hiding is its own affordance.
- **Changes:**
  - `src/job_hunt_not_interested.py` — **NEW.** Persistent not-interested store in the shared `job_hunt_index.db` (SQLite WAL, mirrors saved-searches plumbing; NOT a JSON file — Codex concurrency finding). Table `not_interested_jobs`: key `source:source_job_id` (PK) + fingerprint `sha1(source|title|company)` so unstable LinkedIn ids still match; 180-day prune on write; idempotent `hide_jobs`, `unhide_jobs`, `list_hidden` (newest first), `count_hidden`, `hidden_lookup`, `filter_results`.
  - `src/ui_handlers.py` — `handle_source_search` + `handle_source_search_more` filter results through the store BEFORE rendering; paging math (`has_more`, next skip) intentionally stays on the RAW count (filter is display-only). `/more` JSON gains `visible_count` + `hidden_count`. New endpoints: `handle_jobs_hide` (POST `/jobs/not-interested`, idempotent, returns per-entry `keys` for undo), `handle_jobs_unhide` (POST `/jobs/not-interested/undo` — shared by undo toast and overlay Unhide), `handle_jobs_hidden_list` (GET `/jobs/not-interested`). `_render_search_jobs_tab` renders a "N job(s) on this page are hidden" note, incl. the all-hidden empty page (Codex: never a blank page with a live Next button).
  - `src/ui_routes.py` — routes for the three endpoints (GET dispatched before POST paths).
  - `src/job_sources/_multiselect.py` — cards start UNTICKED (auto-`_sel.add` removed from registration); per-card ✕ injected by JS (`jstHide`) with a 10s undo toast (`jstUndoHide` reinserts the removed DOM nodes); `jstHideUnticked` bulk-hides only VISIBLE unticked cards; `jstShowHidden` overlay lists the store with per-row Unhide; `jstLoadMore` now REPLACES the list (forward-only "Next page", page indicator, scroll-to-top) — form fields of ticked cards are captured into `_jobs[id].fields` before removal so `jstEvaluateAll` still evaluates shortlists across pages; action bar wording "shortlisted" + "· N from earlier pages". `STAGING_OVERLAY` constant now also carries the hidden-jobs overlay + toast markup (zero-touch for the 3 source renderers); `more_button_html()` kept its name but renders the full footer and always renders (Next button only when `more_url`). New helper `hide_attrs(result)`.
  - `src/job_sources/reed_source.py`, `adzuna_source.py`, `linkedin_source.py` — cards gain `data-jst-source` + `data-jst-sjid` via `hide_attrs` (identity fields the hide endpoint needs). One-line change each + import.
  - `src/ui_state.py` — `_PAGE_UPDATED["search"]` → `2026-07-01 23:33 UTC`.
  - `docs/tasks/search-triage-not-interested-design.md` — **NEW.** Retrospective design spec (problem, Codex findings that reshaped the ask, decisions, store/HTTP/client design, residual risks, test map); Feature Map + INDEX planning-docs table point to it.
  - `tests/test_not_interested.py` — **NEW.** 13 tests: hide/list round-trip, idempotent re-hide, unhide + unknown keys, fingerprint fallback key, invalid source, filter by key / by fingerprint (unstable id) / noop / source-scoped keys (reed:101 ≠ adzuna:101), retention prune, live-server endpoint flow + bad bodies, browser contract (no auto-select, ✕/hidden/Next wiring, footer without next page).
- **Key facts:** Unhidden jobs reappear in FUTURE searches, not the current page (stated in the overlay). Hidden-jobs count in the footer is fetched client-side on script init. A fully-hidden page still counts toward `has_more` (bounded look-ahead refill deferred). **Pre-existing failure, NOT from this work:** `test_ui.py::test_post_tailor_returns_tailored_cv_result_for_apply_job` (422 "Tailored CV failed validation") — tailoring path untouched by this session; tree already carried ~158 uncommitted files. Server restart required to see the new flow.

## 2026-06-30

### D2 deferred-review items closed: source registered/enabled check + digest NULL-score semantics (via codex-builder)
- **Status:** ✅ COMPLETE — `tests/test_saved_searches.py` green (+2 source-rejection tests); `tests/test_digest.py` green (+1 NULL-score test, 31 in the digest batch). Built via the write-enabled `codex-builder` MCP; each edit independently verified by reading the file + running the targeted suite (codex's own report-back was unreliable — one call mis-reported "no edits" because the files are git-untracked, another hit the `-32001` timeout on report while the edits had already landed).
- **Motivation:** Two low-severity items deferred from the D2 design-council review (`PROJECT_TODO.md` line ~235): saved-search `source_id` was only charset-validated, not checked against real sources; and `query_digest`'s treatment of NULL `match_score` under `min_score` was undocumented/implicit.
- **Changes:**
  - `src/job_hunt_saved_searches.py` — `_validate_source_id` now, after the charset/length checks, rejects any `source_id` not in `{s.lower() for s in get_enabled_sources()}` (raises `SavedSearchError`). New import `from src.job_hunt_config import get_enabled_sources` (no cycle — config is low-level). Enforced in the **core** validator, so all callers (`create_saved_search`, `save_saved_search`, programmatic) get it, not just the HTTP route. The existing inline check in `ui_handlers.handle_saved_searches_create` is left as defense-in-depth.
  - `src/job_hunt_digest.py` — `_digest_filter_clauses` score clause changed to `COALESCE(match_score, 0) >= ?` (under the existing `if min_score:` guard). Docstrings on `_digest_filter_clauses` and `query_digest` now state: NULL match_score is treated as 0; `min_score=0` returns all digest rows incl. unscored, `min_score>=1` excludes unscored.
  - `tests/test_saved_searches.py` — `test_create_saved_search_rejects_unregistered_source_id`, `test_save_saved_search_rejects_hand_built_unregistered_source_id`.
  - `tests/test_digest.py` — `test_query_digest_min_score_treats_null_as_zero` (mixed scored/NULL rows; `min_score=0` returns all, `min_score=50` excludes NULL).
- **Key facts:** Product decisions were confirmed with the owner before building — source check enforces **registered AND enabled** (accepted risk: disabling a source then blocks create/edit for it); NULL score is **treated as 0** for filtering. Server does not hot-reload — restart required to pick these up.

### Doc cleanup: stale Adzuna/LinkedIn completion marks
- **Status:** ✅ COMPLETE
- **Motivation:** Summary/build-order tables still showed shipped sources as not-started.
- **Changes:**
  - `PROJECT_TODO.md` — summary table row 14 LinkedIn `🔲` → `✅`.
  - `docs/build_order.md` — Deferred table (Adzuna, LinkedIn), `P5-1` heading, and summary-table rows 12/13 all flipped `🔲`/`⏸` → `✅`.

### Multi-select JS consolidated onto shared module — fixes broken Adzuna "More jobs" button (design-council + Codex)
- **Status:** ✅ COMPLETE — planned via the design-council skill with an independent read-only Codex review; `test_ui.py` (58) + `test_linkedin_source.py` + new `test_multiselect_shared.py` (4) + digest/bookmark suites all green (135 in the affected batch).
- **Motivation:** Reed and Adzuna still embedded their own inline copies of the multi-select JS (only LinkedIn used `_multiselect.py`). A byte-comparison found Adzuna's inline JS was missing the `window.jstLoadMore` definition entirely — so the "More jobs" button added to Adzuna the same day called an **undefined function (ReferenceError) and was non-functional in the browser**; the endpoint test only exercised the server JSON, so it went undetected. Consolidation removes the duplication *and* fixes the button.
- **Changes:**
  - `src/job_sources/reed_source.py` — `render_reed_search_results` now imports `STAGING_OVERLAY`, `ACTION_BAR`, `multiselect_script()`, `more_button_html()` from `_multiselect`; deleted the inline overlay/action-bar/JS/more-button blocks (~12.7 KB). Reed's rendered output is **byte-identical** before/after (verified across more-url / no-more / empty / error states).
  - `src/job_sources/adzuna_source.py` — same swap (~10.8 KB inline removed). Net output change = Adzuna now ships the shared JS **including `jstLoadMore`**, so its button works.
  - `tests/test_multiselect_shared.py` — **NEW.** Contract-level guard (per Codex: don't diff the 6 KB blob): every source's results HTML must contain `onclick="jstLoadMore(this)"` + `window.jstLoadMore=function(btn)` + `data-next-url=`, all three must embed the shared `MULTISELECT_JS`/`STAGING_OVERLAY`/`ACTION_BAR`, and the button (only) disappears when `more_url=None`.
- **Key facts:** Card rendering stays source-local; only the four shared chrome/JS helpers are centralised. **Codex med-severity note (deferred, out of scope):** the multi-select relies on `window._jst_*` globals + hardcoded `jst-cards-container`/`jst-more-wrap` ids, so it assumes a single result grid per page — safe today (only the active source renders) but would collide if two source grids ever rendered simultaneously.

### "More jobs" pagination generalised to all sources (Reed + Adzuna + LinkedIn)
- **Status:** ✅ COMPLETE — targeted suites green (`test_ui.py`, `test_linkedin_source.py`, digest + saved-search suites: 186 passed in one batch; source batch +33). One stale assertion updated (see below).
- **Motivation:** The "More jobs" load-more button existed only on Reed; the more-URL builder and the `/more` AJAX endpoint were Reed-hardcoded. Adzuna and LinkedIn had no pagination, and LinkedIn's results never loaded the multi-select JS on a fresh search. User wanted the button on every source. (The reported Reed "page 2 = page 1" duplication is already prevented in current code by the `resultsToSkip` fix in `reed_client.py`; a stale running server would still show it — restart required.)
- **Changes:**
  - `src/job_sources/_multiselect.py` — **NEW.** Shared `MULTISELECT_JS`, `STAGING_OVERLAY`, `ACTION_BAR` (extracted verbatim from `reed_source`) + `multiselect_script()` and `more_button_html(more_url)`. Loader targets `jst-cards-container` / `jst-more-wrap`.
  - `src/job_sources/source_registry.py` — `JobSource` gained optional `render_cards_fragment` (`(results, *, skip, nonce) -> str`), default `None` = source has no pagination.
  - `src/ui_handlers.py` — `handle_source_search` builds `_more_url` for ANY source (`/search/{source_id}/more`), advancing the skip cursor one page; new `_take_skip_param_keys` handles camelCase (Reed/Adzuna `resultsToTake`/`resultsSkip`) vs snake_case (LinkedIn `results_to_take`/`results_skip`). New generic `handle_source_search_more`; old `handle_search_reed_more` kept as a back-compat shim.
  - `src/ui_routes.py` — replaced `/search/reed/more` with generic `GET /search/{source}/more` (regex, matched before `/search/{source}`); imports `handle_source_search_more`.
  - `src/job_sources/adzuna_source.py` + `adzuna_client.py` — `resultsSkip` in normalize; `search_adzuna_jobs_for_ui` threads skip; `fetch_adzuna_jobs(..., skip=)` converts offset→Adzuna page (`skip//take+1`); render adds the shared More button.
  - `src/job_sources/linkedin_source.py` — `results_skip` in normalize; `_fetch_search(..., start=)` + `_cache_key(..., start)` page the scraper; `_render_cards(..., skip=)` offsets ids; `render_results` now uses `jst-cards-container` and includes the shared multi-select JS + staging + action bar + More button (also fixes LinkedIn's previously-missing select JS on a fresh search).
  - `tests/test_linkedin_source.py` — `test_xss_title_escaped_in_render` now asserts the full payload `<script>alert(1)</script>` is escaped (was a blanket `'<script>' not in html`, valid only while LinkedIn had no static JS).
  - `tests/test_ui.py` — +3 endpoint tests mirroring the Reed `/more` test: `test_get_search_adzuna_more_returns_offset_page` (skip→page, `jrc-10`, `resultsSkip=20`), `test_get_search_linkedin_more_returns_offset_page` (snake_case params, `start` offset, `li-rc-10`, `results_skip=20`), `test_get_search_unknown_source_more_reports_no_pagination` (clean JSON error, not a 500). `test_ui.py` 58 passed.
- **Key facts:** Card ids are offset by `skip` on every source (`jrc-{skip+i}` / `li-rc-{skip+i}`) so appended pages never collide. Adzuna pages by URL page number; LinkedIn pages by `start` offset (start is in the cache key so each page caches separately). **Deferred tech-debt:** `reed_source` and `adzuna_source` still embed their own inline copies of the multi-select JS — only LinkedIn uses `_multiselect.py`; consolidating Reed/Adzuna onto the shared module is a follow-up.

### Saved Searches — defense-in-depth field revalidation + source_id charset hardening (tech-debt item 1)
- **Status:** ✅ COMPLETE — `tests/test_saved_searches.py` 64 passed (+13); `tests/test_ui.py` 55 passed (regression). Built via the write-enabled `codex-builder` MCP; independent read-only `codex` review (council Step 12) caught a charset gap, fixed and re-verified.
- **Motivation:** `save_saved_search` only validated `search_id` — an internal caller hand-building a `SavedSearch` and calling `save` directly could persist unvalidated `name`/`source_id`/`params` (the D2 review's deferred "save_saved_search revalidation" item).
- **Changes:**
  - `src/job_hunt_saved_searches.py` — new shared helper `validate_saved_search_fields(name, source_id, params)` (runs `_validate_name`/`_validate_source_id`/`_validate_params`, returns cleaned tuple). `create_saved_search` and `save_saved_search` both call it (parity — no validator drift). `save_saved_search` now validates AND binds the cleaned values before the `INSERT … ON CONFLICT`. `_validate_source_id` gained a charset allowlist `_SOURCE_ID_PATTERN = ^[a-z0-9_-]+$` (checked after strip/lower), rejecting `bad/source`, `with space`, `../x`, `id;drop`, etc.
  - `tests/test_saved_searches.py` — +13 tests: direct `save_saved_search` rejects invalid name / source_id (format) / params before any DB write; charset-invalid source_id rejected on both create + save paths; extra `params` failure modes (too-many-keys, blank/non-string key, overlong key); valid hand-built search still saves + loads back.
- **Key facts:** `source_id` is FORMAT-validated only (charset/length) — job-source registry/enabled-source membership is a **separate still-open item** (registered-vs-enabled check). The prior gap was low-risk (source_id is parameter-bound in SQL and never used to build a filesystem path) but hardened anyway. No page render touched → no `_PAGE_UPDATED` bump. CSRF remains deferred (logged gap).

### LinkedIn Source adapter + tests (P5-2)
- **Status:** ✅ COMPLETE
- **Motivation:** P5-2 was deferred pending a fetch client design. The public (guest) LinkedIn job-search page is now scraped best-effort using `requests` + BeautifulSoup — no API key required.
- **Changes:**
  - `src/job_sources/linkedin_source.py` — **NEW.** Full `JobSource` adapter: `LinkedInBlockedError`; `is_available` (always True); SQLite cache layer (`set_cache_db_path`, `_cache_key`, `_cache_get`, `_cache_set`, `_open_cache_conn`, TTL=300s); `normalize_search_params`; `_is_blocked` (HTTP 999/429/403/401, login-redirect URL, page < 5000 chars); `_extract_job_id_from_url`, `_parse_search_html` (BeautifulSoup, `.base-card` selector, job-id dedup); `_fetch_search` (lazy `requests` import, connect 5s/read 10s, raises `LinkedInBlockedError` or `TimeoutError`); `search_handler` (cache-first); `_fetch_description` (lazy full description on select); `select_handler` (form validation, lazy desc fetch, skill extraction, returns `default_form_values` dict); `_linkedin_job_id`; `render_search_form`; `_render_select_form`, `_render_cards`, `render_results` (mirrors Adzuna `.jst-rc` card pattern); `_register()` (import-time side effect).
  - `tests/test_linkedin_source.py` — **NEW.** 16 tests: 25-card parse, login-wall block, short-page block, empty results, HTTP 429, HTTP 403, timeout, XSS escaping, duplicate dedup, `normalize_search_params` defaults/clamp/invalid-work-mode, cache hit skips HTTP, `render_results` edge cases (None/error/empty).
- **Key facts:** Salary data is unavailable from LinkedIn public search (all `salary_display=""`, `salary_min/max_gbp=None`). Absence of job cards is NOT treated as a block (valid zero-result page). SQLite cache DB path is synced from `config.state_root` in `select_handler` so searches and selects share the same DB. v2 cookie-based auth (li_at/JSESSIONID) is deferred. No new `ENABLED_SOURCES` entry yet — requires `src/ui_routes.py` import for registration.

## 2026-06-26

### Bookmark → Evaluate bridge (+ Re-evaluate link on scored jobs)
- **Status:** ✅ COMPLETE — 7 new tests (`tests/test_bookmark_evaluate.py`) green; `test_ui.py` regression 55 passed. Design-council planning + Codex design review (read-only) before build.
- **Motivation:** A job bookmarked via `POST /jobs/save` stored a minimal `JobPosting` + `not_applied` outcome + index row but had **no path to be evaluated later** — `handle_evaluate`/`handle_job_submit` only build from an HTTP form, never load a saved job by id. Bookmarked jobs dead-ended.
- **Changes:**
  - `src/ui_utils.py` — new pure helper `form_values_from_reviewed_job(job)`: maps a saved `JobPosting` back to Evaluate-form values, joins skill lists with `\n`, **preserves `job_id`** so re-submit updates the same record; missing values stay blank.
  - `src/ui_handlers.py` — new `handle_evaluate_form(req, config, responder, job_id)`: loads the saved job (404 if missing), renders the home Evaluate tab prefilled with a review notice. Read-only.
  - `src/ui_routes.py` — `GET /job/<id>/evaluate-form`, registered **before** the generic `/job/` catch-all (which would otherwise swallow it).
  - `src/ui_render.py` — unevaluated job page (`has_analysis=False`): replaced the "not evaluated yet" dead-end with a **"Review & evaluate this job →"** CTA. Already-scored job page (action bar): added an optional **"↻ Re-evaluate"** link to the same prefill route.
  - `src/ui_state.py` — bumped `_PAGE_UPDATED["job"]`.
  - `docs/tasks/bookmark-evaluate-bridge-design.md` — **NEW** design spec (implemented + reviewed).
- **Key facts:** No new submit route was needed — the Evaluate form already renders and round-trips a `job_id` field, so reusing the id updates in place (verified). Headless one-click evaluate was **deliberately rejected** to honour the review-before-evaluate + truthful-missing-data principle (bookmarks carry `description_raw="No description provided."` + empty skills). Codex's "high" audit-overwrite concern does **not** apply to the bookmark path: bookmarks write no `raw_inputs/` or analysis, so there is nothing to overwrite; re-evaluating an already-scored job overwrites its analysis in place (pre-existing same-id behaviour, surfaced by the new Re-evaluate link — no eval history kept).

### Daily Job Digest — OQ-2 (re-evaluate seen digest jobs on profile/threshold change)
- **Status:** ✅ COMPLETE — 14 new tests (`tests/test_digest_reeval.py`) green; digest suites 88 passed; full fast batch 509 passed/1 skipped (1 unrelated flaky `test_saved_searches` WAL-lock under sandbox FS, passes isolated). Design-first → Codex design review → implement → Codex code review (no critical findings).
- **Motivation:** The daily digest is new-only by design (§7a) — changing your profile or `digest_threshold` never re-scored already-seen jobs. OQ-2 is the explicit, manual action that re-scores the indexed digest jobs against the current profile and resurfaces the ones that now qualify.
- **Changes:**
  - `src/job_hunt_index.py` — 4 new helpers: `list_digest_jobs_for_reeval` (digest rows + old score + llm_status snapshot, score DESC/job_id ASC), `resurface_digest_job` (digest_seen→0, preserves digest_date), `requeue_llm_if_eligible` (**CAS**: NULL/failed/skipped/done→pending, resets attempts; blocks pending/processing), `clear_llm_queue` (**CAS**: pending→NULL only). Every llm_* write is compare-and-swap (guard in WHERE, returns rowcount).
  - `src/job_hunt_scheduler.py` — `ReevalResult` dataclass + `reevaluate_digest_jobs` (under `_PIPELINE_LOCK`): per-job reload→`evaluate_reviewed_job`→`save_job_analysis`→`upsert_job`; crossed-up→resurface + re-queue (cap `digest_max_llm_per_run`); dropped-below→dequeue. `row_status` helper preserves the user's board status on re-score. Imports `StorageError` + the 4 index helpers.
  - `src/ui_handlers.py` / `src/ui_routes.py` — `handle_digest_reevaluate` + `POST /digest/reevaluate` (sync, returns ReevalResult JSON; no Gemini call — crossed-up jobs only queued).
  - `src/ui_render.py` — "Re-evaluate all" button + confirm + result toast on the digest page.
  - `src/ui_state.py` — added `_PAGE_UPDATED["digest"]`.
  - `docs/tasks/oq-2-reevaluate-seen-design.md` — **NEW** design doc (rev 3: implemented + reviewed).
- **Key facts:** "crossed up" = `new_score ≥ threshold AND (old_score < threshold OR llm_status IS NULL)`. The `llm_status IS NULL` ("never queued as a match") signal is what makes a **threshold-only** change actually do something — a pure threshold edit can't move the score, so a score-vs-threshold test alone would never fire. Trade-off: the first re-evaluate after enabling AI (or lowering the threshold) can resurface every qualifying NULL-status job at once (AI re-queue capped by `digest_max_llm_per_run`; the unread resurface is not capped). Re-queueing `done`→`pending` refreshes stale AI (OQ-2-B); the worker overwrites the summary on its next run. CAS guards make every llm_* write safe against the concurrent LLM worker (which `_PIPELINE_LOCK` does not serialise). Server has no hot-reload — restart before testing.

## 2026-06-24

### Daily Job Digest — D5 (scheduler daemon) + D6 (paced LLM worker) — feature COMPLETE
- **Status:** ✅ COMPLETE — full suite 552 passed / 1 skipped (13 deselected = pre-existing environmental `test_multi_llm_chat`). 16 new tests (`test_digest_worker.py`, `test_digest_scheduler.py`). Design-council reviewed pre-build (caught the stranded-claim, double-pace, and once-per-day criticals).
- **Motivation:** D5 makes the digest run automatically each day; D6 layers paced Gemini enrichment on high-match jobs without tripping rate limits — completing the D1–D6 Daily Digest.
- **Changes (D6):**
  - `src/job_hunt_models.py` — `JobAnalysis` +5 optional `llm_*` fields (fit/risk/action/model/generated_at); `job_hunt_storage.job_analysis_from_dict` reads them explicitly (old records → None).
  - `src/job_hunt_llm.py` — `class RateLimited`; `_call_gemini_model` now returns a 4th `reason` ("rate_limited"/"not_found"/"server_error"/"fatal"); `_call_gemini_reasoning` returns `all_rate_limited`; `explain_job_match_with_llm(..., raise_on_rate_limit=True)` raises `RateLimited` only when **every** attempted model 429'd (not 404/503).
  - `src/job_hunt_scheduler.py` — `drain_llm_batch` (worker-lock serialised; claim→paced Gemini→`save_analysis_llm_fields`→`incr_rpd`; on 429/RPD requeue all UNSTARTED claimed rows immediately; detail-fetch inside try; missing local data → terminal `skipped`; single max-attempt transition); `LLMQueueWorker` daemon (no-ops while disabled/no key; startup stale-reset; exception-isolated cycles); `save_analysis_llm_fields`, `_fetch_full_description` (source-aware), `rpd_date_key` (Pacific, falls back to local), `llm_queue_stats`.
  - `src/ui_handlers.py` / `src/ui_routes.py` — `POST /digest/run-llm-batch`, `GET /digest/llm-queue`.
- **Changes (D5):**
  - `src/job_hunt_scheduler.py` — `DigestScheduler` daemon: **poll loop** (~30s) running `run_digest_pipeline` once per local day at `digest_run_time`; in-memory `last_run_date` once-per-day guard (slot reserved before run); lock-guarded `status()` snapshot; exception-isolated; `_PIPELINE_LOCK` serialises scheduler vs manual "Run now".
  - `src/ui_routes.py` (`main`) — auto-starts both daemons at server launch (gated by `digest_enabled`/`digest_llm_enabled` toggles, worker also needs `GOOGLE_API_KEY`); ordered shutdown (`server_close` then `stop()` with bounded join). `src/ui_handlers.py` — `set_daemons` + live `GET /scheduler/status`.
- **Council fixes applied:** two process-wide locks (`_LLM_WORKER_LOCK`, `_PIPELINE_LOCK`) eliminate the 2×RPM breach, RPD check/incr race, and concurrent-pipeline writes; requeue-unstarted-on-throttle (no 30-min stranding); terminal skip on missing data; single status transition on max attempts; `RateLimited` only on all-429. Deferred (single-process makes moot): token-conditional completion, claim heartbeats.
- **Key facts:** daemons are **on by default but gated** — nothing runs until the user's profile toggles are on (and the worker needs a Gemini key). Pacing defaults (rpm 4 / batch 4 / 15-min interval) keep a 50-job backlog well under 200 RPD. RPD counter keyed by Pacific date to match Gemini's reset.

### Daily Job Digest — D3 (pipeline) + D4 (feed UI) + design-council code review
- **Status:** ✅ COMPLETE — full suite 536 passed / 1 skipped (13 deselected = pre-existing environmental `test_multi_llm_chat`). ~40 new tests (`test_profile.py`, `test_digest_pipeline.py`, `test_digest_ui.py`).
- **Motivation:** D3 turns saved searches into a scored, deduped, queued feed; D4 makes that feed visible/filterable. Reviewed by Codex both pre-build (caught 2 critical D3 bugs + a D4 API gap) and post-build.
- **Changes (D3):**
  - `src/job_hunt_models.py` — `CandidateProfile` +10 `digest_*` fields (all defaulted).
  - `src/job_hunt_profile.py` — `parse_bool` / `_int_in` / `_parse_hhmm` validators; from_dict/to_dict + OPTIONAL_PROFILE_FIELDS for the 10 fields (ranged, HH:MM, strict bool).
  - `src/ui_utils.py` — `reviewed_job_payload_from_ui_result(result, *, source_id=None)` mapper (authoritative source_id, "Unknown"-cleaning, £/comma salary coercion).
  - `src/job_hunt_scheduler.py` — **NEW.** `DigestRunResult` (+`jobs_already_seen`) + `run_digest_pipeline` (fetch→guard/dedup→convert→deterministic eval→index-last→queue `pending`). Per-result + per-search isolation; staged counters; one global `newly_queued` cap; `run_date` once; skipped-job JSONL log. No Gemini calls (D6).
  - `src/ui_handlers.py` / `src/ui_routes.py` — `handle_run_now` (`POST /saved-searches/{id}/run-now`, sync, one search, 404), `handle_scheduler_status` (`GET /scheduler/status`, static); digest settings persisted in `handle_save_profile` (preserve-on-omit).
  - `src/ui_render.py` — Digest settings panel in the profile form; "Run now" button per saved-search row; `ProfilePageViewModel` +10 digest fields.
  - `scripts/verify_digest.py` — **NEW** live-check (runs one saved search against the real API on the user's machine).
- **Changes (D4):**
  - `src/job_hunt_digest.py` — `query_digest` extended with SQL-level `source_id`/`saved_search_id`/`seen` (tri-state) filters + `_digest_filter_clauses` helper; `DigestEntry.llm_status`; stable sort tie-breaker; `mark_all_seen` scoped to filters.
  - `src/ui_render.py` — `render_digest_page` (pure, XSS-escaped; `[View]`→internal `/job/{id}` only, external apply URL NOT rendered); sidebar **Digest** nav + unseen badge (AJAX `/digest/count`).
  - `src/ui_handlers.py` / `src/ui_routes.py` — `handle_digest` (`GET /digest`, strict filter parse), `handle_digest_mark_seen` (`POST /digest/mark-seen`, exactly-one-mode body, calendar-valid dates, ≤500, 400 on malformed).
  - `src/ui_state.py` — bumped `_PAGE_UPDATED["profile"]`, `["evaluate"]`, `["add_job"]`.
- **Code-review fixes:** staged counters (scored-after-eval, new-after-upsert; persist/queue failures → errors not skips); non-dict adapter items isolated; `islice` cap; mark-seen strictness (`{all:false}`/both-modes/non-string ids/invalid all-mode filters → 400, no scope-widening). Codex cleared: no SQL injection, `seen` tri-state correct, global cap correct, connections closed.
- **Key facts:** "no LLM in D3" = no rate-limited **Gemini**; local Ollama skill extraction via `extract_skills_from_text` (Mic-chosen) is allowed, bounded by `digest_max_per_source`. Manual add/select keeps its own job_id (OQ-1). **Deferred (low):** `digest_job_id` lossy sanitisation (numeric ids safe + fail-loud upsert guards); pagination (limit+count); CSRF (loopback, app-wide).

### Daily Job Digest — D1 + D2 design-council code review (post-implementation fixes)
- **Status:** ✅ COMPLETE — full suite 483 passed / 1 skipped (the 13 deselected = pre-existing environmental `test_multi_llm_chat` sandbox file-unlink failures). +5 review tests.
- **Motivation:** Independent Codex read-only review of the shipped D1/D2 code (not the design) to catch correctness/concurrency bugs before D3 builds on top.
- **Changes:**
  - `src/job_hunt_saved_searches.py` — **HIGH** fix: `toggle_saved_search` now reads inside the open transaction + guards a `None` row → `SavedSearchNotFound` (was: commit-then-SELECT race → 500). `_connect` sets `busy_timeout`+WAL and closes on setup failure (no leak). `save_saved_search` → `INSERT … ON CONFLICT(search_id) DO UPDATE` (not delete-then-insert). Table gained `CHECK (enabled IN (0,1))`; toggle uses `CASE WHEN`.
  - `src/ui_handlers.py` — `handle_saved_searches_create`: invalid falsy `params` (`[]`/`""`) now rejected (400) via `payload.get("params", {})`; non-UTF-8 body caught → 400 (was 500).
  - `src/job_hunt_index.py` — `_migrate_schema` tolerates the duplicate-column race between two first-run threads; `claim_batch` validates `limit` (negative → `[]`, not unbounded) and rolls back on error; `upsert_job` IntegrityError log no longer over-asserts which constraint fired.
  - `src/job_hunt_digest.py` — `query_digest` clamps negative `limit`; `mark_seen` de-dups + chunks the `IN(...)` list (no `too many SQL variables`).
  - `tests/test_saved_searches.py`, `tests/test_digest.py` — +5 tests (invalid-params 400, negative-limit, mark_seen dedup).
- **Key facts:** Codex cleared two things — no SQL injection in the dynamic WHERE/IN-clause (all values parameter-bound) and `BEGIN IMMEDIATE` in `claim_batch` is correct for this connection path. **Deferred (low value, noted):** `save_saved_search` only validates `search_id` (internal callers could persist unvalidated data); source validated against *enabled* names not the *registered* registry; `query_digest(min_score=0)` includes NULL-score rows as 0.

### Daily Job Digest — D2 Schema migration + dedup + digest query layer
- **Status:** ✅ COMPLETE — 28 tests in `tests/test_digest.py`; full suite green. Schema, dedup, and badge endpoint live. D3–D6 still backlog.
- **Motivation:** The load-bearing phase — every later digest phase depends on the index schema + dedup being correct.
- **Changes:**
  - `src/job_hunt_models.py` — `JobPosting.source_job_id` (optional, default None).
  - `src/job_hunt_reviewed_input.py` — `source_job_id` in `OPTIONAL_REVIEWED_JOB_FIELDS` + `reviewed_job_from_dict`/`_to_dict` round-trip (missing → None).
  - `src/job_sources/reed_source.py`, `adzuna_source.py` — carry normalized `source_job_id` (already `str().strip()`, no int-parse) through the select→evaluate values.
  - `src/ui_utils.py` — `digest_job_id(source, source_job_id)` canonical id; `reviewed_job_payload_from_form` + `default_form_values` carry `source_job_id`.
  - `src/ui_render.py` — `render_input_form` renders a hidden `source_job_id` field.
  - `src/job_hunt_index.py` — `_migrate_schema` (10 digest/LLM columns, idempotent); `open_db` sets WAL + `busy_timeout`; partial `UNIQUE(source, source_job_id)` + 3 perf indexes; `llm_rpd` table. `upsert_job` → `ON CONFLICT(job_id) DO UPDATE` preserving digest+LLM columns, source lower-cased, **no IntegrityError fallback (fail-loud)**. `rebuild_index` persists `source_job_id`+`apply_url`. New: `is_already_indexed`, `set_digest_meta`, `set_llm_status`, `claim_batch`, `reset_stale_llm_processing`, `rpd_used_today`/`incr_rpd_counter`, `source_job_id_from_ui_result`, `apply_url_from_ui_result`.
  - `src/job_hunt_digest.py` — **NEW.** `DigestEntry` + `query_digest`, `mark_seen`, `mark_all_seen`, `unseen_count`, `digest_stats`. `DigestEntry.url` reads `jobs.apply_url`.
  - `src/ui_handlers.py` / `src/ui_routes.py` — `GET /digest/count` (badge; `{unseen: N}`).
  - `src/ui_state.py` — bumped `_PAGE_UPDATED["evaluate"]` / `["add_job"]` (hidden field added to the shared input form).
- **Key facts:** Manual add/select still mints its own `job_id` (not canonical `digest_job_id`) — accepted per OQ-1 (two rows tolerated; partial unique index excludes NULL ids). `claim_batch`/`set_llm_status`/RPD are schema-level primitives here; the paced LLM worker that uses them is D6.

### Daily Job Digest — D1 Saved Searches (storage + JSON API + My Profile UI)
- **Status:** ✅ COMPLETE — 44 new tests green (`tests/test_saved_searches.py`: 37 unit + 6 route + 1 profile render); full UI/index/lint suites pass. No auto-run yet (D1 scope).
- **Motivation:** First slice of the Daily Job Digest backlog — let the user save, list, enable/disable, and delete reusable named searches that later phases (D3+) will run on a schedule.
- **Design-council re-review (Codex):** D1/D2 re-reviewed before coding. Four decisions locked & applied — (1) SQLite table over per-file JSON; (2) opaque `uuid4().hex` PK over slug (kills the silent-overwrite collision); (3) WAL retained but documented local-disk-only; (4) IntegrityError fallback dropped from D2 `upsert_job` in favour of fail-loud logging. Decisions 3–4 are D2-scoped and were folded into the spec, not yet coded.
- **Changes:**
  - `src/job_hunt_saved_searches.py` — **NEW.** SQLite-backed CRUD over a `saved_searches` table in `job_hunt_index.db` (owns its own `CREATE TABLE IF NOT EXISTS`, so D1 ships independently of the D2 migration). `SavedSearch` dataclass; `validate_search_id` (strict `^[A-Za-z0-9_-]{1,64}$`, applied on every op); `create/load/list/save/delete/toggle_saved_search`, `update_last_run`. Atomic toggle via `UPDATE … SET enabled = 1 - enabled`; params validated + defensively copied; corrupt params blob degrades one row, never crashes the list.
  - `src/ui_handlers.py` — 4 handlers: `handle_saved_searches_list/_create/_delete/_toggle` (+ `_saved_search_to_json`). Source validated against `get_enabled_sources()`. `render_profile` now passes `enabled_sources` to the page.
  - `src/ui_routes.py` — routes `GET/POST /saved-searches`, `POST /saved-searches/{id}/delete`, `POST /saved-searches/{id}/toggle`.
  - `src/ui_render.py` — `render_profile_page` gains a Saved Searches section (add form + live list with Enable/Disable/Delete) and an `enabled_sources` param.
  - `src/ui_state.py` — bumped `_PAGE_UPDATED["profile"]`.
  - `docs/tasks/backlog-01-daily-digest-design.md` — v6 council decisions folded in (and an earlier v5.1 consistency cleanup of stale `source_ref` wording).
  - `tests/test_saved_searches.py` — **NEW** (44 tests).
- **Key facts:** No filesystem path is built from `search_id` (SQLite), so the per-file path-traversal vector is gone; `validate_search_id` stays as input hygiene. The "Save this search" shortcut button on Find Jobs results was deliberately deferred — full create/list/toggle/delete is delivered via the My Profile section instead. D2 not started.

### Find Jobs — shared search form (one criteria set, per-source buttons)
- **Status:** ✅ COMPLETE — UI suite 55/55 green.
- **Motivation:** With Reed and Adzuna both enabled, the Find Jobs tab rendered two separate search forms, forcing the user to type the same keywords/location/filters twice.
- **Changes:**
  - `src/ui_handlers.py` — `_render_search_jobs_tab` rewritten: renders **one** shared criteria form (`id="job-search-form"`) plus one submit button per registered source. Each enabled button posts the shared fields to its own `/search/{source_id}` via `formaction`; disabled sources show a greyed, non-clickable button. New helper `_render_shared_search_form(values, buttons_html)`. Added `render_select_options` to the `ui_utils` import.
  - `tests/test_ui.py` — home-page assertion updated `id="reed-search-form"` → `id="job-search-form"`.
- **Key facts:** Results still render one source at a time (whichever button was clicked) — `handle_source_search` and each source's `render_results` are unchanged, so selection / "Evaluate all" / Reed pagination keep working. Criteria persist across a search (form prefilled from `search_values`), so the other board's button can be clicked without re-typing. Pressing Enter defaults to Search Reed (first button / form `action`). The per-source `render_search_form` callables in `reed_source`/`adzuna_source` are now unused but left in place (still valid registry fields).

### P5-1 — Adzuna source wiring (live end-to-end)
- **Status:** ✅ COMPLETE — Adzuna is registered, enabled, and returning live jobs (verified against the real API with the user's keys). UI suite 55/55 green; full suite 374 passed (only the unrelated `test_multi_llm_chat.py` sandbox file-unlink failures remain).
- **Motivation:** Reed was the only wired source. The registry/feature-flag scaffolding (GAP-C/P5-0) was in place but Adzuna had only a normaliser — no adapter connecting it to the generic UI.
- **Changes:**
  - `src/job_sources/adzuna_source.py` — **NEW** `JobSource` adapter mirroring `reed_source`: `_is_adzuna_available` (checks `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` + `.env` load), `normalize_adzuna_search_params`, `search_adzuna_jobs_for_ui`, `adzuna_job_to_ui_result`, `adzuna_select_form_to_evaluate_values`, `_render_adzuna_search_form`, `render_adzuna_search_results`, `render_adzuna_select_form`, `_register()`. Deliberately **no source_snapshot** and **no detail-fetch** (snapshot is only required for `source_type=="reed"`; Adzuna has no per-job detail endpoint).
  - `src/job_sources/adzuna_client.py` — **bug fix:** endpoint was `/1/data/gb/jobs` with `max_results` (not a valid Adzuna API) → corrected to documented `/v1/api/jobs/gb/search/1` with `results_per_page`. This was the actual blocker; it always returned 0 jobs before.
  - `src/job_sources/normalize.py` — `normalize_adzuna` null-guards: `job.get("location") or {}`, `company or {}`, `(contract_time or "")`, `(contract_type or "unknown")`. Adzuna returns explicit nulls on some listings; previously a single null-field job crashed the whole result set.
  - `src/ui_handlers.py` — `handle_batch_evaluate` now dispatches the select handler by the card's `source` field via `get_source(...)` instead of hardcoding the Reed handler (Reed behaviour unchanged; falls back to `reed` for source-less payloads).
  - `src/ui_routes.py` — `from src.job_sources import adzuna_source as _adzuna_src` (import-time registration).
  - `src/job_hunt_config.py` — `ENABLED_SOURCES = ["Reed", "Adzuna"]`.
  - `src/ui_utils.py` — `format_salary_range` collapses `min == max` to a single `£X` (was `£X – £X`); shared by Reed + job detail too.
  - `requirements-dev.txt` — declared `requests>=2,<3` (used by both clients, previously undeclared).
  - `scripts/verify_adzuna.py` — **NEW** standalone live check (parses `.env` without python-dotenv) for verifying keys + endpoint on the user's machine.
  - `tests/test_ui.py` — `/sources` assertion updated to `["Reed", "Adzuna"]`.
  - `.env` — Adzuna keys added; duplicate placeholder `GOOGLE_API_KEY` line removed (kept the real `AIza…` key).
- **Key facts:** Reviewed via design-council/Codex — it flagged a false-positive "501-char description" (limit is deliberately 501 for 500+ellipsis) and two real null-crash bugs (fixed). The sandbox is firewalled from `api.adzuna.com`, so live verification was done on the user's machine via `scripts/verify_adzuna.py` (5 BA jobs in London returned and normalised correctly). The app runs on **system python3** (per `restart.sh`), which must have `requests` installed — a clean machine would have failed Reed too.

### F1 v2 — ATS keyword-match "re-check against tailored CV"
- **Status:** ✅ COMPLETE — built from `docs/tasks/F1_v2_recheck_design.md` (rev 3,
  with a real Codex independent review folded in). Full suite **408 passed / 1
  skipped** (excludes `tests/test_multi_llm_chat.py`, which fails only on a sandbox
  file-unlink permission, unrelated to this change). +25 new tests.
- **Motivation:** close the F1 loop — the keyword panel was computed once against the
  master CV at eval and never moved. v2 adds a button that re-scores against the
  latest saved tailored CV and shows `was X% → now Y% (tailored CV)`.
- **Changes:**
  - `src/job_hunt_models.py` — `JobAnalysis` gains `keyword_match_baseline_rate` and
    `keyword_match_source` ("master"|"tailored"), validated in `__post_init__`.
  - `src/job_hunt_storage.py` — `job_analysis_from_dict` reads both new fields
    explicitly (it enumerates, not `asdict`); old records default to no-baseline/master.
  - `src/job_hunt_evaluation.py` — a (re-)eval recaptures the baseline from the fresh
    master rate and resets source to "master".
  - `src/job_hunt_tailoring.py` — **NEW** `load_latest_tailored_cv()` (strict job-id
    allow-list, rejects `.`/`..`, in-dir containment, strips one metadata line,
    fail-closed `profile_id`) + `EmptyTailoredCVError`.
  - `src/ui_render.py` — extracted `render_keyword_match_panel()` (single path for
    first render + AJAX), `id="kw-panel-body"` wrapper, delta / no-baseline "now Y%"
    states, re-check button, and `window.atsRecheck` (outerHTML swap).
  - `src/ui_handlers.py` — `handle_ats_recheck()` (per-job lock, 404/422 contract,
    empty-CV 422, panel rendered via `_keyword_match_vm_fields` so AJAX == reload);
    `JobPageViewModel` + vm fields carry baseline/source.
  - `src/ui_routes.py` / `src/ui_state.py` — `POST /job/{id}/ats-recheck` route +
    `_PAGE_UPDATED["job"]` bump.
  - `tests/test_f1_recheck.py` — **NEW** (25): loader path-safety/empty/profile-id,
    storage roundtrip + old-record defaults, panel states, and the flow (improve,
    422-no-CV, 404-unknown, 422-empty-no-mutation, AJAX↔reload parity).
- **Key facts:** Codex's 3 high-severity catches drove the design — (H1) render the
  AJAX panel through the same derived view-model as reload, (H2) read the new fields
  in `from_dict` or they silently reset, (H3) an empty tailored file is a 422 and must
  not overwrite a valid rate. The verdict card still shares `keyword_match_rate`
  (overwrite moves both — intended for MVP, covered by tests).

### Recovery merge and documentation reconciliation
- **Status:** ✅ COMPLETE — recovered implementation merged into `main` as
  `59ff270` (`codex/recovered-ui-f1`).
- **Recovery:** Restored the LT-1 split UI (`job_hunt_ui.py` is a 19-line entry
  point), the Reed source adapter/registry, F1 `job_hunt_keyword_match.py`, and
  their tests from the recovery branch. The prior monolithic-checkout diagnosis was
  not an accurate description of the recovered source and is superseded by this
  entry.
- **User-facing link:** Reed normalization now preserves the original posting URL
  as `source_ref`; the saved job page renders it as a safe “View original posting /
  Apply” link instead of exposing only a provider ID.
- **Documentation:** Re-baselined README, product spec, function list, UI scope,
  index, project context, TODO, build order, and development sequence against the
  recovered source. The two `Claude deliverable` design docs are now explicitly
  historical/non-authoritative and may be removed manually.
- **Verification:** `python3 -m pytest tests/test_ui.py tests/test_keyword_match.py
  tests/test_evaluation.py tests/test_storage.py -q` → **99 passed**;
  `git diff --check` clean; `python3 scripts/check_viewer_docs.py` → all 13 viewer
  entries resolve.

## 2026-06-19

### F1 (v1) — Per-job ATS keyword match + keyword gap
- **Status:** ✅ COMPLETE (v1) — 337/337 tests green (+22 new). Built from `docs/tasks/f1-ats-match-rate-design.md` after two review rounds (Mic + reviewer): all pre-build edits and the "75% stat is contested" correction incorporated.
- **Changes:**
  - `src/job_hunt_keyword_match.py` — **NEW**. `compute_keyword_match(cv_text, required, preferred) -> KeywordMatchResult`: edge-aware whole-token matching (handles `C#`/`C++`/`.NET`/`Node.js`/`CI/CD`; `R`≠`React`, `BA`≠`database`), casefold dedupe with **required-wins**, **null contract** (no CV/keywords → rate `None`, never 100), and overuse (>4×) anti-stuffing flag.
  - `src/job_hunt_models.py` — `JobAnalysis` gains `keyword_match_rate`, `keywords_required_missing`, `keywords_preferred_missing`, `keywords_overused` (+ 0–100 validation). `src/job_hunt_storage.py` — serialise/round-trip the 4 fields (back-compat for old records).
  - `src/job_hunt_evaluation.py` — hook beside `ats_score`; **advisory/display only** (does NOT feed `decide_application`).
  - `src/ui_render.py` / `src/ui_handlers.py` — "Keyword match — NN%" beside ATS readiness in the verdict card; a keyword-gap card (present green / missing amber chips, required + preferred) + stuffing warning; matched lists rebuilt in `_build_job_page_vm` from job skills − missing (canonical key, required-wins). `_PAGE_UPDATED["job"]` bumped.
  - Tests — `tests/test_keyword_match.py` (17: punctuation keywords, null contract, required-wins, overuse), + storage round-trip/back-compat, evaluation population (advisory), and a job-page render test.
  - Docs — `data_contract.md`, `product_spec.md`, INDEX, design-doc status.
- **Deferred to v2:** re-check vs the tailored CV (`POST /job/{id}/ats-recheck`), synonym alias map, optional index column for board sorting.

### Post-refactor code review + lint sweep
- **Status:** ✅ COMPLETE — pyflakes findings 77 → 6 (all documented-benign); 315 tests green.
- **Review:** fresh full-tree review (`docs/code-review-2026-06-19.md`). Verdict: refactor is clean — no correctness regressions, no `self.`/closure leftovers, sentinel logic correct, byte-identical render. One real latent landmine found: dead module `job_hunt_track_outcomes.py` referenced an undefined `outcomes_store` (would `NameError` if imported) — not used anywhere.
- **Sweep:**
  - Emptied the 2 dead modules (`job_hunt_track_outcomes.py`, `job_hunt_paste_ui.py`) to deprecation stubs — sandbox can't delete files in the mount, so they need a `git rm` on the host.
  - Pruned unused imports (autoflake) across `ui_handlers`/`ui_render`/`reed_source` + pre-existing `normalize`/`job_hunt_profile`/`job_hunt_scoring`/`job_hunt_parsing`/`job_hunt_outcomes`/`shared_bus`/`test_fetch`.
  - Removed 6 dead `content_length` lines (`ui_handlers`), the dead `_SKILL_GAP_CODES` set and `ids_csv`/`json` (`ui_render`).
  - `# noqa: F401` on the `ui_routes` reed_source registration import.
  - Left 6 benign findings: 5 cosmetic embedded-JS f-strings + the intentional side-effect import.
  - **Follow-up:** fixed the 2 trivial f-strings (byte-identical `/job` verified); added `tests/test_lint.py` (pyflakes gate with a 2-entry allowlist for the 3 remaining JS-block f-strings + the side-effect import). pyflakes now **4 (all allowlisted)**; suite **316 green**.

### Full system test — post-refactor verification
- **Status:** ✅ PASS — system fully functional end-to-end after the LT-1/LT-2 split.
- **Scope run:**
  1. **Compile + imports** — all `src/`+`tests/` compile; all 8 layers (`ui_state`/`ui_utils`/`ui_render`/`ui_handlers`/`ui_routes`/`job_hunt_ui`/`reed_source`/`job_hunt_validation`) import cleanly as cold first-imports (no circular-import deadlock in any order). Import graph verified strictly one-way: `ui_routes → ui_handlers → ui_render → ui_utils ⇄ ui_state`; `ui_render` domain-free; `reed_source` no upward imports.
  2. **Full suite** — **325 passed**. The only red is `tests/test_multi_llm_chat.py` (3 failed + 7 errored), all `PermissionError: Operation not permitted` on `unlink` in the mounted folder — a sandbox FS limitation in this environment, not a code defect (passes on a normal machine).
  3. **Live-server smoke — 13/13** — booted the real `_build_handler` server and drove it over HTTP: `GET /`, `/?tab=evaluate`, `/sources` (`{"enabled":["Reed"]}`), `/jobs`, `/board`, `/board/view`, `/profile`, 404 handling, plus a full evaluate → job-detail → jobs-list → outcome → board write/read cycle.
  4. **Reed source path + entry point** — live `GET /search/reed` rendered results and `/search/reed/more` returned offset cards (`has_more`); the real CLI `python3 -m src.job_hunt_ui --profile … --port 8973` launched as a subprocess, bound, and served `/sources` (200).
- **Verdict:** every layer of the split cooperates over real HTTP; architecture is clean and acyclic; 325-test suite green (excluding the unrelated sandbox-only `unlink` failures).

### LT-2 — Move CSS/JS out of the render_page f-string into module constants
- **Status:** ✅ COMPLETE — 315/315 tests green; render_page output verified **byte-identical** before/after (3 cases incl. dynamic title/body/model-label).
- **Motivation:** ~800 lines of CSS/JS were inlined in a single `render_page` f-string, so every brace had to be doubled (`{{`/`}}`) and CSS/JS edits meant fighting Python string escaping.
- **Changes:** `src/ui_render.py` — extracted the static CSS (~12 KB) and JS (~3.6 KB) into module-level constants `_PAGE_CSS` / `_PAGE_JS` (plain strings, single braces). The only dynamic JS value (the model label) is substituted at render time via a `__MODEL_LABEL__` sentinel (`_PAGE_JS.replace(...)`), avoiding `string.Template`'s `$` clashes with JS. `render_page` shrank from 316 → 29 lines; the f-string now only interpolates `escape(title)`, `body`, and the rendered JS.
- **Key facts:** Output is byte-for-byte unchanged — the `{{`→`{` unescape exactly reverses the old f-string escaping, proven by a before/after diff harness.

### LT-1 Step 7 — Remove shell back-compat re-exports
- **Status:** ✅ COMPLETE — 315/315 tests green.
- **Changes:** the only importer of the old re-exports (`tests/test_ui.py`) now imports each symbol from its real home (`UIServerConfig`←ui_state, `_build_handler`←ui_routes, form helpers←ui_utils, `load_recent_job_history`/`raw_input_payload_from_form`←ui_handlers). `src/job_hunt_ui.py` reduced from 48 → **19 lines** (docstring + `from src.ui_routes import main` + `__main__` entry). Entry point unchanged: `python3 -m src.job_hunt_ui`.

### MT-2 — Extract shared validation helpers into `job_hunt_validation.py`
- **Status:** ✅ COMPLETE — 312/312 tests green (added 18 validation unit tests).
- **Motivation:** Five small validators were copy-pasted across `job_hunt_storage`, `job_hunt_reviewed_input`, `job_hunt_profile` with subtle divergence (3 different string-list semantics, storage allowing negative ints, per-module error types and messages).
- **Changes:**
  - `src/job_hunt_validation.py` — **NEW**. 8 canonical helpers, each taking an injected `error=` class and behaviour flags (`message_style`, `strip`, `dedup`, `allow_empty_items`, `non_negative`, `empty_as_none`).
  - `job_hunt_storage.py` / `job_hunt_reviewed_input.py` / `job_hunt_profile.py` — the private helper names are now `functools.partial` bindings of the canonical functions; **call sites unchanged**, each module still raises its own `*Error`.
  - `tests/test_validation.py` — **NEW** (18 tests) incl. explicit locks for the 3 reviewer findings: `message_style` wording, `bool` rejection by all numeric helpers, and `optional_text_or_empty(" ") == " "`.
- **Key facts:** Fully behaviour-preserving, including error-message text. Design doc: `docs/tasks/mt-02-validation-helpers-design.md` (reviewed + revised before build).

### MT-6 — Tests for batch cap, pagination, multipart/CV-upload, save-profile skills
- **Status:** ✅ COMPLETE — 315/315 tests green (added 6).
- **Changes:** `tests/test_ui.py` — added a `_http_post_multipart` helper and 6 tests: `test_post_batch_evaluate_caps_at_20`, `test_get_search_reed_more_returns_offset_page` (offset card IDs `jrc-10`, `resultsSkip=20` next_url, `has_more`), `test_post_parse_cv_missing_boundary_returns_clean_error` (MT-4 path), `test_post_parse_cv_extracts_text_from_txt`, `test_post_parse_cv_auto_saves_when_profile_id_present` (`_DATA_ROOT` monkeypatched to tmp), `test_post_save_profile_skills_json_takes_precedence_over_comma`.

### MT-3 — Neutral scoring for missing required-skills + low-confidence decision gate
- **Status:** ✅ COMPLETE — 291/291 tests green. (Mic approved the "do it properly" option.)
- **Motivation:** A job listing no required skills scored 0 on that dimension, silently penalising incomplete data and auto-"skip"-ing it. The spec wanted neutral scoring with confidence carrying the uncertainty — but `decide_application()` ignored confidence, so neutral scoring alone would have flipped sparse jobs to auto-"apply". Fixed both halves together.
- **Changes:**
  - `src/job_hunt_scoring.py` — `_score_required_skills` returns full neutral weight (not 0) when no required skills are provided, consistent with unknown location/salary/experience.
  - `src/job_hunt_decision.py` — `decide_application` gained a `confidence: ConfidenceLevel = "high"` arg; a score that meets the apply threshold but has **low** confidence is routed to **review** instead of **apply**.
  - `src/job_hunt_evaluation.py` — passes `scoring_result.confidence` into `decide_application`.
  - `tests/` — updated `test_unknown_job_data_lowers_confidence_before_score`, `test_evaluate_reviewed_job_keeps_confidence_separate_from_fit_score`, and `test_sparse_reviewed_job_flow_*` (now `_review_`): the sparse job scores **86.5** (was 51.5) and is decided **review** (was skip), confidence still low.
- **Behaviour change for users:** data-sparse jobs now surface as **review** (human checks them) rather than being silently skipped; a high score on thin data can never auto-recommend "apply".

### Medium-term + LT-3 fixes (MT-4, MT-5, MT-7, LT-3; MT-3 flagged)
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Changes:**
  - **MT-4** `src/ui_handlers.py` — `parse_multipart_form` now checks for a `boundary=` parameter and raises a clear `ValueError` (surfaced as a 400) instead of crashing with "not enough values to unpack".
  - **MT-5** `src/ui_handlers.py` — `_allowed_profile_dir` anchors to `_DATA_ROOT = <project root>/data` (absolute) instead of CWD-relative `Path("data")`, so profile reads/writes are correct regardless of launch directory.
  - **MT-7** `src/ui_utils.py` / `src/ui_state.py` / `src/job_sources/reed_source.py` / `src/ui_handlers.py` — removed the dead select-nonce system: no-op `consume_select_nonce`, the `_SELECT_NONCES` store, TTL cleanup, and the always-passing check. `create_select_nonce` is now a stateless token generator.
  - **LT-3** `src/job_hunt_config.py` — `ScoringWeights.__post_init__` asserts the 7 dimension weights sum to 100 (±0.01).
- **Flagged, NOT done — MT-3**: scoring missing-required-skills as neutral would, given that `decide_application()` ignores confidence, push data-sparse jobs from `skip` → `apply`. Needs to be paired with a confidence gate in the decision policy; left for Mic's product sign-off (see PROJECT_TODO).

### Quick wins QW-1 through QW-9
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Changes:**
  - **QW-1** `src/job_hunt_scoring.py` — `_score_required_skills` param typed `list[str]`; removed the redundant `list(required_skills)` that would have silently emptied a generator after `_match_skills` consumed it.
  - **QW-8** `src/job_hunt_scoring.py` — `_score_skill_bucket` now caps the all-matched return at `weight * 1.5` so a dimension can't inflate far past its weight (previously masked by the global `min(100)`).
  - **QW-2** `src/job_hunt_ats_scorer.py` — removed the inverted ALL-CAPS-header penalty (`≥3 headers → 0`); standard CV section headings now score full format marks. Updated `tests/test_ats_scorer.py::test_multiple_all_caps_headers_are_ats_friendly`.
  - **QW-3** `src/job_sources/reed_client.py` — deleted module-level `logging.basicConfig` (was overriding host logging config on import).
  - **QW-5** `src/job_hunt_evaluation.py` — removed non-existent `evaluate_job_from_raw` from `__all__`.
  - **QW-6** `src/job_hunt_config.py` — removed the misleading 1-of-6 `__all__`.
  - **QW-9** `src/ui_handlers.py` — `handle_add_gap_skills` caps skill names at 120 chars during normalisation.
- **QW-4** `src/shared_bus.py` — NOT deleted (it is live: imported by `tests/test_swarm_router_auto_advance.py` and `tests/test_swarm_stage_derivation.py`, so the code-review "dead code" premise was wrong). Fixed the real issues: merged the duplicate `_conn()` into one (kept the URI-aware implementation that was actually winning) and the duplicate `DB_PATH` into one — removed the hardcoded `~/.openclaw/workspace/shared_memory.db` foreign path; `DB_PATH` now defaults to a project-relative file and honours the `SHARED_BUS_DB` env var. 12 swarm tests green.

### QW-7 — Consolidate 6 duplicated `upsert_job` blocks into one helper
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Motivation:** The 14-field index-upsert dict was copy-pasted across 6 handlers; any one could silently drift from the others.
- **Changes:**
  - `src/ui_handlers.py` — new `_upsert_job_to_index(config, job_id, *, reviewed_job, analysis, outcome)`. A `_UPSERT_LOAD` sentinel means "load this piece from disk by job_id if the caller didn't supply it"; absent data → NULL columns; wrapped in try/except (non-fatal). Replaced the blocks in `render_result`, `handle_job_submit`, `handle_outcome`, `handle_decision_override`, `handle_batch_evaluate`, `handle_jobs_save` — each now a single call. ~90 lines of duplication removed.
- **Key facts:** Behaviour is unchanged — callers that already hold `result.reviewed_job`/`result.analysis` pass them in (no reload); job_id-only callers let the helper load. `status` defaults to `"not_applied"` when no outcome, matching the previous per-block logic.

### LT-1 — Split `job_hunt_ui.py` god module into focused layers (+ MT-1 Reed extraction)
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Motivation:** `job_hunt_ui.py` had grown to 4,729 lines mixing routing, handlers, HTML rendering, Reed logic, utils and constants — every handler/renderer was untestable without a live HTTP server, and each new job source would add hundreds more lines.
- **Changes:**
  - `src/job_sources/reed_source.py` — **NEW** (782 lines, MT-1). All Reed rendering/normalisation/snapshot/salary/availability + self-registration. `source_registry.py` contract updated: `select_handler(form, config)` (2-arg), `render_results(results, error, nonce, more_url=None)` (4-arg).
  - `src/ui_state.py` — **NEW** (75). Constants + `UIServerConfig` (new `model_label` field, set at startup).
  - `src/ui_utils.py` — **NEW** (179). Pure helpers (`escape`, form extractors, salary format, nonce, `render_select_options`). reed_source now imports only from `ui_utils`/`ui_state`, removing the reed↔ui circular import.
  - `src/ui_render.py` — **NEW** (2,118). All HTML rendering; **domain-free**. Introduced view-models `JobPageViewModel`, `ProfilePageViewModel`, `ReviewQueueViewModel`; `render_page` reads `config.model_label` instead of importing the LLM module.
  - `src/ui_handlers.py` — **NEW** (1,598). All request handlers as standalone `(req, config, responder)` functions — testable without a live server.
  - `src/ui_routes.py` — **NEW** (320). HTTP server, dispatch, `UIRequest`, `UIResponder`, `_parse_request`, `main`, `build_parser`. Source registration as a startup side-effect import.
  - `src/job_hunt_ui.py` — reduced from 4,729 → **48-line shell**: re-exports back-compat symbols + entry point.
  - `tests/test_ui.py` — 8 Reed test fakes gained the `skip` kwarg (stale baseline fix); 8 monkeypatch targets repointed `src.job_hunt_ui.fetch_reed_jobs` → `src.job_sources.reed_source.fetch_reed_jobs`.
- **Key facts:** Import direction is strictly one-way: `ui_routes → ui_handlers → ui_render → ui_utils ⇄ ui_state`; domain modules imported only by `ui_handlers`; sources self-contained in `job_sources/`. Entry point unchanged (`python3 -m src.job_hunt_ui`). Divergences from the spec: `raw_input_payload_from_form` stayed in `ui_handlers` (Reed-coupled, not pure); `render_select_options` + nonce helpers went to `ui_utils` (to break the cycle); QW-7 `_upsert_job_to_index` consolidation deferred.

## 2026-06-18

### LLM Backend — Ollama replaced with Google Gemini
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Motivation:** Ollama consistently timed out (60 s+) due to local model cold-start. Switched to Google Gemini REST API — no new packages required (uses existing `requests`); responses in ~2–5 s.
- **Changes:**
  - `src/job_hunt_llm.py` — completely rewritten. Removed all Ollama code. New `_call_gemini_model()` core (accepts `model`, `thinking_budget`, `timeout`). New `_call_gemini()` for fast skill extraction. New `_call_gemini_reasoning()` for job analysis with 3-model chain + thinking mode.
  - `src/job_hunt_ui.py` — removed `_ollama_model` import references; updated UI strings ("Ollama" → "Gemini"); fixed "Ollama unavailable" error string.
  - `.env` — added `GOOGLE_API_KEY=your_key_here` entry.
  - `.env.example` — replaced Ollama block with Google Gemini block.
- **Environment variables:**
  - `GOOGLE_API_KEY` (required) — API key from https://aistudio.google.com/apikey
  - `GEMINI_MODEL` (optional) — overrides skill-extraction model (default: `gemini-3.1-flash-lite`)
- **Skill extraction model chain** (on 404 or 429):
  1. `gemini-3.1-flash-lite` — primary (fast, cheap)
  2. `gemini-2.5-flash-lite` — fallback

### AI Analysis — Structured Output + Reasoning Model
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Motivation:** The old AI analysis dumped a wall of free-form prose into a single text box. Hard to scan, no focus. Redesigned to return 3 structured sections with a reasoning model.
- **Prompt change:** `_EXPLAIN_PROMPT` now instructs Gemini to return `{"fit": "...", "risk": "...", "action": "..."}` JSON — no prose, no markdown. One field per concern.
- **Backend change:** `explain_job_match_with_llm()` return type changed from `tuple[str|None, str|None]` to `tuple[dict[str,str]|None, str|None]`. `_handle_job_explain` spreads the dict: `{"ok": True, "fit": ..., "risk": ..., "action": ...}`.
- **UI redesign** (`render_job_page` AI Analysis block):
  - Idle state: "Click Run Analysis for a Gemini assessment of this match."
  - Loading state: "Reasoning… this may take up to 30 s"
  - Result: 3 separated sections, each with coloured label + body text:
    - **FIT ASSESSMENT** (accent blue) — honest overall verdict
    - **KEY RISK** (warning red) — single most important gap
    - **RECOMMENDED ACTION** (green) — one concrete next step
  - Error state: styled red box with error message
  - Badge: "· via Gemini (gemini-2.5-flash · high reasoning)"
  - All text set via `element.textContent` (XSS-safe)
- **Reasoning model chain** (`_call_gemini_reasoning`, on 404 or 429):
  1. `gemini-3-flash-preview` + thinkingBudget 8000 — primary (best reasoning)
  2. `gemini-2.5-flash` + thinkingBudget 8000 — first fallback
  3. `gemini-3.1-flash-lite` — second fallback, no thinking
  - Timeout for thinking calls: 60 s (vs 30 s for fast calls)

### UI — Per-Page Last-Updated Timestamps
- **Status:** ✅ COMPLETE — 291/291 tests green
- **What:** Every page now shows "Page updated YYYY-MM-DD HH:MM UTC" so the user can tell when a UI change took effect without restarting or checking code.
- **Implementation:**
  - `_CODE_UPDATED` (single string) replaced with `_PAGE_UPDATED: dict[str, str]` keyed by tab name: `"search"`, `"evaluate"`, `"add_job"`, `"history"`, `"board"`, `"profile"`, `"job"`
  - Sidebar footer: `Page updated {_PAGE_UPDATED.get(active_tab, "—")}`
  - Job detail page: small `<footer>` element at bottom of `<main>` showing `_PAGE_UPDATED["job"]`
- **Rule:** Bump the relevant key whenever that page's rendering function is modified. Saved to memory so future sessions remember.

### UI — Multi-Select Search Results + Staging Overlay
- **Status:** ✅ COMPLETE — 291/291 tests green
- **What:** Reed search results redesigned from single-select cards to a multi-select flow with a staging review panel before evaluation.
- **Card design:**
  - Each result is a clickable card (`onclick="jstToggle('jrc-N')"`) with custom checkbox, pill tags (location 📍, salary mono, employment type, work mode), and filter notes
  - Cards stored in `_jobs` dict by id; metadata in `data-jst-*` attributes
- **Sticky action bar** (`id="jst-bar"`): shows count, "Review selected" button, "Clear all" button; hidden until ≥1 card selected
- **Staging overlay** (`id="jst-overlay"`): full-screen modal (`position:fixed;inset:0;z-index:200`) listing staged jobs; each row has "Evaluate" and "✕ Remove" buttons; list built via `document.createElement` + `textContent` (XSS-safe)
- **JS IIFE**: `_sel` (Set), `_jobs` (dict), `jstToggle`, `jstSelectAll`, `jstClearAll`, `jstShowStaging`, `jstCloseStaging`, `jstRemoveStaging`, `jstEvaluate`
- **`render_reed_select_form()`**: added `form_id` param; form hidden by default (`style="display:none;"`); no submit button
- **Nonce unchanged**: `consume_select_nonce` validates only (does not consume), so multiple forms with the same nonce all submit successfully

### Dev Tooling — Auto-Reload Watcher + Restart Script
- **Status:** ✅ COMPLETE
- **`dev.py`** — zero-dependency auto-reload watcher. Polls `src/**/*.py` MD5 hashes every 1 s; kills and restarts server process on any change. Usage: `python3 dev.py [--port 9000] [--profile data/mic_profile.json]`
- **`restart.sh`** — kills any running instance on the configured port, waits 0.3 s, starts fresh. Usage: `./restart.sh` or `PORT=9001 ./restart.sh`

---

## 2026-06-17

### UX Hardening — Status Feedback, Error Messages, and AI Analysis Button
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Motivation:** Testing revealed several silent failure modes and opaque error messages that left the user with no actionable fix. Five gaps addressed in one pass.

#### Gap 1 — Profile page CV status indicator
- **Before:** No indication on the Profile page of whether a CV was actually on file. User could not tell if the auto-save had worked.
- **Fix:** Added a coloured status strip at the top of the "Upload CV" section:
  - 🟢 Green tick: "CV on file: 2,341 chars | saved to /abs/path/..."
  - 🟡 Amber warning: "CV ref set but no text stored — re-upload below"
  - 🔴 Red warning: "No CV on file — upload your CV below so Tailor CV and Cover Letter work"
- **Implementation:** Python-generated HTML in `render_profile_page()` — computed from `profile_obj.master_cv_text` length and `profile_obj.master_cv_ref`.

#### Gap 2 — Profile save flash confirmation
- **Before:** Saving profile redirected to `/profile?profile_id=...` with no confirmation. User could not tell if save succeeded.
- **Fix:** `_handle_save_profile` now builds a flash message: `"Profile saved. CV: 2,341 chars on file."` (or `"No CV on file — upload a CV file above."` if absent). Message is URL-encoded and passed as `?flash=...` query param. `_render_profile` and `render_profile_page` accept and display a green flash banner at top of page.

#### Gap 3 — Tailor CV error — now actionable
- **Before:** `"No master CV available on candidate profile"` — told the user nothing about what happened or how to fix it.
- **Fix:** Two specific messages depending on failure mode:
  - cv_ref present but file unreadable: `"CV file could not be read (/abs/path): <error>. Re-upload your CV on the Profile page."`
  - cv_ref absent: `"No master CV on profile. Go to Profile → upload your CV file → click Save (or Parse CV to auto-save)."`

#### Gap 4 — Cover letter no longer silently generates without CV
- **Before:** If CV was missing/unreadable, `cv_text` silently fell to `""` and the function proceeded — generating a weak letter with no CV context, reported as success.
- **Fix:** Same error-and-return logic as tailor. Returns HTTP 422 with the same actionable message instead of proceeding with empty CV text.

#### Gap 5 — Tailor result panel shows match stats
- **Before:** Success panel showed only `saved_path` and `summary`.
- **Fix:** JS now renders `promoted` / `matched` / `missing` counts inline: `✓ 3 promoted   ✓ 7 matched   ⚠ 2 missing`.

#### Gap 5b — Auto-save error visibility
- **Before:** `auto_save_error` was logged server-side but never surfaced in the browser.
- **Fix:** Server returns `auto_save_error` string in JSON. JS status message shows it: `"Auto-save FAILED: <reason>. Save manually below."` so failures are visible without needing the server log.

#### Gap 6 — AI Analysis: manual button instead of auto-fire
- **Before:** Ollama was called automatically every time the job detail page loaded (30–60s on first call). Slow on cold start, wasted resources if user only wanted the rule-based scores.
- **Fix:** Replaced the auto-fetch with a **"Run Analysis"** button. Shows "Analysing…" while running, then the result. Becomes "Re-run" / "Retry" on completion/failure. Button stays disabled during the request.
- **Changes:** `src/job_hunt_ui.py` — `explainable_result_html` block in `render_job_page()`; new `runAiAnalysis()` JS function.

- **All changes in:** `src/job_hunt_ui.py` — `_render_profile`, `_handle_save_profile`, `_handle_tailor`, `_handle_cover_letter`, `render_profile_page`, `render_job_page` (tailor result JS, AI analysis JS)

---

### Feature — LLM-Based CV Skill Extraction (Ollama, with keyword fallback)
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Problem:** CV skill extraction used hardcoded `KNOWN_SKILLS` keyword matching. Any phrasing not in the list was missed (e.g. "business requirements" instead of "business requirements document", or bespoke domain skills like "Temenos" or "Murex"). Skills in the CV were not being surfaced in the profile, so the evaluator reported them as missing.
- **Fix:**
  - `src/job_hunt_llm.py` — added `_CV_SKILL_EXTRACT_PROMPT` and `extract_cv_skills_with_llm(cv_text)`: calls Ollama with a CV-specific prompt that asks for a flat `{"skills": [...]}` list. Prompt is tuned to: use standard industry names, include only evidenced soft skills, exclude job titles / degrees / unsubstantiated traits, Title Case output. Truncates to 12,000 chars (CVs are longer than job descriptions).
  - `src/job_hunt_parsing.py` — added `extract_skills_from_cv(cv_text) -> list[str]`: tries `extract_cv_skills_with_llm` first; falls back to `_extract_skills` keyword scan when Ollama is offline or fails.
  - `src/job_hunt_ui.py` — `_handle_parse_cv` now calls `extract_skills_from_cv(text)` instead of `_extract_skills(text)` directly.
- **Behaviour:** When Ollama is running, skills are extracted freely from CV text regardless of phrasing. When Ollama is offline, the system falls back to keyword scanning — same as before, no regression.
- **Note:** The CV prompt is deliberately different from the job prompt (`_SKILL_EXTRACT_PROMPT`). Job extraction splits required vs preferred; CV extraction returns a flat list of what the candidate HAS.

### Feature — CV Auto-Save on Upload (No Save Button Required)
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Problem:** User had to re-upload their CV every testing session because uploading only filled the textarea in memory — the user also had to remember to click "Save Profile" before the CV was persisted to the JSON file.
- **Fix:**
  - JS CV upload handler now appends `profile_id` to the multipart FormData before sending to `/profile/parse-cv`
  - `_handle_parse_cv`: if `profile_id` is present in the upload, immediately loads the existing profile (falling back to startup profile if the dir-based JSON doesn't exist yet), writes the CV text to `data/{profile_id}/docs/master_cv{ext}`, updates `master_cv_text` and `master_cv_ref` (as absolute path), saves the profile JSON, and syncs `config.profile_path` if the ids match
  - Returns `auto_saved: true` in the JSON response
  - Status message updated: "CV parsed successfully. CV saved automatically. Added N skill(s)…"
  - Auto-save failure is non-fatal (silent pass) — if something goes wrong, user can still click Save manually
- **Result:** Upload CV once, it persists across server restarts. No extra clicks needed for testing.
- **Changes:** `src/job_hunt_ui.py` — `_handle_parse_cv`, CV upload JS handler

### Feature — CV Skill Extraction: Auto-populate Profile Skills from Uploaded CV
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Problem:** After uploading a CV, skills mentioned in the CV were not appearing in the profile Skills table. The evaluator checks `profile.skills` (the table), not the CV text, so even if the CV mentioned SQL or Agile, the system reported those as missing skills on the candidate.
- **Root cause:** `/profile/parse-cv` only returned `master_cv_text`. The JS set the CV textarea but never touched the skills table. The skills table had to be filled manually.
- **Fix:**
  - `_handle_parse_cv`: after extracting CV text, calls `_extract_skills(text)` and returns a `suggested_skills` list in the JSON response
  - JS CV upload handler: after setting the CV textarea, iterates `data.suggested_skills`; any skill name not already in the table (case-insensitive match) is added as a new row with `level: "unspecified"`. Existing rows are never modified.
  - Skills table IIFE: exports `window.makeRow` so the CV upload IIFE (separate scope) can create new table rows using the same function
  - Status message updated to include a count: "CV parsed successfully. Added N skill(s) from CV — review levels below."
- **UX note:** Extracted skills have level "unspecified" by default — user should review and set their level before saving. This is intentional: the system cannot infer seniority from keyword presence alone.
- **Changes:** `src/job_hunt_ui.py` — `_handle_parse_cv`, CV upload JS handler, skills table IIFE

### Bugfix — Tailor / Cover Letter "No master CV available" + Full Profile Disconnect Audit
- **Status:** ✅ COMPLETE — 112/112 tests green (1 pre-existing permission error on viewer file unrelated to this fix)
- **Root causes identified (3 disconnections):**
  1. **Wrong profile file for tailor/cover-letter**: `_handle_tailor` and cover-letter handler load `config.profile_path` (`data/mic_profile.json`), which has no `master_cv_ref` and no `master_cv_text`. But CV upload saves to `data/{profile_id}/candidate_profile.json` — a completely different file. So the endpoint always returned "No master CV available".
  2. **Profile page shows empty form**: `/profile?profile_id=mic_profile` tried to load `data/mic_profile/candidate_profile.json` (which didn't exist) and showed an empty form — never falling back to `data/mic_profile.json`. User would fill only the CV and save a stripped profile losing all skills/experience data.
  3. **cv_ref double-path bug**: When `master_cv_ref` is a relative path like `data/mic_profile/docs/master_cv.txt`, the tailor/cover-letter handlers prepended `config.profile_path.parent` (`data/`) producing `data/data/mic_profile/docs/master_cv.txt` — wrong path, file not found.
- **Fixes:**
  1. `_render_profile`: when `data/{profile_id}/candidate_profile.json` doesn't exist and `profile_id` matches `config.profile_path.stem`, fall back to loading `config.profile_path` so user sees their existing profile data in the form.
  2. `_handle_save_profile`: (a) create `profile_dir` before writing; (b) store `master_cv_ref` as absolute path via `.resolve()` to avoid all relative-path ambiguity; (c) when `profile_id` matches `config.profile_path.stem`, also write the saved profile to `config.profile_path` — so evaluate/tailor/cover-letter/home all see the latest data including the CV.
  3. `_handle_tailor` and cover-letter handler: resolve relative `master_cv_ref` paths against `Path.cwd()` instead of `config.profile_path.parent` (now moot since we store absolute paths, but keeps the fallback correct for old profiles).
- **Changes:** `src/job_hunt_ui.py` — `_render_profile`, `_handle_save_profile`, `_handle_tailor`, cover-letter handler

### Spec Doc Update — All Phase 1–5 GAPs Reflected
- **Status:** ✅ COMPLETE
- **Files updated:** `docs/product_spec.md`, `Claude deliverable/docs/ui_structure_v4.md`, `Claude deliverable/docs/function_list_v4.md`, `docs/tasks/gap-c-source-feature-flag-design.md`
- **What changed:**
  - `product_spec.md` — Implementation state table updated: all Phase 1–4 items moved to ✅ done; only GAP-J (Gap Coach) and GAP-B UI columns remain; `source_registry.py` added to Key Files; test count updated to 291; Resolved section extended with source registry and required-skills fix entries
  - `ui_structure_v4.md` — Routes updated from hardcoded `/search/reed`→`/search/{source}` and `/select/reed`→`/select/{source}`; reconciliation table updated (GAP-A/C/I/D/E/F/G/H all ✅); "What's already correct" section extended
  - `function_list_v4.md` — All GAP-A through GAP-I warnings replaced with ✅ resolved notes; `source_registry.py` functions section added; HTTP route table rewritten to show all 18 current routes; priority list replaced with short remaining-work list
  - `gap-c-source-feature-flag-design.md` — Status changed to ✅ Complete; Adzuna wiring steps updated to registry pattern (one file + one import); source key vs display label section updated

### Bugfix — Missing Required Skills / Preferred Skills Always Empty
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Root cause (1 of 2):** `KNOWN_SKILLS` in `src/job_hunt_parsing.py` had only 12 hardcoded entries. When Ollama is not running, the keyword fallback finds nothing in most real-world job descriptions, so `job.required_skills = []`. With no required skills, `_score_required_skills` returns early with `([], [])` — both matched AND missing empty. The evaluate form shows the skills fields blank and the result correctly shows "None" for missing skills, but the scoring is blind.
- **Root cause (2 of 2):** For `reed-55622726`, `missing_required_skills = []` is **correct** — the candidate has all two required skills (`Process Mapping`, `Business Analysis`). Empty missing skills = good match, not a bug.
- **Fix:** Expanded `KNOWN_SKILLS` from 12 to ~85 entries covering: data/analytics (SQL, Power BI, Excel, KPI, dashboards, data modelling/migration, BI, reporting), BA/PM core (requirements gathering/elicitation, process mapping/improvement, gap analysis, stakeholder management/engagement, user stories, use cases, BRD, traceability matrix, root cause analysis, impact/cost-benefit/feasibility), Agile/delivery (Agile, Scrum, Kanban, sprint planning, JIRA, Confluence, refinement), Waterfall/governance (PRINCE2, PMP, project management, change management/control, risk management, governance, compliance, audit), systems/tech (UML, BPMN, Visio, LucidChart, SharePoint, MS Project, ERP, CRM, Salesforce, SAP, Oracle, ServiceNow, API, integration, system design, UAT, QA), and soft skills (facilitation, presentation, documentation, business case, strategy, transformation, Lean, Six Sigma).
- **Also fixed:** `_extract_skills` was using `.title()` for all skills, which produced `Brd`, `Uml`, `Bpmn`, `Uat` etc. Added `_SKILL_ACRONYMS` set; acronyms are now `.upper()`.
- **Test updated:** `tests/test_parsing.py::test_parse_job_from_text_prefills_expected_fields` changed from exact list match to `set >=` superset check (expanded list now finds more skills in the same fixture text).
- **Changes:** `src/job_hunt_parsing.py` — `KNOWN_SKILLS` expanded; `_SKILL_ACRONYMS` set added; `_extract_skills` uses `upper()` for acronyms

### Bugfix — Parse CV Always Returns "Failed to Fetch"
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Root cause:** `do_POST` called `_read_form_data()` at line 240 **unconditionally**, before routing. `_read_form_data` does `.decode("utf-8")` on the raw body. When a multipart form with a binary file (PDF, DOCX) was submitted to `/profile/parse-cv`, the binary body caused `UnicodeDecodeError`. This exception escaped `do_POST` with no HTTP response sent — the browser received a closed connection and showed "Failed to fetch" rather than an error message.
- **Fix:** Moved `/profile/parse-cv` into the early-exit block before `_read_form_data()`, matching the same pattern already used for `/tailor`, `/cover-letter`, `/jobs/save`, and `/job/{id}/decision`.
- **Changes:** `src/job_hunt_ui.py` — moved parse-cv route check to pre-`_read_form_data` block; removed duplicate check that remained lower in `do_POST`

### Defensive Hardening — Server Error Handling
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Why:** Any unhandled exception in `do_GET` or `do_POST` caused the connection to close silently, producing "Failed to fetch" for JS callers and a browser connection error for page loads. This made server-side bugs invisible to the user and hard to debug.
- **Changes:**
  - `src/job_hunt_ui.py` — `do_GET` and `do_POST` now delegate to `_do_GET_inner` / `_do_POST_inner` wrapped in try/except; unhandled exceptions return HTML 500 (GET) or JSON 500 (POST) instead of silently closing the connection; exceptions are logged via `logger.exception`
  - `src/job_hunt_ui.py` — `_read_form_data()` call in `_do_POST_inner` now wrapped in its own try/except; malformed Content-Length or client disconnect returns 400 JSON instead of propagating
  - `src/job_hunt_ui.py` — `_handle_parse_cv`: replaced CWD-relative `Path("temp_uploads")` with `tempfile.mkstemp(suffix=ext)`; OS-managed temp file with no path dependency; `finally` block still calls `unlink(missing_ok=True)`

### Job Detail Fetch — Fix Required Skills Always Empty After Loading Screen
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Root cause:** Reed search API truncates `jobDescription` to ~500 chars. `extract_skills_from_text` was called on that stub, so Ollama had too little context to extract anything useful.
- **Fix:** `reed_select_form_to_evaluate_values` in `src/job_hunt_ui.py` now calls `fetch_reed_job_detail(source_job_id)` immediately after nonce validation. If the detail fetch succeeds, the full `jobDescription` (HTML-stripped) replaces the truncated preview for both skill extraction and the `description_raw`/`copied_text` form fields. Falls back silently to the truncated preview on any network failure.
- **Changes:**
  - `src/job_hunt_ui.py` — `reed_select_form_to_evaluate_values`: fetch full description via detail API before calling `extract_skills_from_text`
  - `src/job_sources/reed_client.py` — `fetch_reed_job_detail(job_id)` already added in prior session; confirmed present

### Multi-Source Job Board Architecture — Source Registry
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Why:** All job-source logic was hardcoded to Reed. Routes (`/search/reed`, `/select/reed`), nonce constants (`_REED_SELECT_NONCES`), field limits (`_REED_SELECT_FIELD_LIMITS`), and the search tab UI all assumed Reed as the only source. Adding Adzuna or LinkedIn would have required editing routing, dispatch, and rendering in multiple places.
- **Changes:**
  - `src/job_sources/source_registry.py` — **New file.** `JobSource` frozen dataclass with fields: `source_id`, `display_name`, `is_available`, `normalize_search_params`, `search_handler`, `select_handler`, `render_search_form`, `render_results`. `register()`, `get_source()`, `all_sources()` helpers.
  - `src/job_hunt_ui.py`:
    - Routes `GET /search/reed` → `GET /search/{source}` (regex match, dispatches through registry)
    - Routes `POST /select/reed` → `POST /select/{source}` (regex match, dispatches through registry)
    - `_handle_reed_search` / `_handle_reed_select` → `_handle_source_search(source_id, params)` / `_handle_source_select(source_id, form)` — unknown source returns 404
    - `_REED_SELECT_NONCES` → `_SELECT_NONCES`; `_REED_SELECT_NONCE_TTL_SECONDS` → `_SELECT_NONCE_TTL_SECONDS`
    - `_REED_SELECT_FIELD_LIMITS` → `_SELECT_FORM_FIELD_LIMITS`
    - `_ALLOWED_REED_WORK_MODES` → `_ALLOWED_WORK_MODES`; `_ALLOWED_REED_EMPLOYMENT_TYPES` → `_ALLOWED_EMPLOYMENT_TYPES`
    - `create_reed_select_nonce` / `consume_reed_select_nonce` → `create_select_nonce` / `consume_select_nonce`
    - `_render_search_jobs_tab` rewritten to iterate `all_sources()` — source pills and forms are now dynamic
    - `_render_reed_search_form(values, enabled) → str` extracted as a standalone function (registered as Reed's `render_search_form`)
    - Reed registered as a `JobSource` at module level after all Reed functions are defined (bottom of module)
    - `logging` import + module-level `logger` added (was missing, caused `NameError` in `reed_select_form_to_evaluate_values`)
    - `GET /board` restored to return JSON (was accidentally changed to HTML in a prior session); HTML board view moved to `GET /board/view`; sidebar link updated to `/board/view`
  - `tests/test_ui.py` — Updated stale string assertions to match current UI text: `"Reed-first job search"` → `"Search across connected job boards"`, `"Invalid or expired Reed selection token"` → `"Invalid or expired selection token"`, `"Enter and review one job"` → `"Evaluate a job"`, `"Recent evaluated jobs"` → `"Evaluated jobs"`, removed two help-text assertions that no longer exist in the UI

### How to add a new job source (e.g. Adzuna)
1. Create `src/job_sources/adzuna_source.py` with self-contained rendering + search logic (import only from `adzuna_client.py`, `source_registry.py`, and stdlib — no circular dependency on `job_hunt_ui.py`)
2. Call `register(JobSource(...))` at module level in that file
3. In `src/job_hunt_ui.py`, add one import line: `from src.job_sources import adzuna_source as _adzuna_src; _ = _adzuna_src`
4. No routing, dispatch, or rendering changes needed in `job_hunt_ui.py`

---

## 2026-06-16

### P4-2 · GAP-G — Cover Letter Extension + Route
- **Status:** ✅ COMPLETE — 291/291 tests green
- **Changes:**
  - `src/job_hunt_cover_letter.py` — Added keyword-only `tone` ("professional"/"conversational"/"concise"), `length` ("brief"/"standard"/"detailed"), `points` params to `generate_cover_letter_text()`; added `_apply_tone()`, `_filter_grounded_points()`, `save_cover_letter()` helpers; input validation raises `ValueError` on invalid tone/length
  - `src/job_hunt_ui.py` — Added `POST /cover-letter` route; decision gate blocks skip (400); accepts apply and review; saves to `output/cover_letters/<job_id>.txt`; returns `{letter, word_count, saved_path}`
  - `tests/test_cover_letter.py` — 9 new tests: verbatim why_company_text, all tones, length comparison, grounded points, error validation
  - `tests/test_ui.py` — 4 new route tests: apply → 200, skip → 400, missing fields → 400, unknown job → 404
- **Method:** Claude Code subagent

### P4-1 · GAP-F — Tailor CV Enrichment + Route
- **Status:** ✅ COMPLETE — 278/278 tests green
- **Changes:**
  - `src/job_hunt_models.py` — Added `TailoredCVResult` dataclass (`summary`, `promoted`, `matched`, `missing`, `markdown`; `slots=True`)
  - `src/job_hunt_tailoring.py` — `tailor_cv()` now returns `TailoredCVResult`; added `_build_summary()`, `_build_promoted()` helpers; computes `matched`/`missing` keyword diff; `validate_tailored_cv()` accepts `TailoredCVResult`, validates promoted bullets appear verbatim in markdown; `save_tailored_cv()` accepts `TailoredCVResult | str`
  - `src/job_hunt_ui.py` — Added `POST /tailor` route with decision gate (403 skip, 400 review without `manual_selected=true`, proceed on apply); returns `{summary, promoted, matched, missing, markdown, saved_path}`
  - `tests/test_tailoring.py` — 6 existing tests updated to use new API; 7 new tests: return type, summary, promoted, matched/missing invariants, validation accept/reject
  - `tests/test_ui.py` — 4 new route tests: apply → 200, skip → 403, review without manual_selected → 400, unknown job → 404
- **Method:** Claude Code subagent

### P3-1 · GAP-H — Board Aggregate + SQLite Index
- **Status:** ✅ COMPLETE — 267/267 tests green
- **Changes:**
  - `src/job_hunt_index.py` — New module: SQLite schema (`jobs` table), `open_db()`, `upsert_job()`, `query_jobs_list()`, `query_board()` (6 columns + active/interviews/offers/response_rate stats + `allowed_transitions` per card), `rebuild_index()` (wipes and rebuilds from JSON, skips bad files)
  - `src/job_hunt_ui.py` — Added `GET /jobs`, `GET /board`, `POST /jobs/save` routes; startup auto-rebuild if DB missing; upsert hooks after evaluate, outcome update, and decision-override writes
  - `tests/test_index.py` — New: 10 tests covering upsert, query, board grouping, stats, transitions, replace semantics, NULL handling, rebuild from JSON
  - `tests/test_ui.py` — 4 new route tests: empty jobs list, board 6 columns, save creates not_applied outcome, list after save
- **Method:** Claude Code subagent

### P2-3 · GAP-E — Decision Override Persistence
- **Status:** ✅ COMPLETE — 253/253 tests green
- **Changes:**
  - `src/job_hunt_models.py` — Added `user_decision: str | None = None` and `user_decision_note: str | None = None` to `JobAnalysis`; added module-level `effective_decision(analysis)` function
  - `src/job_hunt_storage.py` — `job_analysis_from_dict()` reads both new fields with `None` defaults (backward compat)
  - `src/job_hunt_tailoring.py` — Tailoring gate now uses `effective_decision()` instead of raw `decision`
  - `src/job_hunt_cover_letter.py` — Cover letter gate now uses `effective_decision()`
  - `src/job_hunt_reporting.py` — Report rows export both `engine_decision` and `user_decision` columns
  - `src/job_hunt_ui.py` — Added `POST /job/<job_id>/decision` route (set/clear override, returns JSON with engine + user decision); Evaluate screen shows Apply/Review/Skip override buttons with active-highlight and "Overridden" badge
  - `tests/test_models.py` — 3 new tests: defaults, effective_decision no-override, effective_decision with override
  - `tests/test_storage.py` — 3 new tests: round-trip with values, round-trip None, backward compat with old JSON
  - `tests/test_evaluation.py` — 1 new test: `user_decision=None` on all new analyses
  - `tests/test_reporting.py` — 2 new tests: engine_decision and user_decision columns present
  - `tests/test_ui.py` — 4 new route tests: valid set, clear with null, invalid value → 400, unknown job → 404
- **Method:** Claude Code subagent

### P2-2 · JOB-008 — ATS Scorer Integration
- **Status:** ✅ COMPLETE — 240/240 tests green
- **Changes:**
  - `src/job_hunt_models.py` — Added `ats_score: int | None = None` to `JobAnalysis`
  - `src/job_hunt_evaluation.py` — Calls `score_cv()` after scoring when `profile.master_cv_text` is set; `None` when absent; score does not affect `match_score` or `decision`
  - `src/job_hunt_storage.py` — `job_analysis_from_dict()` reads `ats_score` with `None` default (backward compat)
  - `src/job_hunt_ui.py` — Evaluate screen shows "ATS readiness: N / 100" or "ATS score: N/A (no CV on file)" in score breakdown panel
  - `tests/test_evaluation.py` — 2 new tests: score populated when CV present, None when absent
  - `tests/test_storage.py` — 2 new tests: ats_score round-trips with value and None
- **Method:** Claude Code subagent

### P2-1 · Source Quality Gating
- **Status:** ✅ COMPLETE — 236/236 tests green
- **Changes:**
  - `src/job_hunt_models.py` — Added `source_quality_score: int | None = None` to `JobPosting`
  - `src/job_hunt_config.py` — Added `SOURCE_QUALITY_SKIP_THRESHOLD = 40`, `SOURCE_QUALITY_REVIEW_THRESHOLD = 70`; added `"marginal-source-quality"` to `DEFAULT_DECISION_POLICY.critical_risk_codes`
  - `src/job_hunt_evaluation.py` — Added `_source_quality_blockers_and_flags()` and injected into `evaluate_reviewed_job()`
  - `src/job_hunt_orchestrator.py` — Populates `source_quality_score` from normalised Reed result
  - `src/job_hunt_reviewed_input.py` — Accepts `source_quality_score` in `reviewed_job_from_dict()` with `None` default
  - `src/job_hunt_ui.py` — Evaluate screen shows amber badge (40–69) or red badge (<40) for source quality
  - `tests/test_evaluation.py` — 4 new tests: None no-gate, <40 skip, 40–69 review, ≥70 no effect
- **Method:** Claude Code subagent

### P1-2 · GAP-C/I — Source Feature Flag
- **Status:** ✅ COMPLETE — 29/29 tests green
- **Changes:**
  - `src/job_hunt_config.py` — Added `ENABLED_SOURCES: list[str] = ["Reed"]` and `get_enabled_sources()` helper
  - `src/job_hunt_ui.py` — Added `GET /sources` route returning `{"enabled": ["Reed"]}`; Find Jobs tab now shows Reed as active, Adzuna and LinkedIn greyed out with "Coming soon"
  - `tests/test_ui.py` — Added `test_get_sources_returns_enabled_list`
- **Method:** Claude Code subagent (parallel build)

### P1-3 · GAP-D — Field Provenance (Null Contract)
- **Status:** ✅ COMPLETE — 232/232 tests green
- **Changes:**
  - `src/job_hunt_parsing.py` — All extraction functions now return `None` (scalars) or `[]` (lists) when a field is not found; `work_mode` returns `"unknown"` (not `None`); `job_id` falls back to `uuid4()[:8]` when both title and company are `None`; `_normalise_work_mode()` returns `"unknown"` for missing input
  - `src/job_hunt_ui.py` — Field-review badges added to Add Job form: "Auto-filled" (green) for present values, "Not found" (amber) for `null`/empty; badge visibility toggled by `parseAndPreview()` JS after prefill; CSS classes `.field-badge`, `.badge-autofilled`, `.badge-notfound` added to global stylesheet
  - `tests/test_parsing.py` — 15 null-contract tests covering every scalar and list field
- **Method:** Claude Code subagent (parallel build, combined with P1-4)

### P1-4 · JOB-009 — Harden URL Fetcher
- **Status:** ✅ COMPLETE — 232/232 tests green
- **Changes:**
  - `src/job_hunt_parsing.py` — `parse_job_from_url()` hardened with 8 security controls: host allowlist (`ALLOWED_HOSTS` frozenset), HTTPS-first redirect revalidation (max 3 hops), 8s network / 2s parse split timeout, content-type guard, 5MB content-size guard, robots.txt fail-closed (`_RobotsCache` with 5-min TTL — any error blocks the fetch), script/style/iframe stripping, SSRF prevention (private/loopback IP rejection via `_check_ssrf()`)
  - `src/job_hunt_paste_fetch.py` — Zeroed out (dead code; file cannot be deleted in sandbox but is empty and has no imports)
  - `tests/test_parsing.py` — 14 URL hardening tests: allowlist, SSRF, robots.txt fail-closed, content-type/size, redirect revalidation, max hops, HTTP scheme rejection
- **Method:** Claude Code subagent (parallel build, combined with P1-3)

### P1-1 · GAP-B — Skill Dataclass
- **Status:** ✅ COMPLETE — 73/73 tests green
- **Scope:** Replaced `CandidateProfile.skills: list[str]` with `list[Skill]` across the full blast radius.
- **Changes:**
  - `src/job_hunt_models.py` — Added `Skill` dataclass (`name`, `level`, `years`, `evidence_type`) with `__post_init__` validation; constants `VALID_SKILL_LEVELS`, `VALID_EVIDENCE_TYPES`
  - `src/job_hunt_profile.py` — `_coerce_skill()` backward-coerces plain JSON strings to `Skill` on load; `_skill_to_dict()` serialises back; round-trip clean
  - `src/job_hunt_scoring.py` — extracts `s.name` list before skill-match loop
  - `src/job_hunt_tailoring.py` — lookup dicts use `skill.name` (lines 22, 121)
  - `src/job_hunt_cover_letter.py` — `_match_skills()` accepts `list[Skill]` via `hasattr` guard
  - `src/job_hunt_ui.py` — My Profile page: skills table (name / level / years) replaces comma input; JS encodes rows to `skills_json` on submit; save handler parses `skills_json` first, falls back to comma-split; summary row shows `s.name` not raw string
  - `docs/data_contract.md` — Skills contract section updated with Skill object shape, valid values, and coercion note
- **Tests added:**
  - `tests/test_models.py` — 6 Skill validation tests (defaults, empty name, bad level, bad evidence_type, negative years, valid fields)
  - `tests/test_profile.py` — 5 coercion/round-trip tests (plain string coercion, dict round-trip, missing name, bad level, save-reload)
  - `tests/test_scoring.py`, `test_tailoring.py`, `test_cover_letter.py`, `test_evaluation.py`, `test_integration_flow.py` — all `build_candidate()`/`build_profile()` fixtures updated to `list[Skill]`
- **Design review:** Wiser (5 blockers) and Codex reviews applied; design doc updated before build; 8 recurring design doc mistake patterns saved to memory.

---

## 2026-05-22

### Public Web Extraction POC
- **Status**: LIVE_POC_GO
- **Path**: `poc/public_web_extraction/`
- **Scope**: Broader read-only Browse CLI extraction study for public product, pricing, blog, careers, and company/about pages; separate from `poc/browser_enrichment/`.
- **Evidence**: v2 rerun on 2026-05-22: `python3.14 -m pytest poc/public_web_extraction/tests -v` -> 25/25 passed. `python3.14 poc/public_web_extraction/run_preflight.py` -> 20 candidates, 17 passed, 3 failed. `python3.14 poc/public_web_extraction/run_live_extraction.py` -> 10 extraction attempts, 9 successful extractions, 1 failed extraction, average quality 96, average confidence 91, safety violations 0.
- **Fix note**: `extracted_pages.json` had been overwritten by a pytest fixture because `test_max_pages_per_run_enforcement` called `run_live_extraction.run()` without isolating the output path. The test now writes to `tmp_path`, and the live output files were regenerated together.
- **Output**: `output/candidate_preflight.json`, `output/extracted_pages.json`, `output/research_summary.json`, `output/extraction_report_v2.md`, 9 markdown exports, screenshots, snapshots.
- **Recommendation**: GO for continued private POC/research use only; not production integration and not account/action automation.

## 2026-05-21

### Handy Task 12 — Models Code Review & Documentation Sync
- **Status**: REVIEW_COMPLETE
- **Findings**: Verified `job_hunt_models.py` contains:
  - 9 core model classes with strict validation
  - 12 validation rules enforced (non-empty fields, numeric constraints)
  - Clear separation of concerns between profile, job, analysis, and outcomes
- **Action**: Created `docs/models_overview.md` with:
  - Class structure diagrams
  - Validation rule matrix
  - Usage examples

### Handy Task 13 — Codebase Audit
- **Status**: COMPLETED
- **Findings**: Verified all code changes since 2026-04-14 are present including:
  - `src/job_hunt_config.py`
  - `src/job_hunt_scoring.py`
  - `src/job_hunt_decision.py`
  - Expanded test suite (180+ tests)
- **Action**: Updated `PROJECT_CONTEXT.md` with current module list

### PL-04 — Reed Raw Response Audit Storage (Final)
- **Status**: QA_COMPLETE
- **Key Updates**: Implemented `source_snapshot` storage in `raw_inputs/<job_id>.json`, validation for 20KB payload cap, and separation between raw input and analysis records

### UI Polish (Unplanned but Completed)
- **Status**: IMPLEMENTED
- **Changes**: Improved Reed result cards, keyboard navigation support, responsive design, and enhanced `/select/reed` error handling

### Testing Infrastructure Upgrades
- **Status**: UPGRADED
- **Changes**: Added pytest plugins, test coverage reporting, and `test_requirements.txt` for QA environments

### COMPLETED TODO Items
- **JOB-001**: Tailoring truth validation (180/180 tests passing)
- **JOB-002**: Reed orchestrator integration (QA passed Apr 12–13)
- **JOB-007**: URL ingestion design (created and QA-reviewed)
- **JOB-006**: Reed viewer cleanup (canonical version established)

### Remaining High-Priority Items
1. **JOB-005**: Cover letter tests (missing `tests/test_cover_letter.py`)
2. **JOB-008**: ATS scorer verification (needs integration confirmation)
3. **JOB-009**: Paste-fetch clarification (requires design review)
4. **JOB-010**: CV tailoring brief review (pending Wiser review)

### Technical Debt Inventory
- Test file organization (3 files >100 lines without subsections)
- API error response inconsistencies
- Documentation gaps (`docs/models_overview.md`, `docs/swagger.json`)

### Next Steps Recommendation
1. Complete documentation updates
2. Address test file organization
3. Resolve API error response inconsistencies
4. Schedule Wiser review for pending items
