from __future__ import annotations

import pytest

from src.models import ApplicationOutcome
from src.outcomes import (
    ALLOWED_OUTCOME_STATUSES,
    OutcomeValidationError,
    create_outcome_record,
    outcome_from_dict,
    outcome_to_dict,
    update_outcome,
)


FIXED_TIME = "2026-04-04T20:40:00Z"
LATER_TIME = "2026-04-05T09:15:00Z"


def test_create_outcome_record_starts_with_not_applied_history() -> None:
    outcome = create_outcome_record("job-001", updated_at=FIXED_TIME, notes="Saved for later")

    assert isinstance(outcome, ApplicationOutcome)
    assert outcome.job_id == "job-001"
    assert outcome.status == "not_applied"
    assert outcome.updated_at == FIXED_TIME
    assert outcome.notes == "Saved for later"
    assert len(outcome.history) == 1
    assert outcome.history[0].status == "not_applied"


def test_update_outcome_appends_new_history_event_and_updates_current_state() -> None:
    initial = create_outcome_record("job-001", updated_at=FIXED_TIME)

    updated = update_outcome(
        initial,
        status="applied",
        updated_at=LATER_TIME,
        notes="Submitted tailored CV",
    )

    assert updated.status == "applied"
    assert updated.updated_at == LATER_TIME
    assert updated.notes == "Submitted tailored CV"
    assert [event.status for event in updated.history] == ["not_applied", "applied"]
    assert initial.status == "not_applied"
    assert len(initial.history) == 1


def test_update_outcome_rejects_invalid_transition() -> None:
    initial = create_outcome_record("job-001", updated_at=FIXED_TIME)

    with pytest.raises(OutcomeValidationError, match="invalid outcome transition"):
        update_outcome(initial, status="interview", updated_at=LATER_TIME)


def test_outcome_to_dict_and_from_dict_round_trip() -> None:
    outcome = update_outcome(
        create_outcome_record("job-001", updated_at=FIXED_TIME),
        status="applied",
        updated_at=LATER_TIME,
        notes="Submitted via company portal",
    )

    payload = outcome_to_dict(outcome)
    restored = outcome_from_dict(payload)

    assert restored == outcome


def test_outcome_from_dict_rejects_mismatched_current_and_history_state() -> None:
    with pytest.raises(OutcomeValidationError, match="latest history event"):
        outcome_from_dict(
            {
                "job_id": "job-001",
                "status": "applied",
                "updated_at": LATER_TIME,
                "notes": None,
                "history": [
                    {
                        "status": "not_applied",
                        "updated_at": FIXED_TIME,
                        "notes": None,
                    }
                ],
            }
        )


def test_allowed_statuses_match_mvp_contract() -> None:
    assert ALLOWED_OUTCOME_STATUSES == (
        "not_applied",
        "applied",
        "interview",
        "rejected",
        "offer",
        "withdrawn",
    )
