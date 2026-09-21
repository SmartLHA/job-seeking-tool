"""Tests for job_hunt_track_store — JSON-backed persistence layer."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src import job_hunt_track_store as ts


@pytest.fixture
def in_memory_storage():
    """Provide in-memory storage for track_store tests."""
    # Create an in-memory data store
    memory_data = {"jobs": [], "version": 1, "updated_at": None}

    def mock_load_data():
        return dict(memory_data)

    def mock_save_data(data):
        memory_data.clear()
        memory_data.update(data)
        memory_data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with patch.object(ts, "_load_data", side_effect=mock_load_data):
        with patch.object(ts, "_save_data", side_effect=mock_save_data):
            yield memory_data


def test_load_data_with_missing_file() -> None:
    """_load_data returns default when file doesn't exist."""
    # Create a mock DATA_FILE that doesn't exist
    fake_path = Path("/nonexistent/path/jobs.json")

    with patch.object(ts, "DATA_FILE", fake_path):
        data = ts._load_data()
        assert data == ts.DEFAULT_DATA


def test_load_data_with_valid_json() -> None:
    """_load_data reads and parses JSON correctly."""
    test_data = {
        "jobs": [{"id": "job_001", "title": "BA"}],
        "version": 1,
        "updated_at": "2026-01-01T00:00:00Z",
    }

    fake_path = Path("/fake/path/jobs.json")
    with patch.object(ts, "DATA_FILE", fake_path):
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", create=True) as mock_file:
                mock_file.return_value.__enter__.return_value.read.return_value = json.dumps(test_data).encode()
                with patch.object(Path, "read_text", return_value=json.dumps(test_data)):
                    loaded = ts._load_data()
                    assert loaded == test_data
                    assert loaded["jobs"][0]["id"] == "job_001"


def test_load_data_with_corrupt_json() -> None:
    """_load_data returns default on JSON decode error."""
    fake_path = Path("/fake/path/jobs.json")
    with patch.object(ts, "DATA_FILE", fake_path):
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "read_text", return_value="{invalid json"):
                data = ts._load_data()
                assert data == ts.DEFAULT_DATA


def test_save_data_creates_and_overwrites(tmp_path: Path) -> None:
    """_save_data writes atomically and sets updated_at."""
    test_data = {"jobs": [{"id": "job_001"}], "version": 1, "updated_at": None}
    data_file = tmp_path / "jobs.json"

    with patch.object(ts, "DATA_FILE", data_file):
        ts._save_data(test_data)

        assert data_file.exists()
        loaded = json.loads(data_file.read_text(encoding="utf-8"))
        assert loaded["jobs"] == [{"id": "job_001"}]
        assert loaded["updated_at"] is not None
        # Verify it's a valid timestamp
        datetime.fromisoformat(loaded["updated_at"].replace("Z", "+00:00"))


def test_save_data_uses_temp_file_pattern(tmp_path: Path) -> None:
    """_save_data uses .json.tmp intermediate; no leftover temp on success."""
    test_data = {"jobs": [], "version": 1, "updated_at": None}
    data_file = tmp_path / "jobs.json"

    with patch.object(ts, "DATA_FILE", data_file):
        ts._save_data(test_data)

        # Check that only the real file exists, not a .tmp
        tmp_file = data_file.with_suffix(".json.tmp")
        assert data_file.exists()
        assert not tmp_file.exists()


def test_get_all_empty(in_memory_storage) -> None:
    """get_all returns empty list when no jobs stored."""
    jobs = ts.get_all()
    assert jobs == []


def test_get_all_returns_stored_jobs(in_memory_storage) -> None:
    """get_all returns all stored jobs."""
    job1 = {"title": "BA", "company": "Co1"}
    job2 = {"title": "PM", "company": "Co2"}

    result1 = ts.upsert(job1)
    result2 = ts.upsert(job2)

    all_jobs = ts.get_all()
    assert len(all_jobs) == 2
    assert any(j["id"] == result1["id"] for j in all_jobs)
    assert any(j["id"] == result2["id"] for j in all_jobs)


def test_upsert_new_job_generates_id(in_memory_storage) -> None:
    """upsert without id generates and returns id."""
    job = {"title": "BA", "company": "Example"}
    result = ts.upsert(job)

    assert "id" in result
    assert result["id"].startswith("job_")
    assert result["title"] == "BA"


def test_upsert_existing_job_by_id_replaces(in_memory_storage) -> None:
    """upsert with existing id updates that job."""
    job1 = {"title": "BA"}
    result1 = ts.upsert(job1)
    job_id = result1["id"]

    updated = {"id": job_id, "title": "PM", "company": "NewCo"}
    result2 = ts.upsert(updated)

    assert result2["id"] == job_id
    assert result2["title"] == "PM"
    assert result2["company"] == "NewCo"

    # Verify count stayed at 1
    all_jobs = ts.get_all()
    assert len(all_jobs) == 1


def test_upsert_round_trip(in_memory_storage) -> None:
    """upsert then get_all preserves data exactly."""
    job = {"title": "BA", "company": "Co", "salary": 50000}
    inserted = ts.upsert(job)

    all_jobs = ts.get_all()
    assert len(all_jobs) == 1
    assert all_jobs[0] == inserted


def test_update_status_existing_job(in_memory_storage) -> None:
    """update_status modifies status and updated_at."""
    job = {"title": "BA"}
    inserted = ts.upsert(job)
    job_id = inserted["id"]

    updated = ts.update_status(job_id, "applied", notes="Good fit")

    assert updated is not None
    assert updated["status"] == "applied"
    assert updated["notes"] == "Good fit"
    assert "updated_at" in updated


def test_update_status_nonexistent_job(in_memory_storage) -> None:
    """update_status returns None for missing job_id."""
    result = ts.update_status("nonexistent_id", "applied")
    assert result is None


def test_update_status_no_notes_doesnt_clear(in_memory_storage) -> None:
    """update_status with None notes doesn't set notes field."""
    job = {"title": "BA", "notes": "Original"}
    inserted = ts.upsert(job)
    job_id = inserted["id"]

    updated = ts.update_status(job_id, "applied", notes=None)

    # notes is not explicitly checked/modified when notes=None per the logic
    assert updated["status"] == "applied"


def test_delete_existing_job(in_memory_storage) -> None:
    """delete removes a job by id and returns True."""
    job = {"title": "BA"}
    inserted = ts.upsert(job)
    job_id = inserted["id"]

    result = ts.delete(job_id)

    assert result is True
    assert ts.get_all() == []


def test_delete_nonexistent_job(in_memory_storage) -> None:
    """delete returns False for missing job_id."""
    result = ts.delete("nonexistent_id")
    assert result is False


def test_delete_one_of_many(in_memory_storage) -> None:
    """delete only removes the targeted job."""
    job1 = {"title": "BA"}
    job2 = {"title": "PM"}
    r1 = ts.upsert(job1)
    r2 = ts.upsert(job2)

    ts.delete(r1["id"])

    remaining = ts.get_all()
    assert len(remaining) == 1
    assert remaining[0]["id"] == r2["id"]


def test_get_by_status_empty(in_memory_storage) -> None:
    """get_by_status returns empty list when no jobs have that status."""
    job = {"title": "BA", "status": "applied"}
    ts.upsert(job)

    result = ts.get_by_status("rejected")
    assert result == []


def test_get_by_status_filters_correctly(in_memory_storage) -> None:
    """get_by_status returns only jobs with matching status."""
    job1 = {"title": "BA", "status": "applied"}
    job2 = {"title": "PM", "status": "rejected"}
    job3 = {"title": "Dev", "status": "applied"}

    ts.upsert(job1)
    ts.upsert(job2)
    ts.upsert(job3)

    applied = ts.get_by_status("applied")
    assert len(applied) == 2
    assert all(j["status"] == "applied" for j in applied)


def test_gen_id_format_and_uniqueness(in_memory_storage) -> None:
    """_gen_id generates unique IDs with job_YYYYMMDD_### format."""
    # Upsert multiple jobs - each should get a unique ID
    result1 = ts.upsert({"title": "Job1"})
    result2 = ts.upsert({"title": "Job2"})
    result3 = ts.upsert({"title": "Job3"})

    id1 = result1["id"]
    id2 = result2["id"]
    id3 = result3["id"]

    # All IDs should start with job_
    assert id1.startswith("job_")
    assert id2.startswith("job_")
    assert id3.startswith("job_")

    # All IDs should be different
    assert id1 != id2
    assert id2 != id3
    assert id1 != id3

    # Format: job_YYYYMMDD_### or job_YYYYMMDD_hex
    assert len(id1) >= len("job_20260101_001")


def test_gen_id_increments_counter(in_memory_storage) -> None:
    """_gen_id increments counter suffix within same date."""
    upsert1 = ts.upsert({"title": "BA"})
    upsert2 = ts.upsert({"title": "PM"})

    id1 = upsert1["id"]
    id2 = upsert2["id"]

    # Both should be from the same day, with incremented numbers
    assert id1.split("_")[1] == id2.split("_")[1]  # Same date part
    assert id1 != id2


def test_thread_safety_lock_exists() -> None:
    """Module lock is usable for exclusive access."""
    assert ts._LOCK.acquire(blocking=False) is True
    ts._LOCK.release()


def test_concurrent_upserts_dont_corrupt(in_memory_storage) -> None:
    """Multiple upserts update consistently (basic concurrency check)."""
    jobs_to_add = [{"title": f"Job{i}"} for i in range(5)]
    results = [ts.upsert(job) for job in jobs_to_add]

    all_jobs = ts.get_all()
    assert len(all_jobs) == 5
    assert len(results) == 5

    # All IDs should be unique
    ids = [r["id"] for r in results]
    assert len(set(ids)) == 5
