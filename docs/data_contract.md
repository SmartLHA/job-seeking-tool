# Data Contract Draft

**Superseded section (see below):** The job ingestion/sourcing layer has been replaced by `docs/tasks/job-ingestion-api-design.md` (Reed + Adzuna API design, Wiser review pending). The JobPosting contract below remains valid for the internal job record used in analysis and tailoring.

## Status

Proposed first non-coding artifact for approval before implementation.

## Purpose

This document defines the MVP data contract for the product.
It exists to prevent implementation from inventing structure during coding.

This contract should support:
- lightweight input via job URL and manual copied text
- deterministic scoring
- explainable Apply / Review / Skip decisions
- truthful CV tailoring
- minimal local UI display

## Design Rules

- Keep fields explicit and minimal.
- Prefer unknown/null over guessed values.
- Do not force extraction of data that cannot be obtained confidently.
- Structure must support explainability.
- Structure must support truthful downstream output.

## MVP JobPosting Contract

### Required fields
- `job_id`
- `job_title`
- `company`
- `description_raw`
- `source_type` — e.g. `url`, `copied_text`
- `source_ref` — URL or local reference string
- `location`
- `work_mode` — e.g. `remote`, `hybrid`, `onsite`, `unknown`
- `employment_type`
- `required_skills`
- `preferred_skills`
- `required_years_experience`
- `nice_to_have_years_experience`
- `domain`
- `notes`

### Optional fields
- `salary_min_gbp`
- `salary_max_gbp`

### Unknown handling
- Missing structured values should be stored as `null`, empty list, or `unknown` depending on field type.
- Unknown values must not be fabricated from weak signals.

## MVP CandidateProfile Contract

Expected truth source is limited to:
- candidate profile
- master CV

Core candidate fields expected for scoring/tailoring:
- `candidate_id`
- `name`
- `target_roles`
- `locations`
- `remote_preference`
- `salary_floor_gbp`
- `right_to_work_uk`
- `skills` — `list[Skill]`; each Skill has `name: str`, `level: str` (one of `unspecified|junior|mid|senior|expert`, default `unspecified`), `years: int | None` (default `null`), `evidence_type: str` (one of `self-reported|evidenced`, default `self-reported`). On load, plain strings are backward-coerced to `Skill(name=value)`.
- `years_experience`
- `industries`
- `achievements`
- `certifications`
- `master_cv_ref`

## MVP JobAnalysis Contract

### Required fields
- `job_id`
- `match_score`
- `score_breakdown`
- `blockers`
- `strengths`
- `missing_required_skills`
- `missing_preferred_skills`
- `risk_flags`
- `decision`
- `decision_reason`
- `confidence`

### Optional fields
- `tailoring_ready`
- `tailoring_notes`
- `ats_score` — 0–100 ATS parse-friendliness; `None` if no master CV at evaluation
- `user_decision` / `user_decision_note` — manual override of the engine decision
- **F1 — per-job ATS keyword match (advisory/display only; never feeds decisioning):**
  - `keyword_match_rate` — 0–100 coverage of the job's keywords in the CV; `None` when there is no CV or the job lists no keywords (never defaulted to 100)
  - `keywords_required_missing` — required keywords absent from the CV (list[str])
  - `keywords_preferred_missing` — preferred keywords absent from the CV (list[str])
  - `keywords_overused` — keywords repeated > 4× in the CV (anti-stuffing signal)
  - *(matched lists are derived for display = job skills − missing, so not persisted)*

## Score Breakdown Contract

`score_breakdown` should be a structured object, not a text blob.

Suggested fields:
- `skills_score`
- `experience_score`
- `location_score`
- `salary_score`
- `domain_score`
- `work_mode_score`
- `notes`

Each score field should support:
- numeric contribution
- short explanation

Skills scoring rule:
- Partial matches score proportionally: `(matched / total) * weight`
- Full matches keep the base weight, then add a configurable bonus for each extra matched skill beyond the first
- Required skills use `bonus_per_extra_required`
- Preferred skills use `bonus_per_extra_preferred`

## Blocker Contract

Each blocker should be represented as a structured item:
- `code`
- `label`
- `reason`
- `severity`

Suggested blocker categories:
- `work_authorization`
- `salary_floor`
- `location_mismatch`
- `seniority_mismatch`
- `critical_missing_requirement`

## Risk Flag Contract

Risk flags are not always blockers.
They should represent caution conditions that may still allow `Review`.

Each risk flag should include:
- `code`
- `label`
- `reason`

## Decision Contract

Allowed decisions:
- `apply`
- `review`
- `skip`

Decision output should always include:
- `decision`
- `decision_reason`
- `blocker_summary`
- `top_strengths`
- `top_gaps`

## Tailoring Contract

Tailored CV generation is only allowed when:
- decision is `apply`, or
- decision is `review` and the user manually selects it for tailoring
- truth source remains limited to candidate profile + master CV

Tailoring output should reference:
- `job_id`
- `candidate_id`
- `source_cv_ref`
- `tailored_cv_ref`
- `tailoring_notes`

## Skill Object Shape

```json
[
  {"name": "SQL", "level": "senior", "years": 7, "evidence_type": "evidenced"},
  {"name": "Stakeholder Management", "level": "unspecified", "years": null, "evidence_type": "self-reported"}
]
```

Plain strings in existing JSON files are auto-coerced on load: `"Python"` → `{"name": "Python", "level": "unspecified", "years": null, "evidence_type": "self-reported"}`.

## Minimal Example — JobPosting

```json
{
  "job_id": "sample-001",
  "job_title": "Business Analyst",
  "company": "Example Co",
  "description_raw": "We are hiring a Business Analyst with stakeholder management and process mapping experience.",
  "source_type": "copied_text",
  "source_ref": null,
  "location": "London",
  "work_mode": "hybrid",
  "salary_min_gbp": 45000,
  "salary_max_gbp": 55000,
  "employment_type": "full-time",
  "required_skills": ["stakeholder management", "process mapping"],
  "preferred_skills": ["SQL"],
  "required_years_experience": 2,
  "nice_to_have_years_experience": null,
  "domain": null,
  "notes": null
}
```

## Minimal Example — JobAnalysis

```json
{
  "job_id": "sample-001",
  "match_score": 78,
  "score_breakdown": {
    "skills_score": {"value": 32, "reason": "Strong match on required BA skills"},
    "experience_score": {"value": 18, "reason": "Experience level broadly suitable"},
    "location_score": {"value": 12, "reason": "Location acceptable"},
    "salary_score": {"value": 8, "reason": "Salary appears acceptable"},
    "domain_score": {"value": 8, "reason": "Domain fit is neutral/acceptable"},
    "work_mode_score": {"value": 0, "reason": "No strong boost or penalty"},
    "notes": []
  },
  "blockers": [],
  "strengths": ["stakeholder management", "process mapping"],
  "missing_required_skills": [],
  "missing_preferred_skills": ["SQL"],
  "risk_flags": [
    {"code": "preferred-skill-gap", "label": "Preferred skill gap", "reason": "SQL not evidenced"}
  ],
  "decision": "review",
  "decision_reason": "Strong core fit with one notable preferred-skill gap",
  "confidence": "medium",
  "tailoring_ready": true,
  "tailoring_notes": "Safe to tailor from approved profile/CV facts only"
}
```

## Approval outcome

Confirmed with Mic:
1. the required JobPosting set is minimal but sufficient for MVP, while remaining extensible later
2. all listed non-salary metadata fields are in MVP scope; salary fields remain optional
3. blocker categories are correct for MVP as currently defined
4. the score breakdown shape is acceptable for explainability in MVP
5. `review` jobs should only be tailoring-eligible when manually selected

## Remaining notes

- The contract should stay extensible for future fields.
- Inclusion in MVP does not mean every field must always be confidently populated from URL/manual text input.
- Unknown values should still remain explicit rather than guessed.
- Confidence should be treated as a first-class output separate from score.
- Storage should preserve the distinction between raw input, reviewed structured job data, and derived analysis.
