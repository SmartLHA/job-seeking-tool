# Product Specification

## Status

**Updated: 2026-06-16** — Reflects implementation state after UI v4 design (Claude deliverable, 2026-06-15).
Prior update was 2026-05-02; stale items corrected per `GAP_ANALYSIS_S_HAND.md` (2026-05-20).

---

## Working Product Description

A local-first AI job search decision-support and application-preparation product for the UK market.

## Core Goals

- Ingest jobs (API + manual text)
- Structure job data
- Score job fit
- Decide Apply / Review / Skip
- Generate truthful tailored CVs and cover letters
- Track outcomes over time

## Non-Goals

- Mass auto-apply
- Browser automation
- Background account interaction
- Fabricated candidate claims
- Raw application-volume optimization

## Product Principles

- Deterministic logic first
- Explainability
- Local-first privacy
- Truthful output
- Modular implementation
- Small testable steps

---

## Implementation State (as of 2026-06-16)

### ✅ Implemented and working

| Feature | Notes |
|---------|-------|
| Candidate profile loading/saving | `job_hunt_profile.py` |
| Master CV loading/saving | |
| Deterministic scoring (6-component) | `job_hunt_scoring.py`, weights in `job_hunt_config.py` |
| Apply / Review / Skip decisioning | `job_hunt_decision.py` |
| Evaluation flow (score + decision compose) | `job_hunt_evaluation.py` |
| Local state storage (4 separated layers) | `raw_inputs/`, `reviewed_jobs/`, `analyses/`, `outcomes/` |
| JSON/CSV report export | `job_hunt_reporting.py` |
| Outcomes tracking with state machine | `job_hunt_outcomes.py` — enforces transition rules |
| CLI | `python3 src/job_hunt_main.py` |
| Browser UI (search-first) | `python3 src/job_hunt_ui.py` — port 8765 |
| Reed search → prefill → field review → evaluate | Full pipeline wired in UI and orchestrator |
| CV tailoring (MVP) | `job_hunt_tailoring.py` — deterministic, markdown output |
| Tailoring truth validation | `validate_tailored_cv()` — real, rejects unsupported claims |
| URL/text prefill | `POST /prefill` → `parse_job_from_url` / `parse_job_from_text` |
| Reed API client | `job_sources/reed_client.py` — wired to orchestrator |
| Adzuna API normaliser | `job_sources/adzuna_client.py` + `normalize_adzuna` — exists, NOT wired to orchestrator |
| Cover letter generation | `job_hunt_cover_letter.py` + `tests/test_cover_letter.py` — module complete, no UI path |
| ATS scorer | `job_hunt_ats_scorer.py` + `tests/test_ats_scorer.py` — exists, NOT integrated into evaluation flow |
| Deduplication | `job_sources/dedup.py` — title/company/Jaccard cross-source dedup |
| Public web extraction POC | `poc/public_web_extraction/` — research only, not production |

### ⚠️ Module exists but not wired into product flow

| Feature | Gap | Reference |
|---------|-----|-----------|
| Cover letter → UI/orchestrator | Module works; no route, no UI action | GAP-G |
| Tailored CV → UI action | Backend works; UI still shows "not implemented" | GAP-F |
| ATS scorer → evaluation | Score computed but not surfaced in `JobAnalysis` or UI | GAP_ANALYSIS §7 |
| Adzuna source | Normaliser exists; no fetch client wired; no orchestrator call | GAP-C/I |
| URL ingestion safety | Two competing implementations; canonical path not decided | JOB-009 |
| Source quality gating | `source_quality` computed in normaliser; not used in decision path | GAP_ANALYSIS §2 |

### ❌ Not yet implemented (new UI requires these)

| Feature | Gap | Priority |
|---------|-----|----------|
| Tracker board aggregate read-model | No `/board` or `/jobs` aggregate route | GAP-H — High |
| Outcome status reconciliation | UI stages ≠ backend enum | GAP-A — High |
| Gap Coach screen | Entirely new module + route | GAP-J — Medium |
| Save-without-evaluate (bookmark) | No `POST /jobs/save` endpoint | GAP-A/H |
| Decision override persistence | Engine decision only; no user override stored | GAP-E |
| Cover letter route | `POST /cover-letter` does not exist | GAP-G |
| Tailoring route | `POST /tailor` does not exist | GAP-F |
| Per-field `found` provenance | Parsing returns values only; null = not-found | GAP-D |
| Profile skill metadata (level/years) | `skills` is `list[str]` only | GAP-B |
| `get_enabled_sources()` flag | No feature flag for Adzuna/LinkedIn | GAP-I |

---

## MVP Workflow (implemented)

```
1. Load candidate profile
2. Search Reed (primary) or paste text / URL (fallback)
3. Select Reed result → prefill OR submit text/URL → prefill
4. User reviews + edits structured fields
5. User clicks Evaluate (explicit — no auto-submit)
6. Deterministic scoring + decision runs
7. Result stored: raw_input / reviewed_job / analysis (separate)
8. User sees score, decision, breakdown, blockers, strengths, gaps
9. (Optional) Tailor CV — apply decisions auto-eligible; review requires manual selection
10. (Optional) Generate cover letter
11. Record outcome
```

---

## New UI Scope (v4 design, 2026-06-15)

The `Claude deliverable/` folder contains the v4 HTML prototype and backend binding docs.
This represents the target UI, materially beyond the minimal MVP shell.

**6 navigation screens:**
1. Find Jobs — search + filter + source toggles + processing pipeline overlay
2. Evaluate — review queue + full job detail with score dial + 6-component breakdown
3. Add Job — URL/text prefill → field review → explicit evaluate gate
4. Tracker — Kanban board (Saved · Applied · Screening · Interview · Offer · Rejected)
5. Gap Coach — aggregated skill gaps and strengths across all analyses
6. My Profile — CV upload, candidate facts, skills, achievements, certifications

**2 full-screen workspaces:**
- Tailor CV — evidence points panel + tailored CV preview
- Cover Letter — why-company textarea + tone/length controls + letter preview

Binding between each screen and the backend is documented in:
`Claude deliverable/docs/ui_structure_v4.md` (authoritative)
`Claude deliverable/docs/function_list_v4.md` (function signatures + gaps)

---

## Key Data Contract Notes

- `match_score` — 0–100 integer
- `confidence` — categorical `"low"|"medium"|"high"` (NOT a float or percentage)
- `decision` — `"apply"|"review"|"skip"`
- `OutcomeStatus` — `not_applied|applied|interview|rejected|offer|withdrawn`
  - Enforces a state machine; not all transitions are valid
- `ScoreBreakdown` — exactly 6 fixed components: skills, experience, location, salary, domain, work_mode
- Source quality (`source_quality_score`) will gate decisions: `<40` = blocker, `40–70` = force Review

---

## Decisions Made (2026-06-16)

All open design questions resolved:

| Item | Decision |
|------|----------|
| GAP-A Tracker statuses | Remap UI to 6 real `OutcomeStatus` values; drop Saved/Screening; add Withdrawn; constrain DnD |
| JOB-009 URL fetcher | `parse_job_from_url` canonical; harden to safety spec; delete `job_hunt_paste_fetch.py` |
| GAP-F Tailor CV model | Enrich backend — `tailor_cv()` returns `{summary, promoted[], matched[], missing[]}` |
| GAP-G Cover letter controls | Extend `generate_cover_letter_text()` with `tone`, `length`, `points` parameters |
| GAP-B Profile skills | Add `Skill` dataclass with `level`, `years`, `evidence_type` to `CandidateProfile` |
| Source quality gating | `<40` = blocker (skip); `40–70` = risk flag (force Review); thresholds in config |
| ATS scorer | Integrate into `evaluate_reviewed_job()`; add `ats_score` to `JobAnalysis`; surface in UI |

## Open Questions

None — all design decisions resolved as of 2026-06-16.

---

## Resolved

| Item | Resolution |
|------|-----------|
| Product naming | ✅ "Job Seeking Tool" |
| Primary target user | ✅ IT/BA background, UK market |
| Reed orchestrator wiring | ✅ `run_reed_evaluation_flow()` wired (JOB-002, 2026-05-13) |
| Tailoring truth validation | ✅ Real validator implemented (JOB-001, 2026-05-13) |
| Cover letter tests | ✅ `tests/test_cover_letter.py` exists |
| Reed viewer canon | ✅ `viewer/reed_jobs_v4.html` only (JOB-006, 2026-05-20) |
| data_contract.md | ✅ Exists (`docs/data_contract.md`) |
| tailoring_spec.md | ✅ Exists (`docs/tailoring_spec.md`) |
| Scoring philosophy | ✅ Unknown = neutral credit, not penalty; confidence is data-completeness only |
| Storage strategy | ✅ Separate folders: raw_inputs/, reviewed_jobs/, analyses/, outcomes/ |
| Tailoring timing | ✅ apply = auto-eligible; review = manual selection required |
| Auto-submit guard | ✅ User must click Evaluate; no auto-submit at any point in flow |

---

## Key Files

```
src/
  job_hunt_models.py           # All dataclasses + enums
  job_hunt_config.py           # Scoring weights, decision thresholds, policies
  job_hunt_profile.py          # Profile load/save/validate
  job_hunt_reviewed_input.py   # Field-review contract → JobPosting
  job_hunt_scoring.py          # 6-component deterministic scoring
  job_hunt_decision.py         # Apply/Review/Skip rules
  job_hunt_evaluation.py       # Compose scoring + decision → JobAnalysis
  job_hunt_storage.py          # Separated state persistence
  job_hunt_reporting.py        # JSON/CSV export
  job_hunt_outcomes.py         # Outcome state machine
  job_hunt_orchestrator.py     # Pipeline coordination (Reed wired)
  job_hunt_tailoring.py        # CV tailoring + truth validation
  job_hunt_cover_letter.py     # Cover letter generation (no route yet)
  job_hunt_ats_scorer.py       # ATS scoring (not integrated)
  job_hunt_ui.py               # Main local UI server (port 8765)
  job_sources/
    reed_client.py             # Reed API fetch (wired)
    adzuna_client.py           # Adzuna normaliser (not wired)
    normalize.py               # Reed + Adzuna normalisation
    dedup.py                   # Cross-source deduplication

Claude deliverable/
  Job Seeking Tool.html        # v4 UI prototype entry point
  docs/ui_structure_v4.md      # Screen → backend binding (authoritative)
  docs/function_list_v4.md     # Real function signatures + gap catalogue

docs/
  ui_scope.md                  # UI screen definitions (v3)
  architecture_guardrails.md   # Module boundary rules
  data_contract.md             # Data shapes
  tailoring_spec.md            # Tailoring rules
  development_rules.md         # Build discipline
  development_sequence.md      # Phase build order

tests/                         # 180+ tests
```
