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



# Qualitative grade bands (A-F) on the 0-100 match score. Grade A starts at
# DEFAULT_DECISION_POLICY.apply_threshold and grade C at its review_threshold,
# so grades never disagree with the decision bands. B and D are display-only
# sub-bands with no decision meaning (Slice 1, 2026-10-19).
GRADE_B_THRESHOLD: float = 72.0
GRADE_D_THRESHOLD: float = 50.0


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


# ── Market-aware salary (2026-09-22, revision 2) ─────────────────────────────
# Position bands are RANGES of the Adzuna histogram percentile, not single anchor
# points: bottom < 25th, 25th <= typical <= 75th, top > 75th.
MARKET_POSITION_BOTTOM_PERCENTILE: float = 25.0
MARKET_POSITION_TOP_PERCENTILE: float = 75.0
# A histogram sample below this size, or with fewer than this many buckets, is too
# thin to classify a position from — "unknown" instead of a false-precision claim.
MARKET_MIN_SAMPLE_TOTAL: int = 30
MARKET_MIN_BUCKETS: int = 5
# A job salary is only treated as a clear annual figure (and used to classify market
# position) when BOTH min and max are known AND both are >= this floor; anything
# lower reads as a day/hourly rate, not an annual salary, so it is "unknown".
MARKET_ANNUAL_SALARY_FLOOR: int = 10000
# Employment types that make an annual-salary market comparison unreliable (day-rate
# contracts, short temp work, part-time pro-rata pay) — normalised, lower-cased tokens
# as stored in JobPosting.employment_type (see src/ui_state.py _ALLOWED_EMPLOYMENT_TYPES).
MARKET_EXCLUDED_EMPLOYMENT_TYPES: frozenset[str] = frozenset(
    {"contract", "temporary", "temp", "part_time", "part-time"}
)

# The optional score effect (a fixed -5 when the STORED snapshot says "bottom") is
# OFF by default. Read through market_score_effect_enabled() (not the module
# constant directly) so tests can monkeypatch it without touching call sites.
MARKET_SCORE_EFFECT: bool = False


def market_score_effect_enabled() -> bool:
    """Whether the optional market-position score effect is active. Default OFF."""
    return MARKET_SCORE_EFFECT


