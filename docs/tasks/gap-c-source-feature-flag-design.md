# GAP-C/I — Source Feature Flag (Adzuna / LinkedIn)

**Status:** Ready to build
**Date:** 2026-06-16
**Decision:** Add `get_enabled_sources()` to config; UI hides unwired source toggles

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

## Adzuna Wiring (when ready — not in this ticket)

When Adzuna is ready to wire:
1. Implement `fetch_adzuna_jobs(keyword, location, max_results)` in `job_sources/adzuna_client.py`
2. Add `run_adzuna_evaluation_flow()` or extend `run_reed_evaluation_flow()` to handle multiple sources
3. Add `"Adzuna"` to `ENABLED_SOURCES` in config
4. Add `GET /search/adzuna` route (or extend `/search/reed` to accept `source` param)

The UI toggle will automatically become active once `"Adzuna"` appears in `/sources`.

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

## Source Key vs Display Label

`ENABLED_SOURCES` uses display-friendly strings that match what the UI shows users.
Verify before build that the internal source key used in route handlers and Reed search calls
matches this string exactly (e.g. `"Reed"` not `"reed"` or `"reed_api"`).
Check the existing `GET /search/reed` handler and normaliser to confirm the canonical key,
and align `ENABLED_SOURCES` to it.
