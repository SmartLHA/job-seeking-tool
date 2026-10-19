# Scoring consistency — Slice 1 (2026-10-19)

**Status:** implemented, not committed. Approved by Mike 2026-10-19 ("do slice 1").
**Origin:** design-council review (Claude plan + independent reviewer agent; Codex unavailable in Cowork). Research: knowledge-wiki `Notes/job-search-automation-sources.md`.

## Problem
The match score is deterministic (weighted rules); the LLM is advisory only. Perceived "instability near the cut-off" came from inconsistent thresholds, not LLM scoring:
- Decision policy: Apply ≥80, Review 65–<80, Skip <65 (`src/job_hunt_config.py` DecisionPolicy)
- Review-queue colour used 75/50 (`src/ui_render.py`)
- Grade bands hardcoded 80/72/65/50 (`src/job_hunt_qualitative.py`), against architecture_guardrails "thresholds in config"
- Critical-risk reason below 65 falsely said the score "would otherwise qualify for apply"; in 65–79 the critical risk was not mentioned
- Queue truncated the score (`int()`) while reasons rounded (`:.0f`): 79.6 showed "79" in the queue but "Score 80" in the reason

## Changes (decisions unchanged)
- `job_hunt_decision.py`: `format_score()` — one display rule (truncate). Reason text per band for critical risks.
- `job_hunt_config.py`: `GRADE_B_THRESHOLD = 72.0`, `GRADE_D_THRESHOLD = 50.0`.
- `job_hunt_qualitative.py`: grade A/C use `DEFAULT_DECISION_POLICY` thresholds; B/D from config. Grade output unchanged.
- `ui_render.py`: module-level `score_tone()` from the decision policy; queue uses it and `format_score()`.
- **Visible change:** queue colour boundaries move from 75/50 to 80/65 (75–79 now amber not green; 50–64 now grey/skip not amber).
- `_subscore_bar` deliberately unchanged (dimension subscores are a different scale).

## Tests
`tests/test_decision_boundaries.py` (37 cases): exact boundaries 80.0/79.99/65.0/64.99, low-confidence gate, critical risk in each band, marginal-source-quality default-policy-only, display rule, grade/policy alignment, queue tone == decision.

## Not in this slice (separate approval)
- 1b: digest filter "score ≥70" hides Review jobs 65–69 — needs decision on filter semantics and migration of saved values.
- 1c: record which skill extractor ran (Gemini vs keyword fallback) per job.
- 2: borderline flag — only after measuring score variance on 20–30 re-extracted jobs.
- 3: qualitative rubric range descriptors (replace 1/3/5 anchors).
- Open: should a very low score with a critical risk go to Review (current spec) or Skip? Behaviour kept; text fixed.
