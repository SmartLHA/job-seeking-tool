# Job Seeking Tool — Project TODO
**Last updated:** 2026-06-19 (full code-review backlog cleared incl. LT-2; full system test PASS — 325 tests green + 13/13 live-endpoint smoke + entry-point/Reed-path verified; only env-only multi_llm_chat unlink failures remain) | **Owner:** Mic
**Build order:** See `docs/build_order.md` for dependency map and rationale.
**Rule:** Complete each phase fully (tests green) before starting the next.

---

## ✅ Pre-Build Decision — GAP-A (Tracker Status Columns)

**Status:** ✅ Resolved 2026-06-16 — Option A (remap UI to real backend enum)

Tracker columns remapped to the 6 real `OutcomeStatus` values. No backend enum changes needed.
DnD constrained to legal transitions per `_ALLOWED_TRANSITIONS`. Unblocks GAP-H (P3-1).

**UI deliverables** (implement alongside P3-1 GAP-H):
- Rename columns: `Not Applied · Applied · Interview · Offer · Rejected · Withdrawn`
- Drop Saved and Screening columns
- "Save" from Find Jobs creates `not_applied` outcome (via `POST /jobs/save`)
- Constrain DnD: grey out illegal transition targets
- `Withdrawn` column visible; cards there are read-only
- Update `screens4.jsx` column definitions

---

## Phase 1 — Foundation
*No dependencies. All four can be built in parallel. Must all be green before Phase 2 starts.*

---

### ✅ P1-1 · [GAP-B] Skill Dataclass
**Status:** ✅ Done 2026-06-16 — 73/73 tests green
**Design doc:** `docs/tasks/gap-b-skill-dataclass-design.md`

---

### ✅ P1-2 · [GAP-C/I] Source Feature Flag
**Status:** ✅ Done 2026-06-16 — 232/232 tests green
**Design doc:** `docs/tasks/gap-c-source-feature-flag-design.md`

---

### ✅ P1-3 · [GAP-D] Field Provenance (Null Contract)
**Status:** ✅ Done 2026-06-16 — 232/232 tests green
**Design doc:** `docs/tasks/gap-d-field-provenance-design.md`

---

### ✅ P1-4 · [JOB-009] Harden URL Fetcher
**Status:** ✅ Done 2026-06-16 — 232/232 tests green
**Design doc:** `docs/tasks/url-ingestion-design.md`

---

## ✅ Phase 1 — COMPLETE (2026-06-16)
*All four P1 items done and green. Phase 2 is now unblocked.*

---

## Phase 2 — Evaluation Enrichment
*Wait for all Phase 1 items to be green. P2-1 → P2-2 → P2-3 must run in order.*

---

### ✅ P2-1 · Source Quality Gating
**Status:** ✅ Done 2026-06-16 — 236/236 tests green
**Design doc:** `docs/tasks/source-quality-gating-design.md`

---

### ✅ P2-2 · ATS Scorer Integration [JOB-008]
**Status:** ✅ Done 2026-06-16 — 240/240 tests green
**Design doc:** `docs/tasks/ats-score-deferred.md`

---

### ✅ P2-3 · [GAP-E] Decision Override Persistence
**Status:** ✅ Done 2026-06-16 — 253/253 tests green
**Design doc:** `docs/tasks/gap-e-decision-override-design.md`

---

## Phase 3 — Infrastructure
*Wait for P2-3 (GAP-E). SQLite schema includes `ats_score` (P2-2) and `user_decision` (P2-3).*

---

### ✅ P3-1 · [GAP-H] Board Aggregate + SQLite Index
**Status:** ✅ Done 2026-06-16 — 267/267 tests green
**Design doc:** `docs/tasks/gap-h-board-aggregate-design.md`

---

## Phase 4 — Workspaces
*Wait for P2-3 (GAP-E). P4-1 and P4-2 can be built in parallel.*

---

### ✅ P4-1 · [GAP-F] Tailor CV Enrichment + Route
**Status:** ✅ Done 2026-06-16 — 278/278 tests green
**Design doc:** `docs/tasks/cv-tailoring-brief.md`

---

### ✅ P4-2 · [GAP-G] Cover Letter Extension + Route
**Status:** ✅ Done 2026-06-16 — 291/291 tests green
**Design doc:** `docs/tasks/cover-letter-spec-draft.md`

---

## Phase 5 — Multi-Source Expansion
*Source registry is in place (2026-06-17). Each new source just needs its own `*_source.py` file and one import line in `job_hunt_ui.py`.*

---

### 🔲 P5-1 · Adzuna Source Wiring
**Status:** Ready to build — `adzuna_client.py` exists, registry pattern is in place
**What to build:**
1. `src/job_sources/adzuna_source.py` — implements `JobSource` adapter: `is_available()` (checks `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`), `normalize_search_params()`, `search_handler()`, `select_handler()`, `render_search_form()`, `render_results()`
2. Add `from src.job_sources import adzuna_source as _adzuna_src` to `src/job_hunt_ui.py`
3. Enable `"adzuna"` in `ENABLED_SOURCES` via `src/job_hunt_config.py` once wired
**Design doc:** `docs/tasks/gap-c-source-feature-flag-design.md`
**Effort:** Medium

---

### 🔲 P5-2 · LinkedIn Source
**Status:** Deferred — no fetch client yet
**Design doc:** — (to be written)
**Trigger:** After LinkedIn fetch client is designed

---

## ✅ UX Hardening — Complete (2026-06-17)

| Item | Description |
|------|-------------|
| ✅ Profile CV status indicator | Green/amber/red strip on Profile page showing CV on-file state and char count |
| ✅ Profile save flash banner | Redirect after save now shows "Profile saved. CV: N chars on file." confirmation |
| ✅ Tailor actionable error | "No master CV" now points user to Profile page; distinguishes missing-ref vs unreadable-file |
| ✅ Cover letter error on missing CV | No longer silently proceeds with empty CV; returns same actionable error as tailor |
| ✅ Tailor result match stats | Result panel shows promoted / matched / missing counts alongside saved path |
| ✅ Auto-save error visible in browser | `auto_save_error` returned in JSON; shown in status bar if auto-save fails |
| ✅ AI Analysis manual button | Replaced auto-fire Ollama call with a "Run Analysis" button on job detail page |

---

## ✅ LLM + AI Analysis Overhaul — Complete (2026-06-18)

| Item | Description |
|------|-------------|
| ✅ Ollama → Google Gemini | `job_hunt_llm.py` rewritten to use Gemini REST API; no new packages; `GOOGLE_API_KEY` env var |
| ✅ Skill extraction model chain | `gemini-3.1-flash-lite` → `gemini-2.5-flash-lite` (fallback on 404/429) |
| ✅ Structured AI Analysis output | `explain_job_match_with_llm()` returns `{fit, risk, action}` dict; prompt requires JSON |
| ✅ 3-section AI Analysis UI | Fit Assessment / Key Risk / Recommended Action — colour-labelled, DOM-safe |
| ✅ Reasoning model chain | `gemini-3-flash-preview` (thinking 8k) → `gemini-2.5-flash` (thinking 8k) → `gemini-3.1-flash-lite` (fallback on 404/429) |
| ✅ Multi-select search results | Clickable cards, staging overlay, "Evaluate" per-job from staging; XSS-safe DOM building |
| ✅ Per-page timestamps | `_PAGE_UPDATED` dict; sidebar footer + job detail footer; rule saved to memory |
| ✅ Dev tooling | `dev.py` auto-reload watcher; `restart.sh` quick-restart script |

---

## ⏸ Deferred

| Item | Design doc | Trigger to revisit |
|------|------------|--------------------|
| GAP-J — Gap Coach | `docs/tasks/gap-j-gap-coach-design.md` | 10+ jobs evaluated in the tool |
| LinkedIn source | — | After LinkedIn fetch client is designed and built |

---

## 🆕 Product Features — from market research (2026-06)
**Research:** `docs/product-feature-research-2026-06.md` (market scan; quality/targeting beats auto-apply).

### ✅ F1 · Per-job ATS Match Rate + keyword gap
**Status:** ✅ Done (v1) 2026-06-19 — 337 tests green. **Design doc:** `docs/tasks/f1-ats-match-rate-design.md`
**What:** deterministic 0–100 keyword match rate per job (CV vs the job's required/preferred skills) with a present/missing breakdown, surfaced on the job page; anti-stuffing warning. New `src/job_hunt_keyword_match.py`; hook in `evaluate_reviewed_job`; 3 new `JobAnalysis` fields (+ storage round-trip). No new routes/LLM in v1.
**Effort:** M
**Other researched candidates (not yet designed):** F2 interview-prep pack, F3 follow-up nudges, F4 application-package export, F5 Adzuna + salary benchmark.

---

## 🗓 Backlog — Daily Job Digest (Auto-Evaluate + High-Match Feed)
**Design doc:** `docs/tasks/backlog-01-daily-digest-design.md`
**Prerequisite:** MT-1 (Reed source extraction) should be done first.

The feature runs a daily background pipeline (default 07:00) against the user's **saved search profiles**, evaluates all new jobs deterministically, runs LLM analysis on those scoring ≥ the user's configured threshold, and surfaces them in a **Digest feed** with a sidebar badge showing unseen count.

Phased into 5 sub-tasks — implement in order:

### ⬜ D1 · Saved Searches — foundation
**Status:** ⬜ Backlog
**What:** `src/job_hunt_saved_searches.py` + tests. SQLite column `saved_search_id`. Routes `GET/POST/DELETE /saved-searches`. "Save this search" button on Find Jobs tab. Saved Searches section in My Profile.
**Deliverable:** User can save, list, delete named searches. No auto-run yet.
**Effort:** M

---

### ⬜ D2 · Digest Schema + Query Layer
**Status:** ⬜ Backlog
**What:** Add `digest_date TEXT`, `digest_seen INTEGER` to SQLite jobs table via `migrate_schema()`. `src/job_hunt_digest.py` with `query_digest()`, `mark_seen()`, `unseen_count()` + tests. Route `GET /digest/count` (returns `{unseen: 0}` until D3 runs).
**Deliverable:** Schema ready; badge endpoint live.
**Effort:** S

---

### ⬜ D3 · Digest Pipeline (manual trigger)
**Status:** ⬜ Backlog
**What:** `run_digest_pipeline()` in `src/job_hunt_scheduler.py`. Route `POST /saved-searches/{id}/run-now`. New `UserPreferences` fields on `CandidateProfile` (`digest_threshold`, `digest_llm_enabled`, `digest_max_per_source`, `digest_max_llm_per_run`).
**Deliverable:** User can trigger a digest run manually. Results appear in index marked as digest jobs.
**Effort:** M–L

---

### ⬜ D4 · Digest UI
**Status:** ⬜ Backlog
**What:** `render_digest_page()`. Route `GET /digest`. Route `POST /digest/mark-seen`. Sidebar badge (AJAX `GET /digest/count`). Filters: date / source / saved-search / seen status.
**Deliverable:** User can see, filter, and mark digest jobs. Badge appears in sidebar.
**Effort:** M

---

### ⬜ D5 · Scheduler (fully automatic daily run)
**Status:** ⬜ Backlog
**What:** `DigestScheduler` background daemon thread. Integrated into server startup. `digest_run_time` + `digest_enabled` profile fields. Route `GET /scheduler/status`. Digest settings section in My Profile.
**Deliverable:** Fully automatic daily digest — user wakes up to a fresh feed.
**Effort:** M

---

## Summary Table

| # | Item | Phase | Effort | Blocked by | Design doc |
|---|------|-------|--------|------------|------------|
| 1 | ✅ GAP-B Skill dataclass | P1-1 | Medium | — | `docs/tasks/gap-b-skill-dataclass-design.md` |
| 2 | ✅ GAP-C/I Source flag | P1-2 | Small | — | `docs/tasks/gap-c-source-feature-flag-design.md` |
| 3 | ✅ GAP-D Field provenance | P1-3 | Small-Med | — | `docs/tasks/gap-d-field-provenance-design.md` |
| 4 | ✅ JOB-009 URL hardening | P1-4 | Medium | — | `docs/tasks/url-ingestion-design.md` |
| 5 | ✅ Source quality gating | P2-1 | Medium | P1 complete | `docs/tasks/source-quality-gating-design.md` |
| 6 | ✅ ATS scorer (JOB-008) | P2-2 | Small-Med | P2-1 | `docs/tasks/ats-score-deferred.md` |
| 7 | ✅ GAP-E Decision override | P2-3 | Medium | P2-2 | `docs/tasks/gap-e-decision-override-design.md` |
| 8 | ✅ GAP-H Board + SQLite | P3-1 | Large | P2-3 | `docs/tasks/gap-h-board-aggregate-design.md` |
| 9 | ✅ GAP-F Tailor CV | P4-1 | Large | P2-3 | `docs/tasks/cv-tailoring-brief.md` |
| 10 | ✅ GAP-G Cover letter | P4-2 | Medium | P2-3 | `docs/tasks/cover-letter-spec-draft.md` |
| 11 | ✅ Source registry + Reed decoupling | P5-0 | Medium | P4 complete | `src/job_sources/source_registry.py` |
| 12 | ✅ UX hardening — status/errors/AI button | UX | Small | P5-0 | — |
| 13 | 🔲 Adzuna source wiring | P5-1 | Medium | P5-0 | `docs/tasks/gap-c-source-feature-flag-design.md` |
| 14 | 🔲 LinkedIn source | P5-2 | Large | fetch client | — |
| — | GAP-J Gap Coach | Deferred | — | 10+ jobs | `docs/tasks/gap-j-gap-coach-design.md` |

---

## ✅ Completed

| Item | Description | Done |
|------|-------------|------|
| JOB-001 | Tailoring truth validation — real implementation, rejects unsupported claims | ✅ 2026-05-13 |
| JOB-002 | Reed orchestrator integration — `run_reed_evaluation_flow()` wired | ✅ 2026-05-13 |
| JOB-003 | PROJECT_LOG.md catch-up (Apr 14–28 gap entry) | ✅ 2026-05-02 |
| JOB-004 | product_spec.md updated (stale scope refs) | ✅ 2026-05-02 |
| JOB-005 | Cover letter tests — `tests/test_cover_letter.py` confirmed existing | ✅ 2026-05-20 |
| P1-1 GAP-B | Skill dataclass — `Skill` model, backward-compat loader, blast-radius updates to scoring/tailoring/cover_letter/UI, 73/73 tests | ✅ 2026-06-16 |
| P1-2 GAP-C/I | Source feature flag — `ENABLED_SOURCES`, `GET /sources`, Find Jobs toggles (Reed active, others "Coming soon") | ✅ 2026-06-16 |
| P1-3 GAP-D | Null contract — parsing returns `None`/`[]`/`"unknown"`, field-review badges in Add Job UI, 15 null-contract tests | ✅ 2026-06-16 |
| P1-4 JOB-009 | URL hardening — 8 security controls in `parse_job_from_url()`, paste_fetch.py zeroed, 14 security tests | ✅ 2026-06-16 |
| P2-1 | Source quality gating — `source_quality_score` on JobPosting, skip/review thresholds, UI badge, 4 new tests (236 total) | ✅ 2026-06-16 |
| P2-2 JOB-008 | ATS scorer integration — `ats_score` on JobAnalysis, wired into evaluate_reviewed_job(), Evaluate screen display, 4 new tests (240 total) | ✅ 2026-06-16 |
| P2-3 GAP-E | Decision override persistence — `user_decision`/`user_decision_note` on JobAnalysis, `effective_decision()`, POST /job/id/decision route, override buttons in UI, 13 new tests (253 total) | ✅ 2026-06-16 |
| P3-1 GAP-H | Board aggregate + SQLite index — `job_hunt_index.py`, GET /jobs, GET /board (6 columns + stats + allowed_transitions), POST /jobs/save, upsert hooks, startup rebuild, 14 new tests (267 total) | ✅ 2026-06-16 |
| P4-1 GAP-F | Tailor CV enrichment — `TailoredCVResult` dataclass, `tailor_cv()` returns structured result (summary/promoted/matched/missing/markdown), `validate_tailored_cv()` covers all fields, `POST /tailor` route with decision gate, 11 new tests (278 total) | ✅ 2026-06-16 |
| P4-2 GAP-G | Cover letter extension — `tone`/`length`/`points` params, `save_cover_letter()`, `POST /cover-letter` route with skip gate, 13 new tests (291 total) | ✅ 2026-06-16 |
| JOB-006 | Reed viewer canon — `viewer/reed_jobs_v4.html` only | ✅ 2026-05-20 |
| JOB-007 | URL ingestion design doc created — `docs/tasks/url-ingestion-design.md` | ✅ 2026-05-13 |
| 3A | data_contract.md and tailoring_spec.md created | ✅ 2026-05-02 |

---

---

## Code Quality — Quick Wins
*From code review 2026-06-18. Low effort, high value. No phase dependencies — can be done in any order.*

---

### ✅ QW-1 · Fix `_score_required_skills` Iterable double-consume
**Status:** ✅ Done 2026-06-19 — param typed `list[str]`; removed the redundant `list()` re-consume. 291 tests green.
**File:** `src/job_hunt_scoring.py` lines 91–108
**What:** Change `required_skills` parameter type from `Iterable[str]` to `list[str]`. Remove the `list(required_skills)` call after `_match_skills` has already consumed the iterator. Silent correctness bug if caller ever passes a generator.
**Effort:** XS

---

### ✅ QW-2 · Fix ATS scorer — ALL-CAPS header penalty is inverted
**Status:** ✅ Done 2026-06-19 — removed the `>=3 ALL-CAPS headers → 0` penalty; well-structured CVs now score full format marks. Updated `test_multiple_all_caps_headers`. 291 green.
**File:** `src/job_hunt_ats_scorer.py` lines 74–80
**What:** `_score_format` currently returns 0 for CVs with 3+ ALL-CAPS section headers (`EXPERIENCE`, `SKILLS`, `EDUCATION`). This is the standard professional and ATS-friendly format. Remove or flip the penalty — well-formatted CVs should not score lower than unstructured text.
**Effort:** XS

---

### ✅ QW-3 · Remove `logging.basicConfig` from `reed_client.py` module level
**Status:** ✅ Done 2026-06-19 — deleted module-level `basicConfig`; keeps `getLogger(__name__)`.
**File:** `src/job_sources/reed_client.py` line 10
**What:** Delete `logging.basicConfig(level=logging.INFO)`. Use `logging.getLogger(__name__)` already on line 11. Module-level `basicConfig` overrides the host process's logging config on import.
**Effort:** XS

---

### ✅ QW-4 · Fix `shared_bus.py` (NOT deleted — it is live)
**Status:** ✅ Done 2026-06-19 — 291 tests green (incl. 12 swarm tests). `shared_bus` is imported by `tests/test_swarm_router_auto_advance.py` and `tests/test_swarm_stage_derivation.py`, so the code-review 'unused, delete it' premise was wrong. Fixed instead: collapsed the two `_conn()` definitions into one (kept the URI-aware impl that actually ran) and the two `DB_PATH` definitions into one — removed the hardcoded `~/.openclaw/workspace/shared_memory.db` foreign path; `DB_PATH` now defaults project-relative and honours the `SHARED_BUS_DB` env override.
**File:** `src/shared_bus.py`
**What:** File has two definitions each of `_conn()` (lines 27, 257) and `DB_PATH` (lines 12, 266); second pair silently overrides the first. `DB_PATH` points to `~/.openclaw/workspace/shared_memory.db` — a path on an AI tool's machine, not this project. If the swarm feature is unused, delete the file. If needed, fix duplicates and make `DB_PATH` configurable.
**Effort:** XS

---

### ✅ QW-5 · Remove `evaluate_job_from_raw` from `__all__` or implement it
**Status:** ✅ Done 2026-06-19 — removed the non-existent name from `__all__`.
**File:** `src/job_hunt_evaluation.py` line 109
**What:** `__all__` exports `evaluate_job_from_raw` but no such function exists anywhere in the module. Either remove it from `__all__` or implement it. Currently a misleading broken export.
**Effort:** XS

---

### ✅ QW-6 · Fix `job_hunt_config.py` `__all__`
**Status:** ✅ Done 2026-06-19 — removed the misleading 1-of-6 `__all__` so all public names export.
**File:** `src/job_hunt_config.py` line 106
**What:** `__all__ = ["ScoringWeights"]` but the module also exports `ScoringPolicy`, `DecisionPolicy`, `DEFAULT_SCORING_POLICY`, `get_enabled_sources`, etc. Either list all exported names or remove `__all__` entirely.
**Effort:** XS

---

### ✅ QW-7 · Extract duplicated `upsert_job` block into a helper
**Status:** ✅ Done 2026-06-19 — 291 tests green. `_upsert_job_to_index(config, job_id, *, reviewed_job, analysis, outcome)` in `src/ui_handlers.py` (sentinel-loads any piece not supplied); replaced all 6 copy-pasted blocks (render_result, handle_job_submit, handle_outcome, handle_decision_override, handle_batch_evaluate, handle_jobs_save).
**File:** `src/job_hunt_ui.py`
**What:** The 15-field `upsert_job` dict is copy-pasted in five handlers: `_render_result`, `_handle_job_submit`, `_handle_outcome`, `_handle_decision_override`, `_handle_batch_evaluate`. Extract to a single `_upsert_job_to_index(job_id)` helper called from all five. One will diverge otherwise.
**Effort:** S

---

### ✅ QW-8 · Add dimension-level cap to skill score bonus
**Status:** ✅ Done 2026-06-19 — `_score_skill_bucket` now caps the all-matched return at `weight * 1.5`. 291 green.
**File:** `src/job_hunt_scoring.py` line 141
**What:** `_score_skill_bucket` can return up to weight + (N-1) × bonus_per_match, pushing the dimension well above its weight (e.g. 35-pt dimension → 42+ pts). The global `min(100)` cap absorbs this but masks the signal — a candidate can score 100 with 3 of 5 required skills. Cap the dimension return value at `weight * 1.5` (or similar) so the global cap is not doing silent work.
**Effort:** XS

---

### ✅ QW-9 · Add skill name length cap in `_handle_add_gap_skills`
**Status:** ✅ Done 2026-06-19 — skill names capped at 120 chars during normalisation in `handle_add_gap_skills` (now in `ui_handlers.py`).
**File:** `src/job_hunt_ui.py` around line 1091
**What:** Skill names from `POST /job/{id}/add-gap-skills` JSON body are only stripped and deduplicated before writing to the profile. No length cap — arbitrarily long strings accumulate. Add a max length of ~120 characters per skill name before appending.
**Effort:** XS

---

## Code Quality — Medium Term
*Each item needs some design thought but has a bounded scope. No blocking dependencies between them.*

---

### ✅ MT-1 · Move Reed rendering/normalisation into `src/job_sources/reed_source.py`
**Status:** ✅ Done 2026-06-19 — 291 tests green. reed_source.py (782 lines) self-contained; registry contract updated to 2-arg select_handler / 4-arg render_results; reed↔ui circular import removed.
**Files:** New `src/job_sources/reed_source.py`, `src/job_hunt_ui.py`
**What:** Move `_render_reed_search_form`, `render_reed_search_results`, `_render_reed_cards_fragment`, `reed_select_form_to_evaluate_values`, `normalize_reed_search_params`, `search_reed_jobs_for_ui`, salary/snapshot helpers, and the `_register_source` call into a self-contained source module. The source registry abstraction was built for this. Cuts `job_hunt_ui.py` by ~600–700 lines.
**Effort:** M

---

### ✅ MT-2 · Extract shared validation helpers to `src/job_hunt_validation.py`
**Status:** ✅ Done 2026-06-19 — 312 tests green. New `src/job_hunt_validation.py` (8 parameterised helpers + injected `error=` class); `storage`/`reviewed_input`/`profile` keep their private names as `functools.partial` bindings, so all call sites are unchanged and each module still raises its own exception type. Behaviour-preserving incl. messages (`message_style` keeps storage's combined wording). Design: `docs/tasks/mt-02-validation-helpers-design.md`. Reviewer findings addressed: message_style, explicit bool rejection, `optional_text_or_empty(' ')` whitespace lock. 18 new unit tests in `tests/test_validation.py`.
**Files:** New `src/job_hunt_validation.py`, `job_hunt_storage.py`, `job_hunt_reviewed_input.py`, `job_hunt_profile.py`
**What:** `_required_string`, `_optional_string`, `_normalise_string_list`, `_optional_non_negative_int`, `_optional_bool` are duplicated across three modules with subtly different behaviour. Create one canonical module and import from it in all three. Prevents silent divergence.
**Effort:** S–M

---

### ✅ MT-3 · Score required-skills-missing as neutral + confidence gate
**Status:** ✅ Done 2026-06-19 (Mic approved Option 1) — 291 tests green. (1) `_score_required_skills` now returns full neutral weight when the job lists no required skills (matching unknown location/salary/experience), so absent data isn't penalised. (2) `decide_application` gained a `confidence` arg and a gate: a score that meets the apply threshold but has **low** confidence is routed to **review**, never auto-**apply** — so data-sparse jobs go to a human instead of being recommended blind. (3) `evaluate_reviewed_job` threads `scoring_result.confidence` through. Updated 3 tests (sparse job now scores 86.5 → review, not 51.5 → skip).
**File:** `src/job_hunt_scoring.py`
**What:** When `required_skills == []`, the required-skills dimension currently scores 0. This silently penalises jobs with incomplete skill data in the most important dimension — contradicting the confidence system's design (carry uncertainty, don't penalise it). Score neutral (same as when salary or location is missing) and let confidence carry the uncertainty signal.
**Effort:** S

---

### ✅ MT-4 · Guard `parse_multipart_form` against missing Content-Type boundary
**Status:** ✅ Done 2026-06-19 — explicit `boundary=` check raises a clear `ValueError` (surfaced as a 400 by `handle_parse_cv`) instead of the cryptic 'not enough values to unpack'. (Function now lives in `ui_handlers.py` as `parse_multipart_form`.) 291 green.
**File:** `src/job_hunt_ui.py` lines 572–574
**What:** `content_type.split(";", 1)` raises `ValueError` if `Content-Type` is `multipart/form-data` without `;boundary=...`. The outer `except` catches it but returns "not enough values to unpack" to the browser. Add an explicit check before splitting and return a clear error message.
**Effort:** XS

---

### ✅ MT-5 · Anchor profile paths to an absolute base
**Status:** ✅ Done 2026-06-19 — `_allowed_profile_dir` now resolves against `_DATA_ROOT = Path(__file__).resolve().parents[1] / 'data'` (project-root-absolute) instead of CWD-relative `Path('data')`, so reads/writes hit the right directory regardless of launch CWD. 291 green.
**File:** `src/job_hunt_ui.py` lines ~150–166
**What:** `_allowed_profile_dir` constructs `Path("data") / profile_id` — a relative CWD path. If the server starts from a directory other than the project root, all profile reads/writes go to the wrong location silently. Resolve to an absolute path anchored to the config's known startup location.
**Effort:** S

---

### ✅ MT-6 · Write missing tests for batch evaluate, pagination, CV auto-save
**Status:** ✅ Done 2026-06-19 — 315 tests green. Added 6 tests in `tests/test_ui.py`: batch-evaluate cap, `/search/reed/more` pagination, multipart missing-boundary (MT-4 path), parse-CV happy path, parse-CV auto-save (with `_DATA_ROOT` monkeypatched to tmp), and save-profile skills_json-over-comma precedence. Added a `_http_post_multipart` helper to the harness.
**File:** `tests/test_ui.py`
**What:** The following flows are completely untested: `POST /jobs/batch-evaluate`, `GET /search/reed/more` (pagination), CV auto-save happy path in `_handle_parse_cv`, `_handle_save_profile` skills JSON vs comma-split fallback, `_read_multipart_form` crash on missing boundary. Add at least one test per flow.
**Effort:** M

---

### ✅ MT-7 · Remove nonce infrastructure
**Status:** ✅ Done 2026-06-19 — deleted the no-op `consume_select_nonce`, the `_SELECT_NONCES` store and TTL cleanup, and the always-passing check in `reed_select_form_to_evaluate_values`. `create_select_nonce` is now a stateless token generator (token still emitted as a hidden field as a placeholder; nothing validates it). 291 green incl. `test_post_select_reed_nonce_not_enforced`.
**File:** `src/job_hunt_ui.py` lines 1905–1909
**What:** `consume_select_nonce` always returns `True` (CSRF check disabled to avoid dev-reload friction). The nonce creation, `_SELECT_NONCES` dict, and TTL cleanup are all live but pointless. Either re-enable the check or delete the entire nonce system to remove misleading dead code.
**Effort:** S

---

## Code Quality — Longer Term
*Architectural changes. Worth deferring until quick wins and medium-term items are done.*

---

### ✅ LT-1 · Split `job_hunt_ui.py` into routing / handler / render layers
**Status:** ✅ Done 2026-06-19 — 315 tests green. All 7 steps complete: reed_source (MT-1) → ui_state → ui_utils → ui_render (full view-models, domain-free) → ui_handlers (standalone (req,config,responder) fns + UIRequest/UIResponder) → ui_routes → shell. **Step 7 (re-export cleanup) done**: the one importer (`tests/test_ui.py`) repointed to `ui_state`/`ui_routes`/`ui_utils`/`ui_handlers`; shell reduced to **19 lines** (docstring + `from src.ui_routes import main` + entry point). QW-7 also done separately.
**Design doc:** `docs/tasks/lt-01-ui-layer-split-design.md`
**Files:** `src/ui_state.py`, `src/ui_utils.py`, `src/ui_render.py`, `src/ui_handlers.py`, `src/ui_routes.py`; `job_hunt_ui.py` → thin 20-line shell
**What:** At 4,700+ lines, `job_hunt_ui.py` mixes HTTP routing, business coordination, and HTML generation in one file. Split into 5 focused modules using a `UIResponder` interface pattern so every handler and render function is independently testable without a live HTTP server. Adding new job sources (Adzuna, LinkedIn) becomes safe once this split is in place — each source lives in `src/job_sources/{name}_source.py` only.
**Effort:** L (but incremental — 7 steps, server runnable after each)
**Prerequisite:** MT-1 (Reed source extraction) must go first — removes ~650 lines before the split begins

---

### ✅ LT-2 · Move CSS and JS out of f-strings into module-level constants
**Status:** ✅ Done 2026-06-19 — 315 tests green, render output **byte-identical** (verified by diff before/after). In `src/ui_render.py`, `render_page`'s inlined CSS (~12 KB) and JS (~3.6 KB) moved to plain module constants `_PAGE_CSS` / `_PAGE_JS` (single braces, no f-string `{{`/`}}` escaping); the one dynamic JS value (model label) is substituted via a `__MODEL_LABEL__` sentinel. `render_page` shrank 316 → 29 lines.
**File:** `src/job_hunt_ui.py` (`render_page` and JS IIFE blocks)
**What:** ~800 lines of CSS/JS are inlined on every response via f-string concatenation. This makes CSS/JS changes require navigating Python string escaping and makes the render output untestable at the element level. Move to module-level string constants (stdlib `string.Template`) or static file routes as a minimum.
**Effort:** M–L

---

### ✅ LT-3 · Add `__post_init__` validator to `ScoringWeights` asserting weights sum to 100
**Status:** ✅ Done 2026-06-19 — `ScoringWeights.__post_init__` raises if the 7 dimension weights don't sum to 100 (±0.01), so misconfiguration is caught at construction instead of silently hitting the global min(100) cap. 291 green.
**File:** `src/job_hunt_config.py`
**What:** A misconfigured `ScoringWeights` where weights sum to 120 would silently produce outputs that hit the `min(100)` global cap for most candidates — no error raised. Add a `__post_init__` that asserts `self.total() == 100.0` (within a small tolerance) so misconfiguration is caught at startup.
**Effort:** XS

---

## Code Review Reference
**Full review:** `docs/code-review-2026-06-18.md`
**Reviewed:** 2026-06-18 | **Issues found:** 6 architecture, 10 code quality, 5 security/correctness, 10 test gap areas

---

## Pipeline Gate

**Phase 1 ✅ COMPLETE** — all four items done and green (2026-06-16).
**Phase 2 ✅ COMPLETE** — P2-1, P2-2, P2-3 all done and green (2026-06-16). 253 tests passing.
**Phase 3 ✅ COMPLETE** — P3-1 done and green (2026-06-16). 267 tests passing.
**Phase 4 ✅ COMPLETE** — P4-1 and P4-2 both done and green (2026-06-16). 291 tests passing.
**UX Hardening ✅ COMPLETE** — CV status, error messages, AI Analysis button, match stats panel (2026-06-17). 291 tests passing.
**LLM + AI Overhaul ✅ COMPLETE** — Gemini backend, structured analysis, reasoning chain, multi-select UI, per-page timestamps, dev tooling (2026-06-18). 291 tests passing.
