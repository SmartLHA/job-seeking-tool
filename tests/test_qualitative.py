from __future__ import annotations

import json
from pathlib import Path

from src.job_hunt_index import claim_qualitative_assessment, finish_qualitative_assessment, open_db
from src.job_hunt_models import CandidateProfile, Skill
from src.job_hunt_qualitative import (
    QualitativeValidationFailure,
    derive_base_grade,
    derive_grade,
    build_qualitative_prompt,
    parse_and_validate,
    quote_in_text,
)


JD = "Lead stakeholder workshops, process mapping, and UAT for a hybrid London team."


def _valid_payload() -> dict:
    return {
        "dimensions": {
            "seniority_fit": {
                "score": 4,
                "evidence": ["Lead stakeholder workshops"],
                "reasoning": "The posting asks for lead-level workshop ownership.",
            },
            "culture_signals": {
                "score": 3,
                "evidence": ["hybrid London team"],
                "reasoning": "There is limited culture evidence beyond working pattern.",
            },
            "red_flags": {
                "score": 5,
                "evidence": ["process mapping"],
                "reasoning": "No material red flags are visible in the supplied text.",
            },
            "role_archetype_alignment": {
                "score": 5,
                "evidence": ["process mapping, and UAT"],
                "reasoning": "The BA activities align strongly with target BA roles.",
            },
        },
        "posting_quality": {"tier": "unknown_caution", "signals": ["Company context is limited."]},
    }


def test_parse_and_validate_accepts_valid_payload() -> None:
    parsed = parse_and_validate(json.dumps(_valid_payload()), JD)
    assert not isinstance(parsed, QualitativeValidationFailure)
    assert parsed["dimensions"]["seniority_fit"]["score"] == 4


def test_parse_and_validate_rejects_non_json() -> None:
    failure = parse_and_validate("not json", JD)
    assert isinstance(failure, QualitativeValidationFailure)
    assert failure.code == "non_json"


def test_parse_and_validate_rejects_missing_dimension() -> None:
    payload = _valid_payload()
    del payload["dimensions"]["red_flags"]
    failure = parse_and_validate(json.dumps(payload), JD)
    assert isinstance(failure, QualitativeValidationFailure)
    assert failure.code == "schema"


def test_parse_and_validate_rejects_out_of_range_score() -> None:
    payload = _valid_payload()
    payload["dimensions"]["seniority_fit"]["score"] = 6
    failure = parse_and_validate(json.dumps(payload), JD)
    assert isinstance(failure, QualitativeValidationFailure)
    assert failure.code == "schema"


def test_parse_and_validate_rejects_fabricated_quote() -> None:
    payload = _valid_payload()
    payload["dimensions"]["culture_signals"]["evidence"] = ["free lunch and unlimited holidays"]
    failure = parse_and_validate(json.dumps(payload), JD)
    assert isinstance(failure, QualitativeValidationFailure)
    assert failure.code == "fabricated_quote"


def test_quote_normalisation_matches_case_whitespace_and_unicode_punctuation() -> None:
    source = "Lead discovery - stakeholder workshops\nand UAT."
    assert quote_in_text("lead discovery – stakeholder workshops and uat", source)
    assert not quote_in_text("lead discovery and product ownership", source)


def test_archetype_fallback_prompt_and_validation() -> None:
    profile = CandidateProfile(candidate_id="c1", target_roles=[], skills=[Skill("UAT")])
    prompt = build_qualitative_prompt(JD, profile)
    assert "candidate target_roles are missing; alignment was not guessed" in prompt
    assert "master_cv" not in prompt.casefold()

    payload = _valid_payload()
    payload["dimensions"]["role_archetype_alignment"] = {
        "tier": "unknown",
        "warning": "candidate target_roles are missing; alignment was not guessed",
    }
    parsed = parse_and_validate(json.dumps(payload), JD, allow_unknown_archetype=True)
    assert not isinstance(parsed, QualitativeValidationFailure)
    assert parsed["dimensions"]["role_archetype_alignment"]["tier"] == "unknown"


def test_unknown_archetype_rejected_when_target_roles_present() -> None:
    payload = _valid_payload()
    payload["dimensions"]["role_archetype_alignment"] = {
        "tier": "unknown",
        "warning": "candidate target_roles are missing; alignment was not guessed",
    }

    failure = parse_and_validate(json.dumps(payload), JD, allow_unknown_archetype=False)

    assert isinstance(failure, QualitativeValidationFailure)
    assert failure.code == "schema"
    assert "cannot be unknown" in failure.message


def test_migration_idempotency_open_db_twice(tmp_path: Path) -> None:
    db_path = tmp_path / "job_hunt_index.db"
    open_db(db_path).close()
    conn = open_db(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(qualitative_index)")}
    finally:
        conn.close()
    assert {"job_ref", "status", "legitimacy_tier", "prompt_version", "created_at"}.issubset(cols)


def test_qualitative_claim_is_compare_and_swap(tmp_path: Path) -> None:
    db_path = tmp_path / "job_hunt_index.db"
    first = claim_qualitative_assessment(db_path, "job-1", now="2026-07-08T10:00:00")
    second = claim_qualitative_assessment(db_path, "job-1", now="2026-07-08T10:00:01")
    assert first["claimed"] is True
    assert second["claimed"] is False
    assert second["row"]["status"] == "running"

    finish_qualitative_assessment(db_path, "job-1", status="done", legitimacy_tier="unknown_caution")
    third = claim_qualitative_assessment(db_path, "job-1", now="2026-07-08T10:00:02")
    assert third["claimed"] is False
    forced = claim_qualitative_assessment(db_path, "job-1", now="2026-07-08T10:00:03", force=True)
    assert forced["claimed"] is True


def test_base_grade_boundaries_are_nested_inside_decision_bands() -> None:
    assert derive_base_grade(80) == "A"
    assert derive_base_grade(79.9) == "B"
    assert derive_base_grade(72) == "B"
    assert derive_base_grade(71.99) == "C"
    assert derive_base_grade(65) == "C"
    assert derive_base_grade(64.99) == "D"
    assert derive_base_grade(50) == "D"
    assert derive_base_grade(49.99) == "F"


def test_culture_contradiction_caps_high_base_grade_at_c() -> None:
    assessment = _valid_payload()
    assessment["dimensions"]["culture_signals"]["score"] = 2
    assessment["dimensions"]["culture_signals"]["evidence_contradicts_requirements"] = True

    grade = derive_grade(85, assessment)

    assert grade["base_grade"] == "A"
    assert grade["capped_grade"] == "C"
    assert grade["display_grade"] == "C"
    assert grade["cap_reason"] == "culture evidence contradicts requirements"
    assert grade["is_capped"] is True


def test_red_flags_score_caps_high_base_grade_at_c() -> None:
    assessment = _valid_payload()
    assessment["dimensions"]["red_flags"]["score"] = 2

    grade = derive_grade(85, assessment)

    assert grade["base_grade"] == "A"
    assert grade["capped_grade"] == "C"
    assert grade["cap_reason"] == "red flags score indicates material risk"


def test_decision_cap_blocker_skip_caps_a_score_at_f() -> None:
    grade = derive_grade(
        85,
        _valid_payload(),
        effective_decision="skip",
        has_blockers=True,
        decision_reason="Skipped because blocker rules were triggered: Salary below floor",
    )

    assert grade["base_grade"] == "A"
    assert grade["capped_grade"] == "F"
    assert grade["display_grade"] == "F"
    assert "hard blocker" in grade["cap_reason"]
    assert "Salary below floor" in grade["cap_reason"]


def test_decision_cap_low_confidence_review_caps_a_score_at_b() -> None:
    grade = derive_grade(85, _valid_payload(), effective_decision="review", confidence="low")

    assert grade["base_grade"] == "A"
    assert grade["capped_grade"] == "B"
    assert grade["display_grade"] == "B"
    assert grade["cap_reason"] == "low confidence - needs review"


def test_decision_cap_apply_leaves_a_score_unchanged() -> None:
    grade = derive_grade(85, _valid_payload(), effective_decision="apply", confidence="high")

    assert grade["base_grade"] == "A"
    assert grade["capped_grade"] == "A"
    assert grade["display_grade"] == "A"
    assert grade["cap_reason"] is None
    assert grade["is_capped"] is False


def test_decision_and_culture_caps_use_lower_letter() -> None:
    assessment = _valid_payload()
    assessment["dimensions"]["culture_signals"]["score"] = 2
    assessment["dimensions"]["culture_signals"]["evidence_contradicts_requirements"] = True

    grade = derive_grade(85, assessment, effective_decision="review", confidence="low")

    assert grade["base_grade"] == "A"
    assert grade["capped_grade"] == "C"
    assert grade["display_grade"] == "C"
    assert grade["cap_reason"] == "culture evidence contradicts requirements"


def test_warning_triggers_for_high_base_grade_and_low_culture_only() -> None:
    assessment = _valid_payload()
    assessment["dimensions"]["culture_signals"]["score"] = 2

    assert derive_grade(80, assessment)["warning"] == (
        "High technical fit, unconfirmed/poor culture fit - verify before applying."
    )
    assert derive_grade(72, assessment)["warning"] == (
        "High technical fit, unconfirmed/poor culture fit - verify before applying."
    )
    assert derive_grade(71.99, assessment)["warning"] is None
