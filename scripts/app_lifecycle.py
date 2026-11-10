#!/usr/bin/env python3
"""Safe start/restart for the local server (owned-instance lifecycle).

Only an instance this helper launched (and can re-identify) is ever signalled,
and only with SIGINT. Nothing is killed by name or by port; there is no force-kill.

Usage: app_lifecycle.py {start,restart} --port N --host H --profile P [--open]
Env:   JOB_TOOL_RUNTIME_DIR (record dir), JOB_TOOL_SERVER_CMD (JSON argv, tests),
       JOB_TOOL_STOP_TIMEOUT (seconds, default 15), DRY_RUN=1.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*cmd: str) -> str:
    try:
        env = dict(os.environ, LC_ALL="C")
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def runtime_dir() -> Path:
    return Path(os.environ.get("JOB_TOOL_RUNTIME_DIR") or ROOT / "data" / "state" / "runtime")


def listener_pid(port: int) -> int | None:
    """PID listening on the TCP port, or None. Several listeners count as ambiguous (-1)."""
    out = _run("lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t")
    pids = {int(p) for p in out.split() if p.isdigit()}
    if not pids and not out:
        import re
        pids = {int(p) for p in re.findall(r"pid=(\d+)", _run("ss", "-H", "-ltnp", f"sport = :{port}"))}
    return None if not pids else (pids.pop() if len(pids) == 1 else -1)


def identity(pid: int) -> dict | None:
    """Start time, command line and cwd of a live process, or None if dead/unreadable."""
    stat = _run("ps", "-o", "stat=", "-p", str(pid)) if pid > 0 else ""
    if not stat or stat.startswith("Z"):
        return None
    start, command = _run("ps", "-o", "lstart=", "-p", str(pid)), _run("ps", "-o", "command=", "-p", str(pid))
    try:
        cwd = os.path.realpath(os.readlink(f"/proc/{pid}/cwd"))
    except OSError:
        cwd = next((l[1:] for l in _run("lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn").splitlines() if l.startswith("n")), "")
        cwd = os.path.realpath(cwd) if cwd else ""
    return {"start_time": start, "command": command, "cwd": cwd} if start and command and cwd else None


def read_record(port: int) -> dict | None:
    try:
        rec = json.loads((runtime_dir() / f"app-{port}.json").read_text())
        return rec if isinstance(rec, dict) else None
    except (OSError, ValueError):
        return None


def write_record(port: int, pid: int) -> None:
    d = runtime_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(d, 0o700)
    rec = dict(identity(pid) or {}, pid=pid, port=port, created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    tmp = d / f".app-{port}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(rec, fh)
    os.replace(tmp, d / f"app-{port}.json")


def remove_record(port: int, pid: int | None = None) -> None:
    rec = read_record(port)
    if pid is None or (rec and rec.get("pid") == pid):
        (runtime_dir() / f"app-{port}.json").unlink(missing_ok=True)


def verified_owned(port: int, lpid: int | None) -> dict | None:
    """The record, if it provably describes the live listener; else None."""
    rec = read_record(port)
    if not rec or lpid is None or lpid <= 0 or rec.get("pid") != lpid:
        return None
    now = identity(lpid)
    if now and all(now[k] == rec.get(k) for k in ("start_time", "command", "cwd")) and rec.get("port") == port:
        return rec
    return None


def server_cmd(args) -> list[str]:
    if os.environ.get("JOB_TOOL_SERVER_CMD"):
        return list(json.loads(os.environ["JOB_TOOL_SERVER_CMD"]))
    return [sys.executable, "-m", "src.job_hunt_ui", "--profile", args.profile,
            "--port", str(args.port), "--host", args.host]


def stop_owned(rec: dict, port: int) -> bool:
    """SIGINT the verified instance; wait for exit AND port release. Never force-kill."""
    pid = rec["pid"]
    os.kill(pid, signal.SIGINT)
    deadline = time.time() + float(os.environ.get("JOB_TOOL_STOP_TIMEOUT", "15"))
    while time.time() < deadline:
        if identity(pid) is None and listener_pid(port) is None:
            return True
        time.sleep(0.2)
    return False


def open_when_ready(url: str, port: int, pid: int) -> None:
    for _ in range(60):
        if listener_pid(port) == pid:
            webbrowser.open(url)
            return
        time.sleep(0.5)


def foreground(child: subprocess.Popen, port: int) -> int:
    def forward(signum, _frame):
        try:
            child.send_signal(signal.SIGINT)
        except OSError:
            pass
    signal.signal(signal.SIGINT, forward)
    signal.signal(signal.SIGTERM, forward)
    code = child.wait()
    remove_record(port, child.pid)
    return code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["start", "restart"])
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--profile", default="data/mic_profile.json")
    ap.add_argument("--open", action="store_true", help="open the browser")
    args = ap.parse_args(argv)
    port, url = args.port, f"http://127.0.0.1:{args.port}"

    lpid = listener_pid(port)
    if os.environ.get("DRY_RUN") == "1":
        owned = verified_owned(port, lpid)
        state = ("owned instance running" if owned else "free" if lpid is None else "held by another process")
        plan = ("restart: SIGINT the owned instance, then start" if owned and args.action == "restart" else
                "report already running" if owned else "refuse, signal nothing" if lpid is not None else "start the server")
        print(f"DRY_RUN: {args.action} on port {port}: port is {state}; would {plan}. Nothing changed.")
        return 0

    d = runtime_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(d, 0o700)
    with open(d / f"app-{port}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # one start/restart operation at a time
        lpid = listener_pid(port)
        owned = verified_owned(port, lpid)
        if lpid is not None and not owned:
            print(f"Port {port} is in use by a process this tool did not start (or cannot be verified). "
                  "Nothing was stopped. Free the port or choose another PORT.", file=sys.stderr)
            return 1
        if owned and args.action == "start":
            print(f"The app is already running at {url}.")
            print("To restart it, close the Terminal window that started it (or press Ctrl+C there) and start again.")
            if args.open:
                webbrowser.open(url)
            return 0
        if owned:
            print(f"Stopping the running instance (pid {owned['pid']}) with SIGINT...")
            if not stop_owned(owned, port):
                print("The instance did not stop in time. It was left running; nothing was force-killed.", file=sys.stderr)
                return 1
        remove_record(port)  # stale or just-stopped record; port is free here
        child = subprocess.Popen(server_cmd(args), cwd=ROOT)
        write_record(port, child.pid)
    print(f"Starting server -> {url}")
    print("(Keep this window open. Close it or press Ctrl+C to stop the server.)")
    if args.open:
        threading.Thread(target=open_when_ready, args=(url, port, child.pid), daemon=True).start()
    return foreground(child, port)


if __name__ == "__main__":
    sys.exit(main())
