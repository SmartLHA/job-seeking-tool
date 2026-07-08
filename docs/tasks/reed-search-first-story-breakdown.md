# Reed Search First — Development Story Breakdown

**Status:** ✅ PL-01 through PL-05 shipped (all QA complete).
**Owner:** SilverHand
**Project:** Job Seeking Tool

## Confirmed Product Direction

The app first main page should become a Reed job-source search flow, not the manual Evaluate form.

Target journey:

```text
Open app → Search Reed → Select job → Review prefilled Evaluate form → User clicks Evaluate
```

Manual input / URL / paste must remain available as a fallback tab, but not as the primary journey.

## Confirmed Decisions

1. Reed is the only job source in this phase.
2. Later sources: Adzuna and LinkedIn.
3. Main page starts with search.
4. Search fields:
   - required/core: keywords, location
   - optional: salary, remote/hybrid, permanent/contract
5. Selecting a job pre-fills the Evaluate form.
6. User reviews before clicking Evaluate; no auto-evaluate on selection.
7. Do not directly embed or reuse `reed_jobs_v4.html`; rebuild inside the app style.
8. Keep manual input / URL / paste as fallback tab.
9. Capture as much Reed data as possible.
10. Store original Reed raw response separately for audit.

---

## Story Order

### PL-01 — App landing restructure: Search-first shell

**User story:**
As a job seeker, when I open the app, I see a Reed search page first instead of the manual Evaluate form, so I can begin from real jobs.

**Scope:**
- Change app first page/default tab to job source search.
- Add clear tabs/sections:
  - Search Jobs
  - Evaluate / Review Selected Job
  - Manual Fallback
  - History
  - My Profile
- Keep existing Evaluate behavior accessible but secondary.
- Do not integrate Reed API deeply yet beyond shell/wiring placeholders unless existing endpoints are already safe to reuse.

**Acceptance criteria:**
- `GET /` opens Search Jobs by default.
- Manual input remains reachable as fallback.
- Existing History/Profile pages are not broken.
- No Kanban/viewer route confusion.

**Depends on:** none.

---

### PL-02 — Reed search form and API adapter wiring

**User story:**
As a user, I can search Reed from the app using keyword/location and optional filters, so I can find candidate jobs without leaving the app.

**Scope:**
- Rebuild Reed search UI inside `src/job_hunt_ui.py` app style.
- Wire to existing JOB-002 Reed orchestrator/API integration where available.
- Search fields:
  - keywords
  - location
  - salary minimum or salary hint if Reed adapter supports it
  - remote/hybrid filter if data/adapter supports it
  - permanent/contract filter if data/adapter supports it
- Show results list with enough summary to choose a job.
- Friendly empty/error states.

**Acceptance criteria:**
- Search submits from app page.
- Results render in app style.
- Optional unsupported filters fail gracefully or are marked as best-effort, not silently fabricated.
- No manual copy/paste needed to see Reed results.

**Depends on:** PL-01.

---

### PL-03 — Select Reed job → prefill review/evaluate form

**User story:**
As a user, I can select one Reed job and see the Evaluate form prefilled, so I can review before scoring.

**Scope:**
- Add Select action to each Reed result.
- Map Reed data into the existing reviewed job input shape.
- Prefill Evaluate form fields.
- Preserve editable review step before evaluation.
- Include best-effort fields: title, company, location, description, salary, URL, employment type, work mode, source ID, source name, external reference, skills if available.

**Acceptance criteria:**
- Selecting a search result moves/opens user into Review/Evaluate step.
- Prefilled fields are visible and editable.
- User must click Evaluate manually.
- Evaluation uses the reviewed/prefilled data, not hidden raw data.

**Depends on:** PL-02.

---

### PL-04 — Raw Reed response audit storage

**User story:**
As a user/system owner, I can audit exactly what Reed returned separately from the reviewed job and analysis, so results remain truthful and traceable.

**Scope:**
- Store original Reed raw response separately from reviewed job and analysis.
- Preserve existing invariant: raw input, reviewed job, and analysis are separate.
- Link stored raw input to selected/evaluated job.
- Avoid storing fabricated fields.

**Acceptance criteria:**
- After evaluating a selected Reed job, raw Reed payload or source snapshot is stored separately.
- Reviewed job record remains the user-reviewed structure.
- Analysis remains separate.
- History/reporting can trace source where practical.

**Depends on:** PL-03.

---

### PL-05 — Result polish, fallback safety, and regression hardening

**Status:** Build implemented 2026-05-14; QA pending.

**User story:**
As a user, I can still use fallback/manual input when Reed search fails or lacks data, and the app behaves predictably.

**Scope:**
- Polish empty/loading/error states.
- Ensure fallback tab works.
- Add regression coverage for existing Evaluate/History/Profile behavior.
- Add smoke path for Search → Select → Review → Evaluate.
- Document source limitations and future Adzuna/LinkedIn extension points.

**Acceptance criteria:**
- Reed failure does not block manual evaluation.
- Existing manual evaluation tests still pass.
- Search-first smoke flow passes.
- Future source extension point is documented without implementing Adzuna/LinkedIn.

**Depends on:** PL-04.

---

## Recommended Development Sequence

```text
PL-01 → PL-02 → PL-03 → PL-04 → PL-05
```

Each PL should run as its own staged item:

```text
design → review → build → qa → ship
```

Do not combine stories into one broad build. Each PL has an independently testable outcome.

## Engineering Notes for Later Design

- The app currently has a real app server in `src/job_hunt_ui.py`.
- Port `8765` is currently occupied by the OpenClaw/viewer server; app smoke can run on another port such as `8766` unless routing is changed deliberately.
- `reed_jobs_v4.html` is reference material only; do not iframe/copy as-is.
- JOB-002 Reed orchestrator integration should be treated as the backend source of truth where available.
- Search filters must be honest: if Reed/API adapter cannot support a filter directly, implement best-effort filtering visibly or defer it.

## Out of Scope for This Story Set

- Adzuna implementation.
- LinkedIn implementation.
- Auto-apply.
- Auto-evaluate immediately after selection.
- Removing fallback manual/URL/paste input.
- Replacing the whole UI framework.
