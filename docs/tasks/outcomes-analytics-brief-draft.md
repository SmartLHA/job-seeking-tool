# Outcomes Analytics — Brief Draft

**Status: Planning only — implement after CV tailoring**

---

## Goal
Track application outcomes and show basic conversion metrics over time.

## MVP scope (from `docs/development_sequence.md`)

- Record application status locally (`applied`, `interview`, `rejected`, `offer`, `withdrawn`)
- Basic status updates with notes
- Minimal history view/reporting

## Already implemented

- `src/outcomes.py` — `ApplicationOutcome` model, create/update, status history
- `OutcomeStatus = Literal["not_applied","applied","interview","rejected","offer","withdrawn"]`
- Storage in `data/state/outcomes/`

## What may still be needed

- [ ] `src/reporting.py` extension — `get_outcome_summary()` → applied count, interview rate, offer rate, rejection rate
- [ ] `src/reporting.py` extension — `get_score_to_outcome_analysis()` — does higher score predict interview/offer?
- [ ] Basic UI extension — show outcome history / simple metrics in UI (or keep CLI-only for MVP)
- [ ] Outcome history view in UI

## Questions for Mic

1. UI or CLI-only for MVP outcomes tracking?
2. Want score-to-outcome correlation analysis in MVP?
3. Want a simple weekly summary report (text/JSON)?

## Dependencies

- CV tailoring must be complete first
- Outcomes storage already exists
