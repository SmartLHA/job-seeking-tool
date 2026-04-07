# Job Seeking Tool

Local-first job-search decision support for the UK market.

Current focus:
- load a candidate profile
- load a reviewed job JSON
- run deterministic evaluation
- save reviewed job and analysis separately
- export simple JSON/CSV reports
- keep outcomes tracking local

This is an early local-first foundation with a lightweight CLI and a very small localhost UI shell.

## Current status

Implemented now:
- candidate profile loading and validation
- master CV reference checking
- reviewed job input normalization
- deterministic scoring
- Apply / Review / Skip decisioning
- evaluation flow composition
- local state storage with separation between raw inputs, reviewed jobs, analyses, and outcomes
- JSON/CSV report export
- basic outcomes tracking
- lightweight CLI entrypoint
- minimal localhost browser UI for one-job evaluation and outcome tracking
- local project docs viewer under `viewer/`

Not implemented yet:
- broad ingestion/parsing
- richer/final product UI
- CV tailoring flow
- cover letters
- auto-apply or browser automation

## Repo shape

Main code lives in `src/`.

Key modules currently in use:
- `src/profile.py`
- `src/reviewed_input.py`
- `src/scoring.py`
- `src/decision.py`
- `src/evaluation.py`
- `src/storage.py`
- `src/reporting.py`
- `src/outcomes.py`
- `src/orchestrator.py`
- `src/main.py`

Tests live in `tests/`.

## CLI usage

Current entrypoint:

```bash
python3 -m src.main \
  --profile path/to/candidate_profile.json \
  --reviewed-job path/to/reviewed_job.json
```

Optional flags:

```bash
python3 -m src.main \
  --profile path/to/candidate_profile.json \
  --reviewed-job path/to/reviewed_job.json \
  --state-root data/state \
  --report-dir output/reports \
  --raw-input path/to/raw_input.json \
  --raw-input-id raw-job-001
```

Arguments:
- `--profile`: candidate profile JSON file
- `--reviewed-job`: reviewed job JSON file used for evaluation
- `--state-root`: local storage root for raw/reviewed/analysis state, default `data/state`
- `--report-dir`: JSON/CSV report output directory, default `output/reports`
- `--raw-input`: optional raw input JSON stored separately for auditability
- `--raw-input-id`: optional raw input record id, defaults to the reviewed job id

On success, the CLI prints a short summary including:
- job title and company
- decision
- match score
- confidence
- saved reviewed job path
- saved analysis path
- generated JSON/CSV report paths

If the profile includes `master_cv_ref`, the CLI also checks that the referenced local file exists and is readable.

## Expected input shape

### Candidate profile JSON

The profile loader expects a JSON object with fields such as:
- `candidate_id`
- `name`
- `target_roles`
- `locations`
- `remote_preference`
- `salary_floor_gbp`
- `right_to_work_uk`
- `skills`
- `years_experience`
- `industries`
- `achievements`
- `certifications`
- `master_cv_ref` (optional)

Unknown profile fields are currently rejected.

### Reviewed job JSON

A reviewed job should be a JSON object with the structured fields needed for evaluation.
A working example exists at:
- `input/reviewed_job_demo.json`

Typical fields include:
- `job_id`
- `job_title`
- `company`
- `description_raw`
- `source_type`
- `source_ref`
- `location`
- `work_mode`
- `employment_type`
- `required_skills`
- `preferred_skills`
- `required_years_experience`
- `nice_to_have_years_experience`
- `domain`
- `notes`
- `salary_min_gbp`
- `salary_max_gbp`

## Example run

From the repo root:

```bash
python3 -m src.main \
  --profile /path/to/candidate_profile.json \
  --reviewed-job input/reviewed_job_demo.json
```

## Minimal local UI

A very small browser UI is now available for the current one-job workflow.
It stays intentionally thin and local-first:
- enter URL or copied-text context
- review/edit the structured fields used for scoring
- run evaluation and save results locally
- inspect score, blockers, strengths, gaps, and decision
- record a basic local outcome status
- review recent evaluated jobs

Start it with:

```bash
python3 -m src.ui \
  --profile /path/to/candidate_profile.json
```

Optional flags:

```bash
python3 -m src.ui \
  --profile /path/to/candidate_profile.json \
  --state-root data/state \
  --report-dir output/reports \
  --host 127.0.0.1 \
  --port 8765
```

Then open:

```text
http://127.0.0.1:8765
```

## Outputs

A successful run currently writes:
- reviewed job JSON under `data/state/reviewed_jobs/`
- job analysis JSON under `data/state/analyses/`
- optional raw input JSON under `data/state/raw_inputs/`
- report JSON and CSV under `output/reports/`

Outcome records are stored separately under the outcomes state when that flow is used.

## Tests

Run the current test suite with:

```bash
python3 -m pytest
```

## Notes

This repo follows the project guardrails in:
- `PROJECT_CONTEXT.md`
- `docs/architecture_guardrails.md`
- `docs/development_sequence.md`
- `docs/development_rules.md`

The product name is still undecided, so documentation should stay neutral.
