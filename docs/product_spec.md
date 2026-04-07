# Product Specification

## Status

Draft derived from planning discussions with Mic. This file should be updated as product decisions are confirmed.

## Working Product Description

A local-first AI job search decision-support and application-preparation product for the UK market.

## Core Goals

- Ingest jobs
- Structure job data
- Score job fit
- Decide Apply / Review / Skip
- Generate truthful tailored CVs and cover letters
- Track outcomes over time

## Non-Goals

- Mass auto-apply
- Browser automation
- Background account interaction
- Fabricated candidate claims
- Raw application-volume optimization

## Product Principles

- Deterministic logic first
- Explainability
- Local-first privacy
- Truthful output
- Modular implementation
- Small testable steps

## MVP Scope

A successful MVP can:
1. load a candidate profile
2. load a master CV
3. ingest jobs from text or JSON
4. parse jobs into structure
5. check blockers
6. score job fit
7. decide Apply / Review / Skip
8. generate a daily report
9. optionally generate a truthful tailored CV and cover letter for shortlisted jobs
10. record outcomes locally

## Open Questions

- Final public product name
- Primary target user for v1
- MVP input priority
- URL ingestion scope
- truth-source structure for approved evidence points
- tailoring timing within MVP
- scoring philosophy
- storage source-of-truth strategy
- duplicate detection rule
- UI timing
