from __future__ import annotations

import pytest

from src.job_hunt_models import ApplicationOutcome
from src.job_hunt_outcomes import (
    ALLOWED_OUTCOME_STATUSES,
    OutcomeValidationError,
    create_outcome_record,
    outcome_from_dict,
    outcome_to_dict,
    reset_terminal_outcome,
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


@pytest.mark.parametrize("terminal_status", ["rejected", "withdrawn"])
def test_reset_terminal_outcome_preserves_terminal_history(terminal_status: str) -> None:
    terminal = update_outcome(
        update_outcome(create_outcome_record("job-001", updated_at=FIXED_TIME), status="applied", updated_at=LATER_TIME),
        status=terminal_status,
        updated_at="2026-04-06T09:15:00Z",
        notes="Original terminal outcome",
    )

    reset = reset_terminal_outcome(
        terminal,
        updated_at="2026-04-07T09:15:00Z",
        reason="Selected the wrong job",
    )

    assert reset.status == "not_applied"
    assert [event.status for event in reset.history] == ["not_applied", "applied", terminal_status, "not_applied"]
    assert reset.history[-2].notes == "Original terminal outcome"
    assert reset.history[-1].notes == f"Reset from {terminal_status}. Reason: Selected the wrong job"


def test_reset_terminal_outcome_rejects_non_terminal_status() -> None:
    applied = update_outcome(
        create_outcome_record("job-001", updated_at=FIXED_TIME),
        status="applied",
        updated_at=LATER_TIME,
    )

    with pytest.raises(OutcomeValidationError, match="only rejected or withdrawn"):
        reset_terminal_outcome(applied, updated_at="2026-04-07T09:15:00Z")


def test_reset_terminal_outcome_records_default_reason() -> None:
    rejected = update_outcome(
        update_outcome(create_outcome_record("job-001", updated_at=FIXED_TIME), status="applied", updated_at=LATER_TIME),
        status="rejected",
        updated_at="2026-04-06T09:15:00Z",
    )

    reset = reset_terminal_outcome(rejected, updated_at="2026-04-07T09:15:00Z")

    assert reset.history[-1].notes == "Reset from rejected. Reason: Marked by mistake."


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
