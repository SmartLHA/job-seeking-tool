# Project Index

**For agents only** — which file to read for any given task. Updated as files are reviewed.
Used by SilverHand to brief Handy/Scout precisely, and by any agent to orient quickly.
**Not a product document** — it's an internal reference, not user-facing.

---

## Core Project Docs

| File | Purpose |
|------|---------|
| `PROJECT_CONTEXT.md` | Master project memory: direction, constraints, architecture, progress, next steps. Start here. |
| `PROJECT_LOG.md` | Dated history of all decisions, discussions, and implementation milestones. |
| `README.md` | CLI usage, UI startup, repo structure, expected input shapes, test commands. |

---

## Planning Docs (`docs/`)

| File | Purpose |
|------|---------|
| `docs/Requirement_Design_v1.md` | **Full requirements/design reference** (15 sections: product direction, modules + JSON schemas, data architecture, UI flows, dev sequence/phases, risk register, test requirements, OpenClaw instruction). Lossless conversion of the retired `To-AI/Requirement_Design_v1.docx` (2026-06-22). Historical design reference — source code is authoritative for implemented behaviour; the in-doc "Implementation Status — 22 June 2026" block supersedes older claims. |
| `docs/product_spec.md` | What the product is, MVP scope, goals/non-goals, user stories. |
| `docs/function_list.md` | Source-verified current module map, including the recovered split UI and F1 keyword matcher. |
| `docs/development_sequence.md` | Phased build order (Phase 0–8). |
| `docs/development_rules.md` | Non-negotiable build rules: local-first, truthful output, deterministic-first, tests. |
| `docs/data_contract.md` | MVP data shapes — JobPosting, JobAnalysis, blockers, score breakdown. |
| `docs/ui_scope.md` | Source-verified UI architecture, implemented workflows, routes, and remaining scope. |
| `docs/build_order.md` | **Build priority order** — 4 phases, 10 items, dependency map, effort ratings, related files per item. |
| `docs/architecture_guardrails.md` | Pre-implementation architecture discipline: state separation, module boundaries, policy config principles. |
| `docs/team_protocol.yaml` | Multi-agent team protocol: SilverHand/Handy/Scout roles, anti-idle rule, QA modes. |
| `Claude deliverable/docs/ui_structure_v4.md` | Historical Claude prototype/design input; not authoritative after the 2026-06-22 source reconciliation. Safe to remove manually once no longer needed. |
| `Claude deliverable/docs/function_list_v4.md` | Historical Claude function-design input; not authoritative after the 2026-06-22 source reconciliation. Safe to remove manually once no longer needed. |
| `Claude deliverable/Job Seeking Tool.html` | v4 interactive UI prototype — open in browser to see the full design. |
| `docs/tasks/gap-b-skill-dataclass-design.md` | GAP-B: Extend CandidateProfile.skills to list[Skill] with level/years/evidence_type; backward-compat loader. |
| `docs/tasks/gap-c-source-feature-flag-design.md` | GAP-C/I: get_enabled_sources() config + GET /sources route; gates Adzuna/LinkedIn toggles until wired. |
| `docs/tasks/gap-d-field-provenance-design.md` | GAP-D: Null-as-not-found parsing contract; UI tags auto-filled vs not-found per field. |
| `docs/tasks/gap-e-decision-override-design.md` | GAP-E: user_decision field on JobAnalysis; POST /job/<id>/decision; effective_decision() helper. |
| `docs/tasks/gap-h-board-aggregate-design.md` | GAP-H: GET /jobs, GET /board aggregate routes; POST /jobs/save bookmark; load_board() scan. |
| `docs/tasks/gap-j-gap-coach-design.md` | GAP-J: New gap_coach.py module; aggregate_gaps() + top_strengths() + GET /coach route. |
| `docs/tasks/source-quality-gating-design.md` | Source quality gating: <40 = skip blocker, 40–70 = force Review; thresholds in config. |
| `docs/tasks/cover-letter-spec-draft.md` | GAP-G: Cover letter v2 — tone/length/points params; POST /cover-letter route. |
| `docs/tasks/cv-tailoring-brief.md` | GAP-F: Tailoring v2 — TailoredCVResult with summary/promoted/matched/missing; POST /tailor route. |
| `docs/tasks/ats-score-deferred.md` | JOB-008: ATS scorer integration — ats_score on JobAnalysis; called from evaluate_reviewed_job(). |
| `docs/tasks/url-ingestion-design.md` | JOB-009: URL ingestion spec + hardening tasks for parse_job_from_url(); delete job_hunt_paste_fetch.py. |
| `docs/tasks/reed-search-first-story-breakdown.md` | Story breakdown for making Reed search the app's first/main journey before Evaluate. |
| `docs/tasks/pl-01-reed-search-first-shell-design.md` | PL-01 design: make the app landing shell search-first while preserving manual fallback. |
| `docs/tasks/pl-02-reed-search-form-api-wiring-design.md` | PL-02 design: app-native Reed search form, filters, and result rendering before selection/prefill. |
| `docs/tasks/pl-03-reed-select-prefill-evaluate-design.md` | PL-03 design: select a Reed result and prefill the existing Evaluate review form without auto-evaluating. |
| `docs/tasks/pl-04-reed-raw-response-audit-storage-design.md` | PL-04 design: carry selected Reed source snapshot into raw input audit storage on Evaluate. |
| `docs/tasks/pl-05-reed-search-polish-regression-hardening-design.md` | PL-05 design: final Reed-first flow polish, fallback safety, docs, and regression hardening. |
| `docs/tasks/search-triage-not-interested-design.md` | Search triage (2026-07-02): untick-default shortlist, per-card ✕ → persistent `not_interested_jobs` store (key + fingerprint), undo, Hidden jobs overlay, page-replace "Next page". Includes the Codex findings that reshaped the original "Remove selected" ask. |

---

## Source Code (`src/`)

> Lists the key modules. Not exhaustive — support/client modules (e.g. `job_hunt_index`,
> `job_hunt_llm`, `job_hunt_parsing`, `job_hunt_tailoring`, the `src/job_sources/` clients
> and `source_registry`, etc.) also exist; see `docs/function_list.md` for the full map.

| File | Purpose |
|------|---------|
| `src/job_hunt_models.py` | All dataclass models: `CandidateProfile`, `JobPosting`, `Blocker`, `RiskFlag`, `ScoreComponent`, `ScoreBreakdown`, `JobAnalysis`, `OutcomeEvent`, `ApplicationOutcome`. Validation in each model's `__post_init__`. `Decision = Literal["apply","review","skip"]`. `ConfidenceLevel = Literal["low","medium","high"]`. `OutcomeStatus = Literal["not_applied","applied","interview","rejected","offer","withdrawn"]`. |
| `src/job_hunt_config.py` | All tunable policy objects: `ScoringWeights` (skills_required=35, preferred=5, experience=20, location/salary/domain/work_mode=10 each), `ConfidencePolicy`, `ScoringPolicy`, `DecisionPolicy`. Apply threshold ≥80; review threshold ≥65; blockers always skip; `missing-required-skills` and `salary-below-floor` are critical risks gating apply. |
| `src/job_hunt_scoring.py` | `score_job(profile, job, policy)` → `ScoringResult`. 7-component weighted scoring: required skills (35pt), preferred skills (5pt), experience (20pt), location (10pt), salary (10pt), domain (10pt), work mode (10pt). Confidence (high/medium/low) derived independently from data completeness — NOT from score. Unknown fields get neutral credit but reduce confidence. Risk flags (`missing-required-skills`, `missing-preferred-skills`, `salary-below-floor`) built here. |
| `src/job_hunt_decision.py` | `decide_application(score, blockers, risk_flags, policy)` → `DecisionResult`. Priority: blockers → skip; score ≥80 + no critical risks → apply; score 65-79 → review; critical risks present → review (even with high score); else → skip. |
| `src/job_hunt_profile.py` | `load_candidate_profile(path)` / `save_candidate_profile(profile, path)`. `load_master_cv(path)` / `save_master_cv(content, path)`. `resolve_master_cv_path(profile, profile_path)` for relative-path resolution. `ProfileValidationError` on bad input. Unknown extra fields rejected. Master CV existence checked on load if `master_cv_ref` set. |
| `src/job_hunt_reviewed_input.py` | `reviewed_job_from_dict(payload, job_id)` → `JobPosting`. Converts pre-reviewed job JSON into typed model. Unknown extra fields rejected. Skill lists deduplicated case-insensitively. `ReviewedInputValidationError` on bad input. `reviewed_job_to_dict(job)` for round-trip. |
| `src/job_hunt_storage.py` | `ensure_storage_layout(root)` → `StorageLayout`. Four folders: `raw_inputs/`, `reviewed_jobs/`, `analyses/`, `outcomes/`. `save/load_reviewed_job`, `save/load_job_analysis`, `save/load_raw_input`, `save/load_application_outcome`. `job_analysis_to_dict/from_dict` for typed↔dict conversion. `StorageError` on bad storage data. |
| `src/job_hunt_scheduler.py` | **(Daily Digest D3/D5/D6 + OQ-2).** D3: `run_digest_pipeline -> DigestRunResult` (LLM-free pipeline; `_PIPELINE_LOCK` serialises with manual Run-now). D5: `DigestScheduler` daemon (poll loop, once-per-day at `digest_run_time`, exception-isolated, lock-guarded `status()`). D6: `drain_llm_batch` (worker-lock paced Gemini, 429→backoff+requeue, RPD cap, source-aware detail), `LLMQueueWorker` daemon, `save_analysis_llm_fields`, `rpd_date_key` (Pacific), `llm_queue_stats`. **OQ-2:** `reevaluate_digest_jobs -> ReevalResult` (under `_PIPELINE_LOCK`; re-score every digest row, crossed-up→resurface+requeue, dropped-below→dequeue), `row_status` helper. |
| `src/job_hunt_digest.py` | **NEW (Daily Digest D2).** Digest read model over the SQLite jobs index. `DigestEntry` dataclass; `query_digest(date/unseen_only/min_score/limit)`, `mark_seen`, `mark_all_seen`, `unseen_count`, `digest_stats`. Reads digest rows (`digest_date IS NOT NULL`); `DigestEntry.url` comes from `jobs.apply_url`. Negative LIMIT clamped; `mark_seen` de-dups + chunks the IN-list. Score filter uses `COALESCE(match_score,0) >= min_score` (NULL treated as 0; `min_score=0` returns all incl. unscored). |
| `src/job_hunt_saved_searches.py` | **NEW (Daily Digest D1).** SQLite-backed saved-search CRUD over a `saved_searches` table in `job_hunt_index.db` (owns its own `CREATE TABLE IF NOT EXISTS`). `SavedSearch` dataclass; `validate_search_id` (`^[A-Za-z0-9_-]{1,64}$`, every op); `create_saved_search` (mints `uuid4().hex`), `load/list/save/delete/toggle_saved_search`, `update_last_run`. Atomic toggle, params validated + defensively copied, corrupt-row resilient. `SavedSearchError`/`SavedSearchNotFound`. |
| `src/job_hunt_not_interested.py` | **NEW (Search triage 2026-07).** Persistent "not interested" store over a `not_interested_jobs` table in `job_hunt_index.db` (same WAL/busy-timeout plumbing as saved searches). Key `source:source_job_id` + fingerprint `sha1(source|title|company)` (matches survive unstable LinkedIn ids); 180-day prune on write. `hide_jobs` (idempotent), `unhide_jobs`, `list_hidden` (newest first), `count_hidden`, `hidden_lookup`, `filter_results(results) -> (visible, hidden_count)` — display-only filter used by search + pagination handlers. |
| `src/job_hunt_keyword_match.py` | **NEW (F1).** `compute_keyword_match(cv_text, required, preferred) -> KeywordMatchResult` — per-job ATS keyword coverage: edge-aware whole-token matching (handles `C#`/`C++`/`.NET`/`Node.js`/`CI/CD`), required-wins dedupe, null contract (no CV/keywords → rate `None`), overuse (>4×) anti-stuffing flag. Hooked in `evaluate_reviewed_job`; advisory/display only. |
| `src/job_hunt_validation.py` | **NEW (MT-2).** Canonical field validators shared by `storage`/`reviewed_input`/`profile`: `required_string` (`message_style`), `optional_string` (`empty_as_none`), `optional_text_or_empty`, `string_list` (`strip`/`dedup`/`allow_empty_items`), `optional_int` (`non_negative`), `optional_non_negative_float`, `optional_bool`, `required_number`. Each takes an injected `error=` class; callers bind flags+error via `functools.partial` so they keep their own exception type and unchanged call sites. |
| `src/job_hunt_evaluation.py` | `evaluate_reviewed_job(profile, job, scoring_policy, decision_policy)` → `JobAnalysis`. Composes `score_job()` + `decide_application()`. Sets `tailoring_ready` from decision (apply=True, review/manual-review=not yet). Sets `confidence` from scoring result. Injects blockers if provided externally. |
| `src/job_hunt_outcomes.py` | `create_outcome_record(job_id, ...)` → `ApplicationOutcome`. `update_outcome(outcome, status, notes)` → new outcome with history entry. `allowed_next_statuses(current)` → valid next statuses per `_ALLOWED_TRANSITIONS` (drives the job-page Status dropdown). `OutcomeValidationError` on bad status/transition. `outcome_to_dict` / `outcome_from_dict` for persistence. |
| `src/job_hunt_track_store.py` | JSON-file job-tracking store (`_LOCK`-guarded): `get_all`, `upsert`, `update_status`, `delete`, `get_by_status`, `_gen_id`, `_load_data`/`_save_data`. **2026-07-08:** first documented + first tests (`tests/test_track_store.py`); `delete()` persistence bug fixed (`data["jobs"]` was never updated before save). |
| `src/job_hunt_reporting.py` | `build_report_rows(jobs, analyses, outcomes)` → flat list of row dicts per job. `summarize_decisions(analyses)` → count of apply/review/skip. `export_report_json(rows, output_path)` / `export_report_csv(rows, output_path)`. CSV includes: job_id, job_title, company, match_score, confidence, decision, blockers, strengths, missing_skills. |
| `src/job_hunt_orchestrator.py` | `run_evaluation(profile_path, reviewed_job_path, ...)` → full pipeline result. Loads profile + reviewed job → evaluates → saves reviewed job, analysis, optional raw input → generates reports. Also `submit_reviewed_job(profile_path, job_payload)` for UI: accepts unvalidated dict, converts to reviewed job, evaluates, stores, returns analysis. |
| `src/job_hunt_main.py` | CLI entrypoint using `argparse`. `--profile` (required), `--reviewed-job` (required), `--state-root` (default `data/state`), `--report-dir` (default `output/reports`), `--raw-input`, `--raw-input-id`. Prints summary on success (job title, company, decision, score, confidence, paths). Exits non-zero on validation/evaluation errors. |
| `src/job_hunt_ui.py` | **Thin 19-line entry point after the LT-1 split.** Run `python3 -m src.job_hunt_ui --profile …`. It imports `main` from `ui_routes`; the implementation lives in `ui_routes` / `ui_handlers` / `ui_render` / `ui_utils` / `ui_state` below. |
| `src/ui_routes.py` | **NEW (LT-1).** HTTP server + dispatch. `UIRequest` (parsed method/path/query/form/json_body/raw_body/headers), `UIResponder` (`send_html`/`send_json`/`redirect`), `_parse_request`, `_build_handler` (slim `do_GET`/`do_POST` → standalone handlers), `main`, `build_parser`. Imports each `job_sources/*_source` for registration side effect. |
| `src/ui_handlers.py` | **NEW (LT-1).** All request handlers as standalone `handle_*(req, config, responder)` / `render_*` functions (testable without a live server). View-model builders `_build_job_page_vm` / `_build_profile_page_vm`, `_render_search_jobs_tab` (source orchestration), `_allowed_profile_dir`, `load_recent_job_history`, `raw_input_payload_from_form`, `parse_multipart_form`, `_index_db_path`, `handle_sources`. Only layer that imports domain modules. |
| `src/ui_render.py` | **NEW (LT-1).** All HTML rendering — **pure: data in, string out, no domain imports**. View-models `JobPageViewModel`, `ProfilePageViewModel`, `ReviewQueueViewModel`. `render_page` (reads `config.model_label`), `render_home_page`, `render_job_page`, `render_profile_page`, `render_review_queue_page`, `render_history_table`, `render_input_form`, `_render_sidebar`, `_render_add_job_*`, `_normalize_home_tab`. |
| `src/ui_utils.py` | **NEW (LT-1).** Pure helpers: `escape`, `format_salary_range`, `squash_whitespace`, `normalize_optional_int_text`, form extractors (`required_text`/`optional_text`/`optional_float`/`optional_int`), `default_form_values`, `split_lines_or_commas`, `reviewed_job_payload_from_form`, `job_id_from_request_path`, `render_select_options`, `create_select_nonce`/`consume_select_nonce`. Imports only stdlib + `ui_state`. |
| `src/ui_state.py` | **NEW (LT-1).** Constants + `UIServerConfig` (`profile_path`, `state_root`, `report_dir`, `host`, `port`, `model_label`). `_PAGE_UPDATED`, `_HOME_TABS`, `_SELECT_*`, CV-upload limits (`_MAX_CV_SIZE_BYTES`, allowlists). Leaf module (no `ui_*` imports). |
| `src/job_sources/_multiselect.py` | Shared result-grid chrome/JS for all sources (Reed/Adzuna/LinkedIn import it): `MULTISELECT_JS`, `STAGING_OVERLAY` (also carries the hidden-jobs overlay + undo toast), `ACTION_BAR`, `multiselect_script()`, `more_button_html()` (full footer: page indicator, "Hide unticked on this page", "Hidden jobs (N)", Next page), `hide_attrs(result)`. Triage model (2026-07): cards start unticked (tick = shortlist for evaluate only); per-card ✕ + bulk hide persist via `/jobs/not-interested` with 10s undo; `jstLoadMore` replaces the list ("Next page", forward-only) and captures ticked cards' form fields so cross-page batch evaluation works. |
| `src/job_sources/reed_source.py` | **NEW (MT-1).** Self-contained Reed source: search-form + results + cards + select-form rendering, `normalize_reed_search_params`, `search_reed_jobs_for_ui`, `reed_select_form_to_evaluate_values(form, config)`, snapshot/salary helpers, `_is_reed_available`, and `_register()` (fires on import). Imports only `ui_utils`/`ui_state` from the UI side (no `job_hunt_ui` dependency). |
| `src/job_sources/adzuna_source.py` | **NEW (P5-1).** Self-contained Adzuna source mirroring `reed_source`: `_render_adzuna_search_form`, `search_adzuna_jobs_for_ui`, `adzuna_job_to_ui_result`, `normalize_adzuna_search_params`, `adzuna_select_form_to_evaluate_values(form, config)`, `render_adzuna_search_results`, `_is_adzuna_available`, `_register()`. No source_snapshot / no detail-fetch (Adzuna has no per-job detail endpoint; snapshot is reed-only). |
| `src/job_sources/linkedin_source.py` | **NEW (P5-2).** LinkedIn public-search scraper (no API key). `LinkedInBlockedError`; `is_available` (always True); SQLite cache (5-min TTL, SHA-256 key, `set_cache_db_path`); `normalize_search_params`; `_is_blocked` (HTTP 999/429/403/401, login-redirect URL, page < 5000 chars); `_parse_search_html` (BeautifulSoup `.base-card`, job-id dedup, `description_preview`); `_fetch_search` (lazy `requests`); `search_handler` (cache-first); `_fetch_description` (lazy full desc); `select_handler` (form validation, skill extraction, returns `default_form_values`); `_linkedin_job_id`; `render_search_form`; `_render_select_form`, `_render_cards`, `render_results` (mirrors Adzuna `.jst-rc` pattern); `_register()`. Salary always empty (not available on public search). |

---

## Tests (`tests/`)

| File | Tests |
|------|-------|
| `tests/test_models.py` | Model construction, validation guardrails (empty required fields, salary range, score bounds). |
| `tests/test_scoring.py` | Component scoring, confidence derivation, risk flag generation. |
| `tests/test_decision.py` | Blocker skip, apply threshold, review threshold, critical risk gating. |
| `tests/test_profile.py` | Valid/invalid profile loading, failure cases, round-trip, CV file handling. |
| `tests/test_reviewed_input.py` | Reviewed-input normalization, unknown handling, round-trip conversion. |
| `tests/test_storage.py` | Storage layout, round-trips, state separation, invalid payload handling. |
| `tests/test_evaluation.py` | Apply/review/skip evaluation flow, confidence-vs-score behavior. |
| `tests/test_outcomes.py` | Outcome creation, updates, validation, persistence, layout. |
| `tests/test_reporting.py` | Row building, summary counts, JSON/CSV export. |
| `tests/test_orchestrator.py` | Orchestration flow, reviewed job submission. |
| `tests/test_main.py` | CLI argument handling, exit codes, output. |
| `tests/test_integration_flow.py` | End-to-end integration: profile → reviewed job → evaluation → storage → reporting → outcomes. |
| `tests/test_ui.py` | UI request handling: GET `/`, Reed search/no-results/error/select/evaluate flow, POST `/evaluate`, validation failures, GET `/job`, POST `/outcome`, profile page, CV parsing. |
| `tests/test_linkedin_source.py` | **NEW (P5-2).** 16 tests: 25-card parse, login-wall/short-page/HTTP-429/HTTP-403/timeout blocked variants, empty results, XSS title escaping, duplicate job-id dedup, `normalize_search_params` defaults/clamping/invalid-work-mode, cache-hit skips HTTP, `render_results` edge cases. |
| `tests/test_track_store.py` | **NEW (coverage audit 2026-07-08).** 22 tests: `job_hunt_track_store` full round-trip (upsert/get_all/update_status/delete/get_by_status/_gen_id), corrupt-JSON + missing-file `_load_data`, atomic `_save_data`. Exposed + now guards the `delete()` persistence bug. |
| `tests/test_llm_queue_worker.py` | **NEW (2026-07-08).** 14 tests: `LLMQueueWorker` lifecycle (init/start/stop), `_has_key` env variants, `_loop` drain/exception/stop paths — real `_loop` body executed with `drain_llm_batch` mocked. |
| `tests/test_shared_bus_getters.py` | **NEW (2026-07-08).** 13 tests: `shared_bus` `get_pipeline_runs` / `get_active_pipelines` / `get_agent_executions` on empty + populated temp SQLite DBs, ordering + limit. |
| `tests/test_misc_uncovered.py` | **NEW (2026-07-08).** 34 tests: `_parse_json_from_text` (fences/prose/invalid), tailoring `_extract_bullet_lines`/`_extract_plain_lines`, `apply_url_from_ui_result`, `_is_fetch_allowed`. |
| `tests/test_reed_adzuna_clients.py` | **NEW (2026-07-08).** 24 tests: `fetch_reed_jobs` / `fetch_adzuna_jobs` with `requests.get` mocked (success/empty/429/HTTP error/malformed JSON/no creds — asserts no HTTP call without creds), `save_raw_response`, env loading. |
| `tests/test_source_forms.py` | **NEW (2026-07-08).** 59 tests: reed/adzuna/linkedin form rendering + XSS escaping, availability checks, `adzuna_selected_job_id`, `_validate_adzuna_salary_text`, `adzuna_select_form_to_evaluate_values` (10 variants). |
| `tests/test_ui_handlers_uncovered.py` | **NEW (2026-07-08).** 28 tests: 9 previously-untested handlers — `handle_job_explain`, `handle_prefill`, `handle_job_submit`, `handle_add_gap_skills`, `handle_ai_review_cv`, `handle_get_board_view`, `handle_search_reed_more`, `handle_get_review_queue`, `set_daemons` — LLM/parse boundaries mocked. |
| `tests/test_ui_render_uncovered.py` | **NEW (2026-07-08).** 26 tests: `render_review_queue_page` incl. nested `_chip`/`_score_color` bands, `render_simple_list`, `render_detail_item`, HTML escaping. |
| `tests/test_ui_routes_uncovered.py` | **NEW (2026-07-08).** 17 tests: `build_parser` defaults/flags/validation. `main` intentionally untested (HTTPServer/daemon coupling). |
| `tests/test_llm_wrappers_uncovered.py` | **NEW (2026-07-08).** 20 tests: `ai_review_cv_with_llm`, `extract_cv_skills_with_llm`, `extract_skills_from_cv` fallback, `generate_cover_letter_text` — Gemini transport patched, valid + malformed LLM responses. |

---

## Sample Inputs (`input/`)

| File | Purpose |
|------|---------|
| `input/reviewed_job_demo.json` | Standard demo reviewed job. |
| `input/reviewed_job_gap.json` | Required-skill gap → review decision. |
| `input/reviewed_job_salary_miss.json` | Salary below floor → review decision. |
| `input/reviewed_job_sparse.json` | Missing/unknown fields → low confidence. |
| `input/reviewed_job_invalid.json` | Invalid payload → clean failure. |

---

## Other

| File | Purpose |
|------|---------|
| `poc/public_web_extraction/README.md` | Broad public web extraction POC using Browse CLI with read-only guardrails, candidate URL mode, preflight, structured schema, quality scoring, v2 research summaries, markdown exports, screenshots/snapshots, and report output. |
| `docs/tasks/public-web-extraction-poc-v2-quality-design.md` | v2 quality design for useful-link extraction, text cleanup, category profiles, markdown exports, and `extraction_report_v2.md`. |
| `poc/browser_enrichment/README.md` | Earlier job-page-only browser enrichment POC; kept separate from the broader public web extraction study. |
| `viewer/app.js` | Docs viewer JS — section extraction, markdown rendering, dashboard card summaries. |
| `viewer/documents.json` | Manifest of docs shown in the viewer. Update here to add docs to the viewer. |
| `viewer/viewer.sh` | Start/stop/status/restart script for the docs HTTP server. |

---

## Feature Map

> Cross-reference: feature → design spec → key functions → routes → UI page.
> Used by the update-project-docs skill to locate the right `docs/tasks/` spec when a function is modified.
> Keep this table current whenever a feature is built or a spec is added.

| Feature | Design spec (`docs/tasks/`) | Key functions | Routes | UI page |
|---|---|---|---|---|
| Search-first landing shell | `pl-01-reed-search-first-shell-design.md` | `_render_home`, `_render_search_jobs_tab`, `_render_shared_search_form` (one shared criteria form + per-source `formaction` buttons) | `GET /` | Find Jobs tab |
| Reed search form + results | `pl-02-reed-search-form-api-wiring-design.md` | `fetch_reed_jobs`, `search_reed_jobs_for_ui`, `normalize_reed_search_params`, `render_reed_search_results`, `_handle_source_search` | `GET /search/reed` | Find Jobs tab |
| Source pagination ("Next page" replaces list — all sources) | — | `handle_source_search_more`, `_take_skip_param_keys` (`ui_handlers`); `JobSource.render_cards_fragment`; `_render_reed_cards_fragment` / `_render_adzuna_cards_fragment` / `_render_cards`; `_multiselect.py` (`MULTISELECT_JS`, `more_button_html` footer, `jstLoadMore` replace-mode, cross-page shortlist field capture) | `GET /search/{source}/more` (Reed, Adzuna, LinkedIn) | Find Jobs tab |
| Search triage — not-interested hide/unhide ✅ | `search-triage-not-interested-design.md` | `job_hunt_not_interested.py`: `hide_jobs`, `unhide_jobs`, `list_hidden`, `count_hidden`, `filter_results`, `make_key`, `make_fingerprint`; `ui_handlers`: `handle_jobs_hide`, `handle_jobs_unhide`, `handle_jobs_hidden_list`, filter calls in `handle_source_search` / `handle_source_search_more`, hidden-note in `_render_search_jobs_tab`; `_multiselect.py` JS: `jstHide`, `jstUndoHide`, `jstHideUnticked`, `jstShowHidden`, `hide_attrs` | `POST /jobs/not-interested`, `POST /jobs/not-interested/undo`, `GET /jobs/not-interested` | Find Jobs tab (cards ✕, footer, Hidden jobs overlay, undo toast) |
| UI layer split (LT-1) | `docs/tasks/lt-01-ui-layer-split-design.md` | all functions in `job_hunt_ui.py` → `ui_state`, `ui_utils`, `ui_render`, `ui_handlers`, `ui_routes` | all routes | all pages |
| Reed select → prefill | `pl-03-reed-select-prefill-evaluate-design.md` | `reed_select_form_to_evaluate_values`, `render_reed_select_form` | `POST /select/reed` | Add Job tab |
| Raw response audit storage | `pl-04-reed-raw-response-audit-storage-design.md` | `save_raw_response`, `reed_job_to_ui_result` | — | — |
| Search polish + multi-select | `pl-05-reed-search-polish-regression-hardening-design.md` | `render_reed_search_results` (JS: `jstToggle`, `jstEvaluateAll`, staging overlay) | — | Find Jobs tab |
| Review Queue + batch evaluate | `pl-05-reed-search-polish-regression-hardening-design.md` | `render_review_queue_page`, `_handle_get_review_queue`, `_handle_batch_evaluate` | `GET /review-queue`, `POST /jobs/batch-evaluate` | Review Queue (standalone) |
| Job detail embed mode | `pl-05-reed-search-polish-regression-hardening-design.md` | `render_job_page(embed=True)`, `_render_job` | `GET /job/{id}?embed=1` | Review Queue iframe |
| Skill dataclass (GAP-B) | `gap-b-skill-dataclass-design.md` | `Skill` dataclass in `job_hunt_models.py`, backward-compat loader in `load_candidate_profile` | — | My Profile tab |
| Source feature flag (GAP-C/I) | `gap-c-source-feature-flag-design.md` | `source_registry.register`, `get_source`, `all_sources`, `get_enabled_sources` | `GET /sources` | Find Jobs tab |
| Adzuna source wiring (P5-1) | `gap-c-source-feature-flag-design.md` | `adzuna_source.py`: `search_adzuna_jobs_for_ui`, `normalize_adzuna_search_params`, `adzuna_select_form_to_evaluate_values`, `render_adzuna_search_results`; `adzuna_client.fetch_adzuna_jobs`; `normalize_adzuna` | `GET /search/adzuna`, `POST /select/adzuna` | Find Jobs tab |
| Generic batch evaluate (source dispatch) | — | `handle_batch_evaluate` dispatches `select_handler` by card `source` via `get_source` | `POST /jobs/batch-evaluate` | Review Queue |
| Field provenance / null contract (GAP-D) | `gap-d-field-provenance-design.md` | `parse_job_from_text`, `parse_job_from_url` — null = not-found | `POST /prefill` | Add Job tab |
| Decision override (GAP-E) | `gap-e-decision-override-design.md` | `effective_decision`, `_handle_job_decision` | `POST /job/{id}/decision` | Evaluate tab |
| Board aggregate (GAP-H) | `gap-h-board-aggregate-design.md` | `job_hunt_index.py`: `load_board`, `_handle_get_board`, `_handle_get_board_view`; `ui_handlers`: `handle_get_jobs`, `handle_jobs_save` | `GET /jobs`, `GET /board`, `GET /board/view`, `POST /jobs/save` | Tracker tab |
| CV tailoring (GAP-F) | `cv-tailoring-brief.md` | `tailor_cv`, `TailoredCVResult`, `validate_tailored_cv`, `save_tailored_cv` | `POST /tailor` | Tailor CV workspace |
| Cover letter (GAP-G) | `cover-letter-spec-draft.md` | `generate_cover_letter_text`, `save_cover_letter` | `POST /cover-letter` | Cover Letter workspace |
| ATS score | `ats-score-deferred.md` | `ats_score` on `JobAnalysis`, called from `evaluate_reviewed_job` | — | Evaluate tab |
| ATS keyword match (F1) | `f1-ats-match-rate-design.md` | `compute_keyword_match`, `_keyword_match_vm_fields`, `render_keyword_match_panel` | — | Job detail page |
| ATS keyword re-check (F1 v2) | `F1_v2_recheck_design.md` | `load_latest_tailored_cv`, `handle_ats_recheck`, `render_keyword_match_panel` | `POST /job/{id}/ats-recheck` | Job detail page |
| URL ingestion | `url-ingestion-design.md`, `job-007-url-ingestion-design-creation-brief.md` | `parse_job_from_url`, `parse_job_from_text` | `POST /prefill` | Add Job tab |
| Source quality gating | `source-quality-gating-design.md` | `source_quality` on `NormalizedJob`; thresholds in `job_hunt_config.py` | — | Find Jobs / Evaluate |
| Gap Coach (GAP-J) | `gap-j-gap-coach-design.md` | *(not yet implemented)* `aggregate_gaps`, `top_strengths`, `GET /coach` | `GET /coach` | Gap Coach tab |
| Saved Searches (Digest D1) ✅ | `backlog-01-daily-digest-design.md` | `job_hunt_saved_searches.py`: `SavedSearch`, `create/load/list/save/delete/toggle_saved_search`, `update_last_run`, `validate_search_id`, `validate_saved_search_fields` (shared name/source_id/params validator used by both create + save; `_validate_source_id` charset allowlist `^[a-z0-9_-]+$`); `ui_handlers`: `handle_saved_searches_list/_create/_delete/_toggle`; `render_profile_page` (Saved Searches section) | `GET/POST /saved-searches`, `POST /saved-searches/{id}/delete`, `POST /saved-searches/{id}/toggle` | My Profile tab |
| Digest schema + query layer (D2) ✅ | `backlog-01-daily-digest-design.md` | `job_hunt_index.py`: `_migrate_schema`, `upsert_job` (ON CONFLICT, fail-loud), `is_already_indexed`, `set_digest_meta`, `claim_batch`, `set_llm_status`, `reset_stale_llm_processing`, RPD counters; `job_hunt_digest.py`: `query_digest`, `mark_seen`, `unseen_count`, `digest_stats`; `ui_utils.digest_job_id`; `JobPosting.source_job_id` | `GET /digest/count` | (badge; Digest page is D4) |
| Digest pipeline (D3) ✅ | `backlog-01-daily-digest-design.md` | `job_hunt_scheduler.py`: `run_digest_pipeline`, `DigestRunResult`; `ui_utils.reviewed_job_payload_from_ui_result`; `CandidateProfile.digest_*` + `parse_bool`/`_int_in`/`_parse_hhmm`; `ui_handlers`: `handle_run_now`, `handle_scheduler_status` | `POST /saved-searches/{id}/run-now`, `GET /scheduler/status` | My Profile (settings + Run now) |
| Digest feed UI (D4) ✅ | `backlog-01-daily-digest-design.md` | `ui_render.render_digest_page`; `job_hunt_digest`: extended `query_digest` filters, `DigestEntry.llm_status`, `mark_all_seen` (scoped); `ui_handlers`: `handle_digest`, `handle_digest_mark_seen`, `_parse_digest_filters` | `GET /digest`, `POST /digest/mark-seen` | Digest (standalone page) + sidebar badge |
| Digest scheduler (D5) ✅ | `backlog-01-daily-digest-design.md` | `job_hunt_scheduler.DigestScheduler` (poll loop, once-per-day, `_PIPELINE_LOCK`); auto-start in `ui_routes.main`; `ui_handlers.handle_scheduler_status`/`set_daemons` | `GET /scheduler/status` | (background; status JSON) |
| Paced LLM worker (D6) ✅ | `backlog-01-daily-digest-design.md` | `job_hunt_scheduler`: `drain_llm_batch`, `LLMQueueWorker`, `save_analysis_llm_fields`, `rpd_date_key`, `llm_queue_stats`; `job_hunt_llm.RateLimited` + `explain_job_match_with_llm(raise_on_rate_limit=)`; `JobAnalysis.llm_*` | `POST /digest/run-llm-batch`, `GET /digest/llm-queue` | Digest page (per-job AI badge) |
| Re-evaluate seen jobs (OQ-2) ✅ | `oq-2-reevaluate-seen-design.md` | `job_hunt_index.py`: `list_digest_jobs_for_reeval`, `resurface_digest_job`, `requeue_llm_if_eligible` (CAS), `clear_llm_queue` (CAS); `job_hunt_scheduler.py`: `reevaluate_digest_jobs`, `ReevalResult`, `row_status`; `ui_handlers.handle_digest_reevaluate`; `ui_render.render_digest_page` ("Re-evaluate all" button) | `POST /digest/reevaluate` | Digest page (Re-evaluate all) |
| LinkedIn source (P5-2) ✅ | — | `linkedin_source.py`: `is_available`, `normalize_search_params`, `search_handler`, `select_handler`, `_fetch_search`, `_fetch_description`, `_is_blocked`, `_parse_search_html`, `_linkedin_job_id`, `render_search_form`, `render_results`, SQLite cache helpers; `LinkedInBlockedError` | `GET /search/linkedin`, `POST /select/linkedin` | Find Jobs tab |
| Bookmark → Evaluate bridge ✅ | `bookmark-evaluate-bridge-design.md` | `form_values_from_reviewed_job` (`ui_utils`), `handle_evaluate_form` (`ui_handlers`); job-page CTA + Re-evaluate link (`render_job_page`) | `GET /job/<id>/evaluate-form` | Job detail page → Evaluate tab |
| Outcomes / tracker transitions | — | `create_outcome_record`, `update_outcome`, `allowed_next_statuses`, `_ALLOWED_TRANSITIONS`, `handle_outcome` | `POST /outcome` | Tracker tab + job page Outcome card |
| Profile load/save/CV parse | — | `load_candidate_profile`, `save_candidate_profile`, `parse_cv_file` | `GET /profile`, `POST /profile/save`, `POST /profile/parse-cv` | My Profile tab |
| Job detail page | — | `render_job` (`ui_handlers`), `render_job_page` (`ui_render`) | `GET /job/{id}` | Job detail page |
| Manual evaluate + save (Add Job flow) | — | `handle_evaluate`, `handle_job_submit` | `POST /evaluate`, `POST /job-submit` | Add Job → Evaluate tab |
| LLM explain match | — | `handle_job_explain`, `explain_job_match_with_llm` | `GET /job/{id}/explain` | Job detail page (AJAX JSON) |
| Add gap skills to profile | — | `handle_add_gap_skills` | `POST /job/{id}/add-gap-skills` | Job detail page |
| AI review CV (Gemini light rewrite) | — | `handle_ai_review_cv`, `ai_review_cv_with_llm` | `POST /job/{id}/ai-review-cv` | Job detail page |

---

## What to Read for Common Tasks

- **Understand the product** → `PROJECT_CONTEXT.md`
- **Check progress/history** → `PROJECT_LOG.md`
- **Run the CLI** → `README.md` + `src/job_hunt_main.py --help`
- **Run the UI** → `README.md` + **`python3 -m src.job_hunt_ui --profile data/mic_profile/candidate_profile.json`**
- **Understand scoring** → `src/job_hunt_scoring.py` + `src/job_hunt_config.py` (start with `score_job()` and `ScoringWeights`)
- **Understand decisioning** → `src/job_hunt_decision.py` + `src/job_hunt_config.py` (start with `decide_application()` and `DecisionPolicy`)
- **Change data shapes** → `src/job_hunt_models.py` + `docs/data_contract.md`
- **Change policy thresholds** → `src/job_hunt_config.py` only — all weights, thresholds, critical risks are there
- **Add a new module** → `docs/function_list.md` + `docs/architecture_guardrails.md`
- **Understand the evaluation flow** → `src/job_hunt_evaluation.py` (wires scoring + decision)
- **Understand the CLI orchestration** → `src/job_hunt_orchestrator.py` + `src/job_hunt_main.py`
- **Understand the UI** → `src/ui_routes.py`, then `src/ui_handlers.py`, `src/ui_render.py`, `src/ui_utils.py`, and `src/ui_state.py`
- **Write tests** → any `tests/test_*.py` for the pattern
- **Browse docs visually** → `http://127.0.0.1:8765/viewer/` (project doc viewer served by `viewer_server.py` on port 8765)

## Data Flow (one job run)

```
Profile JSON          Reviewed Job JSON
      │                       │
      ▼                       ▼
profile.py         reviewed_input.py
(CandidateProfile)  (JobPosting)
      │                       │
      └───────────┬───────────┘
                  ▼
           evaluation.py
           ┌─────┴─────┐
           ▼           ▼
      scoring.py  decision.py
      (ScoringResult) (DecisionResult)
           │           │
           └─────┬─────┘
                 ▼
            JobAnalysis
             (model)
                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
   storage.py reporting.py outcomes.py
 (saved JSON) (JSON/CSV) (outcome record)
```

## Key Invariants

- Raw input, reviewed job, and analysis are stored **separately** — none overwrites the other
- `match_score` and `confidence` are **independent** — score is fit, confidence is data completeness
- Blockers always produce `skip` — no score threshold can override a blocker
- Tailoring is only set `tailoring_ready=True` on `apply` decisions — review jobs must be manually shortlisted
- Unknown fields in scoring get **neutral credit** (don't penalise score) but **reduce confidence**
