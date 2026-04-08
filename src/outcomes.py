from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.models import ApplicationOutcome, OutcomeEvent, OutcomeStatus


class OutcomeValidationError(ValueError):
    """Raised when outcome input or transitions are invalid."""


# Outcomes stay intentionally basic for MVP: one current status per job plus a
# small append-only history of changes. This supports local tracking without
# turning the feature into reporting or analytics infrastructure.
ALLOWED_OUTCOME_STATUSES: tuple[OutcomeStatus, ...] = (
    "not_applied",
    "applied",
    "interview",
    "rejected",
    "offer",
    "withdrawn",
)


@dataclass(frozen=True, slots=True)
class OutcomeUpdate:
    status: OutcomeStatus
    updated_at: str
    notes: str | None = None


_DEFAULT_INITIAL_STATUS: OutcomeStatus = "not_applied"


_ALLOWED_TRANSITIONS: dict[OutcomeStatus, frozenset[OutcomeStatus]] = {
    "not_applied": frozenset({"not_applied", "applied", "withdrawn"}),
    "applied": frozenset({"applied", "interview", "rejected", "offer", "withdrawn"}),
    "interview": frozenset({"interview", "rejected", "offer", "withdrawn"}),
    "rejected": frozenset({"rejected"}),
    "offer": frozenset({"offer", "withdrawn"}),
    "withdrawn": frozenset({"withdrawn"}),
}


def create_outcome_record(
    job_id: str,
    *,
    updated_at: str | None = None,
    notes: str | None = None,
) -> ApplicationOutcome:
    """Create the initial local outcome record for a job."""
    resolved_timestamp = _normalise_timestamp(updated_at)
    initial_notes = _normalise_optional_notes(notes)
    initial_event = OutcomeEvent(
        status=_DEFAULT_INITIAL_STATUS,
        updated_at=resolved_timestamp,
        notes=initial_notes,
    )
    return ApplicationOutcome(
        job_id=_required_job_id(job_id),
        status=_DEFAULT_INITIAL_STATUS,
        updated_at=resolved_timestamp,
        notes=initial_notes,
        history=[initial_event],
    )


def update_outcome(
    outcome: ApplicationOutcome,
    *,
    status: OutcomeStatus,
    updated_at: str | None = None,
    notes: str | None = None,
) -> ApplicationOutcome:
    """Return a new outcome record with one validated appended status update."""
    resolved_status = _normalise_status(status)
    _validate_transition(outcome.status, resolved_status)
    resolved_timestamp = _normalise_timestamp(updated_at)
    resolved_notes = _normalise_optional_notes(notes)

    event = OutcomeEvent(
        status=resolved_status,
        updated_at=resolved_timestamp,
        notes=resolved_notes,
    )
    return ApplicationOutcome(
        job_id=outcome.job_id,
        status=resolved_status,
        updated_at=resolved_timestamp,
        notes=resolved_notes,
        history=[*outcome.history, event],
    )


def outcome_to_dict(outcome: ApplicationOutcome) -> dict[str, Any]:
    """Convert an outcome record into a JSON-friendly mapping."""
    return {
        "job_id": outcome.job_id,
        "status": outcome.status,
        "updated_at": outcome.updated_at,
        "notes": outcome.notes,
        "history": [
            {
                "status": event.status,
                "updated_at": event.updated_at,
                "notes": event.notes,
            }
            for event in outcome.history
        ],
    }


def outcome_from_dict(payload: dict[str, Any], *, job_id: str | None = None) -> ApplicationOutcome:
    """Validate stored outcome payloads and rebuild the typed outcome record."""
    if not isinstance(payload, dict):
        raise OutcomeValidationError("outcome payload must be an object")

    resolved_job_id = job_id or payload.get("job_id")
    if not isinstance(resolved_job_id, str) or not resolved_job_id.strip():
        raise OutcomeValidationError("outcome payload must include a non-empty job_id")

    history_payload = payload.get("history", [])
    if history_payload is None:
        history_payload = []
    if not isinstance(history_payload, list):
        raise OutcomeValidationError("history must be a list")

    history: list[OutcomeEvent] = []
    for item in history_payload:
        if not isinstance(item, dict):
            raise OutcomeValidationError("history must contain objects")
        history.append(
            OutcomeEvent(
                status=_normalise_status(item.get("status")),
                updated_at=_normalise_timestamp(item.get("updated_at")),
                notes=_normalise_optional_notes(item.get("notes")),
            )
        )

    status = _normalise_status(payload.get("status"))
    updated_at = _normalise_timestamp(payload.get("updated_at"))
    notes = _normalise_optional_notes(payload.get("notes"))

    if history:
        last_event = history[-1]
        if (last_event.status, last_event.updated_at, last_event.notes) != (status, updated_at, notes):
            raise OutcomeValidationError(
                "current outcome fields must match the latest history event"
            )
    else:
        history = [OutcomeEvent(status=status, updated_at=updated_at, notes=notes)]

    try:
        return ApplicationOutcome(
            job_id=resolved_job_id.strip(),
            status=status,
            updated_at=updated_at,
            notes=notes,
            history=history,
        )
    except ValueError as exc:
        raise OutcomeValidationError(str(exc)) from exc


def _required_job_id(job_id: str) -> str:
    if not isinstance(job_id, str) or not job_id.strip():
        raise OutcomeValidationError("job_id must be a non-empty string")
    return job_id.strip()


def _normalise_status(value: Any) -> OutcomeStatus:
    if not isinstance(value, str) or not value.strip():
        raise OutcomeValidationError("status must be a non-empty string")
    cleaned = value.strip()
    if cleaned not in ALLOWED_OUTCOME_STATUSES:
        raise OutcomeValidationError(
            f"status must be one of: {', '.join(ALLOWED_OUTCOME_STATUSES)}"
        )
    return cleaned


def _normalise_timestamp(value: Any) -> str:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not isinstance(value, str) or not value.strip():
        raise OutcomeValidationError("updated_at must be a non-empty ISO 8601 string")

    cleaned = value.strip()
    normalised = cleaned.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(normalised)
    except ValueError as exc:
        raise OutcomeValidationError("updated_at must be a valid ISO 8601 string") from exc
    return cleaned


def _normalise_optional_notes(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OutcomeValidationError("notes must be a string when provided")
    cleaned = value.strip()
    return cleaned or None


def _validate_transition(current_status: OutcomeStatus, next_status: OutcomeStatus) -> None:
    allowed_next = _ALLOWED_TRANSITIONS[current_status]
    if next_status not in allowed_next:
        raise OutcomeValidationError(
            f"invalid outcome transition: {current_status} -> {next_status}"
        )
