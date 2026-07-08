# Product Specification

**Updated: 2026-07-02 (search triage UX).** Source code in `src/` is authoritative. This document describes the recovered split UI and F1 keyword-match implementation, not the earlier monolithic checkout.

## Product

A local-first UK job-search copilot that helps a candidate discover roles, review extracted data, make explainable Apply/Review/Skip decisions, prepare truthful application materials, and track outcomes. It is not an auto-apply tool.

## Principles

- Deterministic scoring, decisions, safety gates, persistence, and reporting.
- LLM calls are optional, manual, and advisory. They cannot alter scores or decisions.
- Local storage and explicit user approval before any evaluation or generated material.
- Truthful CV/profile evidence only. Missing requirements remain unclaimed.
- The user opens and submits an application themselves.

## Implemented capabilities

| Area | Current behaviour |
|---|---|
| UI architecture | `job_hunt_ui.py` is a thin entry point over `ui_routes`, `ui_handlers`, `ui_render`, `ui_utils`, and `ui_state`. |
| Sources | Generic registry; Reed, Adzuna, and LinkedIn adapters are enabled (live). |
| Ingestion | Reed search/select/detail enrichment, manual paste/URL prefill, field-review provenance, safe canonical URL parsing. |
| Search triage | Results are triaged page-by-page: cards start unticked (tick = shortlist for evaluation only); per-card ✕ or "Hide unticked on this page" marks jobs not-interested — persisted and filtered from all future searches, with a 10s undo and a "Hidden jobs" overlay to unhide; "Next page" replaces the list (forward-only) and shortlisted jobs survive page changes. |
| Evaluation | Seven weights: required skills 35, preferred skills 5, experience 20, location/salary/domain/work mode 10 each. Confidence is `low`/`medium`/`high`. |
| Quality and ATS | Source-quality gate, ATS readiness score, and F1 per-job keyword match with missing-keyword and stuffing signals. F1 v2 adds a re-check (`POST /job/<id>/ats-recheck`) that re-scores against the latest tailored CV and shows `was X% → now Y%`. F1 is advisory only. |
| Decisions | Apply/Review/Skip with persisted user override and effective-decision handling. |
| CV and letter | Truth-validated `POST /tailor` and grounded `POST /cover-letter`, exposed from the job-detail experience. |
| Board and outcome | SQLite jobs index, JSON board, board HTML view, saved-job path, legal outcome transitions, and review queue. A bookmarked (saved-but-unevaluated) job can be reloaded into the Evaluate form via `GET /job/<id>/evaluate-form` and scored in place; evaluated jobs offer a Re-evaluate link to the same route. The job page's outcome form offers only legal next statuses, shows an allowed-next / final-status hint, and gives inline success/error feedback in the card (2026-07-07). |
| Profile | Structured `Skill(name, level, years, evidence_type)`, CV parsing, and local profile save. |
| AI analysis | Manual Gemini explanation and CV-review actions, separate from deterministic policy. |

## Workflow

```text
Search configured source or add a job
→ triage results page-by-page (shortlist ✓ / hide ✕, hidden jobs never return)
→ select/review extracted fields
→ explicitly evaluate
→ inspect score, confidence, ATS/keyword signals, evidence, gaps, and decision
→ optionally tailor CV / generate cover letter
→ open original posting and submit manually
→ record outcome and review board/history
```

## Contracts

- `match_score`: 0–100.
- `confidence`: categorical `low|medium|high`, never a probability.
- `ScoreBreakdown`: six displayed buckets, with skills internally split into required and preferred weights.
- F1 `keyword_match_rate`: 0–100 coverage or `null` if no CV/keywords; never used to decide Apply/Review/Skip.
- Tracker statuses: `not_applied|applied|interview|offer|rejected|withdrawn`.
- `source_ref`: keeps the source/advert reference. HTTP(S) URLs render as **View original posting / Apply**.

## Non-goals

- Auto-submitting applications, browser automation, credential storage, stealth behaviour, or mass applications.
- Treating mock prototype data as real candidate/job data.
- Fabricating candidate claims.

## Backlog

- Gap Coach aggregate.
- *(Daily Digest **complete** 2026-06-24, D1–D6: saved searches, schema/dedup, deterministic pipeline + Run-now, filterable `/digest` feed with sidebar unseen badge, automatic daily scheduler daemon, and a paced rate-limited Gemini worker that enriches high-match jobs. Both daemons auto-start gated by the user's My Profile toggles; the worker also needs a Gemini key. **OQ-2 (2026-06-26):** a manual "Re-evaluate all" action re-scores the indexed digest jobs against the current profile/threshold and resurfaces the ones that now qualify — the digest is otherwise new-only by design.)*
- *(Source adapters shipped: Adzuna 2026-06-24 — P5-1; LinkedIn 2026-06-28 — P5-2. Both enabled.)*
- DOCX/PDF application-package export.
- Controlled synonym/alias support for keyword matching.
