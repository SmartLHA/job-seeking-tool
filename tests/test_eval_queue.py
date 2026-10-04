from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    requests_stub = types.ModuleType("requests")
    requests_stub.exceptions = types.SimpleNamespace(ConnectionError=Exception, Timeout=TimeoutError)
    requests_stub.post = lambda *args, **kwargs: None
    sys.modules["requests"] = requests_stub

from src.job_hunt_index import (
    cancel_eval_batch,
    claim_eval_queue_row,
    enqueue_eval_batch,
    finish_eval_queue_row,
    get_eval_batch,
    get_qualitative_index_row,
    incr_rpd_counter,
    open_db,
    reset_stale_eval_queue_running,
    upsert_job,
)
from src.job_hunt_models import CandidateProfile, JobAnalysis, JobPosting, ScoreBreakdown, ScoreComponent, Skill
from src.job_hunt_scheduler import process_eval_queue_once, rpd_date_key
from src.job_hunt_storage import load_qualitative_assessment, save_job_analysis, save_reviewed_job
from src.ui_handlers import handle_batch_assess, handle_cancel_batch, handle_get_batch
from src.ui_state import UIServerConfig


class _Responder:
    body = ""
    status = None
    redirect_location = None

    def send_html(self, body, *, status=None):
        self.body = body
        self.status = status

    def redirect(self, location):
        self.redirect_location = location


def _config(tmp_path: Path) -> UIServerConfig:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps({"candidate_id": "c1", "target_roles": ["Business Analyst"]}), encoding="utf-8")
    return UIServerConfig(profile_path=profile_path, state_root=tmp_path / "state", report_dir=tmp_path / "reports")


def _profile(*, rpd: int = 200) -> CandidateProfile:
    return CandidateProfile(
        candidate_id="c1",
        target_roles=["Business Analyst"],
        skills=[Skill("SQL"), Skill("Stakeholder Management")],
        digest_llm_rpd=rpd,
    )


def _analysis(job_id: str, decision: str = "review") -> JobAnalysis:
    comp = ScoreComponent(80, "ok")
    return JobAnalysis(
        job_id=job_id,
        match_score=74,
        score_breakdown=ScoreBreakdown(comp, comp, comp, comp, comp, comp),
        decision=decision,
        decision_reason="Needs review",
        confidence="high",
    )


def _save_job(config: UIServerConfig, job_id: str, *, decision: str = "review") -> None:
    job = JobPosting(
        job_id=job_id,
        job_title="Business Analyst",
        company="Example",
        description_raw="Looking for stakeholder management and SQL.",
        source_type="copied_text",
        source_ref="manual",
        location="London",
        work_mode="hybrid",
        employment_type="full-time",
        required_skills=["SQL"],
        source_job_id=job_id,
    )
    save_reviewed_job(job, config.state_root)
    save_job_analysis(_analysis(job_id, decision), config.state_root)
    upsert_job(config.state_root / "job_hunt_index.db", {
        "job_id": job_id,
        "job_title": job.job_title,
        "company": job.company,
        "location": job.location,
        "source": job.source_type,
        "source_job_id": job.source_job_id,
        "apply_url": job.source_ref,
        "match_score": 74,
        "decision": decision,
        "status": "not_applied",
        "updated_at": "2026-07-09",
    })


def _llm_payload() -> str:
    return json.dumps({
        "dimensions": {
            "seniority_fit": {"score": 4, "evidence": ["Looking for stakeholder management"], "reasoning": "Strong BA signal."},
            "culture_signals": {"score": 3, "evidence": ["Looking for stakeholder management and SQL"], "reasoning": "Limited culture evidence."},
            "red_flags": {"score": 5, "evidence": ["SQL"], "reasoning": "No material red flags."},
            "role_archetype_alignment": {"score": 5, "evidence": ["stakeholder management and SQL"], "reasoning": "Aligned to BA work."},
        },
        "posting_quality": {"tier": "unknown_caution", "signals": ["Short JD."]},
    })


def test_eval_queue_state_machine_and_migration_idempotency(tmp_path: Path) -> None:
    db_path = tmp_path / "job_hunt_index.db"
    open_db(db_path).close()
    open_db(db_path).close()
    batch_id = enqueue_eval_batch(db_path, ["job-1", "job-2"], now="2026-07-09T10:00:00")
    claimed = claim_eval_queue_row(db_path, now="2026-07-09T10:00:01")
    assert claimed and claimed["job_ref"] == "job-1"
    assert finish_eval_queue_row(db_path, claimed["id"], claimed["claim_token"], status="done", now="2026-07-09T10:00:02")
    assert cancel_eval_batch(db_path, batch_id, now="2026-07-09T10:00:03") == 1
    assert [r["status"] for r in get_eval_batch(db_path, batch_id)] == ["done", "cancelled"]
    with pytest.raises(ValueError, match="duplicate"):
        enqueue_eval_batch(db_path, ["job-1", "job-1"], now="2026-07-09T10:00:00")


def test_stale_running_reset_each_cycle(tmp_path: Path) -> None:
    db_path = tmp_path / "job_hunt_index.db"
    batch_id = enqueue_eval_batch(db_path, ["job-1"], now="2026-07-09T10:00:00")
    claim_eval_queue_row(db_path, now="2026-07-09T10:00:00")
    reset = reset_stale_eval_queue_running(
        db_path,
        now=datetime.fromisoformat("2026-07-09T10:45:00"),
        older_than_minutes=30,
    )
    assert reset == 1
    assert get_eval_batch(db_path, batch_id)[0]["status"] == "pending"
    row = claim_eval_queue_row(db_path, now="2026-07-09T10:46:00")
    assert row and row["job_ref"] == "job-1"
    assert row["retries"] == 1


def test_worker_processes_pending_after_reinstantiation(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    _save_job(config, "job-1")
    db_path = config.state_root / "job_hunt_index.db"
    enqueue_eval_batch(db_path, ["job-1"], now="2026-07-09T10:00:00")
    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", lambda prompt, *, before_attempt=None: (_llm_payload(), None, "gemini-test", False))

    first = process_eval_queue_once(config=config, profile=_profile(), db_path=db_path, sleep=lambda _s: None)
    second = process_eval_queue_once(config=config, profile=_profile(), db_path=db_path, sleep=lambda _s: None)

    assert first.processed == 1
    assert second.processed == 0
    assert load_qualitative_assessment("job-1", config.state_root)["model"] == "gemini-test"


def test_forced_done_row_is_reassessed_from_queue(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    _save_job(config, "job-1")
    db_path = config.state_root / "job_hunt_index.db"
    calls: list[str] = []
    models = ["gemini-old", "gemini-new"]

    def fake_reasoning(prompt, *, before_attempt=None):
        calls.append(prompt)
        return _llm_payload(), None, models.pop(0), False

    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", fake_reasoning)
    first_batch = enqueue_eval_batch(db_path, ["job-1"], now="2026-07-09T10:00:00")
    first = process_eval_queue_once(config=config, profile=_profile(), db_path=db_path, sleep=lambda _s: None)
    assert first.processed == 1
    assert get_eval_batch(db_path, first_batch)[0]["status"] == "done"
    assert load_qualitative_assessment("job-1", config.state_root)["model"] == "gemini-old"

    second_batch = enqueue_eval_batch(db_path, ["job-1"], now="2026-07-09T10:01:00", force=True)
    second = process_eval_queue_once(config=config, profile=_profile(), db_path=db_path, sleep=lambda _s: None)

    assert second.processed == 1
    assert len(calls) == 2
    assert get_eval_batch(db_path, second_batch)[0]["status"] == "done"
    assert load_qualitative_assessment("job-1", config.state_root)["model"] == "gemini-new"


def test_quota_exhausted_pauses_batch_without_calling_remaining_rows(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    _save_job(config, "job-1")
    _save_job(config, "job-2")
    db_path = config.state_root / "job_hunt_index.db"
    batch_id = enqueue_eval_batch(db_path, ["job-1", "job-2"], now="2026-07-09T10:00:00")
    incr_rpd_counter(db_path, rpd_date_key())
    calls = []
    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", lambda *a, **k: calls.append("called"))

    result = process_eval_queue_once(config=config, profile=_profile(rpd=1), db_path=db_path, sleep=lambda _s: None)

    assert result.quota_paused is True
    assert calls == []
    rows = get_eval_batch(db_path, batch_id)
    assert [r["status"] for r in rows] == ["pending", "pending"]
    assert [r["retries"] for r in rows] == [0, 0]
    assert "quota" in (rows[0]["error_text"] or "").lower()
    assert get_qualitative_index_row(db_path, "job-1") is None


def test_batch_progress_shows_quota_waiting_note(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    _save_job(config, "job-1")
    db_path = config.state_root / "job_hunt_index.db"
    batch_id = enqueue_eval_batch(db_path, ["job-1"], now="2026-07-09T10:00:00")
    incr_rpd_counter(db_path, rpd_date_key())
    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", lambda *a, **k: None)

    process_eval_queue_once(config=config, profile=_profile(rpd=1), db_path=db_path, sleep=lambda _s: None)
    page = _Responder()
    handle_get_batch(types.SimpleNamespace(path=f"/batch/{batch_id}", form={}, raw_body=b""), config, page, batch_id)

    assert "Waiting on Gemini quota" in page.body


def test_429_backoff_retries_then_caps_fast(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    _save_job(config, "job-1")
    db_path = config.state_root / "job_hunt_index.db"
    batch_id = enqueue_eval_batch(db_path, ["job-1"], now="2026-07-09T10:00:00")
    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", lambda prompt, *, before_attempt=None: (None, "429", None, True))
    sleeps: list[float] = []

    for _ in range(4):
        result = process_eval_queue_once(config=config, profile=_profile(), db_path=db_path, sleep=sleeps.append, backoff_seconds=0.01)
        assert result.requeued == 1
    final = process_eval_queue_once(config=config, profile=_profile(), db_path=db_path, sleep=sleeps.append, backoff_seconds=0.01)

    assert sleeps == [0.01, 0.01, 0.01, 0.01]
    assert final.failed == 1
    assert get_eval_batch(db_path, batch_id)[0]["status"] == "error"


def test_cancel_while_running_honours_final_cancel_check(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    _save_job(config, "job-1")
    _save_job(config, "job-2")
    db_path = config.state_root / "job_hunt_index.db"
    batch_id = enqueue_eval_batch(db_path, ["job-1", "job-2"], now="2026-07-09T10:00:00")

    def fake_reasoning(prompt, *, before_attempt=None):
        cancel_eval_batch(db_path, batch_id, now="2026-07-09T10:00:02")
        return _llm_payload(), None, "gemini-test", False

    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", fake_reasoning)
    result = process_eval_queue_once(config=config, profile=_profile(), db_path=db_path, sleep=lambda _s: None)

    assert result.cancelled == 1
    assert [r["status"] for r in get_eval_batch(db_path, batch_id)] == ["cancelled", "cancelled"]
    with pytest.raises(FileNotFoundError):
        load_qualitative_assessment("job-1", config.state_root)
    assert get_qualitative_index_row(db_path, "job-1")["status"] == "error"


def test_cancel_only_running_row_honours_batch_cancel_intent(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    _save_job(config, "job-1")
    db_path = config.state_root / "job_hunt_index.db"
    batch_id = enqueue_eval_batch(db_path, ["job-1"], now="2026-07-09T10:00:00")

    def fake_reasoning(prompt, *, before_attempt=None):
        assert cancel_eval_batch(db_path, batch_id, now="2026-07-09T10:00:02") == 0
        return _llm_payload(), None, "gemini-test", False

    monkeypatch.setattr("src.job_hunt_llm._call_gemini_reasoning", fake_reasoning)
    result = process_eval_queue_once(config=config, profile=_profile(), db_path=db_path, sleep=lambda _s: None)

    assert result.cancelled == 1
    assert get_eval_batch(db_path, batch_id)[0]["status"] == "cancelled"
    with pytest.raises(FileNotFoundError):
        load_qualitative_assessment("job-1", config.state_root)


def test_batch_routes_enqueue_progress_and_cancel(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_job(config, "job-1")
    req = types.SimpleNamespace(
        raw_body=b"job_id=job-1",
        form={},
        json_body=None,
        path="/jobs/batch-assess",
    )
    responder = _Responder()
    handle_batch_assess(req, config, responder)
    assert responder.redirect_location and responder.redirect_location.startswith("/batch/")
    batch_id = responder.redirect_location.rsplit("/", 1)[-1]

    page = _Responder()
    handle_get_batch(types.SimpleNamespace(path=f"/batch/{batch_id}", form={}, raw_body=b""), config, page, batch_id)
    assert "0</strong> done / <strong>1</strong> total" in page.body
    assert "Cancel affects pending jobs only" in page.body

    cancel = _Responder()
    handle_cancel_batch(types.SimpleNamespace(path=f"/batch/{batch_id}/cancel", form={}, raw_body=b""), config, cancel, batch_id)
    assert cancel.redirect_location == f"/batch/{batch_id}"
    assert get_eval_batch(config.state_root / "job_hunt_index.db", batch_id)[0]["status"] == "cancelled"


@pytest.mark.parametrize('kind', ['429', 'quota'])
def test_cancelled_provider_failure_never_requeues_or_calls_again(tmp_path, monkeypatch, kind):
    from src.job_hunt_index import LLMQuotaExhausted
    from src.job_hunt_llm import RateLimited
    config = _config(tmp_path)
    _save_job(config, 'job-1')
    db = config.state_root / 'job_hunt_index.db'
    batch = enqueue_eval_batch(db, ['job-1'], now='2026-07-09T10:00:00')
    calls, sleeps = [], []
    def provider(prompt, *, before_attempt=None):
        calls.append(prompt)
        cancel_eval_batch(db, batch, now='2026-07-09T10:00:02')
        raise RateLimited('synthetic 429') if kind == '429' else LLMQuotaExhausted('synthetic quota')
    monkeypatch.setattr('src.job_hunt_llm._call_gemini_reasoning', provider)
    first = process_eval_queue_once(config=config, profile=_profile(), db_path=db, sleep=sleeps.append)
    second = process_eval_queue_once(config=config, profile=_profile(), db_path=db, sleep=sleeps.append)
    assert first.cancelled == 1 and first.requeued == 0 and not first.quota_paused
    assert second.processed == second.failed == second.requeued == 0
    assert len(calls) == 1 and sleeps == []
    row = get_eval_batch(db, batch)[0]
    assert row['status'] == 'cancelled' and row['claim_token'] is None
    assert row['retries'] == 0 and row['finished_at']


@pytest.mark.parametrize('operation', ['429', 'quota', 'finish'])
def test_retry_transitions_atomically_prefer_cancel_and_preserve_claim_token(tmp_path, operation):
    from src.job_hunt_index import requeue_eval_queue_row, return_eval_queue_row_to_pending
    db = tmp_path / 'queue.db'
    batch = enqueue_eval_batch(db, ['job-1'], now='2026-07-09T10:00:00')
    row = claim_eval_queue_row(db, now='2026-07-09T10:00:01')
    cancel_eval_batch(db, batch, now='2026-07-09T10:00:02')
    def transition(token):
        if operation == '429':
            return requeue_eval_queue_row(db, row['id'], token, now='2026-07-09T10:00:03', retries=1, error_text='429')
        if operation == 'quota':
            return return_eval_queue_row_to_pending(db, row['id'], token, error_text='quota')
        return finish_eval_queue_row(db, row['id'], token, status='error', now='2026-07-09T10:00:03', retries=5)
    assert transition('invalid-token') is False
    unchanged = get_eval_batch(db, batch)[0]
    assert unchanged['status'] == 'running' and unchanged['claim_token'] == row['claim_token']
    assert transition(row['claim_token']) is True
    final = get_eval_batch(db, batch)[0]
    assert final['status'] == 'cancelled' and final['claim_token'] is None
    assert final['retries'] == 0 and final['error_text'] is None and final['finished_at']
    assert claim_eval_queue_row(db, now='2026-07-09T10:01:00') is None


def test_claim_reconciles_old_pending_cancelled_batch_and_claims_live_batch(tmp_path):
    db = tmp_path / 'queue.db'
    cancelled = enqueue_eval_batch(db, ['old-job'], now='2026-07-09T10:00:00')
    cancel_eval_batch(db, cancelled, now='2026-07-09T10:00:01')
    with open_db(db) as conn:
        conn.execute("UPDATE eval_queue SET status='pending', finished_at=NULL WHERE batch_id=?", (cancelled,))
    live = enqueue_eval_batch(db, ['live-job'], now='2026-07-09T10:02:00')
    row = claim_eval_queue_row(db, now='2026-07-09T10:03:00')
    assert row['batch_id'] == live and row['job_ref'] == 'live-job'
    assert get_eval_batch(db, cancelled)[0]['status'] == 'cancelled'
    assert claim_eval_queue_row(db, now='2026-07-09T10:03:01') is None


@pytest.mark.parametrize('retries', [0, 4])
def test_stale_cancelled_running_never_pending_or_retry_cap_error(tmp_path, retries):
    from src.job_hunt_index import pause_eval_batch_for_quota
    db = tmp_path / 'queue.db'
    batch = enqueue_eval_batch(db, ['job-1'], now='2026-07-09T10:00:00')
    row = claim_eval_queue_row(db, now='2026-07-09T10:00:01')
    with open_db(db) as conn:
        conn.execute('UPDATE eval_queue SET retries=? WHERE id=?', (retries, row['id']))
    cancel_eval_batch(db, batch, now='2026-07-09T10:00:02')
    assert pause_eval_batch_for_quota(db, batch, now='2026-07-09T10:00:03', error_text='quota') == 0
    assert reset_stale_eval_queue_running(db, now=datetime.fromisoformat('2026-07-09T10:45:00')) == 1
    final = get_eval_batch(db, batch)[0]
    assert final['status'] == 'cancelled' and final['retries'] == retries
    assert final['claim_token'] is None and final['finished_at'] and final['error_text'] is None
    assert claim_eval_queue_row(db, now='2026-07-09T10:46:00') is None


def test_non_cancelled_retry_and_quota_return_still_work_with_valid_token(tmp_path):
    from src.job_hunt_index import requeue_eval_queue_row, return_eval_queue_row_to_pending
    db = tmp_path / 'queue.db'
    batch = enqueue_eval_batch(db, ['job-1'], now='2026-07-09T10:00:00')
    row = claim_eval_queue_row(db, now='2026-07-09T10:00:01')
    assert not requeue_eval_queue_row(db, row['id'], 'wrong', now='2026-07-09T10:00:02', retries=1)
    assert requeue_eval_queue_row(db, row['id'], row['claim_token'], now='2026-07-09T10:00:02', retries=1, error_text='429')
    final = get_eval_batch(db, batch)[0]
    assert final['status'] == 'pending' and final['retries'] == 1 and final['error_text'] == '429'
    row = claim_eval_queue_row(db, now='2026-07-09T10:00:03')
    assert not return_eval_queue_row_to_pending(db, row['id'], 'wrong', error_text='quota')
    assert return_eval_queue_row_to_pending(db, row['id'], row['claim_token'], error_text='quota')
    final = get_eval_batch(db, batch)[0]
    assert final['status'] == 'pending' and final['retries'] == 1 and final['finished_at'] is None


def test_cancel_after_claim_before_pipeline_makes_zero_provider_calls(tmp_path, monkeypatch):
    import src.job_hunt_scheduler as scheduler
    config = _config(tmp_path)
    _save_job(config, 'job-1')
    db = config.state_root / 'job_hunt_index.db'
    batch = enqueue_eval_batch(db, ['job-1'], now='2026-07-09T10:00:00')
    original = scheduler.claim_eval_queue_row
    def cancel_after_claim(*args, **kwargs):
        row = original(*args, **kwargs)
        cancel_eval_batch(db, batch, now='2026-07-09T10:00:02')
        return row
    monkeypatch.setattr(scheduler, 'claim_eval_queue_row', cancel_after_claim)
    def forbidden(*args, **kwargs):
        pytest.fail('Provider called after cancellation')
    monkeypatch.setattr('src.job_hunt_llm._call_gemini_reasoning', forbidden)
    result = process_eval_queue_once(config=config, profile=_profile(), db_path=db, sleep=lambda _: None)
    assert result.cancelled == 1 and get_eval_batch(db, batch)[0]['status'] == 'cancelled'


def test_cancelled_validation_retry_does_not_make_second_provider_call(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _save_job(config, 'job-1')
    db = config.state_root / 'job_hunt_index.db'
    batch = enqueue_eval_batch(db, ['job-1'], now='2026-07-09T10:00:00')
    calls = []
    def provider(prompt, *, before_attempt=None):
        calls.append(prompt)
        cancel_eval_batch(db, batch, now='2026-07-09T10:00:02')
        return '{}', None, 'synthetic', False
    monkeypatch.setattr('src.job_hunt_llm._call_gemini_reasoning', provider)
    result = process_eval_queue_once(config=config, profile=_profile(), db_path=db, sleep=lambda _: None)
    assert result.cancelled == 1 and len(calls) == 1
    assert get_eval_batch(db, batch)[0]['status'] == 'cancelled'


def test_actual_provider_fallback_checkpoint_stops_after_first_cancelled_call(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _save_job(config, 'job-1')
    db = config.state_root / 'job_hunt_index.db'
    batch = enqueue_eval_batch(db, ['job-1'], now='2026-07-09T10:00:00')
    calls = []
    monkeypatch.setattr('src.job_hunt_llm._api_key', lambda: 'synthetic-key-no-network')
    def provider(prompt, model, key, **kwargs):
        calls.append(model)
        cancel_eval_batch(db, batch, now='2026-07-09T10:00:02')
        return None, 'synthetic 429', True, 'rate_limited'
    monkeypatch.setattr('src.job_hunt_llm._call_gemini_model', provider)
    first = process_eval_queue_once(config=config, profile=_profile(), db_path=db, sleep=lambda _: None)
    second = process_eval_queue_once(config=config, profile=_profile(), db_path=db, sleep=lambda _: None)
    assert first.cancelled == 1 and second.requeued == 0 and len(calls) == 1
    assert get_eval_batch(db, batch)[0]['status'] == 'cancelled'


@pytest.mark.parametrize('kind', ['429', 'quota'])
def test_cancel_racing_retry_transition_reports_cancelled(tmp_path, monkeypatch, kind):
    import src.job_hunt_scheduler as scheduler
    from src.job_hunt_index import LLMQuotaExhausted
    from src.job_hunt_llm import RateLimited
    config = _config(tmp_path)
    _save_job(config, 'job-1')
    db = config.state_root / 'job_hunt_index.db'
    batch = enqueue_eval_batch(db, ['job-1'], now='2026-07-09T10:00:00')
    name = 'requeue_eval_queue_row' if kind == '429' else 'return_eval_queue_row_to_pending'
    original = getattr(scheduler, name)
    def cancel_before_update(*args, **kwargs):
        cancel_eval_batch(db, batch, now='2026-07-09T10:00:02')
        return original(*args, **kwargs)
    monkeypatch.setattr(scheduler, name, cancel_before_update)
    calls = []
    def provider(*args, **kwargs):
        calls.append('synthetic')
        raise RateLimited('synthetic 429') if kind == '429' else LLMQuotaExhausted('synthetic quota')
    monkeypatch.setattr('src.job_hunt_llm._call_gemini_reasoning', provider)
    sleeps = []
    result = process_eval_queue_once(config=config, profile=_profile(), db_path=db, sleep=sleeps.append)
    assert result.cancelled == 1 and result.requeued == 0 and not result.quota_paused and sleeps == []
    assert get_eval_batch(db, batch)[0]['status'] == 'cancelled'
    process_eval_queue_once(config=config, profile=_profile(), db_path=db, sleep=sleeps.append)
    assert calls == ['synthetic']


def test_pipeline_checkpoint_blocks_provider_after_qualitative_claim(tmp_path, monkeypatch):
    import src.job_hunt_index as index
    config = _config(tmp_path)
    _save_job(config, 'job-1')
    db = config.state_root / 'job_hunt_index.db'
    batch = enqueue_eval_batch(db, ['job-1'], now='2026-07-09T10:00:00')
    original = index.claim_qualitative_assessment
    def cancel_after_qualitative_claim(*args, **kwargs):
        claim = original(*args, **kwargs)
        cancel_eval_batch(db, batch, now='2026-07-09T10:00:02')
        return claim
    monkeypatch.setattr(index, 'claim_qualitative_assessment', cancel_after_qualitative_claim)
    def forbidden(*args, **kwargs):
        pytest.fail('Provider called after qualitative claim cancellation')
    monkeypatch.setattr('src.job_hunt_llm._call_gemini_reasoning', forbidden)
    result = process_eval_queue_once(config=config, profile=_profile(), db_path=db, sleep=lambda _: None)
    assert result.cancelled == 1 and get_eval_batch(db, batch)[0]['status'] == 'cancelled'


def test_cancellation_after_completed_row_does_not_misreport_outcome(tmp_path, monkeypatch):
    import src.job_hunt_scheduler as scheduler
    config = _config(tmp_path)
    _save_job(config, 'job-1')
    db = config.state_root / 'job_hunt_index.db'
    batch = enqueue_eval_batch(db, ['job-1'], now='2026-07-09T10:00:00')
    monkeypatch.setattr('src.job_hunt_llm._call_gemini_reasoning', lambda *a, **k: (_llm_payload(), None, 'synthetic', False))
    original = scheduler.finish_eval_queue_row
    def cancel_after_finish(*args, **kwargs):
        updated = original(*args, **kwargs)
        if kwargs['status'] == 'done':
            cancel_eval_batch(db, batch, now='2026-07-09T10:00:02')
        return updated
    monkeypatch.setattr(scheduler, 'finish_eval_queue_row', cancel_after_finish)
    result = process_eval_queue_once(config=config, profile=_profile(), db_path=db, sleep=lambda _: None)
    assert result.processed == 1 and result.cancelled == 0
    assert get_eval_batch(db, batch)[0]['status'] == 'done'
