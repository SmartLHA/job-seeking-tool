# PROJECT_CONTEXT.md

## Project Overview

This project folder is for a medium-to-large software product build: a **local-first AI job search decision-support and application-preparation product for the UK market**.

This product is intended to help a UK-based job seeker:
- ingest jobs
- structure job data
- score job fit
- decide Apply / Review / Skip
- generate truthful tailored CVs and cover letters
- track outcomes over time

It is **not** intended to be:
- a mass auto-apply bot
- browser automation
- background account interaction
- a speculative/fabricating CV writer
- an application-volume maximizer

## Product Naming Status

- `JOB Smart` was discussed earlier but is **not the final product name**.
- Mic confirmed it should **not** be used because the name is already used by others.
- Current project folder name is **`Job Seeking Tool`**.
- Until a final public product name is confirmed, use neutral references such as:
  - "the product"
  - "the job-search copilot product"
  - "the local-first job application copilot"

## Product Priorities

The product must prioritize:
- deterministic logic first
- explainability
- local-first privacy
- truthful output
- modular code
- small testable steps

## Core Positioning

Build a local AI job application copilot for decision support and preparation.

Optimize for:
- interview rate
- application quality
- decision clarity
- time saved

Do **not** optimize for:
- raw application volume

## Development Principles

1. Deterministic before LLM
   - scoring, decision rules, blockers, deduplication, storage, and reports should be deterministic Python logic first
   - LLM use should be limited to:
     - parsing fallback
     - CV tailoring
     - cover letter drafting
     - concise summaries

2. Truthfulness
   - never invent skills, tools, years, titles, projects, certifications, achievements, or metrics
   - generated content must only use approved facts

3. Local-first
   - local JSON / JSONL / SQLite preferred
   - no cloud dependence for core workflows
   - preserve local audit trail

4. Human approval required
   - no final job submission
   - no autonomous apply action

5. Small scoped changes
   - avoid unrelated refactors
   - avoid architecture churn without reason

6. Test-first mindset
   - every core logic module needs tests
   - bad input must not break the pipeline

## Technical Direction

Default stack unless Mic changes it:
- Python
- SQLite + JSON/JSONL
- macOS (Mac mini)
- local CLI-first MVP
- no UI required in early phases
- local cron-compatible scheduling
- light dependencies
- env vars + config file
- pytest
- black + ruff
- practical type hints

Avoid heavy frameworks early.

## Proposed Repo Structure

```text
Job Seeking Tool/
├── PROJECT_CONTEXT.md
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
├── docs/
│   ├── product_spec.md
│   ├── function_list.md
│   ├── development_sequence.md
│   └── development_rules.md
├── data/
│   ├── candidate_profile.json
│   ├── cv_master.md
│   ├── sample_jobs.jsonl
│   └── outcomes.jsonl
├── output/
│   ├── reports/
│   ├── tailored_cvs/
│   └── cover_letters/
├── logs/
├── src/
│   ├── models.py
│   ├── config.py
│   ├── storage.py
│   ├── profile.py
│   ├── ingestion.py
│   ├── parsing.py
│   ├── eligibility.py
│   ├── scoring.py
│   ├── decision.py
│   ├── tailoring.py
│   ├── cover_letter.py
│   ├── reporting.py
│   ├── outcomes.py
│   ├── orchestrator.py
│   └── main.py
└── tests/
    ├── test_profile.py
    ├── test_ingestion.py
    ├── test_parsing.py
    ├── test_eligibility.py
    ├── test_scoring.py
    ├── test_decision.py
    └── test_orchestrator.py
```

## Core Domain Objects

### CandidateProfile
Fields expected:
- name
- target_roles
- locations
- remote_preference
- salary_floor_gbp
- right_to_work_uk
- skills
- years_experience
- industries
- achievements
- certifications

### JobPosting
Fields expected:
- id
- source
- job_title
- company
- location
- work_mode
- salary_min_gbp
- salary_max_gbp
- employment_type
- description
- required_skills
- preferred_skills
- required_years_experience
- domain
- url

### JobAnalysis
Fields expected:
- job_id
- match_score
- score_breakdown
- missing_required_skills
- missing_preferred_skills
- strengths
- risk_flags
- blockers
- decision
- confidence

### ApplicationOutcome
Fields expected:
- job_id
- applied
- applied_at
- status
- notes
- cv_version
- cover_letter_version

## Architecture Guardrails

Before implementation starts, preserve these boundaries:

1. Separate raw input, reviewed structured job data, and derived analysis
   - raw source should remain stored separately from the reviewed structured record
   - analysis output should remain a derived layer, not overwrite the reviewed input

2. Keep evaluation stages separate
   - `eligibility.py` handles blockers / hard constraints
   - `scoring.py` handles explainable scoring contributions
   - `decision.py` converts blockers + score + risks into Apply / Review / Skip

3. Keep lightweight input lightweight
   - input normalization should remain small
   - do not let MVP input handling turn into crawling, batch import, or broad source-specific parsing

4. Keep tailoring downstream
   - tailoring should consume approved candidate facts plus reviewed job data and analysis
   - tailoring should not bypass structured evaluation by working directly from raw job input alone

5. Treat confidence as a first-class result
   - confidence should reflect completeness/certainty of reviewed job data
   - confidence should not be confused with score

6. Keep policy configurable over time
   - whether a criterion becomes a blocker, critical risk, or soft penalty should not be permanently hardwired into product assumptions
   - short-term defaults are acceptable, but the design should allow later user-level configuration

## Module Responsibilities

## Module Responsibilities

### profile.py
- load/save candidate profile
- validate candidate profile
- load/save master CV

### ingestion.py
- ingest raw jobs from text / JSON / optional URL
- normalize raw payloads
- deduplicate jobs

### parsing.py
- structure job descriptions
- extract required/preferred details
- deterministic extraction first, LLM fallback later

### eligibility.py
- run hard blocker checks before scoring

### scoring.py
- deterministic weighted fit scoring
- explainable score breakdown
- strengths and missing skills

### decision.py
- convert score + blockers + risks into Apply / Review / Skip

Default decision logic currently proposed:
- blocker present -> Skip
- score >= 80 and no critical risk -> Apply
- score 65-79 -> Review
- otherwise -> Skip

### tailoring.py
- tailored CV drafts
- shortlisted jobs only
- preserve truth

### cover_letter.py
- concise factual UK-style cover letters

### reporting.py
- daily reports and structured summaries

### outcomes.py
- record applications and downstream results

### storage.py
- isolate persistence logic
- store raw input/source separately from reviewed structured jobs
- store derived analysis separately from reviewed job data

### config.py
- thresholds, weights, policies

### orchestrator.py
- coordinate workflow
- handle errors
- protect against duplicates
- preserve state transitions between raw input, reviewed data, and derived analysis

### main.py
- local entrypoint

## MVP Workflow Shape

The intended MVP workflow is:
1. load candidate profile and master CV
2. enter a job using URL or manual copied text
3. store the raw input/source
4. transform the input into a minimum structured job record
5. review/edit uncertain structured fields before final scoring
6. store the reviewed structured job record that will be used for evaluation
7. run deterministic eligibility + scoring + decision logic
8. store the derived analysis result separately
9. inspect explainable results in the minimal local UI
10. optionally trigger tailored CV generation
11. optionally record a basic outcome/status

The MVP should optimize for trustworthy evaluation and safe workflow, not broad automation.

## Non-Functional Requirements

### Explainability
Each job decision should include:
- score
- score breakdown
- blockers
- missing skills
- strengths
- reason for Apply / Review / Skip
- enough structured detail for the user to understand what should be corrected manually before trusting the result

### Reliability
- invalid or partial job data must not crash the pipeline
- errors should be logged clearly
- duplicate jobs should be detected

### Performance
- core scoring and decision must be fast locally
- LLM generation should run only for shortlisted jobs

### Auditability
Store locally:
- raw job input
- parsed job
- analysis result
- decision
- generated output file references
- application outcome

### Privacy
All candidate data and generated outputs should remain local by default.

## Development Sequence

### Phase 0 — Foundations
Deliver:
- models.py
- config.py
- storage.py
- test scaffolding
- README skeleton
- requirements files

Exit criteria:
- repo runs
- tests can execute
- local file persistence works

### Phase 1 — Ingestion & Parsing
Deliver:
- profile loading/validation
- job ingestion from text and JSON
- parsing module
- duplicate detection

Exit criteria:
- messy job input can become structured JobPosting objects

### Phase 2 — Eligibility & Scoring
Deliver:
- hard blocker checks
- weighted scoring engine
- score breakdown
- missing skill detection

Exit criteria:
- every parsed job gets deterministic analysis

### Phase 3 — Decision & Reporting
Deliver:
- Apply/Review/Skip rules
- report generation
- main job summary output

Exit criteria:
- full recommendation pipeline works without document generation

### Phase 4 — Orchestrator
Deliver:
- pipeline coordination
- structured logging
- skip duplicate processing
- end-to-end local run

Exit criteria:
- daily batch run works end to end

### Phase 5 — Tailored CV
Deliver:
- evidence selection
- truthful CV tailoring
- validation checks
- output versioning

Exit criteria:
- safe tailored CV generated for shortlisted roles

### Phase 6 — Cover Letter
Deliver:
- highlight selection
- factual cover letter generation
- truthfulness validation

Exit criteria:
- concise UK-style factual letter generated for shortlisted roles

### Phase 7 — Outcomes & Analytics
Deliver:
- application records
- interview/rejection/offer tracking
- basic conversion metrics

Exit criteria:
- user can see application outcomes over time

### Phase 8 — UI (Later)
Deliver only after core engine is stable.

## Lightweight Input Boundary

MVP may:
- accept one job URL at a time
- accept one copied job text input at a time
- extract only the minimum structured fields needed for evaluation
- leave uncertain fields unknown
- ask the user to review/edit uncertain fields before final scoring

MVP may not:
- crawl sites
- batch ingest jobs from boards
- support many source-specific parsers
- optimize for messy multi-source ingestion reliability
- turn source acquisition into the center of the product

## Scoring Policy Guidance

Until later tuning, follow these principles:
- blockers override score-based recommendations
- unknown data should reduce confidence before it heavily reduces score
- preferred skills are soft boosts, not hard blockers
- required skill gaps may be blockers or major penalties depending on severity
- scoring should remain inspectable and configurable
- whether a criterion is treated as a blocker, critical risk, soft penalty, or neutral factor should be end-user configurable in the mature product

## Tailoring Evidence Rule

Tailored CV generation may:
- reorder existing truthful evidence
- emphasize relevant facts already present in the candidate profile or master CV
- summarize approved evidence more concisely

Tailored CV generation may not:
- invent facts
- imply unsupported experience
- convert missing skills into claimed skills
- smuggle job keywords in as if they are candidate evidence

## Basic Outcomes Contract

MVP outcomes tracking should stay basic.
Allowed outcome states should remain minimal, such as:
- `not_applied`
- `applied`
- `interview`
- `rejected`
- `offer`
- `withdrawn`

Each outcome record should at minimum support:
- `job_id`
- `status`
- `updated_at`
- `notes`

## Forbidden Behaviors

Do not:
- implement auto-apply
- add browser automation
- store candidate data remotely by default
- invent CV facts
- skip tests for core logic
- refactor large parts of repo without being asked
- add unnecessary frameworks
- add interview probability style metrics in MVP

Interview probability may only be considered later if sufficient local outcome data exists.

## MVP Definition

A successful MVP can:
1. load a candidate profile
2. load a master CV
3. accept lightweight job input via job URL and manual copied text
4. turn that input into the minimum structured job data needed for evaluation
5. check blockers
6. score job fit
7. decide Apply / Review / Skip
8. show the result in a minimal local UI
9. generate a truthful tailored CV for shortlisted jobs
10. record basic outcomes locally

MVP should not treat ingestion as a major subsystem. URL input and copied text input are allowed, but broad ingestion coverage, source expansion, and messy multi-source reliability are not the focus of v1.

Do not exceed this scope unless Mic explicitly requests it.

## Working Style

Preferred coding style:
- simple
- modular
- explicit
- easy to review
- low magic
- strong naming
- clear separation between business logic and storage

Prefer:
- small pure functions
- dataclasses or typed models
- readable tests
- config-driven thresholds

## Workflow Discipline (gstack-inspired)

This project follows a staged workflow discipline inspired by the gstack planning model.
The goal is to prevent scope sprawl, premature coding, and mixed-quality agent work.

### How it is applied in this project

1. Planning is separated from implementation
   - product clarification, scope definition, data contracts, UI scope, and architecture guardrails are decided before coding tasks are approved

2. One stage at a time
   - do not bundle product planning, architecture design, implementation, QA, and release readiness into one vague request
   - move forward in small controlled slices

3. Smallest sufficient process
   - do not use every process stage on every small task
   - use only the stages needed to preserve decision quality

4. Implementation is delegated only after scope is stable
   - coding tasks should be created only after the relevant design/docs are clear enough to avoid guessing

5. Review is separate from implementation
   - implementation output from development sub-agents must be reviewed before being accepted as project progress

6. Verification over optimistic summaries
   - changed files, tests, and actual scope compliance matter more than confident status text from an agent

7. Documentation must stay current
   - major planning decisions, progress, and corrections should be reflected in `PROJECT_CONTEXT.md` and `PROJECT_LOG.md`

### Current role split

- SilverHand acts as planner, gatekeeper, reviewer, and project-state maintainer
- Handy acts as the development sub-agent for approved implementation slices only

### Execution rule after initial approval

After Mic approved the staged implementation flow, SilverHand may continue the next small slice automatically when:
- the previous slice passed gatekeeper review
- tests passed
- no new risky ambiguity was introduced

SilverHand should still:
- keep the work one slice at a time
- notify Mic what was done
- move directly to the next item after a slice is Completed if there is no real blocker
- pause only if a risky, ambiguous, or scope-changing issue appears

### Anti-idle rule

If all of these are true:
- the previous item is Completed
- there is no blocker
- there is no unresolved user decision needed
- the next step is already known

then SilverHand must:
1. send the Completed update
2. immediately launch the next concrete step
3. send the In Progress update

`ready to start` should be used only when a real blocker, uncertainty, or user decision is actually present.

### Practical sequence for this project

The working sequence is:
- clarify product and scope
- tighten architecture/data contracts
- approve one implementation slice
- let Handy implement that slice
- SilverHand reviews and verifies the result
- update project docs
- then approve the next slice

## Supporting Docs Expected Before Tasking

Before real implementation tasking begins, these supporting docs should exist:
- `docs/product_spec.md`
- `docs/function_list.md`
- `docs/development_sequence.md`
- `docs/development_rules.md`

## First Recommended Task (Not Yet Executed)

First recommended non-coding artifact:
- `docs/data_contract.md`

It should define:
- MVP JobPosting fields
- MVP JobAnalysis fields
- required vs optional fields
- unknown/nullable handling rules
- blocker categories
- score breakdown structure
- decision output structure
- minimal examples using sample jobs

Acceptance criteria:
- enough detail exists to implement scoring/decision without guessing
- lightweight URL/manual-text input can target the same structure
- truth/explainability requirements are reflected in the contract
- the contract is reviewable before code starts

First recommended coding task after that artifact is approved:
- `src/models.py`
- `src/config.py`
- `src/scoring.py`
- `src/decision.py`
- sample fixtures for structured jobs
- tests for scoring and decision behavior

This coding work has **not** been started yet because Mic asked for planning/confirmation first.

## Confirmed So Far

- Product is local-first and UK-market-oriented.
- Product is not a mass automation bot.
- Deterministic logic should lead; LLM usage should be limited.
- Truthfulness is non-negotiable.
- The final product name is **not** `JOB Smart`.
- The working project folder name is `Job Seeking Tool`.
- A cross-session/project context file should exist and be kept updated.
- SilverHand should handle this as a bigger product, not just ad hoc coding.

## Still Ambiguous / Pending Confirmation

1. Final public product name
2. Whether the truth source should stay limited to candidate profile + master CV only, or later expand to an approved evidence bank
3. Exact minimal local UI shape for MVP
4. How much URL handling is acceptable before it becomes “too much ingestion” for v1
5. Whether copied-text parsing should be strict/manual-assisted or more flexible in MVP
6. Whether current default decision thresholds need revision after first real sample evaluations
7. Post-MVP priority between broader ingestion, cover letters, and richer outcomes tracking

## Latest Milestone

- **Core engine complete** — profile loading, reviewed job input, deterministic scoring, Apply/Review/Skip decisioning, evaluation flow, storage separation, outcomes tracking, reporting/export, and integration tests (69 tests passing)
- **Minimal local UI live** — lightweight localhost browser UI with one-job evaluation flow, outcome recording, and recent job history browser
- **Minimal CLI ready** — `python3 -m src.main` entrypoint wires profile + reviewed job → evaluation → storage → report in one command
- **Docs viewer operational** — project docs browsable at localhost:8765/viewer with dashboard summary cards and cross-doc search

## Latest Progress

- Created project folder `Job Seeking Tool`.
- Moved project memory into the project area.
- Added the requested supporting documentation.
- Completed a v1 clarification checklist pass with Mic.
- Confirmed target user is Mic plus a few similar UK job seekers.
- Confirmed the main v1 goals are better Apply/Review/Skip decisions and higher quality tailored CVs.
- Confirmed MVP should include CV tailoring, but not cover letters.
- Confirmed truth source for MVP is limited to candidate profile + master CV.
- Confirmed scoring philosophy is balanced.
- Confirmed storage strategy is hybrid from the start.
- Confirmed outcomes tracking should stay basic in MVP.
- Confirmed repo/package naming should remain neutral until branding is decided.
- Confirmed MVP should include a minimal local UI.
- Confirmed “scoring/decision first” is the preferred build direction.
- Refined MVP input stance: allow lightweight input via job URL and manual copied text, but do not treat ingestion as a broad MVP subsystem.
- Reduced emphasis on messy-ingestion reliability as a v1 success metric.
- Created `docs/data_contract.md` as the first approved non-coding artifact.
- Reviewed and refined the data contract with Mic.
- Confirmed current JobPosting contract is minimal but sufficient for MVP and extensible later.
- Confirmed salary fields remain optional.
- Confirmed other listed metadata fields are in MVP scope.
- Confirmed blocker categories and score breakdown shape remain as proposed for MVP.
- Confirmed `review` jobs are only tailoring-eligible when manually selected.
- Added workflow-shape guidance to the project context.
- Added explicit lightweight-input boundary rules.
- Added scoring-policy guidance for blockers, unknown data, and preferred skills.
- Added tailoring evidence rules.
- Added a minimal outcomes contract.
- Created `docs/ui_scope.md` to define the MVP local UI.
- Revised the development sequence to include an explicit input review/edit step before trusting scores.
- Added `docs/architecture_guardrails.md` to lock pre-implementation architecture discipline.
- Recorded the gstack-inspired workflow discipline and role split between SilverHand and Handy.
- Handy completed Task 1 (models foundation).
- `src/models.py` and `tests/test_models.py` now exist as the first approved implementation slice.
- Gatekeeper verification passed for the models slice.
- Handy completed Task 1.5 (testing environment setup).
- `requirements-dev.txt` now exists with minimal pytest support.
- `python3 -m pytest` now runs successfully in the repo, and the current model tests are passing.
- Handy completed Task 2 (config + scoring foundation).
- `src/config.py`, `src/scoring.py`, and `tests/test_scoring.py` now exist.
- Deterministic scoring is now implemented with confidence kept separate from match score.
- Handy completed Task 3 (decision foundation).
- `src/decision.py` and `tests/test_decision.py` now exist.
- Decision policy is now configurable in `src/config.py`.
- Handy completed Task 4 (profile/loading foundation).
- `src/profile.py` and `tests/test_profile.py` now exist.
- Local-first profile JSON loading and master CV file loading are now implemented.
- Handy completed Task 5 (reviewed-input foundation).
- `src/reviewed_input.py` and `tests/test_reviewed_input.py` now exist.
- Reviewed job payloads can now be normalized into structured `JobPosting` data without turning this into a broad ingestion subsystem.
- Handy completed Task 6 (storage foundation).
- `src/storage.py` and `tests/test_storage.py` now exist.
- Local JSON storage now preserves separate state folders for raw inputs, reviewed jobs, and derived analyses.
- Handy completed Task 7 (evaluation flow foundation).
- `src/evaluation.py` and `tests/test_evaluation.py` now exist.
- Reviewed job evaluation can now produce a full `JobAnalysis` by composing scoring and decision.
- Handy completed Task 8 (outcomes foundation).
- `src/outcomes.py` and `tests/test_outcomes.py` now exist.
- Local outcomes tracking and separate `outcomes/` persistence are now implemented.
- Handy completed Task 9 (minimal reporting/export foundation).
- `src/reporting.py` and `tests/test_reporting.py` now exist.
- Lightweight JSON/CSV reporting/export is now implemented for evaluated jobs and optional outcomes.
- Handy completed Task 9.5 (integration flow tests).
- `tests/test_integration_flow.py` now exists.
- The current core modules now have integration-level coverage across profile, reviewed input, evaluation, storage, reporting, and outcomes.
- Handy completed Task 10 (minimal CLI/app entry foundation).
- `src/orchestrator.py`, `src/main.py`, `tests/test_orchestrator.py`, and `tests/test_main.py` now exist.
- A lightweight local CLI-first flow now wires together profile loading, reviewed input, evaluation, storage, and reporting.
- Current repo verification passes with `65` tests green.
- Default low-salary mismatch behavior now routes to `review` via the configurable policy/risk layer.
- Built a lightweight local document viewer under `viewer/` so project markdown can be browsed in one place.
- Improved the viewer with grouped document categories, search, a dashboard home page, and summary cards driven by `PROJECT_CONTEXT.md` and `PROJECT_LOG.md`.
- Handy completed Task 11 (minimal local UI shell).
- `src/ui.py` and `tests/test_ui.py` now exist as the minimal localhost browser UI entry.
- One-job browser flow covers URL/text context entry, field review/edit, evaluation, outcome recording, and recent job history.
- `src/orchestrator.py` updated with a UI helper so the browser UI submits reviewed payloads through the existing orchestration path.
- Repo verification holds at `69` tests passing.
- UI request-level coverage added for GET `/`, POST `/evaluate`, POST `/outcome`, and job history endpoints.
- Docs tightened in `docs/ui_scope.md` to clarify current UI input boundaries and tailoring status.
- Viewer manifest updated to include `docs/architecture_guardrails.md`.

## Next Recommended Step

Checkpoint passed — Task 11 complete. Core engine and minimal UI shell are both in place.

The current system now has:
- profile loading
- reviewed input normalization
- scoring
- decisioning
- evaluation flow
- storage separation
- outcomes
- reporting/export
- integration tests
- a minimal CLI/app entry flow
- a minimal local UI shell (localhost browser)

Recommended next step:
1. Perform a real manual smoke run with the CLI and UI using real or realistic sample files to validate end-to-end behaviour before CV tailoring work begins.

Unknown-field scoring policy is now confirmed as mixed neutral:
- some unknown fields may receive full neutral credit
- some unknown fields may receive partial neutral credit
- confidence should still fall when important job data is missing
