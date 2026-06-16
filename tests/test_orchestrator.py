from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.job_hunt_orchestrator import run_local_evaluation_flow, run_reed_evaluation_flow


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


def _reed_job(
    *,
    job_id: int = 123,
    title: str = "Remote Business Analyst",
    location: str = "Remote",
    description: str = "Business Analyst role with stakeholder management and process mapping.",
) -> dict[str, object]:
    return {
        "jobId": job_id,
        "jobTitle": title,
        "locationName": location,
        "employerName": "Reed Co",
        "contractType": "Permanent",
        "fullTime": True,
        "partTime": False,
        "minimumSalary": 55000,
        "maximumSalary": 65000,
        "jobDescription": description,
        "jobUrl": f"https://www.reed.co.uk/jobs/{job_id}",
        "datePosted": "2026-05-01",
    }


def test_run_reed_evaluation_flow_fetches_dedupes_evaluates_stores_and_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.job_hunt_orchestrator.fetch_reed_jobs",
        lambda keyword, location, max_results: [
            _reed_job(job_id=123, description="Short BA description."),
            _reed_job(
                job_id=123,
                description=(
                    "Longer Business Analyst description with stakeholder management, "
                    "process mapping, SQL, Agile delivery and reporting ownership."
                ),
            ),
        ],
    )

    result = run_reed_evaluation_flow(
        profile_path=_write_profile(tmp_path),
        keyword=" Business Analyst ",
        location=" London ",
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
        max_results=25,
    )

    assert result.fetched_count == 2
    assert result.normalized_count == 2
    assert result.deduped_count == 1
    assert len(result.evaluated_jobs) == 1

    evaluated = result.evaluated_jobs[0]
    assert evaluated.reviewed_job.job_id == "reed-123"
    assert evaluated.reviewed_job.source_type == "reed_api"
    assert evaluated.reviewed_job.source_ref == "https://www.reed.co.uk/jobs/123"
    assert evaluated.reviewed_job.work_mode == "remote"
    assert evaluated.reviewed_job.employment_type == "full-time, permanent"
    assert evaluated.reviewed_job.required_skills == []
    assert evaluated.reviewed_job.preferred_skills == []
    assert evaluated.reviewed_job_path == tmp_path / "state" / "reviewed_jobs" / "reed-123.json"
    assert evaluated.analysis_path == tmp_path / "state" / "analyses" / "reed-123.json"
    assert evaluated.raw_input_path == tmp_path / "state" / "raw_inputs" / "reed-123.json"
    assert evaluated.report_json_path == tmp_path / "reports" / "reed-123.json"
    assert evaluated.report_csv_path == tmp_path / "reports" / "reed-123.csv"

    raw_payload = json.loads(evaluated.raw_input_path.read_text(encoding="utf-8"))
    assert raw_payload["source_type"] == "reed_api"
    assert raw_payload["raw_job"]["jobId"] == 123
    assert raw_payload["normalized_job"]["external_id"] == "123"

    report_payload = json.loads(evaluated.report_json_path.read_text(encoding="utf-8"))
    assert report_payload["summary"]["total_jobs"] == 1
    assert report_payload["rows"][0]["job_id"] == "reed-123"


def test_run_reed_evaluation_flow_returns_zero_job_result_for_empty_reed_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.job_hunt_orchestrator.fetch_reed_jobs", lambda *args, **kwargs: [])

    result = run_reed_evaluation_flow(
        profile_path=_write_profile(tmp_path),
        keyword="Business Analyst",
        location="London",
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
    )

    assert result.fetched_count == 0
    assert result.normalized_count == 0
    assert result.deduped_count == 0
    assert result.evaluated_jobs == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"keyword": "", "location": "London", "max_results": 10}, "keyword"),
        ({"keyword": "BA", "location": "   ", "max_results": 10}, "location"),
        ({"keyword": "BA", "location": "London", "max_results": 0}, "max_results"),
    ],
)
def test_run_reed_evaluation_flow_validates_inputs_before_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, object],
    message: str,
) -> None:
    def fail_fetch(*args: object, **kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("fetch_reed_jobs should not be called for invalid input")

    monkeypatch.setattr("src.job_hunt_orchestrator.fetch_reed_jobs", fail_fetch)

    with pytest.raises(ValueError, match=message):
        run_reed_evaluation_flow(
            profile_path=_write_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
            **kwargs,
        )


def test_run_reed_evaluation_flow_maps_remote_type_to_work_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.job_hunt_orchestrator.fetch_reed_jobs",
        lambda *args, **kwargs: [_reed_job(job_id=456, title="Hybrid Business Analyst", location="Hybrid Office")],
    )

    result = run_reed_evaluation_flow(
        profile_path=_write_profile(tmp_path),
        keyword="Business Analyst",
        location="London",
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
    )

    assert result.evaluated_jobs[0].reviewed_job.work_mode == "hybrid"


def test_run_reed_evaluation_flow_does_not_require_adzuna_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_adzuna(*args: object, **kwargs: object) -> None:
        raise AssertionError("Reed flow must not call Adzuna normalization")

    monkeypatch.setattr("src.job_sources.normalize.normalize_adzuna", fail_adzuna)
    monkeypatch.setattr(
        "src.job_hunt_orchestrator.fetch_reed_jobs",
        lambda *args, **kwargs: [_reed_job(job_id=789)],
    )

    result = run_reed_evaluation_flow(
        profile_path=_write_profile(tmp_path),
        keyword="Business Analyst",
        location="London",
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
    )

    assert [job.reviewed_job.job_id for job in result.evaluated_jobs] == ["reed-789"]
