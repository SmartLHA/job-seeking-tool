# Product Specification

**Updated: 2026-06-22 after recovery merge.** Source code in `src/` is authoritative. This document describes the recovered split UI and F1 keyword-match implementation, not the earlier monolithic checkout.

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
| Sources | Generic registry; Reed adapter is enabled. Adzuna/LinkedIn are not enabled. |
| Ingestion | Reed search/select/detail enrichment, manual paste/URL prefill, field-review provenance, safe canonical URL parsing. |
| Evaluation | Seven weights: required skills 35, preferred skills 5, experience 20, location/salary/domain/work mode 10 each. Confidence is `low`/`medium`/`high`. |
| Quality and ATS | Source-quality gate, ATS readiness score, and F1 per-job keyword match with missing-keyword and stuffing signals. F1 v2 adds a re-check (`POST /job/<id>/ats-recheck`) that re-scores against the latest tailored CV and shows `was X% → now Y%`. F1 is advisory only. |
| Decisions | Apply/Review/Skip with persisted user override and effective-decision handling. |
| CV and letter | Truth-validated `POST /tailor` and grounded `POST /cover-letter`, exposed from the job-detail experience. |
| Board and outcome | SQLite jobs index, JSON board, board HTML view, saved-job path, legal outcome transitions, and review queue. |
| Profile | Structured `Skill(name, level, years, evidence_type)`, CV parsing, and local profile save. |
| AI analysis | Manual Gemini explanation and CV-review actions, separate from deterministic policy. |

## Workflow

```text
Search configured source or add a job
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
- Saved searches and daily digest.
- Adzuna/LinkedIn source adapters.
- DOCX/PDF application-package export.
- Controlled synonym/alias support for keyword matching.
