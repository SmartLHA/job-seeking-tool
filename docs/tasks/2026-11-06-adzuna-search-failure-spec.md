# Adzuna search: visible failures

<!-- IMPLEMENTATION STATUS (2026-11-06): built on branch claude/keen-jones-b93b9a in commits 87b0919 (client and tests AC1-AC6, AC13) and 7c23e34 (caller tests AC7-AC11); docs commit dc164a8. Merged to main 2026-11-08 via PR 7 (751b253). Fresh verifier passed on 2026-11-06 at dc164a8: AC1 to AC17, 0 BLOCKER, 0 MAJOR, 3 MINOR, none needing a fix in this build. Full suite: 50 failed, 2838 passed, 16 skipped; failing ids equal the 50 baseline ids. Zero-match body checked by one live call, live run 2026-11-06 (n=1, keyword `zzqxvjkplm`, run by the session that built this, Mike's consent "Yes, one live call"): HTTP 200, keys `__CLASS__`, `count`, `results`, with `results` an empty list; the client returned `[]`. Real error status codes remain UNVERIFIED. -->
<!-- STATUS: APPROVED r2 2026-11-06. Mike answered "Build to this spec, reading saved Adzuna files
to check the zero-result response?" with "Build, read saved files". So Q1 = read saved files,
Q2 = keep the multi-keyword notice out of this build, Q3 = approved.
Base: branch claude/keen-jones-b93b9a at 4a515fd, which equals claude/agitated-sinoussi-7cc5be
(the Reed failure build, since merged to main via PR 7 on 2026-11-08). All file:line references are at 4a515fd.
A fresh verifier checked this draft on 2026-11-06: 0 BLOCKER, 0 MAJOR, 3 MINOR, all fixed in r1.
No Codex or Gemini design review was run on this draft. -->

## 1. Problem

`fetch_adzuna_jobs` (`src/job_sources/adzuna_client.py:16`) returns `[]` on every failure:
`adzuna_client.py:31, 58, 64, 72, 75, 78`. A real empty result also returns `[]`, so no caller can
tell the two apart. The effects today:

- A failing Adzuna saved search says `Run done: Adzuna returned no jobs for this search.`
  (`src/job_hunt_saved_searches.py:465`).
- A failing search on the Find Jobs page shows "No Adzuna results found"
  (`src/job_sources/adzuna_source.py:451-459`).
- A dict with `"results": null` makes the client return `None`, and `raw_jobs[:take]`
  (`adzuna_source.py:119-125`) then raises `TypeError`, a text that means nothing to the user.

The Reed build fixed the same problem with `ReedFetchError` (`src/job_sources/reed_client.py:11-12`).
Section 7 of `docs/tasks/2026-11-05-saved-search-salary-failure-runs-spec.md` left Adzuna out until
its callers were checked. Section 3 below is that check.

## 2. What Adzuna documents

Docs read 2026-11-06, without a live API call. The one live run came later and is recorded below.

| Topic | What the docs say | Source |
|---|---|---|
| Keys | `app_id` and `app_key` are obligatory parameters, shown in the query string | https://developer.adzuna.com/overview |
| Errors | A failed request returns an HTTP status other than 200. No list of codes and no body shape | https://developer.adzuna.com/overview |
| Successful search | Examples show a populated `results` array | https://developer.adzuna.com/docs/search |
| Zero matches | Not documented. No page shows an empty result. See the live run below | https://developer.adzuna.com/docs/search |
| Rate limits | No figure and no 429 behaviour. Limits "are shown in your account" | https://developer.adzuna.com/docs/terms_of_service |

`https://developer.adzuna.com/activedocs` returned only a landing line to the fetch tool, so its
content was not read.

Saved responses, read 2026-11-06 with Mike's consent (a script printed key names and result counts only,
no values): the saved files in `data/raw/adzuna/` in the main checkout are dicts with the keys `__CLASS__`,
`count`, `mean` and `results`, and every `results` is a non-empty list. None is a zero-match or error
response.

Zero-match body, live run 2026-11-06 (n=1, keyword `zzqxvjkplm`, run by the session that built this, Mike's consent "Yes, one live call"): HTTP 200, keys `__CLASS__`, `count`, `results`, with `results` an empty list; the client returned `[]`. This matches section 4.3.

The key being in the URL matters here. `requests` exception text contains the full URL, so a chained
Adzuna exception holds the key. Reed sends its key in an auth header, so this risk is new (section 4.4).

## 3. Callers of `fetch_adzuna_jobs`

Main result: **the market-position feature does not call this function.** It imports only
`fetch_adzuna_salary_histogram` and `read_cached_salary_histogram` (`src/ui_handlers.py:796, 823, 877, 887`),
which return their own status objects. The warning in `PROJECT_TODO.md:44` is about the shared file.

There is one production call: `search_adzuna_jobs_for_ui` (`adzuna_source.py:116`, call at `:119`). It
has no try/except, so an error passes through it. It is registered as the Adzuna `search_handler`
(`adzuna_source.py:491`). The only calls to `search_handler` are `src/job_hunt_scheduler.py:286` and
`src/ui_handlers.py:1069`.

| Caller | Catches the error at | Today on failure | After this build |
|---|---|---|---|
| Find Jobs page (`ui_handlers.py:1069`, in `_run_multi_keyword_search`) | `ui_handlers.py:1070` | "No Adzuna results found" | Banner "Adzuna search unavailable" with `Adzuna search failed: <message>. Manual fallback is still available.` (`ui_handlers.py:1213`, `adzuna_source.py:439-448`) |
| More route (`ui_handlers.py:2133-2137`) | `ui_handlers.py:2178-2180` | Empty page, no error | `{"ok": false, "error": "<message>"}` with HTTP 200. The offset is kept for retry |
| Saved search, Run now and scheduled (`job_hunt_scheduler.py:286`) | `job_hunt_scheduler.py:287-289` | `Run done: Adzuna returned no jobs...` | `Run failed: fetch failed: <message>. No jobs were fetched.` (`job_hunt_saved_searches.py:456-458`). Other searches continue |
| `scripts/verify_adzuna.py:50`, `src/job_sources/test_fetch.py:26`, `adzuna_client.py:325` (developer scripts) | None | `FAIL: 0 jobs...` or an empty list | Traceback showing the fixed message and no key (AC5) |

No caller's code needs to change.

Other facts checked:

- A failing search changes only the run record, the Run now JSON and the displayed text. No digest
  send, retry, alert, lock or exit code reads the errors. They are read only by `search_run_summary`
  (`job_hunt_saved_searches.py:445`), the Run now JSON (`ui_handlers.py:2645-2646`) and the page script
  (`ui_render.py:3246`). The scheduled run (`job_hunt_scheduler.py:1075-1117`) does not read them.
- `is_available` has no caller in `src/`, so with keys missing the client is reached on every path.
- The running server loads `.env` at start (`src/ui_routes.py:168-170`), so "keys are not set" means the
  keys are really missing.
- The client has no multi-page loop. A "later page" is one More request, and the scheduler makes one
  fetch per saved search. So there are no partial pages to keep.
- The salary floor applies to Adzuna searches but only changes the fetch size and filters results
  afterwards (`job_hunt_scheduler.py:282-285`). A failed fetch takes the same path as any other.
- `logger.exception` exists only at `src/ui_routes.py:259, 360`, for errors that escape the handlers.
  The three catch paths above write `str(exc)` only.

## 4. Decisions

### 4.1 New error type

Add to `adzuna_client.py`, in the same form as Reed:

```python
class AdzunaFetchError(RuntimeError):
    """An Adzuna search failed rather than returning an empty result."""
```

### 4.2 Failure messages

Messages are fixed text. `str(e)` from `requests` is never used.

| Failure | Message |
|---|---|
| `ADZUNA_APP_ID` or `ADZUNA_APP_KEY` missing (no request is made) | `Adzuna API keys are not set` |
| HTTP 429 | `Adzuna rate limit reached (HTTP 429)` |
| HTTP 401 or 403 | `Adzuna returned HTTP <status>: check the API keys` |
| Other HTTP error | `Adzuna returned HTTP <status>` |
| HTTP error whose status is not an int from 100 to 599 | `Adzuna returned an HTTP error` |
| Timeout | `Adzuna request timed out` |
| Other request error | `Adzuna request failed (<ClassName>)` |
| Invalid JSON (stdlib or `requests` type) | `Adzuna returned invalid JSON` |
| Body is not usable (4.3) | `Adzuna returned an unexpected response` |

The status check keeps the existing guard at `adzuna_client.py:67-68`: `type(status) is int and
100 <= status <= 599`. The existing test passes a key-like string as the status
(`tests/test_reed_adzuna_clients.py:213`), and Reed has no such guard.

The JSON handler must come before the `RequestException` handler, as in Reed
(`reed_client.py:86`). `requests.exceptions.JSONDecodeError` inherits from `RequestException`, so today
it is caught by the wrong handler.

### 4.3 What counts as empty

Success means a dict whose `results` is a list of dicts. An empty list returns `[]`. Anything else
raises the "unexpected response" error: a dict with no `results`, `results` null or not a list, an item
that is not a dict, or a body that is not a dict.

This is stricter than Reed in two ways. A top-level list is an error, because Adzuna does not document
that form. Non-dict items are an error, because otherwise `normalize_adzuna`
(`src/job_sources/normalize.py:220-231`) raises `AttributeError` and its text would reach the page.

One live call confirmed the zero-match body (section 2, risk R1, question Q1).

### 4.4 No chained exception: different from Reed

Every raise inside an `except` block uses `from None`, not `from e`.

Reed's `from e` is safe because its key is not in the URL. An Adzuna `from e` would put the URL and key
into any printed traceback, including the developer scripts and `logger.exception` at
`ui_routes.py:259, 360`.

### 4.5 Logging

Keep the existing log text built from fixed strings, the class name and the validated status
(`adzuna_client.py:69, 71, 74, 77`). Change only the 429 line, which says "Returning empty list".

### 4.6 Files changed

- `src/job_sources/adzuna_client.py` (only lines before `save_raw_response`, plus the new class)
- new `tests/test_adzuna_failure_paths.py`
- `tests/test_reed_adzuna_clients.py`
- docs: `PROJECT_TODO.md`, `PROJECT_LOG.md`, `INDEX.md`, this spec, and `docs/function_list.md` if it
  lists the changed function

## 5. Acceptance criteria

All tests use synthetic data and fake keys. An autouse fixture replaces `save_raw_response` with a no-op,
so nothing is written to `data/`, and makes any unmocked `requests.get` fail the test. Tests that use the
page or the pipeline register the real Adzuna source (`adzuna_source._register()`) and restore the
registry afterwards, as `tests/test_reed_failure_paths.py:20-29` does.

Client

- AC1. Each failure raises `AdzunaFetchError` with the exact message from 4.2: `ADZUNA_APP_ID` missing,
  `ADZUNA_APP_KEY` missing, both missing, 429, 401, 403, 500, `Timeout`, `ConnectionError`,
  `RequestException`, stdlib `JSONDecodeError`, `requests` `JSONDecodeError`. With keys missing,
  `requests.get` is not called.
- AC2. An `HTTPError` with status `None`, `"fake-adzuna-key-in-url"`, `True` or `600` raises
  `Adzuna returned an HTTP error`.
- AC3. HTTP 200 with each of these bodies raises `Adzuna returned an unexpected response`: `{}`,
  `{"error": "x"}`, `{"results": null}`, `{"results": "x"}`, `{"results": ["x"]}`, `null`, `"x"`, `[]`.
- AC4. HTTP 200 with `{"results": []}` or `{"__CLASS__": "x", "count": 0, "mean": 0, "results": []}`
  returns `[]` and does not raise. `{"results": [{"id": "1"}]}` returns that list unchanged. The paging tests at `tests/test_reed_adzuna_clients.py:335, 353` pass
  unchanged.
- AC5. Key safety. For every failure in AC1 and AC2, the mocked exception text holds a URL with
  `app_key=<fake key>`, so a leak would show. The fake key and the URL are absent from `str(exc)`, from
  `"".join(traceback.format_exception(exc))` and from `caplog.text`. Every log record has `exc_info` of
  `None`. For a failure raised in an `except` block, `exc.__cause__ is None` and
  `exc.__suppress_context__ is True`.
- AC6. Log text matches 4.5 for each failure, and the 429 line no longer says "Returning empty list".

Callers

- AC7. Pipeline: `run_digest_pipeline` with two Adzuna saved searches, where the first times out and the
  second returns one job. `errors` holds `broken: fetch failed: Adzuna request timed out`, the second
  search's job is indexed, and the pipeline does not raise.
- AC8. Run records:
  - AC8a. A timed-out search records status `failed`, stored error
    `fetch failed: Adzuna request timed out`, summary
    `Run failed: fetch failed: Adzuna request timed out. No jobs were fetched.`
    The summary does not contain "returned no jobs".
  - AC8b. `{"results": []}` records status `ok` and summary
    `Run done: Adzuna returned no jobs for this search.`
  - AC8c. Missing keys record status `failed` and stored error `fetch failed: Adzuna API keys are not set`.
  - AC8d. `POST /saved-searches/{id}/run-now` for the case in AC8a returns `ok: true`, `run_status:
    failed` and the same summary, with no fake key in the body.
- AC9. Find Jobs page: `GET /search/adzuna?...` with a timeout returns HTTP 200 and shows "Adzuna search
  unavailable" and `Adzuna search failed: Adzuna request timed out`. It does not show "No Adzuna results
  found" or the fake key. With `{"results": []}`, it shows "No Adzuna results found" and no error banner.
- AC10. More route: page 1 succeeds, then More times out and returns `{"ok": false, "error": "Adzuna request
  timed out"}`, then a retry succeeds. The page numbers in the mocked request URLs are `[1, 2, 2]`.
- AC11. Find Jobs page with two keywords, one failing and one working: HTTP 200 and the working keyword's
  job is shown.
- AC12. Market position is unchanged: `git diff 4a515fd -- src/job_sources/adzuna_client.py` has no change
  at or after `def save_raw_response`, `src/ui_handlers.py` is unchanged, and `tests/test_adzuna_salary.py`
  passes. `tests/test_market_position_route.py` passes except the 4 tests that already fail at 4a515fd.
- AC13. In `tests/test_reed_adzuna_clients.py`, the tests that pinned `[]` on failure (`:233, 255, 305, 318,
  332, 424`) now expect `AdzunaFetchError`, and their log and redaction assertions stay.
  `test_fetch_adzuna_jobs_empty` (`:284-296`) still expects `[]`.

Whole build

- AC14. `git diff --name-only 4a515fd` lists only the files in 4.6. If a caller needs a code change, stop
  and ask Mike (section 9).
- AC15. Full suite with fake keys and the project venv:
  `REED_API_KEY=fake-reed-key ADZUNA_APP_ID=fake-adzuna-id ADZUNA_APP_KEY=fake-adzuna-key GEMINI_API_KEY=fake-gemini-key GOOGLE_API_KEY=fake-google-key <project>/venv/bin/python -m pytest tests/ -q --tb=no -rfE`.
  Run it from this worktree, because the venv is in the main checkout. No failure id appears that is not
  in the run taken before the build at 4a515fd (50 failed, 2802 passed, 16 skipped; 50 ids saved in the
  session notes folder as `adzuna-failure-baseline-4a515fd-failures.txt`).
- AC16. A fresh verifier checks AC1 to AC15 and confirms that changing one `from None` to `from e` makes
  an AC5 test fail, on a temporary copy that is then discarded.
- AC17. Docs follow `docs/docs-update-checklist.md`: `PROJECT_TODO.md:44` marked done, `PROJECT_LOG.md`,
  the `INDEX.md` rows for the client and source, `docs/function_list.md` if it lists the changed function,
  and this spec's status header.

## 6. Risks

- R1. Zero-match body is undocumented. If Adzuna leaves out `results` on zero matches, a real empty search
  would show "unexpected response" instead of "no jobs". The failure would be visible and the fix is one
  line, but it would be wrong until fixed. One live call on 2026-11-06 returned `results` as an empty list (section 2),
  so this risk did not occur on that run (n=1).
- R2. Failures hidden today will start to show. A saved Adzuna search with an expired key or a used-up
  quota will show `Run failed` where it now says "no jobs". This is the aim, but it may look like a new
  problem when it first appears. Nothing beyond the display changes (section 3).
- R3. Real status codes are UNVERIFIED. Adzuna does not list them. Any HTTP error reaches a message through
  the general row in 4.2, but the 401/403 hint and the 429 text are proven only against mocks. The
  behaviour against the live API stays UNVERIFIED unless Mike allows a live run.
- R4. Tests that already fail at 4a515fd hide some evidence. `tests/test_ui.py::test_get_search_adzuna_more_returns_offset_page`
  and 4 tests in `tests/test_market_position_route.py` already fail, so they prove nothing here. AC10 and
  AC12 cover those paths another way.
- R5. Stacked branch. This work sits on the unmerged Reed branch, so that branch must merge first.

## 7. Not in this build

- Notice for a partly failed multi-keyword search. `_partial_error_count` is written at
  `ui_handlers.py:1215` and read nowhere in `src/`. If one keyword fails and another works, the page shows
  the results and says nothing about the failure. Reed has the same gap, so it is a separate fix for both
  sources (Q2).
- The salary histogram functions and their status objects.
- Raw response saving. `adzuna_client.py:54` saves every body, error bodies included, and has no switch like
  Reed's `save_raw`.
- `logging.basicConfig` at import (`adzuna_client.py:13`), retries or backoff on 429, the 10-second timeout.
- Catching the error in developer scripts. As with Reed, a traceback is acceptable there.
- LinkedIn.

## 8. Questions for Mike

- Q1. How should the zero-match body be checked before the build?
  - (a) Recommended: a read-only script over `data/raw/adzuna/` in the main checkout that prints only each
    file's top-level key names and the length of `results`, never any values. No network. It needs your
    consent because it opens `data/`. It helps only if a saved zero-result file exists.
  - (b) One live search for a nonsense keyword, printing the same key names and length. It uses your key
    and one API call.
  - (c) No check. Build on `{"results": []}` and accept R1.
- Q2. Keep the multi-keyword notice out of this build (section 7)? Recommended: yes, as a separate fix.
- Q3. Approve this spec for build?

Answers, 2026-11-06: Q1 = (a), which found no zero-result file. Q2 = yes. Q3 = approved. Option (b) was
run after the build, with Mike's consent (section 2).

## 9. Build order and stop conditions

Builder: the `implementer` agent. Commit after each passing chunk. No push or merge.

1. Q1 check: done 2026-11-06 (section 2). Section 4.3 is unchanged.
2. Client: `AdzunaFetchError`, messages, tests AC1 to AC6 and AC13. Commit.
3. Callers: tests AC7 to AC12. Commit.
4. Docs: AC17. Commit.
5. Fresh verifier: AC14 to AC16, then all the others.

Stop and ask Mike if: a caller needs a code change; the Q1 check shows a body this spec does not cover; a
new test failure survives two fixes; or any step would need a live API call that Q1 did not allow.
