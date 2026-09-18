# Search Triage F2/F3 Implementation Scout — 2026-08-10

## Conclusions

`TRIAGE-F2` belongs wholly in `handle_source_search_more()`: it is the only path that currently produces an empty-page placeholder after the existing hidden/exclude/dedup pipeline. It must reuse the current per-keyword cursor vector, not invent a global cursor. Limit internal fetch cycles with a small constant; stop on visible target, exhaustion, or cap. Keep main and Other results as separate aggregates and preserve the existing response fields.

`TRIAGE-F3` is a client-only change to the shared `_multiselect.py` overlay. The overlay already loads a bounded list and uses `textContent`, so no store or route change is necessary. Add a labelled live filter and render from the fetched array rather than filtering stored data.

## F2: Current pagination and data flow

| Stage | Evidence | Current behaviour |
|---|---|---|
| GET dispatch | `src/ui_routes.py:270-276` | `GET /search/{source}/more` goes to `handle_source_search_more`. |
| Parameter conventions | `src/ui_handlers.py:793-801` | Reed/Adzuna use `resultsToTake`/`resultsSkip`; LinkedIn uses `results_to_take`/`results_skip`. |
| Term parsing/cap | `src/ui_handlers.py:823-841`; `956-988` | Comma-separated terms are de-duplicated and capped at six before the initial request. |
| Per-term search | `src/ui_handlers.py:844-890` | Every non-exhausted term is searched once with its own offset. A full result page advances only that term; a short page becomes exhausted (`None`). |
| Cursor wire format | `src/ui_handlers.py:893-920` | URL `keywordCursors` is a comma vector of non-negative offsets or `x`; malformed vectors return a 400. |
| Initial page state | `src/ui_handlers.py:1001-1081` | The initial search applies bucket → per-bucket dedup → not-interested filter → exclude filter, seeds a search-id with both buckets, and creates the More URL with the cursor vector. |
| Cross-page dedup state | `src/job_sources/search_state.py:46-81` | Search ID is process-local, lock-guarded, TTL-bounded, and seeded from all cards initially rendered. Each later filter call updates the seen set. |
| Existing More handler | `src/ui_handlers.py:1616-1733` | Fetches exactly one raw source page/set of keyword pages, repeats the same display pipeline, produces `cards_html`, `other_results_html`, `next_url`, `has_more`, `count`, `visible_count`, and `hidden_count`. |
| Empty-page UI | `src/job_sources/_multiselect.py:328-374` | The client replaces visible cards; when `visible_count` is zero it displays an explanatory note and leaves Next page available when `has_more` is true. |

### Exact current filtering order in More

`handle_source_search_more()` performs relevance bucketing at `src/ui_handlers.py:1662-1670`, deduplicates each bucket at `1671-1676`, filters not-interested records at `1677-1686`, filters exclude keywords at `1687-1694`, and cross-page deduplicates main then Other at `1695-1707`. Rendering then uses the request's logical skip for main cards and skip plus rendered-main count for Other cards (`1708-1710`). This ordering is the SSF-F1 contract and must stay unchanged per fetched page.

### Minimal compatible F2 shape

1. Add a private cap, e.g. `_MAX_HIDDEN_PAGE_LOOKAHEAD = 3`, beside `_MAX_KEYWORD_SEARCHES` in `src/ui_handlers.py`.
2. Refactor the single More-page pipeline in `1616-1733` into a small private helper returning one processed page: main results, Other results, raw count, filtered count, whether any term was full, next per-term offsets, and sub-errors. The helper must call `filter_new_page(search_id, ...)` for both buckets exactly once per fetched page.
3. In `handle_source_search_more`, process the requested page first. If it has visible cards, preserve one-page behaviour. If it is fully filtered, repeatedly call the helper using its `next_offsets` until at least `take` visible cards are aggregated, all terms are exhausted, a no-more page is observed, or the cap is reached.
4. Aggregate main and Other lists separately; only render once at the end. Use the starting requested `skip` as the virtual render offset and main-list length for the Other offset. This keeps IDs unique against the page just removed by the client and avoids mixing Other cards into the main bucket.
5. Build the next URL from the final cursor vector. Retain the scalar skip for legacy/default parsing, incremented once per internal source-page cycle; multi-keyword continuation authority remains `keywordCursors`.
6. Return the existing JSON fields unchanged. Optionally add `lookahead_pages` for observability only; the current client does not need it. `hidden_count` and `count` should accumulate across internally consumed pages so an exhausted/capped empty response tells the truth.

### F2 edges and risks

| Edge | Required behaviour |
|---|---|
| One main page entirely hidden, next page visible | Respond with next-page visible cards in the same click; URL advances beyond both consumed pages. |
| Only Other results survive | They count toward the visible target and remain in `other_results_html`; main HTML stays empty. |
| Multi-keyword uneven exhaustion | Use `next_offsets` from each pass; never re-query an `x` term. This is the SSF-F2 invariant. |
| Partial source error | Preserve current semantics: a failed term retains its offset for retry; do not convert partial success into a hard error. |
| All pages hidden through cap | Return the existing empty response/note, but with accumulated counts and a next URL only if terms can still continue. |
| Dedup eliminates every later result | Treat as no visible result and subject it to the same cap; do not reset or recreate the search ID. |
| Browser selections | `jstLoadMore` retains selected card form fields before removing old cards (`src/job_sources/_multiselect.py:337-350`). New IDs must not collide with those retained IDs. |
| Provider rate limits | The cap must be small and fixed; every internal iteration invokes all still-active keyword sub-searches. |

## F2: Best existing tests and required additions

| Existing test | Evidence | What it already protects |
|---|---|---|
| Later-page Other bucket | `tests/test_relevance_ui.py:138-157` | Nonmatching later-page titles stay in `other_results_html`, not main cards. |
| Independent cursor continuation | `tests/test_multi_keyword_search.py:214-252` | A term exhausted at 10 is not requested at 20 while another term continues. |
| Generic More route/IDs | `tests/test_ui.py:1863-1896` | More response has offset card IDs, `has_more`, count, and an advanced cursor. |
| Hidden-store path | `tests/test_not_interested.py:85-121`, `179-209` | Key/fingerprint filtering plus hide/list/undo routes. |

Add focused route tests, preferably to `tests/test_relevance_ui.py` or a new search-specific test file:

1. first More page all hidden, second page supplies one main result; assert two source calls, visible result, no empty note, and next URL skip/cursor after both source pages;
2. same, but only an Other result survives; assert bucket separation;
3. first page all hidden with two terms, one exhausted and one continuing; assert calls prove no retry of the exhausted term and final cursor includes `x`;
4. all hidden through cap; assert bounded call count, empty payload, and continuing next URL only when a term still has a full page;
5. selected-card ID safety is adequately covered by a browser smoke only if this change modifies `jstLoadMore`; otherwise handler regressions suffice.

## F3: Current Hidden Jobs overlay path

| Layer | Evidence | Current behaviour |
|---|---|---|
| Store list | `src/job_hunt_not_interested.py:180-191` | `list_hidden()` returns newest-first key/source/title/company/hidden time, limited to 1,000. |
| Store filter contract | `src/job_hunt_not_interested.py:216-246` | Search-page filtering uses key or fingerprint; F3 must not change this persistence behaviour. |
| GET route | `src/ui_routes.py:283-285`; `src/ui_handlers.py:1803-1816` | `GET /jobs/not-interested` returns `jobs`, bounded list count, and total count. |
| Overlay static markup | `src/job_sources/_multiselect.py:20-55` | Overlay has title/count, close button, and `jst-hidden-list`; it has no query field. |
| Overlay fetch/render | `src/job_sources/_multiselect.py:234-275` | `jstShowHidden` fetches records, creates DOM nodes, uses `textContent` for title/metadata, and Unhide removes the row. |
| Footer trigger | `src/job_sources/_multiselect.py:487-516` | Shared footer opens the overlay for every source. |
| Existing browser test pattern | `tests/test_ui.py:1018-1065` | Playwright test skips cleanly if unavailable and captures page errors. |
| Existing contract test | `tests/test_not_interested.py:217-255` | Static JS/markup wiring for hide, undo, overlay, and Next page. |

### Minimal compatible F3 shape

1. Add a visible label plus input (for example `id="jst-hidden-filter"`) to the overlay header in `_multiselect.py`; include a clear button only if it is keyboard-accessible.
2. In `jstShowHidden`, retain `d.jobs` in a local/overlay-scoped array and render via one `renderHiddenJobs(query)` function. Filter a normalised query across title, company, and source; do not make another HTTP request.
3. Keep the DOM-safe construction path (`createElement`, `textContent`). Render a distinct “No hidden jobs match this filter” empty state. Display matched count versus loaded count; do not imply all `d.count` records are present when total exceeds the 1,000 endpoint cap.
4. On Unhide, remove the record from the retained array, re-render through the current filter, and update both count labels from `total_hidden`.
5. Clear filter state when reopening the overlay unless retaining it is an explicit UX decision; reset-on-open is the lower-surprise default.

### F3 tests

- Extend `tests/test_not_interested.py:217-255` to assert input, label, filtering function, and no unsafe `innerHTML` interpolation of job fields.
- Add a Playwright smoke modelled on `tests/test_ui.py:1018-1065`: seed three hidden jobs through the existing JSON route, open overlay, type a title or company fragment, assert only matching row remains, clear it, and unhide. Assert no page errors and correct hidden count.
- The current store and route tests remain sufficient for persistence; F3 does not require database changes.

## Non-goals

- No change to the `not_interested_jobs` schema or identity/fingerprint rule.
- No automatic network look-ahead on the initial search page; approved F2 scope is the More-page empty-state path.
- No change to SSF-F1 bucket semantics or SSF-F2 cursor grammar.
- No remote pagination/filter endpoint for the overlay; loaded-list filtering is enough under the existing 1,000-record bound.

