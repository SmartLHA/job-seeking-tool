# User Flow — Job Seeking Portal

**Created: 2026-06-26.** Grounded in implemented routes (`docs/function_list.md`, `docs/ui_scope.md`). Local-first copilot — never auto-applies; the user opens and submits every application themselves.

Covers the full flow: happy path plus all branches (manual entry, batch queue, review queue, daily digest, decision overrides, error/empty states).

---

## Actors & entry points

- **Single user** (the candidate). No multi-user/auth.
- Entry points: **Profile setup** (first run), **Search** (main journey), **Manual add** (paste/URL), **Daily Digest** (returning user), **Board/Tracker** (manage pipeline).

---

## Stage 0 — Onboarding / Profile (first run)

1. Open app → **My Profile** (`GET /profile`).
2. Upload / paste master CV → `POST /profile/parse-cv` extracts structured skills (`Skill: name, level, years, evidence_type`).
3. Review parsed skills; edit/add manually. Missing data stays **unknown** (never invented).
4. Save → `POST /profile/save` (local storage, explicit save feedback).
5. Optional toggles: enable **Daily Digest scheduler** and **Gemini LLM worker** (worker also needs a Gemini key).
   - Branch — no CV yet: user can still search, but evaluation/keyword-match return limited results until a profile exists.

---

## Stage 1 — Discover a job

Three ways in:

**A. Search a source (main path)**
1. Search form → `GET /search/{source}` (Reed, Adzuna, LinkedIn all live).
2. Browse results; all sources support "more" → `GET /search/{source}/more`. If that requested page is entirely hidden/excluded, the local server may check up to three further source pages before returning the next visible cards; main and Other-results buckets stay separate.
3. Select a result → `POST /select/{source}` — preserves a source snapshot, fetches full Reed detail, extracts skills.
   - Branch — empty results: show empty state; user adjusts query or adds job manually.

**B. Manual add (paste or URL)**
1. Paste text or URL → `POST /prefill` populates the review form.
2. URL parsing is host-allowlisted, robots-aware, SSRF-protected, fail-closed.
   - Branch — blocked/unsafe URL: fail closed with message; user pastes text instead.
3. Bulk (Add & Evaluate → Bulk tab): paste up to 15 URLs (one per line) and/or JD texts (separated by a `---` line); each item is saved and scored one at a time; per-row failures are shown and never stop the run; Stop ends the run; "Open Review queue" appears for saved jobs whose decision is review.

**C. Daily Digest (returning user)** — see Stage 6.

---

## Stage 2 — Review extracted fields

1. Review prefilled fields; provenance tags mark **auto-filled vs not-found**.
2. Correct anything; missing requirements remain unclaimed.
3. Confirm **Save & evaluate** → `POST /job-submit` validates, persists, and scores the job immediately.
   - Branch — batch evaluation remains for selected search results; it uses the same evaluation contract (Stage 4B).

---

## Stage 3 — Evaluate (explicit, deterministic)

1. The user explicitly triggers evaluation: guided manual intake uses `POST /job-submit`; Advanced Review uses `POST /evaluate`. Both use the same persistence and scoring pipeline (nothing auto-evaluates).
2. Deterministic scoring: 7 weights → required skills 35, preferred 5, experience 20, location/salary/domain/work-mode 10 each → `match_score` 0–100.
3. Source-quality gate + ATS readiness + F1 keyword coverage computed.
4. Land on **Job Detail** → `GET /job/<id>`.

---

## Stage 4 — Inspect result & decide

**A. Single job detail** (`GET /job/<id>`) shows:
- Match score, categorical **confidence** (low/med/high — never a probability).
- Source-quality state, ATS readiness, F1 keyword coverage (present/missing required & preferred, stuffing warning — **advisory only**).
- Strengths, gaps, blockers, risk flags, decision reasoning.
- System decision: **Apply / Review / Skip**.

User actions:
- Persist an override → `POST /job/<id>/decision` (effective-decision handling).
- Optional Gemini explanation / CV review → `POST /job/<id>/ai-review-cv`, `GET /job/<id>/explain` (advisory, never changes score/decision).
- Add missing skills to profile → `POST /job/<id>/add-gap-skills`.

**B. Batch / Review queue**
1. Stage several jobs → `POST /jobs/batch-evaluate` (handler-enforced max).
2. Inspect via `GET /review-queue`; open each (`GET /job/<id>?embed=1`).

Decision branches:
- **Skip** → tailoring/cover-letter blocked; job parked.
- **Review** → Tailor CV requires an explicit manual selection; Cover Letter remains available when its company rationale is supplied.
- **Apply** → proceed to Stage 5.

---

## Stage 5 — Prepare materials & apply

1. **Tailor CV** → `POST /tailor` → summary, promoted evidence, matched/missing keywords, markdown. Truth-bounded.
2. **Re-check ATS** against tailored CV → `POST /job/<id>/ats-recheck` → `was X% → now Y%`.
3. **Cover letter** → `POST /cover-letter` (requires `why_company_text`; supported tone/length; grounded points only).
4. **View original posting / Apply** — when `source_ref` is an HTTP(S) URL. **User opens it and submits manually.** Portal never submits.
   - Gate: tailor/letter are decision-gated; Skip blocks them.
5. **Download package** -> `GET /job/<id>/export.zip` -> one zip with `cv.md`, `cover_letter.txt`, `analysis.md`, `job.json` and a `README.txt` listing anything not generated yet. Read-only, not decision-gated (works for Skip jobs too); no `.env`, raw inputs or profile personal fields.

---

## Stage 6 — Daily Digest (returning-user loop)

1. Save a search → `POST /saved-searches` (toggle on/off, delete).
2. Scheduler daemon runs once-daily → indexes new matching jobs (LLM-free pipeline). Manual run → `POST /saved-searches/{id}/run-now`.
3. Sidebar unseen badge → `GET /digest/count`.
4. Open feed → `GET /digest` (filterable); mark seen → `POST /digest/mark-seen`.
5. High-match jobs enriched by paced Gemini worker → `POST /digest/run-llm-batch`, status `GET /digest/llm-queue` (429 backoff, daily cap).
6. **Re-evaluate seen jobs** → `POST /digest/reevaluate` re-scores indexed rows vs current profile/threshold; resurfaces ones that now qualify (digest is otherwise new-only).
7. Pick a job from digest → jump into Stage 4 (Job Detail).

---

## Stage 7 — Track outcome

1. Bookmark without evaluating → `POST /jobs/save` (creates `not_applied`).
2. Board view → `GET /board/view` (`GET /board` data): read-only columns, statistics, and linked job cards. It does not expose drag-and-drop or inline status changes.
3. Open a job from its card and record outcome on Job Detail → `POST /outcome` enforces the state machine. A confirmed `POST /outcome/reset` is available only to recover a mistaken rejected/withdrawn status; the old outcome remains in history.
   - Statuses: **Not Applied → Applied → Interview → Offer / Rejected / Withdrawn** (server-provided transitions only).

---

## Cross-cutting rules (visible in UI throughout)

- Local storage; explicit user approval before any evaluation or generated material.
- Truthful evidence only; missing data stays unknown.
- No auto-apply, credential storage, stealth automation, or mass applications.
- LLM calls are optional, manual, advisory — cannot alter scores or decisions.
- Confidence is categorical, never a probability.

---

## Gaps / not yet in flow (backlog)

- **Gap Coach** aggregate (cross-job strengths/gaps) — backlog.
- **LinkedIn** source adapter — shipped & enabled (P5-2, 2026-06-28).
- **DOCX/PDF** application-package export — backlog.
- Synonym/alias keyword matching — backlog.
