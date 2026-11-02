"""Offline transport contracts; no provider binary may run."""
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest
from src import job_hunt_codex as c

REAL_RUN = c._run

FIXTURES = Path(__file__).parent / 'fixtures' / 'codex_reviewer'
SUCCESS = '{"type":"turn.started"}\n{"type":"turn.completed"}'


@pytest.fixture
def ready(monkeypatch, tmp_path):
    home = tmp_path / 'home'
    home.mkdir(mode=0o700)
    (home / 'AGENTS.md').write_text('')
    monkeypatch.setenv('CV_REVIEW_CODEX_HOME', str(home))
    monkeypatch.delenv('CODEX_BIN', raising=False)
    monkeypatch.setattr(c.shutil, 'which', lambda name: '/fake/bin/' + name)
    return home


def install(fake_codex_run, *, events=SUCCESS, answer='{"results":[]}', code=0, error=None, version='0.166.0'):
    calls = []
    def fake(args, **kwargs):
        calls.append((args, kwargs))
        if '--version' in args:
            return subprocess.CompletedProcess(args, 0, 'codex-cli ' + version + '\n', '')
        if error:
            raise error
        if answer is not None:
            Path(args[args.index('-o') + 1]).write_text(answer)
        return subprocess.CompletedProcess(args, code, events, 'private stderr')
    fake_codex_run(fake)
    return calls


def call():
    return c.call_codex_reviewer('private prompt', 'gpt-6-luna', c.REVIEW_OUTPUT_SCHEMA)


def test_command_environment_schema_and_stdin(ready, fake_codex_run, monkeypatch):
    monkeypatch.setenv('GOOGLE_API_KEY', 'private')
    calls = install(fake_codex_run)
    assert call() == ('{"results":[]}', None, False, None)
    args, kwargs = calls[1]
    assert calls[0][0] == ['/fake/bin/codex', '--version']
    assert calls[0][1]['timeout'] == 10
    assert args[:5] == ['/fake/bin/codex', 'exec', '-s', 'read-only', '-C']
    assert all(flag in args for flag in ('--skip-git-repo-check', '--ephemeral', '--ignore-user-config', '--output-schema', '--json', '-o'))
    assert [args[i+1] for i, value in enumerate(args) if value == '--disable'] == list(c.DISABLED_FEATURES)
    assert all(value in args for value in ('web_search="disabled"', 'mcp_servers={}', 'model_reasoning_effort="low"'))
    assert not set(args) & {'--dangerously-bypass-approvals-and-sandbox', '--approve-for-me', '--dangerously-bypass-hook-trust', 'workspace-write', 'danger-full-access', '--add-dir', '--worktree', '--enable'}
    assert args[-1] == '-'
    assert 'private prompt' not in args and kwargs['input'] == 'private prompt'
    assert kwargs['timeout'] == 180 and 'shell' not in kwargs
    assert set(kwargs['env']) == {'PATH', 'CODEX_HOME', 'TMPDIR'}
    assert kwargs['env']['CODEX_HOME'] == str(ready)


def test_symlink_launcher_and_node_path(tmp_path, monkeypatch):
    launchers, native, nodes = [tmp_path / p for p in ('launchers', 'native', 'nodes')]
    for path in (launchers, native, nodes):
        path.mkdir()
    (native / 'codex').write_text('#!/usr/bin/env node')
    (launchers / 'codex').symlink_to(native / 'codex')
    (nodes / 'node').write_text('fake')
    monkeypatch.setattr(c.shutil, 'which', lambda name: str((launchers if name == 'codex' else nodes) / name))
    monkeypatch.delenv('CODEX_BIN', raising=False)
    codex, node = c.resolve_codex()
    assert codex == str(launchers / 'codex')
    assert c.build_env(codex, node)['PATH'].split(':')[:2] == [str(launchers), str(nodes)]


@pytest.mark.parametrize('damage', ['missing', 'group', 'world', 'agents_missing', 'agents_content', 'config'])
def test_home_rejects_without_launch(ready, damage, fake_codex_run):
    calls = install(fake_codex_run)
    if damage == 'missing':
        ready.rename(ready.with_name('away'))
    elif damage in ('group', 'world'):
        ready.chmod(0o720 if damage == 'group' else 0o702)
    elif damage == 'agents_missing':
        (ready / 'AGENTS.md').rename(ready / 'old')
    elif damage == 'agents_content':
        (ready / 'AGENTS.md').write_text('instructions')
    else:
        (ready / 'config.toml').write_text('')
    assert call()[3] == 'server_error'
    assert calls == []


@pytest.mark.parametrize('missing', ['node', 'codex'])
def test_missing_binary(ready, monkeypatch, missing):
    monkeypatch.setattr(c.shutil, 'which', lambda name: None if name == missing else '/fake/' + name)
    assert call()[3] == 'not_found'


@pytest.mark.parametrize('error,kind', [(FileNotFoundError(), 'not_found'), (PermissionError(), 'not_found'), (OSError(), 'not_found'), (subprocess.TimeoutExpired('codex', 10), 'server_error'), (RuntimeError('private'), 'server_error')])
def test_version_failures(ready, fake_codex_run, error, kind):
    calls = []
    def fake(*args, **kwargs):
        calls.append(kwargs)
        raise error
    fake_codex_run(fake)
    assert call()[3] == kind
    assert len(calls) == 1 and calls[0]['timeout'] == 10


def test_version_checked_each_time_and_untested_blocked(ready, fake_codex_run):
    calls = install(fake_codex_run, version='9.9.9')
    assert call()[3] == 'server_error'
    assert call()[3] == 'server_error'
    assert len(calls) == 2
    assert c.check_codex_ready(allow_untested_version=True) is None


@pytest.mark.parametrize('filename,code,kind', [('events-gpt-6-luna.jsonl', 0, None), ('events-nologin.jsonl', 1, 'not_found'), ('events-badmodel.jsonl', 1, 'not_found'), ('events-usage-limit-2026-10-31.jsonl', 1, 'rate_limited')])
def test_recorded_outcomes(ready, fake_codex_run, filename, code, kind):
    install(fake_codex_run, events=(FIXTURES / filename).read_text(), code=code)
    assert call()[3] == kind


@pytest.mark.parametrize('events,answer,code,kind', [
    ('{"type":"error","message":"Reconnecting 1/5"}\n' + SUCCESS, 'yes', 0, None),
    (SUCCESS, None, 0, 'server_error'), (SUCCESS, 'yes', 1, 'server_error'),
    (SUCCESS + '\n{bad', 'yes', 0, 'server_error'),
    (SUCCESS + '\n{"type":"turn.started"}', 'yes', 0, 'server_error'),
    ('{"type":"turn.started"}\n' + SUCCESS, 'yes', 0, 'server_error'),
    (SUCCESS + '\n{"type":"turn.failed","error":{"message":"failed"}}', 'yes', 0, 'server_error'),
    ('{"type":"error","message":"usage limit"}\n{"type":"error","message":"Reconnecting 2/5"}', 'yes', 1, 'rate_limited'),
])
def test_synthetic_outcomes(ready, fake_codex_run, events, answer, code, kind):
    install(fake_codex_run, events=events, answer=answer, code=code)
    assert call()[3] == kind


@pytest.mark.parametrize('error,kind', [(subprocess.TimeoutExpired('codex', 180), 'timeout'), (FileNotFoundError(), 'not_found'), (RuntimeError('private'), 'server_error')])
def test_exec_exceptions_never_escape(ready, fake_codex_run, error, kind):
    install(fake_codex_run, error=error)
    result = call()
    assert result[3] == kind and result[2] == (kind != 'timeout')
    assert 'private' not in result[1]


def test_run_process_contract_and_group_timeout(monkeypatch, fake_codex_run):
    # Exercise the real wrapper only with an entirely fake Popen.
    process = Mock(pid=123, returncode=0)
    process.communicate.side_effect = [subprocess.TimeoutExpired('fake', 5), ('', '')]
    popen, kill = Mock(return_value=process), Mock()
    monkeypatch.setattr(c.subprocess, 'Popen', popen)
    monkeypatch.setattr(c.os, 'killpg', kill)
    with pytest.raises(subprocess.TimeoutExpired):
        REAL_RUN(['fake'], input='secret', timeout=5, env={})
    assert popen.call_args.kwargs['start_new_session'] is True
    assert 'shell' not in popen.call_args.kwargs
    assert process.communicate.call_args_list[0].kwargs == {'input': 'secret', 'timeout': 5}
    kill.assert_called_once_with(123, c.signal.SIGKILL)


def test_schema_strict_standard_library():
    schema = json.loads(json.dumps(c.REVIEW_OUTPUT_SCHEMA))
    assert schema['required'] == ['results'] and schema['additionalProperties'] is False
    item = schema['properties']['results']['items']
    assert set(item['required']) == set(item['properties']) == {'id', 'verdict', 'evidence_quote', 'reason'}
    assert item['additionalProperties'] is False
    assert item['properties']['evidence_quote']['type'] == ['string', 'null']
    assert item['properties']['verdict']['enum'] == ['SUPPORTED', 'EXAGGERATED', 'UNSUPPORTED']


def test_codex_bin_override_preserved(ready, monkeypatch, fake_codex_run):
    monkeypatch.setenv('CODEX_BIN', '/chosen/symlink/codex')
    calls = install(fake_codex_run)
    assert call()[3] is None
    assert calls[0][0][0] == calls[1][0][0] == '/chosen/symlink/codex'
    assert calls[1][1]['env']['PATH'].split(':')[0] == '/chosen/symlink'


def test_real_run_success(monkeypatch):
    process = Mock(returncode=0)
    process.communicate.return_value = ('stdout', 'stderr')
    monkeypatch.setattr(c.subprocess, 'Popen', Mock(return_value=process))
    result = REAL_RUN(['fake'], input='private', timeout=5, env={'PATH': '/fake'})
    assert (result.returncode, result.stdout, result.stderr) == (0, 'stdout', 'stderr')


def test_only_explicit_selfcheck_may_allow_untested_version():
    import ast
    root = Path(c.__file__).parent.parent
    allowed = root / 'scripts' / 'codex_reviewer_selfcheck.py'
    paths = [*sorted((root / 'src').rglob('*.py')),
             *sorted((root / 'scripts').rglob('*.py'))]
    assert paths
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if (keyword.arg == 'allow_untested_version'
                            and isinstance(keyword.value, ast.Constant)
                            and keyword.value.value is True):
                        assert path == allowed, str(path)


@pytest.mark.parametrize('location', ['temp', 'file', 'env'])
def test_internal_errors_are_redacted_server_error(ready, fake_codex_run, monkeypatch, location):
    install(fake_codex_run)
    def broken(*args, **kwargs):
        raise RuntimeError('private CV content')
    if location == 'temp':
        monkeypatch.setattr(c.tempfile, 'TemporaryDirectory', broken)
    elif location == 'file':
        monkeypatch.setattr(c.Path, 'write_text', broken)
    else:
        monkeypatch.setattr(c, 'build_env', broken)
    assert call() == (None, 'Codex reviewer: server_error', True, 'server_error')


def test_refusing_fence_records_swallowed_launch(ready, codex_transport_fence):
    assert call()[3] == 'server_error'
    assert len(codex_transport_fence) == 1
    codex_transport_fence.clear()


def test_completed_turn_allows_non_turn_events():
    assert c.classify_outcome(0, SUCCESS + '\n{"type":"item.completed"}', 'answer') is None



def test_schema_validates_reply_example_and_rejects_unknown_verdict():
    # A deliberately bounded standard-library validator for the schema vocabulary
    # used by REVIEW_OUTPUT_SCHEMA, not a replacement for the CV item validator.
    def validate(value, schema):
        types = schema.get('type')
        types = types if isinstance(types, list) else [types]
        matches = {'object': isinstance(value, dict), 'array': isinstance(value, list),
                   'string': isinstance(value, str), 'null': value is None}
        if not any(matches.get(kind, False) for kind in types):
            return False
        if 'enum' in schema and value not in schema['enum']:
            return False
        if isinstance(value, dict):
            properties = schema.get('properties', {})
            if not set(schema.get('required', ())).issubset(value):
                return False
            if schema.get('additionalProperties') is False and set(value) - set(properties):
                return False
            return all(validate(item, properties[key]) for key, item in value.items())
        if isinstance(value, list):
            return all(validate(item, schema['items']) for item in value)
        return True

    example = {'results': [{'id': 's-0', 'verdict': 'SUPPORTED',
                           'evidence_quote': 'verbatim source quote',
                           'reason': 'explanation'}]}
    assert validate(example, c.REVIEW_OUTPUT_SCHEMA)
    example['results'][0]['verdict'] = 'UNKNOWN'
    assert not validate(example, c.REVIEW_OUTPUT_SCHEMA)
    example['results'][0].update(verdict='UNSUPPORTED', evidence_quote=None)
    assert validate(example, c.REVIEW_OUTPUT_SCHEMA)
    example['results'][0]['unexpected'] = 'extra'
    assert not validate(example, c.REVIEW_OUTPUT_SCHEMA)


def test_run_forwards_empty_working_directory_without_prompt(tmp_path, monkeypatch):
    process = Mock(returncode=0)
    process.communicate.return_value = ('[]', '')
    popen = Mock(return_value=process)
    monkeypatch.setattr(c.subprocess, 'Popen', popen)
    REAL_RUN(['fake', 'debug', 'prompt-input', 'probe'], timeout=10, env={}, cwd=str(tmp_path))
    assert popen.call_args.kwargs['cwd'] == str(tmp_path)
    assert process.communicate.call_args.kwargs == {'input': None, 'timeout': 10}
