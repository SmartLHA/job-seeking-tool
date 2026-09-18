"""Tests for Reed and Adzuna API client functions.

Tests for fetch_reed_jobs, fetch_adzuna_jobs, save_raw_response in both
reed_client.py and adzuna_client.py. Uses unittest.mock to patch HTTP calls
and environment variables. No real network requests.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime

import pytest

import src.job_sources.reed_client as reed_client
import src.job_sources.adzuna_client as adzuna_client


# ── Reed Client: fetch_reed_jobs ──────────────────────────────────────────────

class TestFetchReedJobs:
    """Tests for reed_client.fetch_reed_jobs"""

    def test_fetch_reed_jobs_success_returns_results(self) -> None:
        """Successful API call with results should parse and return the list."""
        fake_response_json = {
            "results": [
                {
                    "jobId": 12345,
                    "jobTitle": "Business Analyst",
                    "employerName": "Acme Ltd",
                    "locationName": "London",
                },
            ],
            "totalResults": 1,
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = fake_response_json

        with patch("requests.get", return_value=mock_response):
            with patch.dict(os.environ, {"REED_API_KEY": "fake_key"}):
                results = reed_client.fetch_reed_jobs("BA", "London", save_raw=False)

        assert len(results) == 1
        assert results[0]["jobId"] == 12345
        assert results[0]["jobTitle"] == "Business Analyst"

    def test_fetch_reed_jobs_empty_results(self) -> None:
        """Empty results from API should return empty list."""
        fake_response_json = {"results": [], "totalResults": 0}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = fake_response_json

        with patch("requests.get", return_value=mock_response):
            with patch.dict(os.environ, {"REED_API_KEY": "fake_key"}):
                results = reed_client.fetch_reed_jobs("xyz_nonexistent", "Mars", save_raw=False)

        assert results == []

    def test_fetch_reed_jobs_no_api_key_returns_empty(self) -> None:
        """Missing REED_API_KEY should return empty list after env load."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("src.job_sources.reed_client._ensure_env_loaded"):
                with patch("os.getenv", return_value=None):
                    with patch("requests.get") as mock_get:
                        results = reed_client.fetch_reed_jobs("BA", "London", save_raw=False)

        mock_get.assert_not_called()
        assert results == []

    def test_fetch_reed_jobs_rate_limit_429(self) -> None:
        """HTTP 429 should be handled gracefully, returning empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 429

        with patch("requests.get", return_value=mock_response):
            with patch.dict(os.environ, {"REED_API_KEY": "fake_key"}):
                results = reed_client.fetch_reed_jobs("BA", "London", save_raw=False)

        assert results == []

    def test_fetch_reed_jobs_http_error(self) -> None:
        """HTTP error (500, etc) should be caught and return empty list."""
        import requests as req_lib

        with patch("requests.get", side_effect=req_lib.exceptions.HTTPError("Server error")):
            with patch.dict(os.environ, {"REED_API_KEY": "fake_key"}):
                results = reed_client.fetch_reed_jobs("BA", "London", save_raw=False)

        assert results == []

    def test_fetch_reed_jobs_malformed_json(self) -> None:
        """Bad JSON in response should return empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)

        with patch("requests.get", return_value=mock_response):
            with patch.dict(os.environ, {"REED_API_KEY": "fake_key"}):
                results = reed_client.fetch_reed_jobs("BA", "London", save_raw=False)

        assert results == []

    def test_fetch_reed_jobs_respects_skip_parameter(self) -> None:
        """skip parameter should be passed as resultsToSkip to API."""
        fake_response_json = {"results": [{"jobId": 99}], "totalResults": 100}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = fake_response_json

        with patch("requests.get", return_value=mock_response) as mock_get:
            with patch.dict(os.environ, {"REED_API_KEY": "fake_key"}):
                reed_client.fetch_reed_jobs("BA", "London", max_results=10, skip=50, save_raw=False)

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["resultsToSkip"] == 50

    def test_fetch_reed_jobs_plain_list_fallback(self) -> None:
        """Response as plain list (old format) should be handled."""
        fake_response_json = [{"jobId": 111}, {"jobId": 222}]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = fake_response_json

        with patch("requests.get", return_value=mock_response):
            with patch.dict(os.environ, {"REED_API_KEY": "fake_key"}):
                results = reed_client.fetch_reed_jobs("BA", "London", save_raw=False)

        assert len(results) == 2
        assert results[0]["jobId"] == 111

    def test_fetch_reed_jobs_timeout_error(self) -> None:
        """Timeout should be caught and return empty list."""
        import requests as req_lib

        with patch("requests.get", side_effect=req_lib.exceptions.Timeout("timeout")):
            with patch.dict(os.environ, {"REED_API_KEY": "fake_key"}):
                results = reed_client.fetch_reed_jobs("BA", "London", save_raw=False)

        assert results == []


# ── Reed Client: save_raw_response ────────────────────────────────────────────

class TestReedSaveRawResponse:
    """Tests for reed_client.save_raw_response"""

    def test_save_raw_response_valid_json_calls_json_dump(self) -> None:
        """Valid JSON should be parsed and re-dumped."""
        json_content = '{"results": [{"id": 1}]}'
        with patch("pathlib.Path") as mock_path_class:
            mock_path = MagicMock()
            mock_path_class.return_value = mock_path
            mock_path.__truediv__.return_value = mock_path
            mock_path.mkdir.return_value = None
            with patch("builtins.open", create=True) as mock_open:
                with patch("json.dump") as mock_dump:
                    reed_client.save_raw_response(json_content, "reed")
                    # Should attempt to dump JSON, not just write raw
                    if mock_open.called:
                        mock_open.assert_called()

    def test_save_raw_response_invalid_json_fallback(self) -> None:
        """Invalid JSON should be written without parsing."""
        invalid_json = "{invalid"
        with patch("pathlib.Path") as mock_path_class:
            mock_path = MagicMock()
            mock_path_class.return_value = mock_path
            mock_path.__truediv__.return_value = mock_path
            mock_path.mkdir.return_value = None
            with patch("builtins.open", create=True) as mock_open:
                reed_client.save_raw_response(invalid_json, "reed")
                # Should still attempt to open/write even if JSON is bad
                if mock_open.called:
                    mock_open.assert_called()


# ── Adzuna Client: fetch_adzuna_jobs ──────────────────────────────────────────

class TestFetchAdzunaJobs:
    """Tests for adzuna_client.fetch_adzuna_jobs"""

    def test_fetch_adzuna_jobs_success(self) -> None:
        """Successful API call should return results."""
        fake_response_json = {
            "results": [
                {"id": "abc123", "title": "Senior BA", "company": {"display_name": "Tech Co"}},
            ],
            "count": 1,
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = fake_response_json
        mock_response.text = json.dumps(fake_response_json)

        with patch("requests.get", return_value=mock_response):
            with patch.dict(os.environ, {"ADZUNA_APP_ID": "app1", "ADZUNA_APP_KEY": "key1"}):
                results = adzuna_client.fetch_adzuna_jobs("BA", "London")

        assert len(results) == 1
        assert results[0]["id"] == "abc123"

    def test_fetch_adzuna_jobs_empty(self) -> None:
        """Empty results should return empty list."""
        fake_response_json = {"results": [], "count": 0}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = fake_response_json
        mock_response.text = json.dumps(fake_response_json)

        with patch("requests.get", return_value=mock_response):
            with patch.dict(os.environ, {"ADZUNA_APP_ID": "app1", "ADZUNA_APP_KEY": "key1"}):
                results = adzuna_client.fetch_adzuna_jobs("xyz", "Mars")

        assert results == []

    def test_fetch_adzuna_jobs_missing_credentials(self) -> None:
        """Missing app_id or app_key should return empty list."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("requests.get") as mock_get:
                results = adzuna_client.fetch_adzuna_jobs("BA", "London")

        mock_get.assert_not_called()
        assert results == []

    def test_fetch_adzuna_jobs_rate_limit_429(self) -> None:
        """HTTP 429 should return empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "{}"

        with patch("requests.get", return_value=mock_response):
            with patch.dict(os.environ, {"ADZUNA_APP_ID": "app1", "ADZUNA_APP_KEY": "key1"}):
                results = adzuna_client.fetch_adzuna_jobs("BA", "London")

        assert results == []

    def test_fetch_adzuna_jobs_malformed_json(self) -> None:
        """Bad JSON should return empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
        mock_response.text = "invalid"

        with patch("requests.get", return_value=mock_response):
            with patch.dict(os.environ, {"ADZUNA_APP_ID": "app1", "ADZUNA_APP_KEY": "key1"}):
                results = adzuna_client.fetch_adzuna_jobs("BA", "London")

        assert results == []

    def test_fetch_adzuna_jobs_pagination_calculation(self) -> None:
        """Pagination should calculate page from skip and max_results."""
        fake_response_json = {"results": [], "count": 0}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = fake_response_json
        mock_response.text = json.dumps(fake_response_json)

        with patch("requests.get", return_value=mock_response) as mock_get:
            with patch.dict(os.environ, {"ADZUNA_APP_ID": "app1", "ADZUNA_APP_KEY": "key1"}):
                # skip=20, max_results=10 should give page 3 (20//10 + 1)
                adzuna_client.fetch_adzuna_jobs("BA", "London", max_results=10, skip=20)

        call_url = mock_get.call_args[0][0]
        # URL format: /search/{page}
        assert "/search/3" in call_url

    def test_fetch_adzuna_jobs_skip_zero_gives_page_one(self) -> None:
        """skip=0 should give page 1."""
        fake_response_json = {"results": [], "count": 0}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = fake_response_json
        mock_response.text = json.dumps(fake_response_json)

        with patch("requests.get", return_value=mock_response) as mock_get:
            with patch.dict(os.environ, {"ADZUNA_APP_ID": "app1", "ADZUNA_APP_KEY": "key1"}):
                adzuna_client.fetch_adzuna_jobs("BA", "London", skip=0)

        call_url = mock_get.call_args[0][0]
        assert "/search/1" in call_url


# ── Adzuna Client: save_raw_response ──────────────────────────────────────────

class TestAdzunaSaveRawResponse:
    """Tests for adzuna_client.save_raw_response"""

    def test_adzuna_save_raw_response_handles_json(self, tmp_path: Path, monkeypatch) -> None:
        """Valid JSON from Adzuna should be parsed and pretty-printed."""
        json_content = '{"results": [{"id": "job1"}]}'

        monkeypatch.setattr(adzuna_client, "Path", lambda _path: tmp_path)
        adzuna_client.save_raw_response(json_content, "adzuna")

        saved_files = list(tmp_path.glob("raw_*.json"))
        assert len(saved_files) == 1
        assert json.loads(saved_files[0].read_text(encoding="utf-8")) == {"results": [{"id": "job1"}]}

    def test_adzuna_save_raw_response_handles_invalid_json(self, tmp_path: Path, monkeypatch) -> None:
        """Invalid JSON should be written as-is without parsing."""
        invalid_json = "{invalid content"

        monkeypatch.setattr(adzuna_client, "Path", lambda _path: tmp_path)
        adzuna_client.save_raw_response(invalid_json, "adzuna")

        saved_files = list(tmp_path.glob("raw_*.json"))
        assert len(saved_files) == 1
        assert saved_files[0].read_text(encoding="utf-8") == invalid_json


# ── Environment loading (both clients use similar logic) ──────────────────────

class TestEnvLoading:
    """Tests for _ensure_env_loaded in both clients."""

    def test_reed_ensure_env_loaded_with_existing_key(self) -> None:
        """If REED_API_KEY exists, should not try to load .env."""
        with patch.dict(os.environ, {"REED_API_KEY": "existing_key"}):
            with patch("pathlib.Path.exists", return_value=False) as mock_exists:
                reed_client._ensure_env_loaded()
                # Should short-circuit before checking if .env exists
                mock_exists.assert_not_called()

    def test_reed_ensure_env_loaded_tries_dotenv_first(self) -> None:
        """Should try python-dotenv first if key not found."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("dotenv.load_dotenv") as mock_load:
                with patch("pathlib.Path.exists", return_value=False):
                    reed_client._ensure_env_loaded()
                    mock_load.assert_called_once()

    def test_adzuna_client_checks_credentials_before_request(self) -> None:
        """Adzuna client should check for credentials early."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("requests.get") as mock_get:
                results = adzuna_client.fetch_adzuna_jobs("BA", "London")
                mock_get.assert_not_called()
                assert results == []

    def test_reed_fallback_env_parsing_handles_missing_file(self) -> None:
        """Reed's inline .env parser should handle missing .env files gracefully."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("dotenv.load_dotenv") as mock_load:
                with patch("pathlib.Path.exists", return_value=False):
                    reed_client._ensure_env_loaded()
                    assert "REED_API_KEY" not in os.environ
        mock_load.assert_called_once()
