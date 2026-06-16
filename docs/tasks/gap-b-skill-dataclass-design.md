# GAP-B — Skill Dataclass: Profile Model Extension

**Status:** ✅ IMPLEMENTED 2026-06-16 — 73/73 tests green
**Date:** 2026-06-16
**Decision:** Extend `CandidateProfile.skills` from `list[str]` to `list[Skill]` with level, years, evidence_type

---

## Goal

Allow the My Profile screen to store and display per-skill metadata (level, years, evidence type),
and ensure scoring, tailoring, and cover letter still work against the richer model without regression.

---

## New Dataclass

Add to `job_hunt_models.py`:

```python
@dataclass
class Skill:
    name: str                                          # required; non-empty
    level: str = "unspecified"                         # "junior" | "mid" | "senior" | "expert" | "unspecified"
    years: int | None = None                           # years of experience; None = unspecified
    evidence_type: str = "self-reported"               # "evidenced" | "self-reported"

    def __post_init__(self):
        if not self.name.strip():
            raise ValueError("Skill.name must not be empty")
        if self.level not in {"junior", "mid", "senior", "expert", "unspecified"}:
            raise ValueError(f"Invalid skill level: {self.level}")
        if self.evidence_type not in {"evidenced", "self-reported"}:
            raise ValueError(f"Invalid evidence_type: {self.evidence_type}")
        if self.years is not None and self.years < 0:
            raise ValueError("Skill.years must be non-negative")
```

---

## Profile Model Change

```python
# Before
@dataclass
class CandidateProfile:
    skills: list[str]

# After
@dataclass
class CandidateProfile:
    skills: list[Skill]
```

---

## Backward Compatibility (plain-string migration)

Existing `CandidateProfile` JSON files store `skills` as `["Python", "SQL", ...]`.
The loader must handle both formats without requiring manual migration of existing files.

In `candidate_profile_from_dict()`:

```python
def _coerce_skill(raw) -> Skill:
    if isinstance(raw, str):
        name = raw.strip()
        if not name:
            raise ProfileValidationError("skills contains an empty string entry")
        return Skill(name=name)
    if isinstance(raw, dict):
        if "name" not in raw:
            raise ProfileValidationError(f"Skill dict missing 'name' key: {raw!r}")
        return Skill(**{k: v for k, v in raw.items() if k in {"name", "level", "years", "evidence_type"}})
    raise ProfileValidationError(f"Invalid skill entry type {type(raw).__name__!r}: {raw!r}")

profile.skills = [_coerce_skill(s) for s in payload.get("skills", [])]
```

- Plain strings: coerced to `Skill(name=str)` with defaults
- Dicts: only known keys passed to `Skill()` — unknown keys dropped, not silently accepted
- Any other type (int, list, etc.): raises `ProfileValidationError` immediately
- Saving always writes the full `Skill` dict format — files auto-migrate on next save

---

## Scoring Impact

`job_hunt_scoring.py` currently matches skills by string comparison against `profile.skills`.
After this change it must compare against `Skill.name`:

```python
# Before
matched = [s for s in profile.skills if s.lower() in job_skill_lower]

# After
matched = [s for s in profile.skills if s.name.lower() in job_skill_lower]
```

No scoring weights or logic change — only the attribute access changes.

---

## Tailoring Impact (NEW — real breakage)

`job_hunt_tailoring.py` calls string methods directly on `profile.skills` elements at two points.
Both will fail at runtime with `AttributeError` if not fixed.

### Line 22 — `select_relevant_evidence()`
```python
# Current (BROKEN with Skill objects)
candidate_lookup = {_normalize_text(skill): skill.strip() for skill in profile.skills if skill.strip()}

# Fix
candidate_lookup = {_normalize_text(skill.name): skill.name for skill in profile.skills}
```

### Line 121 — `validate_tailored_cv()`
```python
# Current (BROKEN with Skill objects)
allowed_skills = {_normalize_text(value) for value in profile.skills}

# Fix
allowed_skills = {_normalize_text(skill.name) for skill in profile.skills}
```

No logic change — both sites only used `skill` as a display string and lookup key. `.name` is the direct replacement.

---

## Cover Letter Impact (NEW — real breakage)

`job_hunt_cover_letter.py` passes `profile.skills` directly to `_match_skills()`, which calls
`.strip()` on each element in `profile_skills`. This will fail with `AttributeError`.

### `_match_skills()` — line 160
```python
# Current signature and body (BROKEN with Skill objects)
def _match_skills(job_skills: list[str], profile_skills: list[str]) -> list[str]:
    profile_lookup = {_normalize_text(skill): skill for skill in profile_skills if skill.strip()}

# Fix — update signature and body
def _match_skills(job_skills: list[str], profile_skills: list[Skill]) -> list[str]:
    profile_lookup = {_normalize_text(skill.name): skill.name for skill in profile_skills}
```

Call sites (lines 57, 69) pass `profile.skills` — no change needed there once the function signature is updated.

---

## Serialisation

`candidate_profile_to_dict()` must serialise each `Skill` as a dict:

```python
"skills": [
    {"name": "Python", "level": "senior", "years": 7, "evidence_type": "evidenced"},
    ...
]
```

---

## UI Contract (NEW — encoding specified)

### Current encoding (must change)
`POST /profile/save` currently reads skills from a single comma-separated `<input name="skills">` field:
```
skills=Python, SQL, Django
```
The handler splits on commas and stores `list[str]`. This will need to change to carry level/years/evidence.

### New encoding — JSON payload in hidden field
Skills are serialised as JSON in a hidden form field `skills_json`:
```html
<input type="hidden" name="skills_json" value='[{"name":"Python","level":"senior","years":7,"evidence_type":"evidenced"}]'>
```
JavaScript on the profile page updates `skills_json` from the table rows on form submit.

The server handler in `job_hunt_ui.py` reads `skills_json` first; falls back to `skills` (comma split) if not present — this preserves backward compat for any non-JS path.

```python
# In POST /profile/save handler
raw_skills_json = form.get("skills_json")
if raw_skills_json:
    skills_raw = json.loads(raw_skills_json)  # list of dicts
else:
    skills_raw = [s.strip() for s in form.get("skills", "").split(",") if s.strip()]  # plain strings fallback
```

### My Profile skills table (HTML)
Each row has:
- Skill name (text input)
- Level (select: Junior / Mid / Senior / Expert / Unspecified)
- Years (number input, min=0, optional)
- Evidence (select: Self-reported / Evidenced)
- Delete row button

"Add skill" button appends a blank row. On form submit, JS collects all rows into `skills_json`.

### Display-only path (`GET /profile`)
`profile_obj.skills[:10]` join — currently `", ".join(profile_obj.skills[:10])` at line 1556.
Must change to `", ".join(s.name for s in profile_obj.skills[:10])`.

---

## Files to Change

| File | Change | Specific sites |
|------|--------|----------------|
| `src/job_hunt_models.py` | Add `Skill` dataclass; change `CandidateProfile.skills: list[Skill]` | — |
| `src/job_hunt_profile.py` | `_coerce_skill()` with strict validation; update to_dict/from_dict | `candidate_profile_from_dict()`, `candidate_profile_to_dict()` |
| `src/job_hunt_scoring.py` | Access `s.name` instead of `s` in skill-matching loops | All skill iteration sites |
| `src/job_hunt_tailoring.py` | Fix `.strip()` calls on skill elements | Lines 22, 121 |
| `src/job_hunt_cover_letter.py` | Fix `_match_skills()` to accept `list[Skill]` | Lines 158–160 |
| `src/job_hunt_ui.py` | Skills table UI; `skills_json` encoding; fix display join (line 1556); update `POST /profile/save` parser | Lines 1556, 1667–1668, 305, save handler |
| `docs/data_contract.md` | Update profile skills contract section: `skills: list[Skill]`, serialisation shape | — |
| `tests/test_models.py` | Add `Skill` validation tests | New |
| `tests/test_profile.py` | Plain-string backward compat; dict round-trip; invalid type rejection | Update fixtures |
| `tests/test_scoring.py` | Update fixtures: `skills` must be `list[Skill]` not `list[str]` | All profile fixtures |
| `tests/test_tailoring.py` | Update profile fixtures to `list[Skill]` | All profile fixtures |
| `tests/test_cover_letter.py` | Update profile fixtures to `list[Skill]` | All profile fixtures |

---

## Fixture Migration Note

Every test that constructs a `CandidateProfile` with a `skills` list must be updated.
Current pattern:
```python
profile = CandidateProfile(skills=["Python", "SQL"])
```
New pattern:
```python
profile = CandidateProfile(skills=[Skill(name="Python"), Skill(name="SQL")])
```
A shared `make_profile(**kwargs)` test helper in `tests/conftest.py` is the recommended pattern —
update the helper once, all tests that use it get the fix automatically.

---

## Acceptance Criteria

1. `Skill` dataclass validates name (non-empty), level (5 values), evidence_type (2 values), years (≥0)
2. Plain-string `skills` in existing JSON files load correctly as `Skill(name=str)` with defaults
3. Invalid skill entry types (int, list, dict without `name`) raise `ProfileValidationError`
4. After save, files are written in full `Skill` dict format
5. Scoring: skill match rate is unchanged for the same skill names
6. `tailor_cv()` and `validate_tailored_cv()` work correctly with `list[Skill]` — no `AttributeError`
7. `generate_cover_letter_text()` works correctly with `list[Skill]` — no `AttributeError`
8. `GET /profile` returns skills with level/years/evidence_type fields
9. `POST /profile/save` accepts `skills_json` (dict list) and falls back to comma-split `skills`
10. My Profile screen shows level/years/evidence columns; JS encodes rows to `skills_json` on submit
11. All existing profile, scoring, tailoring, and cover letter tests pass after fixture migration

---

## Test Command

```bash
python3 -m pytest tests/test_models.py tests/test_profile.py tests/test_scoring.py tests/test_tailoring.py tests/test_cover_letter.py -v
```
