"""Shared field-validation helpers (MT-2).

One canonical implementation of the small validators that were previously
copy-pasted — with subtle divergence — across :mod:`job_hunt_storage`,
:mod:`job_hunt_reviewed_input` and :mod:`job_hunt_profile`.

Two design points keep this fully behaviour-preserving:

* **Injected exception class** — every helper takes ``error=`` so callers keep
  raising their own ``ValueError`` subclass (``StorageError`` /
  ``ReviewedInputValidationError`` / ``ProfileValidationError``).
* **Behaviour flags** — a single implementation reproduces each historical
  variant exactly (``message_style``, ``strip``, ``dedup``, ``allow_empty_items``,
  ``non_negative``, ``empty_as_none``). Each module binds the right flags + error
  class with :func:`functools.partial`, so existing call sites are unchanged.

Note: Python treats ``bool`` as a subclass of ``int``; the numeric helpers reject
``True``/``False`` explicitly to preserve the original behaviour.
"""
from __future__ import annotations

from typing import Any


def required_string(
    value: Any,
    field_name: str,
    *,
    message_style: str = "split",
    error: type[Exception] = ValueError,
) -> str:
    if message_style == "combined":
        if not isinstance(value, str) or not value.strip():
            raise error(f"{field_name} must be a non-empty string")
        return value.strip()
    if not isinstance(value, str):
        raise error(f"{field_name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise error(f"{field_name} must not be empty")
    return cleaned


def optional_string(
    value: Any,
    field_name: str,
    *,
    empty_as_none: bool = False,
    error: type[Exception] = ValueError,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise error(f"{field_name} must be a string when provided")
    cleaned = value.strip()
    if not cleaned:
        if empty_as_none:
            return None
        raise error(f"{field_name} must not be empty when provided")
    return cleaned


def optional_text_or_empty(
    value: Any,
    field_name: str,
    *,
    error: type[Exception] = ValueError,
) -> str | None:
    """Optional text that permits whitespace/empty strings.

    Deliberately returns ``value or None`` WITHOUT stripping, so a single space
    ``" "`` is preserved as ``" "`` (only ``""`` and ``None`` collapse to ``None``).
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise error(f"{field_name} must be a string when provided")
    return value or None


def string_list(
    value: Any,
    field_name: str,
    *,
    strip: bool = False,
    dedup: bool = False,
    allow_empty_items: bool = True,
    error: type[Exception] = ValueError,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise error(f"{field_name} must be a list of strings")

    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise error(f"{field_name} must contain only strings")
        cleaned = item.strip() if strip else item
        if not allow_empty_items and not cleaned.strip():
            raise error(f"{field_name} must not contain empty strings")
        if dedup:
            key = cleaned.casefold()
            if key in seen:
                continue
            seen.add(key)
        items.append(cleaned)
    return items


def optional_int(
    value: Any,
    field_name: str,
    *,
    non_negative: bool = False,
    error: type[Exception] = ValueError,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise error(f"{field_name} must be an integer when provided")
    if non_negative and value < 0:
        raise error(f"{field_name} must be non-negative when provided")
    return value


def optional_non_negative_float(
    value: Any,
    field_name: str,
    *,
    error: type[Exception] = ValueError,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error(f"{field_name} must be numeric when provided")
    if value < 0:
        raise error(f"{field_name} must be non-negative when provided")
    return float(value)


def optional_bool(
    value: Any,
    field_name: str,
    *,
    error: type[Exception] = ValueError,
) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise error(f"{field_name} must be a boolean when provided")
    return value


def required_number(
    value: Any,
    field_name: str,
    *,
    error: type[Exception] = ValueError,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error(f"{field_name} must be numeric")
    return float(value)


__all__ = [
    "required_string",
    "optional_string",
    "optional_text_or_empty",
    "string_list",
    "optional_int",
    "optional_non_negative_float",
    "optional_bool",
    "required_number",
]
