<!-- STATUS: approved 2026-10-11 (Mike: "approve the test as it stands"); build in progress -->
# Nimble blind check — spec (2026-10-11)

## Goal
Find out whether the local Nimble 9B decision model judges job ads the way Mike does,
before connecting it to any app feature. Mike labels stored jobs blind with two yes/no
questions; Nimble answers the same two questions; a report shows agreement.
No change to the app. No Gemini calls.

## Background
- Nimble runs in Ollama on this Mac: model `nimble:9b-q4_K_M`,
  `POST http://127.0.0.1:11434/v1/systemone`.
- Request: `{"model", "state": <text>, "questions": {<name>: {"type": "choice"|"noul"|"score",
  "instructions": <text>, "criteria": ...}}, "keep_alive": "30m"}`. `criteria` is required
  for choice (object option -> description) and score (array of level texts, lowest
  first, 2-26 levels); optional for noul.
- Response: `{"model", "answers": {<name>: {...}}, "usage": {"input_tokens", "output_tokens"}}`.
  noul -> `{"type":"noul","noul": float 0-1}` (treated as P(yes)).
  score -> `{"type":"score","score": float expected value over ZERO-BASED levels,
  "legend": {"0": ...}, "probabilities": {"0": ...}, "confidence"}`.
  choice -> `{"type":"choice","choice": key, "probabilities": {...}, "confidence"}`.
- Unknown model -> HTTP 404 JSON `{"error": "model \"x\" not found, try pulling it first"}`.
- Context limit 8,192 tokens (job text + all questions). Request body max 64 KiB.
- Why not switch the qualitative assessment now: see the design discussion summarised in
  PROJECT_LOG.md (2026-10-11 entry).

## Scope
New files only:
- `scripts/nimble_check.py` with two commands:
  - `export`: writes `archive/nimble-check/labels.csv`.
  - `run`: calls Nimble and writes `archive/nimble-check/report-<YYYY-MM-DD>.md`.
- `tests/test_nimble_check.py`.
Plus one PROJECT_LOG.md entry and an INDEX.md Feature Map row (docs checklist).

## Job selection (`export`)
- Source: `data/state/reviewed_jobs/*.json`, field `description_raw`.
- All jobs with JD length 1,000-14,000 chars (30 today), plus 5 stub jobs
  (JD <= 520 chars), excluding files whose names start with `demo-`, `test-` or `edge-`.
  Stub pick must be deterministic (e.g. first 5 by job_id).
- Jobs over 14,000 chars are excluded at export so Mike never labels a job `run` skips.
- CSV columns: job_id, title, company, jd_chars, base_grade, decision, link,
  RF (blank), CU (blank).
  - base_grade: from the existing deterministic grade function in
    src/job_hunt_qualitative.py (base grade from match_score) using the stored analysis.
  - decision: the job's stored effective decision (apply / review / skip).
  - link: the local job page URL used by the app's UI.
- The two questions are frozen as module constants, taken from the existing red_flags
  and culture_signals rubric in src/job_hunt_qualitative.py, and printed in comment
  lines at the top of the CSV:
  - RF: does this job ad show material red flags?
  - CU: does the ad's culture or working style clash with what the role requires?
- `export` refuses to overwrite an existing labels.csv unless `--force`.

## Nimble call (`run`)
- Reads labels.csv; one request per job; state = the JD text.
- Questions: `rf` (noul) and `cu` (noul) with the SAME frozen wording (these are the
  test); plus the 4 dimension `score` questions (seniority_fit, culture_signals,
  red_flags, role_archetype_alignment; 5 levels, levels 1/3/5 from the existing rubric,
  2/4 "between" wording) and posting tier `choice` (high_confidence / unknown_caution /
  suspicious) — display only, marked "unvalidated" in the report.
- Threshold for "Nimble yes": noul >= 0.5 (constant, set before any live run).
- Records per job: both noul values, the 4 scores (shown on the 1-5 scale = zero-based
  level + 1, column names say so), tier, input_tokens, latency, model digest
  (from `GET /api/tags`). Flags rows with input_tokens > 7,000.
- Resume: results cached per job under `archive/nimble-check/results/<job_id>.json`;
  a re-run skips jobs already done unless `--force`.
- Errors: connection refused -> stop with a clear "Is Ollama running?" message;
  model not found -> stop with a clear message; other per-job HTTP errors -> recorded
  in the report as errors, run continues.
- `run --smoke`: sends ONE built-in sample JD (not a stored job), prints answer keys,
  input_tokens and latency only. Used to confirm the live API shape.

## Report
- Header: "Indicative - small sample", date, model digest, threshold.
- For RF and CU separately: counts of owner yes / Nimble yes / both / neither /
  unlabelled. A question with fewer than 3 owner "yes" is reported "not tested".
- List by name every job with base grade A or B where Nimble says yes but Mike says no
  (the harmful case).
- Stub rows in a separate section.
- Per-job table with all recorded fields. Blank or invalid labels are reported, never guessed.

## Hard constraints
- Never write under `data/`. Never open the SQLite database. Do not call app storage
  helpers that create directories or files (e.g. `ensure_storage_layout`, `open_db`);
  read JSON files directly. Pure functions from src/ may be imported.
- No new Python packages (use `requests`, already a dependency).
- pytest never makes live HTTP calls (mock `requests`).
- Nothing new at project root.

## Acceptance criteria
1. `tests/test_nimble_check.py` passes and covers: request building (incl. empty
   target_roles not breaking anything), response parsing (noul, score zero-based -> 1-5,
   choice), connection refused, model not found, other HTTP error recorded, label CSV
   parsing (blank / invalid reported), join labels to results by job_id, count logic at
   the 0.5 boundary, "not tested" rule (<3 owner yes), harmful-case list, resume skips
   done jobs, export selection (length bands, fixture exclusion, deterministic stubs,
   >14,000 excluded), export refuses overwrite without --force.
2. Existing qualitative tests still pass: `tests/test_qualitative.py`.
3. `export` runs on the real stored jobs and writes labels.csv with 35 rows (30 + 5).
4. `run --smoke` succeeds against the live local Nimble.
5. No file under `data/` changed (before/after mtime listing).

## Stop conditions
- Live API shape differs from Background -> stop, report.
- Any need to write under data/, open the DB, or add a package -> stop, ask.
