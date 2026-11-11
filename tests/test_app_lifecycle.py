"""Tests for scripts/app_lifecycle.py using disposable synthetic listeners only."""
from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "app_lifecycle.py"

SERVER = """
import signal, socket, sys, os
port, log, mode = int(sys.argv[1]), sys.argv[2], sys.argv[3]
def note(msg):
    with open(log, "a") as fh:
        fh.write(msg + " " + str(os.getpid()) + "\\n")
def on_int(*_):
    note("sigint")
    if mode != "ignore":
        sys.exit(0)
signal.signal(signal.SIGINT, on_int)
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", port)); s.listen(5)
note("started")
while True:
    signal.pause()
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def alive(pid: int) -> bool:
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(out) and not out.startswith("Z")


def wait_for(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        val = cond()
        if val:
            return val
        time.sleep(0.1)
    raise AssertionError("condition not met in time")


class Env:
    def __init__(self, tmp_path: Path):
        self.rt = tmp_path / "runtime"
        self.log = tmp_path / "server.log"
        self.script = tmp_path / "server.py"
        self.script.write_text(SERVER)
        self.port = free_port()
        self.procs: list[subprocess.Popen] = []

    def env(self, mode="exit", **extra):
        cmd = [sys.executable, str(self.script), str(self.port), str(self.log), mode]
        e = dict(os.environ, JOB_TOOL_RUNTIME_DIR=str(self.rt), JOB_TOOL_SERVER_CMD=json.dumps(cmd),
                 JOB_TOOL_STOP_TIMEOUT="3")
        e.pop("DRY_RUN", None)
        e.update(extra)
        return e

    def helper(self, action, mode="exit", **extra) -> subprocess.Popen:
        p = subprocess.Popen([sys.executable, str(HELPER), action, "--port", str(self.port)],
                             env=self.env(mode, **extra), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.procs.append(p)
        return p

    def record(self):
        try:
            return json.loads((self.rt / f"app-{self.port}.json").read_text())
        except (OSError, ValueError):
            return None

    def log_lines(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def start_owned(self, mode="exit") -> dict:
        self.helper("start", mode)
        return wait_for(lambda: self.record() and "started" in " ".join(self.log_lines()) and self.record())

    def listening(self) -> bool:
        with socket.socket() as s:
            return s.connect_ex(("127.0.0.1", self.port)) == 0


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    pids = {r["pid"] for r in [e.record()] if r}
    pids |= {int(l.split()[1]) for l in e.log_lines()}
    for pid in pids:
        if alive(pid):
            os.kill(pid, signal.SIGTERM)
    for p in e.procs:
        if p.poll() is None:
            p.send_signal(signal.SIGTERM)
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.send_signal(signal.SIGINT)
            p.wait(timeout=5)
    for pid in pids:
        wait_for(lambda pid=pid: not alive(pid), 5)


@pytest.fixture
def stranger(env):
    """An unrelated listener on the port (not started by the helper)."""
    p = subprocess.Popen([sys.executable, str(env.script), str(env.port), str(env.log), "exit"])
    wait_for(env.listening)
    yield p
    p.terminate()
    p.wait(timeout=5)


@pytest.mark.parametrize("action", ["start", "restart"])
def test_unrelated_listener_survives(env, stranger, action):
    p = env.helper(action)
    assert p.wait(timeout=20) != 0
    assert stranger.poll() is None and env.listening()
    assert "sigint" not in env.log_lines()[-1]
    assert not env.record()


def test_stale_record_dead_pid_is_retired_and_start_proceeds(env):
    env.rt.mkdir(parents=True)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (env.rt / f"app-{env.port}.json").write_text(json.dumps({"pid": dead.pid, "port": env.port}))
    env.helper("restart")
    rec = wait_for(lambda: (r := env.record()) and r["pid"] != dead.pid and r)
    assert wait_for(env.listening) and alive(rec["pid"])
    assert not any("sigint" in l for l in env.log_lines())


def test_reused_pid_is_not_signalled(env, stranger):
    sys.path.insert(0, str(ROOT / "scripts"))
    import app_lifecycle as lc
    ident = lc.identity(stranger.pid)
    assert ident
    for field in ("start_time", "command"):
        rec = dict(ident, pid=stranger.pid, port=env.port, **{field: "different"})
        env.rt.mkdir(parents=True, exist_ok=True)
        (env.rt / f"app-{env.port}.json").write_text(json.dumps(rec))
        assert env.helper("restart").wait(timeout=20) != 0
        assert env.helper("start").wait(timeout=20) != 0
        assert stranger.poll() is None
    assert not any("sigint" in l for l in env.log_lines())


def test_owned_restart_signals_old_and_starts_new(env):
    old = env.start_owned()
    r = env.helper("restart")
    new = wait_for(lambda: (x := env.record()) and x["pid"] != old["pid"] and x)
    wait_for(lambda: not alive(old["pid"]))
    assert wait_for(env.listening)
    assert f"sigint {old['pid']}" in env.log_lines()
    assert r.poll() is None  # new instance runs in the foreground of the restart call
    assert alive(new["pid"])


def test_owned_child_ignoring_sigint_is_not_killed(env):
    old = env.start_owned("ignore")
    r = env.helper("restart", "ignore")
    assert r.wait(timeout=20) != 0
    assert "did not stop" in r.stderr.read()
    assert alive(old["pid"]) and env.record()["pid"] == old["pid"]
    assert env.log_lines().count(f"sigint {old['pid']}") == 1


def test_concurrent_restarts_are_serialized(env):
    old = env.start_owned()
    a, b = env.helper("restart"), env.helper("restart")
    wait_for(lambda: len({l.split()[1] for l in env.log_lines() if l.startswith("started")}) >= 2)
    time.sleep(3)
    lines = env.log_lines()
    started = [int(l.split()[1]) for l in lines if l.startswith("started")]
    signalled = [int(l.split()[1]) for l in lines if l.startswith("sigint")]
    assert len(started) == len(set(started)) and old["pid"] in signalled
    assert len(signalled) == len(set(signalled))  # nobody signalled twice
    assert set(signalled) <= set(started)  # only helper-started instances were signalled
    assert len([p for p in started if alive(p)]) <= 1  # never two live instances
    assert not any("Traceback" in (p.stderr.read() if p.poll() is not None else "") for p in (a, b))


def test_dry_run_changes_nothing(env, stranger):
    for action in ("start", "restart"):
        p = env.helper(action, DRY_RUN="1")
        assert p.wait(timeout=20) == 0
        assert "DRY_RUN" in p.stdout.read()
    assert not env.rt.exists()
    assert env.log_lines() == ["started " + str(stranger.pid)]
    assert stranger.poll() is None


def test_dry_run_free_port_launches_nothing(env):
    p = env.helper("restart", DRY_RUN="1")
    assert p.wait(timeout=20) == 0
    assert not env.rt.exists() and not env.log.exists() and not env.listening()


def test_start_with_owned_instance_is_noop_and_prints_url(env):
    old = env.start_owned()
    p = env.helper("start")
    assert p.wait(timeout=20) == 0
    assert f"http://127.0.0.1:{env.port}" in p.stdout.read()
    assert alive(old["pid"]) and not any("sigint" in l for l in env.log_lines())
    assert env.record()["pid"] == old["pid"]


def test_record_permissions(env):
    env.start_owned()
    assert (env.rt.stat().st_mode & 0o777) == 0o700
    assert ((env.rt / f"app-{env.port}.json").stat().st_mode & 0o777) == 0o600


@pytest.mark.parametrize("name", ["start.command", "restart.sh"])
def test_scripts_have_no_blanket_kill(name):
    text = (ROOT / name).read_text()
    assert not re.search(r"pkill|killall|kill\s+-9|xargs\s+kill|SIGKILL", text)
    assert "app_lifecycle.py" in text


def test_helper_has_no_blanket_kill():
    code = HELPER.read_text()
    assert not re.search(r"pkill|killall|kill -9|xargs kill|SIGKILL|\.kill\(\)", code)
    assert re.findall(r"os\.kill\([^)]*\)", code) == ["os.kill(pid, signal.SIGINT)"]
