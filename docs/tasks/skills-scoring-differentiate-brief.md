# Skills Scoring Differentiation — Task Brief

**For: Handy**
**Status: Approved — ready to hand off**
**Depends on: None**

---

## Goal

Change skills scoring formula so matching more required skills earns more points than the minimum threshold.

---

## Current Formula

```
skills_score = (matched_required / total_required) * weight
```
- 2/2 required = 1.0 * 35 = **35.0**
- 1/1 required = 1.0 * 35 = **35.0**

Both get the same score — no differentiation.

---

## New Formula

```
skills_score = base_score + (matched_required - 1) * bonus_per_extra_required

bonus_per_extra_required = weight * 0.1  # configurable via ScoringWeights
```

Examples (weight=35, bonus=3.5):
- 1/1 = 35 + 0 = **35.0**
- 2/2 = 35 + 3.5 = **38.5**
- 3/3 = 35 + 7.0 = **42.0**
- 1/2 = 0.5 * 35 = **17.5** (below threshold, penalised)

Same pattern applies to preferred_skills_score (bonus_per_extra_preferred = weight * 0.05).

---

## Files to Change

| File | Change |
|------|--------|
| `src/config.py` | Add `bonus_per_extra_required` and `bonus_per_extra_preferred` to `ScoringWeights` |
| `src/scoring.py` | Update `_score_skills()` to use new formula |
| `tests/test_scoring.py` | Add tests: 1/1=35, 2/2=38.5, 3/3=42, 1/2=17.5 |
| `docs/data_contract.md` | Update skills_score documentation |

---

## Test Command

```bash
python3 -m pytest tests/test_scoring.py -v
```

---

## Acceptance

1. `skills_score` for 2/2 required skills > 1/1
2. `skills_score` for 3/3 required skills > 2/2
3. Partial matches (1/2) score proportionally below the threshold
4. All existing tests still pass
5. New tests cover the differentiation cases
