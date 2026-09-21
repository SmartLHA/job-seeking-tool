# Bookmark → Evaluate bridge

<!-- STATUS -->
> **Implementation status:** ✅ Implemented 2026-06-26
> **Divergences from spec:** none — slice shipped as designed; no new submit route needed (the Evaluate form already round-trips `job_id`).
> **Key functions:** `form_values_from_reviewed_job()`, `handle_evaluate_form()`
> **Routes:** `GET /job/<id>/evaluate-form`
<!-- /STATUS -->

## Problem

A job saved via `POST /jobs/save` (a "bookmark") stored a minimal `JobPosting` +
`not_applied` outcome + index row, but there was **no path to evaluate it later**.
`handle_evaluate` / `handle_job_submit` only build from an HTTP form via
`reviewed_job_payload_from_form`; neither loads a saved job by id. Bookmarked jobs
therefore dead-ended — the user had to re-enter the job to score it.

## Decision

Reload a saved job into the existing Evaluate form (prefilled), preserving its
`job_id`, for explicit user review before scoring. The user completes any fields
the bookmark lacked, then submits the existing `POST /evaluate` path, which updates
the same record in place. Headless one-click evaluate was **deliberately rejected**
— it violates the product's review-before-evaluate + truthful-missing-data principle
(bookmarks store `description_raw="No description provided."` and empty skills).

## Scope

- `form_values_from_reviewed_job(job)` (pure, `ui_utils.py`): maps a `JobPosting`
  back to Evaluate-form values; joins skill lists with newlines; sets `job_id` so
  re-submit updates in place; missing values stay blank.
- `GET /job/<id>/evaluate-form` → `handle_evaluate_form` (`ui_handlers.py`): loads
  the saved job (404 if missing), renders the home Evaluate tab prefilled with a
  review notice. Read-only (no side effects). Route registered **before** the
  generic `/job/` catch-all in `ui_routes.py`.
- Unevaluated job page (`ui_render.py`, `has_analysis=False` branch): replaced the
  "not evaluated yet" dead-end with a **"Review & evaluate this job →"** CTA.
- Already-scored job page (`has_analysis=True` action bar): added an optional
  **"↻ Re-evaluate"** link to the same prefill route (re-score against the current
  profile).

## Non-goals

- No auto/headless evaluate. No new submit route. No schema/API/model changes.

## Risks / residual

- The unevaluated CTA shows whenever `analysis is None`. For a bookmark that is
  exactly right; revisit the gate if other no-analysis states are introduced
  (e.g. a failed evaluation).
- Re-evaluating an already-scored job overwrites its prior `raw_inputs/` + analysis
  (in-place update) — pre-existing behaviour for same-id submits, surfaced here by
  the new Re-evaluate link. Acceptable: it is user-initiated; no eval history is kept.

## Tests

`tests/test_bookmark_evaluate.py` (7): helper mapping / `job_id` preserved / full
form shape with blanks; CTA present on unevaluated page; full
save → prefill (carries `job_id`) → evaluate → analysis under same id (no duplicate);
unknown id → 404; Re-evaluate link present on scored page.
