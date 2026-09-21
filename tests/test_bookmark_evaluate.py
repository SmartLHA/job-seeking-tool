"""Tests for the bookmark -> evaluate bridge.

A job saved via POST /jobs/save (a "bookmark") previously dead-ended: there was
no way to evaluate it later, because evaluation only built from an HTTP form.
This covers the new GET /job/<id>/evaluate-form prefill route, the pure
form_values_from_reviewed_job helper, and the full round-trip that reuses the
same job_id (so re-evaluation updates the record in place, not a duplicate).
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

from src.job_hunt_models import JobPosting
from src.job_hunt_storage import load_job_analysis, load_reviewed_job
from src.ui_routes import _build_handler
from src.ui_state import UIServerConfig
from src.ui_utils import default_form_values, form_values_from_reviewed_job


# ── unit: the pure helper ────────────────────────────────────────────────────

def _sample_job() -> JobPosting:
    return JobPosting(
        job_id="manual-abc123",
        job_title="Business Analyst",
        company="Example Co",
        description_raw="Stakeholder management and SQL.",
        source_type="manual",
        source_ref="https://example.com/job/1",
        location="London",
        work_mode="hybrid",
        employment_type="full-time",
        required_skills=["Stakeholder Management", "SQL"],
        preferred_skills=["Power BI"],
        required_years_experience=3,
        domain="finance",
        salary_min_gbp=50000,
        salary_max_gbp=55000,
        url="https://example.com/job/1",
    )


def test_helper_preserves_job_id() -> None:
    values = form_values_from_reviewed_job(_sample_job())
    # Preserving job_id is the core guarantee: re-submit updates the same record.
    assert values["job_id"] == "manual-abc123"


def test_helper_maps_scalar_and_list_fields() -> None:
    values = form_values_from_reviewed_job(_sample_job())
    assert values["job_title"] == "Business Analyst"
    assert values["company"] == "Example Co"
    assert values["location"] == "London"
    assert values["domain"] == "finance"
    assert values["salary_min_gbp"] == "50000"
    # Lists are newline-joined to match the manual form's textarea convention.
    assert values["required_skills"] == "Stakeholder Management\nSQL"
    assert values["preferred_skills"] == "Power BI"


def test_helper_returns_full_form_shape_with_blanks() -> None:
    # A minimal bookmark (empty skills, default description) still yields a
    # complete, valid form-values dict — missing data stays blank, not invented.
    minimal = JobPosting(
        job_id="manual-empty",
        job_title="Analyst",
        company="Co",
        description_raw="No description provided.",
        source_type="manual",
        source_ref=None,
        location=None,
        work_mode=None,
        employment_type=None,
    )
    values = form_values_from_reviewed_job(minimal)
    assert set(values) == set(default_form_values())
    assert values["required_skills"] == ""
    assert values["location"] == ""
    assert values["source_type"] == "manual"


# ── integration: the full bookmark -> evaluate flow ──────────────────────────

def _write_profile(tmp_path: Path) -> Path:
    profile_dir = tmp_path / "profile"
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
                "skills": ["Stakeholder Management", "SQL"],
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


@contextmanager
def _running_ui_server(tmp_path: Path):
    config = UIServerConfig(
        profile_path=_write_profile(tmp_path),
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


def _http_post_form(url: str, form: dict[str, str]) -> tuple[int, str]:
    data = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _http_post_json(url: str, payload: dict) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_unevaluated_job_page_shows_evaluate_cta(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base, _config):
        status, body = _http_post_json(
            f"{base}/jobs/save",
            {"job_title": "Business Analyst", "company": "Example Co"},
        )
        assert status == 200
        job_id = json.loads(body)["job_id"]

        status, page = _http_get(f"{base}/job/{job_id}")
        assert status == 200
        # The dead-end is gone: the unevaluated job page links to the prefill route.
        assert f"/job/{job_id}/evaluate-form" in page
        assert "evaluate this job" in page.lower()


def test_evaluate_form_prefills_saved_job_and_round_trips(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base, config):
        status, body = _http_post_json(
            f"{base}/jobs/save",
            {
                "job_title": "Business Analyst",
                "company": "Example Co",
                "location": "London",
                "source_ref": "https://example.com/job/1",
            },
        )
        assert status == 200
        job_id = json.loads(body)["job_id"]

        # Prefill route returns the Evaluate form carrying the SAME job_id.
        status, form_page = _http_get(f"{base}/job/{job_id}/evaluate-form")
        assert status == 200
        assert re.search(rf'name="job_id" value="{re.escape(job_id)}"', form_page)
        assert "Business Analyst" in form_page
        assert "Example Co" in form_page

        # Submitting evaluation with that job_id evaluates in place.
        form = {
            **default_form_values(),
            "job_id": job_id,
            "job_title": "Business Analyst",
            "company": "Example Co",
            "description_raw": "Stakeholder management and SQL reporting.",
            "source_type": "manual",
            "required_skills": "Stakeholder Management\nSQL",
        }
        status, _ = _http_post_form(f"{base}/evaluate", form)
        assert status == 200

        # Analysis now exists under the original job_id — no orphan, no duplicate.
        analysis = load_job_analysis(job_id, config.state_root)
        assert analysis.job_id == job_id
        assert load_reviewed_job(job_id, config.state_root).job_id == job_id


def test_evaluate_form_unknown_id_returns_404(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base, _config):
        status, _ = _http_get(f"{base}/job/does-not-exist/evaluate-form")
        assert status == 404


def test_scored_job_page_shows_reevaluate_link(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base, _config):
        job_id = "reeval-job-001"
        form = {
            **default_form_values(),
            "job_id": job_id,
            "job_title": "Business Analyst",
            "company": "Example Co",
            "description_raw": "Stakeholder management and SQL reporting.",
            "source_type": "manual",
            "required_skills": "Stakeholder Management\nSQL",
        }
        status, _ = _http_post_form(f"{base}/evaluate", form)
        assert status == 200

        status, page = _http_get(f"{base}/job/{job_id}")
        assert status == 200
        # An already-scored job offers a Re-evaluate action via the same prefill route.
        assert f"/job/{job_id}/evaluate-form" in page
        assert "re-evaluate" in page.lower()
