"""Synthetic record, source binding and rewrite gate acceptance tests."""
from copy import deepcopy
from dataclasses import asdict
from http import HTTPStatus
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock
from uuid import uuid4

import pytest

from src import job_hunt_cv_review as review, job_hunt_llm as llm, ui_handlers
from src.job_hunt_config import TailoringPolicy
from src.job_hunt_tailoring import EmptyTailoredCVError, load_latest_tailored_cv


@pytest.fixture(autouse=True)
def no_gemini(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('real Gemini calls forbidden')
    monkeypatch.setattr(llm, '_call_gemini_model', forbidden)
    monkeypatch.setattr(llm, '_call_gemini_reasoning', forbidden)


def profile(**kwargs):
    values = dict(candidate_id='synthetic', master_cv_text='Summary\n- Prepared useful reports.',
                  master_cv_ref=None, years_experience=5, skills=[NS(name='SQL')],
                  target_roles=['Analyst'], industries=['Finance'])
    values.update(kwargs)
    return NS(**values)


def record_for(p, body, *, cv_text=None, verdict='PASS', job_id='job-1'):
    cv_text = p.master_cv_text if cv_text is None else cv_text
    evidence, context = review.build_review_source(p, cv_text)
    items = []
    if verdict != 'PASS':
        status, severity = {'BLOCKED': ('UNSUPPORTED', 'BLOCKER'),
                            'NEEDS_EDIT': ('EXAGGERATED', 'MAJOR'),
                            'UNCHECKED': ('UNCHECKED', None)}[verdict]
        items = [dict(id='s-0', block_key='summary', text='Prepared useful reports.',
                      removed=[], verdict=status, evidence_quote=None if status != 'EXAGGERATED' else 'Prepared useful reports.',
                      reason='synthetic', severity=severity)]
    return dict(schema_version=1, generation_id=uuid4().hex, verdict=verdict,
                l0_findings=[], items=items, reviewer_model=review.REVIEWER_MODEL,
                prompt_version=review.REVIEW_PROMPT_VERSION,
                binding=review.compute_binding(p, cv_text, evidence, context, body, job_id),
                writer_model='synthetic-writer', created_at='2026-10-27T12:00:00+00:00',
                revise_round=0, approval=None)


@pytest.fixture
def gate(tmp_path):
    p = profile()
    out = tmp_path / 'tailored'
    out.mkdir()
    policy = TailoringPolicy(output_dir=out)
    body = 'Summary\n- Prepared useful reports clearly.'
    (out / 'job-1.md').write_text('<!-- profile_id: synthetic -->\nordinary CV')
    (out / 'job-1_ai_reviewed.md').write_text('<!-- profile_id: synthetic -->\n  '+body+'\n')
    rec = record_for(p, body)
    review.write_review_record(out, 'job-1', rec)
    return NS(profile=p, out=out, policy=policy, body=body, record=rec, base=tmp_path)


def load(g, **kwargs):
    return load_latest_tailored_cv('job-1', expected_profile_id='synthetic', policy=g.policy,
                                   profile=kwargs.pop('profile', g.profile), base_dir=g.base, **kwargs)


def raw_record(g, rec):
    review.review_record_path(g.out, 'job-1').write_text(json.dumps(rec))


def test_record_roundtrip_and_exact_hashed_body(gate):
    assert review.read_review_record(gate.out, 'job-1') == gate.record
    assert load(gate) == gate.body
    assert review.sha256_text(load(gate)) == gate.record['binding']['rewrite_sha256']
    review.delete_review_record(gate.out, 'job-1')
    assert review.read_review_record(gate.out, 'job-1') is None
    assert load(gate) == 'ordinary CV'


@pytest.mark.parametrize('verdict', ['BLOCKED', 'NEEDS_EDIT', 'UNCHECKED'])
def test_approval_accepts_only_current_generation_and_hash(gate, verdict):
    rec = record_for(gate.profile, gate.body, verdict=verdict)
    raw_record(gate, rec)
    assert load(gate) == 'ordinary CV'
    rec['approval'] = dict(approved_at='2026-10-27T12:01:00+00:00', generation_id=rec['generation_id'],
                           rewrite_sha256=rec['binding']['rewrite_sha256'])
    raw_record(gate, rec)
    assert load(gate) == gate.body
    for field in ['generation_id', 'rewrite_sha256']:
        stale = deepcopy(rec)
        stale['approval'][field] = '0' * (32 if field == 'generation_id' else 64)
        raw_record(gate, stale)
        assert load(gate) == 'ordinary CV'


@pytest.mark.parametrize('path,value', [
    (('schema_version',), 2), (('schema_version',), True), (('generation_id',), 1),
    (('generation_id',), 'invalid'), (('verdict',), 'OTHER'), (('l0_findings',), {}),
    (('items',), {}), (('reviewer_model',), None), (('prompt_version',), 3),
    (('binding',), []), (('binding','profile_id'), 9), (('binding','job_id'), 9),
    (('binding','original_cv_sha256'), 'bad'), (('binding','evidence_sha256'), None),
    (('binding','context_sha256'), 4), (('binding','rewrite_sha256'), ''),
    (('writer_model',), []), (('created_at',), 3), (('revise_round',), 2),
    (('revise_round',), True), (('approval',), {}),
])
def test_invalid_record_field_types_and_enums_fall_back(gate, path, value):
    rec = deepcopy(gate.record)
    node = rec
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    raw_record(gate, rec)
    assert review.read_review_record(gate.out, 'job-1') is None
    assert load(gate) == 'ordinary CV'


@pytest.mark.parametrize('field', ['schema_version', 'generation_id', 'verdict', 'l0_findings', 'items',
    'reviewer_model', 'prompt_version', 'binding', 'writer_model', 'created_at', 'revise_round', 'approval'])
def test_missing_top_level_field_fails_closed(gate, field):
    rec = deepcopy(gate.record)
    del rec[field]
    raw_record(gate, rec)
    assert review.read_review_record(gate.out, 'job-1') is None
    assert load(gate) == 'ordinary CV'


@pytest.mark.parametrize('field', ['profile_id', 'job_id', 'original_cv_sha256', 'evidence_sha256', 'context_sha256', 'rewrite_sha256'])
def test_missing_binding_field_fails_closed(gate, field):
    rec = deepcopy(gate.record)
    del rec['binding'][field]
    raw_record(gate, rec)
    assert review.read_review_record(gate.out, 'job-1') is None
    assert load(gate) == 'ordinary CV'


@pytest.mark.parametrize('field,value', [('id', 1), ('block_key', None), ('text', []), ('verdict', 'OTHER'),
    ('evidence_quote', 2), ('reason', None), ('severity', 'OTHER'), ('removed', [3])])
def test_nested_item_invalid_types(gate, field, value):
    rec = record_for(gate.profile, gate.body, verdict='BLOCKED')
    rec['items'][0][field] = value
    raw_record(gate, rec)
    assert review.read_review_record(gate.out, 'job-1') is None
    assert load(gate) == 'ordinary CV'


@pytest.mark.parametrize('field', ['id', 'block_key', 'text', 'verdict', 'evidence_quote', 'reason', 'severity'])
def test_nested_item_missing_fields(gate, field):
    rec = record_for(gate.profile, gate.body, verdict='BLOCKED')
    del rec['items'][0][field]
    raw_record(gate, rec)
    assert review.read_review_record(gate.out, 'job-1') is None
    assert load(gate) == 'ordinary CV'


def test_malformed_and_contradictory_pass(gate):
    review.review_record_path(gate.out, 'job-1').write_text('not json')
    assert review.read_review_record(gate.out, 'job-1') is None
    assert load(gate) == 'ordinary CV'
    rec = record_for(gate.profile, gate.body, verdict='BLOCKED')
    rec['verdict'] = 'PASS'
    raw_record(gate, rec)
    assert review.read_review_record(gate.out, 'job-1') is None
    assert load(gate) == 'ordinary CV'


@pytest.mark.parametrize('rule,item_id,status', [('L0-1','s-0','SUPPORTED'), ('L0-4','s-1','SUPPORTED'),
                                               ('L0-4','s-0','UNSUPPORTED')])
def test_invalid_cleared_by_fails_closed(gate, rule, item_id, status):
    rec = record_for(gate.profile, gate.body, verdict='BLOCKED')
    item = rec['items'][0]
    item.update(verdict=status, severity=None if status == 'SUPPORTED' else 'BLOCKER')
    rec['l0_findings'] = [asdict(review.Finding(0, rule, 'fact', 'MAJOR', 'detail', item_id, 's-0'))]
    rec['verdict'] = review.overall_verdict([review.Finding(**f) for f in rec['l0_findings']], rec['items'])
    raw_record(gate, rec)
    assert review.read_review_record(gate.out, 'job-1') is None
    assert load(gate) == 'ordinary CV'


@pytest.mark.parametrize('change', ['rewrite', 'original', 'skills', 'roles', 'industries', 'years', 'no_profile', 'no_record', 'missing_master'])
def test_binding_changes_fall_back(gate, change):
    if change == 'rewrite':
        (gate.out / 'job-1_ai_reviewed.md').write_text('<!-- profile_id: synthetic -->\n' + gate.body[:-1] + '!')
    elif change == 'original':
        gate.profile.master_cv_text += ' changed'
    elif change == 'skills':
        gate.profile.skills.append(NS(name='Python'))
    elif change == 'roles':
        gate.profile.target_roles.append('Manager')
    elif change == 'industries':
        gate.profile.industries.append('Retail')
    elif change == 'years':
        gate.profile.years_experience = 8
    elif change == 'no_record':
        review.delete_review_record(gate.out, 'job-1')
    elif change == 'missing_master':
        gate.profile.master_cv_text = None
        gate.profile.master_cv_ref = 'missing.md'
    assert load(gate, profile=None if change == 'no_profile' else gate.profile) == 'ordinary CV'


def test_relative_master_ref_uses_base_dir(gate, monkeypatch):
    (gate.base / 'master.md').write_text(gate.profile.master_cv_text)
    gate.profile.master_cv_ref = 'master.md'
    gate.profile.master_cv_text = None
    elsewhere = gate.base / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert load(gate) == gate.body


def test_valid_empty_rewrite_raises(gate):
    (gate.out / 'job-1_ai_reviewed.md').write_text('<!-- profile_id: synthetic -->\n  ')
    raw_record(gate, record_for(gate.profile, ''))
    with pytest.raises(EmptyTailoredCVError):
        load(gate)


@pytest.fixture
def handler_env(tmp_path, monkeypatch):
    p = profile()
    out = tmp_path / 'tailored'
    out.mkdir()
    policy = TailoringPolicy(output_dir=out)
    monkeypatch.setattr(ui_handlers, 'DEFAULT_TAILORING_POLICY', policy)
    monkeypatch.setattr(ui_handlers, 'load_candidate_profile', lambda *a: p)
    monkeypatch.setattr(ui_handlers, 'load_job_analysis', lambda *a: NS(decision='apply', user_decision=None))
    monkeypatch.setattr(ui_handlers, 'load_reviewed_job', lambda *a: NS(job_id='job-1', required_skills=[], preferred_skills=[]))
    writer = Mock(return_value=({'reviewed_cv': 'Summary\n- Prepared helpful reports.', 'changes': []}, None, 'synthetic-writer'))
    monkeypatch.setattr(llm, 'ai_rewrite_cv', writer)
    config = NS(profile_path=tmp_path/'profile.json', state_root=tmp_path)
    responder = NS(send_json=Mock())
    return NS(profile=p, out=out, policy=policy, config=config, responder=responder, writer=writer)


def call_handler(h):
    ui_handlers.handle_ai_review_cv(NS(json_body={'use_cloud': True}), h.config, h.responder, 'job-1')
    return h.responder.send_json.call_args.args[0]


def test_busy_lock_never_calls_writer(handler_env):
    with review.AI_REVIEW_LOCK:
        response = call_handler(handler_env)
    assert response == {'ok': False, 'error': 'busy'}
    assert handler_env.responder.send_json.call_args.kwargs['status'] == HTTPStatus.CONFLICT
    handler_env.writer.assert_not_called()
    assert list(handler_env.out.iterdir()) == []


def test_unavailable_handler_records_unchecked_and_loader_rejects(handler_env, monkeypatch):
    monkeypatch.setattr(llm, '_api_key', lambda: 'synthetic')
    monkeypatch.setattr(llm, '_call_gemini_model', lambda *a, **k: ('not json', None, False, None))
    response = call_handler(handler_env)
    record = review.read_review_record(handler_env.out, 'job-1')
    assert record is not None and record['verdict'] == 'UNCHECKED'
    assert response['review']['verdict'] == 'UNCHECKED'
    assert response['generation_id'] == record['generation_id']
    assert response['rewrite_sha256'] == record['binding']['rewrite_sha256']
    assert 'items' in response['review'] and 'removed' in response['review']['items'][0]
    assert load_latest_tailored_cv('job-1', policy=handler_env.policy, profile=handler_env.profile,
                                  base_dir=handler_env.config.profile_path.parent) is None


def test_crash_between_markdown_and_record_falls_back(handler_env, monkeypatch):
    (handler_env.out/'job-1.md').write_text('ordinary CV')
    raw = record_for(handler_env.profile, 'old rewrite')
    review.write_review_record(handler_env.out, 'job-1', raw)
    monkeypatch.setattr(review, 'run_blind_review', lambda *a, **k: dict(items=[], reviewer_model=review.REVIEWER_MODEL,
                                                                       prompt_version=review.REVIEW_PROMPT_VERSION))
    def crash(*a, **k):
        raise OSError('synthetic crash after markdown')
    monkeypatch.setattr(review, 'write_review_record', crash)
    call_handler(handler_env)
    assert (handler_env.out/'job-1_ai_reviewed.md').exists()
    assert review.read_review_record(handler_env.out, 'job-1') is None
    assert load_latest_tailored_cv('job-1', policy=handler_env.policy, profile=handler_env.profile,
                                  base_dir=handler_env.config.profile_path.parent) == 'ordinary CV'
    assert not review.AI_REVIEW_LOCK.locked()


@pytest.mark.parametrize('p', [profile(), profile(years_experience=None, skills=[], target_roles=[], industries=[]),
    profile(years_experience=18, skills=[NS(name=f'Skill {i}') for i in range(40)],
            target_roles=[f'Role {i}' for i in range(8)], industries=[f'Industry {i}' for i in range(8)])])
def test_writer_prompt_byte_identical(p, monkeypatch):
    job = NS(job_title='Analyst', company='Synthetic', required_skills=['SQL'], preferred_skills=[], description_raw='Details '*400)
    cv = 'Synthetic CV '*1500
    old_prompt = llm._AI_CV_REVIEW_PROMPT.format(title=job.job_title, company=job.company,
        required_skills=', '.join(job.required_skills) or 'not specified',
        preferred_skills=', '.join(job.preferred_skills) or 'not specified',
        description=(getattr(job, 'description_raw', '') or '')[:2000],
        years=getattr(p, 'years_experience', 'unknown'),
        target_roles=', '.join(getattr(p, 'target_roles', [])[:5]) or 'not specified',
        industries=', '.join(getattr(p, 'industries', [])[:5]) or 'not specified',
        skills=', '.join(s.name for s in getattr(p, 'skills', [])[:30]) or 'none listed',
        cv_text=cv[:llm._MAX_CV_REVIEW_CHARS])
    transport = Mock(return_value=('{"reviewed_cv":"synthetic", "changes":[]}', None, 'writer', False))
    monkeypatch.setattr(llm, '_call_gemini_reasoning', transport)
    llm.ai_rewrite_cv(cv, p, job, NS())
    assert transport.call_args.args[0].encode('utf-8') == old_prompt.encode('utf-8')


@pytest.mark.parametrize('field,value', [('layer', '0'), ('rule', 'OTHER'), ('text', None),
    ('severity', 'OTHER'), ('detail', []), ('item_id', 3), ('cleared_by', 2)])
def test_nested_finding_invalid_types_and_enums(gate, field, value):
    rec = deepcopy(gate.record)
    finding = asdict(review.Finding(0, 'L0-4', 'SQL', 'MINOR', 'synthetic'))
    finding[field] = value
    rec['l0_findings'] = [finding]
    raw_record(gate, rec)
    assert review.read_review_record(gate.out, 'job-1') is None
    assert load(gate) == 'ordinary CV'


@pytest.mark.parametrize('field', ['layer', 'rule', 'text', 'severity', 'detail', 'item_id', 'cleared_by'])
def test_nested_finding_missing_fields(gate, field):
    rec = deepcopy(gate.record)
    finding = asdict(review.Finding(0, 'L0-4', 'SQL', 'MINOR', 'synthetic'))
    del finding[field]
    rec['l0_findings'] = [finding]
    raw_record(gate, rec)
    assert review.read_review_record(gate.out, 'job-1') is None
    assert load(gate) == 'ordinary CV'


@pytest.mark.parametrize('field', ['approved_at', 'generation_id', 'rewrite_sha256'])
@pytest.mark.parametrize('mode', ['missing', 'wrong_type'])
def test_approval_nested_fields_fail_closed(gate, field, mode):
    rec = deepcopy(gate.record)
    rec['approval'] = dict(approved_at='2026-10-27T12:00:00+00:00', generation_id=rec['generation_id'],
                           rewrite_sha256=rec['binding']['rewrite_sha256'])
    if mode == 'missing':
        del rec['approval'][field]
    else:
        rec['approval'][field] = 3
    raw_record(gate, rec)
    assert review.read_review_record(gate.out, 'job-1') is None
    assert load(gate) == 'ordinary CV'


def test_unreadable_master_falls_back(gate, monkeypatch):
    gate.profile.master_cv_text = None
    gate.profile.master_cv_ref = 'master.md'
    def unreadable(*args):
        raise OSError('synthetic unreadable master')
    monkeypatch.setattr('src.job_hunt_profile.load_master_cv', unreadable)
    assert load(gate) == 'ordinary CV'


@pytest.mark.parametrize('text,body', [
    ('<!-- metadata -->\n  body \n', 'body'),
    ('body\n<!-- keep second line -->\n', 'body\n<!-- keep second line -->'),
    ('<!-- multiline\n comment -->\nbody', '<!-- multiline\n comment -->\nbody'),
    ('<!-- header --> trailing\nbody', '<!-- header --> trailing\nbody'),
])
def test_canonical_body_drops_only_complete_first_header_line(text, body):
    assert review.canonical_cv_body(text) == body


def test_source_separates_profile_evidence_from_preferences():
    p = profile()
    evidence, context = review.build_review_source(p, p.master_cv_text)
    assert p.master_cv_text in evidence
    assert 'Years experience: 5' in evidence and 'Profile skills: SQL' in evidence
    assert 'Target roles (preference, not experience): Analyst' in context
    assert 'Industries (preference, not experience): Finance' in context
    assert 'Analyst' not in evidence and 'Finance' not in evidence


def supporting_reviewer(h, monkeypatch):
    """Support every selected item through the reviewer transport."""
    monkeypatch.setattr(llm, '_api_key', lambda: 'synthetic')
    def transport(*args, **kwargs):
        rewrite = h.writer.return_value[0]['reviewed_cv'].replace('\r\n', '\n').replace('\r', '\n')
        items = review.select_review_items(h.profile.master_cv_text, rewrite)
        return (json.dumps({'results': [dict(id=item['id'], verdict='SUPPORTED',
                    evidence_quote='Prepared useful reports.', reason='synthetic support')
                    for item in items]}), None, False, None)
    monkeypatch.setattr(llm, '_call_gemini_model', transport)


def handler_load(h):
    return load_latest_tailored_cv('job-1', expected_profile_id=h.profile.candidate_id,
                                  policy=h.policy, profile=h.profile,
                                  base_dir=h.config.profile_path.parent)


def assert_lock_free():
    assert review.AI_REVIEW_LOCK.acquire(blocking=False)
    review.AI_REVIEW_LOCK.release()


def test_handler_pass_returns_exact_written_canonical_body(handler_env, monkeypatch):
    h = handler_env
    h.writer.return_value[0]['reviewed_cv'] = 'Summary\n- Prepared useful reports clearly.'
    supporting_reviewer(h, monkeypatch)
    response = call_handler(h)
    record = review.read_review_record(h.out, 'job-1')
    assert response['review']['verdict'] == record['verdict'] == 'PASS'
    assert response['review']['l0_findings'] == []
    assert record['items'] and all(item['verdict'] == 'SUPPORTED' for item in record['items'])
    written = review.canonical_cv_body((h.out/'job-1_ai_reviewed.md').read_text())
    assert handler_load(h) == written
    assert review.sha256_text(written) == record['binding']['rewrite_sha256']


def test_lock_free_after_writer_exception(handler_env):
    handler_env.writer.side_effect = RuntimeError('synthetic writer error')
    with pytest.raises(RuntimeError, match='synthetic writer error'):
        call_handler(handler_env)
    assert_lock_free()


def test_lock_free_after_reviewer_transport_error(handler_env, monkeypatch):
    monkeypatch.setattr(llm, '_api_key', lambda: 'synthetic')
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic reviewer transport error')
    monkeypatch.setattr(llm, '_call_gemini_model', fail)
    response = call_handler(handler_env)
    assert response['review']['verdict'] == 'UNCHECKED'
    assert response['review']['items'][0]['unchecked_detail'] == 'server_error'
    assert_lock_free()


def test_export_relative_master_ref_uses_base_dir(gate, monkeypatch):
    import io
    import zipfile
    from src import job_hunt_export as export
    (gate.base/'master.md').write_text(gate.profile.master_cv_text)
    gate.profile.master_cv_ref = 'master.md'
    gate.profile.master_cv_text = None
    elsewhere = gate.base/'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    job = NS(job_id='job-1', job_title='Analyst', company='Synthetic')
    monkeypatch.setattr(export, 'load_reviewed_job', lambda *a: job)
    monkeypatch.setattr(export, '_job_json', lambda *a: '{}')
    monkeypatch.setattr(export, 'load_cover_letter', lambda *a, **k: None)
    def missing(*args):
        raise FileNotFoundError('synthetic absent analysis')
    monkeypatch.setattr(export, 'load_job_analysis', missing)
    data, manifest = export.build_package('job-1', gate.profile, state_root=gate.base,
                                         base_dir=gate.base, policy=gate.policy)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.read(export.ENTRY_CV).decode() == gate.body + '\n'
    assert export.ENTRY_CV in manifest['included']


def test_handler_commit_order(handler_env, monkeypatch):
    supporting_reviewer(handler_env, monkeypatch)
    events = []
    delete, write_md, write_record = review.delete_review_record, ui_handlers.write_cv_text, review.write_review_record
    def deleting(*args, **kwargs):
        events.append('delete')
        return delete(*args, **kwargs)
    def markdown(*args, **kwargs):
        events.append('write .md')
        return write_md(*args, **kwargs)
    def recording(*args, **kwargs):
        events.append('write record')
        return write_record(*args, **kwargs)
    monkeypatch.setattr(review, 'delete_review_record', deleting)
    monkeypatch.setattr(ui_handlers, 'write_cv_text', markdown)
    monkeypatch.setattr(review, 'write_review_record', recording)
    assert call_handler(handler_env)['ok']
    assert events == ['delete', 'write .md', 'write record']


def test_handler_l0_finding_blocks_record_and_response(handler_env, monkeypatch):
    handler_env.writer.return_value[0]['reviewed_cv'] = 'Summary\n- Prepared 1500000 useful reports.'
    supporting_reviewer(handler_env, monkeypatch)
    response = call_handler(handler_env)
    record = review.read_review_record(handler_env.out, 'job-1')
    assert response['review']['verdict'] == record['verdict'] == 'BLOCKED'
    assert response['review']['l0_findings'] == record['l0_findings']
    finding = next(f for f in record['l0_findings'] if f['rule'] == 'L0-1')
    assert '1500000' in finding['text'] and 'e+' not in finding['text'].lower()


@pytest.mark.parametrize('text', ['', '   \n'])
def test_handler_empty_writer_creates_no_files_and_frees_lock(handler_env, text):
    handler_env.writer.return_value = ({'reviewed_cv': text, 'changes': []}, None, 'synthetic-writer')
    assert call_handler(handler_env) == {'ok': False, 'error': 'AI CV review failed'}
    assert handler_env.responder.send_json.call_args.kwargs['status'] == HTTPStatus.INTERNAL_SERVER_ERROR
    assert_lock_free()
    assert not (handler_env.out/'job-1_ai_reviewed.md').exists()
    assert not review.review_record_path(handler_env.out, 'job-1').exists()


def test_handler_uses_one_source_snapshot(handler_env, monkeypatch):
    h = handler_env
    master = h.config.profile_path.parent/'master.md'
    old = h.profile.master_cv_text
    master.write_text(old)
    h.profile.master_cv_text = None
    h.profile.master_cv_ref = 'master.md'
    received = []
    def writer(cv_text, *args):
        received.append(cv_text)
        master.write_text(old + '\nChanged on disk during writer call.')
        return {'reviewed_cv': 'Summary\n- Prepared useful reports clearly.', 'changes': []}, None, 'synthetic-writer'
    h.writer.side_effect = writer
    monkeypatch.setattr(review, 'run_blind_review', lambda *a, **k: dict(items=[],
        reviewer_model=review.REVIEWER_MODEL, prompt_version=review.REVIEW_PROMPT_VERSION))
    call_handler(h)
    record = review.read_review_record(h.out, 'job-1')
    assert received == [old]
    assert record['binding']['original_cv_sha256'] == review.sha256_text(received[0])
    assert handler_load(h) is None


def test_different_profile_id_falls_back(gate):
    gate.profile.candidate_id = 'other-profile'
    assert load(gate) == 'ordinary CV'


def test_symlink_review_record_falls_back(gate):
    path = review.review_record_path(gate.out, 'job-1')
    target = gate.base/'record.json'
    path.rename(target)
    path.symlink_to(target)
    assert review.read_review_record(gate.out, 'job-1') is None
    assert load(gate) == 'ordinary CV'


@pytest.mark.parametrize('newline', ['\r\n', '\r'])
def test_handler_normalizes_writer_line_endings(handler_env, monkeypatch, newline):
    h = handler_env
    h.writer.return_value[0]['reviewed_cv'] = newline.join(['Summary', '- Prepared useful reports clearly.'])
    supporting_reviewer(h, monkeypatch)
    original_review = review.run_blind_review
    seen = []
    def reviewer(*args, **kwargs):
        seen.append(args[4]['reviewed_cv'])
        return original_review(*args, **kwargs)
    monkeypatch.setattr(review, 'run_blind_review', reviewer)
    response = call_handler(h)
    assert response['review']['verdict'] == 'PASS'
    assert seen == ['Summary\n- Prepared useful reports clearly.']
    assert handler_load(h) == seen[0]
    assert '\r' not in (h.out/'job-1_ai_reviewed.md').read_bytes().decode()


def test_copied_review_and_markdown_do_not_bind_another_job(gate):
    assert load(gate) == gate.body
    (gate.out/'job-2.md').write_text('ordinary job 2 CV')
    (gate.out/'job-2_ai_reviewed.md').write_bytes((gate.out/'job-1_ai_reviewed.md').read_bytes())
    review.review_record_path(gate.out, 'job-2').write_bytes(review.review_record_path(gate.out, 'job-1').read_bytes())
    assert load_latest_tailored_cv('job-2', policy=gate.policy, profile=gate.profile,
                                   base_dir=gate.base) == 'ordinary job 2 CV'


def test_ai_reviewed_suffix_cannot_alias_another_jobs_rewrite(gate):
    review.delete_review_record(gate.out, 'job-1')
    assert load_latest_tailored_cv('job-1_ai_reviewed', policy=gate.policy, profile=gate.profile,
                                   base_dir=gate.base) is None


def test_l0_7_finding_record_is_valid_and_loads(gate):
    rec = record_for(gate.profile, gate.body, verdict='BLOCKED')
    rec['items'] = []
    rec['l0_findings'] = [asdict(review.Finding(
        0, 'L0-7', '- Supported 20 analysts across 5 sites.', 'BLOCKER',
        'numbers swapped; original line: - Supported 5 analysts across 20 sites.'))]
    raw_record(gate, rec)
    assert review.read_review_record(gate.out, 'job-1') == rec
    assert load(gate) == 'ordinary CV'  # BLOCKED: the AI rewrite loads only once approved
    rec['approval'] = dict(approved_at='2026-10-29T12:01:00+00:00', generation_id=rec['generation_id'],
                           rewrite_sha256=rec['binding']['rewrite_sha256'])
    raw_record(gate, rec)
    assert review.read_review_record(gate.out, 'job-1') == rec
    assert load(gate) == gate.body
    rec['verdict'] = 'PASS'  # an L0-7 BLOCKER cannot sit under a PASS verdict
    raw_record(gate, rec)
    assert review.read_review_record(gate.out, 'job-1') is None
