# Developer Handoff Prompt

Copy this into a new chat session to hand off development context.

---

## Paste this into the new session:

---

You are helping me build a **local job-seeking tool** — a Python HTTP server (`src/job_hunt_ui.py`) I run on my laptop. It searches job boards (Reed, and more to come), evaluates jobs against my CV/profile, tracks applications, and will soon auto-evaluate daily. The project is in my connected workspace folder.

**My background:** IT Business Analyst / IT Project Manager, 40s, based in UK (moved from Hong Kong 4 years ago).

---

## Key files to read before starting

| File | What it is |
|---|---|
| `PROJECT_TODO.md` | Master task list — phase status, what's done, what's next |
| `INDEX.md` | Feature map — maps each feature to its design spec, functions, routes, and UI page |
| `docs/code-review-2026-06-18.md` | Full codebase review — architecture issues, quick wins (QW-1 to QW-9), medium-term (MT-1 to MT-7), longer-term (LT-1 to LT-3) |
| `function_list_v4.md` | All key functions with signatures and locations |
| `ui_structure_v4.md` | Current UI page structure |
| `PROJECT_LOG.md` | Session history — what was built and when |

## Design specs (in `docs/tasks/`)

| File | What it covers |
|---|---|
| `backlog-01-daily-digest-design.md` | Daily digest — auto-evaluate, saved searches, high-match feed (v2, all reviewer findings resolved) |
| `lt-01-ui-layer-split-design.md` | LT-1 — splitting `job_hunt_ui.py` into 5 focused layers (v2, all reviewer findings resolved) |
| `gap-j-gap-coach-design.md` | Gap Coach feature (deferred) |

---

## Current codebase state

- **291 tests green** as of last session
- `src/job_hunt_ui.py` — 4,729-line god module containing everything (routes, handlers, render, utils, Reed source logic)
- `src/job_hunt_index.py` — SQLite index (`jobs` table, 14 columns; `upsert_job()` uses `INSERT OR REPLACE` — a known issue, fix is in LT-1 design)
- `src/job_sources/source_registry.py` — `JobSource` registry; `search_handler` returns UI result dicts (not NormalizedJob); `render_results` is currently 3-arg but needs to be 4-arg (`more_url=None`) when MT-1 lands
- `src/job_hunt_profile.py` — `CandidateProfile` dataclass; `OPTIONAL_PROFILE_FIELDS` set; loader raises `ProfileValidationError` on any unknown field — adding new fields requires touching 4 places (dataclass + set + `from_dict` + `to_dict`)
- `src/job_sources/reed_source.py` — does NOT exist yet; Reed logic is still in `job_hunt_ui.py` (extraction is MT-1)

---

## Recommended build order

Start with **quick wins** first — low risk, no design doc needed:

| # | Task | File | What |
|---|---|---|---|
| QW-1 | Fix `_score_required_skills` | `job_hunt_scoring.py` L91–108 | Change signature to `list[str]`, remove double-iteration |
| QW-2 | Fix ATS scorer ALL-CAPS penalty | `job_hunt_ats_scorer.py` L74–80 | Remove/flip inverted heading penalty |
| QW-3 | Remove `logging.basicConfig` | `reed_client.py` L10 | Overrides host logging config |
| QW-4 | Delete `shared_bus.py` | `shared_bus.py` | Dead code, duplicate definitions, hardcoded foreign path |
| QW-5 | Remove `evaluate_job_from_raw` from `__all__` | `job_hunt_evaluation.py` L109 | Function doesn't exist |
| QW-6 | Fix `job_hunt_config.py` `__all__` | `job_hunt_config.py` L106 | Lists 1 of 6 exports |
| QW-7 | Extract `_upsert_job_to_index()` helper | `job_hunt_ui.py` | 5 copy-pasted upsert blocks |
| QW-8 | Add dimension-level cap to `_score_skill_bucket` | `job_hunt_scoring.py` L141 | Bonus inflates past dimension weight cap |
| QW-9 | Add skill name length cap (~120 chars) | `job_hunt_ui.py` L~1091 | Unbounded strings in profile JSON |

Then move to **MT-1** (Reed source extraction into `src/job_sources/reed_source.py`) — this is a prerequisite for both LT-1 (layer split) and the Daily Digest (backlog-01).

After MT-1, the **Daily Digest** (backlog-01) can be built in 5 phases (D1 → D5). Read `docs/tasks/backlog-01-daily-digest-design.md` before starting — it has all schema, interface, and profile contract details already worked out.

---

## Key rules / constraints

1. **Run tests before and after every change:** `python -m pytest tests/ -q`
2. **After modifying any page's render function:** bump `_PAGE_UPDATED["<page_key>"]` in `src/job_hunt_ui.py` (around line 55) and run `update-project-docs` skill.
3. **Adding new fields to `CandidateProfile`:** must update `OPTIONAL_PROFILE_FIELDS`, `candidate_profile_from_dict()`, `candidate_profile_to_dict()`, the profile UI save handler, and tests. Missing any one of these breaks profile load.
4. **`search_handler` returns UI result dicts**, not `NormalizedJob` — don't call `reed_job_to_ui_result()` on the output.
5. **No `do_DELETE` in the HTTP server** — use `POST /resource/{id}/delete` for deletions.
6. **`INSERT OR REPLACE` in `upsert_job()`** deletes the row and re-inserts — any new columns added to the schema are silently reset to NULL unless you also update `upsert_job()`. The LT-1 design switches this to `ON CONFLICT DO UPDATE`.
7. **`source_registry.py` `render_results`** is currently 3-arg in the codebase but 4-arg in the design (MT-1 updates the contract). Don't call it with 4 args until MT-1 is done.

---

## Task for this session

**[Fill in what you want to build, e.g. "Start with QW-1 through QW-4" or "Build MT-1 — Reed source extraction" or "Build D1 — Saved Searches"]**
