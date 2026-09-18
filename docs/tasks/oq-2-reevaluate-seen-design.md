# OQ-2 — Re-evaluate Seen Digest Jobs on Profile/Threshold Change

<!-- STATUS -->
> **Implementation status:** ✅ Implemented 2026-06-26
> **Divergences from spec:** crossing rule refined during build — added the `llm_status IS NULL` ("never queued as a match") signal so a **threshold-only** change actually fires (§4.1 / §15). Re-enrich of `done` jobs (OQ-2-B) is scoped to crossed-up jobs only.
> **Key functions:** `reevaluate_digest_jobs()`, `ReevalResult`, `row_status()`, `list_digest_jobs_for_reeval()`, `resurface_digest_job()`, `requeue_llm_if_eligible()`, `clear_llm_queue()`, `handle_digest_reevaluate()`
> **Routes:** `POST /digest/reevaluate`
<!-- /STATUS -->

**Status:** ✅ Implemented + Codex-reviewed (2026-06-25). 14 new tests green; full digest suites green.
Crossing rule refined during build — see §4.1 / §15. **No critical review findings.**

> **Build note (rev 3):** the "crossed up" test originally used current-threshold-on-both-sides, which
> made a **threshold-only** change a no-op (an unchanged score can't be both `< threshold` and
> `≥ threshold`). The implemented rule adds a second signal so the feature responds to BOTH triggers it's
> named for — see §4.1.
**Backlog ref:** `PROJECT_TODO.md` → "Re-evaluate seen digest jobs on profile/threshold change".
**Parent design:** `docs/tasks/backlog-01-daily-digest-design.md` §7a (new-only behaviour), §14 (LLM queue).
**Prereq:** Daily Digest D1–D6 shipped (done).

---

## 1. Problem

The digest is **new-only by design** (§7a): a result whose `(lower(source), source_job_id)`
already exists in the index is skipped — never re-scored, never re-surfaced. The accepted
consequence is that **changing your profile or `digest_threshold` does not re-score or resurface
already-seen jobs**. OQ-2 is the explicit, user-triggered action that closes that gap: re-score the
jobs already in the index against the current profile/threshold and bring back the ones that now
qualify.

This does **not** change the daily pipeline's new-only rule. It is a separate manual action.

---

## 2. Decisions locked with Mic (2026-06-25)

| # | Decision | Choice |
|---|----------|--------|
| 1 | **Trigger** | **Manual button** only. No auto-on-save. Matches §7a "explicit action". |
| 2 | **Scope** | **All indexed digest jobs** (`digest_date IS NOT NULL`), regardless of seen state or whether the originating saved search is still enabled/exists. |
| 3 | **Surfacing** | A job that **crosses up** to ≥ threshold is **resurfaced** (`digest_seen=0`) **and re-queued for LLM** (subject to caps). |
| 4 | **Process** | Design-first: this doc → council/Codex review → Mic approval, **before** any implementation. |

**Open decisions confirmed by Mic (2026-06-25):**
- **OQ-2-A — stayed-above:** do **not** resurface jobs that were already ≥ threshold and stay ≥ threshold.
  Only newly **crossed-up** jobs resurface.
- **OQ-2-B — re-enrich `done`:** **yes**, re-queue already-analyzed (`done`) jobs for fresh Gemini AI —
  **but only the crossed-up ones** being resurfaced (OQ-2-B follow-up). Stayed-above `done` jobs keep
  their existing AI text.
- **OQ-2-C — resurface date:** **keep** original `digest_date` (first-seen). Not bumped to today.
- **OQ-2-D — re-queue cap:** reuse the existing `digest_max_llm_per_run` (default 10). No new config field.

**Risk flagged to Mic on decision 2:** "all indexed digest jobs" includes jobs whose saved search
was later **disabled or deleted**. Those can resurface even though the user turned that search off.
Mitigations in §8.

---

## 3. Re-scoring is fully local (no network)

Re-scoring reuses exactly the deterministic path the D3 pipeline already runs, minus fetch and skill
extraction:

```
load_reviewed_job(job_id, state_root)        # already on disk; skills already stored
analysis = evaluate_reviewed_job(profile, reviewed_job)   # deterministic, no Gemini
save_job_analysis(analysis, state_root)
upsert_job(db_path, {... new match_score, decision ...})
```

Consequences:
- **No Reed/Adzuna API calls, no rate limits, no `source_job_id` re-fetch.** Pure CPU + local file I/O.
- Skills are **not** re-extracted — the saved `reviewed_job` already carries `required_skills` /
  `preferred_skills` from its first ingest. (Re-extraction would need the raw description and an LLM/Ollama
  call; out of scope. A job's skills don't change, only the profile does.)
- `upsert_job` preserves all digest/LLM columns (they are deliberately **not** in its `ON CONFLICT … SET`
  list, `job_hunt_index.py` §_UPSERT_SQL), so re-scoring **never clobbers** `digest_date`, `digest_seen`,
  `saved_search_id`, or the `llm_*` columns. Resurface/re-queue are therefore **separate, explicit writes**.

---

## 4. Core logic — `reevaluate_digest_jobs(...)`

New function in `src/job_hunt_scheduler.py` (next to `run_digest_pipeline`, reusing `_PIPELINE_LOCK`
so it can't write a job concurrently with the scheduler or a manual Run-now).

```python
def reevaluate_digest_jobs(*, config, profile, db_path) -> ReevalResult:
    with _PIPELINE_LOCK:                       # serialise with pipeline writers
        threshold = profile.digest_threshold
        rows = list_digest_jobs_for_reeval(db_path)   # (job_id, old_score, llm_status), digest_date IS NOT NULL
        requeued = 0
        for job_id, old_score, llm_status in rows:
            try:
                reviewed = load_reviewed_job(job_id, config.state_root)
            except (FileNotFoundError, StorageError):
                jobs_missing += 1; continue            # indexed but JSON gone → skip, count, never crash
            try:
                analysis = evaluate_reviewed_job(profile, reviewed)
            except Exception:
                jobs_errored += 1; continue            # per-job isolation, like the pipeline
            new_score = analysis.match_score
            save_job_analysis(analysis, config.state_root)
            upsert_job(db_path, {... new_score, analysis.decision ...})   # digest cols preserved
            jobs_rescored += 1

            old_below = (old_score is None) or (old_score < threshold)
            new_above = (new_score is not None) and (new_score >= threshold)

            if old_below and new_above:                # CROSSED UP
                resurface_digest_job(db_path, job_id)  # digest_seen = 0
                jobs_resurfaced += 1
                if profile.digest_llm_enabled and requeued < profile.digest_max_llm_per_run:
                    # COMPARE-AND-SWAP: flips NULL/failed/skipped/done → pending, atomically, in the
                    # DB ('done' included per OQ-2-B: a crossed-up job's old AI text is stale, refresh
                    # it). Returns 1 only if it actually changed an eligible row, so a worker that
                    # moved the row to 'processing' (or already to 'pending') since the SELECT is a no-op.
                    if requeue_llm_if_eligible(db_path, job_id) == 1:   # see §5
                        requeued += 1; jobs_llm_requeued += 1
            elif not new_above:                        # DROPPED BELOW / stayed below
                # CAS guard (WHERE llm_status='pending'); no-op if the worker already claimed it.
                if clear_llm_queue(db_path, job_id) == 1:
                    jobs_dequeued += 1
        return ReevalResult(...)
```

### 4.1 Crossing semantics (precise — as implemented)

```
new_above          = new_score is not None and new_score >= threshold
old_below_by_score = old_score is None or old_score < threshold      # profile raised the score
never_queued       = row.llm_status is None                         # never treated as a match before
crossed_up         = new_above and (old_below_by_score or never_queued)
```

- **threshold** = the *current* `profile.digest_threshold`.
- `old_score` / `llm_status` come from the row snapshot read **before** the re-score upsert.
- **Why two signals:** a pure **threshold** change can't move a job's score, so an `old_score` vs
  `threshold` test alone can never fire on a threshold edit. `llm_status IS NULL` is the proxy for "the
  ingest pipeline never queued this as a match" (it only queues jobs `≥` the threshold in force at
  ingest). Adding `never_queued` makes the feature respond to **both** triggers: profile edits that raise
  the score **and** threshold lowering / enabling AI later. (See §15 for the accepted trade-off.)
- **Crossed up** → resurface (`digest_seen=0`) + re-queue for AI within the cap. Only resurface case.
- **Stayed above and already a match** (`new_above`, was queued, score not below bar) → score/decision
  updated, **no resurface, no re-queue** — don't nag (OQ-2-A).
- **Dropped below / stayed below** (`not new_above`) → score/decision updated; an un-started `pending`
  LLM job is dequeued.

### 4.2 Why a per-job `try/except`

Same contract as the pipeline: one bad row (missing JSON, eval error) is counted and skipped, never
aborts the whole re-eval. A row indexed but with its `reviewed_job` JSON deleted is the realistic case
(`jobs_missing`).

---

## 5. New persistence helpers (`src/job_hunt_index.py`)

Four small additions; all parameter-bound, all scoped to digest rows. **Every LLM-status write is a
compare-and-swap (CAS) with the guard in the `WHERE` clause and returns the affected `rowcount`** — so a
stale snapshot can never overwrite a concurrent worker transition (§14).

```python
def list_digest_jobs_for_reeval(db_path) -> list[Row]:
    # SELECT job_id, match_score AS old_score FROM jobs WHERE digest_date IS NOT NULL
    # ORDER BY match_score DESC, job_id ASC      -- stable secondary sort so a CAPPED re-queue
    #                                            -- picks the SAME highest-scorers each run
    # NOTE: llm_status is NOT selected for decisioning — the CAS helpers below re-check it in-DB.

def resurface_digest_job(db_path, job_id) -> int:
    # UPDATE jobs SET digest_seen = 0 WHERE job_id = ? AND digest_date IS NOT NULL  -> rowcount
    # (Does NOT touch digest_date or saved_search_id — unlike set_digest_meta.)

def requeue_llm_if_eligible(db_path, job_id) -> int:
    # CAS re-queue. Atomic single UPDATE:
    # UPDATE jobs
    #    SET llm_status='pending', llm_attempts=0, llm_next_attempt_at=NULL,
    #        llm_claimed_at=NULL, llm_claim_token=NULL
    #  WHERE job_id=? AND digest_date IS NOT NULL
    #    AND (llm_status IS NULL OR llm_status IN ('failed','skipped','done'))   -- guard
    #        -- 'done' is eligible (OQ-2-B: refresh stale AI on a crossed-up job).
    #        -- 'pending' (already queued) and 'processing' (in flight) are NOT eligible.
    # Returns rowcount (0 if the worker moved it to processing, or it was already pending).

def clear_llm_queue(db_path, job_id) -> int:
    # UPDATE jobs SET llm_status=NULL, llm_next_attempt_at=NULL,
    #        llm_claimed_at=NULL, llm_claim_token=NULL
    #  WHERE job_id=? AND llm_status='pending'      -- guard: only un-started queue entries
    # Returns rowcount (0 if the worker already claimed it to 'processing').
```

Why CAS instead of reusing `set_llm_status(..., 'pending')`: `set_llm_status` writes by `job_id`
**unconditionally**, so a snapshot that was `failed`/`done` at SELECT time but **`processing`** (claimed
by the worker) by action time would be yanked back to `pending`, clearing the claim token while the
worker's Gemini call is still in flight — double-processing. The guarded single-statement UPDATE checks
the live status in the same statement, so the worker and the re-eval can't lose each other's writes. We
re-queue `NULL`/`failed`/`skipped`/`done` rows (per OQ-2-B, a crossed-up `done` job's stale AI is
refreshed) but **never** `pending` (already queued) or `processing` (in flight); the guard enforces
exactly that. Re-queue resets `llm_attempts=0` so the refreshed call gets a full retry budget.

---

## 6. HTTP route + handler

| Method | Path | Body | Returns |
|--------|------|------|---------|
| `POST` | `/digest/reevaluate` | none | `ReevalResult` JSON |

No `do_DELETE`, POST-for-mutation, matching existing server style.

`handle_digest_reevaluate(req, config, responder)` in `src/ui_handlers.py`:
load active profile → call `reevaluate_digest_jobs(...)` → `send_json({"ok": True, **result.to_dict()})`.
Profile-load failure → 500 with a clear message (same shape as `handle_run_now`). Wire in
`src/ui_routes.py` `do_POST` next to `/digest/run-llm-batch`.

`ReevalResult` (frozen dataclass, `to_dict()`):
`jobs_examined, jobs_rescored, jobs_resurfaced, jobs_llm_requeued, jobs_dequeued, jobs_missing,
jobs_errored, started_at, finished_at, errors: list[str]`.

---

## 7. UI

- **Button** on the Digest page header (`render_digest_page`), e.g. **"Re-evaluate all"** next to the
  filter row. A short confirm dialog: *"Re-score every digest job against your current profile and
  threshold. Jobs that now qualify will reappear as unread and may be queued for AI. Continue?"*
- On success, show a one-line toast from the result (e.g. *"Re-scored 142 · 7 resurfaced · 5 queued for
  AI"*) and reload the feed so the badge/unseen counts refresh.
- The unseen **badge** (`unseen_count`) updates automatically because resurfaced rows are `digest_seen=0`.
- **No new profile field.** The button is the whole trigger surface (decision 1).

---

## 8. Scope risk (decision 2) — disabled/deleted saved searches

"All indexed digest jobs" re-scores rows whose `saved_search_id` points at a search the user later
**disabled or deleted**. Such a job can cross up and resurface even though that search is off.

Recommended handling (cheap, no scope change):
- The digest card already shows source + saved-search; **keep that** so a resurfaced job's origin is
  visible.
- Add a non-blocking note to the result toast when resurfaced jobs include ones from
  unknown/disabled searches (optional, low priority).
- Document the behaviour in the confirm dialog ("every digest job").

If Mic later wants the tighter set, it's a one-line `WHERE` change (join to enabled saved-search ids)
— tracked as a follow-up, not built now.

---

## 9. Edge cases

1. **Indexed but JSON gone** → `load_reviewed_job` raises → counted `jobs_missing`, skipped. No crash.
2. **`match_score` NULL** (never scored) → treated as below threshold; can cross up.
3. **Row `processing`** (worker mid-call) → not re-queued; its eventual `done`/`failed` write is
   independent of the re-score (different columns). Score upsert and worker status writes don't collide
   (separate columns; `_PIPELINE_LOCK` only serialises pipeline-style writers, the worker uses
   `_LLM_WORKER_LOCK` + per-row claim tokens).
4. **Large index** → O(N) reviewed_job file reads, synchronous. For the current single-user scale
   (hundreds of rows) this is acceptable; if it grows, move to a background thread with a status
   endpoint (future). Flagged, not built.
5. **Re-eval while a daily run is mid-flight** → blocked on `_PIPELINE_LOCK`; runs after. Correct.
6. **`digest_date` is preserved** on resurface (it's the first-seen date). Consequence: a resurfaced job
   does **not** appear under a `date = today` filter; it appears in the default (all-dates) feed and the
   unseen badge. Accepted (OQ-2-C).
7. **Partial write per job** — `save_job_analysis` then `upsert_job` are two steps; if the second fails
   the JSON analysis is newer than the index row. This is the **same contract the D3 pipeline already
   accepts** (it does save→upsert too); a later re-eval or rebuild reconciles. Per-job `try/except`
   counts it `jobs_errored`. Not wrapped in a cross-file transaction (JSON write isn't transactional with
   SQLite anyway).
8. **Mass-resurface of never-scored rows** — `old_score IS NULL` counts as below threshold, so a digest
   row that was indexed but never scored would cross up on its first real score. In practice digest rows
   are always scored at ingest (D3), so `match_score` is non-NULL; this path is a safety net, explicitly
   accepted, not a concern.

---

## 10. Open questions — RESOLVED (Mic, 2026-06-25)

- **OQ-2-A — "stayed above" jobs:** ✅ **Do not resurface.** Only crossed-up jobs resurface.
- **OQ-2-B — re-enrich `done` jobs:** ✅ **Yes, re-enrich — but only crossed-up `done` jobs** (the ones
  being resurfaced). Stayed-above `done` jobs keep their existing AI text. Re-queue is capped by
  `digest_max_llm_per_run`, so one click can't exceed that many Gemini calls regardless of how many
  jobs cross up.
- **OQ-2-C — bump `digest_date`?** ✅ **No — preserve first-seen date.**
- **OQ-2-D — LLM re-queue cap:** ✅ **Reuse `digest_max_llm_per_run`.** No new config field.

---

## 11. Test plan (`tests/test_digest_reeval.py`)

Unit (in-process, temp DB + temp state_root, no network):
1. **Crossed up** (old below, new ≥ threshold) → `digest_seen` flips to 0, `llm_status='pending'`,
   counted `resurfaced` + `llm_requeued`. Cover a crossed-up **`done`** row → it IS re-queued
   (status `done`→`pending`, `llm_attempts` reset to 0) per OQ-2-B.
2. **Stayed above** → score updated, `digest_seen` unchanged, no re-queue.
3. **Dropped below** with prior `pending` → `llm_status` cleared to NULL, counted `dequeued`.
4. **Threshold lowered** (profile threshold change alone) makes a job cross up → resurfaced.
5. **LLM re-queue cap** honoured (`digest_max_llm_per_run`), highest scorers queued first.
6. **`digest_llm_enabled=False`** → no re-queue even on crossing up.
7. **Missing reviewed_job JSON** → counted `jobs_missing`, loop continues, others still rescored.
8. **CAS guard on re-queue** — a crossed-up row that is `processing` (mid-flight worker) or already
   `pending`: `requeue_llm_if_eligible` returns 0, status untouched, counter not incremented. A crossed-up
   `done` row: returns 1, status → `pending` (OQ-2-B). (§14)
8b. **Dequeue CAS no-op** — a now-below-threshold row that is `processing` (simulating a mid-flight
    worker claim): `clear_llm_queue` returns 0, status stays `processing`.
9. **digest columns preserved** through the `upsert_job` (digest_date/saved_search_id unchanged).
10. **Disabled saved-search job** still included in scope (decision 2) and can resurface.

Route (`tests/test_digest_ui.py` or a new route test):
11. `POST /digest/reevaluate` returns `{"ok": true, ...}` with the expected counters; profile-load
    failure → 500 with a clear error.

Run with system `python3 -m pytest`; batch under the 45 s cap per the suite gotchas.

---

## 12. Files touched (planned)

| File | Change |
|------|--------|
| `src/job_hunt_index.py` | + `list_digest_jobs_for_reeval`, `resurface_digest_job`, `requeue_llm_if_eligible` (CAS), `clear_llm_queue` (CAS) |
| `src/job_hunt_scheduler.py` | + `ReevalResult`, `reevaluate_digest_jobs` (reuses `_PIPELINE_LOCK`) |
| `src/ui_handlers.py` | + `handle_digest_reevaluate` |
| `src/ui_routes.py` | wire `POST /digest/reevaluate` |
| `src/ui_render.py` | "Re-evaluate all" button + confirm + toast on the digest page |
| `tests/test_digest_reeval.py` | new — unit + route tests |
| `PROJECT_TODO.md` / `PROJECT_LOG.md` | mark OQ-2 done on completion (via update-project-docs) |

No schema migration (all needed columns exist from D2). No new profile field. No new dependency.

---

## 13. Out of scope

- Auto re-score on profile save (decision 1 = manual only).
- Re-fetching job descriptions or re-extracting skills.
- Re-enriching `done` jobs that **stay above** threshold (OQ-2-B re-enriches only crossed-up jobs; a
  blanket "refresh all AI" action remains a possible future feature).
- Tightening scope to enabled saved searches only (one-line future change, §8).
- Background/async re-eval with progress (future, only if index grows large — §9.4).

---

## 14. Concurrency model (Codex review fold-in, rev 2)

The re-eval runs under `_PIPELINE_LOCK`, which serialises it against the daily pipeline and manual
Run-now — **but not against the daemon LLM worker** (`drain_llm_batch`, guarded by the separate
`_LLM_WORKER_LOCK` + per-row claim tokens). So the worker can change a row's `llm_status` at any moment
during the re-eval. The TOCTOU fix is to never decide LLM transitions from the Python-side snapshot:

1. **Re-queue is compare-and-swap.** `requeue_llm_if_eligible` flips to `pending` **only**
   `WHERE llm_status IS NULL OR IN ('failed','skipped')` in a single statement. If the worker moved the
   row to `processing`/`done`/`pending` since the SELECT, the UPDATE matches nothing → `rowcount=0` → we
   do not count it and do not touch the in-flight job.
2. **Dequeue is compare-and-swap.** `clear_llm_queue` clears **only** `WHERE llm_status='pending'`. If the
   worker already claimed the row (`processing`), it's a no-op — the in-flight call is never stranded or
   double-run.
3. **Counters are driven by `rowcount`, not the snapshot.** `jobs_llm_requeued` / `jobs_dequeued`
   increment only when the guarded UPDATE actually changed a row, so the `digest_max_llm_per_run` cap
   can't be exhausted by stale reads, and the returned summary never over-reports.
4. **Score upsert vs worker writes don't collide** — re-eval writes `match_score`/`decision`;
   the worker writes `llm_*` columns. Different columns, last-writer-wins per column is correct here.
5. **Stable capped subset** — `ORDER BY match_score DESC, job_id ASC` means a capped re-queue picks the
   same highest-scoring rows on repeated runs (deterministic, testable).

**Acknowledged-but-kept design choices** (Codex raised, intentional):
- Threshold uses the *current* `profile.digest_threshold` for both sides of the cross-up test. This is
  the intended "what qualifies under my settings **now**" semantic; we don't store the threshold in force
  when each job was first seen. A job can therefore resurface because the threshold was lowered, not only
  because its score rose — that is the point of the feature.
- Scope includes jobs from disabled/deleted saved searches (§8) — surfaced origin on the card mitigates
  surprise; tightening is a one-line future change.

---

## 15. Codex implementation review (2026-06-25) — outcome

No critical findings. Confirmed safe against the concurrent LLM worker (all `llm_*` writes are CAS;
`upsert_job` never touches `llm_*`/`digest_*`; score writers all share `_PIPELINE_LOCK`). Items raised
and disposition:

- **`never_queued` can resurface a never-enriched job that was already ≥ threshold** (e.g. ingested with
  AI disabled, or below the old threshold). **Accepted — this is the intended backfill** that makes
  threshold-lowering / enabling-AI-later actually surface matches. One consequence: the *first*
  re-evaluate after enabling AI can resurface every qualifying NULL-status job at once (LLM re-queue is
  capped by `digest_max_llm_per_run`; the `digest_seen` resurface is not capped).
- **Re-queue `done → pending` leaves the prior AI summary in the analysis JSON until the worker re-runs.**
  Intended (OQ-2-B): the worker overwrites it via `save_analysis_llm_fields`. The deterministic score is
  already fresh; only the AI text is briefly stale.
- **`clear_llm_queue` scoping** — hardened to `digest_date IS NOT NULL` to match the other helpers.
- **Surfacing `except`** collects to `errors[]` + logs (not a silent `pass`); a failed transition shows in
  the result's `errors`.
- **`old_score` staleness** — only `_PIPELINE_LOCK`-holding writers (pipeline, this re-eval) change
  `match_score`; the worker does not. A user-driven manual evaluate racing a re-eval click is the only
  theoretical window; single-user, accepted.
- **NULL `match_score` ordering** — SQLite sorts NULL lowest, so `ORDER BY match_score DESC` puts
  unscored rows last (lowest re-queue priority); `job_id ASC` breaks ties deterministically.
