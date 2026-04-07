from __future__ import annotations

import json
from pathlib import Path

from src.evaluation import evaluate_reviewed_job
from src.models import Blocker, CandidateProfile
from src.outcomes import create_outcome_record, update_outcome
from src.profile import load_candidate_profile, resolve_master_cv_path, save_candidate_profile, save_master_cv
from src.reporting import (
    build_evaluated_job_report_row,
    export_report_csv,
    export_report_json,
    summarise_report_rows,
)
from src.reviewed_input import reviewed_job_from_dict
from src.storage import (
    load_application_outcome,
    load_job_analysis,
    load_raw_input,
    load_reviewed_job,
    save_application_outcome,
    save_job_analysis,
    save_raw_input,
    save_reviewed_job,
)


def build_profile() -> CandidateProfile:
    return CandidateProfile(
        candidate_id="cand-001",
        name="Mic",
        target_roles=["Business Analyst", "Data Analyst"],
        locations=["London", "Manchester"],
        remote_preference="remote_friendly",
        salary_floor_gbp=50000,
        right_to_work_uk=True,
        skills=[
            "Stakeholder Management",
            "Process Mapping",
            "SQL",
            "Agile",
            "Requirements Gathering",
        ],
        years_experience=5,
        industries=["finance", "technology"],
        achievements=["Improved reporting workflow"],
        certifications=["BCS Foundation"],
        master_cv_ref="docs/master_cv.md",
    )


def build_reviewed_job_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "job_id": "job-001",
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
    payload.update(overrides)
    return payload


def test_happy_path_end_to_end_flow_from_profile_to_reporting_and_outcome(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile" / "candidate_profile.json"
    cv_path = tmp_path / "profile" / "docs" / "master_cv.md"
    state_root = tmp_path / "state"
    report_json_path = tmp_path / "reports" / "report.json"
    report_csv_path = tmp_path / "reports" / "report.csv"

    profile = build_profile()
    save_master_cv("# Master CV\n\nBusiness analysis experience.", cv_path)
    save_candidate_profile(profile, profile_path)

    loaded_profile = load_candidate_profile(profile_path)
    assert resolve_master_cv_path(loaded_profile, profile_path) == cv_path.resolve()

    raw_payload = {
        "source_type": "copied_text",
        "source_ref": "manual-note-001",
        "payload": "Raw copied job description",
    }
    save_raw_input(raw_payload, "raw-job-001", state_root)

    reviewed_job = reviewed_job_from_dict(build_reviewed_job_payload())
    save_reviewed_job(reviewed_job, state_root)

    analysis = evaluate_reviewed_job(loaded_profile, reviewed_job)
    save_job_analysis(analysis, state_root)

    outcome = update_outcome(
        create_outcome_record(reviewed_job.job_id, updated_at="2026-04-04T20:40:00Z"),
        status="applied",
        updated_at="2026-04-05T09:15:00Z",
        notes="Submitted tailored CV",
    )
    save_application_outcome(outcome, state_root)

    stored_raw = load_raw_input("raw-job-001", state_root)
    stored_job = load_reviewed_job(reviewed_job.job_id, state_root)
    stored_analysis = load_job_analysis(reviewed_job.job_id, state_root)
    stored_outcome = load_application_outcome(reviewed_job.job_id, state_root)

    row = build_evaluated_job_report_row(stored_job, stored_analysis, stored_outcome)
    summary = summarise_report_rows([row])
    export_report_json([row], report_json_path)
    export_report_csv([row], report_csv_path)

    assert stored_raw == raw_payload
    assert stored_job == reviewed_job
    assert stored_analysis.job_id == reviewed_job.job_id
    assert stored_analysis.decision == "apply"
    assert stored_analysis.confidence == "high"
    assert stored_analysis.tailoring_ready is True
    assert stored_outcome.status == "applied"
    assert row.outcome_status == "applied"
    assert summary.total_jobs == 1
    assert summary.decision_counts == {"apply": 1}
    assert summary.outcome_counts == {"applied": 1}

    exported_json = json.loads(report_json_path.read_text(encoding="utf-8"))
    assert exported_json["rows"][0]["job_id"] == reviewed_job.job_id
    assert exported_json["rows"][0]["decision"] == "apply"
    assert report_csv_path.read_text(encoding="utf-8").splitlines()[1].startswith("job-001,")


def test_blocker_override_flow_keeps_storage_layers_separate(tmp_path: Path) -> None:
    profile = build_profile()
    reviewed_job = reviewed_job_from_dict(build_reviewed_job_payload(job_id="job-blocked"))

    analysis = evaluate_reviewed_job(
        profile,
        reviewed_job,
        blockers=[
            Blocker(
                code="work_authorization",
                label="Work authorization",
                reason="Sponsorship is unavailable",
                severity="critical",
            )
        ],
    )

    save_reviewed_job(reviewed_job, tmp_path)
    save_job_analysis(analysis, tmp_path)

    stored_job = load_reviewed_job("job-blocked", tmp_path)
    stored_analysis = load_job_analysis("job-blocked", tmp_path)

    assert stored_job.job_id == "job-blocked"
    assert stored_analysis.job_id == "job-blocked"
    assert stored_analysis.match_score > 0
    assert stored_analysis.decision == "skip"
    assert stored_analysis.blockers[0].code == "work_authorization"
    assert stored_analysis.tailoring_ready is False
    assert (tmp_path / "reviewed_jobs" / "job-blocked.json").exists()
    assert (tmp_path / "analyses" / "job-blocked.json").exists()


def test_sparse_reviewed_job_flow_produces_low_confidence_skip_and_report_without_outcome() -> None:
    profile = build_profile()
    reviewed_job = reviewed_job_from_dict(
        build_reviewed_job_payload(
            job_id="job-sparse",
            required_skills=[],
            required_years_experience=None,
            location=None,
            work_mode="unknown",
            salary_min_gbp=None,
            salary_max_gbp=None,
            domain=None,
        )
    )

    analysis = evaluate_reviewed_job(profile, reviewed_job)
    row = build_evaluated_job_report_row(reviewed_job, analysis)
    summary = summarise_report_rows([row])

    assert analysis.confidence == "low"
    assert analysis.decision == "skip"
    assert analysis.match_score == 51.5
    assert row.outcome_status is None
    assert summary.decision_counts == {"skip": 1}
    assert summary.outcome_counts == {}
    assert any("required skills" in note for note in analysis.score_breakdown.notes)


def test_required_skill_gap_flow_stays_review_and_not_tailoring_ready() -> None:
    profile = build_profile()
    reviewed_job = reviewed_job_from_dict(
        build_reviewed_job_payload(
            job_id="job-gap",
            required_skills=["stakeholder management", "Power BI"],
            preferred_skills=["SQL"],
        )
    )

    analysis = evaluate_reviewed_job(profile, reviewed_job)
    row = build_evaluated_job_report_row(reviewed_job, analysis)

    assert analysis.match_score == 82.5
    assert analysis.decision == "review"
    assert analysis.tailoring_ready is False
    assert analysis.missing_required_skills == ["Power BI"]
    assert any(flag.code == "missing-required-skills" for flag in analysis.risk_flags)
    assert row.missing_required_skills == ["Power BI"]
    assert row.outcome_status is None


def test_storage_round_trip_supports_reporting_with_and_without_outcomes_for_multiple_jobs(
    tmp_path: Path,
) -> None:
    profile = build_profile()

    apply_job = reviewed_job_from_dict(build_reviewed_job_payload(job_id="job-apply"))
    review_job = reviewed_job_from_dict(
        build_reviewed_job_payload(
            job_id="job-review",
            required_skills=["stakeholder management", "Power BI"],
            preferred_skills=[],
        )
    )

    apply_analysis = evaluate_reviewed_job(profile, apply_job)
    review_analysis = evaluate_reviewed_job(profile, review_job)

    save_reviewed_job(apply_job, tmp_path)
    save_reviewed_job(review_job, tmp_path)
    save_job_analysis(apply_analysis, tmp_path)
    save_job_analysis(review_analysis, tmp_path)

    apply_outcome = update_outcome(
        update_outcome(
            create_outcome_record("job-apply", updated_at="2026-04-04T20:40:00Z"),
            status="applied",
            updated_at="2026-04-05T09:15:00Z",
            notes="Submitted tailored CV",
        ),
        status="interview",
        updated_at="2026-04-08T08:30:00Z",
        notes="First-round interview booked",
    )
    save_application_outcome(apply_outcome, tmp_path)

    rows = [
        build_evaluated_job_report_row(
            load_reviewed_job("job-apply", tmp_path),
            load_job_analysis("job-apply", tmp_path),
            load_application_outcome("job-apply", tmp_path),
        ),
        build_evaluated_job_report_row(
            load_reviewed_job("job-review", tmp_path),
            load_job_analysis("job-review", tmp_path),
        ),
    ]

    summary = summarise_report_rows(rows)

    assert [row.job_id for row in rows] == ["job-apply", "job-review"]
    assert rows[0].outcome_status == "interview"
    assert rows[1].outcome_status is None
    assert summary.total_jobs == 2
    assert summary.decision_counts == {"apply": 1, "review": 1}
    assert summary.outcome_counts == {"interview": 1}
