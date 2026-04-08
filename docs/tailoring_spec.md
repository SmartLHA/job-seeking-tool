# Tailoring Spec

## Scope
- MVP tailored CV generation only
- Truth sources: approved `CandidateProfile` plus approved `master_cv`
- Deterministic flow only, no LLM dependency

## Evidence Selection
`select_relevant_evidence(profile, cv_text, job, analysis)`
- Uses matched `required_skills` first
- Then uses matched `preferred_skills`
- Then appends `years_experience` when available
- Ignores `achievements` and `certifications`
- Produces ordered evidence strings for downstream formatting

## Tailored CV Output
`tailor_cv(cv_text, evidence_points, job)`
- Generates markdown for ATS-friendly review
- Includes role target metadata
- Includes matching evidence bullets in deterministic order
- Includes ATS keyword summary from matched skills only
- Embeds the original CV unchanged under `## Base CV`

## Validation
`validate_tailored_cv(original_cv, tailored_cv, profile)`
- Rejects blank or structurally incomplete output
- Confirms embedded base CV exactly matches the approved original CV
- Confirms evidence bullets reference only approved profile skills or approved years of experience
- Rejects unsupported keywords or unknown evidence lines

## Persistence
`save_tailored_cv(job_id, cv_text, profile_id)`
- Writes markdown to `output/tailored_cvs/<job_id>.md`
- Adds a lightweight `profile_id` comment header for traceability

## Review Gate
`evaluate_reviewed_job(..., review_selected_for_tailoring=False)`
- `apply` decisions are tailoring-ready immediately
- `review` decisions stay blocked unless manually selected
- `skip` decisions are never tailoring-ready
