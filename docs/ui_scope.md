# UI Scope — v4

**Updated: 2026-06-17** — UX hardening pass complete: CV status indicator, profile save flash banner, actionable error messages for missing CV, AI Analysis manual button, tailor result match stats.
Prior version (v3, 2026-06-16): reflected v4 UI prototype from `Claude deliverable/`.

---

## Purpose

Define the complete UI for the Job Seeking Tool. The backend binding for each screen
is in `Claude deliverable/docs/ui_structure_v4.md` (authoritative per-screen detail).
This doc defines scope, UX rules, and what remains in/out.

---

## Navigation

Six sidebar items + two full-screen workspace overlays:

```
Sidebar:
  Find Jobs  ·  Evaluate  ·  Add Job  ·  Tracker  ·  Gap Coach  ·  My Profile

Workspaces (full-screen, opened from Evaluate):
  Tailor CV  ·  Cover Letter
```

---

## Screen Definitions

### 1. Find Jobs

**Purpose:** Search job boards, filter results, bookmark or batch-evaluate.

**Flow:**
```
Enter keyword + location
    ↓
Processing overlay (fetch → normalise → dedup → score → decide)
    ↓
Filtered result cards (salary / contract / pattern / source / posted filters)
    ↓
Per-card: Bookmark (Save) or Select for evaluation
    ↓
"Evaluate N selected" → triggers batch evaluation → results appear in Evaluate screen
```

**Key behaviours:**
- Source toggles: Reed (wired), Adzuna (gate behind flag), LinkedIn (not implemented)
- Duplicate cards marked visually (merged to `source: multi_source` by dedup)
- Bookmark saves job without evaluating — creates a "Saved" tracker entry (needs `POST /jobs/save`)
- Processing overlay shows the 5-step pipeline with real step labels

**Backend routes:** `GET /search/reed`, `POST /jobs/save` (GAP — missing)

---

### 2. Evaluate

**Purpose:** Inspect evaluation results; make or override the Apply/Review/Skip decision;
launch Tailor CV or Cover Letter workspaces.

**Layout:** Left panel = review queue sorted by fit score. Right panel = job detail.

**Detail panel shows:**
- Score dial (0–100, `match_score`)
- Decision chip (Apply / Review / Skip) with override buttons (GAP-E — not persisted yet)
- Confidence level bound to 3 levels: low / medium / high (NOT a numeric % — UI meter must map these)
- 6 fixed score breakdown components: Skills · Experience · Location · Salary · Domain · Work Mode
- Strengths list (`strengths[]`)
- Gaps: `missing_required_skills[]` + `missing_preferred_skills[]`
- Blockers: `blockers[]` + `risk_flags[]` as softer cautions
- Action buttons: Tailor CV · Cover Letter · Record Outcome

**Backend routes:** `GET /job?job_id=`, `POST /outcome`

---

### 3. Add Job

**Purpose:** Manually add a single job via URL or pasted text, review extracted fields, then evaluate.

**Flow:**
```
Paste URL  →  POST /prefill  →  parsed field-review form
Paste text →  POST /prefill  →  parsed field-review form
                                        ↓
                              User edits any field
                                        ↓
                          Click "Evaluate" (explicit gate)
                                        ↓
                              POST /job-submit → POST /evaluate
                                        ↓
                              Result → Evaluate screen
```

**Key behaviours:**
- Auto-filled fields tagged visually; `null` fields tagged "not found" (GAP-D: parsing returns values only)
- Unknown values stay unknown — user should not be forced to guess
- No auto-evaluation; user must review and click Evaluate

**Backend routes:** `POST /prefill`, `POST /job-submit`, `POST /evaluate`

---

### 4. Tracker (Kanban)

**Purpose:** Visualise application status across the pipeline; move cards between stages.

**Columns (decided 2026-06-16 — Option A, remap UI to backend):**

`Not Applied · Applied · Interview · Offer · Rejected · Withdrawn`

Maps directly to `OutcomeStatus`: `not_applied · applied · interview · rejected · offer · withdrawn`.
Saved and Screening columns are dropped. Withdrawn is a visible terminal column (read-only cards).

Bookmarking a job from Find Jobs creates a `not_applied` outcome record.
DnD is constrained to legal transitions per `_ALLOWED_TRANSITIONS` — illegal target columns are greyed out.
(e.g. Interview → Applied is blocked; Interview → Offer, Rejected, or Withdrawn are allowed)

**Header stats:** Active · Interviews · Offers · Response rate

**Backend routes:** `GET /board` (GAP-H — missing aggregate), `POST /outcome`

---

### 5. Gap Coach

**Purpose:** Aggregate skill gaps and strengths across all evaluated jobs to guide learning priorities.

**Shows:**
- Top recurring missing required skills (by frequency across analyses)
- Top recurring missing preferred skills
- Strengths that appear consistently
- Risk flag themes

**⚠️ GAP-J: No backend.** Needs:
- `gap_coach.aggregate_gaps(analyses[]) -> theme[]`
- `gap_coach.top_strengths(analyses[]) -> strength[]`
- `GET /coach` route
- Read-model scanning `analyses/` directory

Logic is deterministic aggregation only — no new truth is generated.

---

### 6. My Profile

**Purpose:** View and edit the candidate profile; upload and parse master CV.

**Shows:**
- Candidate name, target roles, locations
- Key facts grid: right_to_work_uk, years_experience, salary_floor_gbp, remote_preference
- Skills table with Name / Level / Years columns (backed by `Skill` dataclass — GAP-B ✅ resolved)
- Achievements, certifications
- **CV status indicator** (top of Upload CV section): green = CV on file (N chars), amber = ref set but no text, red = no CV — all with fix guidance
- Master CV upload + parse (`POST /profile/parse-cv`) — auto-saves CV and profile on upload
- **Flash confirmation banner** after Save: "Profile saved. CV: N chars on file."
- Save profile (`POST /profile/save`)

**Key behaviours (2026-06-17):**
- Uploading a CV and clicking Parse CV auto-saves the CV to disk AND the profile JSON — no extra Save click needed
- Skills extracted from CV (LLM first, keyword fallback) are merged into the skills table automatically
- Auto-save failure is non-fatal but now visible: shown in the status bar if it occurs
- After Save, the redirect carries `?flash=` so the user sees confirmation of what was saved

**Backend routes:** `GET /profile`, `POST /profile/save`, `POST /profile/parse-cv`

---

## Full-Screen Workspaces

### Tailor CV

Opened from Evaluate screen for jobs where `tailoring_ready = True`.

**Layout:** Left panel (evidence points, matched keyword chips) · Right preview pane (generated CV)

**Flow:**
```
Evidence selected from profile + master CV by select_relevant_evidence()
    ↓
tailor_cv() generates markdown output
    ↓
validate_tailored_cv() rejects any claim not in profile
    ↓
User can accept/edit → save_tailored_cv() → POST /tailor (GAP-F — route missing)
```

**GAP-F ✅ RESOLVED:** `tailor_cv()` returns `TailoredCVResult(summary, promoted[], matched[], missing[], markdown)`. `POST /tailor` is live. Result panel in UI shows promoted / matched / missing counts alongside saved path.

**Rules:**
- `apply` decisions: auto `tailoring_ready = True`
- `review` decisions: user must manually select before tailoring is available
- `skip` decisions: tailoring not available

---

### Cover Letter

Opened from Evaluate screen.

**Layout:** Left panel (why-company textarea, tone/length/talking-point toggles) · Right preview pane

**Flow:**
```
User writes "why this company" paragraph
    ↓
generate_cover_letter_text(profile, master_cv, job, analysis, why_company_text)
    ↓
~250–300 word ATS-friendly letter: opening · role-fit · why-company · achievements · close
    ↓
POST /cover-letter (GAP-G — route missing)
```

**GAP-G ✅ RESOLVED:** `generate_cover_letter_text()` accepts `tone`/`length`/`points`. `POST /cover-letter` is live with skip gate. Cover letter now returns 422 (not silent empty) if no master CV is on profile.

---

## Explicitly Out of Scope

- Auto-apply or job submission on behalf of user
- Browser automation
- Multi-user accounts
- Background job monitoring
- Scraping beyond single URL at a time
- Adzuna or LinkedIn until fetch clients are wired and a source flag exists
- Bulk import or mass ingestion

---

## UX Principles (unchanged from v2)

- Flow must be obvious; clarity over cleverness
- Unknown values shown explicitly, not hidden or guessed
- User correction must be easy before scoring
- Explainability visible without overwhelming
- Tailoring is a deliberate action, not an automatic surprise
- Pre-fill with AI parsing — user always reviews before Evaluate

---

## HTTP Routes — Current State

All originally-required routes are now implemented. One remains open.

| Method | Path | Status | Purpose |
|--------|------|--------|---------|
| POST | `/jobs/save` | ✅ Done | Bookmark a job from Find Jobs without evaluating |
| GET | `/jobs` | ✅ Done | List all jobs (scan reviewed_jobs/ + analyses/) |
| GET | `/board` | ✅ Done (JSON) | Board aggregate: all jobs with stage + score |
| GET | `/board/view` | ✅ Done (HTML) | Board Kanban view |
| POST | `/tailor` | ✅ Done | Trigger tailoring, return/save tailored CV |
| POST | `/cover-letter` | ✅ Done | Generate and save cover letter |
| GET | `/job/{id}/explain` | ✅ Done | LLM explanation of job-candidate fit (on-demand) |
| POST | `/profile/parse-cv` | ✅ Done | Upload + parse CV; auto-save to profile |
| POST | `/profile/save` | ✅ Done | Save profile; flash confirmation on redirect |
| GET | `/search/{source}` | ✅ Done | Generic source search (Reed wired) |
| POST | `/select/{source}` | ✅ Done | Generic source select + prefill |
| GET | `/coach` | 🔲 Not yet | Gap Coach aggregate read-model |
