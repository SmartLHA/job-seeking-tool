# Handover — Daily Job Digest (Backlog-01)

**As of:** 2026-06-24 · **Owner:** Mic · **State:** ✅ **SHIPPED** — Daily Digest D1–D6 are implemented and live (this handover is now historical; see `backlog-01-daily-digest-design.md` STATUS block and `PROJECT_LOG.md`).

## What this feature is
Run saved searches on a schedule → deterministically score new jobs against the profile → surface only high-match, first-seen jobs in a Digest feed → run rate-limited LLM analysis on the top scorers. Phases **D1–D6**.

## Read these first (in order)
1. `docs/tasks/backlog-01-daily-digest-design.md` — the spec (v5, authoritative).
2. This handover.
3. `PROJECT_TODO.md` → "Daily Job Digest" backlog + Deferred table.

## Status of the work so far (this was a design-only effort)
- Verified the v2/v3 design against current code; found gaps → rewrote to **v3**.
- Ran **design-council / Codex** review → applied **8 fixes** → **v4**.
- Applied a **16-item pre-implementation review** → **v5** (current).
- Prereqs **MT-1** (Reed source extraction) and **LT-1** (UI layer split) are ✅ done — nothing blocks the build.

## Decisions locked (do not re-litigate)
- **Dedup key = `lower(source) + source_job_id`.** URL is metadata only. Requires new `JobPosting.source_job_id` field.
- New apply-URL index column is named **`apply_url`** (not `source_ref`). Legacy `JobPosting.source_ref` field name kept as-is.
- **Canonical `job_id` = `digest_job_id(source, source_job_id)`** in both manual + digest paths; partial `UNIQUE(source, source_job_id)` index + `IntegrityError` fallback in `upsert_job`.
- **New-only digest:** already-seen jobs are never re-added/re-scored (§7a).
- **LLM result → `JobAnalysis`** (5 new fields); jobs table holds only queue metadata.
- **Rate limits (Gemini free tier, user-confirmed):** `gemini-3-flash-preview`/`gemini-2.5-flash` = 5 RPM, `gemini-3.1-flash-lite` = 15 RPM, RPD ≈ 250. Defaults: `rpm=4, rpd=200, batch_size=4, interval=15min`. All configurable + range-validated.
- **LLM queue is decoupled & paced:** D3 only *queues* (`llm_status="pending"`); D6 worker drains in token-claimed batches with backoff/requeue on 429, daily cap, stale-claim recovery.

## Open items
- **OQ-1 — RESOLVED:** manual job (no id) + digest hit may be two rows; acceptable, no reconcile.
- **OQ-2 — deferred to to-do:** re-score seen jobs on profile/threshold change (tracked in `PROJECT_TODO.md` Deferred table).

## Next action — build order
**D1 (Saved Searches) is fully independent of every fix above — safe first slice.**
- `src/job_hunt_saved_searches.py` (+ tests), own `data/state/saved_searches/` dir (slug-sanitised, path-traversal safe).
- Routes: `GET/POST /saved-searches`, `POST /saved-searches/{id}/delete`, `/toggle`.
- UI: "Save this search" on Find Jobs; Saved Searches section in My Profile.
- Deliverable: save/list/delete searches, no auto-run.

**Then D2 — strict order (model first; §10 in spec):**
1. `JobPosting.source_job_id` field → 2. reviewed-job serialisation round-trip → 3. Reed/Adzuna adapters populate it → 4. DB migration (10 cols incl. claim cols, WAL+busy_timeout) → 5. indexes (§3.1a) → 6. `upsert_job` ON CONFLICT + IntegrityError fallback → 7. `rebuild_index` → 8. digest query layer → 9. tests.

D3 → D4 → D5 → D6 follow per spec §10.

## Acceptance checklist
At the end of the v4/v5 changelog in the spec + Mic's 16-item list. Key gates: no stale dedup text, blank `source_job_id` skipped+logged, `jobs_llm_queued` (not analysed) in D3, profile bool/range validation, LLM result in `JobAnalysis`, stale-processing recovery via `llm_claimed_at`.

## Project rules reminder
- Skill routing in `CLAUDE.md` (office-hours, ship, qa, etc.).
- Bump `_PAGE_UPDATED[key]` in `src/job_hunt_ui.py` when changing any page render.
- After shipping: run the `update-project-docs` skill.
- Complete each phase fully (tests green) before the next.

## Tooling note
Codex MCP review timed out on big multi-file prompts (`-32001`). Workaround that worked: **split into small scoped calls** (1–2 named files, one question, "don't search the rest of the repo"). Model override is rejected on a ChatGPT-account Codex — omit the `model` param.
