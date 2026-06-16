# Job Seeking Tool — Project TODO
**Last updated:** 2026-06-16 (Phase 1 complete — all P1 items done) | **Owner:** Mic
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

## ⏸ Deferred

| Item | Design doc | Trigger to revisit |
|------|------------|--------------------|
| GAP-J — Gap Coach | `docs/tasks/gap-j-gap-coach-design.md` | 10+ jobs evaluated in the tool |
| Adzuna source wiring | `docs/tasks/gap-c-source-feature-flag-design.md` | After `adzuna_client.py` fetch implemented |
| LinkedIn source | — | After LinkedIn fetch client is designed and built |

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

## Pipeline Gate

**Phase 1 ✅ COMPLETE** — all four items done and green (2026-06-16).
**Phase 2 ✅ COMPLETE** — P2-1, P2-2, P2-3 all done and green (2026-06-16). 253 tests passing.
**Phase 3 ✅ COMPLETE** — P3-1 done and green (2026-06-16). 267 tests passing.
**Phase 4 ✅ COMPLETE** — P4-1 and P4-2 both done and green (2026-06-16). 291 tests passing.
