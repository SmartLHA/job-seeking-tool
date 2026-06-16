"""
Outcomes store — thread-safe JSON persistence for job applications.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

VIEWER_DIR = Path(__file__).parent.parent.resolve() / "viewer"
DATA_FILE = VIEWER_DIR / "data" / "jobs.json"

# Thread-safe lock for write operations
_LOCK = threading.Lock()

DEFAULT_DATA = {
    "jobs": [],
    "version": 1,
    "updated_at": None,
}


def _load_data() -> dict:
    """Load jobs from JSON file, return default if missing or corrupt."""
    if not DATA_FILE.exists():
        return dict(DEFAULT_DATA)
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_DATA)


def _save_data(data: dict) -> None:
    """Atomically save data: write to temp file, then rename."""
    data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tmp_path = DATA_FILE.with_suffix(".json.tmp")
    try:
        encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        with open(tmp_path, "wb") as fh:
            fh.write(encoded)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, DATA_FILE)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def get_all() -> list[dict]:
    """Return all jobs."""
    return _load_data().get("jobs", [])


def upsert(job: dict) -> dict:
    """Insert or replace a job. Returns the stored job with id."""
    with _LOCK:
        data = _load_data()
        jobs = data.get("jobs", [])

        # If job has existing id, replace it
        if "id" in job:
            for i, j in enumerate(jobs):
                if j.get("id") == job["id"]:
                    jobs[i] = job
                    _save_data(data)
                    return job

        # Otherwise append with generated id
        job_id = _gen_id()
        job["id"] = job_id
        jobs.append(job)
        _save_data(data)
        return job


def update_status(job_id: str, status: str, notes: str = "") -> dict | None:
    """Update a job's status and optionally notes. Returns updated job or None."""
    with _LOCK:
        data = _load_data()
        jobs = data.get("jobs", [])
        for i, job in enumerate(jobs):
            if job.get("id") == job_id:
                jobs[i]["status"] = status
                jobs[i]["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if notes is not None:
                    jobs[i]["notes"] = notes
                _save_data(data)
                return jobs[i]
        return None


def delete(job_id: str) -> bool:
    """Delete a job by id. Returns True if deleted."""
    with _LOCK:
        data = _load_data()
        jobs = data.get("jobs", [])
        original_len = len(jobs)
        jobs = [j for j in jobs if j.get("id") != job_id]
        if len(jobs) < original_len:
            _save_data(data)
            return True
        return False


def get_by_status(status: str) -> list[dict]:
    """Return jobs with the given status."""
    jobs = _load_data().get("jobs", [])
    return [j for j in jobs if j.get("status") == status]


def _gen_id() -> str:
    """Generate a unique job id."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y%m%d")
    existing = [j.get("id", "") for j in _load_data().get("jobs", [])]
    counter = 1
    while True:
        candidate = f"job_{date_str}_{counter:03d}"
        if candidate not in existing:
            return candidate
        counter += 1
        if counter > 9999:
            break
    # Fallback with timestamp
    import uuid
    return f"job_{date_str}_{uuid.uuid4().hex[:6]}"