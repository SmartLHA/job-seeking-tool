from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# Candidate profile models represent the approved truth source about the person.
# This data is intentionally separate from job records and analysis output because
# later workflow stages should compare candidate facts against a reviewed job, not
# mutate the source-of-truth profile itself.
@dataclass(slots=True)
class CandidateProfile:
    candidate_id: str
    name: str | None = None
    target_roles: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    remote_preference: str | None = None
    salary_floor_gbp: int | None = None
    right_to_work_uk: bool | None = None
    skills: list[str] = field(default_factory=list)
    years_experience: float | None = None
    industries: list[str] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    master_cv_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty")
        if self.salary_floor_gbp is not None and self.salary_floor_gbp < 0:
            raise ValueError("salary_floor_gbp must be non-negative when provided")
        if self.years_experience is not None and self.years_experience < 0:
            raise ValueError("years_experience must be non-negative when provided")


# Job posting models capture the reviewed structured job record that scoring will
# consume. Unknowns are allowed because MVP input may start from copied text or a
# simple URL and should preserve uncertainty instead of guessing.
@dataclass(slots=True)
class JobPosting:
    job_id: str
    job_title: str
    company: str
    description_raw: str
    source_type: str
    source_ref: str | None
    location: str | None
    work_mode: str | None
    employment_type: str | None
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    required_years_experience: float | None = None
    nice_to_have_years_experience: float | None = None
    domain: str | None = None
    notes: str | None = None
    salary_min_gbp: int | None = None
    salary_max_gbp: int | None = None

    def __post_init__(self) -> None:
        required_text_fields = {
            "job_id": self.job_id,
            "job_title": self.job_title,
            "company": self.company,
            "description_raw": self.description_raw,
            "source_type": self.source_type,
        }
        for field_name, value in required_text_fields.items():
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")

        for field_name, value in {
            "required_years_experience": self.required_years_experience,
            "nice_to_have_years_experience": self.nice_to_have_years_experience,
        }.items():
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be non-negative when provided")

        for field_name, value in {
            "salary_min_gbp": self.salary_min_gbp,
            "salary_max_gbp": self.salary_max_gbp,
        }.items():
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be non-negative when provided")

        if (
            self.salary_min_gbp is not None
            and self.salary_max_gbp is not None
            and self.salary_min_gbp > self.salary_max_gbp
        ):
            raise ValueError("salary_min_gbp must not exceed salary_max_gbp")


# Blockers and risks stay structured so later eligibility, scoring, and decision
# modules can stay explainable. Blockers are for hard-stop or near-hard-stop issues;
# risk flags are caution signals that may still lead to review.
BlockerSeverity = Literal["low", "medium", "high", "critical"]


@dataclass(slots=True)
class Blocker:
    code: str
    label: str
    reason: str
    severity: BlockerSeverity

    def __post_init__(self) -> None:
        if not all(part.strip() for part in (self.code, self.label, self.reason)):
            raise ValueError("blocker fields must not be empty")


@dataclass(slots=True)
class RiskFlag:
    code: str
    label: str
    reason: str

    def __post_init__(self) -> None:
        if not all(part.strip() for part in (self.code, self.label, self.reason)):
            raise ValueError("risk flag fields must not be empty")


# Score breakdown remains a structured object rather than free text so the product
# can show why a score exists. Confidence is not stored here on purpose: score is a
# fit result, while confidence expresses how trustworthy or complete the reviewed job
# data is.
@dataclass(slots=True)
class ScoreComponent:
    value: float
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("score component reason must not be empty")


@dataclass(slots=True)
class ScoreBreakdown:
    skills_score: ScoreComponent
    experience_score: ScoreComponent
    location_score: ScoreComponent
    salary_score: ScoreComponent
    domain_score: ScoreComponent
    work_mode_score: ScoreComponent
    notes: list[str] = field(default_factory=list)


Decision = Literal["apply", "review", "skip"]
ConfidenceLevel = Literal["low", "medium", "high"]
OutcomeStatus = Literal[
    "not_applied",
    "applied",
    "interview",
    "rejected",
    "offer",
    "withdrawn",
]


# Job analysis is the derived evaluation layer. It should reference the reviewed job
# record by id, remain separate from the job itself, and keep confidence separate from
# match_score so a promising job with incomplete data can still be shown as uncertain.
@dataclass(slots=True)
class JobAnalysis:
    job_id: str
    match_score: float
    score_breakdown: ScoreBreakdown
    blockers: list[Blocker] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    missing_required_skills: list[str] = field(default_factory=list)
    missing_preferred_skills: list[str] = field(default_factory=list)
    risk_flags: list[RiskFlag] = field(default_factory=list)
    decision: Decision = "review"
    decision_reason: str = ""
    confidence: ConfidenceLevel = "medium"
    tailoring_ready: bool | None = None
    tailoring_notes: str | None = None

    def __post_init__(self) -> None:
        if not self.job_id.strip():
            raise ValueError("job_id must not be empty")
        if not 0 <= self.match_score <= 100:
            raise ValueError("match_score must be between 0 and 100")
        if not self.decision_reason.strip():
            raise ValueError("decision_reason must not be empty")


# Outcomes are kept deliberately small in MVP: a current status plus a readable
# local history. This supports personal tracking without introducing analytics or
# workflow automation complexity too early.
@dataclass(slots=True)
class OutcomeEvent:
    status: OutcomeStatus
    updated_at: str
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.updated_at.strip():
            raise ValueError("updated_at must not be empty")


@dataclass(slots=True)
class ApplicationOutcome:
    job_id: str
    status: OutcomeStatus
    updated_at: str
    notes: str | None = None
    history: list[OutcomeEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.job_id.strip():
            raise ValueError("job_id must not be empty")
        if not self.updated_at.strip():
            raise ValueError("updated_at must not be empty")
        if not self.history:
            raise ValueError("history must contain at least one outcome event")

        latest_event = self.history[-1]
        if latest_event.status != self.status or latest_event.updated_at != self.updated_at:
            raise ValueError("current outcome must match the latest history event")
        if latest_event.notes != self.notes:
            raise ValueError("current outcome notes must match the latest history event")
