# Job Seeking Tool

Local-first job-search decision support and application prep tool for the UK market.

## What it does

- Search Reed (and other configured sources) for jobs
- Evaluate job fit with deterministic scoring → Apply / Review / Skip
- Tailor CV to a specific job (LLM-assisted, truth-only)
- Generate a cover letter (configurable tone, length, key points)
- Track application outcomes locally
- Board view of all evaluated jobs

## How to run

```bash
cd "/Users/lhaclaw/AI-Project-Workspace/job_hunt_Job Seeking Tool"
PYTHONPATH=. python3 src/job_hunt_ui.py \
  --profile data/mic_profile.json \
  --state-root data/state \
  --report-dir output/reports \
  --host 127.0.0.1 \
  --port 9000
```

Then open: **http://127.0.0.1:9000**

## Features

| Feature | Status |
|---|---|
| Find Jobs tab — search across enabled sources | ✅ |
| Evaluate tab — review fields, run scoring | ✅ |
| Add Job tab — paste text or URL to ingest a job | ✅ |
| History tab — recent evaluated jobs | ✅ |
| Board View — kanban-style overview at `/board/view` | ✅ |
| My Profile tab — view / edit candidate profile | ✅ |
| Tailor CV — Actions section on job detail page | ✅ |
| Cover Letter — form on job detail page | ✅ |
| Outcome tracking — record apply / interview / reject | ✅ |
| Auto-apply / browser automation | ❌ never |

## UI

Warm paper style (`#F1EDE4` background, Schibsted Grotesk font), left sidebar navigation, coloured decision badges (Apply / Review / Skip), score pills.

## Route reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Main app shell (tabs: search, evaluate, add_job, history) |
| GET | `/sources` | Returns enabled job sources from config (JSON) |
| GET | `/board` | Board data (JSON) |
| GET | `/board/view` | Board HTML page |
| GET | `/profile` | Profile tab page |
| POST | `/evaluate` | Run evaluation on a reviewed job payload |
| POST | `/jobs/save` | Save a job (accepts `source_type` or `source`) |
| POST | `/tailor` | Tailor CV for a job (`job_id`, `manual_selected`) |
| POST | `/cover-letter` | Generate cover letter (`job_id`, `why_company_text`, `tone`, `length`, `points`) |
| POST | `/outcome` | Record application outcome |
| POST | `/profile/save` | Save updated profile |
| POST | `/profile/parse-cv` | Parse uploaded CV file into profile fields |

## Outputs

| Path | Contents |
|---|---|
| `data/state/reviewed_jobs/` | Structured job records |
| `data/state/analyses/` | Scoring and decision results |
| `data/state/raw_inputs/` | Raw ingestion payloads |
| `output/reports/` | JSON/CSV reports |
| `output/tailored_cvs/` | Tailored CV drafts |
| `output/cover_letters/` | Cover letter drafts |

## Tests

```bash
PYTHONPATH=. python3 -m pytest
```

## Known limitations

- Reed is the primary wired search source; other sources depend on config
- CV tailoring and cover letter generation require an LLM API key in env
- `/board` returns JSON; the HTML view is at `/board/view`
- Profile unknown fields are currently rejected on load
- No auto-apply, no remote data storage, no browser automation

## Architecture notes

See `PROJECT_CONTEXT.md` and `docs/architecture_guardrails.md` for guardrails.
Key principle: deterministic scoring first, LLM only for tailoring/cover letter generation.

---

## CHANGELOG

### 2026-06-18

- **New UI** — warm paper style (`#F1EDE4`), Schibsted Grotesk font, left sidebar nav with: Find Jobs / Evaluate / Add Job / History / My Profile / Board View; coloured decision badges; score pills
- **Tailor CV** — new "Actions" section on job detail page; `POST /tailor` with `job_id`
- **Cover Letter** — form on job detail page; `POST /cover-letter` with `job_id`, `why_company_text`, `tone`, `length`, `points`
- **Board View** — new sidebar nav item; `/board/view` returns full HTML page
- **`/sources` wiring** — Find Jobs tab now dynamically reflects enabled sources from config
- **Field name fix** — `/jobs/save` now accepts both `source_type` and `source`
