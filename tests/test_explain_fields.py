"""Regression coverage for the exact explanation evidence sent to Gemini."""
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from src.job_hunt_llm import (
    _EXPLAIN_PROMPT,
    build_explain_fields,
    explain_job_match_with_llm,
    explain_source_text,
)

_ORIGINAL_PROMPT = """\
You are a practical career advisor. A candidate is evaluating a job posting.
Return ONLY a JSON object with exactly these three fields — no explanation, no markdown, no code fences.

Required format:
{{"fit": "...", "risk": "...", "action": "..."}}

Field rules:
- "fit": 2–3 sentences. Honest verdict on overall match — go beyond the numbers. Is this genuinely worth applying for?
- "risk": 1–2 sentences. The single most important gap or concern the candidate must know about before applying.
- "action": 1–2 sentences. One specific, concrete thing they can do right now to improve their chances.

Be direct. Do not echo back scores or list data. Focus on insight the numbers miss.

CANDIDATE:
- Skills: {skills}
- Years experience: {years}
- Salary floor: {salary}
- Remote preference: {remote}
- Target roles: {target_roles}
- Industries: {industries}

JOB:
- Title: {title} at {company}
- Location: {location}
- Salary: {salary_range}
- Required skills: {required_skills}
- Preferred skills: {preferred_skills}
- Description (excerpt):
{description}

RULE-BASED SCORING SUMMARY:
- Match score: {score}/100  |  Decision: {decision}
- Strengths found: {strengths}
- Missing required skills: {missing_required}
- Missing preferred skills: {missing_preferred}
- Blockers: {blockers}"""

def _original_prompt(profile, job, analysis):
    s_min = getattr(job, "salary_min_gbp", None)
    s_max = getattr(job, "salary_max_gbp", None)
    if s_min and s_max:
        salary_range = f"£{s_min:,}–£{s_max:,}"
    elif s_min:
        salary_range = f"from £{s_min:,}"
    elif s_max:
        salary_range = f"up to £{s_max:,}"
    else:
        salary_range = "not specified"

    profile_salary = getattr(profile, "salary_floor_gbp", None)
    profile_salary_str = f"£{profile_salary:,}" if profile_salary else "not set"

    skills_str = ", ".join(s.name for s in getattr(profile, "skills", [])[:20]) or "none listed"
    blockers_str = ", ".join(b.label for b in getattr(analysis, "blockers", [])) or "none"
    strengths_str = ", ".join(getattr(analysis, "strengths", [])) or "none found"
    missing_req_str = ", ".join(getattr(analysis, "missing_required_skills", [])) or "none"
    missing_pref_str = ", ".join(getattr(analysis, "missing_preferred_skills", [])) or "none"
    description_excerpt = (getattr(job, "description_raw", "") or "")[:1500]

    return _ORIGINAL_PROMPT.format(
        skills=skills_str,
        years=getattr(profile, "years_experience", "unknown"),
        salary=profile_salary_str,
        remote=getattr(profile, "remote_preference", "not set") or "not set",
        target_roles=", ".join(getattr(profile, "target_roles", [])[:5]) or "not specified",
        industries=", ".join(getattr(profile, "industries", [])[:5]) or "not specified",
        title=getattr(job, "job_title", "Unknown"),
        company=getattr(job, "company", "Unknown"),
        location=getattr(job, "location", "Unknown") or "Unknown",
        salary_range=salary_range,
        required_skills=", ".join(getattr(job, "required_skills", [])) or "not specified",
        preferred_skills=", ".join(getattr(job, "preferred_skills", [])) or "not specified",
        description=description_excerpt,
        score=getattr(analysis, "match_score", 0),
        decision=getattr(analysis, "decision", "unknown"),
        strengths=strengths_str,
        missing_required=missing_req_str,
        missing_preferred=missing_pref_str,
        blockers=blockers_str,
    )



def _cases():
    normal = (
        NS(skills=[NS(name="SQL"), NS(name="Agile")], years_experience=12,
           salary_floor_gbp=50000, remote_preference="hybrid",
           target_roles=["Business Analyst"], industries=["Finance"]),
        NS(job_title="Business Analyst", company="Example", location="Reading",
           salary_min_gbp=50000, salary_max_gbp=60000, required_skills=["SQL"],
           preferred_skills=["Python"], description_raw="Use SQL to analyse data."),
        NS(match_score=82.5, decision="apply", strengths=["SQL"],
           missing_required_skills=[], missing_preferred_skills=["Python"],
           blockers=[NS(label="Travel")]),
    )
    optional = (NS(years_experience=None, salary_floor_gbp=None,
                   remote_preference=None),
                NS(salary_min_gbp=None, salary_max_gbp=None,
                   description_raw=None, location=None), NS())
    long = (NS(skills=[NS(name=f"Skill {i}") for i in range(40)],
               target_roles=[f"Role {i}" for i in range(8)],
               industries=[f"Industry {i}" for i in range(8)]),
            NS(description_raw="a" * 1500 + "EXCLUDED TAIL", salary_min_gbp=45000),
            NS(match_score=0, decision="skip"))
    return [normal, optional, long]


@pytest.mark.parametrize("profile,job,analysis", _cases())
def test_prompt_matches_frozen_original(profile, job, analysis):
    fields = build_explain_fields(profile, job, analysis)
    expected = _original_prompt(profile, job, analysis)
    assert _EXPLAIN_PROMPT.format(**fields) == expected
    with patch("src.job_hunt_llm._call_gemini_reasoning",
               return_value=(' {"fit":"Good fit", "risk":"Gap", "action":"Apply"}',
                             None, "test-model", False)) as call:
        result, error = explain_job_match_with_llm(profile, job, analysis)
    call.assert_called_once_with(expected)
    assert error is None
    assert result == {"fit": "Good fit", "risk": "Gap", "action": "Apply",
                      "model_used": "test-model"}
    source = explain_source_text(fields)
    assert source == expected[expected.index("CANDIDATE:\n"):]
    assert f"- Description (excerpt):\n{fields['description']}" in source
    assert f"- Match score: {fields['score']}/100  |  Decision: {fields['decision']}" in source
    assert "Required format:" not in source
    assert "You are a practical career advisor" not in source
    assert "Field rules:" not in source


def test_optional_values_and_limits_remain_exact():
    optional = build_explain_fields(*_cases()[1])
    assert optional["years"] is None
    assert optional["salary"] == "not set"
    assert optional["salary_range"] == "not specified"
    assert optional["description"] == ""
    assert optional["location"] == "Unknown"
    long = build_explain_fields(*_cases()[2])
    assert len(long["description"]) == 1500
    assert "EXCLUDED TAIL" not in explain_source_text(long)
    assert long["skills"].endswith("Skill 19")
    assert "Skill 20" not in long["skills"]
    assert long["target_roles"].endswith("Role 4")
    assert long["industries"].endswith("Industry 4")
