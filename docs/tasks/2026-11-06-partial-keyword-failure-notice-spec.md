# Partly failed multi-keyword search: visible notice

<!-- IMPLEMENTATION STATUS: built (commits c66a249, de8dfa8, 7ccbe23). Branch claude/cool-faraday-76ed62, on top of claude/keen-jones-b93b9a (Adzuna failure build) at db8c6b6. Not pushed, not merged. Fresh verifier passed 2026-11-06 at 8ed6bda (AC1-AC16; AC17 is producer evidence). -->
<!-- STATUS: APPROVED by Mike, 2026-11-06 ("Approve, build it"), with the recommended answers to Q1 and Q2. -->

Line numbers refer to base `db8c6b6`.

## 1. Problem

When some keywords of a multi-keyword search fail and others work, the Find Jobs page shows the working keywords' results and says nothing. The user cannot tell that a keyword was not searched. Reed, Adzuna and LinkedIn all use this code path.

## 2. What the code does today

| Question | Answer | Evidence |
|---|---|---|
| Is the failure collected? | Yes, as a plain string: raw `str(exc)`, with a `'term': ` prefix when there is more than one term. Any exception type is caught. | `src/ui_handlers.py:1070-1075` |
| First page | Writes `search_values["_partial_error_count"]`. Nothing reads it. | `src/ui_handlers.py:1215` |
| More route | `kw_sub_errors` only decides the all-failed raise and stops the hidden-page look-ahead. On a partial failure it is then dropped; the JSON payload has no error field. | `src/ui_handlers.py:2136-2141`, `:2162-2166` |
| Is the failed keyword's offset kept for retry? | Yes. The offset is kept, `has_more` stays true, and the next page retries that keyword. No change needed. | `src/ui_handlers.py:1076`, `:2150`; `tests/test_search_replay.py:248-268` |
| First page with no results at all from the working keywords | Partial case, not the error banner. The renderer shows "No Reed results found", and `_render_search_jobs_tab` adds a Next page button so the failed keyword can be retried. | `src/ui_handlers.py:1212`, `:3243-3250`, `src/job_sources/reed_source.py:525-534`, `adzuna_source.py:451`, `linkedin_source.py:673` |
| More payload when other keywords return nothing | The page says "No more jobs on this page.", which is misleading when a keyword failed. | `src/job_sources/_multiselect.py:415-419` |
| Other callers | None. Saved searches and Run now call `search_handler` once per saved search, so they have no partial case. | `src/job_hunt_scheduler.py:286-289` |

## 3. Decisions

### 3.1 What is collected

`_run_multi_keyword_search` keeps its 4-tuple return and its `sub_errors` strings, so the all-failed banner, the all-failed More error and the existing tests stay as they are. It gains an optional keyword-only argument `failures: list[dict[str, str]] | None = None`. Each failed term appends `{"keyword": term, "message": _keyword_failure_message(source, exc)}`.

`_keyword_failure_message(source, exc)` returns:

- `str(exc)` only when `exc` is a `ReedFetchError` or `AdzunaFetchError`. These hold fixed text with no key, URL or upstream response text (`src/job_sources/reed_client.py:51-100`, `src/job_sources/adzuna_client.py:36-97`).
- Otherwise the fixed text `f"{source.display_name} search failed"`. Raw text from any other exception never reaches the notice. See Q1.

### 3.2 The notice

One helper, `_render_keyword_failure_notice(failures, can_retry_next_page)`, is used by both routes:

- Element id `jst-keyword-failure-note`, inline styles with the amber `--review-bg`, `--review-line`, `--review` colours. Amber separates it from the red "search unavailable" banner, because results are still on the page.
- Title: `Some keywords could not be searched`
- One row per failed keyword, in the order entered: `<strong>keyword</strong>: message`
- Last line: `Next page tries these keywords again.` when `can_retry_next_page`, else `Search again to try these keywords again.`
- Keyword and message both go through `escape` (`src/ui_utils.py:311`).

### 3.3 First page

`handle_source_search` passes a `failures` list and, in the existing partial branch, sets `search_values["_keyword_failures"] = failures`. This replaces `_partial_error_count`. Keys starting with `_` are already left out of More and restart URLs (`src/ui_handlers.py:1182`, `:1289`).

`_render_search_jobs_tab` renders the notice beside the other notes, above `source_results_html` (`src/ui_handlers.py:3253-3302`). `can_retry_next_page` is `bool(search_values.get("_more_url"))`, because the Next page button is on the page whenever that URL is set, with or without results (`:3243-3250`, and the source renderers). The notice is not rendered when `reed_error` is set, so the "Search settings changed" re-render (`:1309-1312`) shows only its banner.

### 3.4 More route

`produce_page` passes a fresh `failures` list for each look-ahead round. On a partial failure the payload gains `keyword_failure_html`, rendered with `can_retry_next_page=has_more`. With no failure the key is absent, so the payload stays exactly as it is today. Payload replay carries the field automatically (`src/job_sources/search_state.py:188-198`).

`jstLoadMore` in `src/job_sources/_multiselect.py`:

- On every successful response, removes any `#jst-keyword-failure-note`. The first-page notice therefore goes away once the retry works, and the notice always describes the latest fetch.
- If `d.keyword_failure_html` is set, inserts it with `container.insertAdjacentHTML("afterbegin", ...)`, above the cards. The scroll at the end of the handler then targets the notice instead of `container.parentElement`. This keeps it on screen in both layouts: in the no-results layout the container sits directly inside the panel, below the search form (`src/ui_handlers.py:3247`).
- Does not show "No more jobs on this page." when the notice is present and `d.count` is 0.

The all-failed More path (`{"ok": False, "error": ...}` and the alert) does not change.

### 3.5 Files changed

`src/ui_handlers.py`, `src/job_sources/_multiselect.py`, new `tests/test_partial_keyword_failure_notice.py`, new browser test `tests/test_partial_keyword_failure_browser.py`, and the docs in AC16.

## 4. Acceptance criteria

Tests use synthetic data, fake keys in the environment, and a mocked `requests.get` that fails the test on any unexpected call. No live API call.

First page:

- **AC1 Reed:** two keywords, one `requests.get` call raises a timeout and the other returns jobs. The page shows the working keyword's card and a notice naming the failed keyword with `Reed request timed out` and the Next page line.
- **AC2 Adzuna:** the same, with `Adzuna request timed out`.
- **AC3:** with three keywords and two failing, the notice has one row per failed keyword, in the order entered.
- **AC4:** failed keyword plus a working keyword with zero results (Reed and Adzuna): the notice appears with the Next page line, and the Next page button is on the page. The `Search again` line appears only when there is no `_more_url` (direct render test).
- **AC5:** no failure gives no notice. A single keyword failing, or all keywords failing, gives the existing banner unchanged and no notice. `_render_search_jobs_tab` with `reed_error` and `_keyword_failures` both set shows only the banner.

More route (`/search/<source>/more`), Reed and Adzuna:

- **AC6:** on a later page one keyword fails and another returns jobs. The JSON has `ok: true` and `keyword_failure_html` naming the keyword and its fixed message, `has_more` is true, and `next_url` keeps the failed keyword's offset in `keywordCursors`. Calling `next_url` retries that keyword at that offset; when it works, the payload has no `keyword_failure_html`.
- **AC7:** failed keyword plus a keyword returning nothing: `ok: true`, `visible_count: 0`, notice present.
- **AC8:** all active keywords fail: the response is the existing `{"ok": False, "error": ...}` and the cursor does not advance.
- **AC9:** replaying the same cursor returns the same payload, including the notice, with no new `requests.get` call.
- **AC10:** with no failure, the payload has no `keyword_failure_html` key.

Browser (real DOM):

- **AC11:** a `required_browser` test, in the style of `tests/test_search_replay_browser.py`, shows that a More response with the field shows the notice inside `#jst-cards-container`, above the cards, with no "No more jobs on this page." text, and that the next successful response without the field removes it. See Q2.

Safety:

- **AC12:** with a fake key in the environment and an exception or response body containing that key, the key appears nowhere in the page or the JSON, for Reed and Adzuna, on the first page and on More.
- **AC13:** a search handler raising an untyped exception whose text contains a URL and a fake key produces the notice with `<source> search failed` and none of the raw text. The same holds for LinkedIn's `RuntimeError`.
- **AC14:** a keyword containing `<img src=x onerror=...>` appears escaped on the first page and in the JSON.

Whole build:

- **AC15:** `_partial_error_count` no longer appears in `src/`. The full suite shows no new failures against the baseline taken at `db8c6b6` (50 failed, 2838 passed, 16 skipped; those 50 depend on test order and are being fixed on `fix/main-test-regressions-2026-11-05`). New tests pass alone and in the full run.
- **AC16:** `PROJECT_TODO.md:45` is marked done in place. `PROJECT_LOG.md`, the `INDEX.md` Feature Map row (`:313`), `docs/function_list.md` (`:204`) and this spec's status header are updated.
- **AC17:** one view in the built-in browser against a local server from a scratch script that fakes `requests.get`: first page and Next page. This confirms the look. It is producer evidence, not a verifier result, and it makes no live API call.

## 5. Risks

- **R1:** in the AC4 case the page still says "No Reed results found" under the notice. That text is true for the working keywords, and the notice directly above it says what failed. Changing it means editing all three renderers, so it is left out.
- **R2:** the all-failed banner and the all-failed More error still show raw `str(exc)` for untyped exceptions (`src/ui_handlers.py:1213`, `:2137`). Existing behaviour and outside this notice. Listed in section 6.
- **R3:** the fixed messages are in English only, like the rest of the page.

## 6. Not in this build

- Raw text in the all-failed banner and More error for untyped exceptions (R2).
- The stray `)` in `margin-bottom:6px);` in the banners at `src/job_sources/reed_source.py:518` and `adzuna_source.py:443`.
- Merging or pushing any of these branches.

## 7. Questions for Mike

- **Q1. LinkedIn and untyped errors.** LinkedIn takes the same path, but its errors carry raw text, so its messages are not safe to show. Recommended: show the notice for every source, using the fixed `<source> search failed` text when the error is not a `ReedFetchError` or `AdzunaFetchError`. Alternative: Reed and Adzuna only, which leaves LinkedIn silent.
- **Q2. Running the browser test.** The Playwright Python package is not in the project venv, so `required_browser` tests skip here. The browser binaries are already cached. Recommended: download the package (`playwright>=1.59,<1.60`, as in the project requirements file) into this session's scratchpad, not the venv, so AC11 actually runs. Alternative: no download; AC11 stays written but unrun here, and AC17 is the only real-DOM evidence.

**Answers (Mike, 2026-11-06):** Q1 recommended option: notice for every source, with the fixed text for other errors. Q2 recommended option: download the Playwright package into the session scratchpad.

## 8. Build order and stop conditions

1. Baseline already taken at `db8c6b6`.
2. Backend: failure collection, helper, first page, More payload, with AC1-AC10 and AC12-AC15 tests. Commit.
3. `jstLoadMore` with AC11. Commit.
4. Live view, AC17.
5. Fresh verifier, full-suite comparison, docs. Commit. No push or merge.

Stop and ask Mike if a finding survives two fixes, if the design needs a change to `sub_errors` text or to the all-failed paths, or if a real key or a live call seems to be needed.

## 9. Build record

- Commits: `c66a249` (backend and tests), `de8dfa8` (`jstLoadMore` and browser test), `7ccbe23` (notice bottom margin, seen in the live view). Not pushed, not merged.
- Tests: `tests/test_partial_keyword_failure_notice.py` (32 tests); `tests/test_partial_keyword_failure_browser.py` (1 test, needs Playwright, skips in the venv; Playwright was installed only into the session scratchpad).
- Live view (AC17), 2026-11-06, built-in browser against a local scratch server with `requests.get` faked, no live API call: Reed first page; Reed Next page failing again then succeeding (notice gone, retried keyword's jobs shown); Reed no-results case (notice plus Next page button); Adzuna first page. The Browser pane was hidden, so the smooth scroll did not animate; the scroll target was confirmed as the notice by recording the call. Producer evidence, not a verifier result.
- Full suite: baseline at `db8c6b6` 50 failed, 2838 passed, 16 skipped; the implementer's full run before `7ccbe23` 50 failed, 2870 passed, 17 skipped, same failure names.
- Fresh verifier, 2026-11-06 at `8ed6bda`: targeted tests 166 passed; browser tests with Playwright 4 passed; full suite 50 failed, 2870 passed, 17 skipped, with the same failure names as the baseline. Three deliberate breaks (raw error text, unescaped keyword, no More notice) each made the expected tests fail. It could not check AC17, having no browser tool. Not tested: a More page with a notice where all jobs are hidden (correct by reading the code).
