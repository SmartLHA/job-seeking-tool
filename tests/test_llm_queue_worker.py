"""Tests for job_hunt_scheduler.LLMQueueWorker — thread-safe queue consumer."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.job_hunt_scheduler import LLMQueueWorker


@pytest.fixture
def mock_config(tmp_path: Path) -> Mock:
    """Minimal mock config with state_root."""
    config = Mock()
    config.state_root = str(tmp_path)
    return config


@pytest.fixture
def mock_profile() -> Mock:
    """Profile with LLM settings."""
    profile = Mock()
    profile.digest_llm_enabled = True
    profile.digest_llm_batch_interval_min = 1  # 1 minute for testing
    return profile


def test_llm_queue_worker_init(mock_config: Mock) -> None:
    """__init__ stores config and sets up stop flag."""
    get_profile = Mock(return_value=Mock())
    worker = LLMQueueWorker(mock_config, get_profile=get_profile)

    assert worker._config == mock_config
    assert worker._get_profile == get_profile
    assert worker._thread is None
    assert not worker._stop.is_set()


def test_llm_queue_worker_start(mock_config: Mock) -> None:
    """start creates and starts a daemon thread."""
    get_profile = Mock(return_value=Mock(digest_llm_enabled=False))

    with patch("src.job_hunt_scheduler.reset_stale_llm_processing"):
        worker = LLMQueueWorker(mock_config, get_profile=get_profile)
        worker.start()

        assert worker._thread is not None
        assert worker._thread.daemon is True
        assert worker._thread.name == "LLMQueueWorker"
        # Stop immediately for cleanup
        worker.stop(timeout=0.5)


def test_llm_queue_worker_start_reset_stale_calls_reset(mock_config: Mock, monkeypatch) -> None:
    """start calls reset_stale_llm_processing on startup."""
    get_profile = Mock(return_value=Mock(digest_llm_enabled=False))
    reset_calls = []

    def fake_reset(*args, **kwargs):
        reset_calls.append((args, kwargs))

    monkeypatch.setattr(
        "src.job_hunt_scheduler.reset_stale_llm_processing",
        fake_reset,
    )

    worker = LLMQueueWorker(mock_config, get_profile=get_profile)
    worker.start()
    worker.stop(timeout=0.5)

    assert len(reset_calls) == 1
    assert "now" in reset_calls[0][1]
    assert "older_than_minutes" in reset_calls[0][1]


def test_llm_queue_worker_stop_sets_flag(mock_config: Mock) -> None:
    """stop sets the stop flag to signal thread exit."""
    get_profile = Mock(return_value=Mock(digest_llm_enabled=False))

    with patch("src.job_hunt_scheduler.reset_stale_llm_processing"):
        worker = LLMQueueWorker(mock_config, get_profile=get_profile)
        worker.start()

        assert not worker._stop.is_set()
        worker.stop(timeout=0.5)
        # After stop, the thread should be stopped
        assert worker._thread is not None


def test_has_key_with_google_api_key(mock_config: Mock, monkeypatch) -> None:
    """_has_key returns True when GOOGLE_API_KEY is set."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test_key_123")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    get_profile = Mock()
    worker = LLMQueueWorker(mock_config, get_profile=get_profile)

    assert worker._has_key() is True


def test_has_key_with_gemini_api_key(mock_config: Mock, monkeypatch) -> None:
    """_has_key returns True when GEMINI_API_KEY is set."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test_key_456")

    get_profile = Mock()
    worker = LLMQueueWorker(mock_config, get_profile=get_profile)

    assert worker._has_key() is True


def test_has_key_with_both_keys(mock_config: Mock, monkeypatch) -> None:
    """_has_key returns True when either key is present."""
    monkeypatch.setenv("GOOGLE_API_KEY", "key1")
    monkeypatch.setenv("GEMINI_API_KEY", "key2")

    get_profile = Mock()
    worker = LLMQueueWorker(mock_config, get_profile=get_profile)

    assert worker._has_key() is True


def test_has_key_with_no_keys(mock_config: Mock, monkeypatch) -> None:
    """_has_key returns False when neither key is set."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    get_profile = Mock()
    worker = LLMQueueWorker(mock_config, get_profile=get_profile)

    assert worker._has_key() is False


def test_loop_exits_on_stop_flag(mock_config: Mock, monkeypatch) -> None:
    """_loop terminates when _stop is set."""
    get_profile = Mock(return_value=Mock(digest_llm_enabled=False))
    drain_calls = []

    def fake_drain(*args, **kwargs):
        drain_calls.append(True)

    monkeypatch.setattr(
        "src.job_hunt_scheduler.drain_llm_batch",
        fake_drain,
    )
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    worker = LLMQueueWorker(mock_config, get_profile=get_profile)
    # Set stop flag immediately to skip the main loop
    worker._stop.set()
    worker._loop()

    # Should exit without calling drain
    assert len(drain_calls) == 0


def test_loop_skips_drain_when_disabled(mock_config: Mock, monkeypatch) -> None:
    """_loop doesn't call drain when digest_llm_enabled is False."""
    profile = Mock(digest_llm_enabled=False, digest_llm_batch_interval_min=15)
    get_profile = Mock(return_value=profile)
    drain_calls = []

    def fake_drain(*args, **kwargs):
        drain_calls.append(True)

    def fake_wait(timeout):
        # Set stop after first iteration
        worker._stop.set()

    monkeypatch.setattr(
        "src.job_hunt_scheduler.drain_llm_batch",
        fake_drain,
    )
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    worker = LLMQueueWorker(mock_config, get_profile=get_profile)
    worker._stop.wait = fake_wait

    worker._loop()

    # drain_llm_batch should not be called since digest_llm_enabled=False
    assert len(drain_calls) == 0


def test_loop_skips_drain_when_no_key(mock_config: Mock, monkeypatch) -> None:
    """_loop doesn't call drain when no API key is set."""
    profile = Mock(digest_llm_enabled=True, digest_llm_batch_interval_min=15)
    get_profile = Mock(return_value=profile)
    drain_calls = []

    def fake_drain(*args, **kwargs):
        drain_calls.append(True)

    def fake_wait(timeout):
        # Set stop after first iteration
        worker._stop.set()

    monkeypatch.setattr(
        "src.job_hunt_scheduler.drain_llm_batch",
        fake_drain,
    )
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    worker = LLMQueueWorker(mock_config, get_profile=get_profile)
    worker._stop.wait = fake_wait

    worker._loop()

    # drain_llm_batch should not be called since no key is present
    assert len(drain_calls) == 0


def test_loop_calls_drain_when_enabled_and_keyed(mock_config: Mock, monkeypatch) -> None:
    """_loop calls drain_llm_batch when enabled and API key is present."""
    profile = Mock(digest_llm_enabled=True, digest_llm_batch_interval_min=15)
    get_profile = Mock(return_value=profile)
    drain_calls = []

    def fake_drain(*args, **kwargs):
        drain_calls.append(kwargs)

    def fake_wait(timeout):
        # Set stop after first iteration
        worker._stop.set()

    monkeypatch.setattr(
        "src.job_hunt_scheduler.drain_llm_batch",
        fake_drain,
    )
    monkeypatch.setenv("GOOGLE_API_KEY", "test_key")

    worker = LLMQueueWorker(mock_config, get_profile=get_profile)
    worker._stop.wait = fake_wait

    worker._loop()

    # drain_llm_batch should be called with config, profile, db_path
    assert len(drain_calls) == 1
    assert "config" in drain_calls[0]
    assert "profile" in drain_calls[0]
    assert "db_path" in drain_calls[0]
    assert drain_calls[0]["config"] == mock_config
    assert drain_calls[0]["profile"] == profile


def test_loop_handles_exception_in_get_profile(mock_config: Mock, monkeypatch) -> None:
    """_loop catches exceptions from get_profile and continues."""
    error_count = [0]

    def failing_profile():
        error_count[0] += 1
        if error_count[0] <= 1:
            raise RuntimeError("profile fetch failed")
        return Mock(digest_llm_enabled=False)

    get_profile = Mock(side_effect=failing_profile)

    def fake_wait(timeout):
        if error_count[0] >= 2:
            worker._stop.set()

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    worker = LLMQueueWorker(mock_config, get_profile=get_profile)
    worker._stop.wait = fake_wait

    # Should not raise, but catch and log the exception
    worker._loop()

    # Should have tried twice (first fails, second succeeds and stops)
    assert error_count[0] >= 1


def test_loop_handles_exception_in_drain(mock_config: Mock, monkeypatch) -> None:
    """_loop catches exceptions from drain_llm_batch and continues."""
    profile = Mock(digest_llm_enabled=True, digest_llm_batch_interval_min=15)
    get_profile = Mock(return_value=profile)

    fake_drain = Mock(side_effect=RuntimeError("drain failed"))

    def fake_wait(timeout):
        # Stop after first iteration
        worker._stop.set()

    monkeypatch.setattr(
        "src.job_hunt_scheduler.drain_llm_batch",
        fake_drain,
    )
    monkeypatch.setenv("GOOGLE_API_KEY", "test_key")

    worker = LLMQueueWorker(mock_config, get_profile=get_profile)
    worker._stop.wait = fake_wait

    worker._loop()

    fake_drain.assert_called_once_with(config=mock_config, profile=profile, db_path=worker._db_path)
    get_profile.assert_called_once()
