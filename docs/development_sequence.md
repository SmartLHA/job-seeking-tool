# Development Sequence

This sequence has been revised after Mic’s clarification pass.

Key shifts:
- scoring / decision quality is the center of MVP
- MVP accepts lightweight job input via URL and manual copied text
- MVP should not become a broad ingestion/parsing product
- MVP includes a minimal local UI
- MVP includes truthful CV tailoring
- cover letters are deferred

## Phase 0 — Foundations
Deliver:
- models.py
- config.py
- storage.py
- test scaffolding
- README skeleton
- requirements files
- initial UI/app shell decision for the minimal local UI

Exit criteria:
- repo runs
- tests can execute
- local persistence works
- project structure supports scoring-first development

## Phase 1 — Structured Job Model + Sample Data + Scoring Core
Deliver:
- candidate profile loading/validation
- master CV loading/validation
- structured JobPosting model contract
- sample structured job fixtures
- eligibility rules
- weighted scoring engine
- score breakdown
- Apply / Review / Skip decision rules

Exit criteria:
- sample jobs can be evaluated deterministically end to end
- scoring feels inspectable and trustworthy enough for early review
- decision outputs are explainable

## Phase 2 — Lightweight Job Input
Deliver:
- manual copied-text input path
- simple URL input path
- minimal transformation into required structured fields
- validation/guardrails for incomplete or low-confidence input
- duplicate detection aligned to confirmed priority rules

Exit criteria:
- user can enter a job through URL or copied text
- system can convert it into the minimum data needed for scoring
- URL handling remains simple and deterministic
- this phase does not expand into a broad ingestion subsystem

## Phase 3 — Input Review / Edit Step
Deliver:
- explicit structured-field review/edit step before final scoring
- clear unknown/uncertain field handling
- user correction flow for incomplete extracted fields
- validation messages that support safe correction

Exit criteria:
- uncertain fields can be corrected before the score is treated as trustworthy
- the workflow supports truthfulness and explainability rather than hidden guessing

## Phase 4 — Minimal Local UI
Deliver:
- local UI for entering job URL or copied text
- profile/master CV selection or loading flow
- structured-field review/edit flow
- scored job result view
- clear Apply / Review / Skip display
- score breakdown / blockers / strengths / missing skills display

Exit criteria:
- a user can complete the core evaluate-a-job flow locally without using raw CLI commands
- workflow feels simple and safe
- decision explanation is visible in the UI
- the correction loop is visible in the UI

## Phase 5 — Tailored CV
Deliver:
- evidence selection from candidate profile + master CV only
- truthful CV tailoring for shortlisted jobs
- validation checks against the allowed truth sources
- output versioning/saving

Exit criteria:
- tailored CV output is usable with light edits
- no invented claims appear
- tailored output is linked to the evaluated job

## Phase 6 — Basic Outcomes Tracking
Deliver:
- record application status locally
- basic status updates
- notes
- minimal history view/reporting

Exit criteria:
- user can record and review basic outcomes over time
- tracking supports practical personal use without heavy analytics

## Phase 7 — Hardening & Workflow Polish
Deliver:
- error handling improvements
- clearer validation messages
- duplicate handling polish
- small workflow refinements
- reporting polish where needed

Exit criteria:
- the end-to-end MVP flow is stable
- local workflow feels reliable and low-friction
- core logic remains modular and testable

## Deferred Until After MVP
- broad ingestion expansion
- messy multi-source parsing reliability as a primary product goal
- cover letter generation
- deeper analytics
- larger automation/orchestration features
- richer UI beyond the minimal local workflow
