# Job Seeking Tool — UI and Functions Audit (2026-09-19)

Scope: what the UI exposes, which backend routes and modules back it, where docs
and code disagree, robustness observations, and ranked extension candidates.
Branch audited: `wip/search-relevance-digest-hardening-2026-09-18` (HEAD `d25394e`).
Method: read-only scan by two scout passes (routing/handlers/docs, then render
layer and domain modules) plus an independent verifier that re-checked its claims
against the code (see Verification note at the end). Line numbers refer to the files as of the audit date.

---

## 1. UI surfaces → backend routes

All routing lives in `src/ui_routes.py` (do_GET / do_POST dispatch tables at
`src/ui_routes.py:266-452`). 50 top-level `handle_*` / `render_*` functions exist in
`src/ui_handlers.py`.

### GET routes (`src/ui_routes.py:266-330`)

| Route | Handler | Line |
|---|---|---|
| `/` | `render_home` | 267 |
| `/search/{source}/more` | `handle_source_search_more` | 271 |
| `/search/{source}` | `handle_source_search` | 275 |
| `/sources` | `handle_sources` | 278 |
| `/jobs` | `handle_get_jobs` | 281 |
| `/jobs/not-interested` | `handle_jobs_hidden_list` | 284 |
| `/saved-searches` | `handle_saved_searches_list` | 287 |
| `/digest/count` | `handle_digest_count` | 290 |
| `/digest` | `handle_digest` | 293 |
| `/digest/llm-queue` | `handle_llm_queue` | 296 |
| `/scheduler/status` | `handle_scheduler_status` | 299 |
| `/board` | `handle_get_board` | 302 |
| `/board/view` | `handle_get_board_view` | 305 |
| `/profile` | `render_profile` | 309 |
| `/job/{id}/explain` | `handle_job_explain` | 313 |
| `/job/{id}/evaluate-form` | `handle_evaluate_form` | 317 |
| `/job/{id}` | `render_job` | 321 |
| `/review-queue` | `handle_get_review_queue` | 324 |
| `/batch/{id}` | `handle_get_batch` | 328 |
| anything else | 404 | 330 |

### POST routes (`src/ui_routes.py:355-452`) — 27 endpoints, all dispatched to a live handler

`/job/{id}/decision`, `/job/{id}/add-gap-skills`, `/job/{id}/ai-review-cv`,
`/job/{id}/ats-recheck`, `/job/{id}/qualitative-assess`, `/jobs/batch-evaluate`,
`/jobs/batch-assess`, `/batch/{id}/cancel`, `/jobs/save`, `/jobs/not-interested`,
`/jobs/not-interested/undo`, `/saved-searches`, `/scoring-preset`,
`/digest/mark-seen`, `/digest/run-llm-batch`, `/digest/reevaluate`,
`/saved-searches/{id}/delete`, `/saved-searches/{id}/toggle`,
`/saved-searches/{id}/run-now`, `/tailor`, `/cover-letter`, `/profile/parse-cv`,
`/evaluate`, `/select/{source}`, `/prefill`, `/job-submit`, `/outcome`,
`/outcome/reset`, `/profile/save`.

### Orphans

- `handle_search_reed_more` (`src/ui_handlers.py:1771`) is imported at
  `src/ui_routes.py:70` but no route calls it. Superseded by the generic
  `handle_source_search_more` (`src/ui_routes.py:271`). Only reference outside
  the definition is `tests/test_ui_handlers_uncovered.py`.
  Grep used: `handle_search_reed_more` across `src/**/*.py` and `tests/**/*.py`.
- GAP-J Gap Coach `GET /coach` is listed in the Feature Map (`INDEX.md:193`) as
  *not yet implemented* and indeed does not exist: no match for `gap_coach`,
  `aggregate_gaps`, `top_strengths` or `/coach` in `src/*.py` or
  `src/job_sources/*.py`. Docs are accurate here; this is a gap, not drift.

(Page-by-page render inventory is in §6.2.)

---

## 2. Backend function groups

| Group | Module(s) | Test file(s) | Notes |
|---|---|---|---|
| Ingestion (Reed / Adzuna / LinkedIn) | `src/job_sources/{reed,adzuna,linkedin}_{client,source}.py` | `tests/test_reed_adzuna_clients.py`, `tests/test_linkedin_source.py`, `tests/test_source_forms.py` | Keys read via `os.getenv("REED_API_KEY")` (`src/job_sources/reed_client.py:44`) and `ADZUNA_APP_ID/KEY` (`src/job_sources/adzuna_client.py:23-24`); missing key logs an error and marks the source unavailable rather than raising. |
| Search / relevance / dedup | `src/job_sources/relevance.py`, `src/job_sources/search_state.py`, `src/job_sources/dedup.py` | `tests/test_relevance.py`, `tests/test_search_dedup.py`, `tests/test_dedup.py`, `tests/test_multi_keyword_search.py` | Tests not listed in `INDEX.md`'s test table (see §3). |
| Scoring / decision | `src/job_hunt_scoring.py`, `src/job_hunt_decision.py`, `src/job_hunt_config.py`, `src/job_hunt_scoring_presets.py` | `tests/test_scoring.py`, `tests/test_decision.py`, `tests/test_scoring_presets.py`, `tests/test_scoring_preset_ui.py` | |
| A–F grade / qualitative | `src/job_hunt_qualitative.py`, `src/text_grounding.py` | `tests/test_qualitative.py` | |
| Batch assessment queue | `src/job_hunt_scheduler.py` (`process_eval_queue_once`), `src/job_hunt_index.py` (`eval_queue` / `eval_batch` tables) | `tests/test_eval_queue.py` | |
| Digest / triage | `src/job_hunt_digest.py`, `src/job_hunt_scheduler.py` (`DigestScheduler`, `LLMQueueWorker`), `src/job_hunt_not_interested.py` | `tests/test_digest.py`, `test_digest_ui.py`, `test_digest_worker.py`, `test_digest_scheduler.py`, `test_digest_e2e.py`, `test_digest_reeval.py`, `test_digest_pipeline.py`, `test_not_interested.py` | None of the digest test files appear in `INDEX.md`'s test table. |
| CV tailoring / cover letter | `src/job_hunt_tailoring.py`, `src/job_hunt_cover_letter.py` | `tests/test_tailoring.py`, `tests/test_cover_letter.py` | |
| ATS scoring | `src/job_hunt_ats_scorer.py`, `src/job_hunt_keyword_match.py` | `tests/test_ats_scorer.py`, `tests/test_keyword_match.py`, `tests/test_f1_recheck.py` | |
| Application tracking / outcomes | `src/job_hunt_track_store.py`, `src/job_hunt_outcomes.py` | `tests/test_track_store.py`, `tests/test_outcomes.py` | |
| Persistence / state | `src/job_hunt_storage.py`, `src/job_hunt_index.py` (SQLite) | `tests/test_storage.py`, `tests/test_index.py` | `data/state/` holds `raw_inputs/`, `reviewed_jobs/`, `analyses/`, `outcomes/` (`INDEX.md:73`). Git status shows many untracked `data/state/analyses/*.json` and several `.fuse_hidden*` files. |
| Unrelated "swarm" infra | `src/shared_bus.py` | `tests/test_shared_bus_getters.py`, `tests/test_swarm_stage_derivation.py`, `tests/test_swarm_router_auto_advance.py`, `tests/test_session_guard.py`, `tests/test_multi_llm_chat.py` | Cross-project feature bundled into this repo (`PROJECT_TODO.md:442-446`, QW-4). DB path env-overridable via `SHARED_BUS_DB`; previously hardcoded to `~/.openclaw/workspace/shared_memory.db`. |

**TODO / FIXME / stub grep over `src/`** (pattern `TODO|FIXME|NotImplemented|not yet implemented|stub|XXX|HACK`): one hit,
`src/job_sources/linkedin_source.py:7` ("TODO (v2): Cookie-based auth"). `tests/` and `docs/` were not grepped for the same pattern.

---

## 3. Docs-vs-code drift

| Doc says | Code has | Evidence |
|---|---|---|
| `INDEX.md` test table lists 25 test files | `tests/` has 61 `.py` files; about 36 are undocumented (relevance, dedup, digest ×7, saved_searches, qualitative, eval_queue, scoring_presets ×2, tailoring, cover_letter, ats_scorer, parsing, validation, index, lint, normalize, quality_score, multi_keyword_search, multiselect_shared, bookmark_evaluate, relevance_ui, f1_recheck, not_interested, swarm / session-guard / chat files) | `INDEX.md:104-133` vs Glob `tests/*.py` |
| `PROJECT_TODO.md` "Last updated: 2026-07-29" | Feature commits through 2026-09-18 (`d25394e`, `63a055e`) not reflected in its Completed / Summary tables | `PROJECT_TODO.md:8` vs git log |
| `docs/tasks/url-ingestion-design.md:283` says delete `src/job_hunt_paste_fetch.py` | File still present, 0 bytes | file read |
| `src/job_hunt_paste_ui.py:1-6` self-documents "DEPRECATED … run `git rm`" | File still present, no live import | grep across `src/` finds only the self-reference |
| `src/ui_routes.py:70` imports `handle_search_reed_more` | No route calls it | `src/ui_handlers.py:1771` |
| Feature Map row for GAP-J Gap Coach | Correctly marked not implemented — no drift | `INDEX.md:193` |

No route in `src/ui_routes.py` was found missing from the Feature Map (`INDEX.md:167-217`); spot-checked, not line-by-line exhaustive.

---

## 4. Quality / robustness observations (ranked by impact)

1. **High — stale planning docs.** `PROJECT_TODO.md` and the `INDEX.md` test table lag the code by about seven weeks. Planning from them will misjudge what is done.
2. **Medium — dead code left in place.** Two self-flagged files (`src/job_hunt_paste_fetch.py`, `src/job_hunt_paste_ui.py`) and one orphan handler (`handle_search_reed_more`).
3. **Medium — scope creep bundled in.** `src/shared_bus.py` plus five test files belong to a cross-project "swarm" feature, not the job-hunt product. Needs a keep-or-prune decision from Mike.
4. **Low — external API failure handling is graceful.** Reed / Adzuna key absence logs and disables the source (`src/job_sources/reed_client.py:44-46`, `src/job_sources/adzuna_client.py:23-27`); Gemini key absence returns a user-facing message (`src/job_hunt_llm.py:103,130,165`). No credential values were read.
5. **Low — stray `.fuse_hidden*` files** under `data/state/` (per git status) look like interrupted-write artefacts on a FUSE-mounted volume. Not inspected further.
6. **Tracked deferrals** (`PROJECT_TODO.md:187-196`): LinkedIn pagination throttling (block / CAPTCHA risk, no design doc), multi-select single-grid-per-page assumption.

---

## 5. Extension opportunities (ranked)

Size: S ≤150 lines, M a few hundred, L needs a data-source or architecture decision first.

### Finish what is half-built

| # | Idea | Builds on | Size | Why it helps |
|---|---|---|---|---|
| 1 | CAREER-F1 bulk URL / JD paste → batch assessment | `/prefill` path in `src/ui_handlers.py`, `handle_batch_assess` (`src/ui_handlers.py:1914`) | M | Batch-assess today only works from review-queue selection; bulk paste lets many postings be triaged per session. Deferred at `PROJECT_TODO.md:374-376`. |
| 2 | Gap Coach `GET /coach` | Spec already written: `docs/tasks/gap-j-gap-coach-design.md`; profile skills model; `JobAnalysis.missing_required_skills` | M | Aggregates skill gaps across evaluated jobs into an upskilling list aimed at £75K+ AI-adjacent BA/PM roles. Zero code exists. |
| 3 | Remove dead code (two paste_* files, orphan handler + its test). Not `generate_cover_letter`, which is live | `src/job_hunt_paste_fetch.py`, `src/job_hunt_paste_ui.py`, `src/ui_handlers.py:1771` | S | Both files already say "delete me". |
| 4 | Refresh `PROJECT_TODO.md` and the `INDEX.md` test table | `INDEX.md:104-133`, `PROJECT_TODO.md` | S | Restores the docs as a trustworthy map before further planning. |
| 5 | LinkedIn pagination throttling before deep "More jobs" paging | `src/job_sources/linkedin_source.py` | S–M | Protects a working source from a block / CAPTCHA. Tracked at `PROJECT_TODO.md:191`. |

### Genuinely new

| # | Idea | Builds on | Size | Why it helps |
|---|---|---|---|---|
| 6 | Salary benchmark via Adzuna salary / histogram endpoints (F5) | `src/job_sources/adzuna_client.py` (already wired) | M | `PROJECT_TODO.md:211` lists F5 as researched-not-designed; the Adzuna client is live so build cost is low. Directly serves a salary-driven search. |
| 7 | Comp-vs-market dimension in qualitative assessment (CAREER-F2) | `src/job_hunt_qualitative.py` + item 6 as the data feed | L | Excluded for lack of a market feed (`PROJECT_TODO.md:378-380`); item 6 unblocks it. |
| 8 | Export / packaging: single-file bundle of tailored CV + cover letter + analysis | `src/job_hunt_tailoring.py`, `src/job_hunt_cover_letter.py`, `src/job_hunt_reporting.py` | M | Listed as remaining "packaging/export improvements" in `PROJECT_CONTEXT.md:143`; no code found. |
| 9 | Focused review of the unmerged digest / triage branch work | `src/job_hunt_scheduler.py`, `src/job_hunt_digest.py` | M | The current WIP branch carries digest / triage hardening the docs have not caught up with; review before building on it. |

### Decision, not build

| # | Item | Where |
|---|---|---|
| 10 | Keep or prune the bundled "swarm" / multi-LLM-chat infra | `src/shared_bus.py`, `viewer/session_guard.py`, five test files |

---

## 6. Second pass — render layer, domain modules, spec docs

### 6.1 Highest-impact finding: cover-letter form fails on default values

The job-detail form offers Length `short/medium/long` and defaults to `medium`
(`src/ui_render.py:1457,1560`), and Tone includes `friendly` (`src/ui_render.py:1452`).
`generate_cover_letter_text` accepts only Tone `professional/conversational/concise` and
Length `brief/standard/detailed` and raises `ValueError` otherwise
(`src/job_hunt_cover_letter.py:16-17,61-64`). The server default is `standard`
(`src/ui_handlers.py:2527-2528`), so the inline JS default and the server default disagree.
`tests/test_ui.py:1839-1861` never sends tone or length, so no test catches it.
Verified by a fresh verifier: with the form's own defaults (Tone `professional`, Length `medium`) the call raises `ValueError: Invalid length: 'medium'` before any network call. Tone `friendly` fails too. The handler turns this into an HTTP 400 with the message (`src/ui_handlers.py:2591-2593`), so the user sees an error, not a crash. Only Length values `brief/standard/detailed` work.

### 6.2 Page-by-page UI inventory

All pages share the sidebar (`src/ui_render.py:2618-2694`): Find Jobs, Add & Evaluate,
Advanced Review, History, Board View, Digest, My Profile. All seven links land on live routes.

| Page | Renders (path:line) | Submits to |
|---|---|---|
| Home / Search tab | `_render_shared_search_form` `src/ui_handlers.py:2660-2716`; per-source `formaction` `:2750`; disabled "Coming soon" buttons `:2754-2756` | `GET /search/{source}` |
| Home / Evaluate tab | form `src/ui_render.py:216` | `POST /evaluate` |
| Home / Add & Evaluate tab | `_render_add_job_tab` `src/ui_render.py:396-513`; fetch `:474`; form `:420` | `POST /prefill`, `POST /job-submit` |
| Search results (all sources) | `src/job_sources/_multiselect.py:203,218,261,274,336,400,412,417,502` | `/jobs/batch-evaluate`, `/jobs/not-interested` (+`/undo`), `/search/{source}/more` |
| Review queue | `render_review_queue_page` `src/ui_render.py:250-385`; form `:367`; iframe `:329,378` | `POST /jobs/batch-assess` |
| Batch progress | `handle_get_batch` `src/ui_handlers.py:1969-2023`; cancel form `:2016` | `POST /batch/{id}/cancel` |
| Job detail | `render_job_page` `src/ui_render.py:842-1876`: qualitative `:1008`, ATS `:805,828`, explain `:1293`, gap skills `:1346`, decision `:1332`, tailor `:1481`, AI review `:1508`, cover letter `:1572` | matching `/job/{id}/*`, `/tailor`, `/cover-letter` |
| Board view | `render_board_page` `src/ui_render.py:95-172` | links to `/job/{id}` only |
| My Profile | `render_profile_page` `src/ui_render.py:1923-2464`: parse-cv `src/ui_handlers.py:2256`, save `:2122`, saved searches `:2412-2445`, preset `:1978` | `/profile/*`, `/saved-searches*`, `/scoring-preset` |
| Daily Digest | `render_digest_page` `src/ui_render.py:2464-2615`: filter `:2502`, mark-seen `:2586`, reevaluate `:2595` | `/digest`, `/digest/mark-seen`, `/digest/reevaluate` |

**Every form and fetch target resolves to a route in section 1. No dead buttons found.**

**Routes with no page link** (grep `digest/llm-queue|scheduler/status|run-llm-batch|"/jobs"` over `src/*.py`, only dispatch and docstring hits):
`GET /digest/llm-queue`, `GET /scheduler/status`, `POST /digest/run-llm-batch`, `GET /jobs` (JSON), `GET /board` (JSON).
`/review-queue` is reachable only through a JS redirect after batch-evaluate (`src/job_sources/_multiselect.py:412`), not from the sidebar.

### 6.3 UX and robustness issues in the render layer

1. Cover-letter defaults fail (6.1). Highest impact.
2. Qualitative assessment is a plain full-page form POST with no spinner while the LLM runs (`src/ui_render.py:1008`), unlike Explain, Tailor and AI-review which use fetch with loading and error states (`:1285-1321`).
3. Review queue uses raw inline-styled panels (`src/ui_render.py:340-384`) outside the app shell the mobile breakpoint targets (`:2903-2932`). Likely poor on narrow screens. UNVERIFIED, inferred from code, no browser render.
4. Digest operational data (Gemini quota via `llm_queue_stats` `src/job_hunt_scheduler.py:653`; daemon status `src/ui_handlers.py:2356-2364`) is computed but never shown on `/digest`.
5. Blocking `alert()` on copy failure (`src/ui_render.py:1540`).
6. ~~Outer home tab strip has no ARIA tab roles~~ **Withdrawn 2026-09-21:** there is no client-side tab strip. `src/ui_render.py:208-233` holds content panels, and each "tab" is a full page load from a sidebar link. The correct pattern is `aria-current="page"` on the sidebar, now applied. Extension candidate H is void.

### 6.4 Domain modules

| Module | Key entry points | Notes |
|---|---|---|
| `job_hunt_scoring.py` | `score_job` `:23-85`; seven weighted components `:90-221` | Pure function. Weights validated to sum 100 (`job_hunt_config.py:36-39`). |
| `job_hunt_decision.py` | `decide_application` `:15-68` | Apply ≥80, Review ≥65 (`job_hunt_config.py:69-70`). Low confidence downgrades Apply to Review (`:36-43`). |
| `job_hunt_qualitative.py` | `derive_base_grade` `:51`, `run_qualitative_assessment_pipeline` `:151`, `parse_and_validate` `:352` | Grade bands A≥80 / B≥72 / C≥65 / D≥50 / F (`:51-61`). Caps only lower a grade. Two retries on bad JSON (`:184-206`). |
| `job_hunt_tailoring.py` | `tailor_cv` `:125`, `validate_tailored_cv` `:235-333` | Validator is real, not a stub. |
| `job_hunt_cover_letter.py` | `generate_cover_letter_text` `:28` (live route), `generate_cover_letter` `:174` | The second is NOT dead: `src/job_hunt_tailoring.py:9,490` imports and calls it inside a separate wrapper also named `generate_cover_letter_text` (`src/job_hunt_tailoring.py:467`). That wrapper is not used by the UI route. Rename risk: two functions share one name in two modules. |
| `job_hunt_ats_scorer.py` | `score_cv` `:6-37`, four 0-25 sub-scores | Thresholds are inline literals, not in config. |
| `job_hunt_index.py` | SQLite layer, `upsert_job` `:228`, queue lifecycle `:843-1112`, digest CAS `:1141-1220` | All helpers have callers in the scheduler. |
| `job_hunt_scheduler.py` | `run_digest_pipeline` `:129`, `DigestScheduler` `:836`, `LLMQueueWorker` `:781`, `process_eval_queue_once` `:686` | No orphaned helpers found. |
| `job_hunt_digest.py` | `query_digest` `:94`, `mark_seen` `:142` | Read model only. |
| `job_hunt_llm.py` | Models hard-coded `:23-27` (gemini-3.1-flash-lite, gemini-2.5-flash-lite, gemini-3-flash-preview, gemini-2.5-flash); endpoint `:36` | Failure handling is classified per error type (`:58-120`), with a distinct `RateLimited` (`:52-55`). |
| `job_hunt_config.py` | Policy dataclasses `:10-102`; source-quality thresholds 40 / 70 `:90-91`; `ENABLED_SOURCES` `:107` | |

**Score-range rule (Mike's standing rule):** decision, grade and ATS logic all use bands, not single anchor points. No violation found in these modules.

### 6.5 Spec-vs-code

| Spec or instruction says | Reality |
|---|---|
| `docs/function_list_v4.md` and `docs/ui_structure_v4.md` (named in the audit brief) | Neither exists. Only `docs/function_list.md` exists (Glob `docs/*v4*`, `docs/ui_structure*`). |
| `docs/function_list.md` latest dated entry 2026-07-22 | Commits `63a055e` and `d25394e` (2026-09-18) are not reflected. A third stale doc after `PROJECT_TODO.md` and the `INDEX.md` test table. |
| `docs/product_spec.md:26` source-quality gate (<40 Skip, 40-69 forced Review) | Threshold values match `job_hunt_config.py:90-91`. Comparison operators live in `job_hunt_evaluation.py`, not read. UNVERIFIED. |
| `docs/product_spec.md:27,33` Apply ≥80, grade A ≥80 | Matches code. No drift. |
| `docs/function_list.md:12` responsive CSS | Media block exists (`src/ui_render.py:2903-2932`), but the review queue sits outside it. |

### 6.6 TODO / skip / xfail grep over `tests/` and `docs/`

Patterns: `TODO|FIXME|NotImplemented|not yet implemented|stub|XXX|HACK`, plus `pytest.mark.skip|xfail|\.skip\(`.
- `docs/tasks/F1_v2_recheck_design.md:112` — deferred multi-profile TODO.
- `tests/test_lint.py:31` — `importorskip("pyflakes")`, conditional only.
- No `skip` or `xfail` markers anywhere in `tests/`. Other "stub" hits are fixture names.

### 6.7 Extra extension candidates from this pass

| # | Idea | Where | Size |
|---|---|---|---|
| A | Fix cover-letter tone/length mismatch, add a test that posts the real form values | `src/ui_render.py:1451-1457,1560`; `src/job_hunt_cover_letter.py:16-17` | S |
| B | Show digest health (Gemini quota left, daemon alive, run-LLM-batch button) on `/digest` | `src/job_hunt_scheduler.py:653`; `src/ui_handlers.py:2356-2399` | S |
| C | Spinner and fetch flow for qualitative assessment | `src/ui_render.py:1008` | S |
| D | Bring review queue into the responsive shell | `src/ui_render.py:250-385` | M |
| E | Resolve the duplicate `generate_cover_letter_text` name in `src/job_hunt_tailoring.py:467` and `src/job_hunt_cover_letter.py:28`; decide if the tailoring wrapper is still needed. Do NOT delete `generate_cover_letter` | `src/job_hunt_tailoring.py:467-490` | S |
| F | Add a nav link to `/review-queue`, or a way back to the last queue | `src/job_sources/_multiselect.py:412` | S |
| G | Move Gemini model names to config or env | `src/job_hunt_llm.py:23-27` | S |
| H | ARIA roles on the outer tab strip | `src/ui_render.py:208-233` | S |

## Not checked (second pass)

- Not read: `job_hunt_evaluation.py`, `job_hunt_reporting.py`, `job_hunt_orchestrator.py`, `job_hunt_profile.py`, `job_hunt_saved_searches.py`, `job_hunt_storage.py`, `job_hunt_track_store.py`, `job_hunt_outcomes.py`, source adapters under `src/job_sources/`.
- About 60 files under `docs/tasks/` were grepped, not read one by one.
- No browser render. All responsive and accessibility points are code inferences.

---

## Not checked (first pass)

- Full bodies of the scoring, decision, qualitative, tailoring, cover-letter, ATS, index, scheduler and digest modules: function-level claims rely on `INDEX.md`'s own module table (`INDEX.md:64-101`) unless the second pass says otherwise.
- `src/ui_render.py` (HTML rendering) — covered in the second pass.
- Individual `docs/tasks/*.md` beyond `url-ingestion-design.md` and `career-ops-absorption-design.md`.
- `docs/product_spec.md`, `docs/function_list_v4.md`, `docs/ui_structure_v4.md` — covered in the second pass.
- Test pass/fail status — run by the verifier (see the verification note at the end).
- `viewer/` beyond the `session_guard.py` reference; `.env` contents (deliberately not read); `data/` contents.

---

## Verification note (fresh-context verifier, 2026-09-20)

- **Corrected after verification:** function count 47 → 50; test files 62 → 61; `INDEX.md` table rows 22 → 25; `generate_cover_letter` is live, not dead.
- **Confirmed:** cover-letter mismatch (reproduced, above); orphan `handle_search_reed_more`; the two empty or deprecated paste files; the three digest and scheduler routes with no page link; about 20 spot-checked path:line references.
- **Test suite:** system `python3` (3.14) gives 10 failed, 1015 passed, 1 skipped. All 10 failures are missing modules (`bs4`, `dotenv`) in `tests/test_linkedin_source.py`, `tests/test_reed_adzuna_clients.py` and `tests/test_source_forms.py`. Not re-run in the project venv because `.venv-check/bin/python` is a dangling link. So the baseline is 1015 passing with 10 environment failures, not a clean pass.
- **Still unchecked:** `GET /jobs` and `GET /board` no-link claim; most §6.2 and §6.3 line references beyond spot-checks; mobile layout and ARIA claims (inferred from code, no browser render); whether every `INDEX.md` table row maps to an existing file, so "about 36 undocumented" is approximate.

> 2026-09-21 update: item 10 (keep or prune swarm / multi-LLM-chat infra) resolved. Mike chose to move it out; code, tests and data archived to `~/.openclaw/archive/2026-09-job-hunt-swarm-fork/`.
