"""Cover letter generation module.

Generates ATS-friendly plain-text cover letters from profile, master CV,
and job posting data.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.job_hunt_models import CandidateProfile, JobAnalysis, JobPosting

_VALID_TONES = {"professional", "conversational", "concise"}
_VALID_LENGTHS = {"brief", "standard", "detailed"}

# Sentence counts per paragraph by length
_LENGTH_SENTENCES = {
    "brief": (2, 2),       # (para1_max, para3_max)
    "standard": (3, 3),
    "detailed": (4, 4),
}


def generate_cover_letter_text(
    profile: CandidateProfile,
    master_cv: str,
    job: JobPosting,
    analysis: JobAnalysis,
    why_company_text: str,
    *,
    tone: str = "professional",
    length: str = "standard",
    points: list[str] | None = None,
) -> str:
    """Generate a cover letter string with optional tone, length, and points.

    Args:
        profile: CandidateProfile with skills, experience, achievements, etc.
        master_cv: Full master CV text (used for achievement context).
        job: JobPosting with role title, company, required/preferred skills.
        analysis: JobAnalysis result for the job.
        why_company_text: 2-3 sentence user-written paragraph about why this company.
        tone: "professional" | "conversational" | "concise". Defaults to "professional".
        length: "brief" | "standard" | "detailed". Defaults to "standard".
        points: Optional list of talking-point hints to weave into Paragraph 3.

    Returns:
        Plain text cover letter, ATS-friendly with no tables, columns, or markdown headers.

    Structure:
        Opening: role + company name
        Paragraph 1: role fit — required skills matched to evidence
        Paragraph 2: why_company_text (inserted verbatim)
        Paragraph 3: key achievements from profile/master CV, weaving in grounded points
        Closing: call to action
    """
    if tone not in _VALID_TONES:
        raise ValueError(f"Invalid tone: {tone!r}. Must be one of {sorted(_VALID_TONES)}")
    if length not in _VALID_LENGTHS:
        raise ValueError(f"Invalid length: {length!r}. Must be one of {sorted(_VALID_LENGTHS)}")

    para1_max, para3_max = _LENGTH_SENTENCES[length]

    # Filter points to only those grounded in profile/CV
    filtered_points = _filter_grounded_points(points or [], profile, master_cv)

    lines: list[str] = []

    # === Opening ===
    lines.append(
        f"I am writing to express my interest in the {job.job_title} role at {job.company}."
    )
    lines.append("")

    # === Paragraph 1: Role fit ===
    para1_sentences: list[str] = []
    matched_required = _match_skills(job.required_skills, profile.skills)
    if matched_required:
        para1_sentences.append(
            f"My background includes proven expertise in {_format_list(matched_required)}, "
            f"which are central to this role."
        )
    if profile.years_experience is not None and len(para1_sentences) < para1_max:
        years_str = (
            str(int(profile.years_experience))
            if float(profile.years_experience).is_integer()
            else str(profile.years_experience)
        )
        para1_sentences.append(
            f"I bring {years_str} years of professional experience delivering results "
            f"in demanding environments."
        )
    matched_preferred = _match_skills(job.preferred_skills, profile.skills)
    if matched_preferred and len(para1_sentences) < para1_max:
        para1_sentences.append(
            f"I additionally hold proficiency in {_format_list(matched_preferred)}, "
            f"which will allow me to contribute beyond the core requirements."
        )
    if not matched_required and not profile.years_experience and len(para1_sentences) < para1_max:
        para1_sentences.append(
            f"My skills and experience align well with the requirements of this role."
        )

    # Trim to max sentences for length
    para1_sentences = para1_sentences[:para1_max]
    lines.append(" ".join(para1_sentences))
    lines.append("")

    # === Paragraph 2: Why this company (verbatim) ===
    why_clean = why_company_text.strip()
    if why_clean:
        lines.append(why_clean)
        lines.append("")

    # === Paragraph 3: Achievements/skills, weaving in grounded points ===
    para3_sentences: list[str] = []
    achievements = [a.strip() for a in profile.achievements[:3] if a.strip()]
    if achievements:
        para3_sentences.append(
            "In my recent work, I have delivered impact through outcomes such as: "
            + "; ".join(achievements[:2])
            + "."
        )
    if filtered_points and len(para3_sentences) < para3_max:
        para3_sentences.append(
            "I bring particular strength in " + _format_list(filtered_points[:2]) + "."
        )
    if profile.skills and len(para3_sentences) < para3_max:
        skill_names = [s.name if hasattr(s, "name") else s for s in profile.skills[:3]]
        para3_sentences.append(
            f"My technical toolkit includes {_format_list(skill_names)}, "
            f"enabling me to add value from day one."
        )
    # Additional evidence sentence for "standard" and "detailed" lengths
    if profile.industries and len(para3_sentences) < para3_max:
        para3_sentences.append(
            f"My experience spans the {_format_list(profile.industries[:2])} sector"
            + ("s" if len(profile.industries) > 1 else "")
            + ", giving me relevant domain context for this role."
        )
    if profile.certifications and len(para3_sentences) < para3_max:
        para3_sentences.append(
            f"I hold {_format_list(profile.certifications[:2])}, which underpin my professional practice."
        )
    if not para3_sentences:
        if profile.industries:
            para3_sentences.append(
                f"I bring cross-industry insight from {_format_list(profile.industries[:2])}, "
                f"which will support my transition into this role."
            )
        else:
            para3_sentences.append(
                "I am confident my background positions me to make an immediate contribution."
            )

    para3_sentences = para3_sentences[:para3_max]
    lines.append(" ".join(para3_sentences))
    lines.append("")

    # === Closing ===
    lines.append(
        "I welcome the opportunity to discuss how my background aligns with your needs. "
        "Thank you for your consideration."
    )

    full_text = "\n".join(lines).strip()
    return _apply_tone(full_text, tone)


def generate_cover_letter(
    profile: CandidateProfile,
    master_cv: str,
    job_posting: JobPosting,
    why_company_text: str,
) -> str:
    """Generate a cover letter string.

    Args:
        profile: CandidateProfile with skills, experience, achievements, etc.
        master_cv: Full master CV text (used for achievement context).
        job_posting: JobPosting with role title, company, required/preferred skills.
        why_company_text: 2-3 sentence user-written paragraph about why this company.

    Returns:
        Plain text cover letter (~250-300 words), ATS-friendly with no tables,
        columns, or ALL-CAPS headers.

    Structure:
        Opening: role + company name
        Paragraph 1: role fit — required skills matched to evidence
        Paragraph 2: why_company_text (inserted as-is)
        Paragraph 3: key achievements from profile/master CV
        Closing: call to action + availability
    """
    lines: list[str] = []

    # === Opening ===
    candidate_name = profile.name or "Candidate"
    lines.append(f"Dear {job_posting.company} Hiring Team,")
    lines.append("")
    lines.append(
        f"I am writing to apply for the {job_posting.job_title} position at "
        f"{job_posting.company}. With my background in "
        f"{_format_list(profile.target_roles[:2])} and hands-on experience "
        f"in {_format_list(job_posting.required_skills[:2])}, I am excited "
        f"to contribute to your team."
    )
    lines.append("")

    # === Paragraph 1: Role fit ===
    para1_parts: list[str] = []
    matched_required = _match_skills(job_posting.required_skills, profile.skills)
    if matched_required:
        para1_parts.append(
            f"I bring proven expertise in {(_format_list(matched_required))}, "
            f"which are central to this role."
        )
    if profile.years_experience is not None:
        years_str = str(int(profile.years_experience)) if float(profile.years_experience).is_integer() else str(profile.years_experience)
        para1_parts.append(
            f"My {years_str} years of professional experience have equipped me "
            f"to deliver results from day one."
        )
    matched_preferred = _match_skills(job_posting.preferred_skills, profile.skills)
    if matched_preferred:
        para1_parts.append(
            f"I additionally hold proficiency in {(_format_list(matched_preferred))}, "
            f"which will allow me to contribute beyond the core requirements."
        )

    if para1_parts:
        lines.append(" ".join(para1_parts))
    else:
        # Fallback: generic role fit
        lines.append(
            f"My skills and experience align well with the requirements of this role, "
            f"and I am eager to bring my background in {_format_list(profile.industries[:1] or ['my field'])} to {job_posting.company}."
        )
    lines.append("")

    # === Paragraph 2: Why this company (user-provided, as-is) ===
    why_clean = why_company_text.strip()
    if why_clean:
        # Ensure it ends with punctuation
        if why_clean[-1] not in ".!?":
            why_clean += "."
        lines.append(why_clean)
        lines.append("")

    # === Paragraph 3: Key achievements ===
    achievement_lines: list[str] = []
    for achievement in profile.achievements[:3]:
        if achievement.strip():
            achievement_lines.append(achievement.strip())

    if achievement_lines:
        lines.append(
            "In my recent work, I have demonstrated impact through outcomes such as: "
            + " ".join(f"- {ach}" for ach in achievement_lines[:2])
        )
        lines.append("")

    # === Closing ===
    lines.append(
        "I would welcome the opportunity to discuss how my background aligns with "
        f"your needs for the {job_posting.job_title} role. I am available for a "
        "conversation at your earliest convenience and look forward to hearing from you."
    )
    lines.append("")
    lines.append(f"{candidate_name.strip()}")

    # Word count check
    full_text = "\n".join(lines)
    word_count = len(full_text.split())

    # If under 200 words, expand closing
    if word_count < 200 and profile.industries:
        # Find and expand the closing
        closing_idx = None
        for i, line in enumerate(lines):
            if "I would welcome the opportunity" in line:
                closing_idx = i
                break
        if closing_idx is not None:
            industry_context = _format_list(profile.industries[:2])
            lines[closing_idx] = (
                f"I would welcome the opportunity to discuss how my background "
                f"in {industry_context} aligns with your needs for the "
                f"{job_posting.job_title} role. I am available for a conversation "
                f"at your earliest convenience and look forward to hearing from you."
            )

    return "\n".join(lines).strip() + "\n"


def _format_list(items: list[str]) -> str:
    """Format a list of strings as a human-readable comma-separated string."""
    if not items:
        return ""
    cleaned = [item.strip() for item in items if item.strip()]
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"


def _normalize_text(value: str) -> str:
    """Normalize text for matching: lowercase, collapse whitespace."""
    return " ".join(value.strip().lower().split())


def _match_skills(job_skills: list[str], profile_skills: list) -> list[str]:
    """Return profile skill names that match job skills (case-insensitive).
    Accepts list[Skill] (with .name attribute) or list[str] for backward compat.
    """
    profile_lookup = {
        _normalize_text(s.name if hasattr(s, "name") else s): (s.name if hasattr(s, "name") else s)
        for s in profile_skills
    }
    matched: list[str] = []
    for skill in job_skills:
        normalized = _normalize_text(skill)
        if normalized and normalized in profile_lookup:
            matched.append(profile_lookup[normalized])
    return matched


def _apply_tone(text: str, tone: str) -> str:
    """Apply a light post-processing pass to adjust tone.

    - "professional": no change (current default)
    - "conversational": replace some formal phrases with informal equivalents
    - "concise": trim filler phrases for directness
    """
    if tone == "professional":
        return text
    if tone == "conversational":
        replacements = [
            ("I am writing to express my interest in", "I'd love to apply for"),
            ("I welcome the opportunity to discuss", "I'd love to discuss"),
            ("which are central to this role", "which are exactly what this role needs"),
            ("enabling me to add value from day one", "and I'm excited to bring them to this team"),
            ("I am confident my background", "I'm confident my background"),
            ("I bring", "I bring"),
        ]
        for old, new in replacements:
            text = text.replace(old, new)
        return text
    if tone == "concise":
        replacements = [
            ("In my recent work, I have delivered impact through outcomes such as: ", "Key achievements: "),
            ("enabling me to add value from day one.", "supporting immediate contribution."),
            ("which will allow me to contribute beyond the core requirements.", "extending beyond core requirements."),
            ("I bring particular strength in ", "Strengths: "),
        ]
        for old, new in replacements:
            text = text.replace(old, new)
        return text
    return text


def _filter_grounded_points(points: list[str], profile: CandidateProfile, master_cv: str) -> list[str]:
    """Return only points that are grounded in profile skills, achievements, or CV text.

    Points that cannot be matched to any profile evidence are silently dropped.
    """
    if not points:
        return []

    # Build a set of normalized evidence tokens from profile
    evidence_tokens: set[str] = set()
    for skill in profile.skills:
        name = skill.name if hasattr(skill, "name") else skill
        evidence_tokens.add(_normalize_text(name))
    for achievement in profile.achievements:
        for word in achievement.lower().split():
            evidence_tokens.add(word.strip(".,;:"))
    if master_cv:
        for word in master_cv.lower().split():
            evidence_tokens.add(word.strip(".,;:"))

    grounded: list[str] = []
    for point in points:
        point_normalized = _normalize_text(point)
        # Check if any word from the point appears in evidence
        point_words = {w.strip(".,;:") for w in point_normalized.split()}
        if point_words & evidence_tokens:
            grounded.append(point)

    return grounded


def save_cover_letter(job_id: str, letter: str, profile_id: str) -> Path:
    """Save a cover letter to output/cover_letters/<job_id>.txt and return the path."""
    output_dir = Path("output") / "cover_letters"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{job_id}.txt"
    path.write_text(letter, encoding="utf-8")
    return path