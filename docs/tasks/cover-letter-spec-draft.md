# Cover Letter Generator — Design Spec v2

**Status:** ✅ IMPLEMENTED 2026-06-16 — 291/291 tests green
**Updated:** 2026-06-16 — extended with tone/length/points parameters (GAP-G decision) + POST /cover-letter route
**Prior version:** v1 described a single `why_company_text` input only

---

## Goal

Generate a near-final quality cover letter from profile + master CV + job posting.
User controls tone, length, and talking-point emphasis via optional parameters.

---

## Fixed Structure (4 paragraphs)

```
Opening: Brief intro — role + company name

Paragraph 1 (Role fit): Required skills matched to candidate evidence from profile/CV

Paragraph 2 (Why this company): User-supplied why_company_text inserted as-is

Paragraph 3 (Achievements): Key achievements/skills evidence from profile/CV

Closing: Call to action, availability, thank you
```

---

## Function Signature (updated)

```python
def generate_cover_letter_text(
    profile: CandidateProfile,
    master_cv: str,
    job: JobPosting,
    analysis: JobAnalysis,
    why_company_text: str,
    *,
    tone: str = "professional",          # "professional" | "conversational" | "concise"
    length: str = "standard",            # "brief" (~150w) | "standard" (~275w) | "detailed" (~400w)
    points: list[str] | None = None,     # optional talking points to weave into Paragraph 3
) -> str:
```

**Rules:**
- `why_company_text` is required — it is inserted verbatim into Paragraph 2
- `tone` adjusts sentence structure and vocabulary; never changes factual content
- `length` adjusts paragraph depth; "brief" compresses Paragraph 1 and 3; "detailed" expands them
- `points` are candidate-supplied emphasis hints (e.g. "mention stakeholder management"); they must still be grounded in profile/CV facts — no invented claims
- Output is always plain text (ATS-friendly); no HTML, tables, columns, or ALL-CAPS headers

---

## New Route

```
POST /cover-letter
Body: {
  job_id: str,
  why_company_text: str,
  tone?: "professional" | "conversational" | "concise",
  length?: "brief" | "standard" | "detailed",
  points?: list[str]
}
Response: {
  letter: str,
  word_count: int,
  saved_path: str
}
```

Handler calls:
1. `load_job_analysis(job_id)` → `JobAnalysis`
2. **Decision gate:** `if effective_decision(analysis) == "skip": return 400 {"error": "Cover letter not available for skipped jobs"}`
3. `load_reviewed_job(job_id)` → `JobPosting`
4. `load_candidate_profile(...)` → `CandidateProfile`
5. `load_master_cv(...)` → `str`
6. `generate_cover_letter_text(profile, master_cv, job, analysis, why_company_text, tone=, length=, points=)`
7. Save output to `output/cover_letters/<job_id>.txt`
8. Return response JSON

`effective_decision()` is imported from `src/job_hunt_models.py`. Both `apply` and `review` decisions are allowed — only `skip` is blocked.

---

## Quality Bar

- Near-final quality — ready to send with minimal edits
- No salary expectations (leave blank)
- ATS-friendly: plain text, no formatting artifacts
- All claims traceable to `CandidateProfile` or `master_cv`

---

## Files to Create/Change

| File | Change |
|------|--------|
| `src/job_hunt_cover_letter.py` | Add `tone`, `length`, `points` parameters; update paragraph generation logic |
| `src/job_hunt_tailoring.py` | Update `generate_cover_letter_text()` wrapper to pass new params |
| `src/job_hunt_ui.py` | Add `POST /cover-letter` route |
| `tests/test_cover_letter.py` | Add tests for tone/length/points variations; existing structure tests remain |

---

## Acceptance Criteria

1. `why_company_text` inserted verbatim into Paragraph 2
2. `tone="professional"` (default) matches current output behaviour — no regression
3. `tone="conversational"` produces less formal language; facts unchanged
4. `tone="concise"` produces shorter sentences; same paragraph structure
5. `length="brief"` outputs ~150 words
6. `length="standard"` outputs ~250–300 words (current default)
7. `length="detailed"` outputs ~380–420 words
8. `points` hints appear in Paragraph 3; all are grounded in profile/CV — no invented claims
9. Output is plain text — no HTML, tables, columns, or `---` dividers
10. No salary field anywhere in output
11. `POST /cover-letter` returns `{letter, word_count, saved_path}`
12. All variations have tests; existing tests pass

---

## Test Command

```bash
python3 -m pytest tests/test_cover_letter.py -v
```
