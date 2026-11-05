import json
import threading
import time
import urllib.error

import pytest
from src import job_hunt_explain_check as m


def reply(p=.8):
    return {'answers': {'supported': {'type': 'noul', 'noul': p}}}


def wait_idle(service):
    end = time.monotonic() + 2
    while service.active is not None and time.monotonic() < end:
        time.sleep(.005)
    assert service.active is None


def test_split_and_preserve():
    text = 'Rate 2.5 is good. Use e.g. SQL in U.K. teams.\nNext line!'
    rows = m.split_statements({'fit': text, 'action': 'Apply now.'})
    fit = [r for r in rows if r['section'] == 'fit']
    assert len(fit) == 3
    assert ''.join(r['text'] for r in fit) == text
    assert rows[-1]['reason'] == 'advice'
    rows = m.split_statements({'fit': 'x' * 601 + '\n' + 'Good. ' * 12})
    assert rows[0]['reason'] == 'limit'
    assert sum('reason' not in r for r in rows) == 9


def test_whitespace_never_becomes_a_statement():
    text = '. \n'.join(['One', 'Two', 'Three', 'Four', 'Five', 'Six']) + '.'
    rows = m.split_statements({'fit': text})
    assert len(rows) == 6
    assert all('reason' not in r for r in rows)
    assert all(r['text'].strip() for r in rows)
    assert ''.join(r['text'] for r in rows) == text
    rows = m.split_statements({'fit': '\n One. Two.\n'})
    assert [r['text'] for r in rows] == ['\n One. ', 'Two.\n']
    assert m.split_statements({'fit': ' \n ', 'risk': '\n'}) == []


def test_create_check_survives_a_concurrent_explain_for_the_same_job(monkeypatch):
    store = m.TokenStore()
    monkeypatch.setattr(m, 'TOKEN_STORE', store)
    real_create = store.create
    created, results, errors, fired = [], [], [], []

    def call(text):
        try:
            results.append(m.create_check('job', 'source', {'fit': text}))
        except Exception as exc:
            errors.append(exc)

    rival = threading.Thread(target=call, args=('Second.',))

    def create(*args, **kwargs):
        token = real_create(*args, **kwargs)
        created.append(token)
        if not fired:
            fired.append(True)
            # Force the interleaving: the rival explain runs right after this
            # token exists. With a lock held across create and the snapshot
            # read it blocks here and finishes afterwards instead.
            rival.start()
            rival.join(.2)
        return token

    monkeypatch.setattr(store, 'create', create)
    call('First.')
    rival.join(2)
    assert not rival.is_alive()
    assert errors == []
    assert len(created) == 2 and len(results) == 2
    by_token = {r['check_token']: r for r in results}
    assert set(by_token) == set(created)
    assert by_token[created[0]]['statements'][0]['text'] == 'First.'
    assert by_token[created[1]]['statements'][0]['text'] == 'Second.'
    assert store.get(created[1], 'job') is not None
    assert store.get(created[0], 'job') is None


def test_store():
    now = [0]
    store = m.TokenStore(lambda: now[0])
    first = store.create('a', 'source', {'fit': 'Yes.'})
    assert store.get(first, 'wrong') is None
    assert store.get('unknown', 'a') is None
    second = store.create('a', 'source', {})
    assert store.get(first, 'a') is None
    now[0] = 600
    assert store.get(second, 'a') is None
    for i in range(21):
        store.create(str(i), 'source', {})
    assert len(store.entries) == 20
    assert all(e['job_id'] != '0' for e in store.entries.values())
    token = store.create('big', 'é' * 4097, {'fit': 'Yes.', 'action': 'Apply.'})
    rows = store.get(token, 'big')['statements']
    assert rows[0]['reason'] == 'source_too_large'
    assert rows[1]['reason'] == 'advice'


@pytest.mark.parametrize('p,verdict', [(0,'could_not_confirm'), (.49,'could_not_confirm'), (.5,'ok'), (1,'ok')])
def test_parse(p, verdict):
    assert m.parse_response(reply(p)) == (p, verdict)


@pytest.mark.parametrize('value', [float('nan'),float('inf'),-1,1.1,True,'0.8'])
def test_bad_probability(value):
    with pytest.raises(m.ModelShapeError):
        m.parse_response(reply(value))


def test_missing_field_and_question():
    with pytest.raises(m.ModelShapeError):
        m.parse_response({})
    payload = m.build_request('source', 'section', 'statement')
    assert payload['state'] == 'SOURCE:\nsource\n\nSECTION (context only, not evidence):\nsection\n\nSTATEMENT TO CHECK:\nstatement'
    assert payload['model'] == m.MODEL
    assert payload['questions']['supported']['instructions'] == m.INSTRUCTIONS
    assert m.QUESTION_VERSION == 'explain-check-v1'


def test_fact_check():
    assert m.fact_check('Salary £50,000 SQL', '£50k SQL')['unsupported_numbers'] == []
    assert m.fact_check('50000', '£50k')['unsupported_numbers'] == []
    assert m.fact_check('SQL', 'SQL AWS 42') == {'unsupported_numbers': [42.0], 'unsupported_caps': ['AWS']}


def test_fence(monkeypatch):
    def socket_forbidden(*args, **kwargs):
        pytest.fail('transport reached opener')
    monkeypatch.setattr(m.urllib.request, 'build_opener', socket_forbidden)
    with pytest.raises(AssertionError, match='transport fence'):
        m._post_systemone({})


def test_worker_deadline_busy_late_and_retry(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    def transport(payload, timeout):
        entered.set()
        release.wait(2)
        return reply()
    service = m.ExplainCheckService(transport=transport)
    token = service.store.create('a','source',{'fit':'One. Two.'})
    result = service.check('a', token, tmp_path, .03)
    assert entered.is_set()
    assert result['state'] == 'partial'
    assert all(r['reason'] == 'time' for r in result['results'].values())
    assert service.check('a',token,tmp_path)['state'] == 'busy'
    release.set()
    wait_idle(service)
    log = json.loads((tmp_path/'logs/explain-check.jsonl').read_text())
    assert len(log['discarded_late_results']) == 1
    assert all(row['reason'] == 'time' for row in log['statements'])
    assert service.check('a',token,tmp_path)['state'] == 'done'
    wait_idle(service)


def test_stale_between_statements(tmp_path):
    service = m.ExplainCheckService()
    calls = []
    def transport(payload, timeout):
        calls.append(payload)
        service.store.create('a','new',{})
        return reply()
    service.transport = transport
    token = service.store.create('a','source',{'fit':'One. Two.'})
    assert service.check('a',token,tmp_path)['state'] == 'stale'
    assert len(calls) == 1
    wait_idle(service)
    assert service.check('a',token,tmp_path)['state'] == 'stale'


@pytest.mark.parametrize('error,reason', [(urllib.error.HTTPError(m.ENDPOINT,404,'missing',{},None),'model_unavailable'), (m.ModelShapeError(),'model_error')])
def test_worker_errors(tmp_path,error,reason):
    def transport(payload,timeout):
        raise error
    service = m.ExplainCheckService(transport=transport)
    token = service.store.create('a','source',{'fit':'One. Two.'})
    result = service.check('a',token,tmp_path)
    assert result['state'] == 'partial'
    assert all(r['reason'] == reason for r in result['results'].values())
    wait_idle(service)


def test_log_mode_fields_and_failure(tmp_path, caplog):
    service = m.ExplainCheckService(transport=lambda *a,**k: reply())
    token = service.store.create('a','source',{'fit':'SQL 42.'})
    assert service.check('a',token,tmp_path)['state'] == 'done'
    wait_idle(service)
    path = tmp_path/'logs/explain-check.jsonl'
    assert path.stat().st_mode & 0o777 == 0o600
    data = json.loads(path.read_text())
    assert {'run_id','job_id','time','model','model_digest','QUESTION_VERSION','threshold','source','statements','discarded_late_results'} <= data.keys()
    assert {'id','section','text','p','verdict','fact_check','seconds'} <= data['statements'][0].keys()
    bad = tmp_path/'file'
    bad.write_text('file')
    assert service.check('a',token,bad)['state'] == 'done'
    wait_idle(service)
    assert 'Could not write explain check log' in caplog.text


def test_injected_clock_deadline(tmp_path):
    now = [0]
    entered = threading.Event()
    release = threading.Event()
    def transport(payload, timeout):
        entered.set()
        release.wait(2)
        return reply()
    service = m.ExplainCheckService(transport=transport, clock=lambda: now[0])
    token = service.store.create('clock', 'source', m.split_statements('One.', '', ''))
    output = []
    thread = threading.Thread(target=lambda: output.append(service.check('clock', token, tmp_path, 90)))
    thread.start()
    assert entered.wait(1)
    now[0] = 91
    with service.condition:
        service.condition.notify_all()
    thread.join(1)
    assert output[0]['state'] == 'partial'
    assert service.check('clock', token, tmp_path)['state'] == 'busy'
    release.set()
    wait_idle(service)
