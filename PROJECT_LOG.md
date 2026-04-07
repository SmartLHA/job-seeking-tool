# PROJECT_LOG.md

This is the project logbook for the job-search copilot product work.

Use it to capture:
- dated progress updates
- key decisions
- naming changes
- scope changes
- notable risks
- implementation milestones
- next recommended actions

---

## 2026-04-04

### Session summary

Initial planning and workspace/project setup took place before implementation.

### What was discussed

- Product concept: local-first AI job search decision-support and application-preparation product for the UK market.
- Product goals:
  - ingest jobs
  - structure job data
  - score job fit
  - decide Apply / Review / Skip
  - generate truthful tailored CVs and cover letters
  - track outcomes over time
- Product is **not** meant to be:
  - mass auto-apply
  - browser automation
  - speculative/fabricated candidate output
  - background account interaction
  - application-volume optimization

### Key constraints captured

- deterministic logic first
- explainability
- local-first privacy
- truthful output
- modular code
- small testable steps
- human approval required before final application actions

### Product naming status

- `JOB Smart` was discussed but rejected as the final product name.
- Reason: Mic said the name is already used by others.
- Current folder name is `Job Seeking Tool`.
- Final public product name is still undecided.

### Planning artifacts created

Created in project folder:
- `PROJECT_CONTEXT.md`
- `docs/product_spec.md`
- `docs/function_list.md`
- `docs/development_sequence.md`
- `docs/development_rules.md`

### Development direction captured

- Python backend only for MVP
- local-first storage only
- SQLite + JSON/JSONL preferred
- no auto-apply in v1
- no browser automation in v1
- deterministic scoring before LLM generation
- all generated CV/cover letter content must be truthful
- no invented skills, years, titles, achievements, or certifications
- every core logic module must have tests
- do not refactor unrelated files
- keep dependencies light
- prefer modular, explicit code over clever abstractions

### High-level architecture discussed

Modules planned:
- models
- config
- storage
- profile
- ingestion
- parsing
- eligibility
- scoring
- decision
- tailoring
- cover_letter
- reporting
- outcomes
- orchestrator
- main

### Current status

- Planning in progress.
- No core product implementation has started yet.
- Foundation docs and project memory have been created first.

### Clarification checklist outcomes

Mic confirmed:

1. Primary target user for v1:
   - Mic + a few similar UK job seekers

2. Main user goals:
   - better Apply / Review / Skip decisions
   - higher quality tailored CVs

3. MVP input stance:
   - lightweight input via job URL and manual copied text
   - not a broad ingestion-focused MVP

4. URL handling in MVP:
   - allowed only if very simple and deterministic

5. Tailoring in MVP:
   - CV only
   - cover letters deferred

6. Truth source design:
   - candidate profile + master CV only

7. Scoring philosophy:
   - balanced

8. Early storage strategy:
   - hybrid from the start

9. Duplicate detection priority:
   1. same company + title + location
   2. same source ID
   3. same company + title
   4. same normalized description hash
   5. same URL

10. Default decision thresholds:
   - keep current proposed thresholds for now

11. Outcomes tracking depth in MVP:
   - basic only

12. Naming while final brand is undecided:
   - keep neutral names everywhere

13. UI expectation for MVP:
   - minimal local UI in MVP

14. First-version success criteria:
   - scoring feels trustworthy
   - tailored CV output is usable with light edits
   - local workflow feels simple and safe

15. Preferred build emphasis:
   - scoring / decision first

### Scope refinement from clarification

- Earlier planning leaned more heavily toward ingestion as a visible MVP pillar.
- Clarification narrowed this.
- MVP may accept job URL and copied text, but should not become a broad ingestion/parsing product in v1.
- The center of gravity is now:
  - decision quality
  - truthful CV tailoring
  - simple local workflow
  - minimal local UI

### Revised recommended next step

1. Update project charter/state files with the clarified v1 shape
2. Rewrite the build sequence so it reflects scoring/decision-first while preserving lightweight URL/text input
3. Identify the first approved non-coding artifact or implementation task

### First recommended artifact / task

Recommended first non-coding artifact:
- `docs/data_contract.md`

Purpose:
- lock the MVP JobPosting structure
- lock the MVP JobAnalysis structure
- define required/optional/unknown fields
- define what scoring consumes
- define what decisioning emits
- prevent implementation from inventing structure mid-build

Recommended first coding task after artifact approval:
- models/config/scoring/decision modules
- sample structured job fixtures
- tests for scoring and decision rules

Reasoning:
- Mic chose scoring/decision-first
- MVP still accepts URL/manual text, so there must be a stable target structure
- this artifact reduces ambiguity before coding begins

### Data contract review outcome

Mic confirmed:
- the required JobPosting set is minimal but sufficient for MVP, while staying extensible later
- salary fields remain optional
- other listed metadata fields are in MVP scope
- blocker categories stay as proposed for MVP
- score breakdown shape stays as proposed for MVP
- `review` jobs are tailoring-eligible only when manually selected

### Design fine-tuning pass

A follow-up design review identified several areas that needed tightening before implementation:
- the exact MVP workflow shape
- the boundary between lightweight input and broad ingestion
- the need for an explicit input review/edit step before trusting scores
- scoring policy guidance for unknown data, blockers, and preferred skills
- clearer tailoring evidence rules
- a minimal basic outcomes contract
- the exact shape of the minimal local UI

Updates made:
- added workflow-shape guidance to `PROJECT_CONTEXT.md`
- added lightweight-input boundary rules
- added scoring-policy guidance
- added tailoring-evidence rules
- added basic outcomes contract guidance
- added `docs/ui_scope.md`
- revised the development sequence to include an explicit input review/edit phase before the local UI result flow

### Project-document sync update

Mic asked that project documents be kept up to date for everything created or changed.

Project documents now reflect:
- charter updates
- clarification checklist outcomes
- data contract creation and review outcomes
- design fine-tuning decisions
- revised MVP workflow and UI scope
- current next-step recommendation: draft the first coding task brief, but do not begin implementation without explicit approval

### Pre-implementation architecture guardrail pass

A final architecture review was completed before implementation planning starts.

Main guardrails added:
- preserve separation between raw input, reviewed structured job data, and derived analysis
- keep eligibility, scoring, and decision logic in separate modules
- keep lightweight input from turning into a broad ingestion/parsing subsystem
- require correction/review before trusted scoring when extracted data is uncertain
- treat confidence as a first-class output separate from score
- keep tailoring downstream of reviewed job data and analysis
- preserve strict truth boundaries for tailoring
- keep policy in config where practical

Artifacts updated/added:
- `PROJECT_CONTEXT.md`
- `docs/data_contract.md`
- `docs/architecture_guardrails.md`

### Workflow-discipline note added

The project docs were updated to explicitly record the gstack-inspired workflow discipline being used in this project.

Key points recorded:
- planning is separated from implementation
- work proceeds one stage at a time
- only the smallest sufficient process should be used
- implementation is delegated only after scope is stable
- review is separate from implementation
- verification matters more than optimistic summaries
- SilverHand acts as planner/gatekeeper and Handy acts as the development sub-agent for approved slices

### Handy Task 1 — Models foundation review

Handy completed the first approved implementation slice.

Files added:
- `src/models.py`
- `tests/test_models.py`

What was delivered:
- typed dataclass-based models for:
  - `CandidateProfile`
  - `JobPosting`
  - `Blocker`
  - `RiskFlag`
  - `ScoreComponent`
  - `ScoreBreakdown`
  - `JobAnalysis`
- section comments explaining model purpose and workflow intent
- lightweight model-level validation for empty required fields, non-negative numeric fields, salary range sanity, score bounds, and non-empty decision reason
- test file covering model construction and key guardrails

Gatekeeper review result:
- accepted as a solid first implementation slice
- aligns with the approved task scope
- preserves confidence as separate from score
- keeps the model layer readable and reasonably extensible
- does not appear to introduce out-of-scope functionality

Initial issue found during verification:
- `pytest` was not yet available in the repo environment when Task 1 finished
- direct Python import/construction sanity check succeeded

### Handy Task 1.5 — Testing environment setup review

Handy completed the testing-environment prerequisite slice.

Files added/updated:
- `requirements-dev.txt`

What changed:
- added the minimum dev dependency needed for repo-local test execution:
  - `pytest>=8,<9`

Gatekeeper verification result:
- accepted
- dependency footprint stayed minimal
- no product logic scope creep occurred
- `python3 -m pytest` now runs successfully in the repo

Verified test result:
- `5 passed`
- current model tests are now runnable and passing

Practical environment note:
- pytest installation needed to respect the host Python environment constraints
- running tests via `python3 -m pytest` is the reliable path

### Handy Task 2 — Config + scoring foundation review

Handy completed Task 2.

Files added:
- `src/config.py`
- `src/scoring.py`
- `tests/test_scoring.py`

What was delivered:
- typed scoring policy/config objects in `src/config.py`
- deterministic `score_job(...)` flow in `src/scoring.py`
- clear separation between `match_score` and `confidence`
- scoring behavior that treats preferred skills as soft boosts
- confidence behavior that drops with missing job data before score is heavily reduced
- focused tests for core scoring behavior

Gatekeeper verification result:
- accepted
- scope stayed controlled
- code remains readable and commented
- pytest verification passed cleanly

Verified test result:
- `10 passed`

Follow-up note before Task 3:
- Mic confirmed a mixed-neutral policy for unknown fields:
  - some unknown fields may receive full neutral credit
  - some unknown fields may receive partial neutral credit
  - confidence should still decrease when important job data is missing

### Handy Task 3 — Decision foundation review

Handy completed Task 3.

Files added:
- `src/decision.py`
- `tests/test_decision.py`

Files updated:
- `src/config.py`

What was delivered:
- typed decision layer kept separate from scoring
- configurable decision policy in `src/config.py`
- Apply / Review / Skip logic aligned to current provisional thresholds
- blocker override behavior
- current critical-risk handling for high-score review gating
- focused decision tests

Gatekeeper verification result:
- accepted
- scope stayed controlled
- decision logic remains separate from scoring logic
- pytest verification passed cleanly

Verified test result:
- `15 passed`

Current decision-policy note:
- `missing-required-skills` is currently treated as the critical decision risk code

### Handy Task 4 — Profile/loading foundation review

Handy completed Task 4.

Files added:
- `src/profile.py`
- `tests/test_profile.py`

What was delivered:
- local-first candidate profile loading/saving helpers
- focused profile validation via `ProfileValidationError`
- JSON profile loading and serialization helpers
- local master CV load/save helpers
- relative-path resolution for `master_cv_ref`
- tests for valid loading, failure cases, round-trip behavior, and CV file handling

Gatekeeper verification result:
- accepted
- scope stayed controlled
- profile loading remains separate from scoring/decision logic
- pytest verification passed cleanly

Verified test result:
- `24 passed`

Current profile-policy note:
- unknown/extra profile keys are rejected by design in the current profile contract

### Handy Task 5 — Reviewed-input foundation review

Handy completed Task 5.

Files added:
- `src/reviewed_input.py`
- `tests/test_reviewed_input.py`

What was delivered:
- narrow reviewed-input conversion layer from reviewed payloads into `JobPosting`
- `ReviewedInputValidationError`
- explicit unknown handling for reviewed fields
- unknown-field rejection
- trimmed string normalization
- case-insensitive skill deduplication during reviewed normalization
- tests for reviewed-input behavior and round-trip conversion

Gatekeeper verification result:
- accepted
- scope stayed controlled
- reviewed-input remains lightweight and separate from broad ingestion
- pytest verification passed cleanly

Verified test result:
- `28 passed`

Current reviewed-input note:
- reviewed skill lists now deduplicate case-insensitively by implemented behavior

### Handy Task 6 — Storage foundation review

Handy completed Task 6.

Files added:
- `src/storage.py`
- `tests/test_storage.py`

What was delivered:
- lightweight local JSON persistence helpers
- explicit storage separation for:
  - raw inputs
  - reviewed jobs
  - derived analyses
- typed round-trip helpers for reviewed jobs and analyses
- tests covering storage layout, round-trips, state separation, and invalid analysis payloads

Gatekeeper verification result:
- accepted
- scope stayed controlled
- raw/reviewed/analysis state separation is now enforced in storage layout
- pytest verification passed cleanly

Verified test result:
- `35 passed`

### Handy Task 7 — Evaluation flow foundation review

Handy completed Task 7.

Files added:
- `src/evaluation.py`
- `tests/test_evaluation.py`

What was delivered:
- lightweight evaluation composition layer
- combines scoring + decision into `JobAnalysis`
- keeps scoring and decision modules separate
- supports injected blockers for future eligibility integration
- sets current tailoring readiness behavior from decision outcome
- tests for apply/review/skip evaluation flow and confidence-vs-score behavior

Gatekeeper verification result:
- accepted
- scope stayed controlled
- composition layer stays small and does not collapse module boundaries
- pytest verification passed cleanly

Verified test result:
- `39 passed`

### Handy Task 8 — Outcomes foundation review

Handy completed Task 8.

Files added:
- `src/outcomes.py`
- `tests/test_outcomes.py`

Files updated:
- `src/models.py`
- `src/storage.py`
- `tests/test_storage.py`

What was delivered:
- basic local outcomes tracking foundation
- typed outcome models and update logic
- separate local `outcomes/` storage state
- simple transition validation for outcome status changes
- tests for creation, updates, validation, persistence, and layout

Gatekeeper verification result:
- accepted
- scope stayed controlled
- outcomes remain basic and local-first
- pytest verification passed cleanly

Verified test result:
- `46 passed`

### Handy Task 9 — Minimal reporting/export foundation review

Handy completed Task 9.

Files added:
- `src/reporting.py`
- `tests/test_reporting.py`

What was delivered:
- lightweight local-first reporting/export helpers
- flat report rows from reviewed jobs + analysis + optional outcomes
- simple summary counts for decisions and outcomes
- JSON export
- CSV export
- tests for row building, summary counts, JSON export, and CSV export

Gatekeeper verification result:
- accepted
- scope stayed controlled
- reporting remains helper-level only and does not turn into analytics/dashboard scope
- pytest verification passed cleanly

Verified test result:
- `52 passed`

### Handy Task 9.5 — Integration flow tests review

Handy completed the integration-test slice.

Files added:
- `tests/test_integration_flow.py`

What was delivered:
- end-to-end integration-style coverage across current modules
- happy-path profile → reviewed job → evaluation → storage → reporting → outcomes flow
- blocker override coverage
- sparse reviewed job / low-confidence coverage
- required-skill-gap review coverage
- storage/reporting flows with and without outcomes

Gatekeeper verification result:
- accepted
- no product code changes were required
- integration safety net is now in place before a CLI/app entry slice
- pytest verification passed cleanly

Verified test result:
- `57 passed`

### Handy Task 10 — Minimal CLI/app entry foundation review

Handy completed Task 10.

Files added:
- `src/orchestrator.py`
- `src/main.py`
- `tests/test_orchestrator.py`
- `tests/test_main.py`

What was delivered:
- lightweight local orchestration flow for one reviewed-job run
- CLI entrypoint for profile + reviewed job + optional raw input
- local flow wiring across profile loading, reviewed input, evaluation, storage, and reporting
- tests for orchestration and CLI behavior

Gatekeeper verification result:
- accepted
- scope stayed controlled
- module boundaries were preserved while adding the entry flow
- pytest verification passed cleanly

Verified test result:
- `62 passed`

### Manual smoke-run note

Additional manual smoke runs were used to probe stronger edge/exception cases.

Observed:
- sparse/unknown-heavy input produced a low-confidence skip as expected
- required-skill gap produced a review decision as expected
- invalid reviewed payload failed cleanly with a non-zero CLI exit code
- low-salary case still produced `apply` under the current default policy

Product decision clarified from this:
- whether a criterion is treated as a blocker, critical risk, or softer penalty should ultimately become end-user configurable rather than permanently fixed in code assumptions

### Salary-mismatch default policy adjustment

Mic asked for the current low-salary mismatch case to default to `review` rather than `apply`.

Implemented:
- added `salary-below-floor` as a current critical decision risk code
- scoring now emits that risk when known salary is below the candidate salary floor
- decision policy now treats that critical risk as review-gating by default

Gatekeeper verification result:
- accepted
- default behavior now matches the requested current policy
- longer-term configurability is preserved through the policy/config layer rather than hard-coding a one-off branch

Verified result:
- repo tests now pass at `65 passed`
- manual smoke run for the low-salary case now returns `review`

### README usage note

Handy created the first project `README.md`.

What it now documents:
- current implemented scope
- current CLI entrypoint and flags
- practical profile/reviewed-job input expectations
- current output/state locations
- current test command
- reminder to keep naming neutral until branding is decided

Gatekeeper verification result:
- accepted
- documentation stays aligned to the implemented CLI-first foundation
- no code changes were made in this slice

### UI request-level test + doc-tightening follow-up

Handy added request-level UI coverage for the local UI HTTP flow.

What was added in tests:
- GET `/`
- POST `/evaluate` success
- POST `/evaluate` validation failure
- GET `/job?job_id=...`
- GET `/job/<id>`
- GET `/job/<id>/`
- POST `/outcome`

Gatekeeper note:
- tests now cover the actual request/response path instead of only helper-level behavior
- Scout's earlier ambiguity about UI wording was also tightened in `docs/ui_scope.md`
- the docs now make clear that the current UI captures URL/text as local context while reviewed structured fields are entered/edited directly, and that tailoring is status-only for now

### Execution mode update

Mic confirmed that after a slice passes review and tests, SilverHand may continue the next small implementation slice automatically.

Guardrails still apply:
- one slice at a time
- notify Mic what was done
- move directly to the next item after a slice is Completed if there is no real blocker
- pause if a risky, ambiguous, or scope-changing issue appears

### Anti-idle rule added

Mic explicitly called out a repeated failure pattern where work was marked Completed but the next obvious step was not launched, causing fake idle gaps.

Rule added:
- if an item is Completed
- and there is no blocker
- and no user decision is needed
- and the next step is known

then SilverHand must immediately:
1. send the Completed update
2. launch the next concrete step
3. send the In Progress update

`ready to start` should only be used for real blockers, uncertainty, or genuine decision points.

### Lean team protocol added

A structured YAML protocol was added for the multi-agent team.

File:
- `docs/team_protocol.yaml`

It captures:
- lean communication rules
- anti-idle workflow rule
- SilverHand / Handy / Scout role boundaries
- direct Handy → Scout handoff
- Scout lean vs full QA modes
- hard gates + scoring framework
- idle Scout behavior for lean test planning
- project-specific guardrails for the Job Seeking Tool

### Local docs dashboard update

A lightweight local project document viewer was added under `viewer/` so Mic can browse project markdown without opening files one by one.

Viewer improvements completed:
- grouped docs by category
- dashboard home page instead of opening straight into a single doc
- summary cards for:
  - Latest development Action Done
  - Latest Discussion outcome
  - Outstanding Question
  - Next Action
- dashboard summaries now derive from `PROJECT_CONTEXT.md` and `PROJECT_LOG.md` instead of staying hardcoded
- summary cards were polished into cleaner bullet-style summaries
- cross-document search was added
- mobile/LAN access instructions were added so the viewer can be opened from a phone on the same Wi‑Fi
- viewer document list was updated to include newly added project docs such as `docs/data_contract.md`, `docs/ui_scope.md`, and `viewer/README.md`
- viewer moved from a hardcoded document list to a manifest-driven approach using `viewer/documents.json`

Purpose:
- make project state easier to inspect locally
- help other sessions understand that the dashboard exists
- keep the dashboard aligned with the project memory files

### Handy Task 11 — Minimal local UI shell review

Handy completed the approved minimal local UI shell slice.

Files added:
- `src/ui.py`
- `tests/test_ui.py`

Files updated:
- `src/orchestrator.py`
- `README.md`

What was delivered:
- a tiny standard-library localhost UI entry path via `python3 -m src.ui`
- one-job browser flow for:
  - entering URL/copied-text context
  - reviewing/editing structured fields
  - running evaluation through the existing orchestration path
  - showing score, confidence, blockers, risks, strengths, missing skills, and decision
  - recording a basic local outcome status
  - viewing recent evaluated jobs from local state
- a small orchestrator helper so the UI can submit reviewed payloads directly without replacing the CLI or introducing a framework
- focused UI/helper tests for form parsing and recent-history behavior

Gatekeeper verification result:
- pending main-session review
- implementation stayed thin and local-first
- CLI path remains intact
- no heavy UI framework was added

Verified test result:
- `69 passed`

---

## 2026-04-07

### Viewer fixes — doc links, usage display, and refresh

Three viewer issues were reported and fixed:

**Issue 1 — All doc links were broken**

Root cause: `documents.json` stored paths like `/PROJECT_CONTEXT.md` (project-root-relative), but `viewer_server.py` served files from the `viewer/` subdirectory only. The security check also rejected `..` path traversal, so sibling files outside `viewer/` couldn't be reached.

Fix: Rewrote `serve_file()` to resolve from `PROJECT_ROOT` (the project root, one level above `viewer/`), map `/viewer/../*` paths to project-root-relative files, and handle `/viewer/*` paths to viewer subdir resources. Added `PROJECT_ROOT` constant and proper `isdir` → `index.html` fallback.

**Issue 2 — No MiniMax token usage info in the viewer**

Root cause: `usage.json` (written by a cron job) didn't include an `ok` field. The browser `fetchUsage()` checked `data.ok` which was `undefined` → falsy → always showed "Usage: unavailable".

Fix: Added `_load_usage_json()` helper that injects `ok: True` when serving from `usage.json`. Also improved empty-state messages from "viewer server only" to "Usage: no session data" and "offline".

**Issue 3 — Refresh button had no effect**

Root cause: Browser HTTP fetch caching despite `cache: 'no-store'`.

Fix: Added `?t=' + Date.now()` cache-busting query param to both `fetchDocText()` and `fetchManifest()` calls in `app.js`.

**Additional fixes**

- `viewer.sh` start command had wrong path (`viewer_server.py` instead of `viewer/viewer_server.py`) — fixed
- `os.chdir()` in `main()` updated to `PROJECT_ROOT` to match new file resolution

Files changed:
- `viewer/viewer_server.py` — rewritten `serve_file()` with proper project-root resolution, added `PROJECT_ROOT`, `_load_usage_json()`
- `viewer/documents.json` — paths changed from `/PROJECT_CONTEXT.md` to `/viewer/../PROJECT_CONTEXT.md` style (now resolved correctly by server)
- `viewer/app.js` — cache-busting query params on fetches, improved usage empty states
- `viewer/viewer.sh` — fixed `viewer_server.py` path in start command

### Session cleanup

Checked all sessions — only 2 active sessions found (main + one closed subagent). No stale inactive sessions requiring cleanup.

### Platform config — ACP default agent + subagent allowlist

Added to `openclaw.json`:
- `acp.defaultAgent: "qa"` — enables ACP runtime for spawned subagents
- `agents.defaults.subagents.allowAgents: ["qa", "dev"]`
- `agents.defaults.subagents.runTimeoutSeconds: 300`

Purpose: fixes WS reliability issues for subagent spawning (was causing gateway 1006 closures on large output).

### Scout QA pass — smoke test (2026-04-07)

Scout ran lean smoke checks via ACP runtime (first successful ACP spawn since config fix):

| Check | Result |
|-------|--------|
| Test suite | ✅ 80 passed |
| CLI smoke | ✅ Business Analyst @ Example Co → apply, 97.5 |
| Viewer doc links | ⚠️ 10/11 — `viewer/README.md` path inconsistent |

**Score: 85/100** — viewer manifest path bug + missing team_protocol.yaml in manifest.

### Handy fix — viewer manifest

Handy Task: Fixed `viewer/documents.json`:
- Changed `Viewer README` path from `/viewer/README.md` → `/viewer/../viewer/README.md`
- Added `docs/team_protocol.yaml` as new Protocol category entry

Result: **12/12 paths now resolve** ✅

Files changed:
- `viewer/documents.json`

### Scout QA pass — 8 tasks, all green (2026-04-07)

Sequential QA run via Scout (Handy on leave):

| # | Task | Result |
|---|------|--------|
| Q1 | Viewer manifest fix (Handy) | ✅ 12/12 paths |
| Q2 | UI home page | ✅ HTTP 200, form OK |
| Q3 | UI evaluate POST | ✅ apply, 95.0 |
| Q4 | UI outcome POST + job GET | ✅ flash + status reflected |
| Q5 | All sample inputs | ✅ demo/gap/salary_miss→review, sparse→skip, invalid→error |
| Q6 | Invalid input rejection | ✅ done in Q5 |
| Q7 | Report generation | ✅ JSON + CSV exist |
| Q8 | Storage separation | ✅ all 3 dirs with files |

**Score: 100/100.** Platform ACP config confirmed working for subagent spawning.

### Cover Letter spec confirmed (2026-04-07)

Decisions confirmed with Mic:
- Near-final quality, salary blank, "why this company" included (2-3 sentences)
- Evidence source: same as CV tailoring (profile + master CV only)
- ATS-friendly formatting required

### CV Tailoring brief finalized (2026-04-07)

Decisions confirmed with Mic:
- Review jobs require manual selection before tailoring
- Evidence: required skills first, from skills + years only
- ATS-friendly output required
- Tailoring only from approved profile + master CV

Briefs ready at `docs/tasks/cv-tailoring-brief.md` and `docs/tasks/cover-letter-spec-draft.md`.

### Structured logging added (SilverHand, 2026-04-07)

Added timestamped run logs to `logs/` directory.
- Each CLI run writes `logs/YYYY-MM-DD_HHMMSS_<job_id>.log`
- Fields: timestamp, job_id, decision, score, confidence, profile_id, job_title, company, input/output paths
- `storage.py`: `StorageLayout` now includes `logs_dir`; `logs/` added to storage creation
- `orchestrator.py`: `_log_run()` writes structured log after each evaluation
- Tests: 80/80 pass

**Next:** CV tailoring — hand off to Handy when back.


