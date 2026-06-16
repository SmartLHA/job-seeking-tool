# CV Tailoring — Design Spec v2

**Status:** ✅ IMPLEMENTED 2026-06-16 — 278/278 tests green
**Updated:** 2026-06-16 — enriched backend return type (GAP-F decision) + POST /tailor route
**Prior version:** v1 described markdown-only output; UI now requires structured enrichment

---

## Goal

Generate a tailored CV for shortlisted jobs with structured output that supports the Tailor CV
workspace UI: promoted bullet points, editable summary, and matched/missing keyword chips.
All output must be grounded in `CandidateProfile` + `master_cv` only — no invented claims.

---

## Confirmed Decisions (unchanged from v1)

1. `review` jobs require **manual user selection** before tailoring is available
2. Evidence selection: **required skills first**, then preferred
3. Evidence sources: **skills + years + achievements** (achievements added; certs remain excluded)
4. Output must be **ATS-friendly plain text**
5. May reorder, emphasise, compress — never invent
6. `validate_tailored_cv()` must cover all output sections including `summary` and `promoted`

---

## Updated Function Signatures

```python
def select_relevant_evidence(
    profile: CandidateProfile,
    cv_text: str,
    job: JobPosting,
    analysis: JobAnalysis,
) -> list[str]:
    # Returns ordered evidence points: required skills → preferred → years → relevant achievements
    # All evidence is traceable to profile fields or cv_text passages

def tailor_cv(
    cv_text: str,
    evidence_points: list[str],
    job: JobPosting,
    policy: TailoringPolicy = DEFAULT_TAILORING_POLICY,
) -> TailoredCVResult:
    # Returns structured result (see below) — NOT a plain string

def validate_tailored_cv(
    original_cv: str,
    tailored: TailoredCVResult,
    profile: CandidateProfile,
) -> bool:
    # Validates summary, promoted bullets, and markdown body
    # Returns True only if all content is traceable to profile/cv_text
    # Raises TailoringValidationError on failure (no silent pass)

def save_tailored_cv(
    job_id: str,
    result: TailoredCVResult,
    profile_id: str,
    policy: TailoringPolicy,
) -> Path:
    # Saves markdown body to output/tailored_cvs/<job_id>.md
    # Returns path
```

---

## New Return Type: TailoredCVResult

```python
@dataclass
class TailoredCVResult:
    summary: str              # 2–3 sentence role-targeted summary (from profile facts only)
    promoted: list[str]       # CV bullet lines promoted to top because they match required skills
    matched: list[str]        # Keywords from job that are present in the tailored output
    missing: list[str]        # Required/preferred keywords from job not present in candidate evidence
    markdown: str             # Full ATS-friendly CV as markdown (existing format, unchanged)
```

Add `TailoredCVResult` to `job_hunt_models.py`.

---

## New Route

```
POST /tailor
Body: {
  job_id: str,
  manual_selected?: bool    # required for review decisions; ignored for apply
}
Response: {
  summary: str,
  promoted: list[str],
  matched: list[str],
  missing: list[str],
  markdown: str,
  saved_path: str
}
```

Handler calls:
1. `load_job_analysis(job_id)` → check `tailoring_ready`; if `review` and not `manual_selected` → 400
2. `load_reviewed_job(job_id)` → `JobPosting`
3. `load_candidate_profile(...)` + `load_master_cv(...)` → evidence sources
4. `select_relevant_evidence(profile, cv_text, job, analysis)` → `evidence_points`
5. `tailor_cv(cv_text, evidence_points, job)` → `TailoredCVResult`
6. `validate_tailored_cv(cv_text, result, profile)` → must be True; else 422
7. `save_tailored_cv(job_id, result, profile_id, policy)`
8. Return response JSON

---

## Tailoring Gate (unchanged)

| Decision | `tailoring_ready` | Can call POST /tailor |
|----------|-------------------|----------------------|
| `apply` | `True` (automatic) | Yes, directly |
| `review` | `False` by default | Only if `manual_selected=true` in request |
| `skip` | `False` | No — returns 403 |

---

## Data Flow

```
CandidateProfile + master_cv + JobPosting + JobAnalysis
         │
         ▼
  select_relevant_evidence()
  (required skills → preferred → years → achievements)
         │
         ▼
  tailor_cv()
  ┌──────┴──────────────────┐
  ▼                         ▼
summary generation    promoted bullet    matched/missing
(from profile facts)  selection          keyword diff
         │
         ▼
  TailoredCVResult
         │
         ▼
  validate_tailored_cv()   ← rejects any claim not in profile/cv_text
         │
         ▼
  save_tailored_cv()  →  output/tailored_cvs/<job_id>.md
```

---

## Files to Create/Change

| File | Change |
|------|--------|
| `src/job_hunt_models.py` | Add `TailoredCVResult` dataclass |
| `src/job_hunt_tailoring.py` | Update `tailor_cv()` return type; add `summary`, `promoted`, `matched`, `missing` generation; update `validate_tailored_cv()` to cover all fields |
| `src/job_hunt_ui.py` | Add `POST /tailor` route |
| `tests/test_tailoring.py` | Add tests for `TailoredCVResult` fields; update existing tests to unpack new return type |

---

## Acceptance Criteria

1. `tailor_cv()` returns a `TailoredCVResult` (not a plain string)
2. `summary` is 2–3 sentences; every claim is in `profile` or `cv_text`
3. `promoted` contains CV bullet lines that contain required skill keywords
4. `matched` = intersection of job keywords and output content
5. `missing` = required/preferred keywords absent from candidate evidence
6. `validate_tailored_cv()` raises `TailoringValidationError` on any invented claim (no silent pass)
7. `apply` decisions: `POST /tailor` works without `manual_selected`
8. `review` decisions: `POST /tailor` without `manual_selected=true` → 400
9. `skip` decisions: `POST /tailor` → 403
10. `POST /tailor` returns `{summary, promoted, matched, missing, markdown, saved_path}`
11. All new fields have tests; existing tailoring tests continue to pass

---

## Test Command

```bash
python3 -m pytest tests/test_tailoring.py -v
```
