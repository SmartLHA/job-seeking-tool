# UI Scope

**Source-verified after recovery merge: 2026-06-22.** The product UI is the recovered split architecture: `ui_routes`, `ui_handlers`, `ui_render`, `ui_utils`, `ui_state`, and source adapters. `src/job_hunt_ui.py` is only the entry-point shim.

## Current experience

The local-first workflow is:

```text
Search a configured source or add a job → review fields → explicitly evaluate
→ inspect the explainable result → prepare material or record outcome → submit manually
```

Reed, Adzuna, and LinkedIn are the enabled sources (all live via the generic source registry). Further sources remain unavailable until their complete adapters are implemented and tested.

### Search, review, and batch queue

- Search uses `GET /search/{source}`; Reed supports a "more" results path.
- Result selection uses `POST /select/{source}`, preserves a source snapshot, and fetches full Reed detail when available before extracting skills.
- Users may stage selected results and call `POST /jobs/batch-evaluate` (maximum enforced by the handler), then inspect them through `GET /review-queue`.
- Manual input uses `POST /prefill` and `POST /job-submit`. URL parsing remains host-allowlisted, robots-aware, SSRF-protected, and fail-closed.
- Parsed values carry field-review provenance. Missing data remains unknown rather than invented.

### Evaluate and job detail

- Job detail is `GET /job/<id>`; `?embed=1` is used by the review queue.
- It shows match score, categorical confidence, source-quality state, ATS readiness, F1 ATS keyword coverage, strengths, gaps, blockers, risk flags, and decision reasoning.
- F1 keyword matching is advisory only. It reports present/missing required and preferred keywords and warns about repeated-keyword stuffing; it does not affect decisions.
- Users can persist an Apply/Review/Skip override through `POST /job/<id>/decision`.
- When `source_ref` is an HTTP(S) advert URL, the page renders **View original posting / Apply**. The product never submits an application itself.
- Optional Gemini analysis is manually triggered through `POST /job/<id>/ai-review-cv` / the job explanation flow, and is separate from deterministic scoring.

### Tailoring, cover letters, profile, and outcomes

- The job page exposes decision-gated Tailor CV and Cover Letter actions, backed by `POST /tailor` and `POST /cover-letter`.
- Tailoring returns summary, promoted evidence, matched keywords, missing keywords, and markdown. Review decisions require manual selection; Skip is blocked.
- Cover letters require `why_company_text`, accept only supported tone/length values, and use grounded optional points.
- Profile editing supports structured skills, master-CV parsing, and explicit save feedback.
- `POST /outcome` enforces the local outcome state machine.

### Board and tracker

- `GET /board` returns SQLite-backed columns, statistics, cards, and allowed transitions.
- `GET /board/view` renders the board UI; `POST /jobs/save` creates a `not_applied` bookmark.
- The only tracker statuses are `Not Applied`, `Applied`, `Interview`, `Offer`, `Rejected`, and `Withdrawn`. Visual transitions must follow the server-provided allowed transitions.

## Visual and safety rules

- Use the established paper/ink layout, clear decision colours, and compact metadata treatment.
- Keep privacy, local storage, evidence boundaries, and manual submission visible in the UI.
- Never turn categorical confidence into a probability.
- Never treat sample/prototype data as live candidate or job data.
- No auto-apply, credential storage, stealth automation, or mass-application behaviour.

## Backlog

- Gap Coach, deterministic aggregation over stored analyses.
- Daily digest and saved searches.
- *(Adzuna and LinkedIn source adapters — shipped & enabled, 2026-06.)*
- DOCX/PDF application-package export.
