# MT-2 Design — Extract shared validation helpers to `src/job_hunt_validation.py`

<!-- STATUS -->
> **Implementation status:** ✅ Implemented 2026-06-19 — 312 tests green (incl. 18 new validation unit tests). All 3 reviewer findings addressed.
> **Author:** Claude + Mic · **Date:** 2026-06-19
> **Goal:** One canonical set of field-validation helpers, behaviour-preserving, zero call-site churn.
<!-- /STATUS -->

## Problem

Five small validators are copy-pasted across three modules with **subtly different
behaviour**, so they have already silently diverged. Consolidating naively would
change validation semantics. The three modules:

- `job_hunt_storage.py` — raises `StorageError`
- `job_hunt_reviewed_input.py` — raises `ReviewedInputValidationError`
- `job_hunt_profile.py` — raises `ProfileValidationError`

All three exception types subclass `ValueError`, but **each module raises its own
type and tests assert those types**, so any shared helper must raise the *caller's*
exception class — not a single shared one.

## The actual behaviour differences (read from source, not assumed)

This table is the crux of the task. Each cell is verified against the current code.

| Helper | `storage` | `reviewed_input` | `profile` |
|---|---|---|---|
| **string list** | `_string_list`: no strip, **no** dedup, **allows empty** items, keeps raw | `_normalise_string_list`: **strip**, **dedup (casefold)**, **rejects empty** | `_normalise_string_list`: **strip**, **no** dedup, **rejects empty** |
| **required string** | `_required_string`: one combined check → msg *"must be a non-empty string"* | `_required_string`: two checks → *"must be a string"* / *"must not be empty"* | *(none)* |
| **optional string** | `_optional_string`: empty → **raise** | `_optional_string`: has `empty_as_none` flag (empty → None when set, else raise) | `_optional_string`: empty → **raise** |
| **optional text-or-empty** | *(none)* | *(none)* | `_optional_text_or_empty`: **allows empty**, returns `value or None` |
| **optional int** | `_optional_int`: **allows negative** (no `< 0` check) | `_optional_non_negative_int`: **rejects negative** | `_optional_non_negative_int`: **rejects negative** |
| **optional non-neg float** | *(`_required_number`: required, no neg-check — different shape)* | `_optional_non_negative_float`: rejects negative | `_optional_non_negative_float`: rejects negative |
| **optional bool** | `_optional_bool` | *(none)* | `_optional_bool` |

Three genuinely different `string_list` semantics and two different `optional_int`
semantics (negative allowed vs rejected) are the traps. The rest differ only in
**error message wording** and **exception type**.

## Design

### New module: `src/job_hunt_validation.py`

One canonical implementation per helper, **parameterised** to reproduce every
existing variant, with an injected `error` class so each module keeps its own
exception type:

```python
def required_string(value, field_name, *, message_style="split", error=ValueError) -> str: ...
def optional_string(value, field_name, *, empty_as_none=False, error=ValueError) -> str | None: ...
def optional_text_or_empty(value, field_name, *, error=ValueError) -> str | None: ...
def string_list(value, field_name, *, strip=False, dedup=False,
                allow_empty_items=True, error=ValueError) -> list[str]: ...
def optional_int(value, field_name, *, non_negative=False, error=ValueError) -> int | None: ...
def optional_non_negative_float(value, field_name, *, error=ValueError) -> float | None: ...
def optional_bool(value, field_name, *, error=ValueError) -> bool | None: ...
def required_number(value, field_name, *, error=ValueError) -> float: ...
```

**`message_style` (reviewer finding #1).** `required_string` takes
`message_style="combined" | "split"` so the message text is preserved exactly per
module — no wording change anywhere:
- `"combined"` (storage) → single message `"{field} must be a non-empty string"`.
- `"split"` (reviewed_input, default) → `"{field} must be a string"` then
  `"{field} must not be empty"`.

**`bool` rejection is part of the contract (reviewer finding #2).** Python treats
`bool` as a subclass of `int`, so every numeric helper MUST reject `True`/`False`
explicitly with `isinstance(value, bool)` guards — preserving current behaviour in
all three modules. This applies to `required_number`, `optional_int`, and
`optional_non_negative_float`. It is an explicit acceptance criterion (see Tests).

`string_list` flags map the three variants exactly:
`strip` (whitespace-trim items), `dedup` (case-insensitive, order-preserving),
`allow_empty_items` (keep "" vs raise on empty/whitespace items).

### Binding pattern — **zero call-site changes**

Each module keeps its existing private names, but **redefines them as
`functools.partial`** bindings of the canonical functions. Every existing call
site (`_optional_string(x, "name")`, etc.) keeps working unchanged because the
`error` class (and the behaviour flags) are pre-bound:

```python
# job_hunt_profile.py
from functools import partial
from src import job_hunt_validation as _v

_normalise_string_list      = partial(_v.string_list, strip=True, dedup=False,
                                       allow_empty_items=False, error=ProfileValidationError)
_optional_string            = partial(_v.optional_string, error=ProfileValidationError)
_optional_text_or_empty     = partial(_v.optional_text_or_empty, error=ProfileValidationError)
_optional_non_negative_int  = partial(_v.optional_int, non_negative=True, error=ProfileValidationError)
_optional_non_negative_float= partial(_v.optional_non_negative_float, error=ProfileValidationError)
_optional_bool              = partial(_v.optional_bool, error=ProfileValidationError)
```

### Exact binding map (reproduces current behaviour)

**`job_hunt_storage.py`**
| old name | binding |
|---|---|
| `_string_list` | `string_list(strip=False, dedup=False, allow_empty_items=True, error=StorageError)` |
| `_required_string` | `required_string(message_style="combined", error=StorageError)` |
| `_optional_string` | `optional_string(error=StorageError)` |
| `_optional_int` | `optional_int(non_negative=False, error=StorageError)` |
| `_optional_bool` | `optional_bool(error=StorageError)` |
| `_required_number` | `required_number(error=StorageError)` |

**`job_hunt_reviewed_input.py`**
| old name | binding |
|---|---|
| `_required_string` | `required_string(error=ReviewedInputValidationError)` |
| `_optional_string` | `optional_string(error=ReviewedInputValidationError)` — callers may still pass `empty_as_none=True` |
| `_normalise_string_list` | `string_list(strip=True, dedup=True, allow_empty_items=False, error=ReviewedInputValidationError)` |
| `_optional_non_negative_int` | `optional_int(non_negative=True, error=ReviewedInputValidationError)` |
| `_optional_non_negative_float` | `optional_non_negative_float(error=ReviewedInputValidationError)` |

**`job_hunt_profile.py`**
| old name | binding |
|---|---|
| `_normalise_string_list` | `string_list(strip=True, dedup=False, allow_empty_items=False, error=ProfileValidationError)` |
| `_optional_string` | `optional_string(error=ProfileValidationError)` |
| `_optional_text_or_empty` | `optional_text_or_empty(error=ProfileValidationError)` |
| `_optional_non_negative_int` | `optional_int(non_negative=True, error=ProfileValidationError)` |
| `_optional_non_negative_float` | `optional_non_negative_float(error=ProfileValidationError)` |
| `_optional_bool` | `optional_bool(error=ProfileValidationError)` |

## Behaviour preservation (revised after review)

**Fully behaviour-preserving, including messages.** With the `message_style`
parameter, `storage._required_string` keeps its exact `"must be a non-empty
string"` wording and `reviewed_input` keeps its split wording. No message text
changes in any module; same inputs accepted/rejected; same exception types. The
original goal ("behaviour-preserving") now holds literally — finding #1 resolved.

## Tests for `src/job_hunt_validation.py` (acceptance criteria)

Beyond the per-flag combinations, these explicitly lock the traps the reviewer
called out:

- **`bool` rejection (finding #2):** `required_number(True, ...)`,
  `optional_int(True, ...)`, and `optional_non_negative_float(False, ...)` each
  raise `error` — `True`/`False` are never accepted as numbers/ints, in every
  module's binding.
- **`message_style` (finding #1):** `required_string("", message_style="combined")`
  → `"... must be a non-empty string"`; `required_string("", message_style="split")`
  → `"... must not be empty"`; `required_string(5, message_style="split")`
  → `"... must be a string"`.
- **`optional_text_or_empty` whitespace (finding #3):** `optional_text_or_empty(" ")`
  returns `" "` (NOT stripped, NOT `None`) — locks the documented-but-surprising
  `value or None` behaviour so extraction can't silently "fix" it. (`""` → `None`,
  `None` → `None`, non-str → raise.)
- **`string_list` variants:** empty-item handling (`storage` keeps `""`, others
  raise), dedup casefold (`["SQL","sql"]` → `["SQL"]` only for reviewed_input),
  strip (storage keeps raw, others trim).
- **`optional_int` negatives:** `non_negative=False` accepts `-1` (storage);
  `non_negative=True` rejects `-1` (reviewed_input, profile).
- **exception type:** each binding raises its module's `*Error` (asserted via the
  pre-bound `error=`).

## Migration steps (each step keeps tests green)

1. Create `src/job_hunt_validation.py` with the 8 canonical functions + unit tests
   for each flag combination (strip/dedup/allow_empty, non_negative, empty_as_none).
2. Repoint `job_hunt_storage.py` helpers to `partial` bindings. Run full suite.
3. Repoint `job_hunt_reviewed_input.py`. Run full suite.
4. Repoint `job_hunt_profile.py`. Run full suite.
5. Delete the now-unused original helper bodies (the `partial` lines replace them).
6. Update docs (PROJECT_LOG, PROJECT_TODO, INDEX feature map, function_list_v4).

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Subtle `string_list` divergence (strip/dedup/empty) collapses incorrectly | Parameterised flags reproduce each variant exactly; dedicated unit tests per flag combo |
| `optional_int` negative-handling differs (storage allows neg) | `non_negative` flag, bound per module per the map above |
| Exception type must stay per-module | `error=` injected via `partial`; verified by existing `pytest.raises(XError)` tests |
| Error-message wording drift | `message_style` param keeps each module's exact wording — no change (finding #1) |
| `bool` silently accepted as int | Explicit `isinstance(value, bool)` guards + dedicated tests (finding #2) |
| Extraction "fixes" `optional_text_or_empty` whitespace | Locked by a `" "` → `" "` test (finding #3) |
| `empty_as_none` (reviewed_input only) | Kept as a per-call kwarg on the canonical `optional_string`; partial binds only `error` |

## Out of scope
- No new validation rules or stricter checks — pure dedup, behaviour-preserving.
- `_required_number` (storage) and `_resolve_local_path` (profile) are left where
  they are unless trivially shared; `_required_number` is included only because it
  is a clean 1:1 move.
