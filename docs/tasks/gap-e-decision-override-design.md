# GAP-E — Decision Override Persistence

**Status:** ✅ IMPLEMENTED 2026-06-16 — 253/253 tests green
**Date:** 2026-06-16
**Decision:** Add `user_decision` field to `JobAnalysis` — separate from engine `decision`

---

## Goal

The Evaluate screen lets users override the Apply/Review/Skip decision the engine produced.
Currently the override is UI-only (lost on refresh). This design makes it persistent.

---

## Approach: Separate user_decision field

Keep the engine's `decision` field immutable (audit trail).
Add a separate optional `user_decision` field that the user can set.

The UI shows `user_decision` when present; falls back to `decision` otherwise.
Reports and tailoring use `user_decision` when present.

---

## Model Change

```python
@dataclass
class JobAnalysis:
    # ... existing fields ...
    decision: str                          # engine decision — never overwritten after evaluation
    decision_reason: str
    user_decision: str | None = None       # "apply" | "review" | "skip" | None
    user_decision_note: str | None = None  # optional free-text reason from user
```

`user_decision` follows the same `Decision` literal type as `decision`.

---

## New Route

```
POST /job/<job_id>/decision
Body: {
  user_decision: "apply" | "review" | "skip",
  note?: str
}
Response: {
  job_id: str,
  engine_decision: str,
  user_decision: str,
  updated_at: str   # ISO timestamp
}
```

Handler:
1. Load `JobAnalysis` from storage
2. Set `analysis.user_decision = payload["user_decision"]`
3. Set `analysis.user_decision_note = payload.get("note")`
4. Save updated analysis back to `analyses/<job_id>.json`
5. Return response

To **clear** an override: `POST /job/<job_id>/decision` with `user_decision: null`.

---

## Effective Decision Logic

**Module:** `effective_decision()` lives in `src/job_hunt_models.py`, alongside `JobAnalysis`.
It is a module-level function (not a method), importable by tailoring, cover letter, reporting, and UI
from a single location with no circular imports.

Wherever the codebase uses `analysis.decision` to drive behaviour, switch to:

```python
# In src/job_hunt_models.py
def effective_decision(analysis: JobAnalysis) -> str:
    return analysis.user_decision or analysis.decision
```

Specifically update:
- Tailoring gate: use `effective_decision()` to check Apply/Review/Skip eligibility
- Cover letter gate: same
- Reporting rows: export both `engine_decision` and `user_decision` columns

---

## UI: Evaluate Screen

Override buttons below the decision chip:
- Three buttons: Apply / Review / Skip (highlighted = current effective decision)
- Clicking an override calls `POST /job/<job_id>/decision`
- A small "Overridden" badge appears on the chip when `user_decision` differs from `decision`
- Clicking the active override again clears it (sends `user_decision: null`)

---

## Files to Change

| File | Change |
|------|--------|
| `src/job_hunt_models.py` | Add `user_decision`, `user_decision_note` to `JobAnalysis` |
| `src/job_hunt_storage.py` | `job_analysis_to_dict` / `job_analysis_from_dict` handle new fields |
| `src/job_hunt_tailoring.py` | Use `effective_decision()` for tailoring gate |
| `src/job_hunt_cover_letter.py` | Use `effective_decision()` for cover letter gate |
| `src/job_hunt_reporting.py` | Export `engine_decision` and `user_decision` columns |
| `src/job_hunt_ui.py` | Add `POST /job/<id>/decision` route; render override buttons + badge in Evaluate screen |
| `tests/test_models.py` | `user_decision` is `None` by default; `effective_decision()` returns engine decision when None, user decision when set |
| `tests/test_storage.py` | `user_decision`/`user_decision_note` round-trip through `job_analysis_to_dict`/`from_dict` |
| `tests/test_evaluation.py` | `evaluate_reviewed_job()` sets `user_decision=None` on all output |
| `tests/test_reporting.py` | Report rows include both `engine_decision` and `user_decision` columns |
| `tests/test_ui.py` | Override route: valid set; clear with null; invalid decision value; missing job_id |

---

## Acceptance Criteria

1. `JobAnalysis.user_decision` is `None` by default after evaluation
2. `POST /job/<id>/decision` with valid decision → persists `user_decision` in stored JSON
3. `POST /job/<id>/decision` with `null` → clears `user_decision` back to `None`
4. `GET /job?job_id=` returns both `engine_decision` (= `decision`) and `user_decision`
5. Evaluate screen shows override buttons; active override highlighted
6. "Overridden" badge appears when `user_decision` ≠ `decision`
7. Tailoring and cover letter gates use `effective_decision()`, not raw `decision`
8. Reports export both engine and user decision columns

---

## Test Command

```bash
python3 -m pytest tests/test_models.py tests/test_storage.py tests/test_evaluation.py tests/test_reporting.py tests/test_ui.py -v
```
