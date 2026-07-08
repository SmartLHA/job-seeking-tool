"""LLM integration — skill extraction and job explanation via Google Gemini.

Uses the Gemini REST API directly (no extra package needed beyond `requests`).

Environment variables:
  GOOGLE_API_KEY  (required)  Your Google AI Studio API key
  GEMINI_MODEL    (optional)  Model name (default: gemini-2.0-flash)

Falls back to keyword extraction when the API is unreachable or returns bad output.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

_DEFAULT_MODEL  = "gemini-3.1-flash-lite"   # primary  (skill extraction)
_FALLBACK_MODEL = "gemini-2.5-flash-lite"   # fallback (skill extraction, 404 only)
_ANALYSIS_MODEL           = "gemini-3-flash-preview"  # job analysis primary — supports thinking
_ANALYSIS_FALLBACK_1      = "gemini-2.5-flash"        # first fallback — also supports thinking
_ANALYSIS_FALLBACK_2      = "gemini-3.1-flash-lite"   # second fallback — no thinking
# Thinking budget cut from 8000 → 2048: on the Gemini-3 preview models a large
# budget drives latency past the timeout. max_output_tokens MUST be set on Gemini 3
# (it's a COMBINED thinking+output cap) or the call can hang indefinitely — so every
# request now passes one. See ai.google.dev/gemini-api/docs/gemini-3.
_ANALYSIS_THINKING_BUDGET = 2048                      # tokens; 0 = off
_ANALYSIS_OUTPUT_TOKENS   = 2048                      # headroom for the JSON answer
_ANALYSIS_MAX_TOKENS      = _ANALYSIS_THINKING_BUDGET + _ANALYSIS_OUTPUT_TOKENS  # combined cap
_SKILL_MAX_TOKENS         = 1024                      # skill-extraction answer is small
_GEMINI_BASE    = "https://generativelanguage.googleapis.com/v1beta/models"
_TIMEOUT_SECONDS        = 30
_ANALYSIS_TIMEOUT       = 60   # thinking calls take longer
_MAX_DESCRIPTION_CHARS  = 8_000
_MAX_CV_CHARS           = 12_000


def _api_key() -> str | None:
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")


def _model() -> str:
    """Return the configured model name (overridable via GEMINI_MODEL env var)."""
    return os.getenv("GEMINI_MODEL", _DEFAULT_MODEL)


class RateLimited(Exception):
    """Raised by the worker-facing path when the ENTIRE model chain failed with
    HTTP 429 (rate limit). Used by the D6 LLM worker to back off + requeue, as
    distinct from a 404/503/bad-output failure which should fail fast."""


def _call_gemini_model(
    prompt: str,
    model: str,
    key: str,
    thinking_budget: int | None = None,
    timeout: int = _TIMEOUT_SECONDS,
    max_output_tokens: int | None = None,
) -> tuple[str | None, str | None, bool, str | None]:
    """Call one specific Gemini model.

    Returns (text, error, should_try_fallback, reason).
    ``reason`` classifies the failure so the chain can tell 429 from 404/503/timeout
    (C7): one of None (success), "rate_limited", "not_found", "server_error",
    "timeout", "fatal". ``should_try_fallback`` is True for 404/429/503 AND timeout
    (a slow model should fall through to a faster/no-thinking one).
    ``max_output_tokens`` caps the COMBINED thinking+output budget — required on
    Gemini 3 or the request can hang indefinitely.
    thinking_budget: None = no thinking config; 0 = thinking off; >0 = thinking on.
    """
    url = f"{_GEMINI_BASE}/{model}:generateContent"
    gen_config: dict = {"temperature": 0.1}
    if thinking_budget is not None:
        gen_config["thinkingConfig"] = {"thinkingBudget": thinking_budget}
    if max_output_tokens is not None:
        gen_config["maxOutputTokens"] = max_output_tokens
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_config,
    }

    try:
        resp = requests.post(url, params={"key": key}, json=payload, timeout=timeout)
    except requests.exceptions.ConnectionError:
        return None, "Cannot reach Gemini API — check your internet connection", False, "fatal"
    except requests.exceptions.Timeout:
        # Slow model: fall through to the next (faster/no-thinking) model in the chain.
        return None, f"Gemini API timed out after {timeout}s — trying next model", True, "timeout"

    if resp.status_code == 404:
        return None, f"Model {model!r} not found (404)", True, "not_found"
    if resp.status_code == 429:
        return None, f"Model {model!r} rate limited (429) — trying next model", True, "rate_limited"
    if resp.status_code == 503:
        return None, f"Model {model!r} unavailable (503 — high demand) — trying next model", True, "server_error"
    if resp.status_code == 401:
        return None, "Invalid GOOGLE_API_KEY — check your key in .env", False, "fatal"
    if not resp.ok:
        return None, f"Gemini API error {resp.status_code}: {resp.text[:200]}", False, "fatal"

    try:
        data = resp.json()
        # Thinking models return a "thought" part followed by the real answer part.
        # We want the last non-thought text part.
        parts = data["candidates"][0]["content"]["parts"]
        text = next(
            (p["text"] for p in reversed(parts) if not p.get("thought") and "text" in p),
            None,
        )
        if text is None:
            return None, "Gemini returned no text part in response", False, "fatal"
        return text.strip(), None, False, None
    except (KeyError, IndexError, ValueError) as exc:
        return None, f"Gemini returned unexpected response shape: {exc}", False, "fatal"


def _call_gemini(prompt: str) -> tuple[str | None, str | None]:
    """Send a prompt to the fast skill-extraction model, with 404 fallback.

    Returns (text, error).
    """
    key = _api_key()
    if not key:
        return None, "GOOGLE_API_KEY not set — add it to your environment or .env file"

    primary = _model()
    text, error, try_fallback, _ = _call_gemini_model(prompt, primary, key, max_output_tokens=_SKILL_MAX_TOKENS)
    if text is not None:
        return text, None

    if try_fallback and primary != _FALLBACK_MODEL:
        logger.warning("Primary model %r unavailable — retrying with fallback %r", primary, _FALLBACK_MODEL)
        text, error, _, _ = _call_gemini_model(prompt, _FALLBACK_MODEL, key, max_output_tokens=_SKILL_MAX_TOKENS)
        if text is not None:
            return text, None

    return None, error


def _call_gemini_reasoning(prompt: str) -> tuple[str | None, str | None, str | None, bool]:
    """Send a prompt using the analysis model chain with high thinking budget.

    Chain (on 404/429/503):
      1. gemini-3-flash-preview  + thinking budget  (primary)
      2. gemini-2.5-flash        + thinking budget  (first fallback)
      3. gemini-3.1-flash-lite   no thinking        (second fallback)

    Returns (text, error, model_used, all_rate_limited).
    ``all_rate_limited`` is True only when at least one model was attempted and
    EVERY attempt failed with 429 (no success, no 404/503/other) — the D6 worker
    uses it to raise RateLimited and back off (C7).
    """
    key = _api_key()
    if not key:
        return None, "GOOGLE_API_KEY not set — add it to your environment or .env file", None, False

    reasons: list[str | None] = []

    def _all_rl() -> bool:
        return bool(reasons) and all(r == "rate_limited" for r in reasons)

    # 1 — primary with thinking
    text, error, try_fallback, reason = _call_gemini_model(
        prompt, _ANALYSIS_MODEL, key,
        thinking_budget=_ANALYSIS_THINKING_BUDGET,
        timeout=_ANALYSIS_TIMEOUT,
        max_output_tokens=_ANALYSIS_MAX_TOKENS,
    )
    if text is not None:
        logger.info("Gemini reasoning OK (model=%s)", _ANALYSIS_MODEL)
        return text, None, _ANALYSIS_MODEL, False
    reasons.append(reason)
    if not try_fallback:
        return None, error, None, _all_rl()

    # 2 — first fallback with thinking
    logger.warning("%r unavailable (404/429/503) — trying %r with thinking", _ANALYSIS_MODEL, _ANALYSIS_FALLBACK_1)
    text, error, try_fallback, reason = _call_gemini_model(
        prompt, _ANALYSIS_FALLBACK_1, key,
        thinking_budget=_ANALYSIS_THINKING_BUDGET,
        timeout=_ANALYSIS_TIMEOUT,
        max_output_tokens=_ANALYSIS_MAX_TOKENS,
    )
    if text is not None:
        logger.info("Gemini reasoning OK (model=%s)", _ANALYSIS_FALLBACK_1)
        return text, None, _ANALYSIS_FALLBACK_1, False
    reasons.append(reason)
    if not try_fallback:
        return None, error, None, _all_rl()

    # 3 — second fallback, no thinking (fast safety net for slow/timed-out thinking models)
    logger.warning("%r unavailable — trying %r without thinking", _ANALYSIS_FALLBACK_1, _ANALYSIS_FALLBACK_2)
    text, error, try_fallback, reason = _call_gemini_model(
        prompt, _ANALYSIS_FALLBACK_2, key,
        timeout=_TIMEOUT_SECONDS,
        max_output_tokens=_ANALYSIS_OUTPUT_TOKENS,
    )
    if text is not None:
        logger.info("Gemini reasoning OK (model=%s, no thinking)", _ANALYSIS_FALLBACK_2)
        return text, None, _ANALYSIS_FALLBACK_2, False
    reasons.append(reason)
    return None, error, None, _all_rl()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SKILL_EXTRACT_PROMPT = """\
Extract skills from this job description and return ONLY a JSON object — no explanation, no markdown.

Required format:
{{"required": ["skill1", "skill2"], "preferred": ["skill3", "skill4"]}}

Rules:
- "required" = explicitly required, essential, or must-have skills / tools / technologies
- "preferred" = nice-to-have, desired, advantageous, or bonus skills / tools / technologies
- Include: technical skills, tools, software, methodologies, frameworks, certifications, domain knowledge
- Exclude: vague soft skills (e.g. "communication", "teamwork") unless explicitly stated as a hard requirement
- Use concise canonical terms ("SQL" not "knowledge of SQL databases")
- If a skill's required/preferred status is unclear, put it in "preferred"
- Never invent skills not present in the description
- Return empty arrays if none found

Job description:
{description}"""

_EXPLAIN_PROMPT = """\
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

_AI_CV_REVIEW_PROMPT = """\
You are a professional CV editor. Lightly rewrite the candidate's CV to better match the target job — without inventing anything.

Return ONLY a JSON object — no explanation, no markdown fences, no commentary outside the JSON.

Required format:
{{"reviewed_cv": "...", "changes": ["change 1", "change 2", ...]}}

Field rules:
- "reviewed_cv": the full rewritten CV text, preserving all section headings, bullet-point style, and line structure
- "changes": a list of 3–8 short plain-English descriptions of what you changed (e.g. "Rephrased summary to lead with project management experience", "Moved SQL bullet to top of Technical Skills")

═══ ABSOLUTE RULES (never break these) ═══
1. NEVER add experience, job titles, companies, dates, or responsibilities not already in the original CV
2. NEVER change any numbers (years, percentages, team sizes, budgets, dates)
3. NEVER claim a skill the candidate has not already demonstrated in the CV or profile skills list
4. NEVER add a new section or remove an existing section
5. If the CV has no evidence for a job requirement — leave that gap as-is; do NOT bridge it with invented content

═══ PERMITTED changes only ═══
1. Rephrase existing sentences to use language closer to the job keywords (e.g. "built reports" → "built data visualisation reports" if job requires data visualisation and the CV already describes building reports)
2. Reorder bullet points within each section — put the most relevant bullets first for this job
3. Strengthen the opening summary / profile statement to lead with what this job is looking for, using only facts already in the CV and the candidate profile
4. Where a tool or skill is clearly evidenced in the CV but not named explicitly, you may name it inline (e.g. "managed project workspace in Teams" → "managed project workspace in Microsoft Teams")

═══ TARGET JOB ═══
Title: {title} at {company}
Required skills: {required_skills}
Preferred skills: {preferred_skills}
Job description (excerpt):
{description}

═══ CANDIDATE PROFILE FACTS (reference only — do not invent beyond these) ═══
Years experience: {years}
Target roles: {target_roles}
Industries: {industries}
Profile skills: {skills}

═══ ORIGINAL CV (rewrite this) ═══
{cv_text}"""

_CV_SKILL_EXTRACT_PROMPT = """\
Extract the professional skills demonstrated in this CV and return ONLY a JSON object — no explanation, no markdown.

Required format:
{{"skills": ["Skill 1", "Skill 2", ...]}}

Rules:
- Include technical skills, tools, software, methodologies, frameworks, and domain knowledge the candidate has used
- Include soft skills only if they are clearly evidenced by specific examples in the CV (e.g. "Stakeholder Management" if they describe managing stakeholders)
- Use standard industry names: "SQL" not "database querying", "Agile" not "agile ways of working", "Stakeholder Management" not "managing stakeholders"
- Each skill must be 1–5 words and Title Case
- Exclude: job titles, company names, academic degrees, personal traits without evidence (e.g. "hardworking")
- Never invent skills not supported by the CV text
- Return an empty array if no skills can be identified

CV:
{cv_text}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json_from_text(raw: str) -> dict | None:
    """Strip markdown fences and extract the first {...} JSON object from raw text."""
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].lstrip("json").strip() if len(parts) >= 2 else raw

    brace_start = raw.find("{")
    brace_end = raw.rfind("}")
    if brace_start != -1 and brace_end != -1:
        raw = raw[brace_start: brace_end + 1]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Public API  (signatures unchanged — callers need no modification)
# ---------------------------------------------------------------------------

def explain_job_match_with_llm(
    profile: "Any",
    job: "Any",
    analysis: "Any",
    *,
    raise_on_rate_limit: bool = False,
) -> tuple[dict[str, str] | None, str | None]:
    """Generate a structured explanation of the job–candidate fit via Gemini.

    Returns ({"fit": ..., "risk": ..., "action": ..., "model_used": ...}, None) on success,
    or (None, error_message) on failure.

    ``raise_on_rate_limit`` (D6 worker): when True and the whole model chain failed
    with 429, raise :class:`RateLimited` instead of returning an error string, so the
    worker can back off + requeue rather than fail-fast."""
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

    prompt = _EXPLAIN_PROMPT.format(
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

    raw, error, model_used, all_rate_limited = _call_gemini_reasoning(prompt)
    if raw is None:
        if all_rate_limited and raise_on_rate_limit:
            raise RateLimited(error or "Gemini rate limited (429)")
        logger.warning("Gemini job explanation failed: %s", error)
        return None, error

    parsed = _parse_json_from_text(raw)
    if parsed is None:
        msg = "Gemini returned non-JSON output for job explanation"
        logger.warning("%s | raw: %.200s", msg, raw)
        return None, msg

    fit    = str(parsed.get("fit", "")).strip()
    risk   = str(parsed.get("risk", "")).strip()
    action = str(parsed.get("action", "")).strip()
    if not fit:
        return None, "Gemini response missing 'fit' field"

    result = {"fit": fit, "risk": risk, "action": action, "model_used": model_used or "unknown"}
    logger.info("Gemini job explanation OK (model=%s, fit=%d chars)", model_used, len(fit))
    return result, None


_MAX_CV_REVIEW_CHARS = 15_000   # generous — full CV needed for quality output


def ai_review_cv_with_llm(
    cv_text: str,
    profile: "Any",
    job: "Any",
    analysis: "Any",
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Use Gemini to lightly rewrite a CV to better match a job, without inventing facts.

    Permitted: rephrase sentences, reorder bullets, strengthen summary, inject evidenced keywords.
    Forbidden: invent experience, change numbers, add unclaimed skills, add/remove sections.

    Returns ({"reviewed_cv": str, "changes": list[str]}, None, model_used) on success,
    or (None, error_message, None) on failure.
    """
    truncated_cv = cv_text[:_MAX_CV_REVIEW_CHARS]
    description_excerpt = (getattr(job, "description_raw", "") or "")[:2000]
    skills_str = ", ".join(s.name for s in getattr(profile, "skills", [])[:30]) or "none listed"

    prompt = _AI_CV_REVIEW_PROMPT.format(
        title=getattr(job, "job_title", "Unknown"),
        company=getattr(job, "company", "Unknown"),
        required_skills=", ".join(getattr(job, "required_skills", [])) or "not specified",
        preferred_skills=", ".join(getattr(job, "preferred_skills", [])) or "not specified",
        description=description_excerpt,
        years=getattr(profile, "years_experience", "unknown"),
        target_roles=", ".join(getattr(profile, "target_roles", [])[:5]) or "not specified",
        industries=", ".join(getattr(profile, "industries", [])[:5]) or "not specified",
        skills=skills_str,
        cv_text=truncated_cv,
    )

    raw, error, model_used, _all_rl = _call_gemini_reasoning(prompt)
    if raw is None:
        logger.warning("Gemini CV review failed: %s", error)
        return None, error, None

    parsed = _parse_json_from_text(raw)
    if parsed is None:
        msg = "Gemini returned non-JSON output for CV review"
        logger.warning("%s | raw: %.200s", msg, raw)
        return None, msg, None

    reviewed_cv = str(parsed.get("reviewed_cv", "")).strip()
    if not reviewed_cv:
        return None, "Gemini response missing 'reviewed_cv' field", None

    changes = [str(c).strip() for c in parsed.get("changes", []) if str(c).strip()]

    result = {"reviewed_cv": reviewed_cv, "changes": changes}
    logger.info("Gemini CV review OK (model=%s, cv_chars=%d, changes=%d)", model_used, len(reviewed_cv), len(changes))
    return result, None, model_used


def extract_skills_with_llm(description: str) -> tuple[dict[str, list[str]] | None, str | None]:
    """Call Gemini to extract required and preferred skills from a job description.

    Returns ({"required": [...], "preferred": [...]}, None) on success,
    or (None, error_message) on failure so the caller can fall back to keyword extraction.
    """
    truncated = description[:_MAX_DESCRIPTION_CHARS]
    prompt = _SKILL_EXTRACT_PROMPT.format(description=truncated)

    raw, error = _call_gemini(prompt)
    if raw is None:
        logger.warning("Gemini skill extraction failed: %s — falling back to keyword extraction", error)
        return None, f"{error} — using keyword extraction instead"

    parsed = _parse_json_from_text(raw)
    if parsed is None:
        msg = "Gemini returned non-JSON output — using keyword extraction instead"
        logger.warning("Gemini non-JSON skill extraction: %.200s", raw)
        return None, msg

    required = [str(s).strip() for s in parsed.get("required", []) if str(s).strip()]
    preferred = [str(s).strip() for s in parsed.get("preferred", []) if str(s).strip()]
    logger.info(
        "Gemini skill extraction OK (model=%s) — %d required, %d preferred",
        _model(), len(required), len(preferred),
    )
    return {"required": required, "preferred": preferred}, None


def extract_cv_skills_with_llm(cv_text: str) -> tuple[list[str] | None, str | None]:
    """Call Gemini to extract skills a candidate has from their CV text.

    Returns (skill_list, None) on success,
    or (None, error_message) on failure so the caller can fall back to keyword extraction.
    """
    truncated = cv_text[:_MAX_CV_CHARS]
    prompt = _CV_SKILL_EXTRACT_PROMPT.format(cv_text=truncated)

    raw, error = _call_gemini(prompt)
    if raw is None:
        logger.warning("Gemini CV extraction failed: %s — falling back to keyword extraction", error)
        return None, f"{error} — using keyword extraction instead"

    parsed = _parse_json_from_text(raw)
    if parsed is None:
        msg = "Gemini returned non-JSON CV output — using keyword extraction instead"
        logger.warning("Gemini non-JSON CV extraction: %.200s", raw)
        return None, msg

    skills = [str(s).strip() for s in parsed.get("skills", []) if str(s).strip()]
    logger.info("Gemini CV skill extraction OK (model=%s) — %d skills", _model(), len(skills))
    return skills, None
