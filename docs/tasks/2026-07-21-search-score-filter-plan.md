# Plan — Search / Score / Filter improvements (2026-07-21)

<!-- STATUS -->
**Implementation status: ✅ Implemented 2026-07-22.** All four slices built as
locked below; no divergences from the locked decisions.
- Key functions: `src/job_sources/relevance.py` (`bucket_jobs_by_relevance`,
  `is_relevant_title`, `is_relevant_description`); `src/job_sources/dedup.py`
  (generalized `_identity_fields`/`is_duplicate_job`/`deduplicate_jobs`);
  `src/job_sources/search_state.py` (`start_search`, `filter_new_page`,
  `known_search`); `src/job_hunt_scoring_presets.py` (`PRESET_WEIGHTS`,
  `load_preset_name`, `save_preset_name`, `get_active_scoring_policy`);
  `src/ui_chip_field.py` (`render_chip_field`, `CHIP_FIELD_JS`);
  `src/ui_handlers.py` (`_parse_keyword_terms`, `_run_multi_keyword_search`,
  `handle_set_scoring_preset`, wiring in `handle_source_search` /
  `handle_source_search_more`).
- Routes: new `POST /scoring-preset`; existing `GET /search/{source}`,
  `GET /search/{source}/more` gained relevance-bucketing, dedup, and
  multi-keyword search behind the same URLs.
- Tests: `tests/test_search_dedup.py` (5), `tests/test_relevance.py` (8),
  `tests/test_relevance_ui.py` (2), `tests/test_scoring_presets.py` (9),
  `tests/test_scoring_preset_ui.py` (3), `tests/test_multi_keyword_search.py`
  (6) — all green. Full suite (project venv): 1005 passed, 2 failed (both
  pre-existing/unrelated — digest run-now route test and the known
  tailor-CV test), 1 skipped.
<!-- /STATUS -->

Design-council planning doc. NOT approved for build. Four slices.

## Context (from scout, file:line verified)
- UI stack: stdlib `http.server` + hand-built HTML strings (`src/ui_routes.py:16-17`). NOT Flask/Streamlit.
- Sources: Reed API, Adzuna API, LinkedIn public scrape (`src/job_hunt_config.py:107`).
- Fit score: `src/job_hunt_scoring.py:23` `score_job`, 7 weighted components; weights in
  `src/job_hunt_config.py:9-39` `ScoringWeights` (skills_required 35, preferred 5, experience 20,
  location 10, salary 10, domain 10, work_mode 10 = 100), sum validated in `__post_init__` (:32-39).
- Search: keyword passed verbatim to external API (`reed_client.py:38`). NO local relevance filter
  anywhere in `src/job_sources/*` or `ui_handlers.py`. Only local filters are exclusions
  (`ui_handlers.py:790-805, 832-847`).
- Dedup: `deduplicate_jobs()` exists (`src/job_sources/dedup.py:38`) but is ONLY wired into the CLI
  orchestrator (`job_hunt_orchestrator.py:22,165`) — NEVER called from interactive search
  (`ui_handlers.handle_source_search` :808-868, `handle_source_search_more` :1381+).
- Filter form: single-value `keywords` input (`ui_handlers.py:2346`); work_mode/employment single
  `<select>` applied "best-effort" only (`reed_source.py:388-403`). Multi-value parsing exists only
  for "Exclude keywords" (`_parse_exclude_terms` :775-786).

## Product goal
Make search results trustworthy (relevant + no duplicates), scores reflect Mike's real priorities,
and let him search several roles/locations at once without fighting the input boxes.

## Success criteria (observable)
1. Searching "Business Analysis" no longer returns clearly-unrelated titles (e.g. "Store Manager").
2. No duplicate job cards in a result list, including after "Show more".
3. Mike can adjust the 7 scoring weights and see scores recompute; weights persist across restart.
4. Mike can enter multiple keywords AND multiple locations in one search → one merged, deduped list.
5. Multi-value fields use chip/tag entry, not raw comma strings.

## Non-goals
- Rewriting the HTTP server / migrating to a framework.
- Semantic/embedding relevance (keep it lexical for v1).
- Changing external API providers or scraping approach.
- Per-source weight profiles.

## Constraints
- stdlib http.server + string HTML — no new heavy frontend deps; chips must be vanilla JS.
- Free-tier API rate limits (Reed/Adzuna) are UNVERIFIED and likely throttled — multiplying calls
  (keywords × locations) is the top operational risk.
- ScoringWeights sum must stay validated (=100 or normalized).

## Risks
- R1 (HIGH): multi-keyword × multi-location = N×M API calls per search → rate-limit/latency blowup.
- R2 (MED): relevance filter too aggressive drops legitimate jobs (e.g. "BA" vs "Business Analyst");
  too loose keeps "Store Manager". Needs a tunable, visible rule.
- R3 (MED): "Show more" pagination dedup must persist seen-keys across calls, not just per page.
- R4 (MED): editable weights = persistence + validation + recompute of already-listed jobs.
- R5 (LOW): chip UI must degrade gracefully (no JS → still submits).

## Slices (proposed order — each independently shippable)

### Slice B — Wire dedup into live search  [smallest, lowest risk → do first]
- Call `deduplicate_jobs()` inside `handle_source_search`; for `handle_source_search_more`, track
  seen dedup-keys in the session/paging state and drop already-shown jobs.
- Acceptance: no duplicate cards in a single search; none after "Show more".

### Slice A — Local relevance filter  [fixes Store-Manager]
- After fetch, score each job's TITLE against query tokens; drop (or bucket as low-relevance) jobs
  with no meaningful token overlap. Tunable threshold + small alias map (BA↔Business Analyst).
- Match against title primarily; description as weak signal only (avoid false positives).
- Acceptance: "Business Analysis" search excludes "Store Manager" in a fixture test.

### Slice C — Editable scoring weights
- Add a weights panel (7 sliders/number inputs) persisted to a config/JSON file; validate/normalize
  to 100; recompute listed jobs. Default = current values so nothing changes until Mike edits.
- Acceptance: change a weight → scores change on reload; persists across restart; sum enforced.

### Slice D — Multi-keyword + multi-location + chip entry  [largest, highest risk]
- Parse multiple keywords and multiple locations; run the cross-product of searches, merge, then
  reuse Slice B dedup. Cap total calls (e.g. max keywords×locations) to protect rate limits.
- Chip/tag vanilla-JS input for keywords, locations, exclude-keywords; hidden field submits
  comma-joined values so the no-JS path still works.
- Acceptance: 2 keywords + 2 locations → single merged deduped list; call count capped; chips submit
  correctly with JS on and off.

## Codex review — converged design changes (2026-07-21)
Independent read-only review raised 4 HIGH items, all "simplify", now folded in:
- A: drop the growable alias map. Use a **role-family rule** (normalise punctuation/plurals/known
  abbrevs; require ≥1 strong role term e.g. analyst/analysis/BA/requirements; short hard-exclude list
  only when no strong term present). **Bucket** non-matches under "Other results", do NOT hard-drop.
- D: N×M cross-product is a rate-limit trap. Preferred design = **multiple keywords × ONE location +
  radius**. Multiple locations only behind a hard call-cap that reports skipped combinations.
- B: seen-key state must NOT be global. Key it by a random **search-id** in a server-side dict,
  guard mutations with a lock (server is ThreadingHTTPServer → real concurrency), expire old entries.
  "Show more" resubmits the search-id + immutable original criteria; new search resets state.
- C: full editable panel is over-engineered for a single user. Start with **named presets**
  (Balanced / Salary-focused / Skills-focused); manual 7-integer edit optional, atomic JSON write
  (temp+rename), never silently normalise — show normalised values before applying.
- Pipeline (test as one unit): fetch → normalise → relevance-bucket → dedup → score → sort → paginate.

## Decisions — LOCKED by Mike (2026-07-21)
- Relevance: **bucket non-matches under "Other results"** (collapsed), never hard-drop.
- Multi-input: **multiple keywords + ONE location + radius** for v1. No multi-location cross-product.
- Weights: **named presets only** (Balanced / Salary-focused / Skills-focused). No manual 7-number
  editor in v1. Presets persist across restart via atomic JSON write.

## Final build order & acceptance (approved-pending)
1. Slice B — dedup in `handle_source_search` + search-id-keyed seen-set (lock, expiry) for "Show more".
   AC: no dup cards single search; none after "Show more"; new search resets; concurrent "more" safe.
2. Slice A — role-family relevance rule; matches → main list, non-matches → "Other results" bucket.
   AC: fixture "Business Analysis" search puts "Store Manager" in Other, keeps "Business Analyst"/"BA".
3. Slice C — 3 named weight presets, selectable, persisted (atomic JSON), scores recompute on switch.
   AC: switch preset → scores change; persists across restart; corrupt/missing file falls back to Balanced.
4. Slice D — multi-keyword parse + chip entry (keywords/location/exclude) with no-JS comma fallback;
   single location + radius; merge+reuse Slice B dedup.
   AC: 2 keywords + 1 location → one merged deduped list; chips submit with JS on and off.

Pipeline order (single tested unit): fetch → normalise → relevance-bucket → dedup → score → sort → paginate.
