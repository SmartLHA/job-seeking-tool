# GAP-C/I — Source Feature Flag (Adzuna / LinkedIn)

**Status:** ✅ Complete (2026-06-17)
**Date:** 2026-06-16 (designed) · 2026-06-17 (implemented)
**Decision:** `get_enabled_sources()` in config + `JobSource` registry pattern; routes are generic

---

## Goal

The Find Jobs screen shows Reed / Adzuna / LinkedIn source toggles. Reed is fully wired.
Adzuna has a normaliser but no fetch client connected to the orchestrator.
LinkedIn has no implementation at all.

This design gates the UI cleanly so only wired sources are selectable, without removing
the toggle UI — it future-proofs the design as sources come online.

---

## Config Change

Add to `job_hunt_config.py`:

```python
# Sources that are fully wired end-to-end (fetch + normalise + orchestrator)
# Add a source here only when its client and orchestrator path are complete and tested.
ENABLED_SOURCES: list[str] = ["Reed"]

def get_enabled_sources() -> list[str]:
    return ENABLED_SOURCES
```

This is the single place to flip when Adzuna or LinkedIn become ready.

---

## UI Behaviour

`GET /sources` (new lightweight route) returns the enabled list:

```
GET /sources
Response: { enabled: ["Reed"] }
```

The Find Jobs screen calls this on load. For each source toggle:
- **Enabled** (in list) → toggle is active and selectable
- **Not enabled** → toggle is shown but greyed out with a tooltip: "Coming soon"

This means the UI does not need to be changed when a new source goes live — only the config.

---

## What Was Built (2026-06-17)

`get_enabled_sources()` and `ENABLED_SOURCES` were implemented as designed. In addition,
a full `JobSource` registry pattern was introduced (`src/job_sources/source_registry.py`)
making routes generic — no separate route is needed per source.

Routes implemented:
- `GET /search/{source}` — dispatches to `source.search_handler`
- `POST /select/{source}` — dispatches to `source.select_handler`

Reed is registered at the bottom of `job_hunt_ui.py` as a `JobSource` frozen dataclass.

## Adzuna Wiring (when ready — P5-1)

Now that the registry is in place, wiring Adzuna is much simpler:
1. Create `src/job_sources/adzuna_source.py` implementing the `JobSource` adapter:
   - `is_available()` — checks `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` env vars
   - `normalize_search_params()`, `search_handler()`, `select_handler()`
   - `render_search_form()`, `render_results()`
2. Add `from src.job_sources import adzuna_source as _adzuna_src` to `job_hunt_ui.py`
   (the module-level import triggers `register()` at import time)
3. Add `"adzuna"` to `ENABLED_SOURCES` in `src/job_hunt_config.py`

The UI toggle activates automatically; no route changes needed.

---

## Files to Change

| File | Change |
|------|--------|
| `src/job_hunt_config.py` | Add `ENABLED_SOURCES` list + `get_enabled_sources()` |
| `src/job_hunt_ui.py` | Add `GET /sources` route; call `get_enabled_sources()` |
| `tests/test_ui.py` | `GET /sources` returns `["Reed"]`; test that default config has Reed only |

---

## Acceptance Criteria

1. `get_enabled_sources()` returns `["Reed"]` with the current default config
2. `GET /sources` endpoint returns `{ enabled: ["Reed"] }`
3. Find Jobs UI: Reed toggle is active; Adzuna and LinkedIn toggles are greyed out with "Coming soon"
4. Adding `"Adzuna"` to `ENABLED_SOURCES` makes the Adzuna toggle active without other UI changes
5. No Adzuna or LinkedIn fetch is attempted unless explicitly enabled

---

## Test Command

```bash
python3 -m pytest tests/test_ui.py -v -k "sources"
```

## Source Key vs Display Label (resolved)

`source_id` in the `JobSource` dataclass uses lowercase kebab (`"reed"`, `"adzuna"`).
`ENABLED_SOURCES` also uses lowercase. `display_name` (`"Reed"`, `"Adzuna"`) is separate
and used only for UI labels. This avoids the case-mismatch risk noted in the original design.
