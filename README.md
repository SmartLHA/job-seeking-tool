# Job Seeking Tool

Local-first UK job-search decision support and application preparation. It scores reviewed jobs deterministically, prepares truthful materials, tracks outcomes locally, and never auto-submits an application.

## Current implementation

- Split local UI: `src/job_hunt_ui.py` is a 19-line entry point over `ui_routes`, `ui_handlers`, `ui_render`, `ui_utils`, and `ui_state`.
- Generic source registry with Reed, Adzuna, and LinkedIn currently enabled. Reed (search, result selection, audit snapshots, full-detail enrichment, deduplication), Adzuna (search, selection, normalisation), and LinkedIn (public search scrape, SQLite cache, blocked-page detection, XSS-safe rendering) are wired end-to-end; batch evaluation and the review queue work across all sources.
- Deterministic Apply / Review / Skip decisions with seven weighted score components and categorical confidence.
- Source-quality gates, ATS readiness, and F1 per-job keyword coverage. Keyword coverage is advisory only and includes missing-keyword and anti-stuffing signals.
- Structured skills, safe URL ingestion, decision overrides, local JSON state, SQLite jobs/board index, board view, and outcome tracking.
- Decision-gated Tailor CV and Cover Letter actions on job detail pages. Output is markdown/text; DOCX/PDF export is not implemented.
- Optional Gemini job explanation is manually triggered and cannot alter score or decision.

## Run the UI

```bash
python3 -m src.job_hunt_ui \
  --profile data/mic_profile/candidate_profile.json \
  --state-root data/state \
  --report-dir output/reports \
  --host 127.0.0.1 \
  --port 9000
```

Open `http://127.0.0.1:9000`.

Required source credentials are read from the environment. Reed needs `REED_API_KEY`; Adzuna needs `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`; optional Gemini functions need `GOOGLE_API_KEY`. (`requests` and `python-dotenv` must be installed for the Python that runs the app — see `requirements-dev.txt`.)

## Route summary

| Area | Routes |
|---|---|
| Search | `GET /search/{source}`, `GET /search/{source}/more`, `POST /select/{source}`, `GET /sources` |
| Not-interested triage | `POST /jobs/not-interested` (hide), `POST /jobs/not-interested/undo` (undo/unhide), `GET /jobs/not-interested` (hidden list) |
| Review/evaluate | `POST /prefill`, `POST /job-submit`, `POST /evaluate`, `GET /job/<id>`, `GET /job/<id>/explain`, `GET /job/<id>/evaluate-form`, `GET /review-queue`, `POST /jobs/batch-evaluate` |
| Job actions | `POST /job/<id>/decision`, `POST /job/<id>/add-gap-skills`, `POST /job/<id>/ai-review-cv`, `POST /job/<id>/ats-recheck`, `POST /tailor`, `POST /cover-letter` |
| Board/outcomes | `GET /jobs`, `GET /board`, `GET /board/view`, `POST /jobs/save`, `POST /outcome` |
| Profile | `GET /profile`, `POST /profile/parse-cv`, `POST /profile/save` |
| Saved searches | `GET /saved-searches`, `POST /saved-searches`, `POST /saved-searches/{id}/delete`, `POST /saved-searches/{id}/toggle`, `POST /saved-searches/{id}/run-now` |
| Daily Digest | `GET /digest`, `GET /digest/count`, `POST /digest/mark-seen`, `POST /digest/reevaluate`, `GET /scheduler/status`, `POST /digest/run-llm-batch`, `GET /digest/llm-queue` |

## State and outputs

State is separated under the configured state root:

- `raw_inputs/`
- `reviewed_jobs/`
- `analyses/`
- `outcomes/`
- SQLite index: `job_hunt_index.db`

Reports are JSON/CSV. Tailored CVs are stored under `output/tailored_cvs/`; cover letters under `output/cover_letters/`.

## Tests

```bash
python3 -m pytest tests/test_ui.py -q
python3 -m pytest tests/test_keyword_match.py tests/test_evaluation.py tests/test_storage.py -q
```

After the recovery merge and original-posting-link update, the combined UI,
F1/evaluation, and storage regression set passed **99 tests** on 2026-06-22.

## Documentation

- [UI scope](docs/ui_scope.md)
- [Function list](docs/function_list.md)
- [Product specification](docs/product_spec.md)
- [Project TODO](PROJECT_TODO.md)
