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
