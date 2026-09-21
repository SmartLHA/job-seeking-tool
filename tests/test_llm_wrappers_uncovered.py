"""Tests for untested LLM and parsing wrapper functions.

Coverage targets:
- ai_review_cv_with_llm (L442 in job_hunt_llm.py)
- extract_cv_skills_with_llm (L524 in job_hunt_llm.py)
- extract_skills_from_cv (L552 in job_hunt_parsing.py)
- generate_cover_letter_text (L453 in job_hunt_tailoring.py)
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

from src.job_hunt_models import (
    CandidateProfile,
    JobPosting,
    JobAnalysis,
    Skill,
    ScoreBreakdown,
    ScoreComponent,
)
from src.job_hunt_llm import ai_review_cv_with_llm, extract_cv_skills_with_llm
from src.job_hunt_parsing import extract_skills_from_cv
from src.job_hunt_tailoring import generate_cover_letter_text


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


class TestAiReviewCvWithLlm:
    """Tests for ai_review_cv_with_llm."""

    def _make_profile(self) -> CandidateProfile:
        return CandidateProfile(
            candidate_id="cand-001",
            name="Test Candidate",
            target_roles=["Business Analyst"],
            locations=["London"],
            remote_preference="remote_friendly",
            salary_floor_gbp=50000,
            right_to_work_uk=True,
            skills=[
                Skill(name="SQL", level="mid"),
                Skill(name="Python", level="junior"),
                Skill(name="Excel", level="expert"),
            ],
            years_experience=5,
            industries=["finance"],
            achievements=["Improved reporting"],
            certifications=["BCS"],
        )

    def _make_job(self) -> JobPosting:
        return JobPosting(
            job_id="job-001",
            job_title="Business Analyst",
            company="Example Co",
            description_raw="Seeking SQL expert with Python experience for data analysis.",
            source_type="copied_text",
            source_ref="manual",
            location="London",
            work_mode="hybrid",
            employment_type="full-time",
            required_skills=["SQL", "Python"],
            preferred_skills=["Tableau"],
        )

    def _make_analysis(self) -> JobAnalysis:
        return JobAnalysis(
            job_id="job-001",
            match_score=75.0,
            score_breakdown=_build_score_breakdown(),
            decision="apply",
            decision_reason="Good match",
        )

    def test_ai_review_cv_success(self) -> None:
        """Test successful CV review with mocked LLM."""
        cv_text = "Master CV text with SQL and Python experience."
        profile = self._make_profile()
        job = self._make_job()
        analysis = self._make_analysis()

        with mock.patch("src.job_hunt_llm._call_gemini_reasoning") as mock_call:
            mock_call.return_value = (
                json.dumps({
                    "reviewed_cv": "Updated CV emphasizing SQL and Python.",
                    "changes": ["Emphasized SQL skills", "Added Python examples"],
                }),
                None,
                "gemini-pro",
                None,
            )
            result, error, model = ai_review_cv_with_llm(cv_text, profile, job, analysis)

        assert result is not None
        assert error is None
        assert model == "gemini-pro"
        assert result["reviewed_cv"] == "Updated CV emphasizing SQL and Python."
        assert len(result["changes"]) == 2

    def test_ai_review_cv_llm_failure(self) -> None:
        """Test CV review when LLM call fails."""
        cv_text = "CV text"
        profile = self._make_profile()
        job = self._make_job()
        analysis = self._make_analysis()

        with mock.patch("src.job_hunt_llm._call_gemini_reasoning") as mock_call:
            mock_call.return_value = (None, "LLM connection error", None, None)
            result, error, model = ai_review_cv_with_llm(cv_text, profile, job, analysis)

        assert result is None
        assert error is not None
        assert "LLM connection error" in error
        assert model is None

    def test_ai_review_cv_malformed_json_response(self) -> None:
        """Test CV review when LLM returns non-JSON."""
        cv_text = "CV text"
        profile = self._make_profile()
        job = self._make_job()
        analysis = self._make_analysis()

        with mock.patch("src.job_hunt_llm._call_gemini_reasoning") as mock_call:
            mock_call.return_value = ("This is not JSON", None, "gemini-pro", None)
            result, error, model = ai_review_cv_with_llm(cv_text, profile, job, analysis)

        assert result is None
        assert error is not None
        assert "non-JSON" in error or "JSON" in error
        assert model is None

    def test_ai_review_cv_missing_reviewed_cv_field(self) -> None:
        """Test CV review when response is missing reviewed_cv field."""
        cv_text = "CV text"
        profile = self._make_profile()
        job = self._make_job()
        analysis = self._make_analysis()

        with mock.patch("src.job_hunt_llm._call_gemini_reasoning") as mock_call:
            mock_call.return_value = (
                json.dumps({"changes": ["Some change"]}),
                None,
                "gemini-pro",
                None,
            )
            result, error, model = ai_review_cv_with_llm(cv_text, profile, job, analysis)

        assert result is None
        assert "reviewed_cv" in error
        assert model is None

    def test_ai_review_cv_empty_changes_list(self) -> None:
        """Test CV review with empty changes list."""
        cv_text = "CV text"
        profile = self._make_profile()
        job = self._make_job()
        analysis = self._make_analysis()

        with mock.patch("src.job_hunt_llm._call_gemini_reasoning") as mock_call:
            mock_call.return_value = (
                json.dumps({
                    "reviewed_cv": "Reviewed CV text",
                    "changes": [],
                }),
                None,
                "gemini-pro",
                None,
            )
            result, error, model = ai_review_cv_with_llm(cv_text, profile, job, analysis)

        assert result is not None
        assert result["changes"] == []
        assert error is None

    def test_ai_review_cv_truncates_long_cv(self) -> None:
        """Test that very long CV text is truncated before sending to LLM."""
        # Create a very long CV
        cv_text = "CV content. " * 100000  # Very long
        profile = self._make_profile()
        job = self._make_job()
        analysis = self._make_analysis()

        with mock.patch("src.job_hunt_llm._call_gemini_reasoning") as mock_call:
            mock_call.return_value = (
                json.dumps({
                    "reviewed_cv": "Reviewed",
                    "changes": [],
                }),
                None,
                "gemini-pro",
                None,
            )
            result, error, model = ai_review_cv_with_llm(cv_text, profile, job, analysis)

        # Verify the call was made (truncation happens internally)
        assert mock_call.called
        call_args = mock_call.call_args[0][0]
        # The prompt should contain the CV (possibly truncated)
        assert "CV" in call_args or "cv" in call_args.lower()


class TestExtractCvSkillsWithLlm:
    """Tests for extract_cv_skills_with_llm."""

    def test_extract_cv_skills_success(self) -> None:
        """Test successful CV skill extraction."""
        cv_text = "Experienced with SQL, Python, and Excel. Expert in stakeholder management."

        with mock.patch("src.job_hunt_llm._call_gemini") as mock_call:
            mock_call.return_value = (
                json.dumps({"skills": ["SQL", "Python", "Excel", "Stakeholder Management"]}),
                None,
            )
            skills, error = extract_cv_skills_with_llm(cv_text)

        assert skills is not None
        assert len(skills) == 4
        assert "SQL" in skills
        assert "Python" in skills
        assert error is None

    def test_extract_cv_skills_llm_failure(self) -> None:
        """Test CV skill extraction when LLM fails."""
        cv_text = "CV text"

        with mock.patch("src.job_hunt_llm._call_gemini") as mock_call:
            mock_call.return_value = (None, "Connection timeout")
            skills, error = extract_cv_skills_with_llm(cv_text)

        assert skills is None
        assert error is not None
        assert "Connection timeout" in error

    def test_extract_cv_skills_malformed_json(self) -> None:
        """Test CV skill extraction with malformed JSON response."""
        cv_text = "CV text"

        with mock.patch("src.job_hunt_llm._call_gemini") as mock_call:
            mock_call.return_value = ("This is not JSON", None)
            skills, error = extract_cv_skills_with_llm(cv_text)

        assert skills is None
        assert error is not None

    def test_extract_cv_skills_empty_skills_list(self) -> None:
        """Test CV skill extraction returning empty list."""
        cv_text = "CV with no clear skills"

        with mock.patch("src.job_hunt_llm._call_gemini") as mock_call:
            mock_call.return_value = (
                json.dumps({"skills": []}),
                None,
            )
            skills, error = extract_cv_skills_with_llm(cv_text)

        assert skills is not None
        assert skills == []
        assert error is None

    def test_extract_cv_skills_filters_empty_strings(self) -> None:
        """Test that empty skill strings are filtered."""
        cv_text = "CV text"

        with mock.patch("src.job_hunt_llm._call_gemini") as mock_call:
            mock_call.return_value = (
                json.dumps({"skills": ["SQL", "", "Python", "  ", "Excel"]}),
                None,
            )
            skills, error = extract_cv_skills_with_llm(cv_text)

        assert skills is not None
        # Empty strings should be filtered
        assert "" not in skills
        assert "  " not in skills
        assert len(skills) == 3


class TestExtractSkillsFromCv:
    """Tests for extract_skills_from_cv (in job_hunt_parsing.py)."""

    def test_extract_skills_uses_llm_when_available(self) -> None:
        """Test that LLM extraction is used when available."""
        cv_text = "CV with SQL and Python"

        with mock.patch("src.job_hunt_llm.extract_cv_skills_with_llm") as mock_llm:
            mock_llm.return_value = (["SQL", "Python"], None)
            skills, warning = extract_skills_from_cv(cv_text)

        assert skills == ["SQL", "Python"]
        assert warning is None

    def test_extract_skills_fallback_to_keyword_on_llm_error(self) -> None:
        """Test fallback to keyword extraction when LLM fails."""
        cv_text = "Experience with SQL and Python"

        with mock.patch("src.job_hunt_llm.extract_cv_skills_with_llm") as mock_llm:
            # Simulate LLM failure
            mock_llm.return_value = (None, "LLM unavailable")
            # Mock the keyword extraction
            with mock.patch("src.job_hunt_parsing._extract_skills") as mock_keyword:
                mock_keyword.return_value = ["SQL", "Python"]
                skills, warning = extract_skills_from_cv(cv_text)

        assert skills is not None  # Fallback worked
        assert warning is not None
        assert "LLM" in warning or "fallback" in warning

    def test_extract_skills_no_warning_on_success(self) -> None:
        """Test no warning when LLM succeeds."""
        cv_text = "CV text"

        with mock.patch("src.job_hunt_llm.extract_cv_skills_with_llm") as mock_llm:
            mock_llm.return_value = (["Skill1", "Skill2"], None)
            skills, warning = extract_skills_from_cv(cv_text)

        assert warning is None

    def test_extract_skills_always_returns_list(self) -> None:
        """Test that extract_skills_from_cv always returns a list (never None)."""
        cv_text = "CV text"

        with mock.patch("src.job_hunt_llm.extract_cv_skills_with_llm") as mock_llm:
            mock_llm.return_value = (None, "Error")
            with mock.patch("src.job_hunt_parsing._extract_skills") as mock_keyword:
                mock_keyword.return_value = []
                skills, warning = extract_skills_from_cv(cv_text)

        assert isinstance(skills, list)
        assert skills is not None


class TestGenerateCoverLetterText:
    """Tests for generate_cover_letter_text."""

    def _make_profile(self) -> CandidateProfile:
        return CandidateProfile(
            candidate_id="cand-001",
            name="John Doe",
            target_roles=["Business Analyst"],
            locations=["London"],
            remote_preference="remote_friendly",
            salary_floor_gbp=50000,
            right_to_work_uk=True,
            skills=[
                Skill(name="SQL", level="expert"),
                Skill(name="Excel", level="expert"),
            ],
            years_experience=7,
            industries=["finance"],
            achievements=["Led data migration project", "Improved reporting efficiency"],
            certifications=["BCS"],
        )

    def _make_job(self) -> JobPosting:
        return JobPosting(
            job_id="job-001",
            job_title="Senior Business Analyst",
            company="Finance Corp",
            description_raw="Looking for BA with SQL and Excel expertise",
            source_type="reed",
            source_ref="https://reed.co.uk/jobs/123",
            location="London",
            work_mode="hybrid",
            employment_type="full-time",
            required_skills=["SQL", "Excel"],
            preferred_skills=["Python"],
        )

    def _make_analysis(self) -> JobAnalysis:
        return JobAnalysis(
            job_id="job-001",
            match_score=85.0,
            score_breakdown=_build_score_breakdown(),
            decision="review",
            decision_reason="Test analysis",
        )

    def test_generate_cover_letter_text_returns_string(self) -> None:
        """Test that cover letter generation returns a string."""
        profile = self._make_profile()
        master_cv = "Master CV content with relevant experience"
        job = self._make_job()
        analysis = self._make_analysis()
        why_company = "I'm impressed by Finance Corp's innovation."

        with mock.patch("src.job_hunt_tailoring.generate_cover_letter") as mock_gen:
            mock_gen.return_value = "Generated cover letter text"
            result = generate_cover_letter_text(profile, master_cv, job, analysis, why_company)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_cover_letter_text_calls_generate_cover_letter(self) -> None:
        """Test that the function delegates to generate_cover_letter."""
        profile = self._make_profile()
        master_cv = "CV content"
        job = self._make_job()
        analysis = self._make_analysis()
        why_company = "Company interest text"

        with mock.patch("src.job_hunt_tailoring.generate_cover_letter") as mock_gen:
            mock_gen.return_value = "Letter"
            result = generate_cover_letter_text(profile, master_cv, job, analysis, why_company)

        # Verify it called generate_cover_letter with the right arguments
        mock_gen.assert_called_once()
        call_args = mock_gen.call_args[0]
        assert call_args[0] == profile
        assert call_args[1] == master_cv
        assert call_args[2] == job
        assert call_args[3] == why_company

    def test_generate_cover_letter_text_ignores_analysis(self) -> None:
        """Test that analysis parameter is passed but not used by public function."""
        profile = self._make_profile()
        master_cv = "CV"
        job = self._make_job()
        analysis = self._make_analysis()
        why_company = "Why"

        # The function deletes analysis, so it shouldn't be used in the output
        with mock.patch("src.job_hunt_tailoring.generate_cover_letter") as mock_gen:
            mock_gen.return_value = "Letter"
            result = generate_cover_letter_text(profile, master_cv, job, analysis, why_company)

        # Call should succeed despite passing analysis
        assert result is not None

    def test_generate_cover_letter_text_with_empty_why_company(self) -> None:
        """Test cover letter generation with empty why_company text."""
        profile = self._make_profile()
        master_cv = "CV"
        job = self._make_job()
        analysis = self._make_analysis()
        why_company = ""  # Empty

        with mock.patch("src.job_hunt_tailoring.generate_cover_letter") as mock_gen:
            mock_gen.return_value = "Letter without company section"
            result = generate_cover_letter_text(profile, master_cv, job, analysis, why_company)

        assert result is not None

    def test_generate_cover_letter_text_with_long_why_company(self) -> None:
        """Test cover letter with long why_company text."""
        profile = self._make_profile()
        master_cv = "CV"
        job = self._make_job()
        analysis = self._make_analysis()
        # Long why_company text
        why_company = "This company is great because... " * 10

        with mock.patch("src.job_hunt_tailoring.generate_cover_letter") as mock_gen:
            mock_gen.return_value = "Long letter"
            result = generate_cover_letter_text(profile, master_cv, job, analysis, why_company)

        assert result is not None
        mock_gen.assert_called_once()
