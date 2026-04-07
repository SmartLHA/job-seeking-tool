from __future__ import annotations

import json
from pathlib import Path

from src.main import main


def _write_profile(tmp_path: Path) -> Path:
    profile_path = tmp_path / "profile" / "candidate_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "profile" / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "profile" / "docs" / "master_cv.md").write_text(
        "# Master CV\n\nBusiness analysis experience.", encoding="utf-8"
    )
    profile_path.write_text(
        json.dumps(
            {
                "candidate_id": "cand-001",
                "name": "Mic",
                "target_roles": ["Business Analyst"],
                "locations": ["London"],
                "remote_preference": "remote_friendly",
                "salary_floor_gbp": 50000,
                "right_to_work_uk": True,
                "skills": ["Stakeholder Management", "Process Mapping", "SQL"],
                "years_experience": 5,
                "industries": ["finance"],
                "achievements": ["Improved reporting workflow"],
                "certifications": ["BCS Foundation"],
                "master_cv_ref": "docs/master_cv.md",
            }
        ),
        encoding="utf-8",
    )
    return profile_path


def _write_reviewed_job(tmp_path: Path) -> Path:
    reviewed_job_path = tmp_path / "inputs" / "job.json"
    reviewed_job_path.parent.mkdir(parents=True, exist_ok=True)
    reviewed_job_path.write_text(
        json.dumps(
            {
                "job_id": "job-001",
                "job_title": "Business Analyst",
                "company": "Example Co",
                "description_raw": "Looking for a BA with stakeholder management and process mapping.",
                "source_type": "copied_text",
                "location": "London",
                "work_mode": "hybrid",
                "employment_type": "full-time",
                "required_skills": ["stakeholder management", "process mapping"],
                "preferred_skills": ["SQL"],
                "required_years_experience": 3,
                "domain": "finance",
                "salary_min_gbp": 50000,
                "salary_max_gbp": 60000,
            }
        ),
        encoding="utf-8",
    )
    return reviewed_job_path


def test_main_runs_local_flow_and_prints_summary(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "--profile",
            str(_write_profile(tmp_path)),
            "--reviewed-job",
            str(_write_reviewed_job(tmp_path)),
            "--state-root",
            str(tmp_path / "state"),
            "--report-dir",
            str(tmp_path / "reports"),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Local evaluation completed" in captured.out
    assert "Decision: apply" in captured.out
    assert (tmp_path / "state" / "reviewed_jobs" / "job-001.json").exists()
    assert (tmp_path / "reports" / "job-001.json").exists()


def test_main_returns_non_zero_for_invalid_reviewed_job_input(tmp_path: Path, capsys) -> None:
    bad_reviewed_job_path = tmp_path / "inputs" / "bad.json"
    bad_reviewed_job_path.parent.mkdir(parents=True, exist_ok=True)
    bad_reviewed_job_path.write_text("[]", encoding="utf-8")

    exit_code = main(
        [
            "--profile",
            str(_write_profile(tmp_path)),
            "--reviewed-job",
            str(bad_reviewed_job_path),
            "--state-root",
            str(tmp_path / "state"),
            "--report-dir",
            str(tmp_path / "reports"),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error:" in captured.err
    assert "JSON object" in captured.err
