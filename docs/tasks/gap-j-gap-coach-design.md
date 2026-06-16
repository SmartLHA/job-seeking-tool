# GAP-J — Gap Coach Module + Route

**Status:** ⏸ Deferred 2026-06-16
**Reason:** Not enough evaluated jobs to make aggregation useful. Revisit when 10+ jobs have been evaluated.
**Note:** Design is complete — ready to build when deferred status is lifted.

---

## Goal

Aggregate skill gaps and strengths across all stored `JobAnalysis` records to help the user
understand recurring patterns: which skills to develop, which strengths to lean on.
Logic is deterministic aggregation only — no LLM, no invented insights.

---

## New Module: src/gap_coach.py

```python
from dataclasses import dataclass
from collections import Counter
from src.job_hunt_models import JobAnalysis

@dataclass
class GapTheme:
    skill: str
    frequency: int          # how many analyses list this as missing
    as_required: int        # count where it was missing_required_skills
    as_preferred: int       # count where it was missing_preferred_skills
    risk_codes: list[str]   # risk flag codes from analyses where this skill was missing

@dataclass
class StrengthTheme:
    strength: str
    frequency: int          # how many analyses list this as a strength

@dataclass
class CoachSummary:
    top_gaps: list[GapTheme]          # sorted by frequency desc, required-first
    top_strengths: list[StrengthTheme]
    analyses_count: int               # total analyses included
    apply_count: int
    review_count: int
    skip_count: int
    avg_score: float | None


def aggregate_gaps(analyses: list[JobAnalysis], top_n: int = 10) -> list[GapTheme]:
    """
    Count missing_required_skills and missing_preferred_skills across all analyses.
    Return top_n themes sorted by: required frequency desc, then preferred freq desc.
    """
    required_counter = Counter()
    preferred_counter = Counter()
    risk_by_skill: dict[str, list[str]] = {}

    for a in analyses:
        for skill in a.missing_required_skills:
            required_counter[skill] += 1
        for skill in a.missing_preferred_skills:
            preferred_counter[skill] += 1
        for rf in a.risk_flags:
            # associate risk flags with the skills missing in the same analysis
            for skill in a.missing_required_skills:
                risk_by_skill.setdefault(skill, []).append(rf.code)

    all_skills = set(required_counter) | set(preferred_counter)
    themes = [
        GapTheme(
            skill=s,
            frequency=required_counter[s] + preferred_counter[s],
            as_required=required_counter[s],
            as_preferred=preferred_counter[s],
            risk_codes=list(set(risk_by_skill.get(s, []))),
        )
        for s in all_skills
    ]
    themes.sort(key=lambda t: (-t.as_required, -t.frequency))
    return themes[:top_n]


def top_strengths(analyses: list[JobAnalysis], top_n: int = 10) -> list[StrengthTheme]:
    """
    Count strengths[] across all analyses.
    Return top_n by frequency desc.
    """
    counter = Counter()
    for a in analyses:
        for s in a.strengths:
            counter[s] += 1
    return [
        StrengthTheme(strength=s, frequency=c)
        for s, c in counter.most_common(top_n)
    ]


def build_coach_summary(analyses: list[JobAnalysis], top_n: int = 10) -> CoachSummary:
    scores = [a.match_score for a in analyses if a.match_score is not None]
    return CoachSummary(
        top_gaps=aggregate_gaps(analyses, top_n),
        top_strengths=top_strengths(analyses, top_n),
        analyses_count=len(analyses),
        apply_count=sum(1 for a in analyses if a.decision == "apply"),
        review_count=sum(1 for a in analyses if a.decision == "review"),
        skip_count=sum(1 for a in analyses if a.decision == "skip"),
        avg_score=sum(scores) / len(scores) if scores else None,
    )
```

---

## New Route

```
GET /coach
Response: {
  top_gaps: [
    {
      skill: str,
      frequency: int,
      as_required: int,
      as_preferred: int,
      risk_codes: list[str]
    },
    ...
  ],
  top_strengths: [
    { strength: str, frequency: int },
    ...
  ],
  analyses_count: int,
  apply_count: int,
  review_count: int,
  skip_count: int,
  avg_score: float | null
}
```

Handler:
1. Scan `analyses/` directory → load all `JobAnalysis` records
2. Call `build_coach_summary(analyses)`
3. Return JSON response

If no analyses exist yet: return empty lists and zero counts (not an error).

---

## UI: Gap Coach Screen

**Top gaps panel** — list ranked by required-miss frequency:
- Skill name
- Frequency bar (e.g. "Missing in 4 of 7 evaluated jobs")
- Badge: "Required" or "Preferred"
- Risk flag indicator if `risk_codes` is non-empty

**Top strengths panel** — list ranked by frequency:
- Strength name
- "Appears in N evaluations"

**Summary row** — Apply / Review / Skip counts + avg score

---

## Files to Create/Change

| File | Change |
|------|--------|
| `src/gap_coach.py` | New module — `GapTheme`, `StrengthTheme`, `CoachSummary`, `aggregate_gaps()`, `top_strengths()`, `build_coach_summary()` |
| `src/job_hunt_ui.py` | Add `GET /coach` route |
| `tests/test_gap_coach.py` | New tests |

---

## Acceptance Criteria

1. `aggregate_gaps([])` returns `[]` — empty input does not error
2. `aggregate_gaps(analyses)` returns skills sorted: required-miss freq desc, then preferred-miss freq desc
3. A skill missing as required in 3 analyses ranks above one missing only as preferred in 5
4. `top_strengths(analyses)` returns strengths sorted by frequency desc
5. `build_coach_summary()` returns correct apply/review/skip counts and avg_score
6. `avg_score` is `None` when no analyses have a score
7. `GET /coach` returns the full summary JSON
8. `GET /coach` with no stored analyses returns `{top_gaps: [], top_strengths: [], analyses_count: 0, ...}`

---

## Test Command

```bash
python3 -m pytest tests/test_gap_coach.py -v
```
