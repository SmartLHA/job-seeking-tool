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
| `docs/product_spec.md` | What the product is, MVP scope, goals/non-goals, user stories. |
| `docs/function_list.md` | All planned modules and their responsibilities. |
| `docs/development_sequence.md` | Phased build order (Phase 0–8). |
| `docs/development_rules.md` | Non-negotiable build rules: local-first, truthful output, deterministic-first, tests. |
| `docs/data_contract.md` | MVP data shapes — JobPosting, JobAnalysis, blockers, score breakdown. |
| `docs/ui_scope.md` | UI screen definitions v3 (6 screens + 2 workspaces), workflow boundaries, new HTTP routes required. |
| `docs/build_order.md` | **Build priority order** — 4 phases, 10 items, dependency map, effort ratings, related files per item. |
| `docs/architecture_guardrails.md` | Pre-implementation architecture discipline: state separation, module boundaries, policy config principles. |
| `docs/team_protocol.yaml` | Multi-agent team protocol: SilverHand/Handy/Scout roles, anti-idle rule, QA modes. |
| `Claude deliverable/docs/ui_structure_v4.md` | **Authoritative** screen → backend binding; each screen mapped to real routes/functions; GAP catalogue. |
| `Claude deliverable/docs/function_list_v4.md` | Real function signatures (read from source) with gap annotations; HTTP route table; openclaw priority list. |
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

---

## Source Code (`src/`)

| File | Purpose |
|------|---------|
| `src/job_hunt_models.py` | All dataclass models: `CandidateProfile`, `JobPosting`, `Blocker`, `RiskFlag`, `ScoreComponent`, `ScoreBreakdown`, `JobAnalysis`, `OutcomeEvent`, `ApplicationOutcome`. Validation in each model's `__post_init__`. `Decision = Literal["apply","review","skip"]`. `ConfidenceLevel = Literal["low","medium","high"]`. `OutcomeStatus = Literal["not_applied","applied","interview","rejected","offer","withdrawn"]`. |
| `src/job_hunt_config.py` | All tunable policy objects: `ScoringWeights` (skills_required=35, preferred=5, experience=20, location/salary/domain/work_mode=10 each), `ConfidencePolicy`, `ScoringPolicy`, `DecisionPolicy`. Apply threshold ≥80; review threshold ≥65; blockers always skip; `missing-required-skills` and `salary-below-floor` are critical risks gating apply. |
| `src/job_hunt_scoring.py` | `score_job(profile, job, policy)` → `ScoringResult`. 7-component weighted scoring: required skills (35pt), preferred skills (5pt), experience (20pt), location (10pt), salary (10pt), domain (10pt), work mode (10pt). Confidence (high/medium/low) derived independently from data completeness — NOT from score. Unknown fields get neutral credit but reduce confidence. Risk flags (`missing-required-skills`, `missing-preferred-skills`, `salary-below-floor`) built here. |
| `src/job_hunt_decision.py` | `decide_application(score, blockers, risk_flags, policy)` → `DecisionResult`. Priority: blockers → skip; score ≥80 + no critical risks → apply; score 65-79 → review; critical risks present → review (even with high score); else → skip. |
| `src/job_hunt_profile.py` | `load_candidate_profile(path)` / `save_candidate_profile(profile, path)`. `load_master_cv(path)` / `save_master_cv(content, path)`. `resolve_master_cv_path(profile, profile_path)` for relative-path resolution. `ProfileValidationError` on bad input. Unknown extra fields rejected. Master CV existence checked on load if `master_cv_ref` set. |
| `src/job_hunt_reviewed_input.py` | `reviewed_job_from_dict(payload, job_id)` → `JobPosting`. Converts pre-reviewed job JSON into typed model. Unknown extra fields rejected. Skill lists deduplicated case-insensitively. `ReviewedInputValidationError` on bad input. `reviewed_job_to_dict(job)` for round-trip. |
| `src/job_hunt_storage.py` | `ensure_storage_layout(root)` → `StorageLayout`. Four folders: `raw_inputs/`, `reviewed_jobs/`, `analyses/`, `outcomes/`. `save/load_reviewed_job`, `save/load_job_analysis`, `save/load_raw_input`, `save/load_application_outcome`. `job_analysis_to_dict/from_dict` for typed↔dict conversion. `StorageError` on bad storage data. |
| `src/job_hunt_keyword_match.py` | **NEW (F1).** `compute_keyword_match(cv_text, required, preferred) -> KeywordMatchResult` — per-job ATS keyword coverage: edge-aware whole-token matching (handles `C#`/`C++`/`.NET`/`Node.js`/`CI/CD`), required-wins dedupe, null contract (no CV/keywords → rate `None`), overuse (>4×) anti-stuffing flag. Hooked in `evaluate_reviewed_job`; advisory/display only. |
| `src/job_hunt_validation.py` | **NEW (MT-2).** Canonical field validators shared by `storage`/`reviewed_input`/`profile`: `required_string` (`message_style`), `optional_string` (`empty_as_none`), `optional_text_or_empty`, `string_list` (`strip`/`dedup`/`allow_empty_items`), `optional_int` (`non_negative`), `optional_non_negative_float`, `optional_bool`, `required_number`. Each takes an injected `error=` class; callers bind flags+error via `functools.partial` so they keep their own exception type and unchanged call sites. |
| `src/job_hunt_evaluation.py` | `evaluate_reviewed_job(profile, job, scoring_policy, decision_policy)` → `JobAnalysis`. Composes `score_job()` + `decide_application()`. Sets `tailoring_ready` from decision (apply=True, review/manual-review=not yet). Sets `confidence` from scoring result. Injects blockers if provided externally. |
| `src/job_hunt_outcomes.py` | `create_outcome(job_id, status, notes)` → `ApplicationOutcome`. `update_outcome(outcome, status, notes)` → new outcome with history entry. `OutcomeValidationError` if status not in `OutcomeStatus`. Transition validation ensures current status matches latest history event. `outcome_to_dict` / `outcome_from_dict` for persistence. |
| `src/job_hunt_reporting.py` | `build_report_rows(jobs, analyses, outcomes)` → flat list of row dicts per job. `summarize_decisions(analyses)` → count of apply/review/skip. `export_report_json(rows, output_path)` / `export_report_csv(rows, output_path)`. CSV includes: job_id, job_title, company, match_score, confidence, decision, blockers, strengths, missing_skills. |
| `src/job_hunt_orchestrator.py` | `run_evaluation(profile_path, reviewed_job_path, ...)` → full pipeline result. Loads profile + reviewed job → evaluates → saves reviewed job, analysis, optional raw input → generates reports. Also `submit_reviewed_job(profile_path, job_payload)` for UI: accepts unvalidated dict, converts to reviewed job, evaluates, stores, returns analysis. |
| `src/job_hunt_main.py` | CLI entrypoint using `argparse`. `--profile` (required), `--reviewed-job` (required), `--state-root` (default `data/state`), `--report-dir` (default `output/reports`), `--raw-input`, `--raw-input-id`. Prints summary on success (job title, company, decision, score, confidence, paths). Exits non-zero on validation/evaluation errors. |
| `src/job_hunt_ui.py` | **Thin shell (19 lines) after the LT-1 split.** **Run: `python3 -m src.job_hunt_ui --profile …`**. Re-exports back-compat symbols (`main`, `_build_handler`, `UIServerConfig`, form helpers) and is the entry point. Real implementation lives in `ui_routes` / `ui_handlers` / `ui_render` / `ui_utils` / `ui_state` below. Endpoints (unchanged): `GET /`, `GET /search/reed`, `GET /search/reed/more`, `POST /select/reed`, `POST /evaluate`, `POST /job-submit`, `GET /job/<id>` (+ `/explain`, `/decision`, `/add-gap-skills`, `/ai-review-cv`), `POST /outcome`, `POST /jobs/batch-evaluate`, `POST /jobs/save`, `GET /jobs`, `GET /board`, `GET /board/view`, `GET /review-queue`, `GET /sources`, `GET /profile`, `POST /profile/parse-cv`, `POST /profile/save`, `POST /tailor`, `POST /cover-letter`, `POST /prefill`. |
| `src/ui_routes.py` | **NEW (LT-1).** HTTP server + dispatch. `UIRequest` (parsed method/path/query/form/json_body/raw_body/headers), `UIResponder` (`send_html`/`send_json`/`redirect`), `_parse_request`, `_build_handler` (slim `do_GET`/`do_POST` → standalone handlers), `main`, `build_parser`. Imports each `job_sources/*_source` for registration side effect. |
| `src/ui_handlers.py` | **NEW (LT-1).** All request handlers as standalone `handle_*(req, config, responder)` / `render_*` functions (testable without a live server). View-model builders `_build_job_page_vm` / `_build_profile_page_vm`, `_render_search_jobs_tab` (source orchestration), `_allowed_profile_dir`, `load_recent_job_history`, `raw_input_payload_from_form`, `parse_multipart_form`, `_index_db_path`, `handle_sources`. Only layer that imports domain modules. |
| `src/ui_render.py` | **NEW (LT-1).** All HTML rendering — **pure: data in, string out, no domain imports**. View-models `JobPageViewModel`, `ProfilePageViewModel`, `ReviewQueueViewModel`. `render_page` (reads `config.model_label`), `render_home_page`, `render_job_page`, `render_profile_page`, `render_review_queue_page`, `render_history_table`, `render_input_form`, `_render_sidebar`, `_render_add_job_*`, `_normalize_home_tab`. |
| `src/ui_utils.py` | **NEW (LT-1).** Pure helpers: `escape`, `format_salary_range`, `squash_whitespace`, `normalize_optional_int_text`, form extractors (`required_text`/`optional_text`/`optional_float`/`optional_int`), `default_form_values`, `split_lines_or_commas`, `reviewed_job_payload_from_form`, `job_id_from_request_path`, `render_select_options`, `create_select_nonce`/`consume_select_nonce`. Imports only stdlib + `ui_state`. |
| `src/ui_state.py` | **NEW (LT-1).** Constants + `UIServerConfig` (`profile_path`, `state_root`, `report_dir`, `host`, `port`, `model_label`). `_PAGE_UPDATED`, `_HOME_TABS`, `_SELECT_*`, CV-upload limits (`_MAX_CV_SIZE_BYTES`, allowlists). Leaf module (no `ui_*` imports). |
| `src/job_sources/reed_source.py` | **NEW (MT-1).** Self-contained Reed source: search-form + results + cards + select-form rendering, `normalize_reed_search_params`, `search_reed_jobs_for_ui`, `reed_select_form_to_evaluate_values(form, config)`, snapshot/salary helpers, `_is_reed_available`, and `_register()` (fires on import). Imports only `ui_utils`/`ui_state` from the UI side (no `job_hunt_ui` dependency). |

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
| Search-first landing shell | `pl-01-reed-search-first-shell-design.md` | `_render_home`, `_render_search_jobs_tab` | `GET /` | Find Jobs tab |
| Reed search form + results | `pl-02-reed-search-form-api-wiring-design.md` | `fetch_reed_jobs`, `search_reed_jobs_for_ui`, `normalize_reed_search_params`, `render_reed_search_results`, `_handle_source_search` | `GET /search/reed` | Find Jobs tab |
| Reed pagination (more jobs) | — | `_handle_search_reed_more`, `_render_reed_cards_fragment`, `jstLoadMore`, `jstRegisterCards` | `GET /search/reed/more` | Find Jobs tab |
| UI layer split (LT-1) | `docs/tasks/lt-01-ui-layer-split-design.md` | all functions in `job_hunt_ui.py` → `ui_state`, `ui_utils`, `ui_render`, `ui_handlers`, `ui_routes` | all routes | all pages |
| Reed select → prefill | `pl-03-reed-select-prefill-evaluate-design.md` | `reed_select_form_to_evaluate_values`, `render_reed_select_form` | `POST /select/reed` | Add Job tab |
| Raw response audit storage | `pl-04-reed-raw-response-audit-storage-design.md` | `save_raw_response`, `reed_job_to_ui_result` | — | — |
| Search polish + multi-select | `pl-05-reed-search-polish-regression-hardening-design.md` | `render_reed_search_results` (JS: `jstToggle`, `jstEvaluateAll`, staging overlay) | — | Find Jobs tab |
| Review Queue + batch evaluate | `pl-05-reed-search-polish-regression-hardening-design.md` | `render_review_queue_page`, `_handle_get_review_queue`, `_handle_batch_evaluate` | `GET /review-queue`, `POST /jobs/batch-evaluate` | Review Queue (standalone) |
| Job detail embed mode | `pl-05-reed-search-polish-regression-hardening-design.md` | `render_job_page(embed=True)`, `_render_job` | `GET /job/{id}?embed=1` | Review Queue iframe |
| Skill dataclass (GAP-B) | `gap-b-skill-dataclass-design.md` | `Skill` dataclass in `job_hunt_models.py`, backward-compat loader in `load_candidate_profile` | — | My Profile tab |
| Source feature flag (GAP-C/I) | `gap-c-source-feature-flag-design.md` | `source_registry.register`, `get_source`, `all_sources`, `get_enabled_sources` | `GET /sources` | Find Jobs tab |
| Field provenance / null contract (GAP-D) | `gap-d-field-provenance-design.md` | `parse_job_from_text`, `parse_job_from_url` — null = not-found | `POST /prefill` | Add Job tab |
| Decision override (GAP-E) | `gap-e-decision-override-design.md` | `effective_decision`, `_handle_job_decision` | `POST /job/{id}/decision` | Evaluate tab |
| Board aggregate (GAP-H) | `gap-h-board-aggregate-design.md` | `job_hunt_index.py`: `load_board`, `_handle_get_board`, `_handle_get_board_view` | `GET /board`, `GET /board/view` | Tracker tab |
| CV tailoring (GAP-F) | `cv-tailoring-brief.md` | `tailor_cv`, `TailoredCVResult`, `validate_tailored_cv`, `save_tailored_cv` | `POST /tailor` | Tailor CV workspace |
| Cover letter (GAP-G) | `cover-letter-spec-draft.md` | `generate_cover_letter_text`, `save_cover_letter` | `POST /cover-letter` | Cover Letter workspace |
| ATS score | `ats-score-deferred.md` | `ats_score` on `JobAnalysis`, called from `evaluate_reviewed_job` | — | Evaluate tab |
| URL ingestion | `url-ingestion-design.md`, `job-007-url-ingestion-design-creation-brief.md` | `parse_job_from_url`, `parse_job_from_text` | `POST /prefill` | Add Job tab |
| Source quality gating | `source-quality-gating-design.md` | `source_quality` on `NormalizedJob`; thresholds in `job_hunt_config.py` | — | Find Jobs / Evaluate |
| Gap Coach (GAP-J) | `gap-j-gap-coach-design.md` | *(not yet implemented)* `aggregate_gaps`, `top_strengths`, `GET /coach` | `GET /coach` | Gap Coach tab |
| Daily Digest (backlog) | `backlog-01-daily-digest-design.md` | `run_digest_pipeline`, `DigestScheduler`, `SavedSearch`, `query_digest`, `unseen_count` | `GET /digest`, `GET /digest/count`, `POST /digest/mark-seen`, `GET/POST/DELETE /saved-searches`, `POST /saved-searches/{id}/run-now`, `GET /scheduler/status` | Digest (new standalone page) |
| Outcomes / tracker transitions | — | `create_outcome`, `update_outcome`, `_ALLOWED_TRANSITIONS` | `POST /outcome` | Tracker tab |
| Profile load/save/CV parse | — | `load_candidate_profile`, `save_candidate_profile`, `parse_cv_file` | `GET /profile`, `POST /profile/save`, `POST /profile/parse-cv` | My Profile tab |

---

## What to Read for Common Tasks

- **Understand the product** → `PROJECT_CONTEXT.md`
- **Check progress/history** → `PROJECT_LOG.md`
- **Run the CLI** → `README.md` + `src/job_hunt_main.py --help`
- **Run the UI** → `README.md` + **`python3 src/job_hunt_ui.py`** (starts on port 8765; no `src/ui.py` entrypoint is retained)
- **Understand scoring** → `src/job_hunt_scoring.py` + `src/job_hunt_config.py` (start with `score_job()` and `ScoringWeights`)
- **Understand decisioning** → `src/job_hunt_decision.py` + `src/job_hunt_config.py` (start with `decide_application()` and `DecisionPolicy`)
- **Change data shapes** → `src/job_hunt_models.py` + `docs/data_contract.md`
- **Change policy thresholds** → `src/job_hunt_config.py` only — all weights, thresholds, critical risks are there
- **Add a new module** → `docs/function_list.md` + `docs/architecture_guardrails.md`
- **Understand the evaluation flow** → `src/job_hunt_evaluation.py` (wires scoring + decision)
- **Understand the CLI orchestration** → `src/job_hunt_orchestrator.py` + `src/job_hunt_main.py`
- **Understand the UI** → `src/job_hunt_ui.py` (endpoint routing + form handling + profile/CV upload tabs)
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
