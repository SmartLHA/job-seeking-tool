"""Offline tests for the reviewer fallback chain (spec Fix 4); every Gemini call is faked."""
import json
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from scripts import cv_review_eval as ev
from src import job_hunt_cv_review as cvr
from src import job_hunt_llm as llm
from src.job_hunt_cv_review import (
    EVAL_REVIEWER_MODELS, REVIEWER_MODEL, REVIEWER_MODELS, item_statuses, overall_verdict, run_blind_review,
)

# The real helper, captured at import so a test can restore it after the autouse fixture fakes it.
REAL_CALL = llm._call_gemini_model

CASES = Path(__file__).parent / 'fixtures/cv_review_eval'
M1, M2 = 'synthetic-reviewer-one', 'synthetic-reviewer-two'
EVIDENCE = 'Existing source fact.'
REWRITE = 'Summary\n- New fact.'
GOOD = json.dumps({'results': [{'id': 's-0', 'verdict': 'SUPPORTED', 'evidence_quote': EVIDENCE,
                                'reason': 'test'}]})

# The real 4-tuple (text, error, should_try_fallback, failure_kind) of src/job_hunt_llm.py:99-123.
# should_try_fallback is True for timeout, which is why the chain must read failure_kind only.
FAILURES = {
    'rate_limited': (None, "Model 'x' rate limited (429) - trying next model", True, 'rate_limited'),
    'server_error': (None, "Model 'x' unavailable (503 - high demand) - trying next model", True, 'server_error'),
    'not_found': (None, "Model 'x' not found (404)", True, 'not_found'),
    'timeout': (None, 'Gemini API timed out after 180s - trying next model', True, 'timeout'),
    'fatal': (None, 'Gemini API error 400: synthetic', False, 'fatal'),
}
SUCCESS = (GOOD, None, False, None)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(llm.requests, 'post', forbidden)
    monkeypatch.setattr(llm, '_call_gemini_model', forbidden)
    monkeypatch.setattr(llm, '_call_gemini_reasoning', forbidden)
    monkeypatch.setattr(llm, '_api_key', lambda: 'synthetic-key')


def script(monkeypatch, replies):
    """Fake _call_gemini_model: one reply per model (a 4-tuple, or an exception to raise).

    Returns the list of models called, in order. A model with no scripted reply fails the test.
    """
    called = []

    def helper(prompt, model, key, **kwargs):
        called.append(model)
        reply = replies[model]
        if isinstance(reply, BaseException):
            raise reply
        return reply
    monkeypatch.setattr(llm, '_call_gemini_model', helper)
    return called


def review_with(models=(M1, M2), writer='writer', **kwargs):
    return run_blind_review('Summary', EVIDENCE, '', [], {'reviewed_cv': REWRITE}, writer,
                            models=models, **kwargs)


def only_item(result):
    assert len(result['items']) == 1
    return result['items'][0]


def unchecked(item, reason, detail=None):
    assert (item['verdict'], item['reason'], item.get('unchecked_detail')) == ('UNCHECKED', reason, detail)


# --- F4-3: fall through on 429, 503, 404 only ---

@pytest.mark.parametrize('kind', ['rate_limited', 'server_error', 'not_found'])
def test_fall_through_kinds_use_the_second_model(kind, monkeypatch):
    called = script(monkeypatch, {M1: FAILURES[kind], M2: SUCCESS})
    result = review_with()
    assert called == [M1, M2]
    assert result['reviewer_model'] == M2
    assert only_item(result)['verdict'] == 'SUPPORTED'
    assert 'unchecked_detail' not in only_item(result)


@pytest.mark.parametrize('kind', ['timeout', 'fatal'])
def test_timeout_and_fatal_stop_the_chain(kind, monkeypatch):
    assert FAILURES[kind][2] is (kind == 'timeout')  # the flag is True for timeout and must not decide
    called = script(monkeypatch, {M1: FAILURES[kind], M2: SUCCESS})
    result = review_with()
    assert called == [M1]
    unchecked(only_item(result), 'reviewer_unavailable', kind)
    assert result['reviewer_model'] == M1


@pytest.mark.parametrize('error, detail', [(TimeoutError(), 'timeout'), (RuntimeError('boom'), 'server_error')])
def test_exception_on_first_model_stops_the_chain(error, detail, monkeypatch):
    called = script(monkeypatch, {M1: error, M2: SUCCESS})
    result = review_with()
    assert called == [M1]
    unchecked(only_item(result), 'reviewer_unavailable', detail)
    assert result['reviewer_model'] == M1


@pytest.mark.parametrize('error, detail', [(TimeoutError(), 'timeout'), (RuntimeError('boom'), 'server_error')])
def test_exception_on_second_model_records_the_second_model(error, detail, monkeypatch):
    called = script(monkeypatch, {M1: FAILURES['rate_limited'], M2: error})
    result = review_with()
    assert called == [M1, M2]
    unchecked(only_item(result), 'reviewer_unavailable', detail)
    assert result['reviewer_model'] == M2


@pytest.mark.parametrize('raw, reason, detail', [
    ('not json', 'reviewer_unavailable', 'bad_json'),
    ('{"results": null}', 'model_error', None),
])
def test_a_reply_from_the_first_model_is_used_even_when_invalid(raw, reason, detail, monkeypatch):
    called = script(monkeypatch, {M1: (raw, None, False, None), M2: SUCCESS})
    result = review_with()
    assert called == [M1]
    unchecked(only_item(result), reason, detail)
    assert result['reviewer_model'] == M1


@pytest.mark.parametrize('first, last', [
    ('rate_limited', 'rate_limited'), ('server_error', 'rate_limited'),
    ('rate_limited', 'not_found'), ('not_found', 'server_error')])
def test_every_model_falling_through_records_the_last_failure(first, last, monkeypatch):
    called = script(monkeypatch, {M1: FAILURES[first], M2: FAILURES[last]})
    result = review_with()
    assert called == [M1, M2]
    unchecked(only_item(result), 'reviewer_unavailable', last)
    assert result['reviewer_model'] == M2
    assert overall_verdict([], item_statuses(result)) == 'UNCHECKED'


def test_the_last_model_is_not_retried_or_looped(monkeypatch):
    called = script(monkeypatch, {M1: FAILURES['rate_limited']})
    result = review_with(models=(M1,))
    assert called == [M1]
    unchecked(only_item(result), 'reviewer_unavailable', 'rate_limited')


# --- F4-2, F4-6: the writer's model is skipped, on both paths ---

def test_writer_model_equal_to_first_model_skips_it(monkeypatch):
    called = script(monkeypatch, {M1: SUCCESS, M2: SUCCESS})
    result = review_with(writer=M1)
    assert called == [M2]
    assert result['reviewer_model'] == M2
    assert only_item(result)['verdict'] == 'SUPPORTED'


def test_writer_model_equal_to_second_model_is_never_called(monkeypatch):
    called = script(monkeypatch, {M1: FAILURES['rate_limited'], M2: SUCCESS})
    result = review_with(writer=M2)
    assert called == [M1]
    unchecked(only_item(result), 'reviewer_unavailable', 'rate_limited')


def test_writer_model_equal_to_the_only_model_is_same_model(monkeypatch):
    called = script(monkeypatch, {M1: SUCCESS})
    result = review_with(models=(M1,), writer=M1)
    assert called == []
    unchecked(only_item(result), 'same_model')
    assert result['reviewer_model'] == M1


def test_transport_path_skips_the_writer_model_and_calls_once():
    prompts = []

    def transport(prompt):
        prompts.append(prompt)
        return GOOD
    result = review_with(writer=M1, transport=transport)
    assert len(prompts) == 1
    assert result['reviewer_model'] == M2
    assert only_item(result)['verdict'] == 'SUPPORTED'


def test_transport_path_has_no_chain():
    prompts = []

    def transport(prompt):
        prompts.append(prompt)
        return 'not json'
    result = review_with(transport=transport)
    assert len(prompts) == 1
    unchecked(only_item(result), 'reviewer_unavailable', 'bad_json')
    assert result['reviewer_model'] == M1


def test_transport_path_same_model():
    def transport(prompt):
        pytest.fail('transport called although every model equals the writer')
    result = review_with(models=(M1,), writer=M1, transport=transport)
    unchecked(only_item(result), 'same_model')
    assert result['reviewer_model'] == M1


# --- F4-5: what reviewer_model records on the paths that make no call ---

def test_no_items_records_the_first_model(monkeypatch):
    called = script(monkeypatch, {M1: SUCCESS, M2: SUCCESS})
    result = run_blind_review('Summary\n- Existing fact.', '', '', [], {'reviewed_cv': 'Summary\n- Existing fact.'},
                              'writer', models=(M1, M2))
    assert result == {'items': [], 'reviewer_model': M1, 'prompt_version': cvr.REVIEW_PROMPT_VERSION}
    assert called == []


@pytest.mark.parametrize('writer', ['writer', M1])
def test_no_key_runs_once_before_the_chain_and_records_the_first_model(writer, monkeypatch):
    called = script(monkeypatch, {M1: SUCCESS, M2: SUCCESS})
    monkeypatch.setattr(llm, '_api_key', lambda: None)
    result = review_with(writer=writer)
    assert called == []
    unchecked(only_item(result), 'reviewer_unavailable', 'no_key')
    assert result['reviewer_model'] == M1  # taken before any model is skipped


# --- F4-2: models=None means REVIEWER_MODELS, read at call time ---

def test_default_models_come_from_reviewer_models(monkeypatch):
    monkeypatch.setattr(cvr, 'REVIEWER_MODELS', (M1, M2))
    called = script(monkeypatch, {M1: FAILURES['server_error'], M2: SUCCESS})
    result = run_blind_review('Summary', EVIDENCE, '', [], {'reviewed_cv': REWRITE}, 'writer')
    assert called == [M1, M2]
    assert result['reviewer_model'] == M2


def test_default_start_model_is_reviewer_model():
    result = run_blind_review('Summary\n- Existing fact.', '', '', [], {'reviewed_cv': 'Summary\n- Existing fact.'},
                              'writer')
    assert result['reviewer_model'] == REVIEWER_MODEL == REVIEWER_MODELS[0]


# --- F4-9: the real helper, with only requests.post mocked ---

def response(status, text=GOOD):
    if status == 200:
        reply = Mock(ok=True, status_code=200)
        reply.json.return_value = {'candidates': [{'content': {'parts': [{'text': text}]}}]}
        return reply
    return Mock(ok=False, status_code=status, text='synthetic body')


def model_of(url):
    return url.split('/models/')[1].split(':')[0]


def test_real_helper_429_then_200(monkeypatch):
    monkeypatch.setattr(llm, '_call_gemini_model', REAL_CALL)
    urls = []

    def post(url, **kwargs):
        urls.append(url)
        return response(429 if len(urls) == 1 else 200)
    monkeypatch.setattr(llm.requests, 'post', post)
    result = review_with()
    assert [model_of(url) for url in urls] == [M1, M2]
    assert result['reviewer_model'] == M2
    assert only_item(result)['verdict'] == 'SUPPORTED'


@pytest.mark.parametrize('outcome, posts, detail', [
    (404, 2, 'not_found'), (429, 2, 'rate_limited'), (503, 2, 'server_error'),
    (400, 1, 'fatal'), (500, 1, 'fatal'), (504, 1, 'fatal'),
    (requests.exceptions.ReadTimeout(), 1, 'timeout'),
    (requests.exceptions.ConnectTimeout(), 1, 'fatal'),
])
def test_real_helper_failure_kinds_decide_the_chain(outcome, posts, detail, monkeypatch):
    monkeypatch.setattr(llm, '_call_gemini_model', REAL_CALL)
    urls = []

    def post(url, **kwargs):
        urls.append(url)
        if isinstance(outcome, BaseException):
            raise outcome
        return response(outcome)
    monkeypatch.setattr(llm.requests, 'post', post)
    result = review_with()
    assert len(urls) == posts
    unchecked(only_item(result), 'reviewer_unavailable', detail)


# --- F4-1: constants ---

def test_reviewer_constants_stay_outside_the_writer_chain():
    writer_chain = {llm._ANALYSIS_MODEL, llm._ANALYSIS_FALLBACK_1, llm._ANALYSIS_FALLBACK_2}
    assert not writer_chain & set(REVIEWER_MODELS)
    assert not writer_chain & set(EVAL_REVIEWER_MODELS)
    assert REVIEWER_MODELS and REVIEWER_MODEL == REVIEWER_MODELS[0]
    assert set(REVIEWER_MODELS) <= set(EVAL_REVIEWER_MODELS)
    assert len(set(REVIEWER_MODELS)) == len(REVIEWER_MODELS)
    assert EVAL_REVIEWER_MODELS == ('gemini-3.5-flash', 'gemini-3.8-flash', 'gpt-6-luna')
    assert REVIEWER_MODELS[0] == 'gemini-3.5-flash'


# --- F4-7: a fall-through logs a warning ---

def test_fall_through_logs_a_warning(monkeypatch, caplog):
    script(monkeypatch, {M1: FAILURES['rate_limited'], M2: SUCCESS})
    with caplog.at_level(logging.WARNING):
        review_with()
    messages = [r.getMessage() for r in caplog.records if r.name == cvr.__name__ and r.levelno == logging.WARNING]
    assert len(messages) == 1
    assert M1 in messages[0] and 'rate_limited' in messages[0] and M2 in messages[0]


def test_no_warning_when_the_chain_stops(monkeypatch, caplog):
    script(monkeypatch, {M1: FAILURES['timeout'], M2: SUCCESS})
    with caplog.at_level(logging.WARNING):
        review_with()
    assert not [r for r in caplog.records if r.name == cvr.__name__]


# --- F4-8: eval ---

@pytest.fixture
def stub_run(monkeypatch, tmp_path):
    seen = []

    def fake_run(cases, **kwargs):
        seen.append(kwargs)
        return [], tmp_path / 'stub-report.md'
    monkeypatch.setattr(ev, 'run', fake_run)
    return seen


def test_eval_rejects_a_model_outside_the_eval_list(stub_run, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        ev.main(['--dry-run', '--reviewer-model', 'gemini-3.1-flash-lite', '--out-dir', str(tmp_path / 'out')])
    assert exc.value.code == 2
    assert 'invalid choice' in capsys.readouterr().err
    assert stub_run == []


def test_eval_flag_reaches_run_and_defaults_to_the_first_reviewer_model(stub_run, tmp_path):
    base = ['--dry-run', '--cases', str(CASES), '--out-dir', str(tmp_path / 'out')]
    assert ev.main(base) == 0
    assert stub_run[-1]['reviewer_model'] == REVIEWER_MODELS[0]
    for model in EVAL_REVIEWER_MODELS:
        assert ev.main(base + ['--reviewer-model', model]) == 0
        assert stub_run[-1]['reviewer_model'] == model


def test_eval_dry_run_with_the_flag_makes_no_call_and_the_header_names_the_model(tmp_path):
    out_dir = tmp_path / 'out'
    rc = ev.main(['--dry-run', '--reviewer-model', 'gemini-3.8-flash', '--cases', str(CASES),
                  '--out-dir', str(out_dir)])  # the autouse fixture fails any network call
    assert rc == 0
    text = next(out_dir.glob('report-*.md')).read_text()
    assert 'Reviewer model: gemini-3.8-flash (not called in dry-run)' in text


@pytest.mark.parametrize('model', [None, 'gemini-3.8-flash'])
def test_eval_run_passes_a_one_model_tuple_and_never_falls_through(model, monkeypatch, tmp_path):
    seen = []
    real = ev.run_blind_review

    def spy(*args, **kwargs):
        seen.append(kwargs.get('models'))
        return real(*args, **kwargs)
    monkeypatch.setattr(ev, 'run_blind_review', spy)
    expected = model or REVIEWER_MODELS[0]
    # 429 on every model: with a chain the second model would be called too.
    called = script(monkeypatch, {m: FAILURES['rate_limited'] for m in EVAL_REVIEWER_MODELS})
    case = next(c for c in ev.load_cases(CASES) if c['id'] == 'clean-rephrase')
    options = {} if model is None else {'reviewer_model': model}
    rows, report = ev.run([case], dry_run=False, out_dir=tmp_path, pace=0, retry_wait=0, sleep=lambda s: None,
                          **options)
    assert seen == [(expected,), (expected,)]  # the first attempt and the one retry
    assert called == [expected, expected]
    assert rows[0]['not_run'] and rows[0]['detail'] == 'rate_limited'
    assert f'Reviewer model: {expected}\n' in report.read_text()
