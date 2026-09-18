# Tailoring Specification
**Status:** Implemented and hardened (2026-07-27) | **Brief:** `docs/tasks/cv-tailoring-brief.md`

---

## Goal

Generate truthful, ATS-friendly tailored CVs for shortlisted jobs — using only approved facts from CandidateProfile and master CV.

---

## Data Flow

```
CandidateProfile + master_cv + JobPosting + JobAnalysis
         │
         ▼
  tailoring.py
  ┌─────┴─────┐
  ▼           ▼
select_    validate_
evidence    truthfulness
(Required    (no invented
 skills      claims)
 first)
  │           │
  └─────┬─────┘
        ▼
  tailored_cv_text (ATS-friendly)
        │
        ▼
  save_tailored_cv(job_id, cv_text, profile_id)
```

---

## Core Functions

### `select_relevant_evidence(profile, cv_text, job, analysis) -> list[str]`
- Required skills → preferred skills → years_experience → achievements
- Evidence sourced from `CandidateProfile.skills`, `years_experience`, and `achievements` (decision 2026-06-16 per cv-tailoring-brief.md; ✅ implemented in code 2026-06-30 — appended as `Achievement: <text>` after experience, blank/non-str entries skipped)
- **Never** from certifications or any other field not in CandidateProfile

### `tailor_cv(cv_text, evidence_points, job) -> str`
- Reorder evidence to match job requirements
- ATS-friendly formatting (plain text, clean section headings)
- Deterministic preferred over LLM

### `validate_tailored_cv(original_cv, tailored_cv, profile) -> bool`
- Cross-checks every factual claim in tailored CV against approved `CandidateProfile.skills`, `years_experience`, and normalized exact `CandidateProfile.achievements`
- Requires the deterministic tailored CV section structure: Role Target, Matching Evidence, optional ATS Keywords, and exact Base CV embedding
- Rejects unexpected generated sections, malformed role target lines, unsupported evidence bullets, unsupported ATS keywords, and modified base CV content
- Returns `True` only if all generated candidate claims are structurally valid and supported by approved profile data

### `save_tailored_cv(job_id, cv_text, profile_id) -> Path`
- Writes to `output/tailored_cvs/<job_id>.md`
- Creates `output/tailored_cvs/` directory if needed
- Accepts only non-empty safe job IDs (`A–Z`, `a–z`, `0–9`, `.`, `_`, `-`; not `.` or `..`) so output cannot traverse outside the configured directory

---

## Tailoring Eligibility Rules

| Decision | Tailoring Allowed? |
|----------|-------------------|
| `apply` | ✅ Yes — auto-eligible |
| `review` | ⚠️ Manual selection required — user must explicitly pick the job |
| `skip` | ❌ No |

---

## Evidence Rules

**Allowed fields:**
- `CandidateProfile.skills` — hard skills, soft skills
- `CandidateProfile.years_experience` — role-relevant experience
- `CandidateProfile.achievements` — allowed only when a generated `Achievement:` claim normalizes exactly to a declared achievement

**Blocked fields (MVP):**
- `certifications` — not in MVP scope for tailoring evidence
- Any field not present in CandidateProfile

**Rules:**
- May reorder, emphasize, compress evidence
- May not invent facts
- May not infer experience that is not explicitly in profile

---

## ATS Formatting Rules

- Plain text output (no HTML tables, columns, or ALL-CAPS headers)
- Clean section breaks
- Standard CV order: Contact → Summary → Skills → Experience → Education
- Skills presented as bullet list or comma-separated, not in tables

---

## Files

| File | Description |
|------|-------------|
| `src/job_hunt_tailoring.py` | Core tailoring logic (88 tests) |
| `tests/test_tailoring.py` | Tailoring test suite |
| `src/job_hunt_config.py` | Contains `TailoringPolicy` config |
| `src/job_hunt_evaluation.py` | Tailoring gate for `review` decisions |
| `output/tailored_cvs/` | Output directory for tailored CVs |

---

## Test Command

```bash
python3 -m pytest tests/test_tailoring.py -v
```

---

## Open Issues

| Issue | Status |
|-------|--------|
| `validate_tailored_cv()` strict truth validation | ✅ Implemented for deterministic CV format — pending QA sign-off |
| Cover letter integration into tailoring | ⚠️ Spec drafted, integration not finalized |
| Achievements as tailoring evidence | ✅ In scope and fail-closed validated against declared achievements |
| Certifications as tailoring evidence | ❌ Out of MVP scope |
