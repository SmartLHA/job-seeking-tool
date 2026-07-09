from __future__ import annotations

import html
import json
import re
import sys
import threading
import types
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from http.server import ThreadingHTTPServer

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    requests_stub = types.ModuleType("requests")
    requests_stub.exceptions = types.SimpleNamespace(ConnectionError=Exception, Timeout=TimeoutError)
    requests_stub.post = lambda *args, **kwargs: None
    sys.modules["requests"] = requests_stub

from src.job_hunt_storage import (
    load_qualitative_assessment,
    load_application_outcome,
    load_job_analysis,
    load_raw_input,
    load_reviewed_job,
    save_application_outcome,
    save_qualitative_assessment,
)
from src.job_hunt_index import (
    claim_qualitative_assessment,
    finish_qualitative_assessment,
    get_qualitative_index_row,
    incr_rpd_counter,
)
from src.job_hunt_scheduler import rpd_date_key
from src.ui_state import UIServerConfig
from src.ui_routes import _build_handler
from src.ui_utils import (
    default_form_values,
    format_salary_range,
    job_id_from_request_path,
    reviewed_job_payload_from_form,
    split_lines_or_commas,
)
from src.ui_handlers import (
    handle_qualitative_assess,
    load_recent_job_history,
    raw_input_payload_from_form,
    render_job,
)
from src.job_hunt_orchestrator import run_local_evaluation_flow_from_payload
from src.job_hunt_outcomes import create_outcome_record, update_outcome


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


class _FakeResponder:
    def __init__(self) -> None:
        self.status = None
        self.body = ""
        self.redirect_location = None

    def send_html(self, body: str, *, status=None) -> None:
        self.status = status
        self.body = body

    def send_json(self, payload, *, status=None) -> None:
        self.status = status
        self.body = json.dumps(payload)

    def redirect(self, location: str) -> None:
        self.redirect_location = location


def _ui_config(tmp_path: Path) -> UIServerConfig:
    return UIServerConfig(
        profile_path=_write_profile(tmp_path),
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
        host="127.0.0.1",
        port=0,
    )


def _save_evaluated_job(tmp_path: Path, config: UIServerConfig, *, job_id: str) -> None:
    run_local_evaluation_flow_from_payload(
        profile_path=config.profile_path,
        reviewed_job_payload={
            "job_id": job_id,
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
        state_root=config.state_root,
        report_dir=config.report_dir,
        raw_input_payload={"copied_text": "original text"},
    )


def _qualitative_llm_payload() -> str:
    return json.dumps({
        "dimensions": {
            "seniority_fit": {
                "score": 4,
                "evidence": ["Looking for stakeholder management"],
                "reasoning": "The role has clear BA ownership signals.",
            },
            "culture_signals": {
                "score": 3,
                "evidence": ["Looking for stakeholder management and SQL"],
                "reasoning": "The JD has little explicit culture evidence.",
            },
            "red_flags": {
                "score": 5,
                "evidence": ["SQL"],
                "reasoning": "No material red flags are visible in the JD.",
            },
            "role_archetype_alignment": {
                "score": 5,
                "evidence": ["stakeholder management and SQL"],
                "reasoning": "The activities align with Business Analyst target roles.",
            },
        },
        "posting_quality": {"tier": "unknown_caution", "signals": ["Short JD text."]},
    })


def _low_culture_llm_payload() -> str:
    payload = json.loads(_qualitative_llm_payload())
    payload["dimensions"]["culture_signals"]["score"] = 2
    payload["dimensions"]["culture_signals"]["evidence_contradicts_requirements"] = True
    payload["dimensions"]["culture_signals"]["reasoning"] = "The culture evidence contradicts the role requirements."
    return json.dumps(payload)


def _low_culture_assessment() -> dict:
    payload = json.loads(_low_culture_llm_payload())
    payload.update({
        "job_id": "job-grade",
        "model": "gemini-test",
        "prompt_version": "qualitative-v1",
        "created_at": "2026-07-09T10:00:00+00:00",
    })
    return payload




def _first_reed_select_form(body: str) -> dict[str, str]:
    match = re.search(r'<form method="post" action="/select/reed"[^>]*>(.*?)</form>', body, re.S)
    assert match, "Reed select form not found"
    fields: dict[str, str] = {}
    for name, value in re.findall(r'name="([^"]+)" value="([^"]*)"', match.group(1)):
        fields[html.unescape(name)] = html.unescape(value)
    return fields




def _evaluate_form_from_body(body: str) -> dict[str, str]:
    match = re.search(r'<form method="post" action="/evaluate" id="job-form">(.*?)</form>', body, re.S)
    assert match, "Evaluate form not found"
    form_html = match.group(1)
    fields: dict[str, str] = {}
    for name, value in re.findall(r'name="([^"]+)" value="([^"]*)"', form_html):
        fields[html.unescape(name)] = html.unescape(value)
    for name, value in re.findall(r'<textarea name="([^"]+)"[^>]*>(.*?)</textarea>', form_html, re.S):
        fields[html.unescape(name)] = html.unescape(value)
    return fields

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


def test_post_qualitative_assess_uses_mocked_llm_and_renders_panel(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_reasoning(prompt: str, *, before_attempt=None):
        calls.append(prompt)
        if before_attempt:
            before_attempt("gemini-test")
        return _qualitative_llm_payload(), None, "gemini-test", False

    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", fake_reasoning)
    config = _ui_config(tmp_path)
    _save_evaluated_job(tmp_path, config, job_id="job-qual-001")
    req = types.SimpleNamespace(path="/job/job-qual-001/qualitative-assess", form={}, json_body=None)
    responder = _FakeResponder()

    handle_qualitative_assess(req, config, responder, "job-qual-001")
    stored = load_qualitative_assessment("job-qual-001", config.state_root)
    row = get_qualitative_index_row(config.state_root / "job_hunt_index.db", "job-qual-001")

    assert len(calls) == 1
    assert "raw CV" not in calls[0]
    assert "This sends the job description and a profile summary to the Gemini API." in responder.body
    assert "Seniority fit" in responder.body
    assert stored["model"] == "gemini-test"
    assert stored["posting_quality"]["tier"] == "unknown_caution"
    assert stored["base_grade"] == "A"
    assert stored["capped_grade"] == "A"
    assert row is not None
    assert row["grade"] == "A"


def test_qualitative_badge_shows_capped_base_and_warning(tmp_path: Path, monkeypatch) -> None:
    def fake_reasoning(prompt: str, *, before_attempt=None):
        if before_attempt:
            before_attempt("gemini-test")
        return _low_culture_llm_payload(), None, "gemini-test", False

    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", fake_reasoning)
    config = _ui_config(tmp_path)
    _save_evaluated_job(tmp_path, config, job_id="job-qual-capped")
    req = types.SimpleNamespace(path="/job/job-qual-capped/qualitative-assess", form={}, json_body=None)
    responder = _FakeResponder()

    handle_qualitative_assess(req, config, responder, "job-qual-capped")
    row = get_qualitative_index_row(config.state_root / "job_hunt_index.db", "job-qual-capped")

    assert row is not None
    assert row["grade"] == "C"
    assert "Base grade A -&gt; capped C: culture evidence contradicts requirements" in responder.body
    assert "High technical fit, unconfirmed/poor culture fit - verify before applying." in responder.body


def test_qualitative_badge_caps_blocker_skip_at_f_and_persists_final_grade(tmp_path: Path, monkeypatch) -> None:
    def fake_reasoning(prompt: str, *, before_attempt=None):
        if before_attempt:
            before_attempt("gemini-test")
        return _qualitative_llm_payload(), None, "gemini-test", False

    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", fake_reasoning)
    config = _ui_config(tmp_path)
    job_id = "job-qual-blocker-skip"
    _save_evaluated_job(tmp_path, config, job_id=job_id)
    analysis_path = config.state_root / "analyses" / f"{job_id}.json"
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    analysis["decision"] = "skip"
    analysis["decision_reason"] = "Skipped because blocker rules were triggered: Salary below floor"
    analysis["blockers"] = [
        {
            "code": "salary-below-floor",
            "label": "Salary below floor",
            "reason": "Salary is below the candidate floor.",
            "severity": "critical",
        }
    ]
    analysis_path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    req = types.SimpleNamespace(path=f"/job/{job_id}/qualitative-assess", form={}, json_body=None)
    responder = _FakeResponder()

    handle_qualitative_assess(req, config, responder, job_id)
    row = get_qualitative_index_row(config.state_root / "job_hunt_index.db", job_id)
    stored = load_qualitative_assessment(job_id, config.state_root)

    assert row is not None
    assert row["grade"] == "F"
    assert stored["base_grade"] == "A"
    assert stored["capped_grade"] == "F"
    assert "Base grade A -&gt; capped F: hard blocker" in responder.body
    assert "Salary below floor" in responder.body


def test_qualitative_grade_badge_shows_base_grade_without_assessment(tmp_path: Path) -> None:
    config = _ui_config(tmp_path)
    _write_apply_job_state(config.state_root, job_id="job-base-grade")
    req = types.SimpleNamespace(path="/job/job-base-grade", form={}, json_body=None)
    responder = _FakeResponder()

    render_job(req, config, responder, "job-base-grade")

    assert "Grade A" in responder.body
    assert "base grade" in responder.body
    assert "Base grade A -&gt; capped C" not in responder.body


def test_qualitative_grade_badge_respects_user_override_effective_decision(tmp_path: Path) -> None:
    config = _ui_config(tmp_path)
    job_id = "job-user-review-grade"
    _write_apply_job_state(config.state_root, job_id=job_id)
    analysis_path = config.state_root / "analyses" / f"{job_id}.json"
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    analysis["user_decision"] = "review"
    analysis["user_decision_note"] = "Manual review before applying."
    analysis_path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    req = types.SimpleNamespace(path=f"/job/{job_id}", form={}, json_body=None)
    responder = _FakeResponder()

    render_job(req, config, responder, job_id)

    assert "Base grade A -&gt; capped B: decision requires review" in responder.body


def test_qualitative_stale_grade_backfills_on_render(tmp_path: Path) -> None:
    config = _ui_config(tmp_path)
    _write_apply_job_state(config.state_root, job_id="job-grade-backfill")
    assessment = _low_culture_assessment()
    assessment["job_id"] = "job-grade-backfill"
    save_qualitative_assessment("job-grade-backfill", assessment, config.state_root)
    db_path = config.state_root / "job_hunt_index.db"
    claim_qualitative_assessment(db_path, "job-grade-backfill", now="2026-07-09T10:00:00")
    finish_qualitative_assessment(
        db_path,
        "job-grade-backfill",
        status="done",
        grade="A",
        legitimacy_tier="unknown_caution",
        culture_flag="caution",
    )
    req = types.SimpleNamespace(path="/job/job-grade-backfill", form={}, json_body=None)
    responder = _FakeResponder()

    render_job(req, config, responder, "job-grade-backfill")
    row = get_qualitative_index_row(db_path, "job-grade-backfill")
    stored = load_qualitative_assessment("job-grade-backfill", config.state_root)

    assert row is not None
    assert row["grade"] == "C"
    assert stored["base_grade"] == "A"
    assert stored["capped_grade"] == "C"
    assert stored["cap_reason"] == "culture evidence contradicts requirements"
    assert "Base grade A -&gt; capped C: culture evidence contradicts requirements" in responder.body


def test_qualitative_grade_warning_not_rendered_for_c_base_grade(tmp_path: Path) -> None:
    config = _ui_config(tmp_path)
    _write_review_job_state(config.state_root, job_id="job-grade-c")
    assessment = _low_culture_assessment()
    assessment["job_id"] = "job-grade-c"
    save_qualitative_assessment("job-grade-c", assessment, config.state_root)
    db_path = config.state_root / "job_hunt_index.db"
    claim_qualitative_assessment(db_path, "job-grade-c", now="2026-07-09T10:00:00")
    finish_qualitative_assessment(
        db_path,
        "job-grade-c",
        status="done",
        legitimacy_tier="unknown_caution",
        culture_flag="caution",
    )
    req = types.SimpleNamespace(path="/job/job-grade-c", form={}, json_body=None)
    responder = _FakeResponder()

    render_job(req, config, responder, "job-grade-c")

    assert "Grade C" in responder.body
    assert "High technical fit, unconfirmed/poor culture fit - verify before applying." not in responder.body


def test_post_qualitative_assess_daily_cap_skips_llm_and_marks_error(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_reasoning(prompt: str, *, before_attempt=None):
        calls.append(prompt)
        raise AssertionError("LLM should not be called after daily cap is exhausted")

    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", fake_reasoning)
    config = _ui_config(tmp_path)
    profile_payload = json.loads(config.profile_path.read_text(encoding="utf-8"))
    profile_payload["digest_llm_rpd"] = 1
    config.profile_path.write_text(json.dumps(profile_payload), encoding="utf-8")
    _save_evaluated_job(tmp_path, config, job_id="job-qual-cap")
    db_path = config.state_root / "job_hunt_index.db"
    incr_rpd_counter(db_path, rpd_date_key())
    req = types.SimpleNamespace(path="/job/job-qual-cap/qualitative-assess", form={}, json_body=None)
    responder = _FakeResponder()

    handle_qualitative_assess(req, config, responder, "job-qual-cap")
    row = get_qualitative_index_row(db_path, "job-qual-cap")

    assert calls == []
    assert row is not None
    assert row["status"] == "error"
    assert row["error_text"] == "daily LLM quota exhausted - try tomorrow"
    assert "daily LLM quota exhausted - try tomorrow" in responder.body


def test_post_qualitative_force_rejected_while_running(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_reasoning(prompt: str, *, before_attempt=None):
        calls.append(prompt)
        return _qualitative_llm_payload(), None, "gemini-test", False

    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", fake_reasoning)
    config = _ui_config(tmp_path)
    _save_evaluated_job(tmp_path, config, job_id="job-qual-running")
    from src.job_hunt_index import claim_qualitative_assessment
    claim_qualitative_assessment(
        config.state_root / "job_hunt_index.db",
        "job-qual-running",
        now="2026-07-08T10:00:00",
    )
    req = types.SimpleNamespace(path="/job/job-qual-running/qualitative-assess", form={"force": "1"}, json_body=None)
    responder = _FakeResponder()

    handle_qualitative_assess(req, config, responder, "job-qual-running")

    assert calls == []
    assert "Assessment is already in flight." in responder.body


def test_post_qualitative_force_versions_done_assessment(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_reasoning(prompt: str, *, before_attempt=None):
        calls.append(prompt)
        if before_attempt:
            before_attempt("gemini-test")
        return _qualitative_llm_payload(), None, "gemini-test", False

    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", fake_reasoning)
    config = _ui_config(tmp_path)
    _save_evaluated_job(tmp_path, config, job_id="job-qual-force")
    req = types.SimpleNamespace(path="/job/job-qual-force/qualitative-assess", form={}, json_body=None)
    first_responder = _FakeResponder()
    handle_qualitative_assess(req, config, first_responder, "job-qual-force")
    force_req = types.SimpleNamespace(path="/job/job-qual-force/qualitative-assess", form={"force": "1"}, json_body=None)
    second_responder = _FakeResponder()
    handle_qualitative_assess(force_req, config, second_responder, "job-qual-force")
    archives = list((config.state_root / "analyses" / "qualitative" / "archive").glob("job-qual-force__*.json"))

    assert len(calls) == 2
    assert archives
    assert "Qualitative assessment saved." in second_responder.body


def test_get_home_page_defaults_to_search_jobs_shell(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/")

    assert status == 200
    assert "Search Jobs" in body
    assert "Search across connected job boards" in body
    assert 'id="job-search-form"' in body
    assert 'name="keywords"' in body
    assert 'name="locationName"' in body
    assert 'name="minimumSalary"' in body
    assert 'name="workMode"' in body
    assert 'name="employmentType"' in body
    assert 'name="resultsToTake"' in body
    assert "Manual Fallback" in body
    assert "Evaluate" in body
    assert "History" in body
    assert "My Profile" in body
    assert 'id="tab-search" class="tab-content"' in body
    assert 'id="tab-evaluate" class="tab-content" hidden' in body



def test_get_reed_search_endpoint_renders_stubbed_results(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_fetch_reed_jobs(keyword: str, location: str, max_results: int, *, skip: int = 0, save_raw: bool = True):
        calls.append({
            "keyword": keyword,
            "location": location,
            "max_results": max_results,
            "save_raw": save_raw,
        })
        return [
            {
                "jobId": 123,
                "jobTitle": "Senior <Business> Analyst",
                "employerName": "Example & Co",
                "locationName": "Hybrid London",
                "minimumSalary": 60000,
                "maximumSalary": 70000,
                "contractType": "Permanent",
                "jobUrl": "https://reed.example/jobs/123?x=1&y=2",
                "jobDescription": "<p>Lead discovery & stakeholder mapping for teams.</p>",
                "fullTime": True,
            }
        ]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)

    query = urllib.parse.urlencode({
        "keywords": "  Business   Analyst  ",
        "locationName": "London",
        "minimumSalary": "60,000",
        "workMode": "hybrid",
        "employmentType": "permanent",
        "resultsToTake": "99",
    })
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed?{query}")

    assert status == 200
    assert calls == [{
        "keyword": "Business Analyst",
        "location": "London",
        "max_results": 50,
        "save_raw": False,
    }]
    assert "Reed results (1)" in body
    assert "Senior &lt;Business&gt; Analyst" in body
    assert "Example &amp; Co" in body
    assert "£60,000 – £70,000" in body
    assert "Lead discovery &amp; stakeholder mapping" in body
    assert "https://reed.example/jobs/123?x=1&amp;y=2" in body
    assert "Minimum salary is passed to Reed only as a best-effort" in body
    assert 'value="50"' in body




def test_post_select_reed_prefills_evaluate_form_without_evaluating(tmp_path: Path, monkeypatch) -> None:
    long_description = "Lead discovery & stakeholder mapping. " * 30

    def fake_fetch_reed_jobs(keyword: str, location: str, max_results: int, *, skip: int = 0, save_raw: bool = True):
        return [
            {
                "jobId": 123,
                "jobTitle": "Senior <Business> Analyst",
                "employerName": "Example & Co",
                "locationName": "Hybrid London",
                "minimumSalary": 60000,
                "maximumSalary": 70000,
                "contractType": "Permanent",
                "jobUrl": "https://reed.example/jobs/123?x=1&y=2",
                "jobDescription": long_description,
                "fullTime": True,
            }
        ]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)

    with _running_ui_server(tmp_path) as (base_url, config):
        search_status, search_body = _http_get(f"{base_url}/search/reed?keywords=BA&locationName=London")
        select_form = _first_reed_select_form(search_body)
        select_status, select_body = _http_post(f"{base_url}/select/reed", select_form)

        assert search_status == 200
        assert select_status == 200
        assert 'id="tab-evaluate" class="tab-content"' in select_body
        assert "This form was prefilled from a Reed search result. Review and edit the fields before clicking Evaluate." in select_body
        assert 'name="job_id" value="reed-123"' in select_body
        assert 'name="input_method" value="reed_search"' in select_body
        assert 'name="source_type" value="reed"' in select_body
        assert 'name="source_ref" value="https://reed.example/jobs/123?x=1&amp;y=2"' in select_body
        assert 'name="source_snapshot_json"' in select_body
        assert 'name="job_title" value="Senior &lt;Business&gt; Analyst"' in select_body
        assert 'name="company" value="Example &amp; Co"' in select_body
        assert 'name="location" value="Hybrid London"' in select_body
        assert 'name="work_mode" value="hybrid"' in select_body
        assert 'name="employment_type" value="permanent"' in select_body
        assert 'name="salary_min_gbp" value="60000"' in select_body
        assert 'name="salary_max_gbp" value="70000"' in select_body
        assert "Lead discovery &amp; stakeholder mapping." in select_body
        assert "Evaluate and save" in select_body
        assert load_recent_job_history(config.state_root) == []
        assert not (config.state_root / "analyses" / "reed-123.json").exists()
        assert not (config.state_root / "reviewed_jobs" / "reed-123.json").exists()
        assert not (config.state_root / "raw_inputs" / "reed-123.json").exists()


def test_evaluate_after_reed_selection_persists_raw_source_snapshot_only_in_raw_input(tmp_path: Path, monkeypatch) -> None:
    def fake_fetch_reed_jobs(keyword: str, location: str, max_results: int, *, skip: int = 0, save_raw: bool = True):
        return [
            {
                "jobId": 456,
                "jobTitle": "Product Business Analyst",
                "employerName": "Audit Co",
                "locationName": "London",
                "minimumSalary": 61000,
                "maximumSalary": 72000,
                "contractType": "Permanent",
                "jobUrl": "https://reed.example/jobs/456",
                "jobDescription": "Original Reed source description with stakeholder management and SQL.",
                "fullTime": True,
            }
        ]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)

    with _running_ui_server(tmp_path) as (base_url, config):
        _search_status, search_body = _http_get(f"{base_url}/search/reed?keywords=BA&locationName=London")
        select_form = _first_reed_select_form(search_body)
        select_status, select_body = _http_post(f"{base_url}/select/reed", select_form)
        evaluate_form = _evaluate_form_from_body(select_body)
        evaluate_form["description_raw"] = "Reviewed description used for scoring with SQL and stakeholder management."
        evaluate_status, _evaluate_body = _http_post(f"{base_url}/evaluate", evaluate_form)

        saved_raw_input = load_raw_input("reed-456", config.state_root)
        saved_reviewed_path = config.state_root / "reviewed_jobs" / "reed-456.json"
        saved_analysis_path = config.state_root / "analyses" / "reed-456.json"
        saved_reviewed_payload = json.loads(saved_reviewed_path.read_text(encoding="utf-8"))
        saved_analysis_payload = json.loads(saved_analysis_path.read_text(encoding="utf-8"))

    assert select_status == 200
    assert evaluate_status == 200
    assert saved_raw_input["input_method"] == "reed_search"
    assert saved_raw_input["source_type"] == "reed"
    assert saved_raw_input["description_raw"] == "Reviewed description used for scoring with SQL and stakeholder management."
    assert saved_raw_input["source_snapshot"]["source"] == "reed"
    assert saved_raw_input["source_snapshot"]["source_job_id"] == "456"
    assert saved_raw_input["source_snapshot"]["capture_stage"] == "select"
    assert saved_raw_input["source_snapshot"]["snapshot_version"] == "pl-04-v1"
    assert saved_raw_input["source_snapshot"]["description_raw"] == "Original Reed source description with stakeholder management and SQL."
    assert isinstance(saved_raw_input["source_snapshot"]["captured_at"], str)
    assert "source_snapshot" not in saved_reviewed_payload
    assert "source_snapshot" not in saved_analysis_payload


def test_post_select_reed_rejects_malformed_source_snapshot_json(tmp_path: Path, monkeypatch) -> None:
    def fake_fetch_reed_jobs(keyword: str, location: str, max_results: int, *, skip: int = 0, save_raw: bool = True):
        return [{"jobId": 789, "jobTitle": "BA", "employerName": "Bad JSON Co", "jobDescription": "Description"}]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)

    with _running_ui_server(tmp_path) as (base_url, _config):
        _search_status, search_body = _http_get(f"{base_url}/search/reed?keywords=BA")
        select_form = _first_reed_select_form(search_body)
        select_form["source_snapshot_json"] = "{not-json"
        status, body = _http_post(f"{base_url}/select/reed", select_form)

    assert status == 400
    assert "source_snapshot_json must be valid JSON" in body


def test_post_evaluate_rejects_oversized_reed_source_snapshot(tmp_path: Path) -> None:
    form = _valid_evaluate_form(job_id="reed-oversized")
    form.update(
        {
            "input_method": "reed_search",
            "source_type": "reed",
            "source_ref": "oversized",
            "source_snapshot_json": json.dumps(
                {
                    "source": "reed",
                    "source_job_id": "oversized",
                    "captured_at": "2026-05-14T00:00:00+00:00",
                    "capture_stage": "select",
                    "snapshot_version": "pl-04-v1",
                    "description_raw": "x" * (20 * 1024),
                }
            ),
        }
    )

    with _running_ui_server(tmp_path) as (base_url, config):
        status, body = _http_post(f"{base_url}/evaluate", form)

    assert status == 200
    assert "source_snapshot_json exceeds 20KB limit" in body
    assert not (config.state_root / "raw_inputs" / "reed-oversized.json").exists()


def test_post_select_reed_nonce_not_enforced(tmp_path: Path) -> None:
    # Nonce enforcement was removed: this is a local-only server and the in-memory nonce
    # dict was wiped on every server restart (e.g. dev.py auto-reloader), causing spurious
    # "Invalid or expired selection token" errors. A missing/bad nonce is now accepted —
    # the request may still fail for other reasons (e.g. missing source_snapshot_json) but
    # must not be rejected specifically due to the nonce.
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_post(
            f"{base_url}/select/reed",
            {
                "nonce": "bad",
                "source": "reed",
                "title": "Business Analyst",
                "company": "Example Co",
                "description_raw": "Description",
            },
        )

    assert "Invalid or expired selection token" not in body


def test_post_select_reed_missing_and_unsafe_fields_remain_safe(tmp_path: Path, monkeypatch) -> None:
    def fake_fetch_reed_jobs(keyword: str, location: str, max_results: int, *, skip: int = 0, save_raw: bool = True):
        return [
            {
                "jobId": None,
                "jobTitle": "<script>alert(1)</script>",
                "employerName": "",
                "jobUrl": "https://reed.example/jobs/safe",
                "jobDescription": "<b>Useful</b> & safe description",
                "minimumSalary": "not numeric",
            }
        ]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)

    with _running_ui_server(tmp_path) as (base_url, _config):
        _search_status, search_body = _http_get(f"{base_url}/search/reed?keywords=BA")
        select_form = _first_reed_select_form(search_body)
        select_status, select_body = _http_post(f"{base_url}/select/reed", select_form)

    assert select_status == 200
    assert 'name="job_title" value="&lt;script&gt;alert(1)&lt;/script&gt;"' in select_body
    assert 'name="company" value="Unknown"' in select_body
    assert "Useful &amp; safe description" in select_body
    assert "<script>alert(1)</script>" not in select_body


def test_get_reed_search_endpoint_failure_keeps_manual_fallback(tmp_path: Path, monkeypatch) -> None:
    def fake_fetch_reed_jobs(keyword: str, location: str, max_results: int, *, skip: int = 0, save_raw: bool = True):
        raise RuntimeError("Reed timeout")

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)

    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed?keywords=BA&locationName=London")

    assert status == 200
    assert "Reed search unavailable" in body
    assert "Reed search failed: Reed timeout. Manual fallback is still available." in body
    assert '<a href="/?tab=add_job">Use Manual Fallback</a>' in body


def test_get_reed_search_endpoint_missing_fields_do_not_crash(tmp_path: Path, monkeypatch) -> None:
    def fake_fetch_reed_jobs(keyword: str, location: str, max_results: int, *, skip: int = 0, save_raw: bool = True):
        return [{"jobId": None, "jobDescription": ""}]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)

    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed?workMode=invalid&employmentType=weird&resultsToTake=nope")

    assert status == 200
    assert "Reed results (1)" in body
    assert "Unknown" in body
    assert 'name="workMode"' in body
    assert '<option value="any" selected>Any</option>' in body
    assert 'value="10"' in body


def test_get_reed_search_endpoint_no_results_keeps_manual_fallback_link(tmp_path: Path, monkeypatch) -> None:
    def fake_fetch_reed_jobs(keyword: str, location: str, max_results: int, *, skip: int = 0, save_raw: bool = True):
        return []

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)

    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed?keywords=Nonexistent&locationName=Nowhere")

    assert status == 200
    assert "No Reed results found" in body
    assert "Try broader keywords or location" in body
    assert '<a href="/?tab=add_job">Use Manual Fallback</a>' in body


def test_get_evaluate_tab_returns_existing_form_and_history_panel(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/?tab=evaluate")

    assert status == 200
    assert "Evaluate a job" in body
    assert "Input method used to enter this job" in body
    assert "Saved source type for this reviewed job" in body
    assert "Original pasted/context text (reference only)" in body
    assert "Evaluated jobs" in body


def test_get_manual_fallback_tab_keeps_paste_and_url_flow(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/?tab=add_job")

    assert status == 200
    assert "Manual Fallback" in body
    assert "Paste Text" in body
    assert "Job URL" in body
    assert "Paste a job advert or enter a posting URL" in body
    assert 'id="tab-add_job" class="tab-content"' in body


def test_get_unknown_home_tab_falls_back_to_search(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/?tab=unsupported")

    assert status == 200
    assert "Search across connected job boards" in body
    assert 'id="tab-search" class="tab-content"' in body
    assert 'id="tab-evaluate" class="tab-content" hidden' in body


def test_post_evaluate_success_renders_saved_job_result(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        status, body = _http_post(f"{base_url}/evaluate", _valid_evaluate_form())

        assert status == 200
        assert "Job evaluated and saved locally." in body
        assert 'class="panel flash success"' in body
        assert "Business Analyst @ Example Co" in body
        assert "Reviewed job fields" in body
        assert "Source type" in body
        assert "Salary range" in body
        assert "£50,000 – £55,000" in body
        assert "Updated: <strong>Not tracked yet</strong>" in body

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
        assert "Evaluate a job" in body
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
    assert "Current: <strong>applied</strong>" in body
    assert f"Updated: <strong>{saved_outcome.updated_at}</strong>" in body
    assert saved_outcome.status == "applied"
    assert saved_outcome.notes == "Submitted manually"


def test_get_sources_returns_enabled_list(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/sources")

    assert status == 200
    assert json.loads(body) == {"enabled": ["Reed", "Adzuna", "LinkedIn"]}


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


def _http_post_json(url: str, payload: dict) -> tuple[int, dict]:
    """POST JSON to url, return (status_code, parsed_json_body)."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {}
        return exc.code, body


def test_post_job_decision_sets_user_decision(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        _http_post(f"{base_url}/evaluate", _valid_evaluate_form(job_id="job-dec-001"))
        status, body = _http_post_json(
            f"{base_url}/job/job-dec-001/decision",
            {"user_decision": "skip"},
        )
        saved = load_job_analysis("job-dec-001", config.state_root)

    assert status == 200
    assert body["job_id"] == "job-dec-001"
    assert body["user_decision"] == "skip"
    assert "engine_decision" in body
    assert "updated_at" in body
    assert saved.user_decision == "skip"


def test_post_job_decision_clears_user_decision_with_null(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        _http_post(f"{base_url}/evaluate", _valid_evaluate_form(job_id="job-dec-002"))
        # First set a decision
        _http_post_json(f"{base_url}/job/job-dec-002/decision", {"user_decision": "skip"})
        # Then clear it
        status, body = _http_post_json(
            f"{base_url}/job/job-dec-002/decision",
            {"user_decision": None},
        )
        saved = load_job_analysis("job-dec-002", config.state_root)

    assert status == 200
    assert body["user_decision"] is None
    assert saved.user_decision is None


def test_post_job_decision_rejects_invalid_value(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        _http_post(f"{base_url}/evaluate", _valid_evaluate_form(job_id="job-dec-003"))
        status, body = _http_post_json(
            f"{base_url}/job/job-dec-003/decision",
            {"user_decision": "invalid"},
        )

    assert status == 400


def test_post_job_decision_returns_404_for_unknown_job(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_post_json(
            f"{base_url}/job/unknown-job-id/decision",
            {"user_decision": "apply"},
        )

    assert status == 404


def _http_post_json_body(url: str, payload: dict) -> tuple[int, dict]:
    """POST JSON and return (status, parsed_json). Alias to _http_post_json."""
    return _http_post_json(url, payload)


def test_get_jobs_returns_empty_list_when_no_jobs(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/jobs")

    assert status == 200
    data = json.loads(body)
    assert "jobs" in data
    assert data["jobs"] == []


def test_get_board_returns_six_columns(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/board")

    assert status == 200
    data = json.loads(body)
    assert "columns" in data
    cols = data["columns"]
    expected = {"not_applied", "applied", "interview", "offer", "rejected", "withdrawn"}
    assert set(cols.keys()) == expected


def test_post_jobs_save_creates_not_applied_outcome(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, data = _http_post_json(
            f"{base_url}/jobs/save",
            {"job_title": "Data Analyst", "company": "Acme Ltd"},
        )

    assert status == 200
    assert "job_id" in data
    assert data["status"] == "not_applied"


def test_get_jobs_after_save_shows_saved_job(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        save_status, save_data = _http_post_json(
            f"{base_url}/jobs/save",
            {"job_title": "Data Engineer", "company": "Pipeline Corp"},
        )
        list_status, list_body = _http_get(f"{base_url}/jobs")

    assert save_status == 200
    assert list_status == 200
    data = json.loads(list_body)
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["job_title"] == "Data Engineer"
    assert data["jobs"][0]["company"] == "Pipeline Corp"
    assert data["jobs"][0]["status"] == "not_applied"


# ---------------------------------------------------------------------------
# Helpers for POST /tailor route tests
# ---------------------------------------------------------------------------

def _write_apply_job_state(state_root: Path, job_id: str = "tailor-job-001") -> None:
    """Write minimal reviewed_job + analysis JSON files for an apply-decision job."""
    from src.job_hunt_storage import ensure_storage_layout
    layout = ensure_storage_layout(state_root)

    reviewed_job_payload = {
        "job_id": job_id,
        "job_title": "Business Analyst",
        "company": "Example Co",
        "description_raw": "BA role requiring stakeholder management and SQL.",
        "source_type": "copied_text",
        "source_ref": None,
        "location": "London",
        "work_mode": "hybrid",
        "employment_type": "full-time",
        "required_skills": ["Stakeholder Management", "SQL"],
        "preferred_skills": ["Power BI"],
        "required_years_experience": 3.0,
        "nice_to_have_years_experience": None,
        "domain": "finance",
        "notes": None,
        "salary_min_gbp": 50000,
        "salary_max_gbp": 60000,
        "source_quality_score": None,
    }
    (layout.reviewed_jobs_dir / f"{job_id}.json").write_text(
        json.dumps(reviewed_job_payload, indent=2), encoding="utf-8"
    )

    _zero = {"value": 0.0, "reason": "placeholder"}
    analysis_payload = {
        "job_id": job_id,
        "match_score": 85.0,
        "score_breakdown": {
            "skills_score": _zero,
            "experience_score": _zero,
            "location_score": _zero,
            "salary_score": _zero,
            "domain_score": _zero,
            "work_mode_score": _zero,
            "notes": [],
        },
        "blockers": [],
        "strengths": [],
        "missing_required_skills": [],
        "missing_preferred_skills": [],
        "risk_flags": [],
        "decision": "apply",
        "decision_reason": "Strong match across required skills.",
        "confidence": "high",
        "tailoring_ready": True,
        "tailoring_notes": None,
        "ats_score": None,
        "user_decision": None,
        "user_decision_note": None,
    }
    (layout.analyses_dir / f"{job_id}.json").write_text(
        json.dumps(analysis_payload, indent=2), encoding="utf-8"
    )


def _write_skip_job_state(state_root: Path, job_id: str = "tailor-skip-001") -> None:
    """Write minimal reviewed_job + analysis JSON files for a skip-decision job."""
    from src.job_hunt_storage import ensure_storage_layout
    layout = ensure_storage_layout(state_root)

    reviewed_job_payload = {
        "job_id": job_id,
        "job_title": "Unknown Role",
        "company": "Mismatch Co",
        "description_raw": "Very different role.",
        "source_type": "copied_text",
        "source_ref": None,
        "location": None,
        "work_mode": None,
        "employment_type": None,
        "required_skills": [],
        "preferred_skills": [],
        "required_years_experience": None,
        "nice_to_have_years_experience": None,
        "domain": None,
        "notes": None,
        "salary_min_gbp": None,
        "salary_max_gbp": None,
        "source_quality_score": None,
    }
    (layout.reviewed_jobs_dir / f"{job_id}.json").write_text(
        json.dumps(reviewed_job_payload, indent=2), encoding="utf-8"
    )

    _zero = {"value": 0.0, "reason": "placeholder"}
    analysis_payload = {
        "job_id": job_id,
        "match_score": 20.0,
        "score_breakdown": {
            "skills_score": _zero,
            "experience_score": _zero,
            "location_score": _zero,
            "salary_score": _zero,
            "domain_score": _zero,
            "work_mode_score": _zero,
            "notes": [],
        },
        "blockers": [],
        "strengths": [],
        "missing_required_skills": [],
        "missing_preferred_skills": [],
        "risk_flags": [],
        "decision": "skip",
        "decision_reason": "Score too low to proceed.",
        "confidence": "high",
        "tailoring_ready": None,
        "tailoring_notes": None,
        "ats_score": None,
        "user_decision": None,
        "user_decision_note": None,
    }
    (layout.analyses_dir / f"{job_id}.json").write_text(
        json.dumps(analysis_payload, indent=2), encoding="utf-8"
    )


def _write_review_job_state(state_root: Path, job_id: str = "tailor-review-001") -> None:
    """Write minimal reviewed_job + analysis JSON files for a review-decision job."""
    from src.job_hunt_storage import ensure_storage_layout
    layout = ensure_storage_layout(state_root)

    reviewed_job_payload = {
        "job_id": job_id,
        "job_title": "Business Analyst",
        "company": "Borderline Co",
        "description_raw": "BA role needing stakeholder management.",
        "source_type": "copied_text",
        "source_ref": None,
        "location": "London",
        "work_mode": "hybrid",
        "employment_type": "full-time",
        "required_skills": ["Stakeholder Management"],
        "preferred_skills": [],
        "required_years_experience": 3.0,
        "nice_to_have_years_experience": None,
        "domain": None,
        "notes": None,
        "salary_min_gbp": None,
        "salary_max_gbp": None,
        "source_quality_score": None,
    }
    (layout.reviewed_jobs_dir / f"{job_id}.json").write_text(
        json.dumps(reviewed_job_payload, indent=2), encoding="utf-8"
    )

    _zero = {"value": 0.0, "reason": "placeholder"}
    analysis_payload = {
        "job_id": job_id,
        "match_score": 70.0,
        "score_breakdown": {
            "skills_score": _zero,
            "experience_score": _zero,
            "location_score": _zero,
            "salary_score": _zero,
            "domain_score": _zero,
            "work_mode_score": _zero,
            "notes": [],
        },
        "blockers": [],
        "strengths": [],
        "missing_required_skills": [],
        "missing_preferred_skills": [],
        "risk_flags": [],
        "decision": "review",
        "decision_reason": "Borderline match — needs manual review.",
        "confidence": "medium",
        "tailoring_ready": None,
        "tailoring_notes": None,
        "ats_score": None,
        "user_decision": None,
        "user_decision_note": None,
    }
    (layout.analyses_dir / f"{job_id}.json").write_text(
        json.dumps(analysis_payload, indent=2), encoding="utf-8"
    )


def _write_master_cv(profile_path: Path) -> None:
    """Write a master CV file next to the profile if not already present."""
    docs_dir = profile_path.parent / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    cv_path = docs_dir / "master_cv.md"
    if not cv_path.exists():
        cv_path.write_text("# Master CV\n\nBusiness analysis delivery.\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# POST /tailor route tests
# ---------------------------------------------------------------------------

def test_post_tailor_returns_tailored_cv_result_for_apply_job(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        _write_master_cv(config.profile_path)
        _write_apply_job_state(config.state_root, "tailor-apply-001")
        status, data = _http_post_json(f"{base_url}/tailor", {"job_id": "tailor-apply-001"})

    assert status == 200, f"Expected 200, got {status}: {data}"
    assert "summary" in data
    assert "promoted" in data
    assert "matched" in data
    assert "missing" in data
    assert "markdown" in data
    assert "saved_path" in data
    assert isinstance(data["summary"], str)
    assert isinstance(data["promoted"], list)
    assert isinstance(data["matched"], list)
    assert isinstance(data["missing"], list)
    assert isinstance(data["markdown"], str)
    assert len(data["markdown"]) > 0


def test_post_tailor_returns_403_for_skip_job(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        _write_master_cv(config.profile_path)
        _write_skip_job_state(config.state_root, "tailor-skip-001")
        status, data = _http_post_json(f"{base_url}/tailor", {"job_id": "tailor-skip-001"})

    assert status == 403
    assert "Skipped jobs cannot be tailored" in data.get("error", "")


def test_post_tailor_returns_400_for_review_job_without_manual_selected(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        _write_master_cv(config.profile_path)
        _write_review_job_state(config.state_root, "tailor-review-001")
        status, data = _http_post_json(f"{base_url}/tailor", {"job_id": "tailor-review-001"})

    assert status == 400
    assert "Review decisions require manual_selected=true" in data.get("error", "")


def test_post_tailor_returns_404_for_unknown_job_id(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, data = _http_post_json(f"{base_url}/tailor", {"job_id": "nonexistent-job-xyz"})

    assert status == 404


# ---------------------------------------------------------------------------
# POST /cover-letter route tests
# ---------------------------------------------------------------------------

def test_post_cover_letter_returns_letter_for_apply_job(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        _write_apply_job_state(config.state_root, "cover-apply-001")
        status, data = _http_post_json(
            f"{base_url}/cover-letter",
            {
                "job_id": "cover-apply-001",
                "why_company_text": "Example Co's mission aligns with my values.",
            },
        )

    assert status == 200, f"Expected 200, got {status}: {data}"
    assert "letter" in data
    assert "word_count" in data
    assert "saved_path" in data
    assert isinstance(data["letter"], str)
    assert len(data["letter"]) > 0
    assert isinstance(data["word_count"], int)
    assert data["word_count"] > 0
    assert "Example Co's mission aligns with my values." in data["letter"]


def test_post_cover_letter_returns_400_for_skip_job(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        _write_skip_job_state(config.state_root, "cover-skip-001")
        status, data = _http_post_json(
            f"{base_url}/cover-letter",
            {
                "job_id": "cover-skip-001",
                "why_company_text": "I like Mismatch Co.",
            },
        )

    assert status == 400
    assert "Cover letter not available for skipped jobs" in data.get("error", "")


def test_post_cover_letter_returns_400_when_missing_required_fields(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        _write_apply_job_state(config.state_root, "cover-missing-001")
        # Missing why_company_text
        status, data = _http_post_json(
            f"{base_url}/cover-letter",
            {"job_id": "cover-missing-001"},
        )

    assert status == 400
    assert "why_company_text" in data.get("error", "")


def test_post_cover_letter_returns_404_for_unknown_job_id(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, data = _http_post_json(
            f"{base_url}/cover-letter",
            {
                "job_id": "nonexistent-cover-xyz",
                "why_company_text": "Great company.",
            },
        )

    assert status == 404


# ---------------------------------------------------------------------------
# MT-6: previously-untested flows — batch cap, pagination, multipart boundary
# ---------------------------------------------------------------------------
def test_post_batch_evaluate_caps_at_20(tmp_path: Path) -> None:
    # MT-6: the batch endpoint rejects more than 20 jobs in a single request.
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, data = _http_post_json(
            f"{base_url}/jobs/batch-evaluate",
            {"jobs": [{"source": "reed"} for _ in range(21)]},
        )
    assert status == 400
    assert data["ok"] is False
    assert "20" in data["error"]


def test_get_search_reed_more_returns_offset_page(tmp_path: Path, monkeypatch) -> None:
    # MT-6: the /search/reed/more AJAX endpoint returns the next page of cards with
    # IDs offset by resultsSkip and a next_url that advances the skip cursor.
    def fake_fetch_reed_jobs(keyword, location, max_results, *, skip=0, save_raw=True):
        return [
            {
                "jobId": 1000 + i,
                "jobTitle": f"Analyst {i}",
                "employerName": "Acme",
                "locationName": "London",
                "minimumSalary": 50000,
                "maximumSalary": 60000,
                "contractType": "Permanent",
                "jobUrl": f"https://reed.example/jobs/{1000 + i}",
                "jobDescription": "<p>Work</p>",
                "fullTime": True,
            }
            for i in range(max_results)
        ]

    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch_reed_jobs)
    query = urllib.parse.urlencode(
        {"keywords": "analyst", "locationName": "London", "resultsToTake": "10", "resultsSkip": "10"}
    )
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed/more?{query}")

    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["count"] == 10
    assert data["has_more"] is True
    assert 'id="jrc-10"' in data["cards_html"]
    assert "resultsSkip=20" in data["next_url"]


def test_get_search_adzuna_more_returns_offset_page(tmp_path: Path, monkeypatch) -> None:
    # The generic /search/{source}/more endpoint pages Adzuna too: ids are offset
    # by resultsSkip and next_url advances the camelCase resultsSkip cursor.
    captured = {}

    def fake_fetch_adzuna_jobs(keyword, location, max_results=50, *, skip=0):
        captured["skip"] = skip  # offset -> Adzuna page conversion happens inside
        return [
            {
                "id": f"a{i}",
                "title": f"Analyst {i}",
                "company": {"display_name": "Acme"},
                "location": {"display_name": "London"},
                "description": "Work",
                "redirect_url": f"https://adzuna.example/jobs/{i}",
                "created": "2026-06-01T00:00:00Z",
                "contract_type": "permanent",
            }
            for i in range(max_results)
        ]

    monkeypatch.setattr(
        "src.job_sources.adzuna_source.fetch_adzuna_jobs", fake_fetch_adzuna_jobs
    )
    query = urllib.parse.urlencode(
        {"keywords": "analyst", "locationName": "London", "resultsToTake": "10", "resultsSkip": "10"}
    )
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/adzuna/more?{query}")

    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["count"] == 10
    assert data["has_more"] is True
    assert captured["skip"] == 10          # resultsSkip threaded to the client
    assert 'id="jrc-10"' in data["cards_html"]   # cards offset, no collision with page 1
    assert "resultsSkip=20" in data["next_url"]


def test_get_search_linkedin_more_returns_offset_page(tmp_path: Path, monkeypatch) -> None:
    # LinkedIn pages by `start` offset and uses snake_case params; the same generic
    # endpoint must offset card ids and advance the results_skip cursor.
    captured = {}

    def fake_fetch_search(keywords, location, work_mode, start=0):
        captured["start"] = start
        return [
            {
                "source": "linkedin",
                "source_job_id": f"{i}",
                "title": f"Engineer {i}",
                "company": "Acme",
                "location": "London",
                "salary_display": "",
                "salary_min_gbp": None,
                "salary_max_gbp": None,
                "employment_type": "",
                "work_mode": "Remote",
                "url": f"https://www.linkedin.com/jobs/view/{i}/",
                "description_preview": "Build things",
                "description_raw": "",
                "filter_notes": "LinkedIn does not provide salary. Results may vary.",
            }
            for i in range(25)
        ]

    monkeypatch.setattr("src.job_sources.linkedin_source._fetch_search", fake_fetch_search)
    # Force a cache miss / no disk writes so the test is deterministic.
    monkeypatch.setattr("src.job_sources.linkedin_source._cache_get", lambda key: None)
    monkeypatch.setattr("src.job_sources.linkedin_source._cache_set", lambda key, results: None)
    query = urllib.parse.urlencode(
        {"keywords": "engineer", "location": "London", "results_to_take": "10", "results_skip": "10"}
    )
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/linkedin/more?{query}")

    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["count"] == 10
    assert data["has_more"] is True
    assert captured["start"] == 10          # results_skip threaded to the scraper offset
    assert 'id="li-rc-10"' in data["cards_html"]
    assert "results_skip=20" in data["next_url"]


def test_get_search_unknown_source_more_reports_no_pagination(tmp_path: Path) -> None:
    # A source with no render_cards_fragment (or an unknown id) returns a clean
    # JSON error rather than a 500.
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/nope/more?keywords=x")
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is False
    assert "pagination" in data["error"].lower()


def test_post_parse_cv_missing_boundary_returns_clean_error(tmp_path: Path) -> None:
    # MT-4/MT-6: a multipart Content-Type with no boundary= must yield a clear 400,
    # not an unhandled "not enough values to unpack" crash.
    with _running_ui_server(tmp_path) as (base_url, _config):
        request = urllib.request.Request(
            f"{base_url}/profile/parse-cv",
            data=b"ignored",
            method="POST",
            headers={"Content-Type": "multipart/form-data"},
        )
        try:
            with urllib.request.urlopen(request) as response:
                status, raw = response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read().decode("utf-8")

    assert status == 400
    data = json.loads(raw)
    assert data["ok"] is False
    assert "boundary" in data["error"].lower()


def _http_post_multipart(url, fields, files):
    """POST a multipart/form-data body. files = {name: (filename, bytes)}."""
    boundary = "----testboundary1234567890"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    for name, (filename, content) in files.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n\r\n'.encode("utf-8")
            + content + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {}


def test_post_parse_cv_extracts_text_from_txt(tmp_path: Path, monkeypatch) -> None:
    # MT-6: a valid .txt upload is parsed and its text returned (no profile_id → no auto-save).
    monkeypatch.setattr("src.job_hunt_parsing.extract_skills_from_cv", lambda text: ([], None))
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, data = _http_post_multipart(
            f"{base_url}/profile/parse-cv",
            fields={},
            files={"cv_file": ("cv.txt", b"Experienced Business Analyst skilled in SQL and Python.")},
        )
    assert status == 200
    assert data["ok"] is True
    assert "Business Analyst" in data["master_cv_text"]
    assert data["filename"] == "cv.txt"
    assert data["auto_saved"] is False


def test_post_parse_cv_auto_saves_when_profile_id_present(tmp_path: Path, monkeypatch) -> None:
    # MT-6: when profile_id is supplied, the CV is persisted to the profile without
    # a separate "Save Profile" click.
    monkeypatch.setattr("src.job_hunt_parsing.extract_skills_from_cv", lambda text: ([], None))
    monkeypatch.setattr("src.ui_handlers._DATA_ROOT", tmp_path / "data")
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, data = _http_post_multipart(
            f"{base_url}/profile/parse-cv",
            fields={"profile_id": "testcand"},
            files={"cv_file": ("cv.txt", b"My CV mentions SQL, Python and stakeholder management.")},
        )
    assert status == 200
    assert data["ok"] is True
    assert data["auto_saved"] is True
    saved = tmp_path / "data" / "testcand" / "candidate_profile.json"
    assert saved.exists()
    obj = json.loads(saved.read_text(encoding="utf-8"))
    assert "SQL" in obj["master_cv_text"]


def test_post_save_profile_skills_json_takes_precedence_over_comma(tmp_path: Path, monkeypatch) -> None:
    # MT-6: handle_save_profile prefers the structured skills_json over the
    # comma-split skills fallback when both are present.
    monkeypatch.setattr("src.ui_handlers._DATA_ROOT", tmp_path / "data")
    with _running_ui_server(tmp_path) as (base_url, _config):
        _http_post(
            f"{base_url}/profile/save",
            {
                "profile_id": "savecand",
                "name": "Test Candidate",
                "skills_json": json.dumps(["SQL", "Python"]),
                "skills": "OldSkillA,OldSkillB",
            },
        )
    saved = tmp_path / "data" / "savecand" / "candidate_profile.json"
    assert saved.exists()
    text = saved.read_text(encoding="utf-8")
    assert "SQL" in text and "Python" in text
    assert "OldSkillA" not in text and "OldSkillB" not in text


def test_job_page_renders_ats_keyword_match_panel(tmp_path: Path) -> None:
    # F1: after evaluating a job, the job page shows the ATS keyword-match panel
    # and the "Keyword match" verdict metric.
    with _running_ui_server(tmp_path) as (base_url, _config):
        _http_post(f"{base_url}/evaluate", {
            "job_id": "kw-1", "job_title": "Senior BA", "company": "Acme",
            "description_raw": "Lead requirements; SQL and Python.",
            "source_type": "manual", "input_method": "manual",
            "required_skills": "SQL, Python", "preferred_skills": "Tableau",
            "location": "London",
        })
        status, body = _http_get(f"{base_url}/job/kw-1")
    assert status == 200
    assert "ATS keyword match" in body
    assert "Keyword match" in body  # the verdict-card metric label


def test_job_page_links_saved_source_url(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, _config):
        _http_post(f"{base_url}/evaluate", {
            "job_id": "apply-link-1", "job_title": "Senior BA", "company": "Acme",
            "description_raw": "Lead requirements and SQL.",
            "source_type": "url", "source_ref": "https://example.test/jobs/1",
            "location": "London",
        })
        status, body = _http_get(f"{base_url}/job/apply-link-1")
    assert status == 200
    assert 'href="https://example.test/jobs/1"' in body
    assert "View original posting / Apply" in body


def test_job_page_apply_link_prefers_url_over_bare_id_source_ref(tmp_path: Path) -> None:
    # The real bug: a Reed-style job whose source_ref is a bare id but whose
    # canonical advert link is stored in JobPosting.url must still render an
    # apply link, sourced from url (not the unusable bare-id source_ref).
    with _running_ui_server(tmp_path) as (base_url, _config):
        _http_post(f"{base_url}/evaluate", {
            "job_id": "apply-link-2", "job_title": "Senior BA", "company": "Acme",
            "description_raw": "Lead requirements and SQL.",
            "source_type": "manual", "input_method": "manual", "source_ref": "40227781",
            "job_url": "https://www.reed.co.uk/jobs/senior-ba/40227781",
            "location": "London",
        })
        status, body = _http_get(f"{base_url}/job/apply-link-2")
    assert status == 200
    assert 'href="https://www.reed.co.uk/jobs/senior-ba/40227781"' in body
    assert "View original posting / Apply" in body
    # The bare id must not be used as the apply href.
    assert 'href="40227781"' not in body


def test_job_page_no_apply_link_when_only_bare_id_present(tmp_path: Path) -> None:
    # No usable URL anywhere (bare id only) → no apply anchor, graceful fallback.
    with _running_ui_server(tmp_path) as (base_url, _config):
        _http_post(f"{base_url}/evaluate", {
            "job_id": "apply-link-3", "job_title": "Senior BA", "company": "Acme",
            "description_raw": "Lead requirements and SQL.",
            "source_type": "manual", "input_method": "manual", "source_ref": "40227781",
            "location": "London",
        })
        status, body = _http_get(f"{base_url}/job/apply-link-3")
    assert status == 200
    assert "View original posting / Apply" not in body
