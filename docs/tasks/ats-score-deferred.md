# ATS Scorer — Integration Design

**Status:** ✅ IMPLEMENTED 2026-06-16 — 240/240 tests green
**Updated:** 2026-06-16 — decision made to integrate into evaluation flow and surface in UI (JOB-008)
**Prior status:** Module existed (`job_hunt_ats_scorer.py`) but was not called from evaluation or shown in UI

---

## Goal

Wire the existing ATS scorer into the evaluation flow so that every `JobAnalysis` includes an
`ats_score`, and surface it in the Evaluate screen score breakdown panel.

---

## What Already Exists

`src/job_hunt_ats_scorer.py` — `score_cv(cv_text: str, job_keywords: list[str]) -> dict`
`tests/test_ats_scorer.py` — unit tests for all 4 metrics

These do not change. The work is integration only (plus the model field and UI display).

---

## ATS Score Metrics (existing, unchanged)

| Factor | Max | Description |
|--------|-----|-------------|
| `keyword_density` | 25 | job keywords from posting found in CV / total keywords |
| `format_score` | 25 | plain text = 25; tables/columns/headers = 0 |
| `section_presence` | 25 | required sections (summary, experience, skills) each = 8pt |
| `length_score` | 25 | 300–800 words = 25; <300 or >1200 = 0 |
| **`overall`** | **100** | sum of all 4 |

---

## Model Change: JobAnalysis

Add `ats_score` to `JobAnalysis` in `job_hunt_models.py`:

```python
@dataclass
class JobAnalysis:
    # ... existing fields ...
    ats_score: int | None = None   # 0–100; None if master CV not available at evaluation time
```

`None` is valid — if the candidate has no `master_cv_text` at evaluation time, skip ATS scoring
and leave `None`. Do not block evaluation.

---

## Integration Point: evaluate_reviewed_job()

In `job_hunt_evaluation.py`, after `score_job()` and `decide_application()`:

```python
ats_score = None
if profile.master_cv_text:
    job_keywords = job.required_skills + job.preferred_skills
    ats_result = score_cv(profile.master_cv_text, job_keywords)
    ats_score = ats_result["overall"]

return JobAnalysis(
    ...,
    ats_score=ats_score,
)
```

Use `master_cv_text` (already loaded on the profile) as the CV input.
Use `job.required_skills + job.preferred_skills` as `job_keywords`.

---

## UI: Evaluate Screen

Surface `ats_score` in the score breakdown panel alongside the 6 component scores.

Display as: **"ATS readiness: 74 / 100"** with a brief label.
If `ats_score is None`: show **"ATS score: N/A (no CV on file)"**.

The ATS score is informational — it does not feed into `match_score` or `decision`.

---

## Files to Change

| File | Change |
|------|--------|
| `src/job_hunt_models.py` | Add `ats_score: int | None = None` to `JobAnalysis` |
| `src/job_hunt_evaluation.py` | Call `score_cv()` after scoring; populate `ats_score` |
| `src/job_hunt_storage.py` | `job_analysis_to_dict` / `job_analysis_from_dict` must handle `ats_score` |
| `src/job_hunt_ui.py` | Render `ats_score` in Evaluate screen breakdown |
| `tests/test_evaluation.py` | Add tests: `ats_score` populated when CV present; `None` when absent |
| `tests/test_storage.py` | `ats_score` round-trips through `job_analysis_to_dict`/`job_analysis_from_dict` — serialisation lives in storage, not models |

Do NOT change `src/job_hunt_ats_scorer.py` or `tests/test_ats_scorer.py`.

---

## Acceptance Criteria

1. `JobAnalysis.ats_score` is an `int` (0–100) when `master_cv_text` is present
2. `JobAnalysis.ats_score` is `None` when `master_cv_text` is absent — evaluation still completes
3. `ats_score` does not affect `match_score` or `decision`
4. `ats_score` serialises to/from JSON correctly (stored in `analyses/<job_id>.json`)
5. Evaluate screen displays ATS score in the breakdown panel
6. Evaluate screen shows "N/A" gracefully when `ats_score is None`
7. Existing `test_ats_scorer.py` tests all pass unchanged
8. New integration tests cover both CV-present and CV-absent paths

---

## Test Command

```bash
python3 -m pytest tests/test_evaluation.py tests/test_storage.py tests/test_ats_scorer.py -v
```
