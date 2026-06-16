# JOB-001 — Tailoring Truth Validation Design

**Status:** Draft for Wiser review  
**Owner:** SilverHand design → Wiser review → Handy build → Scout QA  
**Date:** 2026-05-13

## Problem

`validate_tailored_cv()` is no longer an unconditional `True` stub, but current validation is still too permissive for the intent of JOB-001: a tailored CV must not contain invented candidate claims outside approved sources.

Current observed gaps in `src/job_hunt_tailoring.py`:

1. Unknown/extra top-level sections can be inserted before `## Base CV` and may not be rejected.
2. Only the first line under `## ATS Keywords` is checked; additional factual lines in that section can be ignored.
3. Validation is tied to the deterministic output shape but does not explicitly enforce the allowed section set.
4. Tests cover invented skill and modified base CV, but not hidden unsupported claims or malformed/extra sections.

## Goal

Make `validate_tailored_cv(original_cv, tailored_cv, profile)` a strict structural and truthfulness gate for the deterministic tailored CV format.

The validator should return `True` only when:

- The original CV is embedded exactly under `## Base CV`.
- The tailored CV uses only the approved deterministic sections.
- Matching evidence claims are supported by `CandidateProfile.skills` or `CandidateProfile.years_experience`.
- ATS keywords are either `Keywords: None` or a comma-separated subset of `CandidateProfile.skills`.
- No additional generated candidate-claim sections or unexpected lines exist outside the deterministic template.

## Non-goals

- Do not introduce LLM generation.
- Do not expand evidence to achievements or certifications.
- Do not change the public function signature unless Handy finds a strong reason and reports it before implementation.
- Do not validate job title/company against candidate profile; those are job metadata, not candidate claims. Keep them constrained to the deterministic `## Role Target` section shape.

## Proposed Implementation

### 1. Strict section parsing

In `src/job_hunt_tailoring.py`, update validation to parse the generated portion before `## Base CV` into allowed sections only:

Allowed top-level structure:

```text
# Tailored CV - <non-empty title>

## Role Target
- Job title: <non-empty>
- Company: <non-empty>

## Matching Evidence
- <allowed evidence bullet(s)>

[optional]
## ATS Keywords
Keywords: <None or allowed skill list>

## Base CV
<exact original_cv.strip()>
```

Reject if any unexpected `##` section appears before `## Base CV`.
Reject if any unexpected non-empty line appears in a known section.

### 2. Matching Evidence validation

Allowed bullets:

- `No matched skills were identified from the approved profile.`
- `Required skill: <skill in profile.skills>`
- `Preferred skill: <skill in profile.skills>`
- `Experience: <profile.years_experience> years`

Reject all other bullets or loose lines.

### 3. ATS Keywords validation

Allowed shape:

- Exactly one non-empty line: `Keywords: None`, or
- `Keywords: skill1, skill2, ...` where every keyword normalizes to a value in `profile.skills`.

Reject extra lines under `## ATS Keywords`.
Reject unsupported keywords.

### 4. Base CV validation

Keep current exact check:

- `tailored_cv` must contain `## Base CV\n`.
- Text after the marker, stripped, must equal `original_cv.strip()` exactly.

### 5. Tests

Add regression tests in `tests/test_tailoring.py` for:

1. Reject unexpected generated section before `## Base CV`.
2. Reject extra unsupported line under `## ATS Keywords`.
3. Reject malformed role target lines.
4. Accept current deterministic `tailor_cv()` output.
5. Keep existing invented skill and modified base CV rejections.

## Acceptance Criteria

- `python3 -m pytest tests/test_tailoring.py -v` passes.
- Existing valid tailored CV output remains accepted.
- Hidden unsupported claims before `## Base CV` are rejected.
- Extra lines in `## ATS Keywords` are rejected.
- No broad rewrite of unrelated modules.

## Expected Changed Files

- `src/job_hunt_tailoring.py`
- `tests/test_tailoring.py`
- `docs/tailoring_spec.md` only if implementation changes the documented status/behaviour
- `PROJECT_TODO.md` and `viewer/kanban_data.json` only after QA passes, to move JOB-001 status

## Validation Commands

```bash
python3 -m pytest tests/test_tailoring.py -v
```

Optional regression check if time allows:

```bash
python3 -m pytest tests/test_tailoring.py tests/test_profile.py -v
```
