"""Slice 1c (2026-10-19): record which extractor prefilled a job's skills.

Spec: docs/tasks/2026-10-19-scoring-consistency-slice1.md (Slice 1c section).
"""
from __future__ import annotations

import types
from unittest.mock import patch

import pytest

from src.job_hunt_models import SKILL_EXTRACTION_METHODS, JobPosting
from src.job_hunt_reviewed_input import (
    ReviewedInputValidationError,
    reviewed_job_from_dict,
    reviewed_job_to_dict,
)
from src.ui_render import render_input_form, skill_method_note
from src.ui_utils import (
    default_form_values,
    form_values_from_reviewed_job,
    reviewed_job_payload_from_form,
    skill_extraction_method_from_warning,
)


def _payload(**over):
    base = {
        "job_id": "job-1", "job_title": "BA", "company": "Acme",
        "description_raw": "We need SQL.", "source_type": "reed",
        "source_ref": None, "location": None, "work_mode": None,
        "employment_type": None, "required_skills": ["SQL"], "preferred_skills": [],
    }
    base.update(over)
    return base


# --- model and persistence ---------------------------------------------------
def test_methods_constant() -> None:
    assert SKILL_EXTRACTION_METHODS == ("llm", "keyword")


@pytest.mark.parametrize("method", [None, "llm", "keyword"])
def test_job_posting_accepts_known_methods(method) -> None:
    job = reviewed_job_from_dict(_payload(skill_extraction_method=method))
    assert job.skill_extraction_method == method


def test_job_posting_rejects_unknown_method() -> None:
    with pytest.raises(ValueError):
        JobPosting(job_id="j", job_title="t", company="c", description_raw="d",
                   source_type="reed", source_ref=None, location=None, work_mode=None,
                   employment_type=None, skill_extraction_method="gemini")


@pytest.mark.parametrize("raw,expected", [("", None), ("  ", None), ("LLM", "llm"), (" keyword ", "keyword")])
def test_reviewed_input_normalises_method(raw, expected) -> None:
    assert reviewed_job_from_dict(_payload(skill_extraction_method=raw)).skill_extraction_method == expected


def test_reviewed_input_rejects_unknown_method() -> None:
    with pytest.raises(ReviewedInputValidationError):
        reviewed_job_from_dict(_payload(skill_extraction_method="ollama"))


def test_legacy_record_without_field_loads_as_none() -> None:
    assert reviewed_job_from_dict(_payload()).skill_extraction_method is None


def test_round_trip_keeps_method() -> None:
    job = reviewed_job_from_dict(_payload(skill_extraction_method="keyword"))
    again = reviewed_job_from_dict(reviewed_job_to_dict(job))
    assert again.skill_extraction_method == "keyword"


# --- helper and form plumbing --------------------------------------------------
@pytest.mark.parametrize("warning,expected", [(None, "llm"), ("", "llm"), ("Gemini down; used keyword fallback", "keyword")])
def test_method_from_warning(warning, expected) -> None:
    assert skill_extraction_method_from_warning(warning) == expected


def test_default_form_values_has_blank_method() -> None:
    assert default_form_values()["skill_extraction_method"] == ""


def test_form_payload_carries_method() -> None:
    form = {k: "" for k in default_form_values()}
    form.update({"job_id": "j", "job_title": "t", "company": "c", "description_raw": "d",
                 "source_type": "reed", "skill_extraction_method": "llm"})
    assert reviewed_job_payload_from_form(form)["skill_extraction_method"] == "llm"


def test_form_values_from_saved_job_carry_method() -> None:
    job = reviewed_job_from_dict(_payload(skill_extraction_method="keyword"))
    assert form_values_from_reviewed_job(job)["skill_extraction_method"] == "keyword"


def test_evaluate_form_always_has_hidden_method_field() -> None:
    html = render_input_form(default_form_values())
    assert 'name="skill_extraction_method"' in html
    values = default_form_values() | {"skill_extraction_method": "llm"}
    assert 'name="skill_extraction_method" value="llm"' in render_input_form(values)


def test_add_job_form_has_hidden_method_field() -> None:
    from src.ui_render import _render_add_job_form_fields
    assert 'name="skill_extraction_method"' in _render_add_job_form_fields(default_form_values())


# --- job page note -----------------------------------------------------------------
@pytest.mark.parametrize("method,text", [
    ("llm", "Skills prefilled by Gemini"),
    ("keyword", "Skills prefilled by keyword fallback"),
    (None, "Skills source not recorded"),
])
def test_skill_method_note(method, text) -> None:
    assert text in skill_method_note(method)


# --- writers: where extraction actually runs -----------------------------------------
@pytest.mark.parametrize("warning,expected", [(None, "llm"), ("Gemini rate limited", "keyword")])
def test_linkedin_select_records_method(warning, expected) -> None:
    import src.job_sources.linkedin_source as li
    form = {"source": "linkedin", "source_job_id": "12345", "title": "Business Analyst",
            "company": "Acme Ltd", "location": "London", "work_mode": "remote",
            "employment_type": "permanent", "url": "https://www.linkedin.com/jobs/view/12345/",
            "description_raw": "We need a BA with SQL skills.", "salary_min_gbp": "", "salary_max_gbp": ""}
    with patch("src.job_sources.linkedin_source.extract_skills_from_text",
               return_value=(["SQL"], [], warning)):
        values = li.select_handler(form, config=None)
    assert values["skill_extraction_method"] == expected


def test_paste_prefill_records_keyword() -> None:
    from src.ui_handlers import handle_prefill
    sent = {}
    responder = types.SimpleNamespace(send_json=lambda payload, status=None: sent.update(payload))
    req = types.SimpleNamespace(form={"prefill_mode": "paste",
                                      "job_text": "Job title: BA\nCompany: Acme\nWe need SQL and Excel."})
    handle_prefill(req, None, responder)
    assert sent["ok"] is True
    assert sent["values"]["skill_extraction_method"] == "keyword"


@pytest.mark.parametrize("warning,expected", [(None, "llm"), ("fallback", "keyword")])
def test_digest_pipeline_records_method(tmp_path, monkeypatch, warning, expected) -> None:
    import src.job_hunt_scheduler as scheduler
    from src.job_hunt_index import open_db
    from src.job_hunt_profile import candidate_profile_from_dict
    from src.job_hunt_saved_searches import SavedSearch
    from src.job_hunt_storage import ensure_storage_layout, load_reviewed_job
    from src.job_sources.source_registry import JobSource, register

    monkeypatch.setattr(scheduler, "extract_skills_from_text", lambda text: (["sql"], [], warning))
    ensure_storage_layout(tmp_path)
    db = tmp_path / "job_hunt_index.db"
    open_db(db).close()
    result = {"source": "stub1c", "source_job_id": "77", "title": "Data Analyst", "company": "Acme",
              "location": "London", "description_raw": "We need sql.", "salary_min_gbp": "",
              "salary_max_gbp": "", "url": "https://acme/jobs/77", "work_mode": "hybrid",
              "employment_type": "permanent"}
    register(JobSource(
        source_id="stub1c", display_name="Stub 1c", is_available=lambda: True,
        normalize_search_params=lambda p: dict(p), search_handler=lambda params: [dict(result)],
        select_handler=lambda form, config: {}, render_search_form=lambda values, enabled: "",
        render_results=lambda results, error, nonce, more_url=None: "",
    ))
    profile = candidate_profile_from_dict({"candidate_id": "cand-001", "skills": ["sql"],
                                           "target_roles": ["Data Analyst"], "locations": ["London"],
                                           "digest_threshold": 0})
    config = types.SimpleNamespace(state_root=tmp_path, profile_path=tmp_path / "p.json")
    search = SavedSearch("s1c", "test", "stub1c", {}, True, "2026-10-19T00:00:00", None, 0)
    r = scheduler.run_digest_pipeline(config=config, saved_searches=[search], profile=profile, db_path=db)
    assert r.jobs_new == 1, r.errors
    assert load_reviewed_job("stub1c-77", tmp_path).skill_extraction_method == expected
