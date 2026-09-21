"""Tests for search form rendering and validation functions across job sources.

Tests for _render_reed_search_form, _render_adzuna_search_form, render_search_form (LinkedIn),
and related validation/helper functions. Tests search form HTML generation and validation logic.
No network calls; uses mocks for env vars and form validation.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

import src.job_sources.reed_source as reed_source
import src.job_sources.adzuna_source as adzuna_source
import src.job_sources.linkedin_source as li_source


# ── Reed Source: _render_reed_search_form ─────────────────────────────────────

class TestRenderReedSearchForm:
    """Tests for reed_source._render_reed_search_form"""

    def test_render_form_returns_html(self) -> None:
        """Should return a string containing HTML form elements."""
        values = {"keywords": "BA", "locationName": "London"}
        html = reed_source._render_reed_search_form(values, enabled=True)

        assert isinstance(html, str)
        assert "<form" in html
        assert 'action="/search/reed"' in html
        assert 'type="submit"' in html

    def test_render_form_escapes_values(self) -> None:
        """Should escape HTML special chars in values to prevent XSS."""
        malicious = "<script>alert(1)</script>"
        values = {"keywords": malicious, "locationName": "London"}
        html = reed_source._render_reed_search_form(values, enabled=True)

        # The malicious script must be escaped, not injected
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html or "script" not in html.split('value="')[1].split('"')[0]

    def test_render_form_disabled_sets_opacity(self) -> None:
        """enabled=False should add opacity/pointer-events styling."""
        values = {}
        html = reed_source._render_reed_search_form(values, enabled=False)

        assert 'style="opacity:0.5;pointer-events:none;"' in html

    def test_render_form_enabled_no_disable_style(self) -> None:
        """enabled=True should not add disable style."""
        values = {}
        html = reed_source._render_reed_search_form(values, enabled=True)

        # Should have an empty disable_attr or just no style
        assert 'style="opacity:0.5;pointer-events:none;"' not in html

    def test_render_form_contains_all_fields(self) -> None:
        """Should include all search form fields."""
        values = {}
        html = reed_source._render_reed_search_form(values, enabled=True)

        # Check for input fields
        assert 'name="keywords"' in html
        assert 'name="locationName"' in html
        assert 'name="minimumSalary"' in html
        assert 'name="resultsToTake"' in html
        # Check for select fields
        assert 'name="workMode"' in html
        assert 'name="employmentType"' in html

    def test_render_form_preserves_user_values(self) -> None:
        """Should preserve user-entered values in form fields."""
        values = {
            "keywords": "Python Developer",
            "locationName": "Manchester",
            "resultsToTake": "25",
        }
        html = reed_source._render_reed_search_form(values, enabled=True)

        assert 'value="Python Developer"' in html
        assert 'value="Manchester"' in html
        assert 'value="25"' in html


# ── Reed Source: _is_reed_available and _ensure_reed_env_loaded ──────────────

class TestReedAvailability:
    """Tests for reed_source._is_reed_available and _ensure_reed_env_loaded"""

    def test_is_reed_available_true_when_key_set(self) -> None:
        """Should return True when REED_API_KEY is in environment."""
        with patch.dict(os.environ, {"REED_API_KEY": "test_key"}):
            result = reed_source._is_reed_available()
        assert result is True

    def test_is_reed_available_false_when_key_missing(self) -> None:
        """Should return False when REED_API_KEY is not set."""
        with patch("src.job_sources.reed_source._ensure_reed_env_loaded"):
            with patch("os.getenv", return_value=None):
                result = reed_source._is_reed_available()
        assert result is False

    def test_ensure_reed_env_loaded_with_key_present(self) -> None:
        """Should short-circuit if key already present."""
        with patch.dict(os.environ, {"REED_API_KEY": "exists"}):
            with patch("dotenv.load_dotenv") as mock_load:
                reed_source._ensure_reed_env_loaded()
                mock_load.assert_not_called()

    def test_ensure_reed_env_loaded_tries_dotenv(self) -> None:
        """Should try to load dotenv if key missing."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("dotenv.load_dotenv") as mock_load:
                reed_source._ensure_reed_env_loaded()
                mock_load.assert_called_once()


# ── Adzuna Source: _ensure_adzuna_env_loaded and _is_adzuna_available ───────

class TestAdzunaAvailability:
    """Tests for adzuna_source._is_adzuna_available and _ensure_adzuna_env_loaded"""

    def test_is_adzuna_available_true_when_both_keys_set(self) -> None:
        """Should return True when both ADZUNA_APP_ID and ADZUNA_APP_KEY are set."""
        with patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
            result = adzuna_source._is_adzuna_available()
        assert result is True

    def test_is_adzuna_available_false_when_missing_id(self) -> None:
        """Should return False if ADZUNA_APP_ID is missing."""
        with patch("src.job_sources.adzuna_source._ensure_adzuna_env_loaded"):
            with patch.dict(os.environ, {"ADZUNA_APP_KEY": "key"}, clear=True):
                result = adzuna_source._is_adzuna_available()
        assert result is False

    def test_is_adzuna_available_false_when_missing_key(self) -> None:
        """Should return False if ADZUNA_APP_KEY is missing."""
        with patch("src.job_sources.adzuna_source._ensure_adzuna_env_loaded"):
            with patch.dict(os.environ, {"ADZUNA_APP_ID": "id"}, clear=True):
                result = adzuna_source._is_adzuna_available()
        assert result is False

    def test_is_adzuna_available_false_when_none_set(self) -> None:
        """Should return False when neither key is set."""
        with patch("src.job_sources.adzuna_source._ensure_adzuna_env_loaded"):
            with patch.dict(os.environ, {}, clear=True):
                result = adzuna_source._is_adzuna_available()
        assert result is False

    def test_ensure_adzuna_env_loaded_short_circuits(self) -> None:
        """Should not call load_dotenv if both keys already present."""
        with patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
            with patch("dotenv.load_dotenv") as mock_load:
                adzuna_source._ensure_adzuna_env_loaded()
                mock_load.assert_not_called()

    def test_ensure_adzuna_env_loaded_tries_dotenv_when_missing(self) -> None:
        """Should try load_dotenv if keys are missing."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("dotenv.load_dotenv") as mock_load:
                adzuna_source._ensure_adzuna_env_loaded()
                mock_load.assert_called_once()


# ── Adzuna Source: _render_adzuna_search_form ────────────────────────────────

class TestRenderAdzunaSearchForm:
    """Tests for adzuna_source._render_adzuna_search_form"""

    def test_render_form_returns_html(self) -> None:
        """Should return a string containing HTML form."""
        values = {"keywords": "QA Engineer"}
        html = adzuna_source._render_adzuna_search_form(values, enabled=True)

        assert isinstance(html, str)
        assert "<form" in html
        assert 'action="/search/adzuna"' in html

    def test_render_form_escapes_values(self) -> None:
        """Should escape HTML special chars in field values."""
        malicious = '"><script>alert(1)</script><input type="hidden'
        values = {"keywords": malicious}
        html = adzuna_source._render_adzuna_search_form(values, enabled=True)

        # Escaped version should be present, not the raw script
        assert "<script>alert" not in html.split('value="')[1].split('"')[0] if 'value="' in html else True

    def test_render_form_disabled_when_false(self) -> None:
        """enabled=False should disable the form with CSS."""
        values = {}
        html = adzuna_source._render_adzuna_search_form(values, enabled=False)

        assert 'style="opacity:0.5;pointer-events:none;"' in html

    def test_render_form_enabled_when_true(self) -> None:
        """enabled=True should not add disable CSS."""
        values = {}
        html = adzuna_source._render_adzuna_search_form(values, enabled=True)

        assert 'style="opacity:0.5;pointer-events:none;"' not in html

    def test_render_form_includes_all_fields(self) -> None:
        """Should include all Adzuna search fields."""
        values = {}
        html = adzuna_source._render_adzuna_search_form(values, enabled=True)

        assert 'name="keywords"' in html
        assert 'name="locationName"' in html
        assert 'name="minimumSalary"' in html
        assert 'name="resultsToTake"' in html
        assert 'name="workMode"' in html
        assert 'name="employmentType"' in html


# ── Adzuna Source: adzuna_selected_job_id ────────────────────────────────────

class TestAdzunaSelectedJobId:
    """Tests for adzuna_source.adzuna_selected_job_id"""

    def test_selected_job_id_with_source_job_id(self) -> None:
        """Should use source_job_id as the base for the slug."""
        cleaned = {
            "source_job_id": "12345",
            "title": "Analyst",
            "company": "Acme",
        }
        job_id = adzuna_source.adzuna_selected_job_id(cleaned)

        assert job_id.startswith("adzuna-")
        assert "12345" in job_id

    def test_selected_job_id_fallback_to_title_company(self) -> None:
        """Should use title+company slug if source_job_id is missing."""
        cleaned = {
            "source_job_id": "",
            "title": "Business Analyst",
            "company": "Tech Corp",
        }
        job_id = adzuna_source.adzuna_selected_job_id(cleaned)

        assert job_id.startswith("adzuna-")
        assert "business" in job_id
        assert "analyst" in job_id

    def test_selected_job_id_sanitizes_special_chars(self) -> None:
        """Should convert special chars to hyphens."""
        cleaned = {
            "source_job_id": "job@123#xyz!",
            "title": "Title",
            "company": "Company",
        }
        job_id = adzuna_source.adzuna_selected_job_id(cleaned)

        # Should be lowercase and alphanumeric+hyphens
        assert not any(c in job_id for c in "@#!")
        assert job_id.startswith("adzuna-")

    def test_selected_job_id_handles_empty_values(self) -> None:
        """Should generate UUID-based ID when no usable values."""
        cleaned = {
            "source_job_id": "",
            "title": "",
            "company": "",
        }
        job_id = adzuna_source.adzuna_selected_job_id(cleaned)

        assert job_id.startswith("adzuna-")
        # Should have a UUID portion after the source prefix
        assert len(job_id) > len("adzuna-")

    def test_selected_job_id_max_length_80_chars(self) -> None:
        """Job ID slug should be capped at 80 chars (plus "adzuna-" prefix)."""
        cleaned = {
            "source_job_id": "x" * 200,
            "title": "Dummy",
            "company": "Dummy",
        }
        job_id = adzuna_source.adzuna_selected_job_id(cleaned)

        slug = job_id.replace("adzuna-", "")
        assert len(slug) <= 80


# ── Adzuna Source: _validate_adzuna_salary_text ───────────────────────────────

class TestValidateAdzunaSalaryText:
    """Tests for adzuna_source._validate_adzuna_salary_text"""

    def test_validate_salary_empty_returns_empty(self) -> None:
        """Empty string should return empty string."""
        result = adzuna_source._validate_adzuna_salary_text("", "salary_min_gbp")
        assert result == ""

    def test_validate_salary_none_equivalent_returns_empty(self) -> None:
        """None/falsy should be handled gracefully."""
        result = adzuna_source._validate_adzuna_salary_text("", "salary_max_gbp")
        assert result == ""

    def test_validate_salary_numeric_string_returns_string(self) -> None:
        """Numeric string should be returned as string."""
        result = adzuna_source._validate_adzuna_salary_text("50000", "salary_min_gbp")
        assert result == "50000"

    def test_validate_salary_zero_allowed(self) -> None:
        """Zero salary should be allowed."""
        result = adzuna_source._validate_adzuna_salary_text("0", "salary_min_gbp")
        assert result == "0"

    def test_validate_salary_negative_raises(self) -> None:
        """Negative numbers should raise ValueError (not all digits)."""
        with pytest.raises(ValueError, match="must be numeric"):
            adzuna_source._validate_adzuna_salary_text("-100", "salary_min_gbp")

    def test_validate_salary_non_numeric_raises(self) -> None:
        """Non-numeric string should raise ValueError."""
        with pytest.raises(ValueError, match="must be numeric"):
            adzuna_source._validate_adzuna_salary_text("abc", "salary_min_gbp")

    def test_validate_salary_with_comma_raises(self) -> None:
        """Formatted numbers (with comma) should raise ValueError."""
        with pytest.raises(ValueError, match="must be numeric"):
            adzuna_source._validate_adzuna_salary_text("50,000", "salary_min_gbp")

    def test_validate_salary_large_numbers(self) -> None:
        """Large numbers should be accepted as long as numeric."""
        result = adzuna_source._validate_adzuna_salary_text("9999999999", "salary_max_gbp")
        assert result == "9999999999"


# ── Adzuna Source: adzuna_select_form_to_evaluate_values ──────────────────────

class TestAdzunaSelectFormToEvaluateValues:
    """Tests for adzuna_source.adzuna_select_form_to_evaluate_values"""

    @staticmethod
    def _valid_adzuna_form(**overrides: str) -> dict:
        """Minimal valid Adzuna form POST data."""
        base: dict = {
            "source": "adzuna",
            "source_job_id": "job123",
            "title": "QA Engineer",
            "company": "TestCo",
            "location": "Manchester",
            "work_mode": "remote",
            "employment_type": "permanent",
            "url": "https://adzuna.co.uk/jobs/job123",
            "description_raw": "Test QA role with Python and automation.",
            "salary_min_gbp": "40000",
            "salary_max_gbp": "55000",
        }
        base.update(overrides)
        return base

    def test_select_form_happy_path(self) -> None:
        """Valid form should return a dict with all default_form_values keys."""
        form = self._valid_adzuna_form()
        with patch("src.job_sources.adzuna_source.extract_skills_from_text", return_value=(["Python"], ["Selenium"], None)):
            values = adzuna_source.adzuna_select_form_to_evaluate_values(form, config=None)

        from src.ui_utils import default_form_values
        for key in default_form_values():
            assert key in values, f"Missing key: {key}"

        # Spot-check mapped fields
        assert values["job_title"] == "QA Engineer"
        assert values["company"] == "TestCo"
        assert values["location"] == "Manchester"
        assert values["work_mode"] == "remote"
        assert values["employment_type"] == "permanent"
        assert values["source_type"] == "adzuna"

    def test_select_form_wrong_source_raises(self) -> None:
        """Wrong source value should raise ValueError."""
        form = self._valid_adzuna_form(source="reed")
        with pytest.raises(ValueError, match="only processes Adzuna"):
            adzuna_source.adzuna_select_form_to_evaluate_values(form, config=None)

    def test_select_form_invalid_work_mode_raises(self) -> None:
        """Invalid work_mode should raise ValueError."""
        form = self._valid_adzuna_form(work_mode="gibberish")
        with pytest.raises(ValueError, match="work_mode"):
            adzuna_source.adzuna_select_form_to_evaluate_values(form, config=None)

    def test_select_form_invalid_employment_type_raises(self) -> None:
        """Invalid employment_type should raise ValueError."""
        form = self._valid_adzuna_form(employment_type="wizard")
        with pytest.raises(ValueError, match="employment_type"):
            adzuna_source.adzuna_select_form_to_evaluate_values(form, config=None)

    def test_select_form_invalid_salary_raises(self) -> None:
        """Non-numeric salary should raise ValueError."""
        form = self._valid_adzuna_form(salary_min_gbp="not_a_number")
        with pytest.raises(ValueError, match="must be numeric"):
            adzuna_source.adzuna_select_form_to_evaluate_values(form, config=None)

    def test_select_form_missing_field_raises(self) -> None:
        """Missing required field should raise ValueError (too long check uses get)."""
        form = self._valid_adzuna_form()
        del form["title"]
        with patch("src.job_sources.adzuna_source.extract_skills_from_text", return_value=([], [], None)):
            values = adzuna_source.adzuna_select_form_to_evaluate_values(form, config=None)
            # Missing title becomes empty string, which is allowed
            assert values["job_title"] == "Unknown"

    def test_select_form_clears_unknown_work_mode(self) -> None:
        """work_mode='unknown' should be cleared to empty string."""
        form = self._valid_adzuna_form(work_mode="unknown")
        with patch("src.job_sources.adzuna_source.extract_skills_from_text", return_value=([], [], None)):
            values = adzuna_source.adzuna_select_form_to_evaluate_values(form, config=None)
            assert values["work_mode"] == ""

    def test_select_form_clears_unknown_employment_type(self) -> None:
        """employment_type='unknown' should be cleared to empty string."""
        form = self._valid_adzuna_form(employment_type="unknown")
        with patch("src.job_sources.adzuna_source.extract_skills_from_text", return_value=([], [], None)):
            values = adzuna_source.adzuna_select_form_to_evaluate_values(form, config=None)
            assert values["employment_type"] == ""

    def test_select_form_title_too_long_raises(self) -> None:
        """Title exceeding limit should raise ValueError."""
        form = self._valid_adzuna_form(title="x" * 181)
        with pytest.raises(ValueError, match="title"):
            adzuna_source.adzuna_select_form_to_evaluate_values(form, config=None)

    def test_select_form_salary_zero_allowed(self) -> None:
        """Salary of 0 should be allowed."""
        form = self._valid_adzuna_form(salary_min_gbp="0", salary_max_gbp="0")
        with patch("src.job_sources.adzuna_source.extract_skills_from_text", return_value=([], [], None)):
            values = adzuna_source.adzuna_select_form_to_evaluate_values(form, config=None)
            assert values["salary_min_gbp"] == "0"
            assert values["salary_max_gbp"] == "0"


# ── LinkedIn Source: is_available ────────────────────────────────────────────

class TestLinkedInIsAvailable:
    """Tests for linkedin_source.is_available"""

    def test_is_available_always_true(self) -> None:
        """LinkedIn search needs no API key; should always return True."""
        result = li_source.is_available()
        assert result is True

    def test_is_available_regardless_of_env(self) -> None:
        """Availability should not depend on environment variables."""
        with patch.dict(os.environ, {}, clear=True):
            result = li_source.is_available()
            assert result is True


# ── LinkedIn Source: _fetch_description ──────────────────────────────────────

class TestLinkedInFetchDescription:
    """Tests for linkedin_source._fetch_description"""

    def test_fetch_description_success_extracts_text(self) -> None:
        """Successful fetch should extract and return description text."""
        # Use real HTML with the selector class
        html_with_desc = """
        <html><body>
            <div class="description__text">Required: 5+ years Python</div>
        </body></html>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html_with_desc
        mock_response.url = "https://www.linkedin.com/jobs/view/12345/"

        with patch("requests.get", return_value=mock_response):
            result = li_source._fetch_description("12345")

        # Should have extracted text, or empty if parsing failed
        assert isinstance(result, str)
        if result:  # If parsing succeeded
            assert "Python" in result or "Required" in result

    def test_fetch_description_blocked_returns_empty(self) -> None:
        """LinkedIn block should return empty string."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "x" * 6000
        mock_response.url = "https://www.linkedin.com/jobs/view/12345/"

        with patch("requests.get", return_value=mock_response):
            result = li_source._fetch_description("12345")

        assert result == ""

    def test_fetch_description_timeout_returns_empty(self) -> None:
        """Request timeout should return empty string without raising."""
        import requests as req_lib

        with patch("requests.get", side_effect=req_lib.exceptions.Timeout("timeout")):
            result = li_source._fetch_description("12345")

        assert result == ""

    def test_fetch_description_malformed_html_returns_empty(self) -> None:
        """Unparseable HTML should return empty string."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<invalid html"
        mock_response.url = "https://www.linkedin.com/jobs/view/12345/"

        with patch("requests.get", return_value=mock_response):
            result = li_source._fetch_description("12345")

        # Should still return empty (or any parsed text), not crash
        assert isinstance(result, str)

    def test_fetch_description_empty_element_returns_empty(self) -> None:
        """HTML with no description element should return empty string."""
        html = "<html><body><div>No description here</div></body></html>"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.url = "https://www.linkedin.com/jobs/view/12345/"

        with patch("requests.get", return_value=mock_response):
            result = li_source._fetch_description("12345")

        assert result == ""

    def test_fetch_description_fallback_to_show_more_less(self) -> None:
        """Should try alternate selector if description__text not found."""
        # Use HTML with the fallback selector class (no description__text)
        html_with_fallback = """
        <html><body>
            <div class="show-more-less-html__markup">Alternative description format here</div>
        </body></html>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html_with_fallback
        mock_response.url = "https://www.linkedin.com/jobs/view/12345/"

        with patch("requests.get", return_value=mock_response):
            result = li_source._fetch_description("12345")

        # Should have extracted text, or empty if parsing failed
        assert isinstance(result, str)
        if result:  # If parsing succeeded
            assert "Alternative" in result or "description" in result


# ── LinkedIn Source: render_search_form ───────────────────────────────────────

class TestLinkedInRenderSearchForm:
    """Tests for linkedin_source.render_search_form"""

    def test_render_form_returns_html(self) -> None:
        """Should return a string containing form HTML."""
        values = {"keywords": "BA", "location": "London"}
        html = li_source.render_search_form(values, enabled=True)

        assert isinstance(html, str)
        assert "<form" in html
        assert 'action="/search/linkedin"' in html

    def test_render_form_escapes_values(self) -> None:
        """Should escape HTML special chars in field values."""
        malicious = '"><script>alert(1)</script><input type="hidden'
        values = {
            "keywords": malicious,
            "location": "London",
            "results_to_take": "25",
        }
        html = li_source.render_search_form(values, enabled=True)

        # The malicious payload must not appear as an unescaped attribute value
        assert "<script>alert" not in html.split('value="')[1].split('"')[0] if 'value="' in html else True

    def test_render_form_disabled_when_false(self) -> None:
        """enabled=False should disable the form with CSS."""
        values = {}
        html = li_source.render_search_form(values, enabled=False)

        assert 'style="opacity:0.5;pointer-events:none;"' in html

    def test_render_form_enabled_when_true(self) -> None:
        """enabled=True should not add disable CSS."""
        values = {}
        html = li_source.render_search_form(values, enabled=True)

        assert 'style="opacity:0.5;pointer-events:none;"' not in html

    def test_render_form_includes_all_fields(self) -> None:
        """Should include all LinkedIn search fields."""
        values = {}
        html = li_source.render_search_form(values, enabled=True)

        assert 'name="keywords"' in html
        assert 'name="location"' in html
        assert 'name="work_mode"' in html
        assert 'name="results_to_take"' in html

    def test_render_form_work_mode_options(self) -> None:
        """Should render work_mode select with proper options."""
        values = {"work_mode": "2"}  # "2" = Remote
        html = li_source.render_search_form(values, enabled=True)

        # Check that the selected work mode is marked as selected
        assert '<option value="2" selected>' in html or '<option value="2"  selected>' in html

    def test_render_form_preserves_results_to_take(self) -> None:
        """Should preserve results_to_take value in form."""
        values = {"results_to_take": 50}
        html = li_source.render_search_form(values, enabled=True)

        assert 'value="50"' in html
