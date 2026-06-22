"""Unit tests for the shared validation helpers (MT-2)."""
from __future__ import annotations

import pytest

from src.job_hunt_validation import (
    optional_bool,
    optional_int,
    optional_non_negative_float,
    optional_string,
    optional_text_or_empty,
    required_number,
    required_string,
    string_list,
)


class Boom(ValueError):
    """Stand-in for a module-specific *Error class."""


# --- required_string: message_style (reviewer finding #1) -------------------
def test_required_string_combined_message() -> None:
    with pytest.raises(Boom, match="x must be a non-empty string"):
        required_string("  ", "x", message_style="combined", error=Boom)


def test_required_string_split_messages() -> None:
    with pytest.raises(Boom, match="x must be a string"):
        required_string(5, "x", message_style="split", error=Boom)
    with pytest.raises(Boom, match="x must not be empty"):
        required_string("  ", "x", message_style="split", error=Boom)


def test_required_string_returns_stripped() -> None:
    assert required_string("  hi ", "x", error=Boom) == "hi"
    assert required_string("  hi ", "x", message_style="combined", error=Boom) == "hi"


# --- numeric helpers reject bool (reviewer finding #2) ----------------------
@pytest.mark.parametrize("bad", [True, False])
def test_required_number_rejects_bool(bad: bool) -> None:
    with pytest.raises(Boom):
        required_number(bad, "x", error=Boom)


@pytest.mark.parametrize("bad", [True, False])
def test_optional_int_rejects_bool(bad: bool) -> None:
    with pytest.raises(Boom):
        optional_int(bad, "x", error=Boom)


@pytest.mark.parametrize("bad", [True, False])
def test_optional_non_negative_float_rejects_bool(bad: bool) -> None:
    with pytest.raises(Boom):
        optional_non_negative_float(bad, "x", error=Boom)


def test_optional_int_negative_handling() -> None:
    assert optional_int(-1, "x", non_negative=False, error=Boom) == -1  # storage
    with pytest.raises(Boom, match="non-negative"):
        optional_int(-1, "x", non_negative=True, error=Boom)  # reviewed/profile
    assert optional_int(None, "x", error=Boom) is None


def test_required_number_and_float() -> None:
    assert required_number(3, "x", error=Boom) == 3.0
    assert optional_non_negative_float(2, "x", error=Boom) == 2.0
    assert optional_non_negative_float(None, "x", error=Boom) is None
    with pytest.raises(Boom, match="non-negative"):
        optional_non_negative_float(-0.5, "x", error=Boom)


# --- optional_text_or_empty whitespace trap (reviewer finding #3) -----------
def test_optional_text_or_empty_preserves_whitespace() -> None:
    assert optional_text_or_empty(" ", "x", error=Boom) == " "   # NOT stripped/None
    assert optional_text_or_empty("", "x", error=Boom) is None
    assert optional_text_or_empty(None, "x", error=Boom) is None
    assert optional_text_or_empty("hi", "x", error=Boom) == "hi"
    with pytest.raises(Boom):
        optional_text_or_empty(5, "x", error=Boom)


# --- optional_string + empty_as_none ----------------------------------------
def test_optional_string_variants() -> None:
    assert optional_string(None, "x", error=Boom) is None
    assert optional_string("  a ", "x", error=Boom) == "a"
    with pytest.raises(Boom, match="must not be empty when provided"):
        optional_string("  ", "x", error=Boom)
    assert optional_string("  ", "x", empty_as_none=True, error=Boom) is None
    with pytest.raises(Boom, match="must be a string when provided"):
        optional_string(5, "x", error=Boom)


# --- string_list: the three variants ----------------------------------------
def test_string_list_storage_variant_keeps_raw_and_empty() -> None:
    # storage: no strip, no dedup, empty items allowed
    out = string_list([" a ", "", "a"], "x", strip=False, dedup=False,
                      allow_empty_items=True, error=Boom)
    assert out == [" a ", "", "a"]


def test_string_list_profile_variant_strips_rejects_empty_no_dedup() -> None:
    out = string_list([" a ", "B"], "x", strip=True, dedup=False,
                      allow_empty_items=False, error=Boom)
    assert out == ["a", "B"]
    with pytest.raises(Boom, match="must not contain empty strings"):
        string_list(["  "], "x", strip=True, allow_empty_items=False, error=Boom)
    # no dedup → both kept
    assert string_list(["SQL", "sql"], "x", strip=True, dedup=False,
                       allow_empty_items=False, error=Boom) == ["SQL", "sql"]


def test_string_list_reviewed_variant_dedups_casefold() -> None:
    out = string_list(["SQL", "sql", " Python "], "x", strip=True, dedup=True,
                      allow_empty_items=False, error=Boom)
    assert out == ["SQL", "Python"]


def test_string_list_type_errors_and_none() -> None:
    assert string_list(None, "x", error=Boom) == []
    with pytest.raises(Boom, match="must be a list of strings"):
        string_list("notalist", "x", error=Boom)
    with pytest.raises(Boom, match="must contain only strings"):
        string_list([1], "x", error=Boom)


# --- optional_bool ----------------------------------------------------------
def test_optional_bool() -> None:
    assert optional_bool(None, "x", error=Boom) is None
    assert optional_bool(True, "x", error=Boom) is True
    with pytest.raises(Boom):
        optional_bool("yes", "x", error=Boom)
