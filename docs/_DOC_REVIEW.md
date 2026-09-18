# Doc review — working findings (2026-06-30)

> Codex's first read-only pass ran with an INCOMPLETE route list (it was missing
> `GET /` and `GET /job/{id}`), so its three HIGH findings were false positives.
> Verified against `src/ui_routes.py`. Status below is post-verification.

## docs/function_list.md
- [DISMISSED] `GET /job/<id>` flagged as non-existent — FALSE. Route exists (ui_routes.py:249-251 `render_job`). Doc is correct.

## INDEX.md
- [DISMISSED] `GET /` flagged as non-existent — FALSE. Route exists (ui_routes.py:199 `render_home`). Doc is correct.
- [DISMISSED] `GET /job/{id}?embed=1` flagged as non-existent — FALSE. `/job/{id}` exists; `embed=1` is a query param. Doc is correct.
- [MED — open] INDEX "Source Code" table is not exhaustive (omits ~11 src modules + several job_sources support modules). Decide: make exhaustive vs add "adapters/key modules only" note.
- [LOW — open] Route text style: `<id>` vs `{id}` used inconsistently across docs.

## PROJECT_TODO.md
- [LOW — verified] line 309 P2-3 GAP-E row writes `POST /job/id/decision` → FIX: `POST /job/{id}/decision`.

## docs/build_order.md
- [HIGH — verified] Phase 5 source-registry instructions say new sources need an import line in `src/job_hunt_ui.py` and that Reed registers at the bottom of `job_hunt_ui.py`. ACTUAL: registration imports live in `src/ui_routes.py` (lines 73-76); `job_hunt_ui.py` has no registration code (thin shim post LT-01). → FIX: point Phase 5 registration to `src/ui_routes.py`.
- [MED — verified] "Cross-cutting Reference Files" row says `src/job_hunt_ui.py` is where routes are added/changed. ACTUAL: routing is in `src/ui_routes.py`. → FIX: change row to `src/ui_routes.py`; note `job_hunt_ui.py` is a thin entry point.
- [MED — likely, verify text] "Current status" block still names Saved Searches / Daily Digest as active backlog, but D1-D6 are complete → FIX: update to open items (Gap Coach, exports, etc.).
- [HIGH — needs verify] P1-4 file table reportedly says delete `src/job_hunt_paste_fetch.py`, but module still exists → verify exact wording before editing.

## PROJECT_CONTEXT.md
- [LOW — verified] Duplicated `## Module Responsibilities` heading (lines 269 & 271) → FIX: remove one.
- [MED — verified] Module Responsibilities omits the UI split (ui_routes/ui_handlers/ui_render/ui_state/ui_utils) and source adapters/registry → FIX: add current-architecture subsection.
- [MED — likely] "Current Implementation Baseline" still lists saved searches / daily digest as remaining work (done) and source bullet omits Adzuna/LinkedIn → FIX: update to truly-pending items; list Reed+Adzuna+LinkedIn enabled.

## README.md
- [MED — verified] line 8 says only "Reed and Adzuna currently enabled" → FIX: add LinkedIn (wired & enabled).
- [MED — verified] line 34 route summary uses Reed-specific `GET /search/reed/more` → FIX: use generic `GET /search/{source}/more`.
- [LOW — verified] route summary missing `GET /job/{id}/explain` and `GET /job/{id}/evaluate-form` → FIX: add them.

## SESSION_HANDOFF.md (point-in-time doc — low edit priority)
- [INFO] Outstanding items list now-completed work (source_id check, NULL semantics, LinkedIn row) — these were done 2026-06-30; PROJECT_TODO already reflects it. Editing a dated handoff is optional.
- [DISMISSED] "/search/reed/more shim" claim — the generic `/search/{source}/more` regex matches `reed`, so the shim path still resolves; statement is fine.

## docs/ spec set (batch 3)
### docs/product_spec.md — FIXED
- [MED — verified, FIXED] line 22 said "LinkedIn is not enabled" → now lists Reed/Adzuna/LinkedIn enabled.
- [MED — verified, FIXED] line 63 backlog "LinkedIn source adapter" → marked shipped.
- [MED — open] Decision/contract rows omit thresholds (apply≥80, review≥65, blocker→skip, critical-risk gates). Could add.
- [LOW — open] CV/letter row doesn't state markdown/text-only (DOCX/PDF not implemented).
### docs/data_contract.md
- [DISMISSED] "skills_score collapses required/preferred" HIGH — FALSE. Model `ScoreBreakdown` (job_hunt_models.py:182-187) uses a single combined `skills_score`; doc is correct. (codex biased by my weight-breakdown seed.)
- [NEEDS SOURCE VERIFY] skills scoring "proportional + bonus" rule (lines 122-124) — may match job_hunt_scoring.py; do NOT edit without reading scorer.
- [LOW — likely] example `location_score: {value: 12}` (line 224) exceeds location weight 10 — probable example typo.
- [MED — open] status "Proposed" + URL/manual-text framing predates current enabled sources; thresholds not in Decision Contract.
### docs/architecture_guardrails.md
- [MED — open] status "pre-implementation guardrail note" stale; Guardrail 3 source-scope wording predates 3 enabled sources; missing UI-split boundary guardrail.
### docs/tailoring_spec.md — not reached (codex timeout)

## docs/ spec set (batch 4)
### docs/tailoring_spec.md
- [HIGH — VERIFIED REAL, NEEDS DECISION] Spec says `achievements` are in-scope tailoring evidence ("added 2026-06-16", lines 40-41, 78). ACTUAL: `src/job_hunt_tailoring.py` has NO `achievement` reference; `select_relevant_evidence()` does required→preferred→years_experience only. → DECISION: implement achievements evidence, OR correct spec to mark it not-implemented. NOT auto-edited.
- [LOW — verified, FIXED] line 57 `output/tailured_cvs/` typo → `tailored_cvs/`.
### docs/ui_scope.md — FIXED
- [MED — verified, FIXED] line 14 "Reed is the enabled source / Adzuna+LinkedIn unavailable" → all three live.
- [MED — verified, FIXED] line 59 backlog "Adzuna and LinkedIn source adapters" → marked shipped.
- [LOW — open] line 18 "Reed supports a more results path" — all sources now support /more.
### docs/user_flow.md, development_rules.md — not reached (codex timeout)

## docs/ spec set (batch 5) — all FIXED
- user_flow.md: LinkedIn "not enabled"→live (2 spots); reed/more→generic. FIXED.
- development_sequence.md: cover-letter listed deferred → marked shipped (GAP-G). FIXED.
- development_rules.md: `job_hunt_` naming rule contradicted by ui_*.py split → added LT-01 exception note. FIXED.
- dev-handoff-prompt.md: obsolete (pre-split god-module description) → added SUPERSEDED banner. FIXED.
- product-feature-research-2026-06.md: research doc, low code-accuracy relevance — SKIPPED.

## docs/tasks chunk 1
- gap-c-source-feature-flag-design.md: STATUS said LinkedIn pending + ENABLED_SOURCES=[Reed,Adzuna] → FIXED (LinkedIn live; list updated).
- gap-d-field-provenance-design.md: "Status: Ready to build" → FIXED to ✅ Implemented.
- gap-b / gap-e / gap-h / gap-j: STATUS OK (gap-j correctly still designed-only).

## docs/tasks chunks 2-5 (FIXED unless noted)
- cv-tailoring-brief.md: overclaims achievements implemented — HELD for achievements decision (see below).
- ats-score / cover-letter-spec / source-quality-gating / lt-01 / mt-02 / oq-2 / gap-b/e/h/j / pl-01 / job-001 / f1-ats-match-rate / bookmark-evaluate / skills-scoring(POC) / public-web-extraction(POC): STATUS OK.
- gap-c, gap-d: FIXED (status stale).
- url-ingestion-design.md + job-007 brief: FIXED (added "since implemented" pointers).
- pl-02, pl-03, pl-04, pl-05, reed-search-first-story-breakdown: FIXED (draft→shipped).
- job-002-reed-orchestrator: FIXED (draft→shipped).
- ui-paste-url-prefill-brief: FIXED (ready→implemented).
- backlog-01-daily-digest-HANDOVER: FIXED ("no code yet"→SHIPPED banner).
- F1_v2_recheck_design: DISMISSED false positive (route `/job/{id}/ats-recheck` exists; doc correct).
- outcomes-analytics-brief-draft: DISMISSED false positive (outcomes model/storage IS shipped; only analytics deferred).
- job_browser_enrichment_poc / browse-sh-feasibility: POC docs, left as-is (minor: stale old workspace path in test cmds — low).

## ⚠️ KEY OPEN ITEM — needs your decision
- **Tailoring "achievements" evidence**: `tailoring_spec.md` (lines 40-41, 78) and `cv-tailoring-brief.md` say achievements ARE an implemented tailoring-evidence source ("added 2026-06-16"), but `src/job_hunt_tailoring.py` has NO `achievement` handling — `select_relevant_evidence()` does required→preferred→years_experience only. EITHER implement achievements in the scorer, OR correct both specs to mark it not-implemented. → ✅ RESOLVED 2026-06-30: implemented in `select_relevant_evidence()` (via codex-builder) + test added (17 pass); specs now accurate.

## Summary (FINAL)
- Core docs (7): reviewed; ~9 real issues fixed; 3 HIGH false positives dismissed (bad initial route seed).
- docs/ specs (11): reviewed; product_spec/ui_scope/user_flow/dev-handoff/development_rules/development_sequence/tailoring_spec typo all FIXED; data_contract scoring HIGH dismissed (false); achievements gap held.
- docs/tasks (35): reviewed; ~10 status-staleness fixes applied; 2 false positives dismissed; POC/brief docs left as-is.
- Method note: codex-builder timed out on report-back nearly every call; write-to-file salvaged output. False positives came from incomplete ground-truth seeds — every finding was source-verified before editing.
- Batch 1 (function_list, INDEX): 3 HIGH dismissed as false positives (bad seed route list); 1 MED + 1 LOW open.
- Batch 2 (PROJECT_TODO, build_order): 2 HIGH + 2 MED + 1 LOW verified real; 1 HIGH needs text verify.
- Note: corrected route list (added GET / and GET /job/{id}) eliminated the false positives.
