# Product Specification

## Status

**Updated: 2026-06-18** — LLM backend switched to Google Gemini; AI Analysis redesigned with 3-section structured output and reasoning model chain; multi-select search results; per-page timestamps; dev tooling. 291 tests green.
Prior update: 2026-06-17 (UX hardening, source registry).

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

## Implementation State (as of 2026-06-18)

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
| CV tailoring (MVP) | `job_hunt_tailoring.py` — `TailoredCVResult` dataclass; `{summary, promoted[], matched[], missing[], markdown}` |
| Tailoring truth validation | `validate_tailored_cv()` — real, rejects unsupported claims |
| Tailoring route | `POST /tailor` with decision gate (apply/review only) |
| URL/text prefill | `POST /prefill` → `parse_job_from_url` / `parse_job_from_text` |
| Reed API client | `job_sources/reed_client.py` — wired to orchestrator; detail fetch for full description |
| Adzuna API normaliser | `job_sources/adzuna_client.py` + `normalize_adzuna` — exists, NOT wired to registry yet |
| Cover letter generation | `job_hunt_cover_letter.py` — `tone`/`length`/`points` params; `POST /cover-letter` route with skip gate |
| ATS scorer | `job_hunt_ats_scorer.py` — wired into `evaluate_reviewed_job()`; `ats_score` on `JobAnalysis`; surfaced in UI |
| ATS keyword match (F1) | `job_hunt_keyword_match.py` — per-job keyword coverage (CV vs job required/preferred skills) with present/missing breakdown + anti-stuffing signal; `keyword_match_rate` on `JobAnalysis`; shown on job page; **advisory/display only** |
| Deduplication | `job_sources/dedup.py` — title/company/Jaccard cross-source dedup |
| Board aggregate + SQLite index | `job_hunt_index.py`; `GET /board` (JSON, 6 columns); `GET /board/view` (HTML); `POST /jobs/save` |
| Decision override persistence | `user_decision`/`user_decision_note` on `JobAnalysis`; `effective_decision()`; `POST /job/{id}/decision` |
| Skill dataclass | `Skill(name, level?, years?, evidence_type?)`; backward-compat flat-list loader |
| Field provenance (null contract) | Parsing returns `None`/`[]`/`"unknown"` for missing; field-review badges in Add Job UI |
| Source quality gating | `source_quality_score` on `JobPosting`; skip/review thresholds active in decision path |
| URL ingestion hardening | 8 security controls in `parse_job_from_url()`; `paste_fetch.py` zeroed |
| `get_enabled_sources()` flag | `ENABLED_SOURCES` in config; `GET /sources` route; Reed enabled; Adzuna/LinkedIn show "Coming soon" |
| Source registry | `job_sources/source_registry.py` — `JobSource` frozen dataclass; `register()`/`get_source()`/`all_sources()`; routes generic `/search/{source}` and `/select/{source}` |
| CV status indicator on Profile page | Green/amber/red strip: shows char count, file path, or "No CV on file" warning |
| Profile save flash confirmation | Save redirects with `?flash=` showing CV char count confirmation |
| Tailor / cover-letter actionable errors | Distinguishes missing-ref vs unreadable-file; includes fix instruction pointing to Profile page |
| Cover letter fails fast on missing CV | No longer silently proceeds with empty CV; returns 422 with fix hint |
| Tailor result match stats | JS result panel shows ✓ promoted / ✓ matched / ⚠ missing counts |
| Auto-save error surface | `auto_save_error` returned in parse-cv JSON; shown in browser status bar on failure |
| AI Analysis — structured 3-section output | Job detail page: "Run Analysis" button; result rendered as Fit Assessment / Key Risk / Recommended Action in labelled sections; DOM-safe |
| AI Analysis — reasoning model chain | `gemini-3-flash-preview` (thinking budget 8k) → `gemini-2.5-flash` (thinking 8k) → `gemini-3.1-flash-lite`; fallback on 404 or 429 |
| Google Gemini LLM backend | `job_hunt_llm.py` uses Gemini REST API; no extra packages; `GOOGLE_API_KEY` env var; replaces Ollama |
| Skill extraction model chain | `gemini-3.1-flash-lite` (primary) → `gemini-2.5-flash-lite` (fallback on 404/429); keyword fallback when API unavailable |
| LLM CV skill extraction | `extract_cv_skills_with_llm()` in `job_hunt_llm.py`; free-text skill extraction from CV; keyword fallback when API unavailable |
| Multi-select search results | Reed results rendered as selectable cards; staging overlay for review; per-job "Evaluate" button; JS IIFE with XSS-safe DOM building |
| Per-page last-updated timestamps | `_PAGE_UPDATED` dict in `job_hunt_ui.py`; shown in sidebar footer and job detail page footer |
| Dev tooling | `dev.py` auto-reload watcher (polls src/ MD5 hashes); `restart.sh` quick-restart script |
| CV auto-save on upload | Parse CV uploads write directly to profile JSON without requiring Save button |
| Public web extraction POC | `poc/public_web_extraction/` — research only, not production |

### ⚠️ Module exists but not wired into product flow

| Feature | Gap | Reference |
|---------|-----|-----------|
| Adzuna source | Normaliser exists; registry pattern ready; needs `adzuna_source.py` adapter | P5-1 |

### ❌ Not yet implemented

| Feature | Gap | Priority |
|---------|-----|----------|
| Gap Coach screen | Entirely new module + route | GAP-J — Medium |
| Profile skill metadata (level/years) in UI | `Skill` dataclass done; UI columns not yet wired | GAP-B UI only |

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

## Decisions Made (2026-06-16 to 2026-06-18)

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

| LLM backend | Google Gemini REST API (no extra packages) — `GOOGLE_API_KEY` in `.env`; `gemini-3.1-flash-lite` default for extraction; reasoning chain for analysis |
| AI Analysis output format | Structured JSON `{fit, risk, action}` from Gemini; rendered as 3 labelled sections in UI — not free-form prose |
| Reasoning model for analysis | `gemini-3-flash-preview` primary; `gemini-2.5-flash` first fallback; `gemini-3.1-flash-lite` last resort; fallback on 404 **and** 429 |

## Open Questions

None — all design decisions resolved as of 2026-06-18.

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
| Source registry (GAP-C/I) | ✅ `source_registry.py` — `JobSource` frozen dataclass, generic routes `/search/{source}` and `/select/{source}`, Reed registered at bottom of `job_hunt_ui.py`; adding a source requires one new `*_source.py` file and one import (2026-06-17) |
| Required skills extraction | ✅ Reed detail API fetched before skill extraction — full `jobDescription` HTML, not 500-char preview (2026-06-17) |
| LLM backend | ✅ Google Gemini REST API — `GOOGLE_API_KEY` in `.env`; no extra packages needed (2026-06-18) |
| AI Analysis format | ✅ Structured `{fit, risk, action}` JSON from Gemini; 3-section UI with colour-coded labels (2026-06-18) |
| Reasoning model chain | ✅ `gemini-3-flash-preview` → `gemini-2.5-flash` → `gemini-3.1-flash-lite`; fallback on 404 and 429 (2026-06-18) |

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
    source_registry.py         # JobSource frozen dataclass + register/get_source/all_sources
    reed_client.py             # Reed API fetch (wired) + detail fetch for full description
    adzuna_client.py           # Adzuna normaliser (not wired to registry yet)
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

  job_hunt_llm.py              # Google Gemini LLM integration (skill extraction + job analysis with reasoning)

dev.py                         # Auto-reload dev watcher — restarts server on any src/*.py change
restart.sh                     # Quick kill-and-restart script for the server
tests/                         # 291 tests
```
