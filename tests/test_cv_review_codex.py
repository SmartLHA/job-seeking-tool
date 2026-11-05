"""Offline provider-aware reviewer and eval contracts."""
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from src import job_hunt_codex as codex, job_hunt_cv_review as review, job_hunt_llm as llm
from scripts import cv_review_eval as ev

ORIGINAL = 'Summary\n- Prepared useful reports.'
REWRITE = 'Summary\n- Prepared useful reports clearly.'
QUOTE = 'Prepared useful reports.'
REAL_CODEX_CALL = codex.call_codex_reviewer
GOOD = {'id': 's-0', 'verdict': 'SUPPORTED', 'evidence_quote': QUOTE, 'reason': 'faithful'}


def run(models=('gpt-6-luna', 'gemini-3.5-flash')):
    return review.run_blind_review(ORIGINAL, ORIGINAL, '', [], {'reviewed_cv': REWRITE}, 'writer', models=models)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Unexpected provider call')
    monkeypatch.setattr(llm, '_api_key', lambda: None)
    monkeypatch.setattr(llm, '_call_gemini_model', forbidden)
    monkeypatch.setattr(codex, 'call_codex_reviewer', forbidden)


@pytest.mark.parametrize('kind,fallback', [('rate_limited', True), ('server_error', True), ('not_found', True), ('timeout', False)])
def test_codex_failure_chain(monkeypatch, kind, fallback):
    calls = []
    monkeypatch.setattr(llm, '_api_key', lambda: 'synthetic-key')
    monkeypatch.setattr(codex, 'call_codex_reviewer', lambda *a, **k: (None, 'failure', True, kind))
    def gemini(*a, **k):
        calls.append(a[1])
        return json.dumps({'results': [GOOD]}), None, False, None
    monkeypatch.setattr(llm, '_call_gemini_model', gemini)
    result = run()
    assert calls == (['gemini-3.5-flash'] if fallback else [])
    assert result['reviewer_model'] == ('gemini-3.5-flash' if fallback else 'gpt-6-luna')


def test_codex_success_needs_no_google_key(monkeypatch):
    def fake(prompt, model, schema, **kwargs):
        assert model == 'gpt-6-luna' and schema == codex.REVIEW_OUTPUT_SCHEMA
        return json.dumps({'results': [GOOD]}), None, False, None
    monkeypatch.setattr(codex, 'call_codex_reviewer', fake)
    result = run()
    assert result['reviewer_model'] == 'gpt-6-luna'
    assert result['items'][0]['verdict'] == 'SUPPORTED'


def test_missing_gemini_key_skips_to_codex(monkeypatch):
    monkeypatch.setattr(codex, 'call_codex_reviewer', lambda *a, **k: (json.dumps({'results': [GOOD]}), None, False, None))
    assert run(('gemini-3.5-flash', 'gpt-6-luna'))['items'][0]['verdict'] == 'SUPPORTED'
    assert run(('gemini-3.5-flash',))['items'][0]['unchecked_detail'] == 'no_key'


@pytest.mark.parametrize('results', [[], [GOOD, GOOD], [GOOD, {'id': 'bad'}], [dict(GOOD, evidence_quote=None)]])
def test_codex_reply_validation(monkeypatch, results):
    monkeypatch.setattr(codex, 'call_codex_reviewer', lambda *a, **k: (json.dumps({'results': results}), None, False, None))
    assert run()['items'][0]['verdict'] == 'UNCHECKED'


def test_codex_grounding_downgrade(monkeypatch):
    monkeypatch.setattr(codex, 'call_codex_reviewer', lambda *a, **k: (
        json.dumps({'results': [dict(GOOD, evidence_quote='Invented source quote')]}), None, False, None))
    assert run()['items'][0]['reason'] == 'quote_not_in_source'


def test_chain_deliberately_trips_codex_fence(monkeypatch, tmp_path, codex_transport_fence):
    # Drive the real adapter far enough to reach the fenced version launch.
    home = tmp_path / 'home'
    home.mkdir(mode=0o700)
    (home / 'AGENTS.md').write_text('')
    monkeypatch.setattr(codex, 'codex_home', lambda: home)
    monkeypatch.setattr(codex, 'resolve_codex', lambda: ('/fake/codex', '/fake/node'))
    monkeypatch.setattr(codex, 'call_codex_reviewer', REAL_CODEX_CALL)
    result = run(('gpt-6-luna',))
    assert result['items'][0]['unchecked_detail'] == 'server_error'
    assert len(codex_transport_fence) == 1
    codex_transport_fence.clear()


def test_eval_gpt_ready_without_key_or_dotenv(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(codex, 'check_codex_ready', lambda: calls.append('ready'))
    monkeypatch.setattr(ev, 'run', lambda *a, **k: ([], tmp_path / 'report.md'))
    assert ev.main(['--use-cloud', '--reviewer-model', 'gpt-6-luna']) == 0
    assert calls == ['ready']


def test_eval_gpt_not_ready_fails_before_run(monkeypatch):
    monkeypatch.setattr(codex, 'check_codex_ready', lambda: 'server_error')
    assert ev.main(['--use-cloud', '--reviewer-model', 'gpt-6-luna']) == 2


def test_eval_gpt_dry_run_no_readiness_or_subprocess(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail('Dry-run called readiness/subprocess')
    monkeypatch.setattr(codex, 'check_codex_ready', forbidden)
    monkeypatch.setattr(codex.subprocess, 'Popen', forbidden)
    assert ev.main(['--dry-run', '--reviewer-model', 'gpt-6-luna', '--out-dir', str(tmp_path)]) == 0
    report = next(tmp_path.glob('report-*.md')).read_text()
    assert 'Provider: OpenAI (Codex CLI)' in report
    assert 'Cases including variants: 19; matches: 19; mismatches: 0' in report


def test_openai_reviewer_record_roundtrip(tmp_path):
    profile = SimpleNamespace(candidate_id='synthetic')
    record = dict(schema_version=1, generation_id=uuid4().hex, verdict='PASS', l0_findings=[], items=[],
                  reviewer_model='gpt-6-luna', prompt_version=review.REVIEW_PROMPT_VERSION,
                  binding=review.compute_binding(profile, ORIGINAL, ORIGINAL, '', REWRITE, 'job-1'),
                  writer_model='synthetic-writer', created_at='2026-11-02T12:00:00+00:00',
                  revise_round=0, approval=None)
    review.write_review_record(tmp_path, 'job-1', record)
    assert review.read_review_record(tmp_path, 'job-1') == record


def test_provider_failure_logging_has_no_sensitive_payload(monkeypatch, caplog):
    monkeypatch.setattr(codex, 'call_codex_reviewer', lambda *a, **k: (None, 'private provider stderr', True, 'rate_limited'))
    monkeypatch.setattr(llm, '_api_key', lambda: 'synthetic-key')
    monkeypatch.setattr(llm, '_call_gemini_model', lambda *a, **k: (json.dumps({'results': [GOOD]}), None, False, None))
    run()
    assert 'gpt-6-luna' in caplog.text and 'rate_limited' in caplog.text
    assert 'private provider stderr' not in caplog.text and QUOTE not in caplog.text
