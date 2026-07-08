# Backlog-01 Design — Daily Job Digest (Auto-Evaluate + High-Match Feed)

<!-- STATUS -->
> **Implementation status:** ✅ **FULLY IMPLEMENTED 2026-06-24 — D1–D6 complete** (all design-council reviewed pre + post build; full suite 552 passed/1 skipped). D5 adds `DigestScheduler` (poll loop, once-per-day, `_PIPELINE_LOCK`); D6 adds `drain_llm_batch`/`LLMQueueWorker` (worker-lock paced Gemini, 429→backoff+requeue, Pacific-dated RPD cap, source-aware detail), `job_hunt_llm.RateLimited`, `JobAnalysis.llm_*` (5 fields), and auto-start of both daemons in `ui_routes.main` gated by profile toggles (+ Gemini key for the worker).
> **Live routes:** `GET/POST /saved-searches` (+`/delete`,`/toggle`,`/run-now`), `GET /digest`, `GET /digest/count`, `POST /digest/mark-seen`, `POST /digest/run-llm-batch`, `GET /digest/llm-queue`, `GET /scheduler/status`.
> **Deferred (low, single-process makes moot):** token-conditional LLM completion + claim heartbeats; `digest_job_id` lossy sanitisation (numeric ids safe + fail-loud upsert); pagination; CSRF (loopback). DST-precise scheduling deferred (local-time poll).
> **Divergences (D1):** SQLite `saved_searches` table (not per-file JSON); opaque `uuid4().hex` id (not a slug); "Save this search" button on Find Jobs deferred (create via My Profile). **Divergences (D2):** manual add/select keeps its own job_id rather than canonical `digest_job_id` (OQ-1, two rows tolerated); IntegrityError fallback dropped in favour of fail-loud logging (v6 dec. 4); WAL retained, local-disk only (v6 dec. 3).
> **D2 review follow-ups closed (2026-06-30):** saved-search `source_id` now validated against `get_enabled_sources()` (registered AND enabled) in the core `_validate_source_id`; `query_digest` score filter is `COALESCE(match_score,0) >= min_score` (NULL treated as 0 — `min_score=0` returns all incl. unscored). +3 tests.
> **Key functions (D2):** `job_hunt_index.py` — `_migrate_schema`, `open_db` (WAL+busy_timeout), `upsert_job` (ON CONFLICT, fail-loud), `is_already_indexed`, `set_digest_meta`, `set_llm_status`, `claim_batch`, `reset_stale_llm_processing`, `rpd_used_today`/`incr_rpd_counter`; `job_hunt_digest.py` — `DigestEntry`, `query_digest`, `mark_seen`, `mark_all_seen`, `unseen_count`, `digest_stats`; `ui_utils.digest_job_id`; `JobPosting.source_job_id`.
> **Routes live (D1+D2):** `GET/POST /saved-searches`, `POST /saved-searches/{id}/delete`, `POST /saved-searches/{id}/toggle`, `GET /digest/count`.
> **Routes (D3–D6 planned):** `GET /digest`, `POST /digest/mark-seen`, `POST /saved-searches/{id}/run-now`, `POST /digest/run-llm-batch`, `GET /digest/llm-queue`, `GET /scheduler/status`.
<!-- /STATUS -->

**Date:** 2026-06-24 (v5 — pre-implementation hardening: 16-item spec review applied)
**Owner:** Mic

**v7 design-council decisions (2026-06-24, D3/D4 pre-build review — Mic-approved + built):**
1. **D3 is LLM-free re: Gemini** — `run_digest_pipeline` only flips `llm_status='pending'`; it never
   calls the rate-limited analysis. Local Ollama skill extraction via `extract_skills_from_text`
   (Mic-chosen) IS allowed and bounded by `digest_max_per_source`. The 3-tuple `(req, pref, warning)`
   is unpacked correctly (Codex caught a 2-tuple bug in the spec pseudocode).
2. **LLM-queue cap is one counter spanning the whole run** (`newly_queued` in `run_digest_pipeline`),
   incremented only on a successful `pending` transition.
3. **Write order: index-write LAST** (`upsert_job` + `set_digest_meta` after the JSON saves) so a
   mid-job crash leaves the job un-indexed and simply re-processed next run (accepted non-atomic
   JSON+SQLite writes for a local single-user tool).
4. **`run_date` computed once** at run start (local date); each result + the skipped-log filename use it.
5. **`DigestRunResult` adds `jobs_already_seen`** (dedup hits — expected, not counted as skips).
6. **D4 `query_digest` extended with SQL-level filters** (`source_id`, `saved_search_id`, `seen`
   tri-state) + `DigestEntry.llm_status`; stable sort tie-breaker `match_score DESC, digest_date DESC, job_id DESC`.
7. **D4 XSS**: every external field (`title`/`company`/`location`) escaped at render; **the external
   apply URL is NOT rendered in the feed** — `[View]` links only to internal `/job/{id}` (kills the
   `javascript:`/`data:` vector). The job-detail page still shows the apply link with its http(s) guard.
8. **`mark_all_seen` scoped to current filters** (not the whole date) so a filtered "Mark all seen"
   never marks unrelated rows. `/digest/mark-seen` enforces exactly one mode (`{all:true}` xor
   `{job_ids:[…]}`), bounded ≤500, 400 on malformed.
9. **Manual add/select keeps its own job_id** (OQ-1) — not migrated to canonical `digest_job_id`.
   Pagination deferred (limit+count); CSRF unchanged (loopback, app-wide posture).

**v6 design-council decisions (2026-06-24, D1/D2 re-review — Mic-approved):**
1. **D1 storage = SQLite `saved_searches` table** (not per-file JSON). Reuses the existing
   `job_hunt_index.db`; gives atomic writes + idempotent toggle via SQL, avoids directory-scan in D5.
2. **`search_id` = opaque `uuid4().hex`** (table PK); the human label lives in the `name` column.
   Collision-proof — no silent overwrite, no 409 needed. `validate_search_id()` (strict allow-list)
   still gates every route as input hygiene.
3. **WAL retained, local-disk only.** `data/state` (hence the `.db`) must stay on local disk — never
   a synced/networked folder (iCloud/Dropbox) — or WAL `-wal`/`-shm` files risk corruption. Verified
   2026-06-24: DB resolves to `<launch-dir>/data/state/job_hunt_index.db`, no sync markers.
4. **IntegrityError fallback DROPPED from `upsert_job`.** Canonical `job_id` + the partial
   `UNIQUE(source, source_job_id)` index are the dedup guarantee; a `(source, source_job_id)`
   collision under a *different* `job_id` is now logged loudly as a bug (fail-loud) rather than
   silently patched (which masked the drift). Matches OQ-1 (two rows acceptable).
5. **`source_job_id` normalization mandated at the adapter boundary:** `str(value).strip()`, never
   parsed as a number (leading-zero/whitespace/int-vs-str would split or merge identities). `source`
   lower-cased on write and in every query.
6. New required tests: per-route traversal rejection; `source_job_id` int/str/leading-zero/whitespace
   normalization; **cross-source isolation** (reed/123 + adzuna/123 → 2 distinct rows).

**v5.1 consistency cleanup (2026-06-24, spec only):** removed the duplicated "Review findings
addressed (v2)" heading and rewrote F1 as superseded; fixed the §4.1 result-dict comment and the
§7 upsert payload (`apply_url`, not `source_ref`); corrected §11 Adzuna wording and pinned the D6
v1 dispatch level; rewrote the §13 `source_job_id` resolution; added the §3.3 `IntegrityError`
fallback (preserving digest/LLM columns); fixed the §3.2 migration wording; defined `set_llm_status()`
(§14.3b); made the SQLite `llm_rpd` table the final RPD decision (§14.5); pinned `DigestEntry.url` to
`jobs.apply_url` (§5.2); tightened the `claim_batch` return query (§14.3a). All remaining `source_ref`
references are explicitly legacy URL/display metadata only.

**v5 changes (16-item review, 2026-06-24) — spec only, no code:**
1. Removed the stale v3 dedup text; **final rule: dedup = `lower(source) + source_job_id`**;
   `source_ref`/`apply_url` is URL/display metadata only, never dedup.
2. Schema wording corrected to "**ten new columns**".
3. Added partial **`UNIQUE(source, source_job_id)`** index (defense-in-depth) + the
   conflict-target decision (canonical `job_id` + `IntegrityError` fallback). §3.1a.
4. Added digest / LLM-queue / saved-search **perf indexes**. §3.1a.
5. **Token-based `claim_batch`** (`llm_claim_token`) returning only rows it actually claimed.
6. **`reset_stale_llm_processing`** + `llm_claimed_at` for crash recovery.
7. `digest_job_id(source, source_job_id)` — **no URL-hash fallback**, raises on blank.
8. Concrete **skipped-job JSONL log** (`data/state/logs/digest_skipped_jobs_YYYY-MM-DD.jsonl`). §7b.
9. **`run-now` runs exactly one saved search.** §8.
10. D3 result field renamed **`jobs_llm_queued`** (D3 queues, never calls LLM) + `jobs_skipped`.
11. **New-only digest** behaviour stated explicitly. §7a.
12. New apply-URL column named **`apply_url`** (not `source_ref`); legacy `JobPosting.source_ref`
    kept as-is with comments (rename scoped to new code only).
13. **`parse_bool`** helper (fixes `bool("false") == True`).
14. **Exact range validation** for all digest profile fields; `digest_max_llm_per_run = 0` allowed.
15. **LLM result stored in `JobAnalysis`** (5 new fields); jobs table holds queue metadata only. §14.5a.
16. **D2 implementation order** revised: model layer → serialisation → adapters → migration →
    indexes → upsert → rebuild → query layer → tests.

**Design-council findings applied (v4, 2026-06-24, Codex read-only review):**
- C1 (High → V1 revised): dedup key changed from `source_ref` (URL-first, unstable — Reed has
  `original_url`/`apply_url` alternates that shift between fetches) to **`source_job_id`** (stable
  provider id). Requires a new `source_job_id` field on `JobPosting` so `rebuild_index` can read it
  (Mic-approved 2026-06-24). URL is metadata only (`JobPosting.url`).
- C2 (High): **blank-key guard** — a result with neither `source_job_id` nor a usable id collides as
  `(source, NULL)`. The pipeline skips/quarantines such results; never indexed.
- C3 (High): **empty `description_raw` is rejected** by `JobPosting.__post_init__` / `reviewed_job_from_dict`
  (`job_hunt_models.py:87–97`, `job_hunt_reviewed_input.py:65–73`). The adapter/pipeline skips
  description-less results rather than crashing ingestion.
- C4 (High): **LLM queue concurrency** — threaded `http.server` + worker both `open_db()` per call →
  `database is locked` and manual-drain + auto-worker can double-process a row. Fixed with an atomic
  claim (`BEGIN IMMEDIATE` + conditional UPDATE to a new `processing` status), `PRAGMA busy_timeout`,
  and WAL mode (§14.3).
- C5 (Med): `""` salary strings must be coerced to `None` in the adapter (else `TypeError` on the
  `salary_min <= salary_max` compare, `job_hunt_models.py:113–118`).
- C6 (Med): `upsert_job`'s `ON CONFLICT DO UPDATE` list must **exclude the `llm_*` columns too**
  (not only digest columns) or worker state resets on any re-index.
- C7 (Med): `RateLimited` is raised **only when the whole model-fallback chain failed with 429**;
  status codes are threaded through `job_hunt_llm.py` so 404/503 are not misread as rate-limit (§14.4).
- C8 (Med): the RPD counter's JSON read-modify-write needs a lock (or store it as an atomic SQLite
  row) so concurrent increments don't lose counts (§14.5).
- Over-engineering: Codex flagged none — D1–D6 phasing kept as-is.

**User decisions:**
- Score threshold: configurable per user
- Search source: named saved search profiles
- Seen/dismissed: keep all, mark New/Seen; badge shows unseen count
- Evaluation mode: deterministic first; LLM only for jobs ≥ threshold
- Sources: Reed **and Adzuna** (both live as of P5-1, 2026-06-24)
- LLM enrichment must respect Gemini free-tier RPM **and** daily (RPD) limits; calls are
  spread across time in paced batches, never fired all at once (see §14)

**Verified-against-code findings (v3, 2026-06-24):**
- V1 (High) — **SUPERSEDED BY v4/C1.** v3 originally proposed dedup on `(source, source_ref)`
  with `source_ref` = advert-URL-or-id, and dropped a dedicated `source_job_id` column. That is no
  longer the design. **Final rule (v4): dedup is always `lower(source) + source_job_id`.** v4 adds
  `JobPosting.source_job_id` and persists it through reviewed-job JSON and index rebuild, so the
  stable id *is* available at rebuild (the v3 blocker). `source_ref` is apply/advert URL metadata
  only and is **never** used for dedup. The `source_job_id` column is **kept, not dropped.** See C1.
- V2 (Medium): source-id casing — `upsert_job` stores `source = reviewed_job.source_type`
  (lowercase `"reed"`/`"adzuna"`) but `ENABLED_SOURCES = ["Reed","Adzuna"]`. `SavedSearch.source_id`
  and every dedup/lookup query must `.lower()`-normalise or they silently miss.
- V3 (Medium): `data/state` has a fixed 5-dir whitelist in `_state_file_path`
  (`job_hunt_storage.py:263`); `saved_searches/` is not one. `job_hunt_saved_searches.py` owns its
  own subdir, must `mkdir(parents=True, exist_ok=True)`, and must slug-sanitise `search_id`
  (reject `/`, `..`, etc.) to prevent path traversal.
- V4 (Medium): Adzuna has **no detail-fetch API** by design (P5-1). The v2 pipeline hardcoded
  `fetch_reed_job_detail` before LLM. **Fixed:** detail-fetch step is source-aware — Reed fetches
  full description, Adzuna uses the search-result description as-is (see §7 step 4b, §11).
- V5 (confirmed OK): `search_handler` returns UI dicts (`source_registry.py:63`), `source_job_id`
  present in both adapters, `evaluate_reviewed_job` / `reviewed_job_from_dict` /
  `explain_job_match_with_llm` signatures all match. No change needed.

**Review findings addressed (v2):**
- F1 (superseded by v5): earlier drafts used `source_ref`. Final design uses `source_job_id` for dedup and `apply_url` for display/apply metadata. `source_ref` is legacy URL metadata only and is never used for dedup.
- F2 (High): `INSERT OR REPLACE` replaced with `ON CONFLICT DO UPDATE`; digest columns preserved across updates; `set_digest_meta()` added as separate write
- F3 (High): All profile loader/serializer changes (`OPTIONAL_PROFILE_FIELDS`, `from_dict`, `to_dict`, UI, tests) now explicit in the design
- F4 (Medium): Source interface contract clarified — `search_handler` returns UI result dicts; `reviewed_job_payload_from_ui_result()` adapter introduced; `NormalizedJob` never used in digest pipeline
- F5 (Medium): `DELETE /saved-searches/{id}` replaced with `POST /saved-searches/{id}/delete` (no `do_DELETE` needed)
- F6 (Medium): `run_now()` is synchronous in D3; non-blocking run state deferred to D5

---

## 1. Problem and Goal

The user opens the app and manually searches for jobs every session, seeing the same top results repeatedly. The goal:

> Each morning, automatically fetch new jobs from saved searches, score them against the user's profile, and surface only the high-match ones — so the user can open the app and focus on what's worth pursuing.

---

## 2. Feature Overview

```
[Saved Searches] ──daily at 07:00──▶ [Digest Pipeline]
                                             │
                              ┌──────────────┴──────────────┐
                              │  1. Fetch (source.search_handler)        │
                              │  2. Guard+Dedup (lower(source)+source_job_id) │
                              │  3. Convert (UI dict → reviewed_job)     │
                              │  4. Deterministic eval (all new jobs)    │
                              │  5. Queue high-match for LLM (no call)   │
                              └──────────────┬──────────────┘
                                             │
                              ┌──────────────┴──────────────┐
                              │  SQLite index (source_job_id │
                              │  dedup, digest + LLM-queue cols) │
                              └──────────────┬──────────────┘
                                             │
                                  GET /digest   GET /digest/count
```

---

## 3. SQLite Schema Changes (job_hunt_index.py)

**Ten new columns** on the `jobs` table (was wrongly called "four" in v2). These must be added
before D2 proceeds, via the idempotent migration in §3.2.

### 3.1 New columns

```sql
-- Dedup key: the stable provider job id (Reed jobId / Adzuna id), normalised to str.
-- Written identically by the pipeline and rebuild_index (the latter reads the new
-- JobPosting.source_job_id field — see §3.7). See C1.
ALTER TABLE jobs ADD COLUMN source_job_id TEXT;

-- apply_url: apply/advert URL — metadata/display ONLY, NEVER a dedup key.
-- (Legacy note: an earlier draft called this "source_ref". The NEW column is named
-- apply_url to avoid confusion with JobPosting.source_ref. Item 12.)
ALTER TABLE jobs ADD COLUMN apply_url TEXT;

-- Digest tracking
ALTER TABLE jobs ADD COLUMN digest_date TEXT;          -- ISO date; NULL = not from digest
ALTER TABLE jobs ADD COLUMN digest_seen INTEGER DEFAULT 0;  -- 0=new, 1=seen
ALTER TABLE jobs ADD COLUMN saved_search_id TEXT;      -- which SavedSearch found it

-- LLM enrichment queue (§14). Decouples scoring from rate-limited LLM calls.
ALTER TABLE jobs ADD COLUMN llm_status TEXT;           -- NULL | pending | processing | done | failed | skipped
ALTER TABLE jobs ADD COLUMN llm_attempts INTEGER DEFAULT 0;
ALTER TABLE jobs ADD COLUMN llm_next_attempt_at TEXT;  -- ISO datetime; backoff gate, NULL = ready
ALTER TABLE jobs ADD COLUMN llm_claimed_at TEXT;       -- ISO datetime a worker claimed the row (C4/item 5,6)
ALTER TABLE jobs ADD COLUMN llm_claim_token TEXT;      -- per-claim UUID; only the claimer processes the row
```

> **Dedup key (C1 fix):** dedup is on `lower(source) + source_job_id` — the stable provider id,
> never the URL (URLs shift between fetches). `source` is lower-cased on write and in every
> query (V2). Rows whose `source_job_id` is blank are **never indexed** (C2 guard, §7 step 2;
> skipped-job log §7a). `open_db` must also set `PRAGMA journal_mode=WAL` and
> `PRAGMA busy_timeout=5000` (C4).
>
> **WAL local-disk constraint (v6 decision 3).** WAL adds `-wal`/`-shm` sidecar files and relies on
> shared-memory/locking that synced or networked filesystems don't honour. Keep `data/state` (and
> the `.db`) on **local disk** — never iCloud/Dropbox/a network share — or risk lock failures and
> corruption. Only export/back up the DB when the app is closed (or via SQLite's backup API).

### 3.1a Indexes (item 3, item 4)

```sql
-- Defense-in-depth dedup: make duplicate (source, source_job_id) impossible at the DB level,
-- not just a lookup we promise to run. Partial so legacy/manual rows with no id don't collide.
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_source_source_job_id
    ON jobs(source, source_job_id)
    WHERE source_job_id IS NOT NULL AND source_job_id != '';

-- Digest feed query (date + unseen, highest score first)
CREATE INDEX IF NOT EXISTS idx_jobs_digest_unseen
    ON jobs(digest_date, digest_seen, match_score DESC);

-- LLM queue drain (pending + ready-by-backoff, highest score first)
CREATE INDEX IF NOT EXISTS idx_jobs_llm_queue
    ON jobs(llm_status, llm_next_attempt_at, match_score DESC);

-- Saved-search filter on the digest page
CREATE INDEX IF NOT EXISTS idx_jobs_saved_search
    ON jobs(saved_search_id);
```

> **CRITICAL — conflict-target mismatch (gap found in v4 review).** `upsert_job` uses
> `ON CONFLICT(job_id) DO UPDATE`, but the new unique index is on `(source, source_job_id)` — a
> *different* target. If the same posting reaches the index under two different `job_id`s (e.g. a
> manually-added job, then the digest finds the same posting), the INSERT raises `IntegrityError`
> that `ON CONFLICT(job_id)` will NOT absorb, crashing the run.
> **Decision: make `job_id` canonical.** Both the manual and digest paths derive `job_id`
> deterministically as `digest_job_id(source, source_job_id)` (§4.2), so the same posting always
> maps to the same `job_id` and `ON CONFLICT(job_id)` fully covers it. The partial
> `UNIQUE(source, source_job_id)` index is kept purely as an **invariant guard** — if it ever fires,
> the canonical-id logic has drifted. **v6 decision 4: no IntegrityError fallback** — fail loud and
> log, do not silently patch (see §3.3). (OQ-1 — manual NULL-id row + later digest hit — doesn't trip
> the partial index, since NULL ids are excluded.)

### 3.2 Migration

`open_db()` already runs `CREATE TABLE IF NOT EXISTS`. Add a `_migrate_schema(conn)` call inside `open_db()` that checks `PRAGMA table_info(jobs)` for each new column and runs `ALTER TABLE ... ADD COLUMN` only if missing:

```python
_MIGRATION_COLUMNS = [
    ("source_job_id",       "TEXT"),
    ("apply_url",           "TEXT"),
    ("digest_date",         "TEXT"),
    ("digest_seen",         "INTEGER DEFAULT 0"),
    ("saved_search_id",     "TEXT"),
    ("llm_status",          "TEXT"),
    ("llm_attempts",        "INTEGER DEFAULT 0"),
    ("llm_next_attempt_at", "TEXT"),
    ("llm_claimed_at",      "TEXT"),
    ("llm_claim_token",     "TEXT"),
]
# After ADD COLUMNs, run the CREATE [UNIQUE] INDEX statements from §3.1a (all IF NOT EXISTS)
# and the CREATE TABLE IF NOT EXISTS llm_rpd statement from §14.5.

def _migrate_schema(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    for col_name, col_type in _MIGRATION_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}")
    conn.commit()
```

**Existing rows** get `NULL`/defaults for the new columns — safe and backward-compatible.

### 3.3 Fix `upsert_job()` — replace INSERT OR REPLACE

The current `INSERT OR REPLACE` deletes the old row and inserts a fresh one, which would reset `digest_date` and `digest_seen` to NULL every time a job is updated from a non-digest handler (e.g. when the user records an outcome). This silently drops digest metadata.

**Fix:** use `INSERT ... ON CONFLICT(job_id) DO UPDATE SET` which updates only the columns listed, leaving all others untouched:

```python
def upsert_job(db_path: Path, row: dict[str, Any]) -> None:
    """Upsert evaluation/status columns. Never overwrites digest columns."""
    tailoring_int = (1 if row["tailoring_ready"] else 0) if row.get("tailoring_ready") is not None else None

    conn = open_db(db_path)
    try:
        conn.execute(
            """
            INSERT INTO jobs
                (job_id, job_title, company, location, source, source_job_id, apply_url,
                 match_score, decision, user_decision, ats_score,
                 tailoring_ready, status, updated_at, salary_min, salary_max)
            VALUES
                (:job_id, :job_title, :company, :location, :source, :source_job_id, :apply_url,
                 :match_score, :decision, :user_decision, :ats_score,
                 :tailoring_ready, :status, :updated_at, :salary_min, :salary_max)
            ON CONFLICT(job_id) DO UPDATE SET
                job_title      = excluded.job_title,
                company        = excluded.company,
                location       = excluded.location,
                source         = excluded.source,
                source_job_id  = excluded.source_job_id,
                apply_url      = excluded.apply_url,
                match_score    = excluded.match_score,
                decision       = excluded.decision,
                user_decision  = excluded.user_decision,
                ats_score      = excluded.ats_score,
                tailoring_ready = excluded.tailoring_ready,
                status         = excluded.status,
                updated_at     = excluded.updated_at,
                salary_min     = excluded.salary_min,
                salary_max     = excluded.salary_max
                -- NOT listed here, so preserved unchanged on conflict (C6):
                --   digest_date, digest_seen, saved_search_id,
                --   llm_status, llm_attempts, llm_next_attempt_at,
                --   llm_claimed_at, llm_claim_token
            """,
            {
                "job_id":          row.get("job_id"),
                "job_title":       row.get("job_title"),
                "company":         row.get("company"),
                "location":        row.get("location"),
                "source":          (row.get("source") or "").lower(),   # V2
                "source_job_id":   row.get("source_job_id"),   # NEW — dedup key (C1)
                "apply_url":       row.get("apply_url"),        # apply/advert URL metadata only
                "match_score":     row.get("match_score"),
                "decision":        row.get("decision"),
                "user_decision":   row.get("user_decision"),
                "ats_score":       row.get("ats_score"),
                "tailoring_ready": tailoring_int,
                "status":          row.get("status") or "not_applied",
                "updated_at":      row.get("updated_at"),
                "salary_min":      row.get("salary_min"),
                "salary_max":      row.get("salary_max"),
            },
        )
        conn.commit()
    finally:
        conn.close()
```

**No IntegrityError fallback (v6 decision 4 — supersedes the earlier rev).** Because `job_id` is
canonical (`digest_job_id(source, source_job_id)`, the SAME id in the manual and digest paths), a
posting always maps to one `job_id`, so `ON CONFLICT(job_id)` fully covers the normal case. The
partial `UNIQUE(source, source_job_id)` index stays purely as an **invariant guard.** If it ever
fires — i.e. the same `(source, source_job_id)` arrives under a *different* `job_id` — that is a
canonical-id bug (algorithm drift / a caller that didn't use `digest_job_id`), not a routine
condition. Codex's review showed a silent `UPDATE … WHERE source=? AND source_job_id=?` fallback
would *mask* that bug and persist a non-canonical `job_id`, and a broad `except IntegrityError` could
also swallow unrelated constraints. So instead, **fail loud**: let the `IntegrityError` surface,
log it at ERROR with the conflicting ids, and treat it as a defect to fix — do not patch it at write
time. (OQ-1 — a manual NULL-id row plus a later digest hit — does *not* trip this, since NULL ids are
excluded by the partial index.)

### 3.4 New function `set_digest_meta()`

Called by the digest pipeline after `upsert_job()` to write the digest-specific columns:

```python
def set_digest_meta(
    db_path: Path,
    job_id: str,
    *,
    digest_date: str,        # ISO date string, e.g. "2026-06-18"
    seen: bool = False,
    saved_search_id: str | None = None,
) -> None:
    """Write digest tracking columns for a job. Does not touch eval/status columns."""
    conn = open_db(db_path)
    try:
        conn.execute(
            """
            UPDATE jobs
               SET digest_date      = :digest_date,
                   digest_seen      = :seen,
                   saved_search_id  = :saved_search_id
             WHERE job_id = :job_id
            """,
            {
                "job_id":          job_id,
                "digest_date":     digest_date,
                "seen":            1 if seen else 0,
                "saved_search_id": saved_search_id,
            },
        )
        conn.commit()
    finally:
        conn.close()
```

### 3.5 New function `_is_already_indexed()`

Used by the pipeline to skip already-seen jobs (dedup):

```python
def is_already_indexed(
    db_path: Path,
    source_id: str,
    source_job_id: str,
) -> bool:
    """True if a job with this source + source_job_id already exists in the index.

    Dedup key is the STABLE provider id (C1), not the URL. `source_id` is lower-cased
    to match stored rows (V2). Callers must skip blank source_job_id (C2) before calling.
    """
    if not source_job_id.strip():
        return False  # caller should have quarantined this already
    conn = open_db(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE source = ? AND source_job_id = ? LIMIT 1",
            (source_id.lower(), source_job_id.strip()),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def source_job_id_from_ui_result(result: dict[str, Any]) -> str:
    """Stable dedup id from a source UI result dict. Empty string = not dedupable (C2)."""
    return str(result.get("source_job_id") or "").strip()


def apply_url_from_ui_result(result: dict[str, Any]) -> str:
    """Apply/advert link — metadata only, never a dedup key."""
    return str(result.get("url") or "").strip()
```

### 3.6 Update `rebuild_index()` to persist `source_job_id` + `apply_url`

`rebuild_index()` reads the new `reviewed_job.source_job_id` (dedup key) and the existing
`reviewed_job.url` (with legacy `source_ref` as a display-only fallback) for the apply link, and
passes both to `upsert_job()` — `source_job_id` as the dedup key, the URL as `apply_url`:

```python
# Inside rebuild_index(), after loading reviewed_job:
source_job_id = reviewed_job.source_job_id          # NEW field (§3.7) — the dedup key
apply_url     = reviewed_job.url or reviewed_job.source_ref  # apply-link metadata (legacy field ok)
upsert_job(db_path, {
    ...existing fields...,
    "source":        (reviewed_job.source_type or "").lower(),  # V2
    "source_job_id": source_job_id,   # ADD — dedup key (C1)
    "apply_url":     apply_url,        # ADD — metadata only
})
```

### 3.7 NEW — add `source_job_id` to `JobPosting` (C1, Mic-approved)

`JobPosting` (`job_hunt_models.py:65`) currently has no stable provider id — only `source_ref`
(historically URL-or-id) and `url`. Add an explicit field so the dedup key survives a rebuild:

```python
# In JobPosting dataclass — optional, defaults None so existing records load unchanged
source_job_id: str | None = None
```

Blast radius (all must change together — verify before building D2):
- `job_hunt_models.py` — add the field (no `__post_init__` rule; it's optional).
- `job_hunt_reviewed_input.py` — add `"source_job_id"` to `OPTIONAL_REVIEWED_JOB_FIELDS`;
  map it in `reviewed_job_from_dict` (optional string) and `reviewed_job_to_dict`.
- `reed_source.py` / `adzuna_source.py` — set `source_job_id` in the values they build for the
  manual select flow (they already compute `source_job_id` locally — just stop folding it into
  `source_ref`; keep `source_ref`/`url` = advert URL).
  **Normalization (v6 decision 5, Codex High):** store `source_job_id` as `str(value).strip()` —
  never parse the provider id as a number. The column is TEXT, so `12345678` (int) and `"12345678"`
  collide correctly, but `" 123 "` would NOT collide and a leading-zero id parsed as int (`"00123"`
  → `123`) irreversibly changes identity. Reject blank-after-strip (C2). Also lower-case `source`
  before storing so the dedup key matches the `lower(source)` rule.
- `tests/` — round-trip serialisation test + any fixture asserting the JobPosting field set.
- **Back-compat:** existing reviewed_job JSON files have no `source_job_id` → loads as `None`.
  Such rows can't be deduped by id; `rebuild_index` falls back to leaving `source_job_id` NULL,
  and they simply won't collide-match (acceptable for pre-digest historical jobs).

---

## 4. Source Interface Contract (clarified)

`search_handler` in `JobSource` already returns **UI result dicts** — not `NormalizedJob`. The current Reed implementation (`search_reed_jobs_for_ui`) calls `fetch_reed_jobs → reed_job_to_ui_result` and returns UI dicts. This is the correct contract; the pipeline uses it as-is.

### 4.1 What a UI result dict looks like

```python
{
    "source": "reed",
    "source_job_id": "12345678",    # stable provider id; dedup key with lower(source)
    "title": "Business Analyst",
    "company": "Accenture",
    "location": "London",
    "salary_min_gbp": "50000",
    "salary_max_gbp": "65000",
    "url": "https://www.reed.co.uk/jobs/...",
    "description_raw": "...",
    "work_mode": "hybrid",
    "employment_type": "permanent",
    "source_snapshot_json": "{...}",
    # ... other normalised fields
}
```

### 4.2 New adapter: `reviewed_job_payload_from_ui_result()`

The current evaluate flow goes: HTML form → `reviewed_job_payload_from_form(form)` → `JobPosting`. The digest pipeline has no HTML form — it has a UI result dict. Add a thin adapter:

**V6 fix (v3):** the v2 adapter mapped the wrong key names. The UI result dict (see
`reed_job_to_ui_result`, `reed_source.py:287`) uses `source` / `title` / `source_job_id`,
but `reviewed_job_from_dict` consumes the `JobPosting` shape — `source_type` / `job_title` /
`source_ref` — and also needs a `job_id` and extracted skills, neither of which the v2 adapter
produced. Corrected adapter:

```python
# In ui_utils.py (pure mapping) — skill extraction stays in the pipeline (not pure)
def reviewed_job_payload_from_ui_result(result: dict[str, Any]) -> dict[str, Any]:
    """Convert a source UI result dict to a reviewed_job payload dict (JobPosting shape).
    Mirrors what reviewed_job_payload_from_form produces, but from a search-result dict."""
    def _clean(v: str) -> str:                              # "Unknown" → "" for enum-ish fields
        return "" if str(v).strip().lower() in {"unknown", "none", "null"} else str(v).strip()
    def _salary(v: Any) -> int | None:                      # C5: "" / non-numeric → None
        s = str(v).strip()
        return int(s) if s.isdigit() else None
    sjid = source_job_id_from_ui_result(result)          # caller guarantees non-blank (C2)
    return {
        "job_id":          digest_job_id(result.get("source", ""), sjid),  # canonical id
        "job_title":       result.get("title") or "Unknown",
        "company":         result.get("company") or "Unknown",
        "description_raw": result.get("description_raw", ""),  # C3: caller skips if blank
        "source_type":     (result.get("source") or "").lower(),
        "source_job_id":   sjid,                                   # dedup key (C1)
        "source_ref":      apply_url_from_ui_result(result),      # legacy field = apply URL only
        "url":             apply_url_from_ui_result(result),
        "location":        result.get("location", ""),
        "work_mode":       _clean(result.get("work_mode", "")),
        "employment_type": _clean(result.get("employment_type", "")),
        "salary_min_gbp":  _salary(result.get("salary_min_gbp")),  # C5
        "salary_max_gbp":  _salary(result.get("salary_max_gbp")),  # C5
        # required_skills / preferred_skills added by the pipeline via
        # extract_skills_from_text(description_raw) — see §7 step 4.
    }


def digest_job_id(source: str, source_job_id: str) -> str:
    """Canonical, deterministic, filesystem-safe job_id from source + source_job_id.
    NO url-hash fallback (item 7): a blank source or id is a programming error here —
    the pipeline must skip/log such results (C2) BEFORE calling this.
    Using the SAME canonical id in the manual and digest paths is what lets
    ON CONFLICT(job_id) cover the (source, source_job_id) unique index (§3.1a)."""
    source = (source or "").strip().lower()
    source_job_id = (source_job_id or "").strip()
    if not source or not source_job_id:
        raise ValueError("digest_job_id requires non-blank source and source_job_id")
    return re.sub(r"[^a-z0-9_-]", "-", f"{source}-{source_job_id}")
```

> Manual add-job flow must also adopt `digest_job_id(source, source_job_id)` so a posting added
> both ways resolves to one row (the §3.1a conflict-target decision). See OQ-1 if that path
> cannot supply a `source_job_id`.

**Skill extraction:** in the manual flow Reed's `select_handler` runs
`extract_skills_from_text(full_description)`. The digest pipeline has no detail fetch at scoring
time, so step 4 must run `extract_skills_from_text(payload["description_raw"])` on the
search-result description before `reviewed_job_from_dict`. Lower recall than the full description,
but the LLM worker (§14) re-fetches the full description for high-match jobs later.

This means the pipeline does **not** go through Reed's `select_handler` (which fetches full job
detail from the API and validates a nonce). The source-aware full-detail fetch happens in §14,
just before each LLM call.

---

## 5. New Data Models

### 5.1 `SavedSearch`

```python
@dataclass(frozen=True, slots=True)
class SavedSearch:
    search_id: str          # opaque uuid4().hex (v6 decision 2) — NOT a slug
    name: str               # user label, e.g. "BA roles, London"
    source_id: str          # "reed" | "adzuna" | ...  (lower-cased, registered source)
    params: dict[str, str]  # normalised search params (same shape as normalize_search_params output)
    enabled: bool           # False = skip in daily run
    created_at: str         # ISO datetime (UTC)
    last_run_at: str | None
    last_run_count: int     # new jobs found on last run
```

**Storage (v6 decision 1): a `saved_searches` table in the existing `job_hunt_index.db`.**
**Module:** `src/job_hunt_saved_searches.py`

```sql
CREATE TABLE IF NOT EXISTS saved_searches (
    search_id      TEXT PRIMARY KEY,   -- uuid4().hex
    name           TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    params         TEXT NOT NULL,      -- JSON-encoded dict[str,str]
    enabled        INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    last_run_at    TEXT,
    last_run_count INTEGER NOT NULL DEFAULT 0
);
```

> **Why SQLite, not per-file JSON (v6).** Atomic writes and an idempotent toggle
> (`UPDATE … SET enabled = NOT enabled`) come free from SQLite — no temp-file/`os.replace`
> dance, no read-modify-write race, no directory-scan when D5 asks "which searches are due to run",
> and no corrupt-file-crashes-the-whole-list failure mode. It reuses the DB D2 already migrates.
>
> **No filesystem path is built from `search_id`,** so the per-file path-traversal vector is gone.
> `search_id` is still validated by `validate_search_id()` (strict `^[A-Za-z0-9_-]{1,64}$`) on
> **every** route (`/delete`, `/toggle`, load) as input hygiene — an unknown but well-formed id
> returns 404; a malformed id returns 400. `search_id` is generated as `uuid4().hex` at create time,
> so two searches with the same `name` both save cleanly (no collision, no overwrite).
>
> All storage functions take `state_root` as a **keyword-only** argument (Codex: it was missing on
> load/list/save/delete in the v5 signatures).

---

### 5.2 `DigestEntry` (read model)

```python
@dataclass(frozen=True, slots=True)
class DigestEntry:
    job_id: str
    title: str
    company: str
    match_score: int
    decision: str
    source_id: str
    saved_search_id: str | None
    digest_date: str        # ISO date
    seen: bool
    salary_display: str | None
    location: str | None
    url: str | None
```

> **`DigestEntry.url` is read from `jobs.apply_url`.** Do **not** read `DigestEntry.url` from
> `source_ref`. `apply_url` is the apply/advert/display URL stored on the jobs row; `source_ref`
> is legacy metadata only.

---

### 5.3 `CandidateProfile` — new digest preference fields

The profile loader rejects unknown fields (`ProfileValidationError` on any key not in `OPTIONAL_PROFILE_FIELDS`). All four steps below are required — omitting any one will break loading or saving.

**Step 1 — Add fields to `CandidateProfile` dataclass (`job_hunt_models.py`):**

```python
# All have defaults so existing profiles load without errors
digest_enabled: bool = True
digest_threshold: int = 70
digest_run_time: str = "07:00"
digest_max_per_source: int = 50
digest_llm_enabled: bool = True
digest_max_llm_per_run: int = 10        # max NEW jobs queued for LLM per digest run

# LLM rate-limit controls (§14). Defaults sized to Gemini free tier, 5-RPM analysis chain.
digest_llm_rpm: int = 4                  # calls/min ceiling; <5 for the 5-RPM primary models
digest_llm_rpd: int = 200               # calls/day ceiling; <250 free-tier RPD cap
digest_llm_batch_size: int = 4          # jobs drained per worker cycle
digest_llm_batch_interval_min: int = 15 # minutes between worker cycles
```

> **Per-model note (user-confirmed 2026-06-24):** `gemini-3-flash-preview` and
> `gemini-2.5-flash` = **5 RPM**; `gemini-3.1-flash-lite` = **15 RPM**; free-tier RPD ≈ 250.
> The analysis chain leads with the 5-RPM models, so defaults are sized to those.
> A flash-lite-only setup can safely raise `digest_llm_rpm` to ~12.
> All six existing + four new fields must be range-validated (see Step 5).

**Step 2 — Add to `OPTIONAL_PROFILE_FIELDS` (`job_hunt_profile.py`):**

```python
OPTIONAL_PROFILE_FIELDS = {
    ...,  # existing fields
    "digest_enabled",
    "digest_threshold",
    "digest_run_time",
    "digest_max_per_source",
    "digest_llm_enabled",
    "digest_max_llm_per_run",
    "digest_llm_rpm",
    "digest_llm_rpd",
    "digest_llm_batch_size",
    "digest_llm_batch_interval_min",
}
```

**Step 3 — Update `candidate_profile_from_dict()` (`job_hunt_profile.py`):**

> **Item 13 — never use `bool(payload.get(...))`.** `bool("false") == True`, so a stringy
> `"false"` from a form/JSON would enable the feature. Use a `parse_bool` helper:

```python
_TRUE  = {"true", "1", "yes", "on", "t", "y"}
_FALSE = {"false", "0", "no", "off", "f", "n"}

def parse_bool(value: Any, field: str, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in _TRUE:  return True
    if s in _FALSE: return False
    raise ProfileValidationError(f"{field} must be a boolean (got {value!r})")

def _int_in(value, field, *, default, lo, hi) -> int:
    if value is None or value == "":
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ProfileValidationError(f"{field} must be an integer (got {value!r})")
    if not (lo <= n <= hi):
        raise ProfileValidationError(f"{field} must be {lo}–{hi} (got {n})")
    return n

def _parse_hhmm(value, field, *, default) -> str:
    s = str(value or default).strip()
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s):   # 24-hour HH:MM
        raise ProfileValidationError(f"{field} must be HH:MM 24-hour (got {value!r})")
    return s
```

```python
# Item 14 — exact ranges (max_llm_per_run allows 0 = queue nothing, digest still runs)
digest_enabled              = parse_bool(payload.get("digest_enabled"), "digest_enabled", default=True)
digest_threshold            = _int_in(payload.get("digest_threshold"), "digest_threshold", default=70,  lo=0, hi=100)
digest_run_time             = _parse_hhmm(payload.get("digest_run_time"), "digest_run_time", default="07:00")
digest_max_per_source       = _int_in(payload.get("digest_max_per_source"), "digest_max_per_source", default=50, lo=1, hi=200)
digest_llm_enabled          = parse_bool(payload.get("digest_llm_enabled"), "digest_llm_enabled", default=True)
digest_max_llm_per_run      = _int_in(payload.get("digest_max_llm_per_run"), "digest_max_llm_per_run", default=10, lo=0, hi=100)
digest_llm_rpm              = _int_in(payload.get("digest_llm_rpm"), "digest_llm_rpm", default=4,   lo=1, hi=60)
digest_llm_rpd              = _int_in(payload.get("digest_llm_rpd"), "digest_llm_rpd", default=200, lo=1, hi=1000)
digest_llm_batch_size       = _int_in(payload.get("digest_llm_batch_size"), "digest_llm_batch_size", default=4, lo=1, hi=50)
digest_llm_batch_interval_min = _int_in(payload.get("digest_llm_batch_interval_min"), "digest_llm_batch_interval_min", default=15, lo=1, hi=1440)
```

**Step 4 — Update `candidate_profile_to_dict()` (`job_hunt_profile.py`):**

```python
{
    ...,  # existing fields
    "digest_enabled":          profile.digest_enabled,
    "digest_threshold":        profile.digest_threshold,
    "digest_run_time":         profile.digest_run_time,
    "digest_max_per_source":   profile.digest_max_per_source,
    "digest_llm_enabled":      profile.digest_llm_enabled,
    "digest_max_llm_per_run":  profile.digest_max_llm_per_run,
    "digest_llm_rpm":          profile.digest_llm_rpm,
    "digest_llm_rpd":          profile.digest_llm_rpd,
    "digest_llm_batch_size":   profile.digest_llm_batch_size,
    "digest_llm_batch_interval_min": profile.digest_llm_batch_interval_min,
}
```

**Step 5 — Tests (`tests/test_profile.py`):**
- Round-trip: profile with all 10 digest fields serialises and deserialises correctly
- Defaults: profile JSON with no digest fields loads with defaults (no error)
- **parse_bool:** `"false"`, `"0"`, `"no"`, `"off"` → `False`; `"true"`, `"1"`, `"yes"`, `"on"` →
  `True`; real bools pass through; `"maybe"` / `2` raise `ProfileValidationError`
  (regression guard against `bool("false") == True`)
- Range: `digest_threshold` ∉ 0–100, `digest_max_per_source` ∉ 1–200, `digest_llm_rpm` ∉ 1–60,
  `digest_llm_rpd` ∉ 1–1000, `digest_llm_batch_size` ∉ 1–50, `digest_llm_batch_interval_min` ∉
  1–1440 each raise `ProfileValidationError`
- Boundary: `digest_max_llm_per_run = 0` is **accepted** (queues nothing, digest still runs)
- `digest_run_time`: `"7:00"`, `"24:00"`, `"07:60"`, `"abc"` raise; `"07:00"`, `"23:59"` pass
- Unknown field guard still blocks genuinely unknown keys

---

## 6. New Modules

### 6.1 `src/job_hunt_saved_searches.py`

```python
# v6: SQLite-backed (saved_searches table in job_hunt_index.db); state_root keyword-only on ALL fns.
def validate_search_id(search_id: str) -> str: ...          # ^[A-Za-z0-9_-]{1,64}$ or raise ValueError
def create_saved_search(name, source_id, params, *, state_root) -> SavedSearch: ...  # mints uuid4().hex
def load_saved_search(search_id, *, state_root) -> SavedSearch: ...  # raises SavedSearchNotFound
def list_saved_searches(*, state_root) -> list[SavedSearch]: ...
def save_saved_search(search, *, state_root) -> None: ...    # INSERT OR REPLACE by search_id
def delete_saved_search(search_id, *, state_root) -> bool: ...  # True if a row was deleted
def toggle_saved_search(search_id, *, state_root) -> SavedSearch: ...  # atomic UPDATE … SET enabled = NOT enabled
def update_last_run(search_id, *, state_root, count) -> None: ...
```

### 6.2 `src/job_hunt_digest.py`

```python
def query_digest(
    *,
    db_path: Path,
    date: str | None = None,
    unseen_only: bool = False,
    min_score: int = 0,
    limit: int = 100,
) -> list[DigestEntry]: ...

def mark_seen(job_ids: list[str], *, db_path: Path) -> int: ...
def mark_all_seen(*, db_path: Path, date: str | None = None) -> int: ...
def unseen_count(*, db_path: Path) -> int: ...
def digest_stats(*, db_path: Path) -> dict: ...
```

### 6.3 `src/job_hunt_scheduler.py`

```python
@dataclass(frozen=True)
class DigestRunResult:
    started_at: str
    finished_at: str
    searches_run: int
    jobs_fetched: int
    jobs_new: int            # first-seen, indexed this run
    jobs_scored: int
    jobs_llm_queued: int     # item 10: D3 QUEUES, it does NOT call the LLM.
                             # (LLM-processed counts live in the D6 worker result, §14.)
    jobs_skipped: int        # item 8: blank id / empty description / adapter/eval error
    errors: list[str]


def run_digest_pipeline(
    *,
    config: UIServerConfig,
    saved_searches: list[SavedSearch],
    profile: CandidateProfile,
    db_path: Path,
) -> DigestRunResult:
    """Core pipeline — synchronous, no threading. Called by scheduler thread and
    by the run-now handler. Returns a DigestRunResult when complete."""


class DigestScheduler:
    """Background daemon thread. Runs run_digest_pipeline() at digest_run_time daily."""

    def __init__(self, config, *, get_profile: Callable[[], CandidateProfile]): ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def run_now(self, saved_searches: list[SavedSearch] | None = None) -> DigestRunResult:
        """Synchronous manual trigger. Blocks until pipeline completes.
        The per-search route passes [one SavedSearch] (item 9); the daily scheduler
        passes all enabled searches. Non-blocking async version deferred to D5."""
    def last_result(self) -> DigestRunResult | None: ...
    def next_run_at(self) -> str | None: ...  # ISO datetime
```

---

## 7. Evaluation Pipeline Detail

```
For each SavedSearch (enabled=True), source_id lower-cased:
│
├─ 1. Fetch — source.search_handler(saved_search.params)
│       Returns list of UI result dicts (source_snapshot_json included)
│
├─ 2. Guards + Dedup  (each skip → log_skipped_job(reason) + jobs_skipped += 1, §7b)
│       sjid = source_job_id_from_ui_result(result)
│       if not sjid: skip reason="missing_source_job_id" (C2 — not dedupable)
│       if not result.get("description_raw","").strip(): skip reason="missing_description_raw" (C3)
│       if is_already_indexed(db_path, source_id, sjid): skip silently (already seen — item 11,
│           NOT logged as an error, NOT counted in jobs_skipped)
│
├─ 3. Convert — reviewed_job_payload_from_ui_result(result)
│       Maps UI dict → reviewed_job payload (JobPosting shape), INCLUDING
│       source_job_id = sjid (so JobPosting.source_job_id == the dedup key on rebuild).
│       No HTML form, no nonce, no source-detail API call at this step.
│
├─ 4. Deterministic eval (all new jobs)
│       payload["required_skills"], payload["preferred_skills"] =
│           extract_skills_from_text(payload["description_raw"])   # search-result text
│       reviewed_job_from_dict(payload) → JobPosting
│       evaluate_reviewed_job(profile, job, ...) → JobAnalysis
│       save_reviewed_job + save_job_analysis
│       upsert_job(db_path, {..., "source": source_id.lower(),
│                              "source_job_id": sjid, "apply_url": apply_url})
│       set_digest_meta(db_path, job_id, digest_date=today, saved_search_id=...)
│
└─ 5. Queue for LLM (NO LLM call here — see §14)
│       If profile.digest_llm_enabled AND match_score ≥ profile.digest_threshold:
│           set llm_status = "pending"  (capped at profile.digest_max_llm_per_run
│           newly-queued jobs per run so a huge fetch can't flood the queue)
│       Else: leave llm_status = NULL (deterministic-only digest entry)
```

**Detail fetch is deferred to the LLM worker and is source-aware** (V4): it runs in §14
just before the LLM call, only for jobs that reach the front of the paced queue — so the
rate-limited detail+LLM work is what gets spread across time, not the cheap deterministic scan.

### 7a. New-only behaviour (item 11)

The digest surfaces **first-seen jobs only.** A result whose `(lower(source), source_job_id)`
already exists in the index is skipped and is **not** re-added to today's digest, `digest_seen`
is not reset, and it does not re-enter the LLM queue. This is the whole point — you never see the
same top results again. **Consequence to accept:** changing your profile or `digest_threshold`
later does **not** re-score or resurface already-seen jobs; only genuinely new postings appear.
(If "re-score on profile change" is ever wanted, that's a separate explicit re-evaluation action,
out of scope here — OQ-2.)

### 7b. Skipped-job log (item 8)

"Quarantine" = append a line to a per-day JSONL log; the job is **not** indexed. No new table.

**Path:** `data/state/logs/digest_skipped_jobs_YYYY-MM-DD.jsonl` (the `logs` dir already exists in
the storage layout, `job_hunt_storage.py:268`). One JSON object per line:

```json
{"source":"reed","saved_search_id":"ba-london-01","reason":"missing_source_job_id",
 "title":"Business Analyst","url":"https://www.reed.co.uk/jobs/...","seen_at":"2026-06-24T07:04:13"}
```

**`reason` enum:** `missing_source_job_id` · `missing_description_raw` · `adapter_error` ·
`evaluation_error`. The pipeline increments `DigestRunResult.jobs_skipped` and logs one line per
skip; a single malformed result never aborts the run (each result is processed in try/except, the
error reason recorded, loop continues).

---

## 8. HTTP Routes

No `do_DELETE` — use POST for all mutations to match existing server style.

| Method | Path | Body | Purpose |
|---|---|---|---|
| `GET` | `/digest` | — | Digest feed page |
| `GET` | `/digest/count` | — | JSON `{unseen: N}` for sidebar badge |
| `POST` | `/digest/mark-seen` | JSON `{job_ids: [...]}` or `{all: true}` | Mark seen |
| `GET` | `/saved-searches` | — | JSON list of saved searches |
| `POST` | `/saved-searches` | JSON `{name, source_id, params}` | Create new saved search |
| `POST` | `/saved-searches/{id}/delete` | — | Delete a saved search |
| `POST` | `/saved-searches/{id}/toggle` | — | Enable/disable a saved search |
| `POST` | `/saved-searches/{id}/run-now` | — | **Synchronous** fetch+score trigger; returns `DigestRunResult` JSON (no LLM — jobs queued) |
| `POST` | `/digest/run-llm-batch` | — | Drain ONE paced LLM batch now; returns `{processed, remaining, skipped_rpd, errors}` |
| `GET` | `/digest/llm-queue` | — | JSON `{pending, done, failed, rpd_used_today, next_attempt_at}` |
| `GET` | `/scheduler/status` | — | JSON `{last_run, next_run, running, errors, llm_worker:{running, next_cycle, pending}}` |

**`/saved-searches/{id}/run-now` runs exactly ONE saved search (item 9).** The handler loads the
single `SavedSearch` by `id` and calls `run_digest_pipeline(saved_searches=[that_one], ...)` — it
does **not** run all saved searches. A future all-searches manual trigger, if needed, would be a
separate `POST /digest/run-now` (not in scope now).

Response (synchronous in D3):
```json
{
  "ok": true,
  "started_at": "2026-06-24T07:04:12",
  "finished_at": "2026-06-24T07:04:45",
  "searches_run": 1,
  "jobs_new": 8,
  "jobs_scored": 8,
  "jobs_llm_queued": 3,
  "jobs_skipped": 1,
  "errors": []
}
```
The HTTP handler blocks until `run_now()` returns. For the occasional manual trigger this is acceptable (typically < 30 seconds). If the user wants a non-blocking version, that is a D5 addition.

---

## 9. UI / UX

### Sidebar badge
```
🔔 Digest  [3]
```
Fetched via AJAX on page load from `GET /digest/count`. Badge hidden when `unseen == 0`.

### `/digest` page
Standalone page. Cards sorted by `match_score` descending.

```
Daily Digest                              [Mark all seen] [▼ Date ▼ Source]
8 new matches · Updated today 07:04
─────────────────────────────────────────────────────────────────
● 87  Apply   Business Analyst · Accenture · London · £55–70k  [View]
              ba-london-01 · Reed · Today
─────────────────────────────────────────────────────────────────
● 79  Review  IT Project Manager · HSBC · London · £60–75k     [View]
              ba-london-01 · Reed · Today
─────────────────────────────────────────────────────────────────
○ 74  Review  Business Analyst · Lloyds · Manchester · £50–60k [View]
              pm-manc-01 · Reed · Yesterday
```
● = unseen  ○ = seen. Clicking a row marks it seen and opens `/job/{id}`.

### Saved Searches — in My Profile
```
Saved Searches                                     [+ Add search]
──────────────────────────────────────────────────────────────────
BA roles, London         Reed  Last run: today (8 new)   ● Enabled
  keyword: business analyst · London · 50 results
  [Run now]  [Edit]  [Disable]  [Delete]

PM roles, Manchester     Reed  Last run: yesterday (2)   ● Enabled
  keyword: project manager · Manchester · 50 results
  [Run now]  [Edit]  [Disable]  [Delete]
```
**"Save this search"** button on Find Jobs tab → pre-fills name from keywords+location, calls `POST /saved-searches`, shows flash "Search saved — runs daily at 07:00".

### Digest settings — in My Profile
```
Daily Digest
  [ ] Enabled
  Run time:    07:00
  Show jobs ≥: 70  (match score)
  Max per run: 50  (jobs per saved search)
  AI analysis: [ ] Enabled for top matches
  Max AI calls: 10 per run (newly queued)
  ── AI rate limits (avoid Gemini 429) ──
  Calls/min (RPM):   4   (keep < your model's RPM; 5-RPM chain → 4)
  Calls/day (RPD):   200 (keep < 250 free-tier cap)
  Batch size:        4   (jobs per worker cycle)
  Batch interval:    15  (minutes between cycles)
```

---

## 10. Phased Implementation Plan

### Phase D1 — Saved Searches
- `src/job_hunt_saved_searches.py` + tests
- Routes: `GET /saved-searches`, `POST /saved-searches`, `POST /saved-searches/{id}/delete`, `POST /saved-searches/{id}/toggle`
- UI: "Save this search" button on Find Jobs tab; Saved Searches section in My Profile
- **Deliverable:** User can save, list, and delete searches. No auto-run yet.

### Phase D2 — Schema Migration + Digest Query Layer
**Order matters (item 16): the model layer must be correct before DB/rebuild logic can be verified.**
1. **`JobPosting.source_job_id`** field added (`job_hunt_models.py`, §3.7, C1).
2. **Reviewed-job serialisation:** `OPTIONAL_REVIEWED_JOB_FIELDS` + `reviewed_job_from_dict` +
   `reviewed_job_to_dict` round-trip `source_job_id` (back-compat: missing → None).
3. **Adapters:** Reed/Adzuna populate `source_job_id`; keep `source_ref`/`url` = apply URL only.
4. **DB migration:** `_migrate_schema()` adds all ten columns incl. `apply_url`, the LLM-queue and
   LLM-**claim** columns (`llm_claimed_at`, `llm_claim_token`); `open_db` sets WAL + `busy_timeout` (C4).
5. **Indexes (§3.1a):** partial `UNIQUE(source, source_job_id)` + the three perf indexes (items 3,4).
6. **`upsert_job()`** → `ON CONFLICT(job_id) DO UPDATE`, preserving digest **+ all llm** columns (C6),
   `source` lower-cased (V2), with the `IntegrityError` fallback for the unique index (§3.1a).
7. **`rebuild_index()`** persists `source_job_id` (+ `apply_url`) from the reviewed_job, lower-case source.
8. **Digest query layer:** `src/job_hunt_digest.py` (`query_digest`, `mark_seen`, `unseen_count`) +
   `is_already_indexed()` + `source_job_id_from_ui_result()` + `apply_url_from_ui_result()` +
   `set_digest_meta()` + `claim_batch()` + `reset_stale_llm_processing()` in `job_hunt_index.py`.
9. **Tests:** migration idempotency, dedup, serialisation round-trip, skipped-job logging,
   LLM claim/recovery — see acceptance checklist. **v6 additions:** (a) `source_job_id`
   normalization — `12345678` (int) ≡ `"12345678"`, while `" 123 "` and leading-zero `"00123"` are
   handled per the strip-not-parse rule; (b) **cross-source isolation** — insert `reed/123` and
   `adzuna/123`, run the digest/feed query, assert exactly 2 distinct rows with distinct canonical
   `job_id`s and both source labels (no query keys on `source_job_id` alone); (c) **fail-loud
   invariant** — forcing a `(source, source_job_id)` collision under a different `job_id` raises +
   logs, and does NOT silently patch.
- Route: `GET /digest/count` (returns `{unseen: 0}` until D3 runs)
- **Deliverable:** Schema + model ready; dedup and digest queries verified; badge endpoint live.

### Phase D3 — Digest Pipeline + CandidateProfile Prefs
- 10 new fields on `CandidateProfile` (`digest_*` incl. the 4 LLM-rate fields) with all
  loader/serializer/**range-validation**/test changes (§5.3)
- `reviewed_job_payload_from_ui_result()` + `digest_job_id()` adapters in `ui_utils.py` (V6)
- `run_digest_pipeline()` in `src/job_hunt_scheduler.py` (fetch + deterministic score +
  skill extraction + **queue** high-match jobs as `llm_status="pending"`; **no LLM call**)
- Route: `POST /saved-searches/{id}/run-now` (synchronous; returns `DigestRunResult` JSON)
- Route: `GET /scheduler/status` (static for now)
- Digest settings UI section in My Profile
- **Deliverable:** User can trigger a digest run manually; high-match jobs appear queued for AI.

### Phase D4 — Digest UI
- `render_digest_page()` in `ui_render.py`
- Route: `GET /digest`
- Route: `POST /digest/mark-seen`
- Sidebar badge (AJAX `GET /digest/count`)
- Filters: date / source / saved-search / seen; show per-job `llm_status` (Pending/Done/—)
- **Deliverable:** Full digest feed visible in the app. Badge shows unseen count.

### Phase D5 — Scheduler (automatic daily run)
- `DigestScheduler` daemon thread for the fetch+score run at `digest_run_time`
- Integrated into server startup (`atexit` for clean shutdown)
- `GET /scheduler/status` returns live `last_run`, `next_run`, `running`
- **Deliverable:** Fully automatic fetch+score. User wakes up to a fresh (deterministic) feed.

### Phase D6 — Paced LLM Worker (rate-limited AI enrichment) — see §14
- `LLMQueueWorker` daemon thread: drains `llm_status="pending"` jobs in `digest_llm_batch_size`
  batches every `digest_llm_batch_interval_min` minutes; paces calls at `60/digest_llm_rpm` sec;
  enforces `digest_llm_rpd` via a per-day counter; source-aware detail fetch (§11); 429 →
  exponential backoff via `llm_next_attempt_at` + requeue (never drop)
- Routes: `POST /digest/run-llm-batch` (manual drain), `GET /digest/llm-queue` (status)
- Settings: the 4 LLM-rate fields wired into Digest Settings UI
- **Deliverable:** High-match jobs get AI analysis over time without tripping Gemini 429/RPD.
- **Why a separate phase:** D1–D5 deliver a working deterministic digest; D6 layers AI on top
  so a rate-limit bug can never block the core feed.

---

## 11. Source Extensibility — Reed + Adzuna (both live)

Adzuna shipped in P5-1 (2026-06-24); `ENABLED_SOURCES = ["Reed", "Adzuna"]`. Both expose
`search_handler` via the registry (`source_registry.py:63`) returning UI result dicts with
`source_job_id` populated, so the digest pipeline supports both with no per-source branching
in the fetch/score path. `run_digest_pipeline` loops saved searches, looks up the registered
source by lower-cased `source_id`, and calls `search_handler`.

**Adzuna-specific concern — no detail-fetch API (V4).** Reed enriches a job by calling
`fetch_reed_job_detail(source_job_id)` for the full description; Adzuna has **no** detail
endpoint by design (P5-1 note: "no source_snapshot / no detail-fetch"). So the LLM worker's
detail step (§14) must be **source-aware**:

```python
def fetch_full_description(source_id: str, source_job_id: str, fallback: str) -> str:
    if source_id.lower() == "reed" and source_job_id:
        detail = fetch_reed_job_detail(source_job_id)
        if detail and detail.get("jobDescription"):
            return strip_html(detail["jobDescription"]).strip()
    return fallback   # Adzuna and any failure: use the stored search-result description
```

Adzuna must populate `source_job_id` with the stable Adzuna id. Its advert/apply URL should be
mapped to `apply_url` / `JobPosting.url` / legacy `JobPosting.source_ref` only for display. Dedup
remains `lower(source) + source_job_id`. New sources only need `search_handler` + populated
`source_job_id`.

**D6 v1 dispatch level (item 12):** D6 v1 may use a small source-aware dispatcher with a Reed
branch and a fallback for Adzuna (the `fetch_full_description` example above). A later refactor can
move `detail_fetch_handler` into the source registry. For this backlog item, do **not** design a new
registry contract unless needed.

---

## 12. Dependencies on Other Work

| Dependency | Why | Status |
|---|---|---|
| MT-1 — Reed source extraction | Separates Reed UI logic before D3 pipeline is built; cleaner source boundary | ✅ Done 2026-06-19 |
| LT-1 — UI layer split | Digest handlers + render go into clean layers, not the monolith | ✅ Done 2026-06-19 |
| `job_hunt_index.py` D2 changes | All other D-phases depend on schema migration and `upsert_job` fix | Must be first |
| `CandidateProfile` prefs (D3) | D3 pipeline reads profile for threshold, LLM flag, rate limits | Must be in D3 |

Both prerequisites (MT-1, LT-1) are now complete, so D1 can start immediately.

---

## 13. Open Questions

- **Run time timezone:** `digest_run_time` uses `datetime.now()` (local time). Document this; if machine TZ changes, the run time shifts. Consider storing as UTC with a display conversion.
- **Machine offline at run time:** the scheduler simply misses the run (no catch-up). The "Run now" button is the recovery path.
- **Reed API rate limits:** 5 saved searches × 50 results = 250 API calls. Reed's documented limit is 1 request/second for authenticated calls. Add `time.sleep(0.25)` between result fetches if running multiple saved searches back-to-back.
- **LLM rate/cost cap:** now handled by the §14 paced worker (RPM + RPD + batches), not a single per-run cap. `digest_max_llm_per_run` only caps how many NEW jobs are *queued* per fetch run.
- **`source_job_id` availability — RESOLVED (V5):** `source_job_id` is populated by both Reed and Adzuna adapters. Final dedup uses `lower(source) + source_job_id`. `source_ref`/`apply_url` is display metadata only.
- **LLM worker only runs while the app is up (same as D5 scheduler).** A laptop asleep all day means queued jobs wait until next launch; `POST /digest/run-llm-batch` is the manual drain. If always-on enrichment is needed later, move the worker to an OS-level scheduled task.
- **Per-day counter reset/timezone:** the RPD counter resets at local midnight, but Gemini's free-tier RPD resets at **midnight Pacific**. Defaulting `digest_llm_rpd=200` (< 250) absorbs the mismatch; document it rather than syncing to PT.
- **OQ-1 — RESOLVED (Mic, 2026-06-24): acceptable, no reconcile.** A manually-added job with no
  `source_job_id` and a later digest hit for the same posting may exist as two separate rows under
  different `job_id`s. The partial unique index permits this (NULL ids don't collide); no secondary
  reconcile step is required. D2 upsert can be finalised on this basis.
- **OQ-2 — deferred to a to-do (Mic, 2026-06-24):** re-score / resurface already-seen jobs after a
  profile or threshold change stays **out of scope** for D1–D6 (§7a). Tracked as a future backlog
  item in `PROJECT_TODO.md` ("Re-evaluate seen digest jobs on profile/threshold change").

---

## 14. Rate-Limited LLM Enrichment (D6)

### 14.1 Why decouple

Gemini free tier (user-confirmed 2026-06-24): `gemini-3-flash-preview` and `gemini-2.5-flash`
= **5 RPM**, `gemini-3.1-flash-lite` = **15 RPM**, RPD ≈ **250**. Firing all high-match jobs'
LLM calls inline at the end of a digest run trips 429 immediately. The current client only
reacts to 429 by trying the next model in the chain, then **drops** the job — no wait, no
retry. So enrichment must be a separate, paced, persistent queue that survives restarts.

### 14.2 Queue state (in the existing SQLite `jobs` table)

| Column | Meaning |
|---|---|
| `llm_status` | `NULL` (not queued) · `pending` · `processing` (claimed, in flight) · `done` · `failed` · `skipped` |
| `llm_attempts` | retry count; → `failed` after `_MAX_LLM_ATTEMPTS` (e.g. 5) |
| `llm_next_attempt_at` | ISO datetime backoff gate; row is eligible only when `now ≥` this (or NULL) |

No new table — the jobs row already exists after deterministic scoring.

### 14.3 Worker loop (`LLMQueueWorker` in `job_hunt_scheduler.py`)

```
every digest_llm_batch_interval_min minutes (daemon thread):
    if not profile.digest_llm_enabled: continue
    if rpd_used_today() >= profile.digest_llm_rpd: continue   # daily cap, wait for reset

    reset_stale_llm_processing(db_path, now=now())   # recover crashed claims (item 6)
    batch = claim_batch(db_path,
                limit=profile.digest_llm_batch_size,
                ready_before=now(), now=now())   # token-based atomic claim — see 14.3a (C4/item 5)
    min_gap = 60.0 / max(1, profile.digest_llm_rpm)   # seconds between calls
    for job in batch:
        if rpd_used_today() >= profile.digest_llm_rpd: break
        desc = fetch_full_description(job.source, job.source_job_id, job.description_raw)  # §11
        try:
            result = explain_job_match_with_llm(profile, job, analysis)  # {fit,risk,action}
            save_analysis_llm_fields(job_id, result)
            set_llm_status(job_id, "done")
            incr_rpd_counter()
        except RateLimited as e:           # 429 surfaced from the client (see 14.4)
            backoff = min(_MAX_BACKOFF, base * 2 ** job.llm_attempts)  # e.g. 60s,120s,240s…
            set_llm_status(job_id, "pending",
                           attempts=job.llm_attempts + 1,
                           next_attempt_at=now() + backoff)
            if job.llm_attempts + 1 >= _MAX_LLM_ATTEMPTS:
                set_llm_status(job_id, "failed")
            break                          # stop the batch — we're being throttled
        except Exception as e:             # non-rate error: record, don't infinite-retry
            set_llm_status(job_id, "pending", attempts=job.llm_attempts + 1,
                           next_attempt_at=now() + min_gap)
            if job.llm_attempts + 1 >= _MAX_LLM_ATTEMPTS: set_llm_status(job_id, "failed")
        time.sleep(min_gap)                # pace within the batch
```

**Pacing math (defaults):** batch_size 4, interval 15 min → ≤ 4 calls per 15 min ≈ 0.27/min,
far under 5 RPM, and ≤ ~16/hr. Even a 50-job backlog drains in ~3 hrs, well under 200 RPD.
The `min_gap` sleep is belt-and-braces so a large manual `batch_size` still can't exceed RPM.

### 14.3a Atomic claim — prevents double-processing & lock errors (C4)

The auto worker and the manual `POST /digest/run-llm-batch` can run concurrently, and the
stdlib `http.server` is threaded — two consumers must never grab the same row, and concurrent
writes must not raise `database is locked`. Both paths call ONE shared claim function that
selects-and-marks in a single immediate transaction, then makes LLM calls **outside** the txn:

```python
def claim_batch(db_path, *, limit, ready_before, now) -> list[Row]:
    """Token-based claim (item 5). Returns ONLY rows this call actually claimed."""
    token = str(uuid.uuid4())
    conn = open_db(db_path)   # open_db sets WAL + busy_timeout=5000 (§3.1)
    try:
        conn.execute("BEGIN IMMEDIATE")          # take the write lock up front
        ids = [r["job_id"] for r in conn.execute(
            """SELECT job_id FROM jobs
                WHERE llm_status = 'pending'
                  AND (llm_next_attempt_at IS NULL OR llm_next_attempt_at <= ?)
                ORDER BY match_score DESC LIMIT ?""",
            (ready_before, limit),
        ).fetchall()]
        if ids:
            conn.executemany(
                """UPDATE jobs
                      SET llm_status='processing', llm_claimed_at=?, llm_claim_token=?
                    WHERE job_id=? AND llm_status='pending'""",
                [(now, token, i) for i in ids],
            )
        # Return only what we own — guards against any racing claimer.
        claimed = conn.execute(
            """SELECT * FROM jobs
                WHERE llm_claim_token = ?
                  AND llm_status = 'processing'
                ORDER BY match_score DESC""",
            (token,),
        ).fetchall()
        conn.commit()
        return claimed
    finally:
        conn.close()


def reset_stale_llm_processing(db_path, *, now, older_than_minutes=30) -> int:
    """Recover rows stuck in 'processing' (worker crashed mid-call). Item 6.
    Called on server startup and optionally at the top of each worker cycle."""
    cutoff = iso(now - timedelta(minutes=older_than_minutes))
    conn = open_db(db_path)
    try:
        cur = conn.execute(
            """UPDATE jobs
                  SET llm_status='pending', llm_claimed_at=NULL, llm_claim_token=NULL
                WHERE llm_status='processing'
                  AND (llm_claimed_at IS NULL OR llm_claimed_at <= ?)""",
            (cutoff,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
```

Lifecycle: claimed row is `processing` (stamped `llm_claimed_at` + `llm_claim_token`); on success
→ `done` (token/claimed_at cleared); on 429 → `pending` with backoff `llm_next_attempt_at`; on a
crash it stays `processing` until `reset_stale_llm_processing` (startup + each cycle) returns it to
`pending`. This makes the queue idempotent and restart-safe. `set_llm_status` writes are short
single-row UPDATEs, so WAL + `busy_timeout` absorb contention with request threads.

### 14.3b `set_llm_status()` — the only status-transition writer (item 8)

The worker (§14.3) transitions queue state exclusively through `set_llm_status()`. It does **not**
set `processing` — that status is owned by `claim_batch()` (§14.3a) so the claim and the
status-flip stay in one atomic transaction.

```python
def set_llm_status(
    db_path: Path,
    job_id: str,
    status: str,
    *,
    attempts: int | None = None,
    next_attempt_at: str | None = None,
) -> None:
    ...
```

Required behaviour:
- Validate `status` is one of `pending`, `done`, `failed`, `skipped`. Reject arbitrary strings
  (raise `ValueError`). `processing` is **not** an allowed value here — only `claim_batch()` sets it.
- `status="done"`: clear `llm_claimed_at`, `llm_claim_token`, **and** `llm_next_attempt_at`.
- `status="pending"`: clear `llm_claimed_at` and `llm_claim_token`; set `llm_next_attempt_at` if
  `next_attempt_at` is provided (else leave as-is for an immediate retry).
- `status="failed"`: clear `llm_claimed_at` and `llm_claim_token`; keep `llm_attempts`.
- `status="skipped"`: clear `llm_claimed_at` and `llm_claim_token`.
- If `attempts` is provided, update `llm_attempts`.
- Single-row UPDATE keyed on `job_id`; relies on WAL + `busy_timeout` for contention (§3.1).

### 14.4 Client change — surface 429 distinctly

`job_hunt_llm.py` currently returns `(None, "...rate limited...", True)` on 429 and just tries
the next model. Add a typed signal so the worker can tell "rate limited" (→ backoff + requeue)
from "bad output" (→ fail fast):

- Introduce `class RateLimited(Exception)`.
- **Thread the HTTP status code through (C7).** Today `_call_gemini_model` collapses 429 into
  `(None, "...rate limited...", True)` (`job_hunt_llm.py:77–80`) and the chain returns only an
  error *string*, conflating 404 / 429 / 503. Carry the status code (or a typed failure enum) out
  of each model attempt so the caller knows *why* the chain failed.
- Raise `RateLimited` **only if every applicable model attempt failed with 429** — not on 404
  (model missing → genuinely try next/last) or 503 (transient server). A 404-only failure must
  NOT look like rate-limiting, or the worker backs off forever against a misconfigured model.
- Keep the existing 404 → next-model fallthrough behaviour unchanged.

### 14.5 RPD counter

Counter keyed by local date: `{ "date": "2026-06-24", "count": 37 }`. `incr_rpd_counter()`
bumps it; `rpd_used_today()` returns 0 when the stored date != today (lazy reset).

**Concurrency (C8) — FINAL DECISION: use a SQLite table `llm_rpd`, not JSON.** A JSON
read-modify-write loses increments when the worker and a manual drain run together. The counter
lives in a tiny SQLite table and is incremented atomically, reusing the DB's locking (WAL +
`busy_timeout`) with no extra lock object. (Timezone caveat — Gemini resets at midnight PT — in §13.)

Migration (add to §3.2 alongside the other `CREATE … IF NOT EXISTS` statements):

```sql
CREATE TABLE IF NOT EXISTS llm_rpd (
    date TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0
);
```

Functions:
- `rpd_used_today(db_path, date) -> int` — `SELECT count FROM llm_rpd WHERE date = ?`; returns 0
  when no row for today (lazy reset — yesterday's row simply isn't read).
- `incr_rpd_counter(db_path, date) -> int` — atomic increment, returns the new count:

```sql
INSERT INTO llm_rpd(date,count)
VALUES(?,1)
ON CONFLICT(date) DO UPDATE SET count = count + 1;
```

### 14.5a Where the LLM result is stored (item 15)

**Decision: detailed enrichment goes in the existing `JobAnalysis` JSON record, NOT the jobs
table.** The jobs table holds only queue metadata (`llm_status`, `llm_attempts`,
`llm_next_attempt_at`, `llm_claimed_at`, `llm_claim_token`). This keeps the index lean and reuses
the analysis file that already carries deterministic results + the existing `explain_job_match_with_llm`
`{fit, risk, action}` output.

Add to `JobAnalysis` (`job_hunt_models.py`), all optional with defaults so old files load:

```python
llm_fit_summary: str | None = None
llm_risk_summary: str | None = None
llm_recommended_action: str | None = None
llm_model: str | None = None          # which model produced it (chain may fall back)
llm_generated_at: str | None = None   # ISO datetime
```

`save_analysis_llm_fields(job_id, result)` = load the `JobAnalysis`, set these five fields, re-save
via the existing analysis serializer; then `set_llm_status(job_id, "done")` on the jobs row.
Serialization round-trip + back-compat (missing → None) must be covered by tests.

### 14.6 Manual + automatic triggers

- **Automatic:** `LLMQueueWorker` daemon, started alongside `DigestScheduler` (D6), `atexit` stop.
- **Manual:** `POST /digest/run-llm-batch` drains exactly one batch synchronously (for "I want
  AI on these now") and returns `{processed, remaining, skipped_rpd, errors}`.
- **Observability:** `GET /digest/llm-queue` → `{pending, done, failed, rpd_used_today, next_attempt_at}`.

### 14.7 Tests (D6)

- Pacing: with `rpm=4`, calls are ≥ 15 s apart (monkeypatch clock; assert sleep calls).
- Backoff: a mocked 429 sets `llm_status='pending'` with growing `llm_next_attempt_at`, never drops.
- Daily cap: at `rpd` reached, worker stops and leaves rows `pending`; resets next day.
- Max attempts: after `_MAX_LLM_ATTEMPTS` 429s a job goes `failed`, not infinite-retry.
- Source-aware detail: Reed path calls `fetch_reed_job_detail`; Adzuna path does not and uses fallback.
- Selection order: highest `match_score` drained first.
