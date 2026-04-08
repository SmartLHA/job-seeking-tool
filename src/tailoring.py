from __future__ import annotations

from pathlib import Path

from src.config import DEFAULT_TAILORING_POLICY, TailoringPolicy
from src.models import CandidateProfile, JobAnalysis, JobPosting


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
    candidate_lookup = {_normalize_text(skill): skill.strip() for skill in profile.skills if skill.strip()}

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

    return evidence


def tailor_cv(
    cv_text: str,
    evidence_points: list[str],
    job: JobPosting,
    policy: TailoringPolicy = DEFAULT_TAILORING_POLICY,
) -> str:
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
    return "\n".join(lines).strip() + "\n"


def validate_tailored_cv(
    original_cv: str,
    tailored_cv: str,
    profile: CandidateProfile,
) -> bool:
    if not original_cv.strip() or not tailored_cv.strip():
        return False

    if "## Matching Evidence" not in tailored_cv or "## Base CV" not in tailored_cv:
        return False

    base_cv_marker = "## Base CV\n"
    if base_cv_marker not in tailored_cv:
        return False
    embedded_cv = tailored_cv.split(base_cv_marker, 1)[1].strip()
    if embedded_cv != original_cv.strip():
        return False

    for line in _extract_bullet_lines(tailored_cv, "## Matching Evidence"):
        if line == "No matched skills were identified from the approved profile.":
            continue
        if line.startswith("Required skill: ") or line.startswith("Preferred skill: "):
            skill = line.split(": ", 1)[1]
            if _normalize_text(skill) not in {_normalize_text(value) for value in profile.skills}:
                return False
            continue
        if line.startswith("Experience: "):
            if profile.years_experience is None:
                return False
            expected_years = int(profile.years_experience) if float(profile.years_experience).is_integer() else profile.years_experience
            if line != f"Experience: {expected_years} years":
                return False
            continue
        return False

    keyword_lines = _extract_plain_lines(tailored_cv, "## ATS Keywords", stop_markers={"## Base CV"})
    if keyword_lines:
        keywords = [part.strip() for part in keyword_lines[0].split(":", 1)[-1].split(",") if part.strip()]
        allowed_skills = {_normalize_text(value) for value in profile.skills}
        if any(_normalize_text(keyword) not in allowed_skills for keyword in keywords):
            return False

    return True


def save_tailored_cv(
    job_id: str,
    cv_text: str,
    profile_id: str,
    policy: TailoringPolicy = DEFAULT_TAILORING_POLICY,
) -> Path:
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_id must be a non-empty string")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("profile_id must be a non-empty string")
    if not isinstance(cv_text, str) or not cv_text.strip():
        raise ValueError("cv_text must be a non-empty string")

    output_dir = policy.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{job_id.strip()}.md"
    content = f"<!-- profile_id: {profile_id.strip()} -->\n{cv_text.strip()}\n"
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
