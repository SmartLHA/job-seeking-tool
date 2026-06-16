# Source Quality Gating — Decision Path Integration

**Status:** ✅ IMPLEMENTED 2026-06-16 — 236/236 tests green
**Date:** 2026-06-16
**Decision:** Implement `source_quality_score` as a decision-path input: <40 = skip blocker, 40–70 = force Review

---

## Goal

Jobs fetched from external sources carry a `source_quality` score in the normalised record.
Currently this score is recorded in notes but not used in the decision path.
This design wires it into `evaluate_reviewed_job()` so low-quality records cannot
accidentally produce an Apply decision.

---

## What source_quality Measures (existing, in normalize.py)

`NormalizedJob.source_quality` is a dict with:
- `quality_score` (0–100) — overall data completeness/confidence
- `has_full_description`, `has_salary`, `has_location` — boolean presence flags (confirmed field name from `src/job_sources/normalize.py` line 7)
- `description_length` — character count of job description

The `quality_score` is already computed. This design adds gates based on it.

---

## Model Change: JobPosting

Add `source_quality_score` to `JobPosting` in `job_hunt_models.py`:

```python
@dataclass
class JobPosting:
    # ... existing fields ...
    source_quality_score: int | None = None   # 0–100; None if source quality not known
```

`None` means "quality unknown" — treated as acceptable (no gate applied).
This preserves backward compatibility with manually-entered jobs.

---

## Config: Thresholds

Add to `job_hunt_config.py`:

```python
SOURCE_QUALITY_SKIP_THRESHOLD: int = 40    # below this = blocker → always skip
SOURCE_QUALITY_REVIEW_THRESHOLD: int = 70  # below this (but >= skip) = force Review
```

These are tunables — do not hard-code in logic.

---

## Integration: evaluate_reviewed_job()

After existing blocker checks, add source quality check:

```python
from src.job_hunt_config import SOURCE_QUALITY_SKIP_THRESHOLD, SOURCE_QUALITY_REVIEW_THRESHOLD

def _source_quality_blockers_and_flags(job: JobPosting) -> tuple[list[Blocker], list[RiskFlag]]:
    sq = job.source_quality_score
    if sq is None:
        return [], []    # unknown quality — no gate
    if sq < SOURCE_QUALITY_SKIP_THRESHOLD:
        return [Blocker(
            code="low-source-quality",
            label="Low source quality",
            reason=f"Source quality score {sq}/100 is below the minimum threshold ({SOURCE_QUALITY_SKIP_THRESHOLD}). Job data may be incomplete or unreliable.",
            severity="high",
        )], []
    if sq < SOURCE_QUALITY_REVIEW_THRESHOLD:
        return [], [RiskFlag(
            code="marginal-source-quality",
            label="Marginal source quality",
            reason=f"Source quality score {sq}/100. Review the extracted job fields carefully before applying.",
        )]
    return [], []
```

Inject these into the evaluation alongside any existing blockers/risk flags.
A `Blocker` from source quality → `decide_application()` returns `skip` (existing rule: any blocker = skip).
A `RiskFlag` with code `marginal-source-quality` → treat as a critical risk → force `review` decision.

Add `marginal-source-quality` to `DEFAULT_DECISION_POLICY.critical_risk_codes`.

---

## Population: Reed Orchestrator

In `run_reed_evaluation_flow()` / `run_local_evaluation_flow_from_payload()`, when building
the `JobPosting` from a normalised Reed result, populate `source_quality_score`:

```python
job.source_quality_score = normalized_job["source_quality"]["quality_score"]
```

For manually entered jobs (Add Job / paste text), `source_quality_score` remains `None`.

---

## UI: Evaluate Screen

Show `source_quality_score` as a small badge on the job header in the Evaluate screen:
- Score ≥ 70: no badge (acceptable)
- Score 40–69: amber badge "Quality: 63 — Review fields carefully"
- Score < 40: red badge "Quality: 31 — Low data quality" (will appear alongside Skip decision)
- `None`: no badge

---

## Files to Change

| File | Change |
|------|--------|
| `src/job_hunt_models.py` | Add `source_quality_score: int | None = None` to `JobPosting` |
| `src/job_hunt_config.py` | Add `SOURCE_QUALITY_SKIP_THRESHOLD = 40`, `SOURCE_QUALITY_REVIEW_THRESHOLD = 70`; add `marginal-source-quality` to `critical_risk_codes` |
| `src/job_hunt_evaluation.py` | Call `_source_quality_blockers_and_flags()` and inject results |
| `src/job_hunt_orchestrator.py` | Populate `source_quality_score` from normalised Reed result |
| `src/job_hunt_reviewed_input.py` | Accept `source_quality_score` in `reviewed_job_from_dict()` |
| `src/job_hunt_storage.py` | `reviewed_job_to_dict` / `reviewed_job_from_dict` handle new field |
| `src/job_hunt_ui.py` | Render quality badge in Evaluate screen |
| `tests/test_evaluation.py` | Tests: skip below threshold, review between thresholds, no gate when None |
| `tests/test_scoring.py` | N/A — source quality does not affect match_score |

---

## Acceptance Criteria

1. `source_quality_score = None` → no gate applied; evaluation proceeds normally
2. `source_quality_score < 40` → `Blocker(code="low-source-quality")` → decision = `skip`
3. `source_quality_score` in [40, 70) → `RiskFlag(code="marginal-source-quality")` → decision = `review` (even with high match score)
4. `source_quality_score >= 70` → no effect on decision
5. Thresholds are config values, not hard-coded
6. Reed orchestrator populates `source_quality_score` from normalised job
7. Manually entered jobs have `source_quality_score = None`
8. Evaluate screen shows the quality badge when score < 70

---

## Test Command

```bash
python3 -m pytest tests/test_evaluation.py -v -k "source_quality"
```
