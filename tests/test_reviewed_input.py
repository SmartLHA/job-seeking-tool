from src.models import JobPosting
from src.reviewed_input import (
    ReviewedInputValidationError,
    reviewed_job_from_dict,
    reviewed_job_to_dict,
)


def test_reviewed_job_from_dict_builds_structured_job_with_explicit_unknowns() -> None:
    job = reviewed_job_from_dict(
        {
            "job_id": " reviewed-001 ",
            "job_title": " Business Analyst ",
            "company": " Example Co ",
            "description_raw": " Need stakeholder management and process mapping. ",
            "source_type": " copied_text ",
            "source_ref": "   ",
            "location": "   ",
            "work_mode": "unknown",
            "employment_type": "",
            "required_skills": [" stakeholder management ", "Process Mapping", "process mapping"],
            "preferred_skills": None,
            "required_years_experience": 3,
            "nice_to_have_years_experience": None,
            "domain": "",
            "notes": "  Manual review completed.  ",
            "salary_min_gbp": None,
            "salary_max_gbp": 55000,
        }
    )

    assert isinstance(job, JobPosting)
    assert job.job_id == "reviewed-001"
    assert job.job_title == "Business Analyst"
    assert job.company == "Example Co"
    assert job.source_ref is None
    assert job.location is None
    assert job.work_mode == "unknown"
    assert job.employment_type is None
    assert job.required_skills == ["stakeholder management", "Process Mapping"]
    assert job.preferred_skills == []
    assert job.required_years_experience == 3.0
    assert job.domain is None
    assert job.notes == "Manual review completed."


def test_reviewed_job_from_dict_rejects_unknown_fields() -> None:
    try:
        reviewed_job_from_dict(
            {
                "job_id": "reviewed-001",
                "job_title": "Business Analyst",
                "company": "Example Co",
                "description_raw": "Description",
                "source_type": "copied_text",
                "bonus_field": "not allowed",
            }
        )
    except ReviewedInputValidationError as exc:
        assert "unknown fields" in str(exc)
    else:
        raise AssertionError("Expected unknown field to raise ReviewedInputValidationError")


def test_reviewed_job_from_dict_requires_non_empty_required_text_fields() -> None:
    try:
        reviewed_job_from_dict(
            {
                "job_id": "reviewed-001",
                "job_title": " ",
                "company": "Example Co",
                "description_raw": "Description",
                "source_type": "copied_text",
            }
        )
    except ReviewedInputValidationError as exc:
        assert "job_title" in str(exc)
    else:
        raise AssertionError("Expected empty job_title to raise ReviewedInputValidationError")


def test_reviewed_job_to_dict_round_trips_reviewed_structured_data() -> None:
    original = reviewed_job_from_dict(
        {
            "job_id": "reviewed-002",
            "job_title": "Data Analyst",
            "company": "Insight Ltd",
            "description_raw": "SQL and reporting role.",
            "source_type": "url",
            "source_ref": "https://example.test/jobs/2",
            "location": "London",
            "work_mode": "hybrid",
            "employment_type": "full-time",
            "required_skills": ["SQL", "reporting"],
            "preferred_skills": ["Power BI"],
            "required_years_experience": 2,
            "nice_to_have_years_experience": 4,
            "domain": "technology",
            "notes": None,
            "salary_min_gbp": 45000,
            "salary_max_gbp": 50000,
        }
    )

    payload = reviewed_job_to_dict(original)
    rebuilt = reviewed_job_from_dict(payload)

    assert rebuilt == original
