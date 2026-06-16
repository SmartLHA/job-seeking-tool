"""
Outcomes data layer — high-level API for job application tracking.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

VIEWER_DIR = Path(__file__).parent.resolve()
if str(VIEWER_DIR) not in sys.path:
    sys.path.insert(0, str(VIEWER_DIR))

from datetime import datetime, timezone, timedelta
from typing import Optional

import outcomes_store

VALID_STATUSES = ["not_applied", "applied", "interviewed", "rejected", "ignored"]


def load_jobs() -> list[dict]:
    """Load all jobs from jobs.json."""
    return outcomes_store.get_all()


def save_jobs(jobs: list[dict]) -> None:
    """Save jobs to jobs.json."""
    with outcomes_store._LOCK:
        data = {"jobs": jobs, "version": 1, "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        outcomes_store._save_data(data)


def add_job(job_data: dict) -> str:
    """Add a new job, generate ID, return job_id."""
    job_data.setdefault("status", "not_applied")
    job_data.setdefault("applied_at", None)
    job_data.setdefault("notes", "")
    job_data.setdefault("stage", job_data["status"])
    stored = outcomes_store.upsert(job_data)
    return stored["id"]


def update_job_status(job_id: str, status: str, notes: str = "") -> dict | None:
    """Update job status (not_applied/applied/interviewed/rejected/ignored)."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")
    job = outcomes_store.update_status(job_id, status, notes)
    if job and status == "applied" and not job.get("applied_at"):
        job["applied_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        outcomes_store.upsert(job)
    return job


def get_jobs_by_status(status: str) -> list[dict]:
    """Return jobs with the given status."""
    return outcomes_store.get_by_status(status)


def get_outcomes_summary() -> dict:
    """Return summary: total, applied, interview, rejected, ignored counts."""
    jobs = load_jobs()
    total = len(jobs)
    counts = {s: 0 for s in VALID_STATUSES}
    for j in jobs:
        s = j.get("status", "not_applied")
        if s in counts:
            counts[s] += 1
    applied = counts.get("applied", 0)
    interview = counts.get("interviewed", 0)
    rejected = counts.get("rejected", 0)
    ignored = counts.get("ignored", 0)
    not_applied = counts.get("not_applied", 0)
    rejection_rate = round(rejected / total * 100, 1) if total > 0 else 0.0
    return {
        "total": total,
        "applied": applied,
        "interviewed": interview,
        "rejected": rejected,
        "ignored": ignored,
        "not_applied": not_applied,
        "rejection_rate": rejection_rate,
    }


def get_applications_over_time(period: str = "30d") -> list[dict]:
    """Return application history for chart (last N days)."""
    jobs = load_jobs()
    days = 30
    if period.endswith("d"):
        try:
            days = int(period[:-1])
        except ValueError:
            days = 30

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    # Count applied per day
    daily = {}
    for d in range(days + 1):
        date_str = (start + timedelta(days=d)).strftime("%Y-%m-%d")
        daily[date_str] = {"date": date_str, "applied": 0, "interviewed": 0, "rejected": 0}

    for job in jobs:
        if job.get("applied_at"):
            try:
                dt = datetime.fromisoformat(job["applied_at"].replace("Z", "+00:00"))
                if dt >= start and dt <= now:
                    date_str = dt.strftime("%Y-%m-%d")
                    if date_str in daily:
                        daily[date_str]["applied"] += 1
            except Exception:
                pass
        if job.get("status") == "interviewed":
            # Count interviews too (use updated_at)
            pass
        if job.get("rejected_at"):
            try:
                dt = datetime.fromisoformat(job["rejected_at"].replace("Z", "+00:00"))
                if dt >= start and dt <= now:
                    date_str = dt.strftime("%Y-%m-%d")
                    if date_str in daily:
                        daily[date_str]["rejected"] += 1
            except Exception:
                pass

    return [daily[k] for k in sorted(daily.keys())]


def get_recent_activity(limit: int = 10) -> list[dict]:
    """Return recent status changes."""
    jobs = load_jobs()
    activity = []
    for job in jobs:
        if job.get("updated_at"):
            activity.append({
                "job_id": job.get("id"),
                "job_title": job.get("job_title", "Unknown"),
                "company": job.get("company", "Unknown"),
                "status": job.get("status", "not_applied"),
                "updated_at": job.get("updated_at"),
                "notes": job.get("notes", ""),
            })
    activity.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return activity[:limit]