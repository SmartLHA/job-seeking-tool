"""Tests for miscellaneous uncovered pure functions across modules."""
from __future__ import annotations

import json

import pytest

from src import job_hunt_llm as llm_module
from src import job_hunt_tailoring as tailoring_module
from src import job_hunt_index as index_module
from src import job_hunt_parsing as parsing_module


# ─────────────────────────────────────────────────────────────────────────
# job_hunt_llm._parse_json_from_text
# ─────────────────────────────────────────────────────────────────────────


class TestParseJsonFromText:
    def test_parse_clean_json(self) -> None:
        """_parse_json_from_text extracts clean JSON object."""
        raw = '{"key": "value", "number": 42}'
        result = llm_module._parse_json_from_text(raw)

        assert result == {"key": "value", "number": 42}

    def test_parse_json_with_markdown_fences(self) -> None:
        """_parse_json_from_text strips markdown ```json fences."""
        raw = '```json\n{"key": "value"}\n```'
        result = llm_module._parse_json_from_text(raw)

        assert result == {"key": "value"}

    def test_parse_json_with_fences_no_json_label(self) -> None:
        """_parse_json_from_text handles ``` without json label."""
        raw = '```\n{"key": "value"}\n```'
        result = llm_module._parse_json_from_text(raw)

        assert result == {"key": "value"}

    def test_parse_json_with_surrounding_text(self) -> None:
        """_parse_json_from_text extracts JSON from prose."""
        raw = "Here's the analysis:\n{\n  \"fit\": \"good\",\n  \"risk\": \"low\"\n}\nEnd of analysis"
        result = llm_module._parse_json_from_text(raw)

        assert result == {"fit": "good", "risk": "low"}

    def test_parse_json_nested_structure(self) -> None:
        """_parse_json_from_text handles nested objects."""
        raw = '{"outer": {"inner": "value"}, "array": [1, 2, 3]}'
        result = llm_module._parse_json_from_text(raw)

        assert result == {"outer": {"inner": "value"}, "array": [1, 2, 3]}

    def test_parse_invalid_json_returns_none(self) -> None:
        """_parse_json_from_text returns None for invalid JSON."""
        raw = '{invalid json}'
        result = llm_module._parse_json_from_text(raw)

        assert result is None

    def test_parse_empty_string_returns_none(self) -> None:
        """_parse_json_from_text returns None for empty input."""
        result = llm_module._parse_json_from_text("")

        assert result is None

    def test_parse_no_braces_returns_none(self) -> None:
        """_parse_json_from_text returns None when no {...} found."""
        raw = "just some text without json"
        result = llm_module._parse_json_from_text(raw)

        assert result is None

    def test_parse_unmatched_braces_returns_none(self) -> None:
        """_parse_json_from_text returns None for unmatched braces."""
        raw = '{"key": "value"'
        result = llm_module._parse_json_from_text(raw)

        assert result is None

    def test_parse_multiple_json_objects_extracts_first(self) -> None:
        """_parse_json_from_text extracts content between first { and last }."""
        raw = '{"first": "object"} and {"second": "object"}'
        result = llm_module._parse_json_from_text(raw)

        # Extracting from first { to last } is invalid JSON, so it fails closed.
        assert result is None

    def test_parse_json_with_escaped_quotes(self) -> None:
        """_parse_json_from_text handles escaped quotes in JSON."""
        raw = '{"message": "He said \\"hello\\""}'
        result = llm_module._parse_json_from_text(raw)

        assert result == {"message": 'He said "hello"'}

    def test_parse_json_unicode(self) -> None:
        """_parse_json_from_text handles unicode characters."""
        raw = '{"text": "café", "emoji": "✓"}'
        result = llm_module._parse_json_from_text(raw)

        assert result == {"text": "café", "emoji": "✓"}


# ─────────────────────────────────────────────────────────────────────────
# job_hunt_tailoring._extract_bullet_lines and _extract_plain_lines
# ─────────────────────────────────────────────────────────────────────────


class TestExtractBulletLines:
    def test_extract_bullets_with_dash(self) -> None:
        """_extract_bullet_lines extracts lines starting with '- '."""
        text = "## Skills\n- Python\n- SQL\n- Excel\n## Other\n- Text"
        result = tailoring_module._extract_bullet_lines(text, "## Skills")

        assert result == ["Python", "SQL", "Excel"]

    def test_extract_bullets_stops_at_next_section(self) -> None:
        """_extract_bullet_lines stops at next '## ' marker."""
        text = "## Skills\n- Python\n- SQL\n## Experience\n- 5 years"
        result = tailoring_module._extract_bullet_lines(text, "## Skills")

        assert result == ["Python", "SQL"]

    def test_extract_bullets_missing_section_returns_empty(self) -> None:
        """_extract_bullet_lines returns empty list if section not found."""
        text = "## Skills\n- Python"
        result = tailoring_module._extract_bullet_lines(text, "## Missing")

        assert result == []

    def test_extract_bullets_empty_section(self) -> None:
        """_extract_bullet_lines returns empty list for section with no bullets."""
        text = "## Skills\n## Other\n- Text"
        result = tailoring_module._extract_bullet_lines(text, "## Skills")

        assert result == []

    def test_extract_bullets_with_asterisk(self) -> None:
        """_extract_bullet_lines only extracts '- ' prefix, not '* '."""
        text = "## Skills\n- Python\n* SQL"
        result = tailoring_module._extract_bullet_lines(text, "## Skills")

        # Only '- ' is extracted
        assert "Python" in result
        assert "SQL" not in result

    def test_extract_bullets_strips_whitespace(self) -> None:
        """_extract_bullet_lines strips leading/trailing whitespace from bullets."""
        text = "## Skills\n-  Python  \n- SQL"
        result = tailoring_module._extract_bullet_lines(text, "## Skills")

        # Note: -  (dash + space + space) and - (dash + space) are both recognized
        assert "Python" in result
        assert "SQL" in result


class TestExtractPlainLines:
    def test_extract_plain_lines_simple(self) -> None:
        """_extract_plain_lines extracts all non-empty lines after section."""
        text = "## Skills\nPython\nSQL\n## Other\nText"
        result = tailoring_module._extract_plain_lines(text, "## Skills")

        assert result == ["Python", "SQL"]

    def test_extract_plain_lines_stops_at_marker(self) -> None:
        """_extract_plain_lines stops at '## ' (default marker)."""
        text = "## Skills\nPython\nSQL\n## Experience"
        result = tailoring_module._extract_plain_lines(text, "## Skills")

        assert result == ["Python", "SQL"]

    def test_extract_plain_lines_custom_stop_marker(self) -> None:
        """_extract_plain_lines respects custom stop_markers."""
        text = "## Skills\nPython\n---\nOther"
        result = tailoring_module._extract_plain_lines(text, "## Skills", stop_markers={"---"})

        assert result == ["Python"]

    def test_extract_plain_lines_missing_section(self) -> None:
        """_extract_plain_lines returns empty for missing section."""
        text = "## Skills\nPython"
        result = tailoring_module._extract_plain_lines(text, "## Missing")

        assert result == []

    def test_extract_plain_lines_ignores_empty_lines(self) -> None:
        """_extract_plain_lines skips empty lines."""
        text = "## Skills\nPython\n\nSQL\n\n## Other"
        result = tailoring_module._extract_plain_lines(text, "## Skills")

        assert result == ["Python", "SQL"]

    def test_extract_plain_lines_strips_whitespace(self) -> None:
        """_extract_plain_lines strips whitespace from each line."""
        text = "## Skills\n  Python  \n\tSQL\t"
        result = tailoring_module._extract_plain_lines(text, "## Skills")

        assert result == ["Python", "SQL"]

    def test_extract_plain_lines_at_end_of_text(self) -> None:
        """_extract_plain_lines handles section at end of text."""
        text = "## Skills\nPython\nSQL"
        result = tailoring_module._extract_plain_lines(text, "## Skills")

        assert result == ["Python", "SQL"]


# ─────────────────────────────────────────────────────────────────────────
# job_hunt_index.apply_url_from_ui_result
# ─────────────────────────────────────────────────────────────────────────


class TestApplyUrlFromUiResult:
    def test_apply_url_with_url_key(self) -> None:
        """apply_url_from_ui_result extracts 'url' key as string."""
        result = {"url": "https://example.com/job-123"}
        url = index_module.apply_url_from_ui_result(result)

        assert url == "https://example.com/job-123"

    def test_apply_url_strips_whitespace(self) -> None:
        """apply_url_from_ui_result strips whitespace."""
        result = {"url": "  https://example.com  "}
        url = index_module.apply_url_from_ui_result(result)

        assert url == "https://example.com"

    def test_apply_url_missing_key_returns_empty(self) -> None:
        """apply_url_from_ui_result returns empty string when 'url' key missing."""
        result = {"job_id": "123", "title": "BA"}
        url = index_module.apply_url_from_ui_result(result)

        assert url == ""

    def test_apply_url_none_value_returns_empty(self) -> None:
        """apply_url_from_ui_result returns empty string when 'url' is None."""
        result = {"url": None}
        url = index_module.apply_url_from_ui_result(result)

        assert url == ""

    def test_apply_url_converts_to_string(self) -> None:
        """apply_url_from_ui_result converts non-string values to string."""
        result = {"url": 12345}
        url = index_module.apply_url_from_ui_result(result)

        assert url == "12345"

    def test_apply_url_empty_dict(self) -> None:
        """apply_url_from_ui_result handles empty dict."""
        result = {}
        url = index_module.apply_url_from_ui_result(result)

        assert url == ""


# ─────────────────────────────────────────────────────────────────────────
# job_hunt_parsing._is_fetch_allowed
# ─────────────────────────────────────────────────────────────────────────


class TestIsFetchAllowed:
    def test_is_fetch_allowed_calls_robots_cache(self, monkeypatch) -> None:
        """_is_fetch_allowed delegates to _robots_cache.is_allowed."""
        cache_calls = []

        def fake_is_allowed(url, agent):
            cache_calls.append((url, agent))
            return True

        monkeypatch.setattr(
            parsing_module._robots_cache,
            "is_allowed",
            fake_is_allowed,
        )

        result = parsing_module._is_fetch_allowed("https://example.com/page")

        assert result is True
        assert len(cache_calls) == 1
        assert cache_calls[0][0] == "https://example.com/page"
        assert cache_calls[0][1] == parsing_module.DEFAULT_USER_AGENT

    def test_is_fetch_allowed_returns_false_when_denied(self, monkeypatch) -> None:
        """_is_fetch_allowed returns False when robots.txt denies."""
        def fake_is_allowed(url, agent):
            return False

        monkeypatch.setattr(
            parsing_module._robots_cache,
            "is_allowed",
            fake_is_allowed,
        )

        result = parsing_module._is_fetch_allowed("https://example.com/page")

        assert result is False

    def test_is_fetch_allowed_with_various_urls(self, monkeypatch) -> None:
        """_is_fetch_allowed passes through URLs correctly."""
        captured_urls = []

        def fake_is_allowed(url, agent):
            captured_urls.append(url)
            return True

        monkeypatch.setattr(
            parsing_module._robots_cache,
            "is_allowed",
            fake_is_allowed,
        )

        test_urls = [
            "https://indeed.com/jobs?q=python",
            "https://linkedin.com/jobs/search",
            "https://example.com/page.html",
        ]

        for url in test_urls:
            parsing_module._is_fetch_allowed(url)

        assert captured_urls == test_urls
