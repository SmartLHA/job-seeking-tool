"""Tests for untested ui_handlers functions.

Coverage targets:
- handle_job_explain (L576)
- handle_prefill (L774)
- handle_job_submit (L804)
- handle_add_gap_skills (L919)
- handle_ai_review_cv (L973)
- handle_get_board_view (L1135)
- handle_search_reed_more (L1291)
- handle_get_review_queue (L1365)
- set_daemons (L1721)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from http import HTTPStatus
from pathlib import Path
from unittest import mock

import pytest

from src.job_hunt_models import (
    JobPosting,
    CandidateProfile,
    Skill,
    JobAnalysis,
    ScoreBreakdown,
    ScoreComponent,
)
from src.job_hunt_orchestrator import LocalEvaluationRunResult
from src.ui_handlers import (
    handle_job_explain,
    handle_prefill,
    handle_job_submit,
    handle_add_gap_skills,
    handle_ai_review_cv,
    handle_get_board_view,
    handle_search_reed_more,
    handle_get_review_queue,
    set_daemons,
)
from src.ui_routes import UIRequest, UIResponder
from src.ui_state import UIServerConfig
from src.job_hunt_storage import (
    save_reviewed_job,
    save_job_analysis,
    ensure_storage_layout,
)


def _build_score_breakdown() -> ScoreBreakdown:
    """Helper to create a valid ScoreBreakdown."""
    return ScoreBreakdown(
        skills_score=ScoreComponent(value=32, reason="Strong required skill overlap"),
        experience_score=ScoreComponent(value=18, reason="Experience level is suitable"),
        location_score=ScoreComponent(value=12, reason="Location is acceptable"),
        salary_score=ScoreComponent(value=8, reason="Salary range is acceptable"),
        domain_score=ScoreComponent(value=6, reason="Domain fit is neutral"),
        work_mode_score=ScoreComponent(value=4, reason="Work mode is acceptable"),
    )


def _make_test_job(job_id: str, **kwargs) -> JobPosting:
    """Helper to create a test JobPosting with required fields."""
    defaults = {
        "job_id": job_id,
        "job_title": "Test Role",
        "company": "Test Co",
        "description_raw": "Test description",
        "source_type": "copied_text",
        "source_ref": "manual",
        "location": "London",
        "work_mode": "hybrid",
        "employment_type": "full-time",
    }
    defaults.update(kwargs)
    return JobPosting(**defaults)



def _make_local_eval_result(reviewed_job: JobPosting, analysis: JobAnalysis) -> LocalEvaluationRunResult:
    """Helper to create LocalEvaluationRunResult for mocking."""
    from pathlib import Path
    import tempfile
    
    tmpdir = Path(tempfile.gettempdir())
    return LocalEvaluationRunResult(
        profile=CandidateProfile(candidate_id="test-candidate"),
        reviewed_job=reviewed_job,
        analysis=analysis,
        storage_root=tmpdir / "storage",
        reviewed_job_path=tmpdir / "reviewed_job.json",
        analysis_path=tmpdir / "analysis.json",
        raw_input_path=None,
        report_json_path=tmpdir / "report.json",
        report_csv_path=tmpdir / "report.csv",
        master_cv_path=None,
    )

@dataclass
class MockResponder:
    """Mock UIResponder for testing."""
    json_sent: dict | None = None
    html_sent: str | None = None
    redirect_location: str | None = None
    last_status: HTTPStatus = HTTPStatus.OK

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.json_sent = payload
        self.last_status = status

    def send_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.html_sent = body
        self.last_status = status

    def redirect(self, location: str) -> None:
        self.redirect_location = location


def _make_request(
    method: str = "GET",
    path: str = "/",
    query: dict | None = None,
    form: dict | None = None,
    json_body: dict | None = None,
    raw_body: bytes | None = None,
) -> UIRequest:
    return UIRequest(
        method=method,
        path=path,
        query=query or {},
        form=form or {},
        json_body=json_body,
        raw_body=raw_body or b"",
        headers={},
        content_type="",
    )


def _setup_test_profile(tmp_path: Path) -> Path:
    """Create a test profile and return its path."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "docs").mkdir(parents=True, exist_ok=True)
    cv_path = profile_dir / "docs" / "master_cv.md"
    cv_path.write_text("# Master CV\n\nSQL, Python, Stakeholder Management", encoding="utf-8")

    profile_path = profile_dir / "candidate_profile.json"
    profile_path.write_text(
        json.dumps({
            "candidate_id": "cand-test-001",
            "name": "Test Candidate",
            "target_roles": ["Business Analyst"],
            "locations": ["London"],
            "remote_preference": "remote_friendly",
            "salary_floor_gbp": 50000,
            "right_to_work_uk": True,
            "skills": [
                {"name": "SQL", "level": "mid"},
                {"name": "Python", "level": "junior"},
                {"name": "Stakeholder Management", "level": "expert"},
            ],
            "years_experience": 5,
            "industries": ["finance"],
            "achievements": ["Improved reporting"],
            "certifications": ["BCS"],
            "master_cv_ref": "docs/master_cv.md",
        }),
        encoding="utf-8",
    )
    return profile_path


class TestHandleJobExplain:
    """Tests for handle_job_explain."""

    def test_handle_job_explain_missing_job_id(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        req = _make_request(path="/job//explain")
        responder = MockResponder()

        handle_job_explain(req, config, responder, "  ")

        assert responder.json_sent["ok"] is False
        assert "Missing job id" in responder.json_sent["error"]
        assert responder.last_status == HTTPStatus.BAD_REQUEST

    def test_handle_job_explain_job_not_found(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)
        req = _make_request()
        responder = MockResponder()

        handle_job_explain(req, config, responder, "nonexistent-job")

        assert responder.json_sent["ok"] is False
        assert "not found" in responder.json_sent["error"]
        assert responder.last_status == HTTPStatus.NOT_FOUND

    def test_handle_job_explain_no_analysis(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)

        # Save a job but no analysis
        job = JobPosting(
            job_id="job-001",
            job_title="Business Analyst",
            company="Example Co",
            description_raw="Desc",
            source_type="copied_text",
            source_ref="manual",
            location="London",
            work_mode="hybrid",
            employment_type="full-time",
        )
        save_reviewed_job(job, config.state_root)

        req = _make_request()
        responder = MockResponder()
        handle_job_explain(req, config, responder, "job-001")

        assert responder.json_sent["ok"] is False
        assert "No analysis" in responder.json_sent.get("error", "")
        assert responder.last_status == HTTPStatus.NOT_FOUND

    def test_handle_job_explain_with_mock_llm(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)

        # Save job and analysis
        job = JobPosting(
            job_id="job-001",
            job_title="Business Analyst",
            company="Example Co",
            description_raw="Needs SQL and stakeholder management",
            source_type="reed",
            source_ref="https://reed.co.uk/jobs/123",
            location="London",
            work_mode="hybrid",
            employment_type="full-time",
        )
        save_reviewed_job(job, config.state_root)

        analysis = JobAnalysis(
            job_id="job-001",
            match_score=75.0,
            score_breakdown=_build_score_breakdown(),
            decision="apply",
            decision_reason="Good skill match",
        )
        save_job_analysis(analysis, config.state_root)

        req = _make_request()
        responder = MockResponder()

        # Mock the explain_job_match_with_llm function
        with mock.patch("src.job_hunt_llm.explain_job_match_with_llm") as mock_explain:
            mock_explain.return_value = (
                {"explanation": "Good match", "reasoning": "Skills align well"},
                None,
            )
            handle_job_explain(req, config, responder, "job-001")

        assert responder.json_sent["ok"] is True
        assert "explanation" in responder.json_sent
        assert responder.last_status == HTTPStatus.OK

    def test_handle_job_explain_llm_unavailable(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)

        # Save job and analysis
        job = _make_test_job("job-001", job_title="BA")
        save_reviewed_job(job, config.state_root)

        analysis = JobAnalysis(
            job_id="job-001",
            match_score=50.0,
            score_breakdown=_build_score_breakdown(),
            decision="review",
            decision_reason="Neutral match",
        )
        save_job_analysis(analysis, config.state_root)

        req = _make_request()
        responder = MockResponder()

        with mock.patch("src.job_hunt_llm.explain_job_match_with_llm") as mock_explain:
            mock_explain.return_value = (None, "LLM error")
            handle_job_explain(req, config, responder, "job-001")

        assert responder.json_sent["ok"] is False
        assert responder.last_status == HTTPStatus.SERVICE_UNAVAILABLE


class TestHandlePrefill:
    """Tests for handle_prefill."""

    def test_handle_prefill_paste_mode(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        form = {
            "prefill_mode": "paste",
            "job_text": "Business Analyst role at Example Co, London. Requires SQL.",
        }
        req = _make_request(method="POST", form=form)
        responder = MockResponder()

        with mock.patch("src.job_hunt_parsing.parse_job_from_text") as mock_parse:
            mock_parse.return_value = {
                "job_title": "Business Analyst",
                "company": "Example Co",
                "location": "London",
                "description_raw": "Requires SQL",
            }
            handle_prefill(req, config, responder)

        assert responder.json_sent["ok"] is True
        assert responder.json_sent["values"]["input_method"] == "copied_text"
        assert responder.json_sent["values"]["copied_text"] == form["job_text"]
        assert responder.json_sent["values"]["source_type"] == "copied_text"

    def test_handle_prefill_url_mode(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        url = "https://reed.co.uk/jobs/123"
        form = {
            "prefill_mode": "url",
            "job_url": url,
        }
        req = _make_request(method="POST", form=form)
        responder = MockResponder()

        with mock.patch("src.ui_handlers.parse_job_from_url") as mock_parse:
            mock_parse.return_value = {
                "job_title": "Senior BA",
                "company": "Tech Co",
                "description_raw": "Desc",
            }
            handle_prefill(req, config, responder)

        assert responder.json_sent["ok"] is True
        assert responder.json_sent["values"]["input_method"] == "url"
        assert responder.json_sent["values"]["job_url"] == url
        assert responder.json_sent["values"]["source_type"] == "url"

    def test_handle_prefill_invalid_mode(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        form = {"prefill_mode": "invalid", "job_text": "something"}
        req = _make_request(method="POST", form=form)
        responder = MockResponder()

        handle_prefill(req, config, responder)

        assert responder.json_sent["ok"] is False
        assert "must be paste or url" in responder.json_sent["error"]

    def test_handle_prefill_parse_error(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        form = {"prefill_mode": "paste", "job_text": ""}
        req = _make_request(method="POST", form=form)
        responder = MockResponder()

        with mock.patch("src.job_hunt_parsing.parse_job_from_text") as mock_parse:
            mock_parse.side_effect = ValueError("No job found in text")
            handle_prefill(req, config, responder)

        assert responder.json_sent["ok"] is False
        assert "error" in responder.json_sent


class TestHandleJobSubmit:
    """Tests for handle_job_submit."""

    def test_handle_job_submit_with_valid_form(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)

        form = {
            "job_id": "job-submit-001",
            "job_title": "Business Analyst",
            "company": "Test Co",
            "description_raw": "Role description with SQL and Python",
            "source_type": "copied_text",
            "source_ref": "manual",
            "input_method": "copied_text",
            "copied_text": "Original text",
            "location": "London",
            "work_mode": "hybrid",
            "employment_type": "full-time",
            "required_skills": "SQL, Python",
            "preferred_skills": "Tableau",
            "required_years_experience": "3",
            "domain": "finance",
            "salary_min_gbp": "50000",
            "salary_max_gbp": "60000",
            "notes": "",
        }
        req = _make_request(method="POST", form=form)
        responder = MockResponder()

        with mock.patch("src.ui_handlers.run_local_evaluation_flow_from_payload") as mock_eval:
            mock_eval.return_value = _make_local_eval_result(
                reviewed_job=JobPosting(
                    job_id="job-submit-001",
                    job_title="Business Analyst",
                    company="Test Co",
                    description_raw="Test",
                    source_type="copied_text",
                    source_ref="manual",
                    location="London",
                    work_mode="hybrid",
                    employment_type="full-time",
                ),
                analysis=JobAnalysis(
                    job_id="job-submit-001",
                    match_score=75.0,
                    score_breakdown=_build_score_breakdown(),
                    decision="apply",
                    decision_reason="Good match",
                ),
            )
            handle_job_submit(req, config, responder)

        assert responder.redirect_location == "/job/job-submit-001"

    def test_handle_job_submit_auto_generates_id_when_missing(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)

        form = {
            "job_id": "",  # Empty, should be auto-generated
            "job_title": "Developer",
            "company": "Tech Co",
            "description_raw": "Role",
            "source_type": "copied_text",
            "source_ref": "manual",
            "input_method": "copied_text",
            "copied_text": "text",
            "location": "",
            "work_mode": "remote",
            "employment_type": "full-time",
            "required_skills": "",
            "preferred_skills": "",
            "required_years_experience": "0",
            "domain": "",
            "salary_min_gbp": "",
            "salary_max_gbp": "",
            "notes": "",
        }
        req = _make_request(method="POST", form=form)
        responder = MockResponder()

        with mock.patch("src.ui_handlers.run_local_evaluation_flow_from_payload") as mock_eval:
            mock_eval.return_value = _make_local_eval_result(
                reviewed_job=JobPosting(
                    job_id="developer-tech-co-20260708000000",
                    job_title="Developer",
                    company="Tech Co",
                    description_raw="Test",
                    source_type="copied_text",
                    source_ref="manual",
                    location="London",
                    work_mode="hybrid",
                    employment_type="full-time",
                ),
                analysis=JobAnalysis(
                    job_id="developer-tech-co-20260708000000",
                    match_score=50.0,
                    score_breakdown=_build_score_breakdown(),
                    decision="review",
                    decision_reason="Neutral match",
                ),
            )
            handle_job_submit(req, config, responder)

        # Verify that an ID was generated and passed to the evaluator
        assert mock_eval.called
        call_args = mock_eval.call_args
        assert call_args.kwargs["reviewed_job_payload"]["job_id"]

    def test_handle_job_submit_evaluation_error(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)

        form = {
            "job_id": "job-error-001",
            "job_title": "BA",
            "company": "Co",
            "description_raw": "desc",
            "source_type": "copied_text",
            "source_ref": "manual",
            "input_method": "copied_text",
            "copied_text": "text",
            "location": "",
            "work_mode": "remote",
            "employment_type": "full-time",
            "required_skills": "",
            "preferred_skills": "",
            "required_years_experience": "0",
            "domain": "",
            "salary_min_gbp": "",
            "salary_max_gbp": "",
            "notes": "",
        }
        req = _make_request(method="POST", form=form)
        responder = MockResponder()

        with mock.patch("src.ui_handlers.run_local_evaluation_flow_from_payload") as mock_eval:
            mock_eval.side_effect = Exception("Evaluation failed")
            handle_job_submit(req, config, responder)

        assert responder.json_sent["ok"] is False
        assert responder.last_status == HTTPStatus.UNPROCESSABLE_ENTITY


class TestHandleAddGapSkills:
    """Tests for handle_add_gap_skills."""

    def test_handle_add_gap_skills_adds_new_skills(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        payload = {"skills": ["Tableau", "Power BI", "Advanced Excel"]}
        req = _make_request(
            method="POST",
            raw_body=json.dumps(payload).encode("utf-8"),
        )
        responder = MockResponder()

        handle_add_gap_skills(req, config, responder, "job-001")

        assert responder.json_sent["ok"] is True
        assert len(responder.json_sent["added"]) == 3
        assert "Tableau" in responder.json_sent["added"]
        assert responder.json_sent["skipped"] == []

    def test_handle_add_gap_skills_skips_duplicates(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        # SQL is already in the profile
        payload = {"skills": ["SQL", "Tableau"]}
        req = _make_request(
            method="POST",
            raw_body=json.dumps(payload).encode("utf-8"),
        )
        responder = MockResponder()

        handle_add_gap_skills(req, config, responder, "job-001")

        assert responder.json_sent["ok"] is True
        assert "SQL" in responder.json_sent["skipped"]
        assert "Tableau" in responder.json_sent["added"]

    def test_handle_add_gap_skills_invalid_json(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        req = _make_request(method="POST", raw_body=b"{invalid json}")
        responder = MockResponder()

        handle_add_gap_skills(req, config, responder, "job-001")

        assert responder.json_sent["ok"] is False
        assert responder.last_status == HTTPStatus.BAD_REQUEST

    def test_handle_add_gap_skills_skills_not_list(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        payload = {"skills": "not a list"}
        req = _make_request(
            method="POST",
            raw_body=json.dumps(payload).encode("utf-8"),
        )
        responder = MockResponder()

        handle_add_gap_skills(req, config, responder, "job-001")

        assert responder.json_sent["ok"] is False
        assert responder.last_status == HTTPStatus.BAD_REQUEST

    def test_handle_add_gap_skills_empty_skills_list(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        payload = {"skills": []}
        req = _make_request(
            method="POST",
            raw_body=json.dumps(payload).encode("utf-8"),
        )
        responder = MockResponder()

        handle_add_gap_skills(req, config, responder, "job-001")

        assert responder.json_sent["ok"] is True
        assert responder.json_sent["added"] == []

    def test_handle_add_gap_skills_profile_not_found(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=tmp_path / "nonexistent" / "profile.json",
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        payload = {"skills": ["Python"]}
        req = _make_request(
            method="POST",
            raw_body=json.dumps(payload).encode("utf-8"),
        )
        responder = MockResponder()

        handle_add_gap_skills(req, config, responder, "job-001")

        assert responder.json_sent["ok"] is False
        assert responder.last_status == HTTPStatus.NOT_FOUND


class TestHandleAiReviewCv:
    """Tests for handle_ai_review_cv."""

    def test_handle_ai_review_cv_skipped_job_forbidden(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)

        # Save job and analysis with skip decision
        job = _make_test_job("job-skip")
        save_reviewed_job(job, config.state_root)

        analysis = JobAnalysis(
            job_id="job-skip",
            match_score=20.0,  # Low score triggers skip
            score_breakdown=_build_score_breakdown(),
            decision="skip",
            decision_reason="Poor match",
        )
        save_job_analysis(analysis, config.state_root)

        req = _make_request()
        responder = MockResponder()

        handle_ai_review_cv(req, config, responder, "job-skip")

        assert responder.json_sent["ok"] is False
        assert "cannot have CV reviewed" in responder.json_sent["error"]
        assert responder.last_status == HTTPStatus.FORBIDDEN

    def test_handle_ai_review_cv_success_with_mock_llm(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)

        # Save job and analysis with apply decision
        job = _make_test_job(
            "job-review-cv",
            job_title="Business Analyst",
            company="Test Co",
            description_raw="Needs SQL and Python",
            required_skills=["SQL", "Python"],
        )
        save_reviewed_job(job, config.state_root)

        analysis = JobAnalysis(
            job_id="job-review-cv",
            match_score=75.0,
            score_breakdown=_build_score_breakdown(),
            decision="apply",
            decision_reason="Good match",
        )
        save_job_analysis(analysis, config.state_root)

        req = _make_request()
        responder = MockResponder()

        with mock.patch("src.job_hunt_llm.ai_review_cv_with_llm") as mock_review:
            mock_review.return_value = (
                {
                    "reviewed_cv": "Updated CV text",
                    "changes": ["Emphasized SQL skills"],
                },
                None,
                "gemini-pro",
            )
            handle_ai_review_cv(req, config, responder, "job-review-cv")

        assert responder.json_sent["ok"] is True
        assert responder.json_sent["saved_path"] == "job-review-cv_ai_reviewed.md"
        assert "/" not in responder.json_sent["saved_path"]
        assert "\\" not in responder.json_sent["saved_path"]
        assert responder.last_status == HTTPStatus.OK

    @pytest.mark.parametrize("job_id", ["../escape", "nested/job", "..", ""])
    def test_handle_ai_review_cv_rejects_unsafe_job_id(self, tmp_path: Path, job_id: str) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        responder = MockResponder()

        handle_ai_review_cv(_make_request(), config, responder, job_id)

        assert responder.json_sent == {"ok": False, "error": "Job not found"}
        assert responder.last_status == HTTPStatus.NOT_FOUND

    def test_handle_ai_review_cv_hides_unreadable_cv_path(self, tmp_path: Path) -> None:
        profile_path = _setup_test_profile(tmp_path)
        profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
        profile_data["master_cv_ref"] = "/private/hidden-candidate-documents/master_cv.md"
        profile_path.write_text(json.dumps(profile_data), encoding="utf-8")
        config = UIServerConfig(profile_path=profile_path, state_root=tmp_path / "state", report_dir=tmp_path / "reports")
        ensure_storage_layout(config.state_root)
        job = _make_test_job("job-unreadable-cv")
        save_reviewed_job(job, config.state_root)
        save_job_analysis(JobAnalysis(job_id=job.job_id, match_score=75.0, score_breakdown=_build_score_breakdown(), decision="apply", decision_reason="Good match"), config.state_root)
        responder = MockResponder()

        handle_ai_review_cv(_make_request(), config, responder, job.job_id)

        assert responder.last_status == HTTPStatus.UNPROCESSABLE_ENTITY
        assert "/private/hidden-candidate-documents" not in responder.json_sent["error"]
        assert responder.json_sent["error"] == "CV file could not be read. Re-upload on the Profile page."

    def test_handle_ai_review_cv_job_not_found(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)

        req = _make_request()
        responder = MockResponder()

        handle_ai_review_cv(req, config, responder, "nonexistent-job")

        assert responder.json_sent["ok"] is False
        assert responder.last_status == HTTPStatus.NOT_FOUND


class TestHandleGetBoardView:
    """Tests for handle_get_board_view."""

    def test_handle_get_board_view_renders_six_empty_semantic_columns(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)

        req = _make_request()
        responder = MockResponder()

        handle_get_board_view(req, config, responder)

        assert responder.html_sent is not None
        html = responder.html_sent
        assert "Board View" in html
        assert "coming soon" not in html
        assert "Raw board data" not in html
        assert "<pre" not in html
        assert html.count('class="board-column"') == 6
        for status in ("not_applied", "applied", "interview", "offer", "rejected", "withdrawn"):
            assert f'data-status="{status}"' in html
            assert f'aria-labelledby="board-column-{status}-title"' in html
        assert html.count('class="board-empty"') == 6
        assert 'aria-label="Board summary"' in html
        assert responder.last_status == HTTPStatus.OK

    def test_handle_get_board_view_renders_linked_escaped_card(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        board = {
            "columns": {
                "not_applied": [{
                    "job_id": "job/unsafe id",
                    "job_title": '<script>alert("title")</script>',
                    "company": "A&B <Co>",
                    "location": 'Chester "HQ"',
                    "match_score": "<92>",
                }],
                "applied": [],
                "interview": [],
                "offer": [],
                "rejected": [],
                "withdrawn": [],
            },
            "stats": {"active": 1, "interviews": 0, "offers": 0, "response_rate": 0.25},
        }
        responder = MockResponder()

        with mock.patch("src.job_hunt_index.query_board", return_value=board):
            handle_get_board_view(_make_request(), config, responder)

        html = responder.html_sent
        assert html is not None
        assert 'href="/job/job%2Funsafe%20id"' in html
        assert '<article class="board-card">' in html
        assert "&lt;script&gt;alert(&quot;title&quot;)&lt;/script&gt;" in html
        assert "A&amp;B &lt;Co&gt;" in html
        assert "Chester &quot;HQ&quot;" in html
        assert "Score &lt;92&gt;" in html
        assert "<script>alert" not in html
        assert html.count('class="board-empty"') == 5
        assert ">25%<" in html


class TestHandleSearchReedMore:
    """Tests for handle_search_reed_more."""

    def test_handle_search_reed_more_delegates(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        req = _make_request(
            path="/search/reed/more?keywords=BA&resultsSkip=50&resultsToTake=50"
        )
        responder = MockResponder()

        with mock.patch("src.ui_handlers.handle_source_search_more") as mock_delegate:
            handle_search_reed_more(req, config, responder)
            mock_delegate.assert_called_once()
            assert mock_delegate.call_args[0][3] == "reed"


class TestHandleGetReviewQueue:
    """Tests for handle_get_review_queue."""

    def test_handle_get_review_queue_no_ids(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)

        req = _make_request(path="/review-queue?ids=")
        responder = MockResponder()

        handle_get_review_queue(req, config, responder)

        assert responder.html_sent is not None
        assert "No jobs specified" in responder.html_sent

    def test_handle_get_review_queue_with_jobs(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)

        # Save test jobs
        for i, decision in enumerate(["apply", "review", "skip"]):
            job = _make_test_job(
                f"job-queue-{i}",
                job_title=f"Role {i}",
                company=f"Co {i}",
                salary_min_gbp=50000 + i * 10000,
                salary_max_gbp=60000 + i * 10000,
            )
            save_reviewed_job(job, config.state_root)

            analysis = JobAnalysis(
                job_id=f"job-queue-{i}",
                match_score=75.0 - (i * 20),
                score_breakdown=_build_score_breakdown(),
                decision=decision,
                decision_reason=f"Test {decision}",
            )
            save_job_analysis(analysis, config.state_root)

        req = _make_request(path="/review-queue?ids=job-queue-0,job-queue-1,job-queue-2&active=job-queue-0")
        responder = MockResponder()

        handle_get_review_queue(req, config, responder)

        assert responder.html_sent is not None
        assert "Review queue" in responder.html_sent
        assert "job-queue-0" in responder.html_sent
        assert responder.last_status == HTTPStatus.OK

    def test_handle_get_review_queue_selects_first_when_active_missing(self, tmp_path: Path) -> None:
        config = UIServerConfig(
            profile_path=_setup_test_profile(tmp_path),
            state_root=tmp_path / "state",
            report_dir=tmp_path / "reports",
        )
        ensure_storage_layout(config.state_root)

        # Save a job
        job = _make_test_job("job-first", job_title="Role", company="Co")
        save_reviewed_job(job, config.state_root)

        analysis = JobAnalysis(
            job_id="job-first",
            match_score=75.0,
            score_breakdown=_build_score_breakdown(),
            decision="review",
            decision_reason="Test review",
        )
        save_job_analysis(analysis, config.state_root)

        req = _make_request(path="/review-queue?ids=job-first&active=")
        responder = MockResponder()

        handle_get_review_queue(req, config, responder)

        assert responder.html_sent is not None
        assert "job-first" in responder.html_sent


class TestSetDaemons:
    """Tests for set_daemons."""

    def test_set_daemons_sets_global_state(self) -> None:
        import src.ui_handlers as handlers

        # Store original values
        orig_scheduler = handlers._DIGEST_SCHEDULER
        orig_worker = handlers._LLM_WORKER

        try:
            mock_scheduler = mock.Mock()
            mock_worker = mock.Mock()

            set_daemons(scheduler=mock_scheduler, worker=mock_worker)

            assert handlers._DIGEST_SCHEDULER is mock_scheduler
            assert handlers._LLM_WORKER is mock_worker
        finally:
            # Restore
            set_daemons(scheduler=orig_scheduler, worker=orig_worker)

    def test_set_daemons_accepts_none(self) -> None:
        import src.ui_handlers as handlers

        orig_scheduler = handlers._DIGEST_SCHEDULER
        orig_worker = handlers._LLM_WORKER

        try:
            set_daemons(scheduler=None, worker=None)

            assert handlers._DIGEST_SCHEDULER is None
            assert handlers._LLM_WORKER is None
        finally:
            set_daemons(scheduler=orig_scheduler, worker=orig_worker)
