from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from src.config import DEFAULT_SCORING_POLICY, ScoringPolicy
from src.models import CandidateProfile, ConfidenceLevel, JobPosting, RiskFlag, ScoreBreakdown, ScoreComponent


@dataclass(slots=True)
class ScoringResult:
    match_score: float
    confidence: ConfidenceLevel
    score_breakdown: ScoreBreakdown
    strengths: list[str] = field(default_factory=list)
    missing_required_skills: list[str] = field(default_factory=list)
    missing_preferred_skills: list[str] = field(default_factory=list)
    risk_flags: list[RiskFlag] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def score_job(
    profile: CandidateProfile,
    job: JobPosting,
    policy: ScoringPolicy = DEFAULT_SCORING_POLICY,
) -> ScoringResult:
    required_score, required_reason, matched_required, missing_required = _score_required_skills(
        profile.skills,
        job.required_skills,
        policy,
    )
    preferred_score, preferred_reason, matched_preferred, missing_preferred = _score_preferred_skills(
        profile.skills,
        job.preferred_skills,
        policy,
    )
    experience_score, experience_reason = _score_experience(profile, job, policy)
    location_score, location_reason = _score_location(profile, job, policy)
    salary_score, salary_reason = _score_salary(profile, job, policy)
    domain_score, domain_reason = _score_domain(profile, job, policy)
    work_mode_score, work_mode_reason = _score_work_mode(profile, job, policy)

    skills_score = required_score + preferred_score
    skills_reason = _join_reasons(required_reason, preferred_reason)

    salary_below_floor = _is_salary_below_floor(profile, job)
    notes = _build_notes(job, missing_required, missing_preferred, salary_below_floor)
    risk_flags = _build_risk_flags(missing_required, missing_preferred, salary_below_floor)
    breakdown = ScoreBreakdown(
        skills_score=ScoreComponent(value=round(skills_score, 2), reason=skills_reason),
        experience_score=ScoreComponent(value=round(experience_score, 2), reason=experience_reason),
        location_score=ScoreComponent(value=round(location_score, 2), reason=location_reason),
        salary_score=ScoreComponent(value=round(salary_score, 2), reason=salary_reason),
        domain_score=ScoreComponent(value=round(domain_score, 2), reason=domain_reason),
        work_mode_score=ScoreComponent(value=round(work_mode_score, 2), reason=work_mode_reason),
        notes=notes,
    )

    match_score = round(
        skills_score
        + experience_score
        + location_score
        + salary_score
        + domain_score
        + work_mode_score,
        2,
    )
    confidence = _derive_confidence(job, policy)

    strengths = sorted(set(matched_required + matched_preferred))

    return ScoringResult(
        match_score=match_score,
        confidence=confidence,
        score_breakdown=breakdown,
        strengths=strengths,
        missing_required_skills=missing_required,
        missing_preferred_skills=missing_preferred,
        risk_flags=risk_flags,
        notes=notes,
    )


# Important scoring section: required and preferred skill matching.
# Required skills drive the core fit score; preferred skills are only soft boosts.
def _score_required_skills(
    candidate_skills: Iterable[str],
    required_skills: Iterable[str],
    policy: ScoringPolicy,
) -> tuple[float, str, list[str], list[str]]:
    matched, missing = _match_skills(candidate_skills, required_skills)
    required_list = list(required_skills)
    if not required_list:
        return 0.0, "No required skills were provided in the reviewed job data", [], []

    ratio = len(matched) / len(required_list)
    score = policy.weights.skills_required * ratio
    reason = f"Matched {len(matched)} of {len(required_list)} required skills"
    return score, reason, matched, missing


def _score_preferred_skills(
    candidate_skills: Iterable[str],
    preferred_skills: Iterable[str],
    policy: ScoringPolicy,
) -> tuple[float, str, list[str], list[str]]:
    matched, missing = _match_skills(candidate_skills, preferred_skills)
    preferred_list = list(preferred_skills)
    if not preferred_list:
        return 0.0, "No preferred skills were provided in the reviewed job data", [], []

    ratio = len(matched) / len(preferred_list)
    score = policy.weights.skills_preferred * ratio
    reason = f"Matched {len(matched)} of {len(preferred_list)} preferred skills"
    return score, reason, matched, missing


# Important scoring section: unknown job data should lower confidence before it
# heavily lowers score. When data is missing we usually stay neutral on score.
def _score_experience(
    profile: CandidateProfile,
    job: JobPosting,
    policy: ScoringPolicy,
) -> tuple[float, str]:
    if job.required_years_experience is None:
        return policy.weights.experience, "Required experience is unknown, so score stays neutral"
    if profile.years_experience is None:
        return policy.weights.experience * 0.5, "Candidate experience is unknown, so only partial credit is given"
    if profile.years_experience >= job.required_years_experience:
        return policy.weights.experience, "Candidate meets or exceeds required experience"
    if profile.years_experience >= (job.required_years_experience * policy.partial_experience_credit_ratio):
        return policy.weights.experience * 0.5, "Candidate appears somewhat below the stated experience requirement"
    return 0.0, "Candidate is materially below the stated experience requirement"


def _score_location(
    profile: CandidateProfile,
    job: JobPosting,
    policy: ScoringPolicy,
) -> tuple[float, str]:
    if not job.location:
        return policy.weights.location, "Job location is unknown, so score stays neutral"
    candidate_locations = {_normalize_text(value) for value in profile.locations}
    job_location = _normalize_text(job.location)
    if job_location and job_location in candidate_locations:
        return policy.weights.location, "Job location matches candidate preferences"
    if job.work_mode and _normalize_text(job.work_mode) == "remote":
        return policy.weights.location, "Remote role reduces location importance"
    return 0.0, "Job location is outside the candidate's listed preferences"


def _score_salary(
    profile: CandidateProfile,
    job: JobPosting,
    policy: ScoringPolicy,
) -> tuple[float, str]:
    if profile.salary_floor_gbp is None:
        return policy.weights.salary, "Candidate salary floor is unknown, so score stays neutral"
    if job.salary_max_gbp is None and job.salary_min_gbp is None:
        return policy.weights.salary, "Job salary data is unknown, so score stays neutral"

    known_salary = job.salary_max_gbp if job.salary_max_gbp is not None else job.salary_min_gbp
    if known_salary is None:
        return policy.weights.salary, "Job salary data is unknown, so score stays neutral"
    if known_salary >= profile.salary_floor_gbp:
        return policy.weights.salary, "Job salary appears to meet the candidate floor"
    return 0.0, "Known salary data appears below the candidate floor"


def _score_domain(
    profile: CandidateProfile,
    job: JobPosting,
    policy: ScoringPolicy,
) -> tuple[float, str]:
    if not job.domain:
        return policy.weights.domain * policy.domain_unknown_ratio, "Job domain is unknown, so only neutral partial credit is given"
    candidate_domains = {_normalize_text(value) for value in profile.industries}
    job_domain = _normalize_text(job.domain)
    if job_domain and job_domain in candidate_domains:
        return policy.weights.domain, "Job domain matches candidate experience"
    return 0.0, "Job domain is outside the candidate's known industries"


def _score_work_mode(
    profile: CandidateProfile,
    job: JobPosting,
    policy: ScoringPolicy,
) -> tuple[float, str]:
    preference = _normalize_text(profile.remote_preference)
    work_mode = _normalize_text(job.work_mode)
    if not work_mode or work_mode == "unknown":
        return policy.weights.work_mode * policy.work_mode_unknown_ratio, "Work mode is unknown, so only partial neutral credit is given"
    if not preference:
        return policy.weights.work_mode, "Candidate work mode preference is unknown, so score stays neutral"
    if preference == "remote_only":
        if work_mode == "remote":
            return policy.weights.work_mode, "Remote-only preference matches the job"
        return 0.0, "Role is not remote despite a remote-only preference"
    if preference in {"remote_friendly", "hybrid", "flexible"}:
        if work_mode in {"remote", "hybrid"}:
            return policy.weights.work_mode, "Work mode matches a flexible remote preference"
        return 0.0, "Onsite role does not match the candidate work mode preference"
    return policy.weights.work_mode, "No restrictive work mode preference blocks the job"


# Important scoring section: confidence is derived from data completeness, not fit.
def _derive_confidence(job: JobPosting, policy: ScoringPolicy) -> ConfidenceLevel:
    score = 100.0
    if not job.required_skills:
        score -= policy.confidence.missing_required_skills_penalty
    if job.required_years_experience is None:
        score -= policy.confidence.missing_required_experience_penalty
    if not job.location:
        score -= policy.confidence.missing_location_penalty
    if not job.work_mode or _normalize_text(job.work_mode) == "unknown":
        score -= policy.confidence.missing_work_mode_penalty
    if job.salary_min_gbp is None and job.salary_max_gbp is None:
        score -= policy.confidence.missing_salary_penalty
    if not job.domain:
        score -= policy.confidence.missing_domain_penalty

    if score >= policy.confidence.high_threshold:
        return "high"
    if score >= policy.confidence.medium_threshold:
        return "medium"
    return "low"


def _build_notes(
    job: JobPosting,
    missing_required: list[str],
    missing_preferred: list[str],
    salary_below_floor: bool,
) -> list[str]:
    notes: list[str] = []
    if missing_required:
        notes.append("Missing required skills reduce fit materially.")
    if missing_preferred:
        notes.append("Missing preferred skills are soft gaps only.")
    if salary_below_floor:
        notes.append("Known salary data appears below the candidate floor and needs manual review.")
    if not job.required_skills:
        notes.append("Reviewed job data did not include explicit required skills.")
    if job.required_years_experience is None:
        notes.append("Reviewed job data did not include explicit required years of experience.")
    return notes


def _build_risk_flags(
    missing_required: list[str],
    missing_preferred: list[str],
    salary_below_floor: bool,
) -> list[RiskFlag]:
    risk_flags: list[RiskFlag] = []
    if missing_required:
        risk_flags.append(
            RiskFlag(
                code="missing-required-skills",
                label="Required skill gap",
                reason=f"Missing required skills: {', '.join(missing_required)}",
            )
        )
    if missing_preferred:
        risk_flags.append(
            RiskFlag(
                code="missing-preferred-skills",
                label="Preferred skill gap",
                reason=f"Missing preferred skills: {', '.join(missing_preferred)}",
            )
        )
    if salary_below_floor:
        risk_flags.append(
            RiskFlag(
                code="salary-below-floor",
                label="Salary below floor",
                reason="Known salary data appears below the candidate floor",
            )
        )
    return risk_flags


def _is_salary_below_floor(profile: CandidateProfile, job: JobPosting) -> bool:
    if profile.salary_floor_gbp is None:
        return False
    known_salary = job.salary_max_gbp if job.salary_max_gbp is not None else job.salary_min_gbp
    if known_salary is None:
        return False
    return known_salary < profile.salary_floor_gbp


def _match_skills(candidate_skills: Iterable[str], job_skills: Iterable[str]) -> tuple[list[str], list[str]]:
    candidate_lookup = {_normalize_text(skill): skill for skill in candidate_skills if _normalize_text(skill)}
    matched: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()

    for skill in job_skills:
        normalized = _normalize_text(skill)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if normalized in candidate_lookup:
            matched.append(skill)
        else:
            missing.append(skill)

    return matched, missing


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.strip().lower().split())


def _join_reasons(*parts: str) -> str:
    return "; ".join(part for part in parts if part)
