from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from http.server import ThreadingHTTPServer

from src.storage import (
    load_application_outcome,
    load_job_analysis,
    load_raw_input,
    load_reviewed_job,
    save_application_outcome,
)
from src.ui import (
    UIServerConfig,
    _build_handler,
    default_form_values,
    format_salary_range,
    job_id_from_request_path,
    load_recent_job_history,
    raw_input_payload_from_form,
    reviewed_job_payload_from_form,
    split_lines_or_commas,
)
from src.orchestrator import run_local_evaluation_flow_from_payload
from src.outcomes import create_outcome_record, update_outcome


def _write_profile(tmp_path: Path) -> Path:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "docs").mkdir(parents=True, exist_ok=True)
    (profile_dir / "docs" / "master_cv.md").write_text("# Master CV\n", encoding="utf-8")
    profile_path = profile_dir / "candidate_profile.json"
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


def test_reviewed_job_payload_from_form_parses_lists_and_optional_numbers() -> None:
    form = {
        **default_form_values(),
        "job_id": "job-001",
        "job_title": "Business Analyst",
        "company": "Example Co",
        "description_raw": "Reviewed job description",
        "source_type": "copied_text",
        "required_skills": "SQL, Stakeholder Management\nProcess Mapping",
        "preferred_skills": "Power BI\n Tableau ",
        "required_years_experience": "3",
        "salary_min_gbp": "50000",
    }

    payload = reviewed_job_payload_from_form(form)

    assert payload["required_skills"] == ["SQL", "Stakeholder Management", "Process Mapping"]
    assert payload["preferred_skills"] == ["Power BI", "Tableau"]
    assert payload["required_years_experience"] == 3.0
    assert payload["salary_min_gbp"] == 50000
    assert payload["location"] is None


def test_raw_input_payload_from_form_keeps_original_input_context() -> None:
    form = {
        **default_form_values(),
        "input_method": "url",
        "job_url": "https://example.com/jobs/1",
        "copied_text": "Original copied text",
    }
    reviewed_job_payload = {
        "job_id": "job-001",
        "description_raw": "Reviewed description",
        "source_type": "url",
        "source_ref": "https://example.com/jobs/1",
    }

    payload = raw_input_payload_from_form(form, reviewed_job_payload)

    assert payload["input_method"] == "url"
    assert payload["job_url"] == "https://example.com/jobs/1"
    assert payload["copied_text"] == "Original copied text"
    assert payload["description_raw"] == "Reviewed description"


def test_job_id_from_request_path_supports_query_and_detail_routes() -> None:
    assert job_id_from_request_path("/job?job_id=demo-job-004") == "demo-job-004"
    assert job_id_from_request_path("/job/demo-job-004") == "demo-job-004"
    assert job_id_from_request_path("/job/demo-job-004/") == "demo-job-004"
    assert job_id_from_request_path("/job/") is None
    assert job_id_from_request_path("/other") is None


def test_load_recent_job_history_includes_saved_outcomes(tmp_path: Path) -> None:
    profile_path = _write_profile(tmp_path)
    result = run_local_evaluation_flow_from_payload(
        profile_path=profile_path,
        reviewed_job_payload={
            "job_id": "job-001",
            "job_title": "Business Analyst",
            "company": "Example Co",
            "description_raw": "Looking for stakeholder management and SQL.",
            "source_type": "copied_text",
            "source_ref": "manual-note-001",
            "location": "London",
            "work_mode": "hybrid",
            "employment_type": "full-time",
            "required_skills": ["Stakeholder Management", "SQL"],
            "preferred_skills": ["Power BI"],
            "required_years_experience": 3,
            "domain": "finance",
            "salary_min_gbp": 50000,
            "salary_max_gbp": 55000,
        },
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
        raw_input_payload={"copied_text": "original text"},
    )

    outcome = create_outcome_record(result.reviewed_job.job_id)
    outcome = update_outcome(outcome, status="applied", notes="Submitted manually")
    save_application_outcome(outcome, tmp_path / "state")

    history = load_recent_job_history(tmp_path / "state")

    assert history[0]["job_id"] == "job-001"
    assert history[0]["decision"] == "apply"
    assert history[0]["outcome_status"] == "applied"


def test_split_lines_or_commas_ignores_blank_entries() -> None:
    assert split_lines_or_commas("SQL,\n, Tableau \n Power BI") == ["SQL", "Tableau", "Power BI"]


def test_format_salary_range_handles_known_and_unknown_values() -> None:
    assert format_salary_range(50000, 60000) == "£50,000 – £60,000"
    assert format_salary_range(50000, None) == "From £50,000"
    assert format_salary_range(None, 60000) == "Up to £60,000"
    assert format_salary_range(None, None) == "Unknown"


@contextmanager
def _running_ui_server(tmp_path: Path):
    profile_path = _write_profile(tmp_path)
    config = UIServerConfig(
        profile_path=profile_path,
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
        host="127.0.0.1",
        port=0,
    )
    server = ThreadingHTTPServer((config.host, config.port), _build_handler(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", config
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _http_get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _http_post(url: str, form: dict[str, str]) -> tuple[int, str]:
    data = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _valid_evaluate_form(*, job_id: str = "job-ui-001") -> dict[str, str]:
    return {
        **default_form_values(),
        "job_id": job_id,
        "job_title": "Business Analyst",
        "company": "Example Co",
        "description_raw": "Looking for stakeholder management and SQL.",
        "source_type": "copied_text",
        "source_ref": "manual-note-001",
        "input_method": "copied_text",
        "copied_text": "Original copied text",
        "location": "London",
        "work_mode": "hybrid",
        "employment_type": "full-time",
        "required_skills": "Stakeholder Management, SQL",
        "preferred_skills": "Power BI",
        "required_years_experience": "3",
        "domain": "finance",
        "salary_min_gbp": "50000",
        "salary_max_gbp": "55000",
        "notes": "Reviewed and approved",
    }


def test_get_home_page_returns_form_and_history_panel(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/")

    assert status == 200
    assert "Job Seeking Tool — minimal local UI" in body
    assert "Enter and review one job" in body
    assert "Input method</strong> means how you brought the job in here first." in body
    assert "Original pasted/context text</strong> is saved as reference only." in body
    assert "Input method used to enter this job" in body
    assert "Saved source type for this reviewed job" in body
    assert "Original pasted/context text (reference only)" in body
    assert "Recent evaluated jobs" in body


def test_post_evaluate_success_renders_saved_job_result(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        status, body = _http_post(f"{base_url}/evaluate", _valid_evaluate_form())

        assert status == 200
        assert "Job evaluated and saved locally." in body
        assert 'class="panel flash success"' in body
        assert "Business Analyst @ Example Co" in body
        assert "Explainable result" in body
        assert "Reviewed job fields" in body
        assert "Saved source type" in body
        assert "Source reference" in body
        assert "Salary range" in body
        assert "£50,000 – £55,000" in body
        assert "Last updated: <strong>Not tracked yet</strong>" in body

        history = load_recent_job_history(config.state_root)
        assert history[0]["job_id"] == "job-ui-001"
        assert history[0]["decision"] == "apply"


def test_post_evaluate_validation_failure_re_renders_home_with_error(tmp_path: Path) -> None:
    invalid_form = _valid_evaluate_form()
    invalid_form["job_title"] = ""

    with _running_ui_server(tmp_path) as (base_url, config):
        status, body = _http_post(f"{base_url}/evaluate", invalid_form)

        assert status == 200
        assert "job_title is required" in body
        assert "Enter and review one job" in body
        assert load_recent_job_history(config.state_root) == []


def test_get_job_routes_support_query_and_path_variants(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        _http_post(f"{base_url}/evaluate", _valid_evaluate_form(job_id="job-ui-002"))

        query_status, query_body = _http_get(f"{base_url}/job?job_id=job-ui-002")
        path_status, path_body = _http_get(f"{base_url}/job/job-ui-002")
        slash_status, slash_body = _http_get(f"{base_url}/job/job-ui-002/")

    assert query_status == 200
    assert path_status == 200
    assert slash_status == 200
    assert "Business Analyst @ Example Co" in query_body
    assert "Business Analyst @ Example Co" in path_body
    assert "Business Analyst @ Example Co" in slash_body



def test_request_level_404s_cover_unknown_routes_and_unknown_job_ids(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        missing_route_status, missing_route_body = _http_get(f"{base_url}/does-not-exist")
        missing_query_job_status, missing_query_job_body = _http_get(
            f"{base_url}/job?job_id=missing-job"
        )
        missing_path_job_status, missing_path_job_body = _http_get(
            f"{base_url}/job/missing-job"
        )

    assert missing_route_status == 404
    assert "Page not found." in missing_route_body
    assert missing_query_job_status == 404
    assert missing_path_job_status == 404
    assert "No saved job was found for that id." in missing_query_job_body
    assert "No saved job was found for that id." in missing_path_job_body



def test_post_evaluate_persists_raw_input_context_from_ui_submission(tmp_path: Path) -> None:
    form = _valid_evaluate_form(job_id="job-ui-raw-001")
    form["input_method"] = "url"
    form["source_type"] = "url"
    form["source_ref"] = "https://example.com/jobs/job-ui-raw-001"
    form["job_url"] = "https://example.com/jobs/job-ui-raw-001"
    form["copied_text"] = "Original pasted context from UI"
    form["description_raw"] = "Cleaned reviewed description used for scoring"

    with _running_ui_server(tmp_path) as (base_url, config):
        status, _body = _http_post(f"{base_url}/evaluate", form)
        saved_raw_input = load_raw_input("job-ui-raw-001", config.state_root)

    assert status == 200
    assert saved_raw_input == {
        "input_method": "url",
        "source_type": "url",
        "source_ref": "https://example.com/jobs/job-ui-raw-001",
        "job_url": "https://example.com/jobs/job-ui-raw-001",
        "copied_text": "Original pasted context from UI",
        "description_raw": "Cleaned reviewed description used for scoring",
    }



def test_post_evaluate_same_job_id_overwrites_saved_state_with_latest_submission(tmp_path: Path) -> None:
    first_form = _valid_evaluate_form(job_id="job-ui-repeat-001")
    second_form = _valid_evaluate_form(job_id="job-ui-repeat-001")
    second_form.update(
        {
            "job_title": "Senior Business Analyst",
            "company": "Updated Co",
            "description_raw": "Updated reviewed description with SQL, Power BI, and stakeholder management.",
            "copied_text": "Updated original copied text",
            "required_skills": "Stakeholder Management, SQL, Power BI",
            "preferred_skills": "Tableau",
            "notes": "Second submission should win",
            "salary_min_gbp": "65000",
            "salary_max_gbp": "70000",
        }
    )

    with _running_ui_server(tmp_path) as (base_url, config):
        first_status, _ = _http_post(f"{base_url}/evaluate", first_form)
        second_status, second_body = _http_post(f"{base_url}/evaluate", second_form)

        saved_job = load_reviewed_job("job-ui-repeat-001", config.state_root)
        saved_analysis = load_job_analysis("job-ui-repeat-001", config.state_root)
        saved_raw_input = load_raw_input("job-ui-repeat-001", config.state_root)
        history = load_recent_job_history(config.state_root)

    assert first_status == 200
    assert second_status == 200
    assert "Senior Business Analyst @ Updated Co" in second_body
    assert saved_job.job_title == "Senior Business Analyst"
    assert saved_job.company == "Updated Co"
    assert saved_job.required_skills == ["Stakeholder Management", "SQL", "Power BI"]
    assert saved_job.preferred_skills == ["Tableau"]
    assert saved_job.notes == "Second submission should win"
    assert saved_job.salary_min_gbp == 65000
    assert saved_job.salary_max_gbp == 70000
    assert saved_analysis.job_id == "job-ui-repeat-001"
    assert saved_raw_input["copied_text"] == "Updated original copied text"
    assert saved_raw_input["description_raw"] == (
        "Updated reviewed description with SQL, Power BI, and stakeholder management."
    )
    assert [item for item in history if item["job_id"] == "job-ui-repeat-001"] == [history[0]]
    assert history[0]["job_title"] == "Senior Business Analyst"
    assert history[0]["company"] == "Updated Co"


def test_post_outcome_updates_saved_job_status(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        _http_post(f"{base_url}/evaluate", _valid_evaluate_form(job_id="job-ui-003"))

        status, body = _http_post(
            f"{base_url}/outcome",
            {
                "job_id": "job-ui-003",
                "status": "applied",
                "notes": "Submitted manually",
            },
        )

        saved_outcome = load_application_outcome("job-ui-003", config.state_root)

    assert status == 200
    assert "Outcome updated." in body
    assert 'class="panel flash success"' in body
    assert "Current status: <strong>applied</strong>" in body
    assert f"Last updated: <strong>{saved_outcome.updated_at}</strong>" in body
    assert saved_outcome.status == "applied"
    assert saved_outcome.notes == "Submitted manually"


def test_post_outcome_invalid_transition_shows_error_feedback(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        _http_post(f"{base_url}/evaluate", _valid_evaluate_form(job_id="job-ui-004"))
        _http_post(
            f"{base_url}/outcome",
            {
                "job_id": "job-ui-004",
                "status": "applied",
                "notes": "Submitted manually",
            },
        )

        status, body = _http_post(
            f"{base_url}/outcome",
            {
                "job_id": "job-ui-004",
                "status": "not_applied",
                "notes": "Should fail",
            },
        )

    assert status == 200
    assert "Outcome update failed:" in body
    assert 'class="panel flash error"' in body
