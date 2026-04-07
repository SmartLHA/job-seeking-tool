# UI Scope Draft

Status: MVP design note.

## Purpose

Define the minimal local UI for MVP without overcommitting to a heavy interface.

The UI should exist to make the core workflow simple, safe, and understandable.
It should not try to become a full productivity suite in v1.

## MVP UI Goals

The UI should let a user:
1. load/select their candidate profile and master CV
2. enter a job using URL or copied text as local context input
3. review/edit the structured job fields used for evaluation
4. see the score, blockers, strengths, gaps, and final decision
5. show tailoring readiness/status for future tailored CV work
6. record a basic outcome/status
7. review recent evaluated jobs

## Core MVP Screens

### 1. Profile / CV context screen
Purpose:
- confirm the active candidate profile
- confirm the active master CV

Should show:
- profile identity/name
- key summary fields
- current master CV reference

### 2. Job input screen
Purpose:
- accept one job at a time
- capture lightweight local context only

Input methods:
- URL
- copied job text

Should show:
- input method selector
- text area and/or URL field
- submit / continue action

Current MVP note:
- this screen does not yet perform an automated extraction step
- instead, the entered URL/text acts as local context while the reviewed structured fields are filled/edited directly

### 3. Structured field review screen
Purpose:
- let the user review/edit uncertain extracted fields before final scoring

Should support editing:
- title
- company
- location
- work mode
- employment type
- required skills
- preferred skills
- experience requirement
- domain
- notes
- salary if available

Should allow unknown values to stay unknown.

### 4. Evaluation result screen
Purpose:
- show the core decision result clearly

Should show:
- overall score
- Apply / Review / Skip
- blockers
- strengths
- missing required skills
- missing preferred skills
- score breakdown
- confidence / caution notes if relevant

### 5. Tailored CV action/view
Purpose:
- show tailoring readiness for eligible jobs
- prepare for later manual CV tailoring support

Should show:
- whether tailoring is allowed
- why tailoring is or is not allowed
- generated tailored CV reference or preview once implemented

Current MVP note:
- the current UI only shows readiness/status
- a direct tailored-CV trigger is not implemented yet

Rule:
- `review` jobs should only be tailoring-eligible when manually selected

### 6. Outcomes / history view
Purpose:
- keep a lightweight local record

Should show:
- recent evaluated jobs
- decision
- tailoring status
- current outcome status
- last updated time

## Explicitly Out of Scope for MVP UI

Do not include in MVP UI:
- full dashboard analytics
- browser automation controls
- bulk import management
- multi-user account model
- advanced reporting workspace
- heavy visual customization

## UX Principles

- Keep the flow obvious.
- Prefer clarity over cleverness.
- Show unknown values explicitly.
- Make user correction easy before scoring.
- Make explainability visible without overwhelming the user.
- Keep tailoring as a deliberate action, not an automatic surprise.
