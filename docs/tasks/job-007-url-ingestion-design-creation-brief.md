# JOB-007 — Create URL Ingestion Design Doc Brief

**Status:** Draft for Wiser review  
**Owner:** SilverHand brief → Wiser review → Handy doc creation → Scout QA  
**Date:** 2026-05-13  
**Target artifact:** `docs/tasks/url-ingestion-design.md`

## Problem

`MEMORY.md` and the project TODO previously referenced `docs/tasks/url-ingestion-design.md`, but that file does not exist. The existing `docs/tasks/job-ingestion-api-design.md` covers API sourcing (Reed/Adzuna originally; JOB-002 now implemented Reed-only), not direct URL paste/fetch behaviour.

JOB-007 should create a canonical design document for URL paste/fetch ingestion, without implementing code.

## Required Scope for Target Document

The target document must cover:

- URL paste/fetch ingestion design.
- Time budget: **10 seconds total**.
  - **2 seconds parse budget**.
  - **8 seconds network/fetch budget**.
- Redirect handling: **maximum 3 redirects**.
- Allowed sources:
  - indeed
  - linkedin
  - reed
  - glassdoor
  - cwjobs
  - cv-library
  - guardianjobs
- Review/edit step before evaluation.
- Fallback path: if fetch/parse fails, show raw text/manual entry option.
- Relationship to existing API ingestion:
  - Reed API/orchestrator path is canonical for Reed API fetching after JOB-002.
  - URL ingestion is a user-initiated paste/fetch feature, not bulk scraping.
- Robots.txt / site policy handling, especially for sources with anti-scraping or terms concerns.
- Security posture:
  - URL allowlist.
  - Timeout limits.
  - Redirect limits.
  - No credential use.
  - No JavaScript/browser automation for MVP unless explicitly approved later.
  - Treat fetched content as untrusted external content.
- Data contract mapping to `JobPosting`.
- Testing/QA plan for future implementation.

## Existing Context to Reconcile

- `docs/tasks/ui-paste-url-prefill-brief.md` already describes a UI paste/URL prefill flow and mentions robots.txt + 10s timeout.
- `docs/tasks/job-ingestion-api-design.md` explicitly says generic web scraping is out of scope for API design, but mentions URL ingestion via paste may exist separately.
- `src/job_hunt_paste_fetch.py`, `src/job_hunt_paste_ui.py`, and `src/job_hunt_paste_url.html` exist, but JOB-009 separately decides whether paste_fetch is canonical or superseded. JOB-007 should not resolve JOB-009 unless documenting the dependency/open question.
- `docs/data_contract.md` remains the internal `JobPosting` contract.

## Non-goals

- Do not implement URL fetch code in this task.
- Do not modify runtime UI in this task.
- Do not add new external dependencies.
- Do not enable scraping or browser automation.
- Do not claim LinkedIn/Indeed/Glassdoor are safely fetchable if robots/terms block them; document likely fallback/manual path.
- Do not supersede Reed API ingestion from JOB-002.

## Recommended Target Document Structure

`docs/tasks/url-ingestion-design.md` should include:

1. Status / purpose / relationship to API ingestion.
2. User flow.
3. Source allowlist and source-specific handling table.
4. Fetch constraints:
   - 10s total
   - 8s network
   - 2s parse
   - 3 redirects
   - response size cap recommendation
   - allowed schemes `https` only, optionally `http` redirecting to `https`
5. Security and untrusted content rules.
6. Robots.txt / terms handling.
7. Parsing strategy:
   - deterministic extraction first
   - metadata/schema.org when available
   - visible text fallback
   - no invented fields; unknown stays null/empty/unknown
8. `JobPosting` mapping.
9. Failure modes and user fallback.
10. Acceptance criteria for future build.
11. Test plan for future implementation.
12. Open questions / dependencies, including JOB-009.

## Acceptance Criteria

Handy build passes if:

- `docs/tasks/url-ingestion-design.md` exists.
- It explicitly covers all required constraints from PROJECT_TODO.
- It reconciles URL ingestion with Reed API ingestion and existing `ui-paste-url-prefill-brief.md`.
- It documents allowed sources and source-specific fallback concerns.
- It documents security, timeout, redirect, and untrusted external content handling.
- It clearly states this task is documentation/design only; no code implementation.

Scout QA passes if:

- The file exists at the exact target path.
- Required source list is complete.
- Required timing/redirect constraints are present.
- Relationship to JOB-002/Reed API and JOB-009 paste_fetch decision is clear.
- No implementation code was changed for this task, unless explicitly justified.

## Expected Changed Files

- `docs/tasks/url-ingestion-design.md` — new canonical design doc.
- `PROJECT_TODO.md` and `viewer/kanban_data.json` — update only after QA passes.

## Validation Commands

Documentation validation can use shell checks, for example:

```bash
test -f docs/tasks/url-ingestion-design.md
grep -Ei '10 seconds|10s' docs/tasks/url-ingestion-design.md
grep -Ei '2 seconds|2s' docs/tasks/url-ingestion-design.md
grep -Ei '8 seconds|8s' docs/tasks/url-ingestion-design.md
grep -Ei '3 redirects|maximum 3' docs/tasks/url-ingestion-design.md
grep -Ei 'indeed|linkedin|reed|glassdoor|cwjobs|cv-library|guardianjobs' docs/tasks/url-ingestion-design.md
```
