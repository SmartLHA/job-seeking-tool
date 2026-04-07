# Project Index

**For agents only** — which file to read for any given task. Updated as files are reviewed.
Used by SilverHand to brief Handy/Scout precisely, and by any agent to orient quickly.
**Not a product document** — it's an internal reference, not user-facing.

---

## Core Project Docs

| File | Purpose |
|------|---------|
| `PROJECT_CONTEXT.md` | Master project memory: direction, constraints, architecture, progress, next steps. Start here. |
| `PROJECT_LOG.md` | Dated history of all decisions, discussions, and implementation milestones. |
| `README.md` | CLI usage, UI startup, repo structure, expected input shapes, test commands. |

---

## Planning Docs (`docs/`)

| File | Purpose |
|------|---------|
| `docs/product_spec.md` | What the product is, MVP scope, goals/non-goals, user stories. |
| `docs/function_list.md` | All planned modules and their responsibilities. |
| `docs/development_sequence.md` | Phased build order (Phase 0–8). |
| `docs/development_rules.md` | Non-negotiable build rules: local-first, truthful output, deterministic-first, tests. |
| `docs/data_contract.md` | MVP data shapes — JobPosting, JobAnalysis, blockers, score breakdown. |
| `docs/ui_scope.md` | Minimal local UI definition, workflow boundaries, what's excluded. |
| `docs/architecture_guardrails.md` | Pre-implementation architecture discipline: state separation, module boundaries, policy config principles. |
| `docs/team_protocol.yaml` | Multi-agent team protocol: SilverHand/Handy/Scout roles, anti-idle rule, QA modes. |

---

## Source Code (`src/`)

| File | Purpose |
|------|---------|
| `src/models.py` | All dataclass models: `CandidateProfile`, `JobPosting`, `Blocker`, `RiskFlag`, `ScoreComponent`, `ScoreBreakdown`, `JobAnalysis`, `OutcomeEvent`, `ApplicationOutcome`. Validation in each model's `__post_init__`. `Decision = Literal["apply","review","skip"]`. `ConfidenceLevel = Literal["low","medium","high"]`. `OutcomeStatus = Literal["not_applied","applied","interview","rejected","offer","withdrawn"]`. |
| `src/config.py` | All tunable policy objects: `ScoringWeights` (skills_required=35, preferred=5, experience=20, location/salary/domain/work_mode=10 each), `ConfidencePolicy`, `ScoringPolicy`, `DecisionPolicy`. Apply threshold ≥80; review threshold ≥65; blockers always skip; `missing-required-skills` and `salary-below-floor` are critical risks gating apply. |
| `src/scoring.py` | `score_job(profile, job, policy)` → `ScoringResult`. 7-component weighted scoring: required skills (35pt), preferred skills (5pt), experience (20pt), location (10pt), salary (10pt), domain (10pt), work mode (10pt). Confidence (high/medium/low) derived independently from data completeness — NOT from score. Unknown fields get neutral credit but reduce confidence. Risk flags (`missing-required-skills`, `missing-preferred-skills`, `salary-below-floor`) built here. |
| `src/decision.py` | `decide_application(score, blockers, risk_flags, policy)` → `DecisionResult`. Priority: blockers → skip; score ≥80 + no critical risks → apply; score 65-79 → review; critical risks present → review (even with high score); else → skip. |
| `src/profile.py` | `load_candidate_profile(path)` / `save_candidate_profile(profile, path)`. `load_master_cv(path)` / `save_master_cv(content, path)`. `resolve_master_cv_path(profile, profile_path)` for relative-path resolution. `ProfileValidationError` on bad input. Unknown extra fields rejected. Master CV existence checked on load if `master_cv_ref` set. |
| `src/reviewed_input.py` | `reviewed_job_from_dict(payload, job_id)` → `JobPosting`. Converts pre-reviewed job JSON into typed model. Unknown extra fields rejected. Skill lists deduplicated case-insensitively. `ReviewedInputValidationError` on bad input. `reviewed_job_to_dict(job)` for round-trip. |
| `src/storage.py` | `ensure_storage_layout(root)` → `StorageLayout`. Four folders: `raw_inputs/`, `reviewed_jobs/`, `analyses/`, `outcomes/`. `save/load_reviewed_job`, `save/load_job_analysis`, `save/load_raw_input`, `save/load_application_outcome`. `job_analysis_to_dict/from_dict` for typed↔dict conversion. `StorageError` on bad storage data. |
| `src/evaluation.py` | `evaluate_reviewed_job(profile, job, scoring_policy, decision_policy)` → `JobAnalysis`. Composes `score_job()` + `decide_application()`. Sets `tailoring_ready` from decision (apply=True, review/manual-review=not yet). Sets `confidence` from scoring result. Injects blockers if provided externally. |
| `src/outcomes.py` | `create_outcome(job_id, status, notes)` → `ApplicationOutcome`. `update_outcome(outcome, status, notes)` → new outcome with history entry. `OutcomeValidationError` if status not in `OutcomeStatus`. Transition validation ensures current status matches latest history event. `outcome_to_dict` / `outcome_from_dict` for persistence. |
| `src/reporting.py` | `build_report_rows(jobs, analyses, outcomes)` → flat list of row dicts per job. `summarize_decisions(analyses)` → count of apply/review/skip. `export_report_json(rows, output_path)` / `export_report_csv(rows, output_path)`. CSV includes: job_id, job_title, company, match_score, confidence, decision, blockers, strengths, missing_skills. |
| `src/orchestrator.py` | `run_evaluation(profile_path, reviewed_job_path, ...)` → full pipeline result. Loads profile + reviewed job → evaluates → saves reviewed job, analysis, optional raw input → generates reports. Also `submit_reviewed_job(profile_path, job_payload)` for UI: accepts unvalidated dict, converts to reviewed job, evaluates, stores, returns analysis. |
| `src/main.py` | CLI entrypoint using `argparse`. `--profile` (required), `--reviewed-job` (required), `--state-root` (default `data/state`), `--report-dir` (default `output/reports`), `--raw-input`, `--raw-input-id`. Prints summary on success (job title, company, decision, score, confidence, paths). Exits non-zero on validation/evaluation errors. |
| `src/ui.py` | Localhost browser UI using stdlib `http.server` + `socketserver`. No external frameworks. Endpoints: `GET /` (home with form + recent jobs list), `POST /evaluate` (submit reviewed job payload → `submit_reviewed_job`), `GET /job/<id>` (load analysis from storage), `POST /outcome` (record outcome). HTML rendered inline as template strings. Run: `python3 -m src.ui --profile <path> --port 8765`. |

---

## Tests (`tests/`)

| File | Tests |
|------|-------|
| `tests/test_models.py` | Model construction, validation guardrails (empty required fields, salary range, score bounds). |
| `tests/test_scoring.py` | Component scoring, confidence derivation, risk flag generation. |
| `tests/test_decision.py` | Blocker skip, apply threshold, review threshold, critical risk gating. |
| `tests/test_profile.py` | Valid/invalid profile loading, failure cases, round-trip, CV file handling. |
| `tests/test_reviewed_input.py` | Reviewed-input normalization, unknown handling, round-trip conversion. |
| `tests/test_storage.py` | Storage layout, round-trips, state separation, invalid payload handling. |
| `tests/test_evaluation.py` | Apply/review/skip evaluation flow, confidence-vs-score behavior. |
| `tests/test_outcomes.py` | Outcome creation, updates, validation, persistence, layout. |
| `tests/test_reporting.py` | Row building, summary counts, JSON/CSV export. |
| `tests/test_orchestrator.py` | Orchestration flow, reviewed job submission. |
| `tests/test_main.py` | CLI argument handling, exit codes, output. |
| `tests/test_integration_flow.py` | End-to-end integration: profile → reviewed job → evaluation → storage → reporting → outcomes. |
| `tests/test_ui.py` | UI request handling: GET `/`, POST `/evaluate`, validation failures, GET `/job`, POST `/outcome`. |

---

## Sample Inputs (`input/`)

| File | Purpose |
|------|---------|
| `input/reviewed_job_demo.json` | Standard demo reviewed job. |
| `input/reviewed_job_gap.json` | Required-skill gap → review decision. |
| `input/reviewed_job_salary_miss.json` | Salary below floor → review decision. |
| `input/reviewed_job_sparse.json` | Missing/unknown fields → low confidence. |
| `input/reviewed_job_invalid.json` | Invalid payload → clean failure. |

---

## Other

| File | Purpose |
|------|---------|
| `viewer/app.js` | Docs viewer JS — section extraction, markdown rendering, dashboard card summaries. |
| `viewer/documents.json` | Manifest of docs shown in the viewer. Update here to add docs to the viewer. |
| `viewer/viewer.sh` | Start/stop/status/restart script for the docs HTTP server. |

---

## What to Read for Common Tasks

- **Understand the product** → `PROJECT_CONTEXT.md`
- **Check progress/history** → `PROJECT_LOG.md`
- **Run the CLI** → `README.md` + `src/main.py --help`
- **Run the UI** → `README.md` + `src/ui.py`
- **Understand scoring** → `src/scoring.py` + `src/config.py` (start with `score_job()` and `ScoringWeights`)
- **Understand decisioning** → `src/decision.py` + `src/config.py` (start with `decide_application()` and `DecisionPolicy`)
- **Change data shapes** → `src/models.py` + `docs/data_contract.md`
- **Change policy thresholds** → `src/config.py` only — all weights, thresholds, critical risks are there
- **Add a new module** → `docs/function_list.md` + `docs/architecture_guardrails.md`
- **Understand the evaluation flow** → `src/evaluation.py` (wires scoring + decision)
- **Understand the CLI orchestration** → `src/orchestrator.py` + `src/main.py`
- **Understand the UI** → `src/ui.py` (endpoint routing + form handling)
- **Write tests** → any `tests/test_*.py` for the pattern
- **Browse docs visually** → `http://localhost:8765/viewer/`

## Data Flow (one job run)

```
Profile JSON          Reviewed Job JSON
      │                       │
      ▼                       ▼
profile.py         reviewed_input.py
(CandidateProfile)  (JobPosting)
      │                       │
      └───────────┬───────────┘
                  ▼
           evaluation.py
           ┌─────┴─────┐
           ▼           ▼
      scoring.py  decision.py
      (ScoringResult) (DecisionResult)
           │           │
           └─────┬─────┘
                 ▼
            JobAnalysis
             (model)
                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
   storage.py reporting.py outcomes.py
 (saved JSON) (JSON/CSV) (outcome record)
```

## Key Invariants

- Raw input, reviewed job, and analysis are stored **separately** — none overwrites the other
- `match_score` and `confidence` are **independent** — score is fit, confidence is data completeness
- Blockers always produce `skip` — no score threshold can override a blocker
- Tailoring is only set `tailoring_ready=True` on `apply` decisions — review jobs must be manually shortlisted
- Unknown fields in scoring get **neutral credit** (don't penalise score) but **reduce confidence**
