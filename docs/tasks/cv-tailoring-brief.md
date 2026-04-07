# CV Tailoring — Task Brief (CONFIRMED)

**For: Handy**
**Status: Ready to hand off — decisions confirmed**
**Depends on: QA green (done)**

---

## Goal
Implement MVP CV tailoring for shortlisted jobs. Tailor from `CandidateProfile` + `master_cv` only.

---

## Confirmed Decisions

1. `review` jobs require **manual user selection** before tailoring
2. Evidence selection: **required skills first**, then preferred
3. Evidence sources: **skills + years only** (not achievements/certs — too risky for invented claims)
4. Output must be **ATS-friendly**
5. May reorder, emphasize, compress evidence — never invent
6. Tailoring only from approved profile + master CV — nothing else

---

## Scope

### Must do
- `src/tailoring.py`
- `tests/test_tailoring.py`
- ATS-friendly formatting in output
- Manual selection gate for `review` decisions

### Must NOT do
- No achievements/certifications as evidence (not in scope for MVP)
- No LLM unless deterministic evidence selection insufficient
- No auto-trigger on `review` — must be manual

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

## Key Functions

```python
def select_relevant_evidence(profile, cv_text, job, analysis) -> list[str]:
    # Required skills first → preferred skills → years_experience
    # Evidence from: skills + years_experience only
    # Never from: achievements, certifications

def tailor_cv(cv_text, evidence_points, job) -> str:
    # Reorder + emphasize evidence
    # ATS-friendly formatting
    # Deterministic preferred over LLM

def validate_tailored_cv(original_cv, tailored_cv, profile) -> bool:
    # No invented facts, no unsupported claims

def save_tailored_cv(job_id, cv_text, profile_id) -> Path:
    # output/tailored_cvs/<job_id>.md
```

---

## Acceptance Criteria

1. `tailor_cv()` produces ATS-friendly output for `apply` decisions
2. `review` decisions: tailoring blocked until user explicitly selects the job
3. `validate_tailored_cv()` returns `True` only — no false positives
4. Evidence only from skills + years_experience fields
5. All new functions have tests

---

## Files to Create/Change

| File | Change |
|------|--------|
| `src/tailoring.py` | New |
| `tests/test_tailoring.py` | New |
| `src/config.py` | Add `TailoringPolicy` |
| `src/evaluation.py` | Add tailoring gate for `review` decisions |
| `docs/tailoring_spec.md` | New |

---

## Test Command
```bash
python3 -m pytest tests/test_tailoring.py -v
```
