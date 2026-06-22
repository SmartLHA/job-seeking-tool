# Backlog-01 Design — Daily Job Digest (Auto-Evaluate + High-Match Feed)

<!-- STATUS -->
> **Implementation status:** ⬜ Backlog — design only, not started
> **Divergences from spec:** n/a — this is the spec
> **Key functions:** none yet — all new
> **Routes:** `GET /digest`, `GET /digest/count`, `POST /digest/mark-seen`, `GET /saved-searches`, `POST /saved-searches`, `POST /saved-searches/{id}/delete`, `POST /saved-searches/{id}/run-now`, `GET /scheduler/status`
<!-- /STATUS -->

**Date:** 2026-06-18 (v2 — reviewer findings addressed)
**Owner:** Mic

**User decisions:**
- Score threshold: configurable per user
- Search source: named saved search profiles
- Seen/dismissed: keep all, mark New/Seen; badge shows unseen count
- Evaluation mode: deterministic first; LLM only for jobs ≥ threshold

**Review findings addressed (v2):**
- F1 (High): `source_ref` column added to schema; `upsert_job()` and `rebuild_index()` updated to persist it; dedup query now valid
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
                              │  1. Fetch (source.search_handler)     │
                              │  2. Dedup (source + source_ref)       │
                              │  3. Convert (UI dict → reviewed_job)  │
                              │  4. Deterministic eval (all new jobs) │
                              │  5. LLM (jobs ≥ digest_threshold)     │
                              └──────────────┬──────────────┘
                                             │
                              ┌──────────────┴──────────────┐
                              │  SQLite index (with new      │
                              │  source_ref, digest columns) │
                              └──────────────┬──────────────┘
                                             │
                                  GET /digest   GET /digest/count
```

---

## 3. SQLite Schema Changes (job_hunt_index.py)

Four new columns on the `jobs` table. These must be added before D2 proceeds.

### 3.1 New columns

```sql
-- Dedup: external job ID from the source (e.g. Reed jobId integer as string)
ALTER TABLE jobs ADD COLUMN source_ref TEXT;

-- Digest tracking
ALTER TABLE jobs ADD COLUMN digest_date TEXT;          -- ISO date; NULL = not from digest
ALTER TABLE jobs ADD COLUMN digest_seen INTEGER DEFAULT 0;  -- 0=new, 1=seen
ALTER TABLE jobs ADD COLUMN saved_search_id TEXT;      -- which SavedSearch found it
```

### 3.2 Migration

`open_db()` already runs `CREATE TABLE IF NOT EXISTS`. Add a `_migrate_schema(conn)` call inside `open_db()` that checks `PRAGMA table_info(jobs)` for each new column and runs `ALTER TABLE ... ADD COLUMN` only if missing:

```python
_MIGRATION_COLUMNS = [
    ("source_ref",        "TEXT"),
    ("digest_date",       "TEXT"),
    ("digest_seen",       "INTEGER DEFAULT 0"),
    ("saved_search_id",   "TEXT"),
]

def _migrate_schema(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    for col_name, col_type in _MIGRATION_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}")
    conn.commit()
```

**Existing rows** get `NULL` for all four columns — safe, backward-compatible.

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
                (job_id, job_title, company, location, source, source_ref,
                 match_score, decision, user_decision, ats_score,
                 tailoring_ready, status, updated_at, salary_min, salary_max)
            VALUES
                (:job_id, :job_title, :company, :location, :source, :source_ref,
                 :match_score, :decision, :user_decision, :ats_score,
                 :tailoring_ready, :status, :updated_at, :salary_min, :salary_max)
            ON CONFLICT(job_id) DO UPDATE SET
                job_title      = excluded.job_title,
                company        = excluded.company,
                location       = excluded.location,
                source         = excluded.source,
                source_ref     = excluded.source_ref,
                match_score    = excluded.match_score,
                decision       = excluded.decision,
                user_decision  = excluded.user_decision,
                ats_score      = excluded.ats_score,
                tailoring_ready = excluded.tailoring_ready,
                status         = excluded.status,
                updated_at     = excluded.updated_at,
                salary_min     = excluded.salary_min,
                salary_max     = excluded.salary_max
                -- digest_date, digest_seen, saved_search_id NOT listed here —
                -- they are preserved unchanged on conflict
            """,
            {
                "job_id":          row.get("job_id"),
                "job_title":       row.get("job_title"),
                "company":         row.get("company"),
                "location":        row.get("location"),
                "source":          row.get("source"),
                "source_ref":      row.get("source_ref"),   # NEW
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
    source_ref: str,
) -> bool:
    """True if a job with this source + source_ref already exists in the index."""
    conn = open_db(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE source = ? AND source_ref = ? LIMIT 1",
            (source_id, source_ref),
        ).fetchone()
        return row is not None
    finally:
        conn.close()
```

### 3.6 Update `rebuild_index()` to persist `source_ref`

`rebuild_index()` loads `reviewed_job.source_ref` and passes it to `upsert_job()`:

```python
# Inside rebuild_index(), after loading reviewed_job:
source_ref = reviewed_job.source_ref   # JobPosting already has this field
# Pass to upsert_job:
upsert_job(db_path, {
    ...existing fields...,
    "source_ref": source_ref,   # ADD THIS
})
```

---

## 4. Source Interface Contract (clarified)

`search_handler` in `JobSource` already returns **UI result dicts** — not `NormalizedJob`. The current Reed implementation (`search_reed_jobs_for_ui`) calls `fetch_reed_jobs → reed_job_to_ui_result` and returns UI dicts. This is the correct contract; the pipeline uses it as-is.

### 4.1 What a UI result dict looks like

```python
{
    "source": "reed",
    "source_job_id": "12345678",    # used as source_ref for dedup
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

```python
# In ui_utils.py (or job_hunt_digest.py)
def reviewed_job_payload_from_ui_result(result: dict[str, Any]) -> dict[str, str]:
    """Convert a source UI result dict to a reviewed_job payload dict.
    Mirrors the fields that render_reed_select_form puts in hidden inputs."""
    return {
        "source":               result.get("source", ""),
        "source_job_id":        result.get("source_job_id", ""),
        "title":                result.get("title", ""),
        "company":              result.get("company", ""),
        "location":             result.get("location", ""),
        "work_mode":            result.get("work_mode", ""),
        "employment_type":      result.get("employment_type", ""),
        "url":                  result.get("url", ""),
        "description_raw":      result.get("description_raw", ""),
        "salary_min_gbp":       result.get("salary_min_gbp", ""),
        "salary_max_gbp":       result.get("salary_max_gbp", ""),
        "source_snapshot_json": result.get("source_snapshot_json", ""),
    }
```

This means the pipeline does **not** go through Reed's `select_handler` (which fetches full job detail from the API and validates a nonce). That full detail fetch happens in D3 optionally, just before LLM enrichment.

---

## 5. New Data Models

### 5.1 `SavedSearch`

```python
@dataclass(frozen=True, slots=True)
class SavedSearch:
    search_id: str          # slug, e.g. "ba-london-01"
    name: str               # user label, e.g. "BA roles, London"
    source_id: str          # "reed" | "adzuna" | ...
    params: dict[str, str]  # normalised search params (same shape as normalize_search_params output)
    enabled: bool           # False = skip in daily run
    created_at: str         # ISO datetime
    last_run_at: str | None
    last_run_count: int     # new jobs found on last run
```

**Storage:** `data/state/saved_searches/{search_id}.json`
**Module:** `src/job_hunt_saved_searches.py`

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
digest_max_llm_per_run: int = 10
```

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
}
```

**Step 3 — Update `candidate_profile_from_dict()` (`job_hunt_profile.py`):**

```python
digest_enabled         = bool(payload.get("digest_enabled", True))
digest_threshold       = int(payload.get("digest_threshold", 70))
digest_run_time        = str(payload.get("digest_run_time", "07:00"))
digest_max_per_source  = int(payload.get("digest_max_per_source", 50))
digest_llm_enabled     = bool(payload.get("digest_llm_enabled", True))
digest_max_llm_per_run = int(payload.get("digest_max_llm_per_run", 10))
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
}
```

**Step 5 — Tests (`tests/test_profile.py`):**
- Round-trip: profile with digest fields serialises and deserialises correctly
- Defaults: profile JSON with no digest fields loads with defaults (no error)
- Validation: `digest_threshold` out of range (0–100) raises `ProfileValidationError`
- Unknown field guard still blocks genuinely unknown keys

---

## 6. New Modules

### 6.1 `src/job_hunt_saved_searches.py`

```python
def create_saved_search(name, source_id, params, *, state_root) -> SavedSearch: ...
def load_saved_search(search_id, *, state_root) -> SavedSearch: ...
def list_saved_searches(*, state_root) -> list[SavedSearch]: ...
def save_saved_search(search, *, state_root) -> None: ...
def delete_saved_search(search_id, *, state_root) -> None: ...
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
    jobs_new: int
    jobs_scored: int
    jobs_llm_analysed: int
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
    def run_now(self) -> DigestRunResult:
        """Synchronous manual trigger. Blocks until pipeline completes.
        HTTP handler calls this directly; user waits for the result (D3).
        Non-blocking async version deferred to D5 if needed."""
    def last_result(self) -> DigestRunResult | None: ...
    def next_run_at(self) -> str | None: ...  # ISO datetime
```

---

## 7. Evaluation Pipeline Detail

```
For each SavedSearch (enabled=True):
│
├─ 1. Fetch — source.search_handler(saved_search.params)
│       Returns list of UI result dicts (source_snapshot_json included)
│
├─ 2. Dedup — is_already_indexed(db_path, source_id, result["source_job_id"])
│       Skip if True. Tracks which jobs are genuinely new.
│
├─ 3. Convert — reviewed_job_payload_from_ui_result(result)
│       Maps UI dict fields to reviewed_job payload dict.
│       No HTML form, no nonce, no Reed API call at this step.
│
├─ 4. Deterministic eval (all new jobs)
│       reviewed_job_from_dict(payload) → JobPosting
│       evaluate_reviewed_job(profile, job, ...) → JobAnalysis
│       save_reviewed_job + save_job_analysis
│       upsert_job(db_path, {..., "source_ref": result["source_job_id"]})
│       set_digest_meta(db_path, job_id, digest_date=today, saved_search_id=...)
│
└─ 5. LLM enrichment (jobs where match_score ≥ profile.digest_threshold,
│      up to profile.digest_max_llm_per_run, if profile.digest_llm_enabled)
│       fetch_reed_job_detail(source_job_id) → full jobDescription
│       explain_job_match_with_llm(profile, job, analysis) → {fit, risk, action}
│       Re-save analysis with llm fields populated
│       (errors here are non-fatal — job stays in digest without LLM fields)
│       time.sleep(1) between LLM calls to respect rate limits
```

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
| `POST` | `/saved-searches/{id}/run-now` | — | **Synchronous** trigger; returns `DigestRunResult` JSON |
| `GET` | `/scheduler/status` | — | JSON `{last_run, next_run, running, errors}` |

**`/saved-searches/{id}/run-now` response (synchronous in D3):**
```json
{
  "ok": true,
  "started_at": "2026-06-18T07:04:12",
  "finished_at": "2026-06-18T07:04:45",
  "jobs_new": 8,
  "jobs_scored": 8,
  "jobs_llm_analysed": 3,
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
  Max AI calls: 10 per run
```

---

## 10. Phased Implementation Plan

### Phase D1 — Saved Searches
- `src/job_hunt_saved_searches.py` + tests
- Routes: `GET /saved-searches`, `POST /saved-searches`, `POST /saved-searches/{id}/delete`, `POST /saved-searches/{id}/toggle`
- UI: "Save this search" button on Find Jobs tab; Saved Searches section in My Profile
- **Deliverable:** User can save, list, and delete searches. No auto-run yet.

### Phase D2 — Schema Migration + Digest Query Layer
- `_migrate_schema()` in `job_hunt_index.py` (adds `source_ref`, `digest_date`, `digest_seen`, `saved_search_id`)
- `upsert_job()` rewritten with `ON CONFLICT DO UPDATE` — preserves digest columns
- `set_digest_meta()` added to `job_hunt_index.py`
- `is_already_indexed()` added to `job_hunt_index.py`
- `rebuild_index()` updated to persist `source_ref` from `reviewed_job.source_ref`
- `src/job_hunt_digest.py` with `query_digest`, `mark_seen`, `unseen_count` + tests
- Route: `GET /digest/count` (returns `{unseen: 0}` until D3 runs)
- **Deliverable:** Schema ready; dedup and digest queries verified; badge endpoint live.

### Phase D3 — Digest Pipeline + CandidateProfile Prefs
- New fields on `CandidateProfile` (`digest_threshold`, etc.) with all loader/serializer/test changes
- `reviewed_job_payload_from_ui_result()` adapter in `ui_utils.py`
- `run_digest_pipeline()` in `src/job_hunt_scheduler.py` (no thread yet)
- Route: `POST /saved-searches/{id}/run-now` (synchronous; returns `DigestRunResult` JSON)
- Route: `GET /scheduler/status` (returns static `{last_run: null, running: false}` for now)
- Digest settings UI section in My Profile
- **Deliverable:** User can trigger a digest run manually. Results appear in index with digest metadata.

### Phase D4 — Digest UI
- `render_digest_page()` in `ui_render.py`
- Route: `GET /digest`
- Route: `POST /digest/mark-seen`
- Sidebar badge (AJAX `GET /digest/count`)
- Filters: date / source / saved-search / seen
- **Deliverable:** Full digest feed visible in the app. Badge shows unseen count.

### Phase D5 — Scheduler (automatic daily run)
- `DigestScheduler` daemon thread
- Integrated into server startup (`atexit` for clean shutdown)
- `GET /scheduler/status` returns live `last_run`, `next_run`, `running`
- **Deliverable:** Fully automatic. User wakes up to a fresh feed.

---

## 11. Source Extensibility

The pipeline calls `source.search_handler(params)` — the same `JobSource` interface used by the manual search. When Adzuna is added:

1. Create `src/job_sources/adzuna_source.py` with `search_handler` returning UI result dicts in the same shape
2. Ensure `result["source_job_id"]` is populated (used as `source_ref`)
3. Create Adzuna saved searches with `source_id = "adzuna"`
4. The daily pipeline picks them up automatically — `run_digest_pipeline` loops over saved searches by `source_id`, gets the registered source, calls `search_handler`

The only Adzuna-specific concern: the `reviewed_job_payload_from_ui_result()` adapter maps field names that all sources must populate. If an Adzuna result uses different keys, either normalise them in `adzuna_source.py`'s `search_handler` or make the adapter source-aware.

---

## 12. Dependencies on Other Work

| Dependency | Why | Status |
|---|---|---|
| MT-1 — Reed source extraction | Separates Reed UI logic before D3 pipeline is built; cleaner source boundary | ⬜ Pending |
| LT-1 — UI layer split | Digest handlers + render should go into clean layers, not the monolith | ⬜ Deferred |
| `job_hunt_index.py` D2 changes | All other D-phases depend on schema migration and `upsert_job` fix | Must be first |
| `CandidateProfile` prefs (D3) | D3 pipeline reads profile for threshold, LLM flag, max counts | Must be in D3 |

D1 and D2 have no dependency on MT-1 or LT-1 and can start independently.

---

## 13. Open Questions

- **Run time timezone:** `digest_run_time` uses `datetime.now()` (local time). Document this; if machine TZ changes, the run time shifts. Consider storing as UTC with a display conversion.
- **Machine offline at run time:** the scheduler simply misses the run (no catch-up). The "Run now" button is the recovery path.
- **Reed API rate limits:** 5 saved searches × 50 results = 250 API calls. Reed's documented limit is 1 request/second for authenticated calls. Add `time.sleep(0.25)` between result fetches if running multiple saved searches back-to-back.
- **LLM cost cap:** `digest_max_llm_per_run` (default 10) limits Gemini calls per run. Surfaced in Digest Settings UI so the user can tune it.
- **`source_job_id` availability:** `reed_job_to_ui_result()` currently stores the external ID in `source_snapshot_json` and as `source_job_id` in the result dict. Confirm this key name is stable before D2 dedup relies on it.
