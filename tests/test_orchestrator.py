from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.orchestrator import run_local_evaluation_flow


def _write_profile(tmp_path: Path, *, with_master_cv: bool = True) -> Path:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profile_dir / "candidate_profile.json"

    payload: dict[str, object] = {
        "candidate_id": "cand-001",
        "name": "Mic",
        "target_roles": ["Business Analyst", "Data Analyst"],
        "locations": ["London", "Manchester"],
        "remote_preference": "remote_friendly",
        "salary_floor_gbp": 50000,
        "right_to_work_uk": True,
        "skills": [
            "Stakeholder Management",
            "Process Mapping",
            "SQL",
            "Agile",
        ],
        "years_experience": 5,
        "industries": ["finance", "technology"],
        "achievements": ["Improved reporting workflow"],
        "certifications": ["BCS Foundation"],
    }

    if with_master_cv:
        cv_path = profile_dir / "docs" / "master_cv.md"
        cv_path.parent.mkdir(parents=True, exist_ok=True)
        cv_path.write_text("# Master CV\n\nBusiness analysis experience.", encoding="utf-8")
        payload["master_cv_ref"] = "docs/master_cv.md"

    profile_path.write_text(json.dumps(payload), encoding="utf-8")
    return profile_path


def _write_reviewed_job(tmp_path: Path, *, job_id: str = "job-001") -> Path:
    reviewed_job_path = tmp_path / "inputs" / f"{job_id}.json"
    reviewed_job_path.parent.mkdir(parents=True, exist_ok=True)
    reviewed_job_path.write_text(
        json.dumps(
            {
                "job_id": job_id,
                "job_title": "Business Analyst",
                "company": "Example Co",
                "description_raw": "Looking for a BA with stakeholder management and process mapping.",
                "source_type": "copied_text",
                "source_ref": "manual-note-001",
                "location": "London",
                "work_mode": "hybrid",
                "employment_type": "full-time",
                "required_skills": ["stakeholder management", "process mapping"],
                "preferred_skills": ["SQL", "Power BI"],
                "required_years_experience": 3,
                "nice_to_have_years_experience": None,
                "domain": "finance",
                "notes": "Reviewed and approved",
                "salary_min_gbp": 50000,
                "salary_max_gbp": 60000,
            }
        ),
        encoding="utf-8",
    )
    return reviewed_job_path


def _write_raw_input(tmp_path: Path) -> Path:
    raw_input_path = tmp_path / "inputs" / "raw.json"
    raw_input_path.parent.mkdir(parents=True, exist_ok=True)
    raw_input_path.write_text(
        json.dumps(
            {
                "source_type": "copied_text",
                "source_ref": "manual-note-001",
                "payload": "Raw copied job description",
            }
        ),
        encoding="utf-8",
    )
    return raw_input_path


def test_run_local_evaluation_flow_wires_profile_job_storage_and_reports(tmp_path: Path) -> None:
    result = run_local_evaluation_flow(
        profile_path=_write_profile(tmp_path),
        reviewed_job_path=_write_reviewed_job(tmp_path),
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
        raw_input_path=_write_raw_input(tmp_path),
    )

    assert result.analysis.decision == "apply"
    assert result.analysis.confidence == "high"
    assert result.reviewed_job_path == tmp_path / "state" / "reviewed_jobs" / "job-001.json"
    assert result.analysis_path == tmp_path / "state" / "analyses" / "job-001.json"
    assert result.raw_input_path == tmp_path / "state" / "raw_inputs" / "job-001.json"
    assert result.report_json_path == tmp_path / "reports" / "job-001.json"
    assert result.report_csv_path == tmp_path / "reports" / "job-001.csv"
    assert result.master_cv_path == (tmp_path / "profile" / "docs" / "master_cv.md").resolve()

    report_payload = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    assert report_payload["summary"]["decision_counts"] == {"apply": 1}
    assert report_payload["rows"][0]["job_id"] == "job-001"


def test_run_local_evaluation_flow_allows_profile_without_master_cv(tmp_path: Path) -> None:
    result = run_local_evaluation_flow(
        profile_path=_write_profile(tmp_path, with_master_cv=False),
        reviewed_job_path=_write_reviewed_job(tmp_path, job_id="job-no-cv"),
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
    )

    assert result.master_cv_path is None
    assert result.raw_input_path is None
    assert result.analysis.job_id == "job-no-cv"


def test_run_local_evaluation_flow_rejects_non_object_reviewed_job_json(tmp_path: Path) -> None:
    profile_path = _write_profile(tmp_path)
    bad_reviewed_job_path = tmp_path / "inputs" / "bad.json"
    bad_reviewed_job_path.parent.mkdir(parents=True, exist_ok=True)
    bad_reviewed_job_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        run_local_evaluation_flow(
            profile_path=profile_path,
            reviewed_job_path=bad_reviewed_job_path,
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
