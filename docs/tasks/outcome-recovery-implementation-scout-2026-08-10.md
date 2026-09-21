# Outcome Recovery Implementation Scout — 2026-08-10

## Conclusion

The existing implementation is well suited to a dedicated, history-preserving
reset operation. Do not add reset transitions to the ordinary state machine.
Instead, add a narrowly-scoped domain function that accepts only a current
`rejected` or `withdrawn` outcome and appends a new `not_applied` event. The
previous terminal event remains in `history`; the new event's note should be
server-generated and state the previous status, optionally followed by a
bounded user reason. The normal `update_outcome()` function remains unchanged.

The route can follow `POST /outcome`: load, reset, save JSON, upsert the
SQLite index, and render the job page with the existing embedded-page handling.
The detail-page view-model already derives the allowed status options from the
current JSON outcome, so it will immediately show `not_applied` after reset.

## Current data contract and persistence

| Concern | Evidence | Current behaviour |
|---|---|---|
| Outcome status enum | `src/job_hunt_models.py:193-200` | `not_applied`, `applied`, `interview`, `rejected`, `offer`, `withdrawn`. |
| Event fields | `src/job_hunt_models.py:279-282` | `OutcomeEvent(status, updated_at, notes)`. There is no event type, actor, or reset flag. |
| Record fields | `src/job_hunt_models.py:290-309` | `ApplicationOutcome(job_id, status, updated_at, notes, history)` requires a non-empty history and requires its final event to equal the current fields. |
| Normal transition rule | `src/job_hunt_outcomes.py:37-44`, `70-94`, `208-213` | `rejected` and `withdrawn` only permit same-status note updates; ordinary updates append one event after transition validation. |
| JSON format | `src/job_hunt_outcomes.py:97-112` | Current fields and every history item serialize as `status`, `updated_at`, `notes`; this already supports an append-only reset event without migration. |
| JSON validation/load | `src/job_hunt_outcomes.py:115-164`; `src/job_hunt_storage.py:152-168` | Storage writes `state/outcomes/<job_id>.json` atomically through the existing JSON helper and rebuilds the typed record on load. |

### Minimal compatible reset shape

Add `reset_terminal_outcome(outcome, *, updated_at=None, reason=None)` to
`src/job_hunt_outcomes.py`:

1. Validate `outcome.status in {"rejected", "withdrawn"}`; otherwise raise
   `OutcomeValidationError`.
2. Reuse the existing timestamp and note normalisers.
3. Append one `OutcomeEvent(status="not_applied", updated_at=..., notes=...)`.
4. Return a new `ApplicationOutcome` whose current fields mirror that event.

Recommended note grammar: `Tracking reset from rejected.` or `Tracking reset
from withdrawn. Reason: <cleaned reason>`. This uses only the current schema,
keeps the terminal event intact, and makes the reset visible after a JSON
round-trip. It must not call, weaken, or extend `_ALLOWED_TRANSITIONS`.

## Handler and route path

| Layer | Exact location | Required change |
|---|---|---|
| Handler imports | `src/ui_handlers.py:58`, `74-85` | Import the new domain function; current storage and index dependencies are already present. |
| Existing update handler | `src/ui_handlers.py:1215-1241` | Reuse its load/save/error/render pattern in a dedicated `handle_outcome_reset`; do not overload normal status update semantics. |
| Index synchronization | `src/ui_handlers.py:1238-1239` | Call `_upsert_job_to_index(config, job_id, outcome=outcome)` after reset exactly as normal update does. |
| Route imports | `src/ui_routes.py:45-65` | Import the handler. |
| POST dispatch | `src/ui_routes.py:442-444` | Add a distinct POST route, recommended `/outcome/reset`, adjacent to `/outcome`. Existing route-level loopback/origin/body protections apply before dispatch. |
| Page model | `src/ui_handlers.py:2841-2861` | It derives `outcome_status_options` from `allowed_next_statuses(outcome.status)`; no data-model extension is necessary. |

Handler input should require a non-empty `job_id` and an explicit confirmation
field (for example `confirm_reset=1`). A reset request for no outcome, a
non-terminal current status, or missing confirmation should render the job
page with existing outcome error feedback. Preserve `embed=1`, just as
`handle_outcome()` does, so Review Queue embeds do not escape their frame.

## Detail UI path

| Concern | Evidence | Required change |
|---|---|---|
| Job-page model fields | `src/ui_render.py:701-708`; `src/ui_handlers.py:2853-2857` | The renderer knows only current status/options/notes/time; it does not receive outcome history and does not need it for reset. |
| Outcome card | `src/ui_render.py:1678-1743` | The status select contains only legal transitions. When no next transitions exist, it says the status is final and only notes may be updated. Replace this terminal copy with a reset explanation and a separate confirmed reset form/button for `rejected`/`withdrawn`. |
| Existing form | `src/ui_render.py:1726-1741` | `POST /outcome` already carries job id and optional `embed`; the reset form should carry the same values plus `confirm_reset=1` and a separate optional reset-reason field. |
| XSS safety | `src/ui_render.py:1722-1737` | Current display uses `escape`; continue escaping current status/reason values. |

Keep the normal Save outcome form visible for terminal same-status note edits.
Place the reset control in a visually distinct warning block, explaining that
it creates a new `not_applied` tracking event and keeps the prior history.
The confirmation may be a required checkbox plus a disabled-until-checked
button, but server confirmation remains mandatory.

## Board/index consistency

| Concern | Evidence | Effect after reset |
|---|---|---|
| Upsert writes current outcome status/time | `src/job_hunt_index.py:228-277` | Existing upsert will change the job row to `not_applied` and the new reset timestamp. |
| Board transition metadata | `src/job_hunt_index.py:112-121`, `280-285` | Index has a separate display-only transition map that does not include same-status options. It will show normal `not_applied` onward transitions after upsert. |
| Board stats | `src/job_hunt_index.py:298-330` | Reset moves the job from terminal columns into active counts on the next query, which is consistent with reopening tracking. |
| Rebuild | `src/job_hunt_index.py:333-385` | Rebuild reads the current status from JSON; history does not need indexing. |

The index's `_ALLOWED_TRANSITIONS` is intentionally not the domain authority;
do not add reset transitions there. It is refreshed from the JSON outcome by
the handler's existing upsert.

## Best tests and minimal additions

| Test level | Existing location | Minimal reset coverage |
|---|---|---|
| Domain | `tests/test_outcomes.py:20-65` | Reset rejected and withdrawn; assert old terminal event remains, final event is `not_applied`, reset reason is recorded, original object unchanged; reject `applied`, `interview`, `not_applied`, and `offer`. Reassert ordinary rejected→not_applied remains invalid. |
| Serialization | `tests/test_outcomes.py:58-70`; `tests/test_storage.py:168-184` | Reset JSON round-trip and saved/reloaded outcome preserve all three events. |
| HTTP/UI | `tests/test_ui.py:1291-1346` | Evaluate fixture job, move it to rejected/withdrawn, POST reset with confirmation, assert success page/current status/history/index result; test missing confirmation and reset of applied return outcome error feedback; test `embed=1` remains embedded. |
| View render | Existing job-page render tests in `tests/test_ui.py` | Assert terminal UI includes distinct reset form/control only for rejected/withdrawn, not for offer or active statuses; retain correct final-status text. |
| Index | `tests/test_index.py:166-209` | Either route test asserts query row status, or add a direct JSON reset + `rebuild_index` regression. |

## Backlog/documentation location

`PROJECT_TODO.md:364-368` is the source backlog item. On completion, mark it
done with the verified test result, update `PROJECT_LOG.md`, and update the
outcome/Board sections in current product and user-flow documentation under
the project's documentation checklist.

## Risks to preserve

1. Do not make reset a generic state transition or accept a caller-selected
   reset target: the only target is `not_applied`.
2. Do not mutate or delete history; current dataclasses make immutable-return
   patterns straightforward.
3. Do not create an outcome record solely to reset an untracked job.
4. Do not treat `offer` as resettable under this approved terminal-outcome
   scope: it is non-terminal in the domain graph because it may become
   `withdrawn`.
5. Preserve existing loopback/origin protections by routing through the normal
   `do_POST` path; do not add a bypass endpoint.
