## 2026-06-22

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
