# Architecture Guardrails

Status: pre-implementation guardrail note.

## Purpose

Capture the architectural boundaries that must remain intact during implementation.
These rules exist to prevent scope creep, logic coupling, and trust erosion.

## Guardrail 1 — Preserve state separation

Keep these as separate states:
1. raw input/source
2. reviewed structured job data
3. derived analysis output

Do not overwrite one layer with another.

Why:
- auditability
- reproducibility
- debugging clarity
- trust in the final recommendation

## Guardrail 2 — Keep evaluation modules separate

Preserve this split:
- `eligibility.py` → blockers / hard constraints
- `scoring.py` → explainable numeric contributions
- `decision.py` → Apply / Review / Skip from score + blockers + risks

Do not blur these into one large mixed module.

## Guardrail 3 — Keep lightweight input lightweight

MVP input handling may:
- accept one URL at a time
- accept one copied-text job at a time
- extract minimum fields for evaluation
- leave uncertainty explicit

MVP input handling may not become:
- crawling
- batch import
- broad source integration
- heavy parser architecture

## Guardrail 4 — Force correction before trusted scoring

If extracted fields are uncertain, the user must be able to review/edit them before the score is treated as trustworthy.

The system should prefer:
- explicit unknowns
- editable fields
- visible uncertainty

over hidden guessing.

## Guardrail 5 — Treat confidence as separate from score

`confidence` is not the same as `match_score`.

Use confidence to reflect:
- input completeness
- extraction certainty
- amount of reviewed vs unknown data

A high-looking score with weak supporting data should not appear equally trustworthy.

## Guardrail 6 — Keep tailoring downstream

Tailoring should consume:
- candidate profile
- master CV
- reviewed structured job data
- derived analysis

Tailoring should not bypass the structured evaluation flow by working directly from raw input alone.

## Guardrail 7 — Keep truth boundaries strict

Tailoring may:
- reorder
- emphasize
- compress

Tailoring may not:
- invent
- imply unsupported claims
- convert desired job keywords into candidate evidence

## Guardrail 8 — Keep policy in config where practical

Thresholds, weights, and decision policies should live in config rather than being spread as magic constants across modules.

## Guardrail 9 — Do not overbuild duplicate logic in MVP

Because MVP is not a broad ingestion product, duplicate handling should stay modest.
A duplicate warning is more important than a sophisticated deduplication engine at this stage.
