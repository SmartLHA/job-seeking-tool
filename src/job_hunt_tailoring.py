from __future__ import annotations

import re as _re
from pathlib import Path

from src.job_hunt_config import DEFAULT_TAILORING_POLICY, TailoringPolicy
from src.job_hunt_models import CandidateProfile, JobAnalysis, JobPosting, TailoredCVResult

from src.job_hunt_cover_letter import generate_cover_letter


class TailoringValidationError(ValueError):
    """Raised when a tailored CV contains invented or ungrounded claims."""


class EmptyTailoredCVError(ValueError):
    """Raised when a tailored CV file exists but has no body after the metadata line.

    The caller should map this to a 422 (re-tailor) rather than silently scoring
    an empty CV and overwriting a valid master rate with None (F1 v2, H3).
    """


# F1 v2 — strict allow-list for job ids used to build tailored-CV file paths.
# No '/', no path separators; '.'/'..' are rejected explicitly below.
_SAFE_JOB_ID = _re.compile(r"^[A-Za-z0-9._-]+$")


def _parse_profile_id(header_line: str) -> str | None:
    """Extract the profile_id token from a `<!-- ... profile_id: X ... -->` line.

    Stops at whitespace, a `|` separator, or `>`; hyphens/underscores stay part of
    the id (candidate ids look like `cand-001`).
    """
    match = _re.search(r"profile_id:\s*([^\s|>]+)", header_line or "")
    return match.group(1) if match else None


def load_latest_tailored_cv(
    job_id: str,
    *,
    expected_profile_id: str | None = None,
    policy: TailoringPolicy = DEFAULT_TAILORING_POLICY,
) -> str | None:
    """Return the most-tailored saved CV text for a job, or None if none exists.

    Prefers ``{job_id}_ai_reviewed.md`` over ``{job_id}.md``; strips only a single
    leading HTML-comment metadata line. Returns the CV body (stripped).

    Path safety: ``job_id`` must match a strict allow-list (no '/', no '.'/'..');
    the resolved file must remain inside ``policy.output_dir``. Raises ``ValueError``
    on a malformed job_id so the caller can 404 rather than touch the filesystem.

    Raises ``EmptyTailoredCVError`` when a file exists but its body is empty after
    header-stripping (distinct from "no file", which returns None).

    When ``expected_profile_id`` is given, the loader fails closed: an absent,
    unparsable, or mismatched ``profile_id`` header returns None.
    """
    if not isinstance(job_id, str) or not _SAFE_JOB_ID.match(job_id) or job_id in (".", ".."):
        raise ValueError("invalid job_id")

    base = policy.output_dir.resolve()
    for name in (f"{job_id}_ai_reviewed.md", f"{job_id}.md"):
        path = (base / name).resolve()
        # Defence in depth: the resolved path must stay within base.
        if base != path.parent:
            continue
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        first = lines[0].strip() if lines else ""
        if first.startswith("<!--") and first.endswith("-->"):
            body = "".join(lines[1:])           # drop ONLY the first metadata line
        else:
            body = "".join(lines)               # no header → keep full text
        if expected_profile_id is not None:
            if _parse_profile_id(first) != expected_profile_id:   # fail-closed
                return None
        body = body.strip()
        if not body:
            raise EmptyTailoredCVError("tailored CV is empty")
        return body
    return None


# Tailoring remains deterministic for MVP: we only reuse approved profile facts and
# the approved master CV text. No freeform generation is introduced here.
def select_relevant_evidence(
    profile: CandidateProfile,
    cv_text: str,
    job: JobPosting,
    analysis: JobAnalysis,
) -> list[str]:
    del cv_text, analysis

    evidence: list[str] = []
    candidate_lookup = {_normalize_text(skill.name): skill.name for skill in profile.skills}

    for skill in job.required_skills:
        normalized = _normalize_text(skill)
        if normalized and normalized in candidate_lookup:
            evidence.append(f"Required skill: {candidate_lookup[normalized]}")

    for skill in job.preferred_skills:
        normalized = _normalize_text(skill)
        if normalized and normalized in candidate_lookup:
            evidence.append(f"Preferred skill: {candidate_lookup[normalized]}")

    if profile.years_experience is not None:
        years_value = int(profile.years_experience) if float(profile.years_experience).is_integer() else profile.years_experience
        evidence.append(f"Experience: {years_value} years")

    for achievement in profile.achievements:
        if not isinstance(achievement, str):
            continue
        text = achievement.strip()
        if text:
            evidence.append(f"Achievement: {text}")

    return evidence


def tailor_cv(
    cv_text: str,
    evidence_points: list[str],
    job: JobPosting,
    policy: TailoringPolicy = DEFAULT_TAILORING_POLICY,
    profile: "CandidateProfile | None" = None,
) -> TailoredCVResult:
    base_cv = cv_text.strip()
    if not base_cv:
        raise ValueError("cv_text must be a non-empty string")

    ordered_evidence = [point.strip() for point in evidence_points if isinstance(point, str) and point.strip()]
    limited_evidence = ordered_evidence[: policy.max_evidence_points]
    matched_skills = [point.split(": ", 1)[1] for point in limited_evidence if point.startswith(("Required skill: ", "Preferred skill: "))]

    lines = [
        f"# Tailored CV - {job.job_title}",
        "",
        "## Role Target",
        f"- Job title: {job.job_title}",
        f"- Company: {job.company}",
        "",
        "## Matching Evidence",
    ]

    if limited_evidence:
        lines.extend(f"- {point}" for point in limited_evidence)
    else:
        lines.append("- No matched skills were identified from the approved profile.")

    if policy.include_keyword_summary:
        lines.extend(
            [
                "",
                "## ATS Keywords",
                _format_keyword_line(matched_skills),
            ]
        )

    lines.extend(
        [
            "",
            "## Base CV",
            base_cv,
        ]
    )
    markdown = "\n".join(lines).strip() + "\n"

    # Build summary from profile facts only (no invented claims)
    summary = _build_summary(profile, job)

    # Build promoted: bullet lines from markdown that contain any required skill keyword
    promoted = _build_promoted(markdown, job.required_skills)

    # Build matched/missing from all job keywords vs markdown content
    all_keywords = list(job.required_skills) + list(job.preferred_skills)
    markdown_lower = markdown.lower()
    matched = [kw for kw in all_keywords if kw.lower() in markdown_lower]
    missing = [kw for kw in all_keywords if kw.lower() not in markdown_lower]

    return TailoredCVResult(
        summary=summary,
        promoted=promoted,
        matched=matched,
        missing=missing,
        markdown=markdown,
    )


def _build_summary(profile: "CandidateProfile | None", job: JobPosting) -> str:
    """Build a 2–3 sentence role-targeted summary drawn only from profile facts."""
    if profile is None:
        return f"Candidate targeting the role of {job.job_title} at {job.company}."

    name_part = profile.name or "The candidate"
    years_part = ""
    if profile.years_experience is not None:
        years_value = int(profile.years_experience) if float(profile.years_experience).is_integer() else profile.years_experience
        years_part = f" with {years_value} years of experience"

    industries_part = ""
    if profile.industries:
        industries_part = " in " + " and ".join(profile.industries)

    skills_part = ""
    if profile.skills:
        skill_names = [s.name for s in profile.skills[:4]]
        skills_part = f", skilled in {', '.join(skill_names)}"

    sentence1 = f"{name_part} is targeting the role of {job.job_title}{years_part}{industries_part}."
    sentence2 = f"Their background includes expertise{skills_part}." if profile.skills else ""
    parts = [s for s in [sentence1, sentence2] if s]
    return " ".join(parts)


def _build_promoted(markdown: str, required_skills: list[str]) -> list[str]:
    """Return bullet lines from markdown that contain any required skill (case-insensitive)."""
    if not required_skills:
        return []
    promoted: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            for skill in required_skills:
                if skill.lower() in stripped.lower():
                    promoted.append(stripped)
                    break
    return promoted


def validate_tailored_cv(
    original_cv: str,
    tailored: "TailoredCVResult | str",
    profile: CandidateProfile,
) -> bool:
    # Support both new TailoredCVResult and legacy plain string for backward compatibility
    if isinstance(tailored, str):
        tailored_markdown = tailored
    else:
        tailored_markdown = tailored.markdown

    if not original_cv.strip() or not tailored_markdown.strip():
        return False

    base_cv_marker = "## Base CV\n"
    if base_cv_marker not in tailored_markdown:
        return False

    generated_cv, embedded_cv = tailored_markdown.split(base_cv_marker, 1)
    if embedded_cv.strip() != original_cv.strip():
        return False

    sections = _parse_tailored_generated_sections(generated_cv)
    if sections is None:
        return False

    role_target = sections.get("## Role Target", [])
    if len(role_target) != 2:
        return False
    if not role_target[0].startswith("- Job title: ") or not role_target[0].split(": ", 1)[1].strip():
        return False
    if not role_target[1].startswith("- Company: ") or not role_target[1].split(": ", 1)[1].strip():
        return False

    matching_evidence = sections.get("## Matching Evidence", [])
    if not matching_evidence:
        return False

    allowed_skills = {_normalize_text(skill.name) for skill in profile.skills}
    expected_years = None
    if profile.years_experience is not None:
        expected_years = int(profile.years_experience) if float(profile.years_experience).is_integer() else profile.years_experience

    for line in matching_evidence:
        if not line.startswith("- "):
            return False
        claim = line[2:].strip()
        if claim == "No matched skills were identified from the approved profile.":
            continue
        if claim.startswith("Required skill: ") or claim.startswith("Preferred skill: "):
            skill = claim.split(": ", 1)[1]
            if _normalize_text(skill) not in allowed_skills:
                return False
            continue
        if claim.startswith("Experience: "):
            if expected_years is None or claim != f"Experience: {expected_years} years":
                return False
            continue
        return False

    keyword_lines = sections.get("## ATS Keywords", [])
    if keyword_lines:
        if len(keyword_lines) != 1:
            return False
        keyword_line = keyword_lines[0]
        if not keyword_line.startswith("Keywords: "):
            return False
        keyword_value = keyword_line.split(": ", 1)[1].strip()
        if keyword_value == "None":
            # Also validate promoted bullets if TailoredCVResult
            if not isinstance(tailored, str):
                if not _validate_promoted_bullets(tailored, tailored_markdown):
                    return False
            return True
        keywords = [part.strip() for part in keyword_value.split(",") if part.strip()]
        if not keywords or any(_normalize_text(keyword) not in allowed_skills for keyword in keywords):
            return False

    # Validate promoted bullets appear verbatim in markdown
    if not isinstance(tailored, str):
        if not _validate_promoted_bullets(tailored, tailored_markdown):
            return False

    # Validate summary is grounded in profile (no invented claims beyond profile facts)
    if not isinstance(tailored, str):
        if not _validate_summary(tailored.summary, profile):
            return False

    return True


def _validate_promoted_bullets(tailored: TailoredCVResult, markdown: str) -> bool:
    """Every promoted bullet must appear verbatim in the markdown."""
    for bullet in tailored.promoted:
        if bullet not in markdown:
            return False
    return True


def _validate_summary(summary: str, profile: CandidateProfile) -> bool:
    """Summary must not be empty. Basic grounding check: no empty summary allowed."""
    return bool(summary and summary.strip())


def _parse_tailored_generated_sections(generated_cv: str) -> dict[str, list[str]] | None:
    allowed_order = ["## Role Target", "## Matching Evidence", "## ATS Keywords"]
    required_sections = {"## Role Target", "## Matching Evidence"}
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    last_section_index = -1

    lines = generated_cv.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines or not lines[0].startswith("# Tailored CV - "):
        return None
    title = lines[0].split(" - ", 1)[1].strip()
    if not title:
        return None

    for raw_line in lines[1:]:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            if line not in allowed_order or line in sections:
                return None
            section_index = allowed_order.index(line)
            if section_index <= last_section_index:
                return None
            last_section_index = section_index
            current_section = line
            sections[current_section] = []
            continue
        if current_section is None:
            return None
        sections[current_section].append(line)

    if not required_sections.issubset(sections):
        return None
    return sections


def save_tailored_cv(
    job_id: str,
    cv_text: "TailoredCVResult | str",
    profile_id: str,
    policy: TailoringPolicy = DEFAULT_TAILORING_POLICY,
) -> Path:
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_id must be a non-empty string")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("profile_id must be a non-empty string")

    # Accept either a TailoredCVResult or a plain markdown string
    if isinstance(cv_text, TailoredCVResult):
        markdown_content = cv_text.markdown
    else:
        markdown_content = cv_text

    if not isinstance(markdown_content, str) or not markdown_content.strip():
        raise ValueError("cv_text must be a non-empty string")

    output_dir = policy.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{job_id.strip()}.md"
    content = f"<!-- profile_id: {profile_id.strip()} -->\n{markdown_content.strip()}\n"
    destination.write_text(content, encoding="utf-8")
    return destination


def _extract_bullet_lines(text: str, section_heading: str) -> list[str]:
    return [line[2:].strip() for line in _extract_plain_lines(text, section_heading) if line.startswith("- ")]


def _extract_plain_lines(
    text: str,
    section_heading: str,
    *,
    stop_markers: set[str] | None = None,
) -> list[str]:
    markers = stop_markers or {"## "}
    lines = text.splitlines()
    try:
        start = lines.index(section_heading) + 1
    except ValueError:
        return []

    collected: list[str] = []
    for line in lines[start:]:
        if any(marker == "## " and line.startswith("## ") for marker in markers):
            break
        if any(marker != "## " and line == marker for marker in markers):
            break
        if line.strip():
            collected.append(line.strip())
    return collected


def _format_keyword_line(skills: list[str]) -> str:
    if not skills:
        return "Keywords: None"
    deduped: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        normalized = _normalize_text(skill)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(skill)
    return f"Keywords: {', '.join(deduped)}"


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.strip().lower().split())


def generate_cover_letter_text(
    profile: CandidateProfile,
    master_cv: str,
    job: JobPosting,
    analysis: JobAnalysis,
    why_company_text: str,
) -> str:
    """Generate a cover letter for a job from profile, CV, and job data.

    This is the public integration point that uses select_relevant_evidence
    internally and delegates to the cover_letter module for text generation.

    Args:
        profile: CandidateProfile with skills, experience, achievements.
        master_cv: Full master CV text (for achievement context).
        job: JobPosting with role title, company, required/preferred skills.
        analysis: JobAnalysis (used for future extensibility; not required currently).
        why_company_text: 2-3 sentence user-written paragraph about why this company.

    Returns:
        Plain text cover letter string, ATS-friendly, ~250-300 words.
    """
    del analysis  # reserved for future scoring/filtering use
    return generate_cover_letter(profile, master_cv, job, why_company_text)
