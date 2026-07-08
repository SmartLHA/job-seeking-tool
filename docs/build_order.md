# Build Priority Order

**Date:** 2026-06-16
**Scope:** Historical build plan from the v4 UI design session.
**Rule:** Items within a phase can be built in parallel. Items in a later phase must not start
until all items in the prior phase are complete and tests are green.

> **Current status (updated 2026-06-30):** This plan's foundation, enrichment,
> board, tailoring, cover-letter, source-registry, LT-1 split, and F1 work are
> implemented. Saved Searches + Daily Digest (D1–D6) and the Adzuna & LinkedIn
> source adapters are also complete and enabled. Treat the phase detail below as
> implementation history. The remaining backlog is Gap Coach (GAP-J, deferred) and
> researched-but-undesigned features (interview-prep, follow-up nudges, DOCX/PDF
> export, salary benchmark).

---

## Dependency Map

```
GAP-B (Skill dataclass)
  └─► Source quality gating    ──┐
  └─► ATS scorer integration   ──┤
                                  ├─► GAP-E (Decision override)
  GAP-D (Field provenance)        │     └─► GAP-F (Tailor CV)
  GAP-C/I (Source flag)           │     └─► GAP-G (Cover letter)
  JOB-009 (URL hardening)         │     └─► GAP-H (Board + SQLite)
                                  │
                    GAP-H ◄───────┘  (needs ats_score + user_decision in schema)

GAP-J (Gap Coach) ── deferred
```

---

## Phase 1 — Foundation
*Model and config changes everything else depends on. Do these first.*

---

### ✅ P1-1 · GAP-B — Skill Dataclass *(Done 2026-06-16 — 73/73 tests green)*
**Why first:** Changes `CandidateProfile.skills` from `list[str]` to `list[Skill]`.
Every module that reads the profile (scoring, tailoring, cover letter, UI) must work
against the new shape. Do this before any other model work begins.

**Effort:** Medium — touches 6 files + backward-compat loader

| Role | File |
|------|------|
| Design doc | `docs/tasks/gap-b-skill-dataclass-design.md` |
| Change | `src/job_hunt_models.py` — add `Skill` dataclass; change `CandidateProfile.skills` |
| Change | `src/job_hunt_profile.py` — `_coerce_skill()` backward-compat; update to_dict/from_dict |
| Change | `src/job_hunt_scoring.py` — access `s.name` instead of `s` in skill-match loops |
| Change | `src/job_hunt_tailoring.py` — fix `.strip()` on Skill objects (lines 22, 121) |
| Change | `src/job_hunt_cover_letter.py` — fix `_match_skills()` to accept `list[Skill]` (line 160) |
| Change | `src/job_hunt_ui.py` — My Profile skill table: level/years/evidence columns |
| Tests | `tests/test_models.py` |
| Tests | `tests/test_profile.py` |
| Tests | `tests/test_scoring.py` |
| Tests | `tests/test_tailoring.py` — update profile fixtures to list[Skill] |
| Tests | `tests/test_cover_letter.py` — update profile fixtures to list[Skill] |
| Reference | `docs/data_contract.md` — update profile skills contract section |

---

### ✅ P1-2 · GAP-C/I — Source Feature Flag *(Done 2026-06-16)*
**Why early:** One config line + one route. Unblocks the Find Jobs source toggles immediately.
Completely independent of all other work.

**Effort:** Small — ~30 lines of code

| Role | File |
|------|------|
| Design doc | `docs/tasks/gap-c-source-feature-flag-design.md` |
| Change | `src/job_hunt_config.py` — add `ENABLED_SOURCES`, `get_enabled_sources()` |
| Change | `src/job_hunt_ui.py` — add `GET /sources` route |
| Tests | `tests/test_ui.py` |

---

### ✅ P1-3 · GAP-D — Field Provenance (Null Contract) *(Done 2026-06-16)*
**Why early:** Parsing contract change. Independent of all model work. Lets the Add Job
field-review form correctly tag auto-filled vs not-found fields from day one.

**Effort:** Small-medium — audit all extractors in parsing.py + UI badge rendering

| Role | File |
|------|------|
| Design doc | `docs/tasks/gap-d-field-provenance-design.md` |
| Change | `src/job_hunt_parsing.py` — replace all placeholder defaults with `None`/`[]` |
| Change | `src/job_hunt_ui.py` — field-review form: auto-filled/not-found badge per field |
| Tests | `tests/test_parsing.py` — null-contract tests for every field |

---

### ✅ P1-4 · JOB-009 — Harden URL Fetcher *(Done 2026-06-16)*
**Why early:** Security work. Independent of all model changes. Cleans up the two-fetcher
ambiguity and brings `parse_job_from_url` up to the safety spec before it's used more widely.

**Effort:** Medium — 8 specific hardening tasks + delete dead code

| Role | File |
|------|------|
| Design doc | `docs/tasks/url-ingestion-design.md` (Section 12 — hardening tasks list) |
| Change | `src/job_hunt_parsing.py` — add allowlist, redirect/scheme revalidation, split timeout budgets, content-type/size guards, SSRF prevention, strip scripts/styles |
| Delete | `src/job_hunt_paste_fetch.py` — remove entirely |
| Tests | `tests/test_parsing.py` — allowlist, timeout, redirect, robots, SSRF tests |
| Reference | `docs/tasks/url-ingestion-design.md` — Sections 3–6 for full safety spec |
| Reference | `docs/tasks/job-ingestion-api-design.md` — confirms Reed API path remains separate |

---

## Phase 2 — Evaluation Enrichment
*Enrich the evaluation model. All items touch `JobPosting` or `JobAnalysis`.
Wait for Phase 1 (especially GAP-B) to be green before starting.*

---

### ✅ P2-1 · Source Quality Gating *(Done 2026-06-16 — 236/236 tests green)*
**Why here:** Adds `source_quality_score` to `JobPosting` — a model change. Must come before
ATS scorer and decision override (which both also touch evaluation model) so all model changes
land together in one stable version.

**Effort:** Medium — model field + evaluation logic + config thresholds + UI badge

| Role | File |
|------|------|
| Design doc | `docs/tasks/source-quality-gating-design.md` |
| Change | `src/job_hunt_models.py` — add `source_quality_score: int | None` to `JobPosting` |
| Change | `src/job_hunt_config.py` — `SOURCE_QUALITY_SKIP_THRESHOLD = 40`, `SOURCE_QUALITY_REVIEW_THRESHOLD = 70`; add `marginal-source-quality` to `critical_risk_codes` |
| Change | `src/job_hunt_evaluation.py` — `_source_quality_blockers_and_flags()` injected into evaluation |
| Change | `src/job_hunt_orchestrator.py` — populate `source_quality_score` from Reed normalised result |
| Change | `src/job_hunt_reviewed_input.py` — accept `source_quality_score` in `reviewed_job_from_dict()` |
| Change | `src/job_hunt_storage.py` — serialise/deserialise new field |
| Change | `src/job_hunt_ui.py` — quality badge in Evaluate screen header |
| Tests | `tests/test_evaluation.py` |
| Reference | `docs/tasks/job-ingestion-api-design.md` — original quality-gate spec |
| Reference | `src/job_sources/normalize.py` — `source_quality` dict shape (existing) |

---

### ✅ P2-2 · ATS Scorer Integration (JOB-008) *(Done 2026-06-16 — 240/240 tests green)*
**Why here:** Adds `ats_score` to `JobAnalysis`. Needs to come after source quality (both
touch the evaluation model) so the model lands in one pass. Must come before GAP-H (SQLite
schema includes `ats_score`).

**Effort:** Small-medium — integration only; scorer module already exists and tested

| Role | File |
|------|------|
| Design doc | `docs/tasks/ats-score-deferred.md` |
| Change | `src/job_hunt_models.py` — add `ats_score: int | None = None` to `JobAnalysis` |
| Change | `src/job_hunt_evaluation.py` — call `score_cv()` after scoring; populate `ats_score` |
| Change | `src/job_hunt_storage.py` — serialise/deserialise `ats_score` in `job_analysis_to_dict/_from_dict` |
| Change | `src/job_hunt_ui.py` — render ATS score in Evaluate screen breakdown panel |
| No change | `src/job_hunt_ats_scorer.py` — do not modify |
| No change | `tests/test_ats_scorer.py` — do not modify |
| Tests | `tests/test_evaluation.py` — CV-present and CV-absent paths |
| Tests | `tests/test_models.py` — serialisation |

---

### ✅ P2-3 · GAP-E — Decision Override Persistence *(Done 2026-06-16 — 253/253 tests green)*
**Why here:** Adds `user_decision` to `JobAnalysis`. Must come after ATS scorer (model stable).
Must come before GAP-F, GAP-G, GAP-H — all three need `effective_decision()` or `user_decision`
in the SQLite schema.

**Effort:** Medium — model field + new route + `effective_decision()` wired everywhere

| Role | File |
|------|------|
| Design doc | `docs/tasks/gap-e-decision-override-design.md` |
| Change | `src/job_hunt_models.py` — add `user_decision`, `user_decision_note` to `JobAnalysis` |
| Change | `src/job_hunt_storage.py` — serialise/deserialise new fields |
| Change | `src/job_hunt_tailoring.py` — use `effective_decision()` for tailoring gate |
| Change | `src/job_hunt_cover_letter.py` — use `effective_decision()` for cover letter gate |
| Change | `src/job_hunt_reporting.py` — export `engine_decision` + `user_decision` columns |
| Change | `src/job_hunt_ui.py` — add `POST /job/<id>/decision`; override buttons + badge in Evaluate |
| Tests | `tests/test_models.py` |
| Tests | `tests/test_evaluation.py` |
| Tests | `tests/test_ui.py` |

---

## Phase 3 — Infrastructure
*Board, index, and bookmark. Needs a stable evaluation model (ats_score + user_decision)
before building the SQLite schema.*

---

### ✅ P3-1 · GAP-H — Board Aggregate + SQLite Index *(Done 2026-06-16 — 267/267 tests green)*
**Why here:** SQLite schema includes `ats_score` (P2-2) and `user_decision` (P2-3). Both must
be finalised before the schema is created, or a migration will be needed immediately.

**Effort:** Large — new module, 3 new routes, startup rebuild logic, tests

| Role | File |
|------|------|
| Design doc | `docs/tasks/gap-h-board-aggregate-design.md` |
| New | `src/job_hunt_index.py` — SQLite schema, `upsert_job()`, `query_board()`, `query_jobs_list()`, `rebuild_index()` |
| Change | `src/job_hunt_ui.py` — `GET /jobs`, `GET /board`, `POST /jobs/save`; call `rebuild_index()` on startup |
| Change | `src/job_hunt_outcomes.py` — after `update_outcome()`, call `upsert_job()` |
| Change | `src/job_hunt_evaluation.py` — after evaluation write, call `upsert_job()` |
| New | `tests/test_index.py` — SQLite upsert, query, rebuild |
| Tests | `tests/test_ui.py` — 3 new routes |
| Reference | `src/job_hunt_outcomes.py` — `_ALLOWED_TRANSITIONS` (used for `allowed_transitions` in board response) |
| Reference | `src/job_hunt_models.py` — `OutcomeStatus` values = column names |

---

## Phase 4 — Workspaces
*Tailor CV and Cover Letter full-screen workspaces. Both need `effective_decision()` from
GAP-E (P2-3). Can be built in parallel with each other.*

---

### ✅ P4-1 · GAP-F — Tailor CV Enrichment + Route *(Done 2026-06-16 — 278/278 tests green)*
**Why here:** Needs `effective_decision()` from GAP-E for the tailoring gate. Also needs the
stable `Skill` model from GAP-B to ensure evidence selection works correctly.

**Effort:** Large — enriched return type, new route, updated validation

| Role | File |
|------|------|
| Design doc | `docs/tasks/cv-tailoring-brief.md` |
| Change | `src/job_hunt_models.py` — add `TailoredCVResult` dataclass |
| Change | `src/job_hunt_tailoring.py` — update `tailor_cv()` to return `TailoredCVResult`; add `summary`, `promoted`, `matched`, `missing`; update `validate_tailored_cv()` to cover all fields |
| Change | `src/job_hunt_ui.py` — add `POST /tailor` route |
| Tests | `tests/test_tailoring.py` — new fields; update existing tests to unpack `TailoredCVResult` |
| Reference | `docs/tailoring_spec.md` — truth boundary rules |
| Reference | `docs/architecture_guardrails.md` — Guardrails 6 and 7 (tailoring must not bypass evaluation; no invented claims) |

---

### ✅ P4-2 · GAP-G — Cover Letter Extension + Route *(Done 2026-06-16 — 291/291 tests green)*
**Why here:** Needs `effective_decision()` from GAP-E. Can be built in parallel with GAP-F.

**Effort:** Medium — extend function signature + new route

| Role | File |
|------|------|
| Design doc | `docs/tasks/cover-letter-spec-draft.md` |
| Change | `src/job_hunt_cover_letter.py` — add `tone`, `length`, `points` parameters |
| Change | `src/job_hunt_tailoring.py` — update `generate_cover_letter_text()` wrapper to pass new params |
| Change | `src/job_hunt_ui.py` — add `POST /cover-letter` route |
| Tests | `tests/test_cover_letter.py` — tone/length/points variations; existing tests must still pass |
| Reference | `docs/architecture_guardrails.md` — Guardrail 7 (no invented claims in letter body) |

---

## Deferred

| Item | Status | Trigger to revisit |
|------|--------|--------------------|
| GAP-J — Gap Coach | ⏸ Deferred | 10+ jobs evaluated in the tool |
| Adzuna source wiring | ✅ Done | Shipped — `adzuna_source.py` registered & enabled |
| LinkedIn source | ✅ Done | Shipped — `linkedin_source.py` registered & enabled |

---

## Phase 5 — Multi-Source Expansion *(unlocked 2026-06-17)*

The source registry (`src/job_sources/source_registry.py`) was introduced on 2026-06-17 to decouple the UI from Reed-specific routing and rendering. Adding any new source now requires only a single `*_source.py` file and one import line in `src/ui_routes.py` (the source-registration imports; historically this was `src/job_hunt_ui.py`, before the LT-01 UI split made it a thin entry point) — no routing or dispatch changes needed.

### P5-0 · Source Registry + Reed Decoupling ✅ (2026-06-17)
- New file: `src/job_sources/source_registry.py` — `JobSource` dataclass + registry
- Routes generalised: `/search/{source}` and `/select/{source}`
- Nonce and field-limit constants renamed to be source-agnostic
- `_render_search_jobs_tab` now iterates `all_sources()` dynamically
- Reed registered as first `JobSource` at bottom of `src/job_hunt_ui.py`
- `GET /board` restored to JSON; HTML board view moved to `GET /board/view`
- 291/291 tests green

### P5-1 · Adzuna Source Wiring ✅
- Create `src/job_sources/adzuna_source.py` with self-contained adapter
- One import line in `src/job_hunt_ui.py`
- Enable `"adzuna"` in `ENABLED_SOURCES`
- Blocked by: P5-0 ✅

---

## Summary Table

| # | Item | Phase | Effort | Blocked by | Design doc |
|---|------|-------|--------|------------|------------|
| 1 | ✅ GAP-B Skill dataclass | P1 | Medium | — | `docs/tasks/gap-b-skill-dataclass-design.md` |
| 2 | ✅ GAP-C/I Source flag | P1 | Small | — | `docs/tasks/gap-c-source-feature-flag-design.md` |
| 3 | ✅ GAP-D Field provenance | P1 | Small-Med | — | `docs/tasks/gap-d-field-provenance-design.md` |
| 4 | ✅ JOB-009 URL hardening | P1 | Medium | — | `docs/tasks/url-ingestion-design.md` |
| 5 | ✅ Source quality gating | P2 | Medium | P1 (GAP-B) | `docs/tasks/source-quality-gating-design.md` |
| 6 | ✅ ATS scorer (JOB-008) | P2 | Small-Med | P2-1 | `docs/tasks/ats-score-deferred.md` |
| 7 | ✅ GAP-E Decision override | P2 | Medium | P2-2 | `docs/tasks/gap-e-decision-override-design.md` |
| 8 | ✅ GAP-H Board + SQLite | P3 | Large | P2-3 | `docs/tasks/gap-h-board-aggregate-design.md` |
| 9 | ✅ GAP-F Tailor CV | P4 | Large | P2-3 | `docs/tasks/cv-tailoring-brief.md` |
| 10 | ✅ GAP-G Cover letter | P4 | Medium | P2-3 | `docs/tasks/cover-letter-spec-draft.md` |
| 11 | ✅ Source registry + Reed decoupling | P5-0 | Medium | P4 complete | `src/job_sources/source_registry.py` |
| 12 | ✅ Adzuna source wiring | P5-1 | Medium | P5-0 | `docs/tasks/gap-c-source-feature-flag-design.md` |
| 13 | ✅ LinkedIn source | P5-2 | Large | fetch client | — |
| — | GAP-J Gap Coach | Deferred | — | 10+ jobs | `docs/tasks/gap-j-gap-coach-design.md` |

---

## Cross-cutting Reference Files

These files are not changed by any single item but must be consulted throughout:

| File | Relevant to |
|------|------------|
| `src/job_hunt_models.py` | P1-1, P2-1, P2-2, P2-3, P4-1 — all model changes land here |
| `src/job_hunt_config.py` | P1-2, P2-1 — thresholds and policy |
| `src/ui_routes.py` | Routing + source registration — every route lives here post LT-01 split (`src/job_hunt_ui.py` is now a thin entry point) |
| `docs/architecture_guardrails.md` | P4-1, P4-2 — truth boundaries for tailoring/cover letter |
| `docs/data_contract.md` | P1-1 — update profile skills section after GAP-B |
| `Claude deliverable/docs/ui_structure_v4.md` | All items — authoritative screen → route binding |
| `Claude deliverable/docs/function_list_v4.md` | All items — real function signatures and GAP annotations |
