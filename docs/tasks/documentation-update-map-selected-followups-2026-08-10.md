# Documentation Update Map — Outcome Recovery and Search Triage Follow-ups

**Purpose:** precise, minimal documentation changes after Outcome Recovery, TRIAGE-F2, TRIAGE-F3, TEST-F1, and TEST-F2.  This is an implementation hand-off, not a historical rewrite.

## Conclusions

1. Add one new dated entry at the top of `PROJECT_LOG.md`; preserve all earlier entries as historical evidence.
2. Mark the five completed backlog items done in `PROJECT_TODO.md`; leave TEST-F3 pending unless coverage was actually refreshed in this change.
3. Update the public contracts in `function_list`, `product_spec`, `user_flow`, and `INDEX` for reset, bounded look-ahead, and the Hidden Jobs live filter.
4. `search-triage-not-interested-design.md` is the primary design spec requiring a fresh status block; `gap-h-board-aggregate-design.md` needs the outcome-reset status/write-path amendment.
5. The 2026-07-21 search plan is historical: retain its completed original-slice status, but label the body as historical rather than leaving “not approved” wording.
6. Correct three direct stale LinkedIn claims, plus one stale historical body in the feature-flag design.

## Exact update map

| File | Location | Minimal accurate update |
|---|---:|---|
| `PROJECT_LOG.md` | 1-6 | Insert a new 2026-08-10 entry. State: terminal outcomes can be confirmed-reset to `not_applied` while retaining event history; More uses bounded filtered-page look-ahead; Hidden Jobs overlay has a live text filter; TEST-F1/F2 harden test behaviour. Add the fresh test command/result only when verified in this working tree. |
| `PROJECT_TODO.md` | 8 | Bump **Last updated** using fresh test totals only. |
| `PROJECT_TODO.md` | 354-360 | Mark TRIAGE-F2 and TRIAGE-F3 done. F2 wording must say bounded server-side look-ahead only when a More page is fully filtered, preserving independent keyword cursors. F3 wording must say client-side, live overlay filtering. |
| `PROJECT_TODO.md` | 366-368 | Mark OUTCOME-F1 done: only `rejected`/`withdrawn`, confirmation required, event history retained, resulting current status `not_applied`. |
| `PROJECT_TODO.md` | 386-392 | Mark TEST-F1 and TEST-F2 done with their actual strengthened/isolation contracts. |
| `PROJECT_TODO.md` | 394-396 | Leave TEST-F3 pending unless a fresh coverage refresh was completed and recorded. |
| `INDEX.md` | 115, 120, 122-126 | Refresh test-map descriptions: outcome reset coverage; browser UI coverage now includes search chips and Hidden Jobs filter; TEST-F1/F2 test descriptions should reflect their regression contracts without stale counts. |
| `INDEX.md` | 171-172 | Pagination row: add bounded filtered-page look-ahead. Triage row: add live Hidden Jobs query filter and the new browser coverage. |
| `INDEX.md` | 203 | Add `reset_terminal_outcome`, `handle_outcome_reset`, and `POST /outcome/reset`; make clear that reset appends history rather than overwriting it. |
| `docs/function_list.md` | 13, 19, 38, 43 | Add/reset handler and domain helper; document overlay filter; clarify filtering plus bounded More look-ahead without implying hidden records are deleted. |
| `docs/function_list.md` | 53-54 | Update discovery/pagination contract: a More request may inspect a bounded number of subsequent raw pages only after filtering leaves no visible result; cursor state remains source-normalised and independent per keyword. |
| `docs/function_list.md` | 59-60 | Add `POST /outcome/reset` and the terminal-only, append-history contract. |
| `docs/product_spec.md` | 3, 24, 29 | Bump update date. Search-triage row gains F2/F3; tracker/outcome row gains confirmed terminal reset and history preservation. |
| `docs/user_flow.md` | 31-35 | State that More may make a bounded internal look-ahead to avoid a wholly hidden page; Hidden Jobs overlay can be filtered live by its visible text. |
| `docs/user_flow.md` | 110-116 | Add the rejected/withdrawn branch: user confirms Reset tracking, server records an auditable reset event, status becomes `not_applied`; generic dropdown state-machine remains unchanged. |
| `docs/tasks/search-triage-not-interested-design.md` | 3-8 | Replace status header with 2026-08-10 status naming implemented F2 and F3, key functions/routes/tests, and any intentional divergence. |
| `docs/tasks/search-triage-not-interested-design.md` | 39-41, 61-72, 80-82 | Add the bounded More rule (cap/exhaustion then placeholder), live Hidden Jobs text filter, edge cases (all hidden, cap, multikeyword cursor), and browser tests. Remove F2/F3 from non-goals. |
| `docs/tasks/gap-h-board-aggregate-design.md` | 3-4, 125-134, 153-165 | Update status for the Job Detail reset affordance. Add a reset write path (`POST /outcome/reset`, append event + current-status/index update). Keep Board View read-only; do not revive its historical drag-and-drop path. |
| `docs/tasks/2026-07-21-search-score-filter-plan.md` | 3-31 | Keep the four original slices marked complete. Add a short historical-status note that F2 is documented in the triage design; replace the contradictory “NOT approved for build” wording with “historical planning body”. Do not retrofit its original scope/counts. |
| `docs/tasks/pl-01-reed-search-first-shell-design.md` | 3-10 | Replace contradictory “Design draft — review pending” with a historical/implemented label. This is cleanup, not a feature-spec change. |

## Design-spec status headers

Add or revise a current status header in these design documents:

- `docs/tasks/search-triage-not-interested-design.md` — required; primary F2/F3 contract.
- `docs/tasks/gap-h-board-aggregate-design.md` — required; outcome-reset write path and read-only board constraint.
- `docs/tasks/2026-07-21-search-score-filter-plan.md` — short historical-status clarification only; do not rewrite its original delivered scope.
- `docs/tasks/pl-01-reed-search-first-shell-design.md` — remove its contradictory review-pending marker.

## Stale LinkedIn locations

| File | Location | Correction |
|---|---:|---|
| `PROJECT_TODO.md` | 154 | Replace “remaining wiring” wording: LinkedIn is already registered and enabled. |
| `PROJECT_TODO.md` | 194 | Remove “`ui_routes.py` wiring + `ENABLED_SOURCES` still needed”; keep it as a completed source. |
| `docs/function_list.md` | 67 | Replace “requires import and enabled entry to appear” with current registered/enabled source description. |
| `INDEX.md` | 37 | Optional wording cleanup: do not describe LinkedIn as gated “until wired”. |
| `docs/tasks/gap-c-source-feature-flag-design.md` | 18-20 | Historical body says Reed-only/LinkedIn unimplemented despite its current header. Label it historical or reconcile it with the header. |

## Preservation rules

- Do not alter old project-log entries or historical test totals just to make them match current state.
- Do not mark TEST-F3 complete unless the requested coverage work ran and its result is available.
- Do not say reset is a normal reverse transition: it is an explicit terminal-outcome recovery operation with a confirmation gate and immutable history.
- Do not claim F2 changes the existing cursor model: it must preserve separate main/Other buckets and per-keyword cursors.
