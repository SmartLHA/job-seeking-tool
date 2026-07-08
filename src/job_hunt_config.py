from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


# Scoring policy belongs in config so later tuning can happen without scattering
# magic numbers across the scoring logic.
@dataclass(frozen=True, slots=True)
class ScoringWeights:
    skills_required: float = 35.0
    skills_preferred: float = 5.0
    bonus_per_extra_required: float = 3.5
    bonus_per_extra_preferred: float = 0.25
    experience: float = 20.0
    location: float = 10.0
    salary: float = 10.0
    domain: float = 10.0
    work_mode: float = 10.0

    def total(self) -> float:
        return (
            self.skills_required
            + self.skills_preferred
            + self.experience
            + self.location
            + self.salary
            + self.domain
            + self.work_mode
        )

    def __post_init__(self) -> None:
        # LT-3: catch a misconfigured weight set at construction time. If the
        # seven dimension weights don't sum to 100, most candidates would silently
        # hit the global min(100) cap and the misconfiguration would go unnoticed.
        if abs(self.total() - 100.0) > 0.01:
            raise ValueError(
                f"ScoringWeights dimensions must sum to 100.0, got {self.total():.2f}"
            )


@dataclass(frozen=True, slots=True)
class ConfidencePolicy:
    missing_required_skills_penalty: float = 20.0
    missing_required_experience_penalty: float = 20.0
    missing_location_penalty: float = 12.0
    missing_work_mode_penalty: float = 10.0
    missing_salary_penalty: float = 10.0
    missing_domain_penalty: float = 8.0

    high_threshold: float = 85.0
    medium_threshold: float = 60.0


@dataclass(frozen=True, slots=True)
class ScoringPolicy:
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    confidence: ConfidencePolicy = field(default_factory=ConfidencePolicy)
    partial_experience_credit_ratio: float = 0.6
    work_mode_unknown_ratio: float = 0.4
    domain_unknown_ratio: float = 0.5


DEFAULT_SCORING_POLICY = ScoringPolicy()


@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    apply_threshold: float = 80.0
    review_threshold: float = 65.0
    critical_risk_codes: frozenset[str] = frozenset(
        {
            "missing-required-skills",
            "salary-below-floor",
        }
    )


DEFAULT_DECISION_POLICY = DecisionPolicy(
    critical_risk_codes=frozenset(
        {
            "missing-required-skills",
            "salary-below-floor",
            "marginal-source-quality",
        }
    )
)


SOURCE_QUALITY_SKIP_THRESHOLD: int = 40
SOURCE_QUALITY_REVIEW_THRESHOLD: int = 70


@dataclass(frozen=True, slots=True)
class TailoringPolicy:
    require_manual_selection_for_review: bool = True
    include_keyword_summary: bool = True
    max_evidence_points: int = 8
    output_dir: Path = Path("output/tailored_cvs")


DEFAULT_TAILORING_POLICY = TailoringPolicy()


# Sources that are fully wired end-to-end (fetch + normalise + orchestrator)
# Add a source here only when its client and orchestrator path are complete and tested.
ENABLED_SOURCES: list[str] = ["Reed", "Adzuna", "LinkedIn"]


def get_enabled_sources() -> list[str]:
    """Return the list of currently enabled job sources."""
    return list(ENABLED_SOURCES)


