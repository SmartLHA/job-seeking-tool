"""Reevaluation preserves human choices while rebuilding derived analysis."""
from dataclasses import replace

import pytest

from src.job_hunt_evaluation import evaluate_reviewed_job
from src.job_hunt_orchestrator import run_local_evaluation_flow
from src.job_hunt_scheduler import reevaluate_digest_jobs
from src.job_hunt_storage import load_job_analysis, save_job_analysis
from tests.test_digest_reeval import _profile, _read, _seed, _setup, _SNAPSHOT
from tests.test_orchestrator import _write_profile, _write_reviewed_job


@pytest.fixture(params=["local", "digest"])
def reevaluation(request, tmp_path):
    """Exercise real persistence and scoring in both public pipeline entrypoints."""
    if request.param == "local":
        state = tmp_path / "state"
        kwargs = dict(profile_path=_write_profile(tmp_path),
                      reviewed_job_path=_write_reviewed_job(tmp_path),
                      state_root=state, report_dir=tmp_path / "reports")
        job_id = "job-001"

        def run():
            return run_local_evaluation_flow(**kwargs).analysis

        def assert_index(decision):
            pass  # Local orchestration returns the analysis; UI owns its index update.
    else:
        config, db = _setup(tmp_path)
        state, job_id = config.state_root, "j1"
        job = _seed(config, db, job_id, old_score=0, llm_status=None, seen=True)
        profile = _profile(threshold=0, llm=False)

        def run():
            result = reevaluate_digest_jobs(config=config, profile=profile, db_path=db)
            assert result.jobs_rescored == 1
            assert result.errors == []
            return load_job_analysis(job_id, state)

        def assert_index(decision):
            row = _read(db, job_id)
            assert row["user_decision"] == decision
            assert row["match_score"] == evaluate_reviewed_job(profile, job).match_score

    return run, state, job_id, assert_index


@pytest.mark.parametrize("decision", ["apply", "review", "skip", None])
@pytest.mark.parametrize("note", ["Keep my own reasoning", None])
def test_preserves_manual_fields_and_recomputes_analysis(reevaluation, decision, note):
    run, state, job_id, assert_index = reevaluation
    baseline = run()
    # Stale derived values must not be copied along with the human-owned fields.
    save_job_analysis(replace(
        baseline, user_decision=decision, user_decision_note=note,
        market_snapshot=_SNAPSHOT, match_score=0, decision="skip",
        decision_reason="stale decision", ats_score=1,
    ), state)

    result = run()
    saved = load_job_analysis(job_id, state)
    for analysis in (result, saved):
        assert analysis.user_decision == decision
        assert analysis.user_decision_note == note
        assert analysis.market_snapshot == _SNAPSHOT
        assert analysis.match_score == baseline.match_score
        assert analysis.decision == baseline.decision
        assert analysis.decision_reason == baseline.decision_reason
        assert analysis.ats_score == baseline.ats_score
    assert_index(decision)


def test_missing_previous_analysis_keeps_default_manual_fields(reevaluation):
    run, state, job_id, assert_index = reevaluation
    with pytest.raises(FileNotFoundError):
        load_job_analysis(job_id, state)
    analysis = run()
    assert analysis.user_decision is None
    assert analysis.user_decision_note is None
    assert analysis.market_snapshot is None
    assert_index(None)
