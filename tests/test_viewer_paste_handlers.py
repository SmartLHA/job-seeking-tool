"""Viewer paste/URL handlers must work against src/job_hunt_parsing.py."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "viewer", ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import viewer_server as vs  # noqa: E402


def _call(fn, payload):
    return json.loads(fn(json.dumps(payload).encode()).decode())


def test_no_reference_to_deleted_module():
    assert "job_hunt_paste" + "_ui" not in (ROOT / "viewer" / "viewer_server.py").read_text()


def test_text_parse_returns_job_dict():
    out = _call(vs._handle_api_text_parse, {"text": "Job Title: Business Analyst\nCompany: Acme Ltd\nLocation: Chester\nSalary £50,000 - £60,000\nSQL and Python required"})
    assert "error" not in out
    assert "description_raw" in out


def test_text_parse_empty_is_clean_error():
    assert _call(vs._handle_api_text_parse, {"text": ""}) == {"error": "text is required"}


def test_url_parse_rejects_bad_scheme_without_crash():
    out = _call(vs._handle_api_url_parse, {"url": "ftp://example.com/x"})
    assert "error" in out and "scheme" in out["error"].lower()


def test_url_parse_empty_is_clean_error():
    assert _call(vs._handle_api_url_parse, {"url": ""}) == {"error": "url is required"}


def _tmp_profile(tmp_path):
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({
        "candidate_id": "cand-test-001", "name": "Test Candidate",
        "target_roles": ["Business Analyst"], "locations": ["London"],
        "remote_preference": "remote_friendly", "salary_floor_gbp": 50000,
        "right_to_work_uk": True,
        "skills": [{"name": "SQL", "level": "mid"}],
        "years_experience": 5, "industries": ["finance"], "achievements": [],
    }), encoding="utf-8")
    return p


def test_job_submit_persists_via_main_ui_path(tmp_path, monkeypatch):
    """Viewer submit must land where the main UI looks (state root + SQLite index)."""
    from src.job_hunt_index import query_jobs_list
    from src.job_hunt_storage import load_reviewed_job

    monkeypatch.setattr(vs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("JOB_HUNT_PROFILE", str(_tmp_profile(tmp_path)))
    out = _call(vs._handle_api_job_submit, {
        "job_title": "BA", "company": "Acme", "job_id": "../../Evil",
        "description_raw": "SQL role", "required_skills": ["SQL"],
    })
    assert out.get("ok") is True, out
    job_id = out["job_id"]
    assert ".." not in job_id and "/" not in job_id
    state = tmp_path / "data" / "state"
    assert load_reviewed_job(job_id, state).company == "Acme"
    assert job_id in [r["job_id"] for r in query_jobs_list(state / "job_hunt_index.db")]
    assert not (tmp_path / "data" / f"{job_id}.json").exists()  # old flat file is gone


def test_job_submit_requires_title_company_description():
    out = _call(vs._handle_api_job_submit, {})
    assert "job_title" in out["error"] and "company" in out["error"] and "description_raw" in out["error"]


def _assert_nothing_written(tmp_path):
    data = tmp_path / "data"
    assert not data.exists() or not [p for p in data.rglob("*.json")
                                     if p.name != "profile.json"]


def test_job_submit_missing_description_is_clean_error(tmp_path, monkeypatch):
    monkeypatch.setattr(vs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("JOB_HUNT_PROFILE", str(_tmp_profile(tmp_path)))
    out = _call(vs._handle_api_job_submit, {"job_title": "BA", "company": "Acme"})
    assert "description_raw" in out["error"]
    _assert_nothing_written(tmp_path)


def test_job_submit_missing_company_is_clean_error(tmp_path, monkeypatch):
    monkeypatch.setattr(vs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("JOB_HUNT_PROFILE", str(_tmp_profile(tmp_path)))
    out = _call(vs._handle_api_job_submit, {"job_title": "BA", "description_raw": "SQL role"})
    assert "company" in out["error"]
    _assert_nothing_written(tmp_path)


def test_job_submit_missing_profile_is_clean_error(tmp_path, monkeypatch):
    monkeypatch.setattr(vs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("JOB_HUNT_PROFILE", str(tmp_path / "nope.json"))
    out = _call(vs._handle_api_job_submit, {"job_title": "BA", "company": "Acme", "description_raw": "SQL role"})
    assert "error" in out and "ok" not in out
    _assert_nothing_written(tmp_path)
