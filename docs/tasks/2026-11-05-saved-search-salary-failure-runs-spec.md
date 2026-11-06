# Saved searches: salary floor, visible Reed failures, kept run results

<!-- STATUS: APPROVED r4 2026-11-05. Mike answered "Approve the design with all three
recommendations (Q1–Q3)?" with "Approve, build it". So Q1 = keep and count jobs with no listed
salary; Q2 = keep a range that reaches the floor; Q3 = read 50 jobs, filter locally, at most 10
attempts per run. r2 to r4 apply three Codex design reviews (the third raised no HIGH issue)
and a fresh verifier check of r3 (0 BLOCKER, 0 MAJOR, 5 MINOR). The Gemini pre-check was
skipped: the brief bars Gemini calls without Mike's consent. -->

<!-- STATUS (implementation, 2026-11-05)
Implementation status: ✅ built on branch claude/agitated-sinoussi-7cc5be, NOT pushed, NOT merged.
Fresh verifier passed on 2026-11-06 at db4b58d: 0 BLOCKER, 0 MAJOR, 3 MINOR. Fresh Codex code review: 0 high, 0 medium, 1 low, fixed in db4b58d.
Commits (oldest first): ecb7c0b (ReedFetchError), 96c40f2 (local salary floor, 10-attempt budget),
1efe433 (saved_search_runs records), e3842ae (Run now summary, Last run and Run history display),
fac2eea (test registration fix), d8f4b24 (floor tests need no real key), c3107d6 (docs),
db4b58d (Run now refreshes the list after a failed reply).
Key functions: reed_client.ReedFetchError and fetch_reed_jobs; scheduler _salary_number,
_salary_floor, _salary_verdict, run_digest_pipeline(trigger=...), DigestRunResult (+3 counters);
saved_searches search_run_status, search_run_error, search_run_summary, record_search_run,
list_search_runs; ui_handlers handle_run_now, handle_saved_searches_list, _saved_search_to_json;
ui_render runNow and Run history in render_profile_page.
Routes: POST /saved-searches/{id}/run-now (adds run_status, summary), GET /saved-searches (adds runs).
Divergences: the partial Run now text adds "fetched F, N new" before the counts, which a test pins.
The AC20 harness starts the real handler through _build_handler rather than main() with --state-root,
and its fake Reed varies by keyword. AC19: 18 failures are outside the 46-line archive, all present at
the base in this environment. Section 7 items stay out of scope (Adzuna failures,
floor sent to Reed, 10-job read without a floor, floor on the Reed page, scheduled profile-load
failure record, stale text).
Evidence: full suite 64 failed, 2803 passed, 1 skipped, same 64 ids as base 401e48f (verifier run,
fake keys). Browser check of Run now and history used the real page handlers with synthetic data
and a fake Reed (producer evidence). No live Reed or Gemini call; the salary floor against a live
Reed response is UNVERIFIED. -->

## 1. Problem

Mike asked on 2026-11-05 why a saved search run had failed. No server error was found,
because the tool cannot show one. Code reading found these gaps:

| # | Gap | Evidence |
|---|---|---|
| 1 | The salary floor (`minimumSalary`) changes nothing. A search with a floor of 65000 returned a job at "£38,000 – £45,000". | `src/job_sources/reed_client.py:51-57`, `src/job_sources/reed_source.py:289-295`, no filter in `src/job_hunt_scheduler.py:189-315`; false note at `reed_source.py:393-395` |
| 2 | A Reed failure looks the same as "no new jobs". | `reed_client.py:47, 68, 79, 83, 86, 89` return `[]`; `runNow()` at `src/ui_render.py:3261-3272` ignores `d.errors` |
| 3 | A run result is not kept. Only `jobs_new` is stored, and only for Run now. Scheduled runs store nothing per search. | `src/ui_handlers.py:2613`; `DigestScheduler._maybe_run` keeps `_last_result` in memory only |

Two more traps found while reading, both handled here because they produce the same false
"Run done":

- **Reads only 10 jobs.** A saved Reed search stores no `resultsToTake`, so
  `normalize_reed_search_params` uses 10 (`reed_source.py:257, 273-277`). One run reads the
  first 10 results of one page. `digest_max_per_source` (default 50) never applies. A local
  filter over only 10 jobs would leave almost nothing.
- **Run now on a disabled search does nothing.** The pipeline skips it
  (`job_hunt_scheduler.py:190`) and the browser still says "Run done — 0 new".

## 2. What Reed documents

Source: <https://www.reed.co.uk/developers/jobseeker>, read directly on 2026-11-05.

- `minimumSalary` is a documented search parameter: "lowest possible salary e.g. 20000".
  It does not say whether it matches the bottom or the top of a job's range.
- The page does not say what happens to jobs with no listed salary when the floor is sent.
  It says only that for a hidden salary "none of the salary information will show".
- The search response lists Minimum Salary and Maximum Salary with no pay period. Only the
  details endpoint lists "Yearly Minimum Salary" and "Salary Type (per hour, per day, per
  week, per month, per annum)". So a search result figure may be a day rate.
- No error codes, rate limits or 429 are documented. Paging: `resultsToTake` is limited to 100.
- Third party, UNVERIFIED, search snippet only: an Apify scraper listing claims that setting
  a salary makes Reed drop jobs with no published salary
  (<https://apify.com/spookyweb/uk-jobs-reed/input-schema>).

## 3. Decisions

### Gap 1: filter locally; do not send the floor to Reed

Sending the floor could lose no-salary jobs and day-rate jobs, and the tool would have no
way to see or count that loss. Local filtering gives the same result whatever Reed does,
can be tested offline, and also covers Adzuna saved searches, which do not send it either
(`adzuna_source.py:199`). The cost is reach: Reed returns jobs below the floor, which use up
the fetch. Mitigation: read 50 instead of 10 when a floor is set, still one request, while
processing no more new jobs per run than today (see Fetch size below).

**Rule.** With floor F > 0, for each job not already indexed, the first matching row wins:

| Listed salary | Result | Count in |
|---|---|---|
| None listed, unreadable, or zero (**Q1**) | Keep | `jobs_salary_unknown` |
| Top of range (the larger of min and max) under £10,000, whatever F is: cannot be annual pay, so read as a rate of unknown period | Keep | `jobs_salary_unknown` |
| Top of range is F or more | Keep | |
| Top of range is below F | Drop before any Gemini call, detail request or DB write. One `below_salary_floor` line in the existing skipped-jobs log. | `jobs_below_floor` |

Examples with F = 65000: £38,000–£45,000 dropped; £60,000–£70,000 kept (**Q2**); £65,000
kept; £500–£700 kept as unknown; no salary kept as unknown.

**Known wrong case, accepted.** Reed search results give no pay period, so £12,000 listed per
month (£144,000 a year) reads as annual and is dropped against a floor of 65000. Checking the
details endpoint for every job below the floor would cost one Reed request per job, which is
out of proportion for a rare case. Each drop is logged with title and URL, so it can be checked.

Other points:

- The check goes right after the already-seen check (`job_hunt_scheduler.py:238`), before
  the LinkedIn detail request (`:239`) and skills extraction (`:261`). `jobs_already_seen`
  stays as it is today.
- A dropped job is not indexed, so every run looks at it again at no API or Gemini cost. If
  Mike lowers the floor it can come back.
- Jobs already indexed stay. The floor applies to new jobs only.
- An empty, non-numeric or zero floor means no filter. Fetch size stays as today.
- **Fetch size (Q3).** When a floor is set and the saved params have no `resultsToTake`, the
  pipeline sets `resultsToTake` to `min(50, profile.digest_max_per_source)` after
  `normalize_search_params`. An explicit saved value is respected, with no budget.
- **New-job budget.** A search whose fetch was raised starts at most as many evaluations in
  one run as it would have read before the raise (10). The budget counts attempts, not
  successes, so it limits skills extraction to 10 attempts even when an evaluation or a save
  fails. One attempt can make two Gemini requests, because the wrapper falls back to a second
  model (`job_hunt_llm.py:135-142`), the same as today. Checks run in this order for each
  result:
  1. Not a dict, or no job id: skipped as today. No budget used.
  2. Already seen: counted as today. No budget used. Its initialization repair still runs.
  3. Below the floor: dropped. No budget used. A blank-description result below the floor
     counts here, because this check runs first.
  4. Blank description: skipped as today. No budget used.
  5. Budget used up: adds to `jobs_held_over`, meaning not attempted in this run, with no
     further work. It is not indexed, so a later run can attempt it while it stays inside the
     first 50 and budget is left.
  6. Otherwise the attempt counter goes up immediately before the convert and evaluate block
     (`job_hunt_scheduler.py:258`), and the job continues as today.
- **The AI queue limit is the shared cap, not a per-search one.** The cap is per run (default
  10, `job_hunt_models.py:59`) and capped jobs are not queued later
  (`tests/test_digest_pipeline.py:211-224`). A floor search whose 10 new jobs all qualify can
  use all 10 slots where the old first 10 might have used fewer. With a cap set above 10, it
  can also queue repairs of unfinished initialization (`job_hunt_scheduler.py:235-237`) found
  in the wider read, on top of its 10 new jobs. Accepted: the configured cap still holds, and
  a search that ran first could already use the whole cap.
- **Which sources.** The floor and the fetch size apply only when the normalised params
  contain `minimumSalary` and `resultsToTake`: Reed and Adzuna. LinkedIn's normaliser drops
  the floor (`linkedin_source.py:179-191`) and it provides no salary (`:274`), so LinkedIn runs
  as it does today, and its run row has an empty `salary_floor`.
- **Reed search page.** No filter there: its "More" logic reads a short page as the last
  page (`ui_handlers.py:1078-1082`), so filtering would end paging early. Only the false
  note changes, to "Minimum salary is not applied on this page. It only filters saved-search
  runs." `tests/test_ui.py:697` asserts the old wording and is updated.
- **Saved-search form.** The hint under "Min salary (GBP)" (`ui_render.py:2803`) states the
  rule in one line.

### Gap 2: `fetch_reed_jobs` raises `ReedFetchError`

Every failure path raises `ReedFetchError(RuntimeError)`. Only a real response with no jobs
returns `[]`. A keyword flag or a new return type was rejected, because 23 test fakes have
the fixed signature `fake(keyword, location, max_results, *, skip=0, save_raw=True)`.
Raising leaves that call unchanged, and every production path already catches exceptions.

| Failure (`reed_client.py`) | Message |
|---|---|
| No key (`:47`) | `Reed API key is not set` |
| 429 (`:68`) | `Reed rate limit reached (HTTP 429)` |
| HTTP error (`:83`) | `Reed returned HTTP <status>`, adding `: check the API key` for 401 and 403 |
| Timeout (`:86`) | `Reed request timed out` |
| Other request error (`:86`) | `Reed request failed (<exception class name>)` |
| Bad JSON (`:89`) | `Reed returned invalid JSON` |
| Unexpected JSON shape (`:79`, silent today) | `Reed returned an unexpected response` |

Messages are fixed text, never `str(exc)`, so nothing from a request can reach the page.
Existing log lines stay.

- **Valid replies.** Only a plain list, or a dict whose `results` is a list, counts as a valid
  reply. `{}`, `{"error": ...}` and `{"results": null}` are unexpected responses. Today the
  first two give a false "no jobs" and the third escapes into later code
  (`reed_client.py:74-79`).
- **Catch order.** `requests`' own `JSONDecodeError` inherits `RequestException`, so today's
  catch order reports bad JSON as a request failure (`reed_client.py:84-89`). Decoding errors
  are caught first. The test covers both the `requests` and the standard-library exception.

| Caller | Effect |
|---|---|
| Digest pipeline, `job_hunt_scheduler.py:201` | Caught at `:202`. Becomes `<id>: fetch failed: <message>` and other searches continue. |
| Reed search page, `ui_handlers.py:1069` and the More path `:2133` | Caught. An error banner replaces a false "no results". The offset is kept for retry. This is a visible behaviour change, and it is wanted. |
| `job_hunt_orchestrator.py:186` | Propagates. `run_reed_evaluation_flow` has no caller in `src/`, only tests with fakes. Left as is. |
| `debug_reed.py`, `src/job_sources/test_fetch.py`, `reed_client.py:149` | Developer scripts: a traceback is acceptable. |
| `tests/test_reed_adzuna_clients.py:65, 76, 87, 97, 138` | These assert `[]` on failure. They are changed on purpose to assert the raise, because the behaviour they pin is the defect. |

**What Run now shows.** Python builds the status and the text, so they can be tested without
a browser. `to_dict()` does not change for this; `handle_run_now` adds the two keys to its
own payload (see Overlap, hazard 1).

| `run_status` | When | Text |
|---|---|---|
| `failed` | errors, 0 fetched | `Run failed: <first error>. No jobs were fetched.` plus `(+N more)` |
| `partial` | errors, some fetched | `Run finished with N problem(s): <counts>. First: <first error>` |
| `ok` | no errors, 0 fetched | `Run done: Reed returned no jobs for this search.` (source name from the search) |
| `ok` | no errors, some fetched, 0 new | `Run done: fetched F, nothing new (<counts>).` |
| `ok` | no errors, some new | `Run done: fetched F, N new (<counts>).` |
| `not_run` | disabled search | `Not run: this saved search is disabled.` No run row is stored. |

`<counts>` lists non-zero values only: queued for AI, skipped, already seen, below salary
floor, salary unknown, not attempted (budget reached). `failed` and `partial` show in red.
`ok: true` stays, meaning the request itself worked; existing tests read it.

For `not_run`, `handle_run_now` returns right after loading the search, before loading the
profile, so a disabled search can never get a `failed` row from a profile failure.

### Gap 3: one row per search per run, in a new table

New table beside `saved_searches`, created by `_init_connection`
(`job_hunt_saved_searches.py:183-189`). A new table needs no `ALTER TABLE`, no change to the
frozen `SavedSearch` dataclass and no change to `job_hunt_index.py`.

```sql
CREATE TABLE IF NOT EXISTS saved_search_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  search_id TEXT NOT NULL,
  trigger TEXT NOT NULL CHECK (trigger IN ('manual','scheduled')),
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','partial','failed')),
  salary_floor INTEGER,
  jobs_fetched INTEGER NOT NULL DEFAULT 0,
  jobs_new INTEGER NOT NULL DEFAULT 0,
  jobs_scored INTEGER NOT NULL DEFAULT 0,
  jobs_llm_queued INTEGER NOT NULL DEFAULT 0,
  jobs_skipped INTEGER NOT NULL DEFAULT 0,
  jobs_already_seen INTEGER NOT NULL DEFAULT 0,
  jobs_below_floor INTEGER NOT NULL DEFAULT 0,
  jobs_salary_unknown INTEGER NOT NULL DEFAULT 0,
  jobs_held_over INTEGER NOT NULL DEFAULT 0,
  errors TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_saved_search_runs_search
  ON saved_search_runs (search_id, run_id DESC);
```

- **Written inside the pipeline**, once per enabled search, at the end of that search,
  including unknown source, failed fetch, and an unexpected exception (row saved with the
  error, exception re-raised as today). So Run now and scheduled runs share one path, and
  `DigestScheduler` is not edited.
- **Failures before the loop are recorded too.** If the scoring policy load at
  `job_hunt_scheduler.py:173` raises, each enabled search gets a `failed` row and the exception
  is re-raised. If the profile load at `ui_handlers.py:2598-2603` fails, `handle_run_now`
  records a `failed` manual row before its existing 500 reply. So on Run now, a newer failure
  cannot sit hidden behind an older good run.
- **Known gap, accepted.** Two scheduled-path failures happen before `run_digest_pipeline` is
  called, and stay out of this table because `DigestScheduler` is not edited. A profile-load
  failure only writes a log line (`job_hunt_scheduler.py:971-975`), so it leaves no sign on the
  page. A search-list failure reaches the scheduler status line only (`:1002-1005`).
- `run_digest_pipeline` gets `trigger: str = "scheduled"` and passes it to
  `_run_digest_pipeline_locked`; `handle_run_now` passes `"manual"`.
- Per-search counts come from the difference between the run totals at the start and end of
  that search. `errors` keeps at most 20 items of 500 characters each, with the
  `<search_id>: ` prefix removed.
- A failed row write never stops the run and never replaces an exception already on its way
  up. It is logged and added to `errors`, so it is not hidden. That can turn an otherwise good
  run into `partial`, which is correct: the record of it is missing.
- `DigestRunResult` gains `jobs_below_floor: int = 0`, `jobs_salary_unknown: int = 0` and
  `jobs_held_over: int = 0` after `errors`, and `to_dict()` includes all three.
- `delete_saved_search` deletes the search's rows in the same transaction. A run still in
  progress during a delete can leave one orphan row, which nothing shows. Accepted.
- `jobs_salary_unknown` overlaps the other counts: it says how many jobs were kept with no
  usable salary, whatever then happened to them. All the other job counts are separate, so
  fetched = new + already seen + skipped + below floor + held over + save failures.
- No pruning: a few hundred small rows a year for a local single-user tool. The page shows
  the newest 20.
- `update_last_run` and the two old columns stay. `tests/test_digest_e2e.py:169` reads them.

**On the page.** `GET /saved-searches` adds `runs` to each search: newest first, at most 20,
each with the status and text from the table above. A failed read gives `runs: []` and a log
line, and the list still loads. Each row shows the newest run in a labelled line. A
`<details>` element lists every returned run, the newest included, with time, Run now or
scheduled, text and all kept errors. All of this text goes through the page's `esc()` helper
(`ui_render.py:3224`). A search with no
run rows keeps the old `last run` text, now labelled `(<count> new)`.

## 4. Acceptance criteria

All tests use synthetic data, mocked `requests.get` or fake sources, and the offline skills
stub (`tests/test_digest_pipeline.py:30-34`).

Gap 1
- AC1. F = 65000 and a job at £38,000–£45,000: not indexed, skills extraction not called,
  `jobs_below_floor` = 1, one `below_salary_floor` line in the skipped log.
- AC2. F = 65000: £60,000–£70,000, exactly £65,000, and max-only £70,000 are kept;
  min-only £50,000 is dropped, and so is £12,000 (the accepted monthly-pay case, pinned so the
  behaviour is deliberate).
- AC3. F = 65000: no salary, `"abc"`, zero, and £500–£700 are kept and counted in
  `jobs_salary_unknown`. F = 8000 and a job at £500–£700: also kept as unknown.
- AC4. Floors `""`, `"abc"`, `"0"`, and no key: no job dropped, both counters 0, fetch size
  unchanged (10).
- AC5. With a floor and no saved `resultsToTake`, the source receives 50, or
  `digest_max_per_source` if smaller. A saved `resultsToTake` is kept. The request made by
  `fetch_reed_jobs` contains no `minimumSalary` (asserted on mocked `requests.get`).
- AC6. An already-indexed job with a description and a salary below the floor counts as already
  seen, not below floor.
- AC7. A saved Adzuna search goes through the same rule. A saved LinkedIn search with a floor,
  using the real LinkedIn normaliser, drops nothing, gets no changed fetch size and has an
  empty `salary_floor`.
- AC8. The Reed search page note has the new text and paging is unchanged.
- AC8a. With a floor and 50 results of which 15 would pass and are new: skills extraction runs
  10 times, `jobs_new` = 10, `jobs_held_over` = 5, and `jobs_fetched` = 50. The next run
  processes the 5 held jobs. The count sum in section 3 holds.
- AC8b. No budget used by: non-dict results, blank ids, already-seen jobs, below-floor jobs and
  blank descriptions. Budget used by: a job whose evaluation fails and a job whose save fails,
  so extraction never runs more than 10 times. A blank-description result below the floor
  counts as below floor. Ten jobs that fail evaluation on two runs in a row show errors in both
  runs, and a valid job behind them counts in `jobs_held_over` in both.
- AC8c. Two searches in one run, the first with a floor, and the AI queue cap at its default:
  total queued stays within the cap, and a search with no floor reads and processes the same
  jobs as it did before this build, apart from the shared cap.

Gap 2
- AC9. Each of the 7 failure paths raises `ReedFetchError` with its message, and the message
  has no key value (a fake key string is asserted absent). `{}`, `{"error": "x"}`,
  `{"results": null}` and `{"results": "x"}` raise as unexpected. Bad JSON gives the bad-JSON
  message for both the `requests` and the standard-library exception. `{"results": []}` and
  `[]` return `[]`.
- AC10. Pipeline with one failing and one working search: the failure is in `errors`, the
  working search still runs, `searches_run` = 1.
- AC11. Reed search page with a failing fetch shows the error, not an empty result. More
  with a failing fetch keeps its offset.
- AC12. The run-now response has the right `run_status` and text for all 6 rows of the Gap 2
  table. The served page's JS uses `d.summary` and no longer builds "Run done" itself.

Gap 3
- AC13. Run now on one search adds one row with `trigger='manual'` and correct counts. A
  scheduled-path call adds a row per enabled search with `trigger='scheduled'`. A disabled
  search adds none, and Run now on it returns `not_run` even when profile loading would raise.
- AC14. A failing fetch adds a `failed` row with the error text. An exception inside the loop
  adds a row and still raises. If the row write also fails, the original exception is the one
  raised. A scoring-policy load failure adds a `failed` row per enabled search and still raises.
  A profile-load failure on Run now adds a `failed` manual row and still returns 500.
- AC15. Rows survive reopening the DB. An existing DB with `saved_searches` rows and no new
  table opens without error and those rows are unchanged.
- AC16. `GET /saved-searches` returns `runs`, newest first, at most 20, and a newest run with
  several errors has all of them available to the page. `delete_saved_search` removes the rows. Error text with `<script>` does not reach the DOM as markup: `esc` is
  applied in the served JS (string check) and in the browser check (AC20).
- AC17. A failed row write does not stop the run and appears in `errors`.
- AC18. `DigestRunResult(**r.to_dict()) == r`, and a dict without the three new keys also
  builds. This protects the uncommitted code in the main checkout (Overlap, hazard 1).

Whole build
- AC19. Full suite shows no new failures against a run taken at this branch's base before
  the build, and against `archive/cv-review/baseline-failures-2026-10-26.txt`, which exists
  only in the main checkout (46 lines; read by absolute path).
- AC20. Browser check through a small harness script kept outside the repo. It starts the real
  server with `--state-root` and `--report-dir` in a temp folder and a synthetic profile with
  digest and LLM off. It replaces `dotenv.load_dotenv` with a no-op, sets `REED_API_KEY` to a
  fake value, and replaces `requests.get` with a function that raises a timeout. An empty key
  is not enough: `_ensure_env_loaded` would then try to load `.env` (`reed_client.py:13-35`).
  Run now shows the red failure, the history line survives a reload, and `<details>` opens. No
  Reed call, no Gemini call, no `.env` load, no real data opened.
- AC21. Docs updated per `docs/docs-update-checklist.md`. Fresh verifier passes. Nothing
  pushed or merged.

## 5. Overlap with uncommitted work in the main checkout

Main checkout: branch `feat/cv-blind-review-2026-10-26` at `5ca4c3a`, with uncommitted edits
that this worktree does not contain.

| File | Their edits | This build | Result |
|---|---|---|---|
| `src/job_hunt_scheduler.py` | The import block near `:27` and class `DigestScheduler` only (`:887` onward): the daily-run ledger from Issue 16 | `DigestRunResult`, helpers above `:134`, pipeline `:134-315` | No shared lines expected. Must not edit `DigestScheduler` or that import block. |
| `src/job_hunt_index.py` | `daily_digest_runs` table and functions | Not touched | None |
| `src/job_hunt_parsing.py`, `src/job_hunt_storage.py`, `viewer/viewer_server.py` | Security and parsing | Not touched | None |
| `tests/test_digest_scheduler.py`, `tests/test_parsing.py`, `tests/test_market_position_route.py` | Their tests | Not touched | None |
| `INDEX.md`, `PROJECT_LOG.md`, `PROJECT_TODO.md`, `docs/function_list.md` | Doc updates | Doc updates | **Merge conflicts likely.** Docs go in one last commit, so they are easy to redo at merge. |

**Hazard 1.** Their `_restore_daily_status` runs `DigestRunResult(**attempt["result"])` on a
stored `to_dict()`, inside a block that makes the scheduler refuse to run if it raises. If
`to_dict()` gains a key that is not a dataclass field, the daily digest would stop after
their work merges. So `run_status` and `summary` stay out of `to_dict()`, and AC18 pins this.

**Hazard 2.** Their ledger marks a run `partial` when `result.errors` is non-empty. Reed
failures now reach `errors`, so a failed Reed fetch will correctly mark that day `partial`
and show "retry manually". That is the right behaviour, but it will be seen more often.

The two records do not compete. Their ledger holds one row per day for the whole daily run.
This table holds one row per search for any run. Their spec keeps Run now out of the ledger.

## 6. Risks

- **Gemini use stays at today's limit.** Skills extraction at `job_hunt_scheduler.py:261` runs
  for each new job that passes, and `digest_max_llm_per_run` does not cap it (it gates queueing
  at `:180`). The new-job budget keeps this at no more than 10 attempts per search per run, as
  today, with up to two Gemini requests per attempt.
- **AI queue.** A floor search can fill the shared queue cap more often than its old first 10
  did, so a later search's new jobs may be indexed but not queued. The configured cap still
  holds. See "The AI queue limit" in section 3.
- **Reach.** Reed's result order is not documented. Good jobs past the first 50 are missed, and
  no count here can show that: the counts cover only what was read. Sending the floor to Reed
  might reach them, but what it would drop is unknown until a live check.
- **Slow catch-up.** With many passing jobs, only 10 are attempted per run. A held job that
  falls out of the first 50 before its turn is missed. Jobs that keep failing evaluation or
  saving stay unindexed and use attempts again on every run, so ten of them would block the
  jobs behind them. `jobs_held_over` and the errors of each run show both cases.
- **The £10,000 line is a judgment.** A part-time annual salary under it is kept as unknown
  rather than dropped, which errs toward showing a job. A monthly figure of £10,000 or more is
  dropped against a high floor (Known wrong case).
- **Search page errors are new.** A Reed outage now shows an error banner there.
- **Adzuna still hides failures.** `fetch_adzuna_jobs` returns `[]` on failure (`adzuna_client.py:31, 58, 64, 72, 75, 78`), so a failing Adzuna saved search still shows "Adzuna returned no jobs".

## 7. Not in this build

- Same failure fix for Adzuna. Its client is also used by the market-position feature, so it
  needs its own check of callers.
- Sending the floor to Reed. Needs a live Reed check of what it drops.
- Raising the 10-job read for searches with no floor (changes Gemini use for every search).
- Applying the floor on the Reed search page.
- Recording the scheduled profile-load failure (needs an edit to `DigestScheduler`, so it waits
  for the uncommitted scheduler work in the main checkout to land).
- Stale text: `ui_render.py:2796` "auto-run lands in a later phase"; `ui_handlers.py:2587`
  docstring "No LLM calls".

## 8. Questions for Mike

- **Q1. Jobs with no listed salary when a floor is set.** Recommended: keep and count them.
  Employers can hide salary on Reed, and dropping would remove those jobs with no sign.
  Alternative: drop them.
- **Q2. A range that crosses the floor (£60,000–£70,000 with a floor of 65000).** Recommended:
  keep, because the range reaches the floor. Alternative: require the bottom of the range to
  meet the floor.
- **Q3. How far to look.** Recommended: read 50 jobs when a floor is set, filter locally, and
  process at most 10 new jobs per run, so Gemini use stays at today's limit. Alternative: read
  10 and send the floor to Reed, which may reach further but may silently lose no-salary and
  day-rate jobs, and needs one live Reed check first (one read-only request pair, no Gemini).

## 9. Build order and stop conditions

Each step commits after its tests pass. Step 0 runs first and changes nothing.

0. Run the full suite at the base and save failing test names to the session scratchpad.
1. `ReedFetchError` and client tests (AC9), caller checks (AC10, AC11).
2. Floor rule, fetch size, new-job budget, note and form hint (AC1-AC8c).
3. Run table, recording, delete, list route (AC13-AC18).
4. Status and text, `runNow`, row and history (AC12, AC16, AC20).
5. Full suite (AC19), docs, verifier (AC21).

Builder: per `dispatch.md` Builder routing. Stop and ask Mike if: a change to
`DigestScheduler` turns out to be needed; a suite failure cannot be tied to this build or the
baseline; any step needs a live Reed or Gemini call, or `.env`, `data/` or `output/`.
