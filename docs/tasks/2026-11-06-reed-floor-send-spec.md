# Send the saved-search salary floor to Reed (spec, 2026-11-06)

Status: APPROVED. Mike, 2026-11-06, answering "Build from this spec?": "Approve, build it".

Decision: Mike, 2026-11-06, answering "Should the salary floor stay local-only for now?":
"Send it to Reed too". This reverses the choice in
`docs/tasks/2026-11-05-saved-search-salary-failure-runs-spec.md` (lines 73-77, and out of scope at
line 402). Evidence kept locally, not in git.

Base: `claude/agitated-sinoussi-7cc5be` (PR #5, commit `4a515fd`). Build on
`claude/upbeat-mendeleev-6981ed` in its own commits, as a separate PR that lands after PR #5.
PR #5 itself is not changed. Builder: `implementer` agent, then `verifier`.

## What changes for Mike

- A Reed saved search with a floor asks Reed for jobs at or above that floor. The same run path
  serves scheduled digests and Run now.
- The first 50 jobs hold no below-floor jobs in the live sample, so more of them are candidates,
  and more clear matches fall inside the first 10 attempts.
- Accepted cost: Reed removed some of the no-salary jobs in the live check. The tool cannot see or
  count them.

## Behaviour

1. Send `minimumSalary` on a Reed saved-search run when `_salary_floor` returns a number, as a whole
   number. This covers searches with or without their own saved `resultsToTake`.
2. The local rule (`_salary_verdict`) stays exactly as it is. It still covers Adzuna, and it still
   protects Reed searches if Reed changes what the floor does.
3. Do not send it for:
   - a blank, zero or non-numeric floor;
   - the Reed search page or "More results". A short page ends paging there
     (`src/ui_handlers.py:1078-1082`), which is why the earlier spec kept the floor off that page
     (lines 138-141);
   - Adzuna or LinkedIn saved searches.
4. Read size and the 10-attempt budget do not change.
5. The run line gets no new count and no new wording. `jobs_below_floor` will usually be 0 for Reed
   and "fetched" will be lower. "returned no jobs"
   (`src/job_hunt_saved_searches.py:464-465`) stays true when Reed filters everything out.
6. The form hint at `src/ui_render.py:2803` says "Jobs with no listed salary are kept", which becomes
   false. New text: "Saved-search runs drop new jobs whose listed pay is below this. Jobs with no
   listed salary are kept, but Reed applies this floor too and may leave some of them out."

## Design

- `src/job_sources/reed_client.py`, `fetch_reed_jobs`: add keyword-only
  `minimum_salary: int | None = None`. Add `minimumSalary` to the request params only when it is not
  None.
- `src/job_sources/reed_source.py`, `search_reed_jobs_for_ui`: read
  `search_values.get("_reed_api_floor")`, and pass `minimum_salary=` only when that key is present.
  Calls without the key stay identical, so the 26 fixed-signature test fakes and the exact-arguments
  test (`tests/test_ui.py:685-690`) need no change.
- `src/job_hunt_scheduler.py`, `run_digest_pipeline`: after the fetch-size step (`:285`) and before
  `source.search_handler(params)`, when `salary_floor is not None and source_id == "reed"`, set
  `params["_reed_api_floor"] = str(int(salary_floor))`. It is set after normalising, so the search
  page and "More results" cannot carry it.
- `src/ui_render.py:2803`: the new hint text. No existing test pins the old text.

## Acceptance criteria

Tests inspect the outgoing request at `requests.get`, with no live Reed call.

- AC1: A Reed saved-search run with floor "<floor>" and no saved `resultsToTake` sends exactly one
  Reed request with `minimumSalary` equal to the floor as an integer and `resultsToTake` 50 at the default profile.
  `keywords`, `locationName`, `resultsToSkip` and `distanceFromLocation` are unchanged.
- AC2: With a saved `resultsToTake`, the floor is still sent and the saved value is respected as today.
- AC3: With floor "", "abc", "0" or no floor, the request has no `minimumSalary`. The existing
  `test_ac4_disabled_floor` still passes.
- AC4: A manual Reed search and "More results" with a minimum salary send no `minimumSalary`.
  `tests/test_ui.py:685-690` and the paging test at `tests/test_saved_search_salary_floor.py:224-251`
  pass unchanged.
- AC5: Adzuna and LinkedIn saved searches with a floor behave as before and do not receive
  `_reed_api_floor`.
- AC6: If a Reed reply still holds a below-floor job, it is dropped and counted. No-salary and
  day-rate jobs in the reply are kept as unknown.
- AC7: A failed Reed fetch with a floor gives the same failed run and error text as today.
- AC8: The form shows the new hint text.
- AC9: `_reed_api_floor` is not stored in the saved search, the run row or the job index, and does
  not appear in a "More results" link.
- AC10: Docs say the floor is sent on Reed saved-search runs: `INDEX.md:104`,
  `docs/product_spec.md:72`, `PROJECT_CONTEXT.md:122`, `PROJECT_TODO.md:46`, a new `PROJECT_LOG.md`
  entry, and a pointer to this spec at lines 73 and 402 of the 2026-11-05 spec. Follow
  `docs/docs-update-checklist.md`.
- AC11: `pytest tests/test_saved_search_salary_floor.py tests/test_ui.py tests/test_reed_failure_paths.py
  tests/test_reed_adzuna_clients.py` passes, and the full suite shows no new failure against the base
  commit. New behaviour has at least one new test.

After the build, Mike can press Run now once on a real Reed saved search. That is his call, because
it writes to the job index.

## Accepted risks

- Reed's rule is not documented, and the evidence is one search at one moment. A regional search or another floor may differ.
- Day rates under £250 were not seen in the live check, so they may or may not be removed.
- The first 50 jobs change once the floor is sent, so a job held over from an earlier no-floor run
  may no longer be read.
- Reed's sort order was not checked. If new jobs do not reach the first 50, a search stops finding
  jobs after about 5 runs (50 candidates at 10 per run).
- If too few no-salary jobs appear in practice, removing the scheduler step turns this off.

## Out of scope

- Sending the floor to Adzuna, or changing read size or the budget.
- Counting what Reed removes.
- `viewer/viewer_server.py:1910-1913` with `viewer/reed_jobs.js:49`, which may already send a floor
  from the older viewer. Whether that script is served is UNVERIFIED.
