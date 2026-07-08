# GAP-D — Per-Field Found Provenance from Parsing

**Status:** ✅ Implemented 2026-06 — per-field found/not-found provenance + null-contract parsing shipped
**Date:** 2026-06-16
**Decision:** Parsing returns `null` as the "not found" signal; UI derives "auto-filled vs not found" from nulls

---

## Goal

The Add Job field-review form must visually distinguish auto-filled fields (parser found a value)
from not-found fields (parser returned null/empty). Currently parsing returns values only with
no explicit signal — the UI cannot tell the difference between "parser found nothing" and
"parser found an empty string".

---

## Approach: Null-as-Not-Found (simpler option)

Rather than adding a separate `found` map, standardise the parsing contract:

- A field that the parser **found** → returns a non-null, non-empty value
- A field the parser **did not find** → returns `None` (for scalars) or `[]` (for lists)

The UI tags any field whose value is `None` or `[]` as **"not found"**, and any other field
as **"auto-filled"**.

This requires no new data structure — just strict discipline in parsing output.

---

## Parsing Contract (updated)

`parse_job_from_text()` and `parse_job_from_url()` must follow this contract:

| Field | "Found" signal | "Not found" signal |
|-------|---------------|-------------------|
| `job_title` | non-empty string | `None` |
| `company` | non-empty string | `None` |
| `location` | non-empty string | `None` |
| `work_mode` | `"remote"` \| `"hybrid"` \| `"onsite"` | `"unknown"` |
| `employment_type` | `"permanent"` \| `"contract"` \| `"temporary"` | `None` |
| `required_skills` | non-empty list | `[]` |
| `preferred_skills` | non-empty list | `[]` |
| `required_years_experience` | positive int | `None` |
| `nice_to_have_years_experience` | positive int | `None` |
| `domain` | non-empty string | `None` |
| `salary_min_gbp` | positive number | `None` |
| `salary_max_gbp` | positive number | `None` |
| `notes` | non-empty string | `None` |

**Rule:** Parsers must never guess or default to a placeholder string (e.g. `"unknown"` for
`job_title`). If the value cannot be confidently extracted, return `None` / `[]`.

`work_mode` is the exception: it uses the literal string `"unknown"` because the model requires
a string in that field, and `"unknown"` is a valid model value meaning "not determined".

---

## UI Tagging Logic (frontend)

```javascript
function fieldStatus(value) {
  if (value === null || value === undefined) return "not-found";
  if (Array.isArray(value) && value.length === 0) return "not-found";
  if (value === "unknown") return "not-found";   // work_mode only
  return "auto-filled";
}
```

- **Auto-filled** tag: blue chip, editable
- **Not found** tag: grey chip, field is empty and editable
- Both states leave the field editable — user can always correct or fill in

---

## Boundary: Null Contract vs JobPosting Validation (NEW)

`JobPosting.__post_init__` validates that `job_title` and `company` are **non-empty strings**.
Returning `None` from the parser will cause `JobPosting` construction to fail — these two fields
are not optional in the model.

**Resolution:** The null contract applies to the *parsing output dict*, not to the `JobPosting`
object. The boundary is the review form:

```
parse_job_from_text() → dict (may have None job_title/company)
        ↓
  Review form displayed — user sees empty fields, fills them in
        ↓
  User submits form
        ↓
  reviewed_job_from_dict() → JobPosting (validates non-empty job_title/company)
```

- Parser returns `None` for `job_title`/`company` if not found → UI shows empty editable field
- Review form **must not submit** if `job_title` or `company` is still empty — client-side or server-side validation before `JobPosting` is constructed
- `reviewed_job_from_dict()` already validates non-empty — this is the correct guard; do not relax it

**job_id fallback:** `_build_job_id()` in parsing.py currently takes `inferred_title` and
`inferred_company`. When both are `None`, the parser cannot build a meaningful job_id from
title/company. Use a UUID fallback:
```python
job_id = _build_job_id(title, company) if (title and company) else str(uuid.uuid4())[:8]
```
This is returned in the parse dict for the UI's reference, not stored until the user submits.

---

## Files to Change

| File | Change |
|------|--------|
| `src/job_hunt_parsing.py` | Audit all extractors — replace placeholder defaults with `None`/`[]`; `work_mode` returns `"unknown"` when not detected; UUID fallback for job_id when title/company both None |
| `src/job_hunt_ui.py` | Field-review form: add `fieldStatus()` tag per field; block form submit if job_title/company empty |
| `tests/test_parsing.py` | Tests: each field returns `None`/`[]` when absent; job_id is a UUID when both title and company are None |

---

## Acceptance Criteria

1. `parse_job_from_text()` returns `None` for any scalar field not found in the text
2. `parse_job_from_text()` returns `[]` for any list field not found in the text
3. `work_mode` returns `"unknown"` when no remote/hybrid/onsite signal is present
4. No field returns a guess or placeholder string when the value is absent
5. When `job_title` and `company` are both `None`, `job_id` is a short UUID string
6. Review form shows empty editable fields for `None` values (not the string `"None"`)
7. Review form blocks submission when `job_title` or `company` is still empty
8. Field-review form tags each field as "auto-filled" or "not found" based on the null contract
9. "Not found" fields are empty and editable (not blocked)
10. Existing parsing tests continue to pass; new null-contract tests are added

---

## Test Command

```bash
python3 -m pytest tests/test_parsing.py -v
```
