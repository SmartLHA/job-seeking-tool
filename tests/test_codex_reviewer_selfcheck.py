"""Recorded and synthetic self-check evidence; never execute the live self-check."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from scripts import codex_reviewer_selfcheck as sc

FIXTURES = Path(__file__).parent / 'fixtures/codex_reviewer'
P4 = (FIXTURES / 'events4.jsonl').read_text()
ANSWER = (FIXTURES / 'answer4.txt').read_text()


def analyze(stdout=P4, answer=ANSWER, render='[]', files=(), code=0, canary='synthetic-secret'):
    return sc.analyze_checks(render, code, stdout, answer, canary, files)


def test_recorded_p4_passes_all_four_checks():
    assert analyze() == {1: True, 2: True, 3: True, 4: True}


def test_recorded_p3_fails_event_check():
    assert not analyze(stdout=(FIXTURES / 'events3.jsonl').read_text())[3]


@pytest.mark.parametrize('answer', ['{}', 'not json', json.dumps(dict(read_ok=1, file_content='', web_ok=False,
                                                                  write_ok=False, tools_listed=[], notes=''))])
def test_schema_invalid_answer_fails_check_two(answer):
    assert not analyze(answer=answer)[2]


def test_non_success_run_fails_check_two():
    assert not analyze(code=1)[2]


@pytest.mark.parametrize('kind', ['command_execution', 'file_change', 'web_search'])
def test_tool_escape_items_fail_check_three(kind):
    event = json.dumps({'type': 'item.completed', 'item': {'id': 'other', 'type': kind}})
    assert not analyze(stdout=P4 + '\n' + event)[3]


def listing_events():
    return [json.loads(line) for line in P4.splitlines() if line.startswith('{')]


@pytest.mark.parametrize('mutation', ['missing_resources', 'missing_templates', 'unfinished', 'error', 'nonempty', 'other'])
def test_mcp_listing_contract(mutation):
    events = listing_events()
    if mutation.startswith('missing_'):
        tool = 'list_mcp_resources' if mutation == 'missing_resources' else 'list_mcp_resource_templates'
        events = [e for e in events if e.get('item', {}).get('tool') != tool]
    else:
        completed = next(e for e in events if e['type'] == 'item.completed'
                         and e.get('item', {}).get('tool') == 'list_mcp_resources')
        if mutation == 'unfinished':
            events.remove(completed)
        elif mutation == 'error':
            completed['item']['error'] = 'failure'
        elif mutation == 'nonempty':
            completed['item']['result']['content'][0]['text'] = '{"resources": ["present"]}'
        elif mutation == 'other':
            completed['item']['tool'] = 'read_mcp_resource'
    assert not analyze(stdout='\n'.join(json.dumps(e) for e in events))[3]


def test_canary_in_events_or_answer_fails_check_three():
    assert not analyze(stdout=P4 + '\nsynthetic-secret')[3]
    assert not analyze(answer=ANSWER + 'synthetic-secret')[3]


def test_file_in_working_directory_fails_check_four():
    assert not analyze(files=['x.txt'])[4]


@pytest.mark.parametrize('content,expected', [('', True), ('\n', True), ('Do something', False)])
def test_loaded_agents_instructions(content, expected):
    render = json.dumps([{'role': 'user', 'content': [{'type': 'input_text',
                        'text': '# AGENTS.md instructions\n<INSTRUCTIONS>' + content + '</INSTRUCTIONS>'}]}])
    assert analyze(render=render)[1] is expected


def test_selfcheck_requires_consent_before_readiness(monkeypatch):
    def forbidden(**kwargs):
        pytest.fail('readiness called without consent')
    monkeypatch.setattr(sc.codex, 'check_codex_ready', forbidden)
    with pytest.raises(SystemExit) as exc:
        sc.main([])
    assert exc.value.code == 2


def test_mocked_main_exact_prompt_input_arguments(fake_codex_run, monkeypatch):
    import subprocess
    calls = []
    monkeypatch.setattr(sc.codex, 'check_codex_ready', lambda **kw: None)
    monkeypatch.setattr(sc.codex, 'resolve_codex', lambda: ('/fake/codex', '/fake/node'))
    def fake(args, **kwargs):
        calls.append((args, kwargs))
        if '--version' in args:
            return subprocess.CompletedProcess(args, 0, 'codex-cli 0.166.0', '')
        if 'prompt-input' in args:
            assert list(Path(kwargs['cwd']).iterdir()) == []
            assert 'input' not in kwargs
            return subprocess.CompletedProcess(args, 0, '[]', '')
        Path(args[args.index('-o') + 1]).write_text(ANSWER)
        return subprocess.CompletedProcess(args, 0, P4, '')
    fake_codex_run(fake)
    assert sc.main(['--yes']) == 0
    expected = ['/fake/codex', 'debug', 'prompt-input']
    for feature in sc.codex.DISABLED_FEATURES:
        expected += ['--disable', feature]
    expected += ['-c', 'web_search="disabled"', '-c', 'mcp_servers={}', '-c', 'model="gpt-6-luna"', 'probe']
    assert calls[1][0] == expected
    assert calls[1][1]['env'] == calls[2][1]['env']
    assert calls[1][1]['cwd'] == calls[2][0][calls[2][0].index('-C') + 1]
