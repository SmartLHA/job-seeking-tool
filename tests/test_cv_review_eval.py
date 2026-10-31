"""Offline synthetic reviewer eval contracts; never call the provider."""
import json
from pathlib import Path
import pytest
from scripts import cv_review_eval as ev
from src import job_hunt_llm

CASES = Path(__file__).parent / 'fixtures/cv_review_eval'
NUMBERS_CASES = Path(__file__).parent / 'fixtures/cv_review_eval_numbers'


@pytest.fixture(autouse=True)
def no_cloud(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('Unexpected cloud transport')
    monkeypatch.setattr(job_hunt_llm, '_call_gemini_model', blocked)


def test_schema_and_selected_labels():
    assert len(list(CASES.glob('*.json'))) == 15
    for case in ev.load_cases(CASES):
        assert {'id', 'description', 'original_cv', 'rewrite', 'profile', 'job_skills', 'labels'} <= case.keys()
        assert set(case['profile']) == {'years_experience', 'skills', 'target_roles', 'industries'}
        assert case['labels']['expected_overall'] in {'PASS', 'NEEDS_EDIT', 'BLOCKED'}
        labels = case['labels']['expected_items']
        assert all(x['expected'] in ev.CLASSES[:3] for x in labels)
        selected = [i['text'] for i in ev.select_review_items(case['original_cv'], case['rewrite'])]
        assert selected == [x['statement'] for x in labels], case['id']


def test_numbers_fixtures_hold_the_spec_cases():
    # Spec Fix 3 F-B3: three cases in their own folder, so the main set stays 15 files / 19 calls.
    assert len(list(NUMBERS_CASES.glob('*.json'))) == 3
    cases = {c['id']: c for c in ev.load_cases(NUMBERS_CASES)}
    expected = {
        'percent-swap': ('Summary\n- Cut costs by 15% and errors by 40%.',
                         'Summary\n- Cut costs by 40% and errors by 15%.',
                         'BLOCKED', '- Cut costs by 40% and errors by 15%.', 'UNSUPPORTED'),
        'number-reformat': ('Summary\n- Supported five analysts.', 'Summary\n- Supported 5 analysts.',
                            'PASS', '- Supported 5 analysts.', 'SUPPORTED'),
        'lower-bound': ('Summary\n- Supported 20 analysts.', 'Summary\n- Supported over a dozen analysts.',
                        'PASS', '- Supported over a dozen analysts.', 'SUPPORTED'),
    }
    assert set(cases) == set(expected)
    for cid, (original, rewrite, overall, statement, verdict) in expected.items():
        case = cases[cid]
        assert (case['original_cv'], case['rewrite']) == (original, rewrite)
        assert case['labels']['expected_overall'] == overall
        assert case['labels']['expected_l0'] == []
        assert case['labels']['expected_items'] == [{'statement': statement, 'expected': verdict}]
        assert [i['text'] for i in ev.select_review_items(original, rewrite)] == [statement]
        assert set(case['profile']) == {'years_experience', 'skills', 'target_roles', 'industries'}
    # Ids stay unique when the live check copies these next to main-set cases.
    assert not set(cases) & {c['id'] for c in ev.load_cases(CASES)}


def test_numbers_dry_run_l0_matches_expected(tmp_path):
    def forbidden(prompt):
        pytest.fail('Dry run invoked transport')
    rows, report = ev.run(ev.load_cases(NUMBERS_CASES), dry_run=True, out_dir=tmp_path, transport=forbidden)
    assert len(rows) == 3
    assert not [r for r in rows if r['mismatch']]
    assert all(r['expected_l0'] == r['actual_l0'] == [] for r in rows)


def test_dry_report_no_transport(tmp_path):
    def forbidden(prompt):
        pytest.fail('Dry run invoked transport')
    rows, report = ev.run(ev.load_cases(CASES), dry_run=True, out_dir=tmp_path, transport=forbidden)
    assert not [r for r in rows if r['mismatch']]
    text = report.read_text()
    assert ev.WARNING in text
    assert 'Statement |' not in text


def test_handmade_metrics():
    m = ev.metrics([('SUPPORTED', 'EXAGGERATED'), ('EXAGGERATED', 'UNSUPPORTED'),
                    ('UNSUPPORTED', 'UNCHECKED'), ('SUPPORTED', 'SUPPORTED')])
    assert (m['recall'], m['precision'], m['unchecked_rate']) == ('0.500', '0.500', '0.250')
    assert m['confusion']['UNSUPPORTED', 'UNCHECKED'] == 1
    empty = ev.metrics([])
    assert (empty['recall'], empty['precision'], empty['unchecked_rate']) == ('n/a', 'n/a', 'n/a')
    assert ev.metrics([('SUPPORTED', 'SUPPORTED')])['precision'] == 'n/a'


def test_fake_live_report(tmp_path):
    case = next(c for c in ev.load_cases(CASES) if c['id'] == 'clean-rephrase')
    def fake(prompt):
        return json.dumps({'results': [{'id': 's-0', 'verdict': 'SUPPORTED',
                         'evidence_quote': 'Helped teams document business needs.', 'reason': 'faithful'}]})
    rows, report = ev.run([case], dry_run=False, out_dir=tmp_path, transport=fake)
    assert rows[0]['actual'] == 'PASS'
    text = report.read_text()
    assert 'Item recall: n/a; precision: n/a; UNCHECKED rate: 0.000' in text
    assert '| SUPPORTED | 1 | 0 | 0 | 0 |' in text
    assert case['labels']['expected_items'][0]['statement'] in text
    assert case['original_cv'] not in text


def test_mode_required():
    with pytest.raises(SystemExit) as exc:
        ev.main([])
    assert exc.value.code != 0


def test_source_separates_preferences():
    case = ev.load_cases(CASES)[0]
    evidence, context = ev.build_source(case)
    assert 'Years experience: 5' in evidence
    assert 'Profile skills:' in evidence
    assert 'Programme Director' not in evidence
    assert 'Target roles (preference, not experience): Programme Director' in context


def test_no_contact_patterns():
    import re
    email = re.compile(r'[A-Za-z0-9_.+-]+\x40[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
    phone = re.compile(r'(?<!\d)(?:\+\d[\d ()-]{8,}\d|0\d[\d ()-]{8,}\d)(?!\d)')
    for file in [*CASES.glob('*.json'), *NUMBERS_CASES.glob('*.json'), Path(__file__)]:
        text = file.read_text()
        assert not email.search(text), file.name
        assert not phone.search(text), file.name


# --- C4 fix F1-F3: --use-cloud loads the project .env and fails fast without a key ---

FAKE_KEY = 'fake-key-for-tests'


@pytest.fixture
def fake_dotenv(monkeypatch):
    """Stand-in dotenv module: records calls, never reads a real .env file."""
    import sys
    import types
    calls = []
    module = types.ModuleType('dotenv')
    module.load_dotenv = lambda *args, **kwargs: calls.append((args, kwargs))
    monkeypatch.setitem(sys.modules, 'dotenv', module)
    return calls


class RunCalls(list):
    """dry_run flag of each stubbed run() call; the pacing keywords are in .kwargs."""
    def __init__(self):
        super().__init__()
        self.kwargs = []


@pytest.fixture
def stub_run(monkeypatch, tmp_path):
    """Replace ev.run so main() never reaches the reviewer; records the dry_run flag and pacing keywords."""
    seen = RunCalls()
    def fake_run(cases, *, dry_run, out_dir, transport=None, pace=ev.DEFAULT_PACE,
                 retry_wait=ev.DEFAULT_RETRY_WAIT, sleep=None, reviewer_model=None):
        seen.append(dry_run)
        seen.kwargs.append(dict(pace=pace, retry_wait=retry_wait, sleep=sleep))
        return [], tmp_path / 'stub-report.md'
    monkeypatch.setattr(ev, 'run', fake_run)
    return seen


def test_use_cloud_loads_project_env(monkeypatch, fake_dotenv, stub_run, tmp_path, capsys):
    monkeypatch.setattr(job_hunt_llm, '_api_key', lambda: FAKE_KEY)
    rc = ev.main(['--use-cloud', '--cases', str(CASES), '--out-dir', str(tmp_path / 'out')])
    assert rc == 0
    assert fake_dotenv == [((ev.ROOT / '.env',), {})]
    assert stub_run == [False]
    captured = capsys.readouterr()
    assert FAKE_KEY not in captured.out + captured.err


def test_dry_run_does_not_load_env(monkeypatch, fake_dotenv, stub_run, tmp_path):
    def forbidden():
        pytest.fail('Dry run looked up the API key')
    monkeypatch.setattr(job_hunt_llm, '_api_key', forbidden)
    rc = ev.main(['--dry-run', '--cases', str(CASES), '--out-dir', str(tmp_path / 'out')])
    assert rc == 0
    assert fake_dotenv == []
    assert stub_run == [True]


def test_use_cloud_without_key_fails_fast(monkeypatch, fake_dotenv, stub_run, tmp_path, capsys):
    monkeypatch.setattr(job_hunt_llm, '_api_key', lambda: None)
    out_dir = tmp_path / 'out'
    rc = ev.main(['--use-cloud', '--cases', str(CASES), '--out-dir', str(out_dir)])
    assert rc != 0
    assert fake_dotenv == [((ev.ROOT / '.env',), {})]
    assert stub_run == []
    assert not out_dir.exists()
    captured = capsys.readouterr()
    assert captured.out == ''
    lines = captured.err.strip().splitlines()
    assert len(lines) == 1
    assert 'GOOGLE_API_KEY' in lines[0] and 'GEMINI_API_KEY' in lines[0]


def test_use_cloud_tolerates_missing_dotenv_package(monkeypatch, stub_run, tmp_path, capsys):
    import sys
    monkeypatch.setitem(sys.modules, 'dotenv', None)  # makes `from dotenv import ...` raise ImportError
    monkeypatch.setattr(job_hunt_llm, '_api_key', lambda: FAKE_KEY)
    assert ev.main(['--use-cloud', '--cases', str(CASES), '--out-dir', str(tmp_path / 'out')]) == 0
    assert stub_run == [False]
    monkeypatch.setattr(job_hunt_llm, '_api_key', lambda: None)
    assert ev.main(['--use-cloud', '--cases', str(CASES), '--out-dir', str(tmp_path / 'out')]) != 0
    assert stub_run == [False]


# --- C4 fix 2 P1-P5: pacing, one retry and a clean rate-limit stop (no network, no real sleep) ---

def pick(*ids):
    """Fixture cases in the given order."""
    by_id = {c['id']: c for c in ev.load_cases(CASES)}
    return [by_id[i] for i in ids]


def script_gemini(monkeypatch, outcomes):
    """Replace the Gemini helper with one scripted outcome per call; returns the prompts sent.

    'ok' answers every sent item UNSUPPORTED (valid for any case); any other value is the
    failure kind the helper reports, e.g. 'rate_limited'. A call beyond the script fails the test.
    """
    import re
    monkeypatch.setattr(job_hunt_llm, '_api_key', lambda: FAKE_KEY)
    prompts = []
    def helper(prompt, *args, **kwargs):
        if len(prompts) >= len(outcomes):
            pytest.fail('More reviewer calls than scripted')
        outcome = outcomes[len(prompts)]
        prompts.append(prompt)
        if outcome != 'ok':
            return None, 'failure', False, outcome
        nonce = re.search(r'<<<DATA-(\w+)>>>', prompt).group(1)
        blocks = re.findall(r'<<<DATA-' + nonce + r'>>>\n(.*?)\n<<<END-' + nonce + r'>>>', prompt, re.S)
        items = json.loads(next(b.split('\n', 1)[1] for b in blocks if b.startswith('REVIEW_ITEMS\n')))
        reply = {'results': [{'id': i['id'], 'verdict': 'UNSUPPORTED', 'evidence_quote': None,
                              'reason': 'scripted'} for i in items]}
        return json.dumps(reply), None, False, None
    monkeypatch.setattr(job_hunt_llm, '_call_gemini_model', helper)
    return prompts


def live(cases, tmp_path, sleeps, pace=3.0, retry_wait=9.0):
    return ev.run(cases, dry_run=False, out_dir=tmp_path, pace=pace, retry_wait=retry_wait, sleep=sleeps.append)


def test_pacing_between_consecutive_calls_not_before_first(monkeypatch, tmp_path):
    prompts = script_gemini(monkeypatch, ['ok', 'ok', 'ok'])
    sleeps = []
    rows, report = live(pick('clean-rephrase', 'changed-date', 'new-title'), tmp_path, sleeps, pace=7.5)
    assert len(prompts) == 3
    assert sleeps == [7.5, 7.5]
    assert not any(r['not_run'] for r in rows)


def test_dry_run_never_waits(tmp_path):
    sleeps = []
    rows, report = ev.run(ev.load_cases(CASES), dry_run=True, out_dir=tmp_path, pace=7.5,
                          retry_wait=9.0, sleep=sleeps.append)
    assert sleeps == []
    assert len(rows) == 19 and not any(r['not_run'] for r in rows)


def test_zero_pace_and_retry_wait_never_call_sleep(monkeypatch, tmp_path):
    script_gemini(monkeypatch, ['ok', 'rate_limited', 'ok'])
    sleeps = []
    live(pick('clean-rephrase', 'changed-date'), tmp_path, sleeps, pace=0, retry_wait=0)
    assert sleeps == []


@pytest.mark.parametrize('first', ['rate_limited', 'server_error'])
def test_retry_once_then_second_result_is_recorded(first, monkeypatch, tmp_path):
    prompts = script_gemini(monkeypatch, [first, 'ok'])
    sleeps = []
    rows, report = live(pick('deleted-qualifier'), tmp_path, sleeps)
    assert len(prompts) == 2
    assert sleeps == [9.0]
    assert rows[0]['detail'] == '' and not rows[0]['not_run']
    text = report.read_text()
    assert 'UNCHECKED rate: 0.000' in text          # the retry's answer, not the failed first call
    assert '| EXAGGERATED | 0 | 0 | 1 | 0 |' in text  # scripted 'ok' answers UNSUPPORTED


@pytest.mark.parametrize('kind', ['timeout', 'bad_json'])
def test_other_details_are_not_retried(kind, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(job_hunt_llm, '_api_key', lambda: FAKE_KEY)
    def helper(*args, **kwargs):
        calls.append(kind)
        return ('not json', None, False, None) if kind == 'bad_json' else (None, 'failure', False, kind)
    monkeypatch.setattr(job_hunt_llm, '_call_gemini_model', helper)
    sleeps = []
    rows, report = live(pick('clean-rephrase'), tmp_path, sleeps)
    assert len(calls) == 1
    assert sleeps == []
    assert rows[0]['detail'] == kind and not rows[0]['not_run']


def test_repeated_rate_limit_stops_the_run(monkeypatch, tmp_path):
    prompts = script_gemini(monkeypatch, ['ok', 'rate_limited', 'rate_limited'])
    sleeps = []
    cases = pick('deleted-qualifier', 'changed-date', 'new-title', 'clean-rephrase')
    rows, report = live(cases, tmp_path, sleeps)
    assert len(prompts) == 3                                  # case 1 once, case 2 twice, nothing after
    assert sleeps == [3.0, 9.0]                               # pace before case 2, then the retry wait
    assert [r['actual'] == 'NOT_RUN' for r in rows] == [False, True, True, True]
    assert [r['not_run'] for r in rows] == [False, True, True, True]
    assert [r['detail'] for r in rows] == ['', 'rate_limited', '', '']
    text = report.read_text()
    assert 'Run stopped: 1 of 4 cases ran; stopped on a repeated rate limit' in text
    assert 'which limit is UNVERIFIED' in text
    assert 'NOT_RUN: changed-date, new-title, clean-rephrase' in text
    # The one run case mismatches its label (scripted UNSUPPORTED gives BLOCKED); NOT_RUN counts as neither.
    assert 'Cases including variants: 4; matches: 0; mismatches: 1' in text
    # Metrics come from case 1 alone: its one EXAGGERATED item came back UNSUPPORTED.
    assert 'Item recall: 1.000; precision: 1.000; UNCHECKED rate: 0.000' in text
    assert cases[0]['labels']['expected_items'][0]['statement'] in text
    for skipped in cases[1:]:
        assert skipped['labels']['expected_items'][0]['statement'] not in text
    assert '| changed-date | BLOCKED | NOT_RUN | rate_limited |' in text
    assert '| new-title | ' in text and 'NOT_RUN' in text.split('| new-title | ')[1].split('\n')[0]


def test_stop_on_first_case_prints_na_metrics(monkeypatch, tmp_path):
    prompts = script_gemini(monkeypatch, ['rate_limited', 'rate_limited'])
    rows, report = live(pick('clean-rephrase', 'changed-date'), tmp_path, [])
    assert len(prompts) == 2
    assert all(r['not_run'] for r in rows)
    text = report.read_text()
    assert 'Run stopped: 0 of 2 cases ran' in text
    assert 'Item recall: n/a; precision: n/a; UNCHECKED rate: n/a' in text
    assert 'Cases including variants: 2; matches: 0; mismatches: 0' in text


def test_server_error_twice_keeps_unchecked_and_continues(monkeypatch, tmp_path):
    prompts = script_gemini(monkeypatch, ['server_error', 'server_error', 'ok', 'ok'])
    sleeps = []
    rows, report = live(pick('clean-rephrase', 'changed-date', 'new-title'), tmp_path, sleeps)
    assert len(prompts) == 4
    assert sleeps == [9.0, 3.0, 3.0]                          # retry wait, then pace before cases 2 and 3
    assert not any(r['not_run'] for r in rows)
    assert (rows[0]['actual'], rows[0]['detail']) == ('UNCHECKED', 'server_error')
    assert [r['detail'] for r in rows[1:]] == ['', '']
    text = report.read_text()
    assert '| clean-rephrase | PASS | UNCHECKED | server_error |' in text
    assert 'Run stopped' not in text


@pytest.mark.parametrize('first, second', [('rate_limited', 'server_error'), ('server_error', 'rate_limited')])
def test_mixed_failures_do_not_stop_the_run(first, second, monkeypatch, tmp_path):
    # Only two rate limits in a row stop the run; a 503 on either attempt does not.
    prompts = script_gemini(monkeypatch, [first, second, 'ok'])
    rows, report = live(pick('clean-rephrase', 'changed-date'), tmp_path, [])
    assert len(prompts) == 3
    assert [r['not_run'] for r in rows] == [False, False]
    assert rows[0]['detail'] == second


def test_main_exits_3_on_rate_limit_stop_and_still_writes_report(monkeypatch, fake_dotenv, tmp_path, capsys):
    cases_dir = tmp_path / 'cases'
    cases_dir.mkdir()
    for file in sorted(CASES.glob('*.json'))[:4]:
        (cases_dir / file.name).write_text(file.read_text())
    total = len(ev.load_cases(cases_dir))
    prompts = script_gemini(monkeypatch, ['ok', 'rate_limited', 'rate_limited'])
    out_dir = tmp_path / 'out'
    rc = ev.main(['--use-cloud', '--cases', str(cases_dir), '--out-dir', str(out_dir),
                  '--pace', '0', '--retry-wait', '0'])
    assert rc == 3
    assert len(prompts) == 3
    reports = list(out_dir.glob('report-*.md'))
    assert len(reports) == 1
    assert f'Run stopped: 1 of {total} cases ran' in reports[0].read_text()
    out = capsys.readouterr().out
    assert f'Run stopped: 1 of {total} cases ran' in out and f'report: {reports[0]}' in out


def test_main_exits_0_when_every_case_runs(monkeypatch, fake_dotenv, tmp_path):
    cases_dir = tmp_path / 'cases'
    cases_dir.mkdir()
    (cases_dir / 'one.json').write_text(next(CASES.glob('*clean-rephrase*.json')).read_text())
    prompts = script_gemini(monkeypatch, ['rate_limited', 'ok'])
    rc = ev.main(['--use-cloud', '--cases', str(cases_dir), '--out-dir', str(tmp_path / 'out'),
                  '--pace', '0', '--retry-wait', '0'])
    assert rc == 0 and len(prompts) == 2


def test_pace_and_retry_wait_flags_reach_run(stub_run, tmp_path):
    ev.main(['--dry-run', '--cases', str(CASES), '--out-dir', str(tmp_path / 'out')])
    assert stub_run.kwargs[-1] == dict(pace=15.0, retry_wait=65.0, sleep=None)
    ev.main(['--dry-run', '--cases', str(CASES), '--out-dir', str(tmp_path / 'out'),
             '--pace', '2.5', '--retry-wait', '0'])
    assert stub_run.kwargs[-1] == dict(pace=2.5, retry_wait=0.0, sleep=None)


@pytest.mark.parametrize('flag', ['--pace', '--retry-wait'])
@pytest.mark.parametrize('value', ['-1', '-0.5', 'nan', 'inf', 'abc'])
def test_bad_pace_values_rejected(flag, value, stub_run, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        ev.main(['--dry-run', '--cases', str(CASES), '--out-dir', str(tmp_path / 'out'), flag, value])
    assert exc.value.code == 2
    assert stub_run == []
    assert flag in capsys.readouterr().err


def test_help_lists_pace_flags(capsys):
    with pytest.raises(SystemExit) as exc:
        ev.main(['--help'])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert '--pace' in out and '--retry-wait' in out
