# Job Seeking Tool

Local-first UK job-search decision support and application preparation. It scores reviewed jobs deterministically, prepares truthful materials, tracks outcomes locally, and never auto-submits an application.

## Current implementation

- Split local UI: `src/job_hunt_ui.py` is a 19-line entry point over `ui_routes`, `ui_handlers`, `ui_render`, `ui_utils`, and `ui_state`.
- Generic source registry with Reed, Adzuna, and LinkedIn currently enabled. Reed (search, result selection, audit snapshots, full-detail enrichment), Adzuna (search, selection, normalisation), and LinkedIn (public search scrape, SQLite cache, blocked-page detection, XSS-safe rendering) are wired end-to-end; batch evaluation and the review queue work across all sources.
- Search improvements (2026-07-22): a local relevance filter buckets clearly-unrelated titles into a collapsed "Other results" section (never drops them); results are deduplicated live, including across "Show more" pages; the keyword field accepts multiple comma-separated terms via chip/tag entry (one location + radius, capped at 6 sub-searches to protect free-tier rate limits).
- Deterministic Apply / Review / Skip decisions with seven weighted score components (switchable between 3 named presets — Balanced/Salary-focused/Skills-focused, persisted across restart) and categorical confidence.
- Source-quality gates, ATS readiness, and F1 per-job keyword coverage. Keyword coverage is advisory only and includes missing-keyword and anti-stuffing signals.
- Structured skills, safe URL ingestion, decision overrides, local JSON state, SQLite jobs/board index, an accessible stage-based Board View, and outcome tracking. The local UI binds only to loopback hosts and validates browser POST origins.
- New manual jobs follow one guided **Add & Evaluate** journey (paste or URL → review → save and score). The separate Advanced Review screen is retained for already-reviewed or amended job data; both routes use the same persistence/scoring pipeline.
- Decision-gated Tailor CV and Cover Letter actions on job detail pages. Tailored `Achievement:` claims must match a declared profile achievement; output is markdown/text and DOCX/PDF export is not implemented.
- Profile separates job-search preferences, evidence, CV upload, scoring, and digest settings. Local CV filesystem paths are never rendered in the browser.
- Optional Gemini job explanation is manually triggered and cannot alter score or decision.
- Career-ops absorption (2026-07-08/09): on-demand, LLM-judged qualitative assessment (culture fit, archetype alignment, red flags, posting-quality signals — advisory only), a deterministic A-F grade over the existing score (capped by the effective decision and by qualitative evidence, never raised), and a persisted batch-assessment queue for review-queue selections sharing the existing paced Gemini worker.

## Run the UI

Install dependencies in the project's virtual environment (from this directory):

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements-dev.txt
```

PDF CV extraction requires `pypdf>=6.19,<7`; DOCX CV extraction requires
`python-docx>=1.2,<2` (imported as `docx`). Both are included in the manifest.
TXT extraction uses Python's standard library. Missing extraction dependencies
produce an installation error. Format checks use synthetic files only:

```bash
venv/bin/python -m pytest tests/test_cv_format_dependencies.py
```

Then run the UI with that same environment:

```bash
venv/bin/python -m src.job_hunt_ui \
  --profile data/mic_profile/candidate_profile.json \
  --state-root data/state \
  --report-dir output/reports \
  --host 127.0.0.1 \
  --port 9000
```

Open `http://127.0.0.1:9000`.

Required source credentials are read from the environment. Reed needs `REED_API_KEY`; Adzuna needs `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`; optional Gemini functions need `GOOGLE_API_KEY`. (`requests` and `python-dotenv` must be installed for the Python that runs the app — see `requirements-dev.txt`.)

Local CV uploads extract text and suggest skills locally by default. The unchecked
cloud option explicitly permits sending up to 12,000 characters of CV text to
Gemini; other optional Gemini actions retain their own disclosures. Extracted
text is stored as `docs/master_cv.txt` within the selected profile. New saves
update the reference; existing legacy references and files are retained.

All UI requests require one valid loopback Host at the bound port. POST clients
must supply a matching Origin or Referer; headerless POST clients are rejected.
AI explanation is POST-only (GET returns 405 with `Allow: POST`). Search selections
have stable source/job identities and a maximum of 20; partial evaluation keeps
failed or changed selections for retry and links to successful results.
Cover letters are stored per profile and job; export includes only the active
profile's matching letter, with no legacy fallback.

For repair scope and verification limits, see the [audit remediation record](docs/tasks/audit-remediation-2026-10-04.md).

## Route summary

| Area | Routes |
|---|---|
| Search | `GET /search/{source}`, `GET /search/{source}/more`, `POST /select/{source}`, `GET /sources` |
| Not-interested triage | `POST /jobs/not-interested` (hide), `POST /jobs/not-interested/undo` (undo/unhide), `GET /jobs/not-interested` (hidden list) |
| Review/evaluate | `POST /prefill`, `POST /job-submit`, `POST /evaluate`, `GET /job/<id>`, `POST /job/<id>/explain`, `GET /job/<id>/evaluate-form`, `GET /review-queue`, `POST /jobs/batch-evaluate` |
| Job actions | `POST /job/<id>/decision`, `POST /job/<id>/add-gap-skills`, `POST /job/<id>/ai-review-cv`, `POST /job/<id>/ats-recheck`, `POST /tailor`, `POST /cover-letter`, `POST /job/<id>/qualitative-assess` |
| Batch qualitative assessment | `POST /jobs/batch-assess`, `GET /batch/<batch_id>`, `POST /batch/<batch_id>/cancel` |
| Board/outcomes | `GET /jobs`, `GET /board`, `GET /board/view`, `POST /jobs/save`, `POST /outcome` |
| Profile | `GET /profile`, `POST /profile/parse-cv`, `POST /profile/save`, `POST /scoring-preset` |
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

The Critical audit regression suite passed **167 tests** on 2026-07-27, including
live-browser Add Job and mobile viewport checks.

## Documentation

- [UI scope](docs/ui_scope.md)
- [Function list](docs/function_list.md)
- [Product specification](docs/product_spec.md)
- [Project TODO](PROJECT_TODO.md)
