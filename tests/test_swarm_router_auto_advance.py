from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
VIEWER_DIR = REPO_ROOT / "viewer"
for path in (SRC_DIR, VIEWER_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import swarm_router
import shared_bus


def test_import_is_side_effect_free_with_unwritable_home(tmp_path: Path) -> None:
    home = tmp_path / "unwritable-home"
    home.mkdir()
    home.chmod(0o500)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PYTHONPATH"] = os.pathsep.join((str(VIEWER_DIR), str(REPO_ROOT)))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import swarm_router"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    finally:
        home.chmod(0o700)

    assert result.returncode == 0, result.stderr
    assert not (home / ".openclaw").exists()


def test_initializer_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    fake_shared_bus = SimpleNamespace(add_swarm_tables=lambda: calls.append("migrate"))

    monkeypatch.setattr(swarm_router, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(swarm_router, "_SWARM_LOG", tmp_path / "logs" / "swarm.log")
    monkeypatch.setattr(swarm_router, "_sb", fake_shared_bus)
    monkeypatch.setattr(swarm_router, "recover_orphaned_pipelines", lambda: calls.append("recover"))
    monkeypatch.setattr(swarm_router, "_initialized", False)
    monkeypatch.setattr(swarm_router, "_hdlr", None)

    swarm_router.initialize_swarm_router()
    swarm_router.initialize_swarm_router()

    handler = swarm_router._hdlr
    try:
        assert calls == ["migrate", "recover"]
        assert handler is not None
        assert (tmp_path / "logs" / "swarm.log").is_file()
        assert sum(item is handler for item in swarm_router._log.handlers) == 1
    finally:
        if handler is not None:
            swarm_router._log.removeHandler(handler)
            handler.close()


def test_viewer_startup_initializes_router_before_listening(monkeypatch) -> None:
    import viewer_server

    events: list[str] = []
    fake_router = SimpleNamespace(
        initialize_swarm_router=lambda: events.append("initialize"),
    )

    class FakeSocket:
        def setsockopt(self, *_args) -> None:
            pass

        def bind(self, *_args) -> None:
            events.append("bind")

        def listen(self, *_args) -> None:
            events.append("listen")

        def accept(self):
            events.append("accept")
            raise KeyboardInterrupt

    monkeypatch.setitem(sys.modules, "swarm_router", fake_router)
    monkeypatch.setattr(viewer_server, "_ensure_multi_chat_dirs", lambda: None)
    monkeypatch.setattr(viewer_server.socket, "socket", lambda *_args: FakeSocket())

    viewer_server.main()

    assert events == ["initialize", "bind", "listen", "accept"]


def _make_db(db_path: Path, *, current_stage: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE pipeline_runs (session_id TEXT PRIMARY KEY, uuid TEXT, current_stage TEXT, current_agent TEXT, updated_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE stage_handoff_docs (pipeline_run_id TEXT, stage TEXT, version INTEGER, generated_at TEXT, producer_agent TEXT, completed_at TEXT, attempt_no INTEGER DEFAULT 1)"
    )
    conn.execute(
        "INSERT INTO pipeline_runs VALUES ('sess-1', 'pipe-1', ?, 'dev', datetime('now'))",
        (current_stage,),
    )
    conn.execute(
        "INSERT INTO stage_handoff_docs (pipeline_run_id, stage, version, generated_at, producer_agent, completed_at, attempt_no) VALUES ('pipe-1', ?, 1, datetime('now', '-5 minutes'), 'dev', NULL, 1)",
        (current_stage,),
    )
    conn.commit()
    conn.close()
    shared_bus.add_swarm_tables(db_path)


def test_handy_completion_advances_pipeline_to_qa(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "shared_memory.db"
    _make_db(db_path, current_stage="build")
    monkeypatch.setattr(shared_bus, "DB_PATH", db_path)
    monkeypatch.setattr(swarm_router._sb, "DB_PATH", db_path)

    swarm_router._advance_pipeline_stage_if_needed(
        "pipe-1",
        [{"agent_role": "coder", "status": "done", "execution_id": "exec-1"}],
    )

    conn = sqlite3.connect(db_path)
    stage = conn.execute("SELECT current_stage, current_agent FROM pipeline_runs WHERE session_id = 'sess-1'").fetchone()
    events = conn.execute(
        "SELECT stage, event_type, agent_name FROM stage_events WHERE pipeline_run_id = 'pipe-1' ORDER BY id"
    ).fetchall()
    conn.close()

    assert stage == ("qa", "handy")
    assert events == [("build", "stage_completed", "dev"), ("qa", "stage_started", "handy")]


def test_scout_completion_advances_pipeline_to_ship(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "shared_memory.db"
    _make_db(db_path, current_stage="qa")
    monkeypatch.setattr(shared_bus, "DB_PATH", db_path)
    monkeypatch.setattr(swarm_router._sb, "DB_PATH", db_path)

    swarm_router._advance_pipeline_stage_if_needed(
        "pipe-1",
        [{"agent_role": "qa", "status": "done", "execution_id": "exec-qa"}],
    )

    conn = sqlite3.connect(db_path)
    stage = conn.execute("SELECT current_stage, current_agent FROM pipeline_runs WHERE session_id = 'sess-1'").fetchone()
    events = conn.execute(
        "SELECT stage, event_type, agent_name FROM stage_events WHERE pipeline_run_id = 'pipe-1' ORDER BY id"
    ).fetchall()
    conn.close()

    assert stage == ("ship", "scout")
    assert events == [("qa", "stage_completed", "dev"), ("ship", "stage_started", "scout")]
