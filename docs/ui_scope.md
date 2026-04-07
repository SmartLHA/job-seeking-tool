# UI Scope — v2

Status: Updated 2026-04-07

## Purpose

Define the minimal local UI for MVP without overcommitting to a heavy interface.
The UI should exist to make the core workflow simple, safe, and understandable.
It should not try to become a full productivity suite in v1.

## New Input Flow

```
1. Paste job text OR enter job URL
         ↓
2. System parses + pre-fills structured fields
         ↓
3. User reviews and edits pre-filled fields
         ↓
4. User clicks "Evaluate" → evaluation runs
         ↓
5. Result screen shown
```

**Rule: User must explicitly review and click Evaluate — no auto-submit.**

---

## MVP UI Goals

The UI should let a user:
1. load/select their candidate profile and master CV
2. enter a job using URL or copied text as local context input
3. system parses and pre-fills structured job fields from pasted text or fetched URL
4. user reviews and edits pre-filled fields before continuing
5. see the score, blockers, strengths, gaps, and final decision
6. show tailoring readiness/status for future tailored CV work
7. record a basic outcome/status
8. review recent evaluated jobs

---

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
- capture lightweight local context

Input methods:
- **Pasted job text** → AI parses and pre-fills structured fields
- **Job URL** → system fetches webpage, extracts data, pre-fills fields

Should show:
- input method selector (paste text | paste URL)
- text area for pasted job description
- URL field for job posting link
- submit / continue action
- parsing status indicator

Error handling:
- if parsing fails → show raw text, let user fill fields manually
- if URL fetch fails → show error, offer manual paste as fallback
- respect robots.txt for URL fetching

### 3. Structured field review screen
Purpose:
- let the user review and edit pre-filled fields before evaluation

Behavior:
- fields are pre-filled from step 2
- user can correct any field before clicking Evaluate
- unknown values remain unknown (not forced to guess)

Should support editing:
- title, company, location, work mode, employment type
- required skills, preferred skills
- experience requirement, domain, salary
- notes

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

Rule:
- `review` jobs require manual user selection before tailoring
- `apply` jobs are automatically tailoring-ready

### 6. Outcomes / history view
Purpose:
- keep a lightweight local record

Should show:
- recent evaluated jobs
- decision
- tailoring status
- current outcome status
- last updated time

---

## Explicitly Out of Scope for MVP UI

Do not include in MVP UI:
- full dashboard analytics
- browser automation controls
- bulk import management
- multi-user account model
- advanced reporting workspace
- heavy visual customization
- auto-apply or job submission
- scraping beyond single URL at a time
- background job monitoring

---

## UX Principles

- Keep the flow obvious.
- Prefer clarity over cleverness.
- Show unknown values explicitly.
- Make user correction easy before scoring.
- Make explainability visible without overwhelming the user.
- Keep tailoring as a deliberate action, not an automatic surprise.
- Pre-fill with AI parsing — but user always reviews before Evaluate.
