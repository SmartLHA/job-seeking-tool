"""Bounded, fail-closed Codex CLI transport for the blind CV reviewer."""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile

TESTED_CODEX_VERSIONS = ('0.166.0',)
DISABLED_FEATURES = (
    'shell_tool', 'unified_exec', 'browser_use', 'browser_use_external',
    'computer_use', 'in_app_browser', 'apps', 'plugins', 'memories', 'goals',
    'image_generation', 'multi_agent', 'view_image', 'skill_search',
    'skill_mcp_dependency_install',
)
REVIEW_OUTPUT_SCHEMA = {
    'type': 'object', 'properties': {'results': {
        'type': 'array', 'items': {
            'type': 'object', 'properties': {
                'id': {'type': 'string'},
                'verdict': {'type': 'string', 'enum': ['SUPPORTED', 'EXAGGERATED', 'UNSUPPORTED']},
                'evidence_quote': {'type': ['string', 'null']},
                'reason': {'type': 'string'},
            }, 'required': ['id', 'verdict', 'evidence_quote', 'reason'],
            'additionalProperties': False,
        },
    }}, 'required': ['results'], 'additionalProperties': False,
}


def _run(args, *, input=None, timeout, env):
    """Launch one isolated process group; reap the entire group on timeout."""
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=env,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def resolve_codex():
    """Return launcher paths as found, preserving symlink launcher directories."""
    codex_bin = os.environ.get('CODEX_BIN') or shutil.which('codex')
    node = shutil.which('node')
    if not codex_bin or not node:
        raise FileNotFoundError('Codex and node are required')
    return codex_bin, node


def codex_home():
    return Path(os.environ.get('CV_REVIEW_CODEX_HOME', '~/.codex-cv-reviewer')).expanduser()


def build_env(codex_bin, node, home=None, temp_dir=None):
    directories = [str(Path(codex_bin).absolute().parent),
                   str(Path(node).absolute().parent), '/usr/bin', '/bin']
    return {'PATH': os.pathsep.join(dict.fromkeys(directories)),
            'CODEX_HOME': str(home if home is not None else codex_home()),
            'TMPDIR': os.environ.get('TMPDIR') or str(temp_dir or tempfile.gettempdir())}


def build_exec_args(codex_bin, model, work_dir, schema_file, answer_file):
    args = [str(codex_bin), 'exec', '-s', 'read-only', '-C', str(work_dir),
            '--skip-git-repo-check', '--ephemeral', '--ignore-user-config']
    for feature in DISABLED_FEATURES:
        args.extend(['--disable', feature])
    return args + ['-c', 'web_search="disabled"', '-c', 'mcp_servers={}', '-m', model,
                   '-c', 'model_reasoning_effort="low"', '--output-schema', str(schema_file),
                   '--json', '-o', str(answer_file), '-']


def check_codex_ready(*, allow_untested_version=False):
    """Check home and local CLI version before every review; never raise."""
    try:
        home = codex_home()
        if (not home.is_dir() or home.stat().st_mode & 0o022
                or not (home / 'AGENTS.md').is_file()
                or (home / 'AGENTS.md').read_bytes() != b''
                or (home / 'config.toml').exists()):
            return 'server_error'
    except Exception:
        return 'server_error'
    try:
        codex_bin, node = resolve_codex()
        result = _run([codex_bin, '--version'], timeout=10,
                      env=build_env(codex_bin, node, home))
        version = re.fullmatch(r'codex-cli (\S+)\s*', result.stdout)
        if result.returncode or not version:
            return 'server_error'
        if not allow_untested_version and version.group(1) not in TESTED_CODEX_VERSIONS:
            return 'server_error'
        return None
    except (FileNotFoundError, PermissionError, OSError):
        return 'not_found'
    except Exception:
        return 'server_error'


def classify_outcome(returncode, stdout, answer):
    """Return a failure kind, or None for a complete successful turn stream."""
    active = False
    started = False
    valid = True
    last_turn = None
    failed = None
    last_error = ''
    try:
        for line in stdout.splitlines():
            if not line.startswith('{'):
                continue
            event = json.loads(line)
            kind = event.get('type')
            if kind == 'turn.started':
                valid = valid and not active
                active = started = True
                last_turn = kind
            elif kind == 'turn.completed':
                valid = valid and active
                active = False
                last_turn = kind
            elif kind == 'turn.failed':
                failed = event.get('error', {}).get('message', '')
                last_turn = kind
            elif kind == 'error':
                message = event.get('message', '')
                if not message.startswith('Reconnecting'):
                    last_error = message
    except (ValueError, TypeError, AttributeError):
        return 'server_error'
    if returncode == 0 and valid and started and not active and last_turn == 'turn.completed' and failed is None and answer.strip():
        return None
    message = failed if failed is not None else last_error
    if 'usage limit' in message.lower():
        return 'rate_limited'
    if any(part in message for part in ('401 Unauthorized', 'Not logged in',
                                        'not supported when using Codex with a ChatGPT account')):
        return 'not_found'
    return 'server_error'


def _failure(kind):
    # Deliberately omit provider output, prompt and exception details.
    return None, 'Codex reviewer: ' + kind, kind != 'timeout', kind


def call_codex_reviewer(prompt, model, schema, *, timeout=180):
    """Return (text, error, fallback, failure_kind), without leaking exceptions."""
    try:
        failure = check_codex_ready()
        if failure:
            return _failure(failure)
        codex_bin, node = resolve_codex()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / 'work'
            work.mkdir()
            schema_file, answer_file = root / 'schema.json', root / 'answer.txt'
            schema_file.write_text(json.dumps(schema), encoding='utf-8')
            args = build_exec_args(codex_bin, model, work, schema_file, answer_file)
            env = build_env(codex_bin, node, temp_dir=temporary)
            try:
                result = _run(args, input=prompt, timeout=timeout, env=env)
            except (FileNotFoundError, PermissionError, OSError):
                return _failure('not_found')
            answer = answer_file.read_text(encoding='utf-8') if answer_file.is_file() else ''
            failure = classify_outcome(result.returncode, result.stdout, answer)
            return _failure(failure) if failure else (answer, None, False, None)
    except subprocess.TimeoutExpired:
        return _failure('timeout')
    except Exception:
        return _failure('server_error')
