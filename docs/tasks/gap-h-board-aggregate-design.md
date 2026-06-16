# GAP-H — Board/List Aggregate Read-Model + New Routes

**Status:** ✅ IMPLEMENTED 2026-06-16 — 267/267 tests green
**Date:** 2026-06-16

---

## Goal

The Tracker Kanban board and Find Jobs "Save" bookmark both need server-side aggregate views
over the stored per-record JSON files. Currently storage is per-id only — no list or board view exists.

---

## New Routes

### GET /jobs
Returns a list of all known jobs with their current stage and score.

```
GET /jobs
Response: {
  jobs: [
    {
      job_id: str,
      job_title: str,
      company: str,
      location: str | null,
      match_score: int | null,       # null if not yet evaluated
      decision: str | null,          # engine decision; null if not evaluated
      user_decision: str | null,     # override if set
      status: str,                   # current OutcomeStatus
      updated_at: str,               # ISO timestamp of last outcome update
      tailoring_ready: bool | null,
      ats_score: int | null
    },
    ...
  ]
}
```

### GET /board
Returns jobs grouped by OutcomeStatus for the Kanban board.

```
GET /board
Response: {
  columns: {
    "not_applied": [ ...job cards... ],
    "applied":     [ ...job cards... ],
    "interview":   [ ...job cards... ],
    "offer":       [ ...job cards... ],
    "rejected":    [ ...job cards... ],
    "withdrawn":   [ ...job cards... ]
  },
  stats: {
    active: int,         # not in rejected or withdrawn
    interviews: int,
    offers: int,
    response_rate: float # (interview+offer) / (applied+interview+offer+rejected)
  }
}
```

Each job card in columns uses the same shape as the `/jobs` list item above.

### POST /jobs/save
Bookmark a job from Find Jobs without evaluating. Creates a `not_applied` outcome record
and saves a minimal reviewed job stub for display on the board.

```
POST /jobs/save
Body: {
  job_title: str,
  company: str,
  location?: str,
  source?: str,          # "Reed" | "Adzuna" | "LinkedIn"
  source_ref?: str,      # original job URL or ID
  salary_min_gbp?: int,
  salary_max_gbp?: int,
  description_raw?: str
}
Response: {
  job_id: str,
  status: "not_applied"
}
```

Handler:
1. Generate a `job_id`
2. `create_outcome_record(job_id, status="not_applied")` → save to `outcomes/`
3. Save a minimal `JobPosting` stub to `reviewed_jobs/` (unevaluated; `match_score = null`)
4. Return `{job_id, status}`

---

## Read-Model: SQLite Index

**Decision 2026-06-16:** Use SQLite as a query index. JSON files remain the authoritative source
of truth. SQLite is the read layer for `/board` and `/jobs`.

### New module: src/job_hunt_index.py

Owns the SQLite schema, upsert functions, query functions, and rebuild logic.

```sql
CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT PRIMARY KEY,
    job_title       TEXT,
    company         TEXT,
    location        TEXT,
    source          TEXT,
    match_score     INTEGER,        -- NULL if not yet evaluated
    decision        TEXT,           -- engine decision; NULL if not evaluated
    user_decision   TEXT,           -- user override; NULL if not overridden
    ats_score       INTEGER,        -- NULL if not evaluated or no CV
    tailoring_ready INTEGER,        -- 0 or 1
    status          TEXT NOT NULL,  -- OutcomeStatus value
    updated_at      TEXT,           -- ISO timestamp
    salary_min      INTEGER,
    salary_max      INTEGER
);
```

### Write path

Every operation that changes a job updates **JSON first, then SQLite**:

| Operation | JSON written | SQLite upserted |
|-----------|-------------|-----------------|
| `POST /jobs/save` | `reviewed_jobs/<id>.json` + `outcomes/<id>.json` | INSERT row with `status=not_applied`, scores NULL |
| `POST /evaluate` | `analyses/<id>.json` | UPDATE row with score/decision/tailoring_ready |
| `POST /outcome` | `outcomes/<id>.json` | UPDATE row with new status + updated_at |
| `POST /job/<id>/decision` | `analyses/<id>.json` | UPDATE user_decision |

### Read path

`GET /board` and `GET /jobs` query SQLite directly — no file scanning.

### Startup rebuild

On app startup, if `job_hunt_index.db` is missing or corrupt:
```python
def rebuild_index(storage_layout: StorageLayout, db_path: Path) -> None:
    """Scan JSON files and repopulate SQLite from source of truth."""
    ...
```

This ensures the index can always be reconstructed from the JSON files.

---

## Transition Constraint (from GAP-A)

The Tracker UI must only allow DnD moves that are valid per `_ALLOWED_TRANSITIONS`.
The `POST /outcome` route already enforces this server-side via `update_outcome()`.
The UI must additionally grey out invalid column targets when dragging a card.

The board endpoint returns `allowed_transitions` per card to let the UI know what is legal:

```json
{
  "job_id": "abc123",
  "status": "applied",
  "allowed_transitions": ["interview", "rejected", "withdrawn"],
  ...
}
```

---

## Files to Change

| File | Change |
|------|--------|
| `src/job_hunt_index.py` | **New** — SQLite schema, `upsert_job()`, `query_board()`, `query_jobs_list()`, `rebuild_index()` |
| `src/job_hunt_ui.py` | Add `GET /jobs`, `GET /board`, `POST /jobs/save` routes; call index functions; rebuild index on startup if missing |
| `src/job_hunt_orchestrator.py` | After `save_reviewed_job()` + `save_job_analysis()` (lines 106-108), call `upsert_job()` — this is where evaluation JSON writes actually happen |
| `src/job_hunt_ui.py` | After `save_application_outcome()` (line 586), call `upsert_job()` — this is where outcome JSON writes actually happen |
| `tests/test_index.py` | **New** — SQLite upsert, query, rebuild tests with mixed evaluated/unevaluated jobs |
| `tests/test_ui.py` | Tests for all three new routes: empty board, mixed states, save-without-evaluate |

---

## Acceptance Criteria

1. `GET /jobs` returns all jobs across `outcomes/` with correct status and score (null if unevaluated)
2. `GET /board` returns jobs grouped by the 6 `OutcomeStatus` values
3. `GET /board` includes `allowed_transitions` per card
4. `GET /board` returns correct `stats` (active, interviews, offers, response_rate)
5. `POST /jobs/save` creates an `outcomes/<job_id>.json` with `status: not_applied`
6. `POST /jobs/save` creates a minimal `reviewed_jobs/<job_id>.json` stub
7. Saved-but-not-evaluated jobs appear in the `not_applied` board column with `match_score: null`
8. Board scan handles missing analysis files gracefully (unevaluated jobs)

---

## Test Command

```bash
python3 -m pytest tests/test_index.py tests/test_storage.py tests/test_ui.py -v
```
