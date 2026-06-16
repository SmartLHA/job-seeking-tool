"""
Swarm Router — Persistent Coordinator for Multi-Agent Parallelism

Detects /swarm <task> commands in Telegram, creates pipeline DB rows,
spawns agents via sessions_spawn(), polls for completion, sends Telegram
summary on done/failed/partial.

Must be imported in main session to activate.
Calls add_swarm_tables() and recover_orphaned_pipelines() on import.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ── Paths ──────────────────────────────────────────────────────────────────────

WORKSPACE_ROOT = Path.home() / ".openclaw" / "workspace"
SRC_DIR = WORKSPACE_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

# ── Logging ────────────────────────────────────────────────────────────────────

LOG_DIR = Path.home() / ".openclaw" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_SWARM_LOG = LOG_DIR / "swarm.log"

_log = logging.getLogger("swarm_router")
_log.setLevel(logging.DEBUG)
_hdlr = logging.FileHandler(_SWARM_LOG)
_hdlr.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_log.addHandler(_hdlr)


def _log_info(msg: str) -> None:
    _log.info(msg)
    print(f"[swarm] {msg}", flush=True)


def _log_err(msg: str) -> None:
    _log.error(msg)
    print(f"[swarm] ERROR: {msg}", flush=True)


# ── Late imports — verify OpenClaw tools available ─────────────────────────────

try:
    from openclaw.api import sessions_spawn, sessions_list, subagents
    _OPENCLAW_AVAILABLE = True
except Exception as e:
    _OPENCLAW_AVAILABLE = False
    _log_err(f"OpenClaw tools not available: {e}")

try:
    import telegram as _telegram_mod
    _TELEGRAM_AVAILABLE = True
except Exception:
    _TELEGRAM_AVAILABLE = False

try:
    from src import shared_bus as _sb
except Exception as e:
    _log_err(f"shared_bus not available: {e}")
    _sb = None


# ── Config ─────────────────────────────────────────────────────────────────────

PIPELINE_TIMEOUT_S = 300   # 5 minutes hard limit
POLL_INTERVAL_S = 2        # poll agent_executions every 2s
LIVENESS_INTERVAL_S = 30  # sessions_list every 30s
MAX_ACTIVE_PIPELINES = 2   # beyond this, new pipelines queue

# Agent role → OpenClaw agent mapping
_ROLE_TO_AGENT = {
    "researcher": "dev",
    "coder":      "dev",
    "qa":         "qa",
    "reviewer":   "wiser",
    "analyst":    "dev",
    "handy":      "dev",
    "scout":      "qa",
    "wiser":      "wiser",
    "helper":     "helper",
}

# Default roles when none specified
DEFAULT_ROLES = ["researcher", "coder", "qa"]


# ── Swappable Telegram sender ──────────────────────────────────────────────────

_telegram_send_fn: Optional[callable] = None


def set_telegram_sender(fn: callable) -> None:
    """Override the Telegram send function (for testing / different backends)."""
    global _telegram_send_fn
    _telegram_send_fn = fn


def _send_telegram(text: str) -> None:
    if _telegram_send_fn is not None:
        _telegram_send_fn(text)
        return
    # Default: try openclaw.telegram integration if available
    try:
        from openclaw.integrations.telegram import send_message
        send_message(text)
    except Exception:
        _log_err(f"Telegram send failed — no sender configured and default not available")


# ── Shared state (protected by lock) ──────────────────────────────────────────

_active_pipelines: dict[str, dict[str, Any]] = {}  # pipeline_run_id → state
_state_lock = threading.Lock()


# ── Swarm Command Parsing ──────────────────────────────────────────────────────

_ROLES_PATTERN = re.compile(
    r"with\s+([a-zA-Z_, ]+?)(?:\s+|$)",
    re.IGNORECASE
)

_STOP_PATTERN = re.compile(
    r"^/swarm\s+stop\s+([a-zA-Z0-9\-]+)",
    re.IGNORECASE
)

_TASK_PATTERN = re.compile(
    r"^/swarm\s+(.+)",
    re.IGNORECASE
)


def _parse_swarm_command(text: str) -> tuple[Optional[str], Optional[list[str]], Optional[str]]:
    """
    Parse a Telegram /swarm message.
    Returns (task_key, agent_roles, stop_pipeline_id) or (None, None, None).
    """
    text = text.strip()

    # Check for stop
    m_stop = _STOP_PATTERN.match(text)
    if m_stop:
        return None, None, m_stop.group(1)

    # Check for general swarm
    m_task = _TASK_PATTERN.match(text)
    if not m_task:
        return None, None, None

    task_body = m_task.group(1).strip()

    # Extract "with role1, role2" clause
    m_roles = _ROLES_PATTERN.search(task_body)
    if m_roles:
        roles_str = m_roles.group(1)
        agent_roles = [r.strip().lower() for r in roles_str.split(",") if r.strip()]
        task_key = _TASK_PATTERN.match(text[:m_roles.start()].strip()).group(1) if _TASK_PATTERN.match(text[:m_roles.start()].strip()) else task_body[:m_roles.start()].strip()
    else:
        agent_roles = list(DEFAULT_ROLES)
        task_key = task_body

    task_key = task_key.strip()
    if not task_key:
        return None, None, None

    return task_key, agent_roles, None


# ── Core Router Functions ──────────────────────────────────────────────────────

def _build_agent_prompt(role: str, task_key: str, pipeline_run_id: str) -> str:
    """Build the initial agent prompt with swarm context."""
    return (
        f"You are a {role} agent in a swarm pipeline.\n"
        f"Pipeline ID: {pipeline_run_id}\n"
        f"Task: {task_key}\n\n"
        f"When you complete your work, write the result to shared_memory.db "
        f"agent_executions with status='done' and result_ref='msg:<message_id>'\n"
        f"or result_ref='file:<path>' for artifacts.\n"
        f"Report failures with status='failed' and result_ref='spawn_error:<detail>'.\n"
        f"Keep your session alive until the router marks the pipeline complete."
    )


def init_pipeline(task_key: str, agent_roles: list[str], router_session_key: str) -> str:
    """
    Create a swarm pipeline: insert pipeline_runs + agent_executions rows.
    Returns pipeline_run_id (uuid string).
    """
    if _sb is None:
        raise RuntimeError("shared_bus not available")

    # Migration: ensure swarm tables exist
    try:
        _sb.add_swarm_tables()
    except Exception as e:
        _log_err(f"add_swarm_tables failed: {e}")

    pipeline_run_id = _sb.init_pipeline(
        task_key=task_key,
        agent_roles=agent_roles,
        router_session_key=router_session_key,
    )
    _log_info(f"Pipeline {pipeline_run_id} created for task='{task_key}' roles={agent_roles}")
    return pipeline_run_id


def start_pipeline(pipeline_run_id: str, agents: list[dict[str, Any]]) -> None:
    """
    Spawn agents for a pipeline via sessions_spawn().
    Updates agent_executions rows from 'queued' → 'spawning' → 'running'.
    Stores session_key in agent_executions.session_key.
    """
    if not _OPENCLAW_AVAILABLE:
        _log_err("sessions_spawn not available — cannot start pipeline")
        return

    if _sb is None:
        _log_err("shared_bus not available")
        return

    for agent_info in agents:
        exec_id = agent_info["execution_id"]
        role = agent_info["agent_role"]
        task_key = agent_info.get("task_key", "")
        openclaw_agent = _ROLE_TO_AGENT.get(role, "dev")

        # Update to spawning
        try:
            _sb.update_agent_status(exec_id, "spawning")
        except Exception as e:
            _log_err(f"update_agent_status(spawning) failed: {e}")

        # Spawn via OpenClaw sessions_spawn
        try:
            result = sessions_spawn(
                agent=openclaw_agent,
                prompt=_build_agent_prompt(role, task_key, pipeline_run_id),
            )
            if result and result.get("sessionKey"):
                session_key = result["sessionKey"]
                _log_info(f"Spawned {role} agent session_key={session_key}")

                # Store session_key in DB
                try:
                    conn = _sb._conn()
                    try:
                        now_ts = int(datetime.now().timestamp() * 1000)
                        conn.execute("BEGIN IMMEDIATE")
                        conn.execute("""
                            UPDATE agent_executions
                            SET session_key = ?, status = 'running', heartbeat_at = ?, updated_at = ?
                            WHERE execution_id = ?
                        """, (session_key, now_ts, now_ts, exec_id))
                        conn.execute("COMMIT")
                    except Exception:
                        conn.execute("ROLLBACK")
                        raise
                    finally:
                        conn.close()
                except Exception as e:
                    _log_err(f"Failed to store session_key for {exec_id}: {e}")

            else:
                # Spawn returned but no session key
                _sb.update_agent_status(exec_id, "failed", f"spawn_error: no session_key returned")
                _log_err(f"Spawn {role} returned no sessionKey: {result}")
        except Exception as e:
            _sb.update_agent_status(exec_id, "failed", f"spawn_error: {e}")
            _log_err(f"spawn error for {role}: {e}")


def poll_agent_executions(pipeline_run_id: str) -> list[dict[str, Any]]:
    """Return current agent_executions rows for a pipeline."""
    if _sb is None:
        return []
    return _sb.get_agent_executions(pipeline_run_id)


def check_liveness(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Check sessions_list() for each running agent's session_key.
    Update status to 'failed' if session not found or completed/failed.
    Returns updated agent list.
    """
    if not _OPENCLAW_AVAILABLE or _sb is None:
        return agents

    try:
        live_sessions = sessions_list()
        live_keys = {s.get("sessionKey") for s in live_sessions} if live_sessions else set()

        updated_agents = []
        for agent in agents:
            if agent["status"] not in ("running", "spawning"):
                updated_agents.append(agent)
                continue

            sk = agent.get("session_key")
            if not sk:
                # No session key yet — keep as is
                updated_agents.append(agent)
                continue

            if sk not in live_keys:
                # Session dead — mark as failed
                try:
                    _sb.update_agent_status(agent["execution_id"], "failed", "orphan: session not in sessions_list")
                    agent = dict(agent)
                    agent["status"] = "failed"
                    _log_info(f"Agent {agent['agent_role']} marked failed (session not found)")
                except Exception as e:
                    _log_err(f"liveness update failed for {agent['execution_id']}: {e}")
            else:
                # Session alive — update heartbeat
                try:
                    conn = _sb._conn()
                    try:
                        now_ts = int(datetime.now().timestamp() * 1000)
                        conn.execute("BEGIN IMMEDIATE")
                        conn.execute("UPDATE agent_executions SET heartbeat_at = ?, updated_at = ? WHERE execution_id = ?",
                                     (now_ts, now_ts, agent["execution_id"]))
                        conn.execute("COMMIT")
                    except Exception:
                        conn.execute("ROLLBACK")
                        raise
                    finally:
                        conn.close()
                except Exception:
                    pass  # heartbeat is best-effort

            updated_agents.append(agent)

        return updated_agents
    except Exception as e:
        _log_err(f"sessions_list() call failed: {e}")
        return agents


def _advance_pipeline_stage_if_needed(pipeline_run_id: str, agents: list[dict[str, Any]]) -> None:
    """Advance pipeline stage from completed Handy/Scout work when possible."""
    if _sb is None or not agents:
        return

    try:
        conn = _sb._conn()
        try:
            row = conn.execute(
                "SELECT session_id, current_stage FROM pipeline_runs WHERE COALESCE(uuid, session_id) = ? OR session_id = ?",
                (pipeline_run_id, pipeline_run_id),
            ).fetchone()
        finally:
            conn.close()
    except Exception as e:
        _log_err(f"pipeline stage lookup failed for {pipeline_run_id}: {e}")
        return

    if row is None:
        return

    session_id = row[0]
    current_stage = row[1] or "spec"
    role_status = {agent.get("agent_role"): agent.get("status") for agent in agents}

    transitions: list[tuple[str, str]] = []
    if role_status.get("coder") == "done" and current_stage in {"spec", "design", "build", "review"}:
        transitions.append(("qa", "handy"))
    if role_status.get("qa") == "done" and current_stage == "qa":
        transitions.append(("ship", "scout"))

    for next_stage, agent_name in transitions:
        try:
            changed = _sb.advance_pipeline_stage(session_id, next_stage, agent_name)
            if changed:
                current_stage = next_stage
        except Exception as e:
            if "forward-only" not in str(e):
                _log_err(f"advance_pipeline_stage failed for {pipeline_run_id} -> {next_stage}: {e}")


def _build_summary(pipeline_run_id: str, agents: list[dict[str, Any]], elapsed_s: float) -> str:
    """Build a Telegram-formatted summary from agent results."""
    lines = []
    status_icon = {"done": "✅", "failed": "❌", "timed_out": "⏱", "cancelled": "🚫", "running": "🔄"}

    for agent in agents:
        icon = status_icon.get(agent["status"], "?")
        ref = agent.get("result_ref", "")
        # Summarise message refs
        if ref and ref.startswith("msg:"):
            lines.append(f"{icon} {agent['agent_role']} — msg:{ref[4:12]}...")
        elif ref:
            lines.append(f"{icon} {agent['agent_role']} — {ref[:60]}")
        else:
            lines.append(f"{icon} {agent['agent_role']} — {agent['status']}")

    stage = "?"
    if _sb:
        stage = _sb.derive_pipeline_stage(agents)

    status = "active"
    if all(a["status"] == "done" for a in agents):
        status = "done"
    elif any(a["status"] in ("failed", "timed_out") for a in agents):
        status = "partial"
    elif any(a["status"] == "cancelled" for a in agents):
        status = "cancelled"

    header = {
        "done":       f"🐝 Swarm Complete: {agents[0].get('task_key', '?')} ({elapsed_s:.0f}s)",
        "partial":    f"🐝 Swarm Partial: {agents[0].get('task_key', '?')} ({elapsed_s:.0f}s)",
        "cancelled":  f"🐝 Swarm Cancelled: {agents[0].get('task_key', '?')}",
        "active":     f"🐝 Swarm Active: {agents[0].get('task_key', '?')} ({elapsed_s:.0f}s)",
    }.get(status, f"🐝 Swarm Status: {status}")

    return header + "\n" + "\n".join(lines) + f"\n📊 Stage: {stage}"


def run_pipeline_loop(
    pipeline_run_id: str,
    task_key: str,
    agent_roles: list[str],
    router_session_key: str,
    max_duration_s: int = PIPELINE_TIMEOUT_S,
) -> None:
    """
    Persistent coordinator loop for one pipeline.
    Spawns agents, polls every POLL_INTERVAL_S, checks liveness every LIVENESS_INTERVAL_S.
    Sends Telegram summary on done/failed/partial.
    """
    start_time = time.time()
    last_liveness_check = 0.0
    pipeline_done = False

    _log_info(f"Starting pipeline loop for {pipeline_run_id}")

    # Spawn all agents
    agents = poll_agent_executions(pipeline_run_id)
    start_pipeline(pipeline_run_id, agents)

    while True:
        elapsed = time.time() - start_time

        # Hard timeout
        if elapsed >= max_duration_s:
            _log_info(f"Pipeline {pipeline_run_id} hit hard timeout ({max_duration_s}s)")
            _mark_pipeline_timed_out(pipeline_run_id, agents)
            break

        # Check for done/failed/cancelled
        agents = poll_agent_executions(pipeline_run_id)
        _advance_pipeline_stage_if_needed(pipeline_run_id, agents)

        done_count = sum(1 for a in agents if a["status"] == "done")
        failed_count = sum(1 for a in agents if a["status"] in ("failed", "timed_out", "cancelled"))
        running_count = sum(1 for a in agents if a["status"] in ("running", "spawning", "queued"))

        if done_count + failed_count == len(agents) and len(agents) > 0:
            # All agents have reached a terminal state
            pipeline_done = True
        elif failed_count > 0 and running_count == 0:
            # All remaining are failed/timed_out/cancelled — pipeline failed
            pipeline_done = True

        if pipeline_done:
            break

        # Liveness check every LIVENESS_INTERVAL_S
        if time.time() - last_liveness_check >= LIVENESS_INTERVAL_S:
            agents = check_liveness(agents)
            last_liveness_check = time.time()

        time.sleep(POLL_INTERVAL_S)

    # Build and send summary
    agents = poll_agent_executions(pipeline_run_id)
    elapsed_s = time.time() - start_time
    summary = _build_summary(pipeline_run_id, agents, elapsed_s)

    # Determine final pipeline status
    if all(a["status"] == "done" for a in agents):
        final_status = "done"
    elif any(a["status"] == "cancelled" for a in agents):
        final_status = "cancelled"
    elif any(a["status"] == "failed" for a in agents) or any(a["status"] == "timed_out" for a in agents):
        final_status = "partial"
    else:
        final_status = "active"

    # Close pipeline in DB
    if _sb:
        try:
            _sb.close_pipeline(pipeline_run_id, final_status)
        except Exception as e:
            _log_err(f"close_pipeline failed: {e}")

    # Remove from active pipelines
    with _state_lock:
        _active_pipelines.pop(pipeline_run_id, None)

    # Send Telegram
    _send_telegram(summary)
    _log_info(f"Pipeline {pipeline_run_id} complete: {final_status}")


def _mark_pipeline_timed_out(pipeline_run_id: str, agents: list[dict[str, Any]]) -> None:
    """Mark all running agents as timed_out and close pipeline."""
    if _sb is None:
        return

    for agent in agents:
        if agent["status"] in ("running", "spawning", "queued"):
            try:
                _sb.update_agent_status(agent["execution_id"], "timed_out")
            except Exception:
                pass

    try:
        _sb.close_pipeline(pipeline_run_id, "failed")
    except Exception:
        pass


def stop_pipeline(pipeline_run_id: str) -> bool:
    """
    Stop a running pipeline: kill all agent sessions, update DB status.
    Returns True if stopped, False if pipeline not found.
    """
    if not _OPENCLAW_AVAILABLE or _sb is None:
        _log_err("stop_pipeline: OpenClaw or shared_bus not available")
        return False

    agents = _sb.get_agent_executions(pipeline_run_id)
    if not agents:
        _log_err(f"stop_pipeline: pipeline {pipeline_run_id} not found")
        return False

    killed = []
    for agent in agents:
        sk = agent.get("session_key")
        if sk:
            try:
                subagents(action="kill", target=sk)
                killed.append(sk)
            except Exception as e:
                _log_err(f"kill {sk} failed: {e}")

        try:
            _sb.update_agent_status(agent["execution_id"], "cancelled")
        except Exception:
            pass

    try:
        _sb.close_pipeline(pipeline_run_id, "cancelled")
    except Exception:
        pass

    # Remove from active
    with _state_lock:
        _active_pipelines.pop(pipeline_run_id, None)

    task_key = "unknown"
    with _state_lock:
        for pid, pdata in _active_pipelines.items():
            if pid == pipeline_run_id:
                task_key = pdata.get("task_key", "unknown")
                break

    _send_telegram(f"🐝 Swarm cancelled: {task_key}")
    _log_info(f"Pipeline {pipeline_run_id} stopped — killed {len(killed)} sessions")
    return True


# ── Orphaned Pipeline Recovery ─────────────────────────────────────────────────

def recover_orphaned_pipelines() -> None:
    """
    Run on module import: find active pipelines whose router session is gone,
    kill orphaned agent sessions, mark as failed.
    """
    if not _OPENCLAW_AVAILABLE or _sb is None:
        return

    _log_info("Running orphaned pipeline recovery...")

    try:
        _sb.add_swarm_tables()
    except Exception as e:
        _log_err(f"add_swarm_tables during recovery: {e}")

    active_pipelines = _sb.get_active_pipelines()
    recovered = 0

    try:
        live_sessions = sessions_list() or []
        live_router_keys = {s.get("sessionKey") for s in live_sessions}
    except Exception:
        live_router_keys = set()

    for pipeline in active_pipelines:
        router_sk = pipeline.get("router_session_key", "")
        pid = pipeline.get("uuid") or pipeline.get("id", "")

        if not router_sk:
            # No router session key — likely pre-swarm pipeline, skip
            continue

        if router_sk not in live_router_keys:
            # Stale coordinator — clean up
            _log_info(f"Recovering orphaned pipeline: {pid}")
            try:
                agents = _sb.get_agent_executions(str(pid))
            except Exception as e:
                _log_err(f"get_agent_executions for {pid}: {e}")
                agents = []

            for agent in agents:
                sk = agent.get("session_key")
                if sk:
                    try:
                        subagents(action="kill", target=sk)
                    except Exception:
                        pass  # already dead

                try:
                    _sb.update_agent_status(agent["execution_id"], "failed", "coordinator_crash")
                except Exception:
                    pass

            try:
                _sb.close_pipeline(str(pid), "failed")
            except Exception:
                pass

            recovered += 1

    if recovered:
        _log_info(f"Recovered {recovered} orphaned pipelines")
    else:
        _log_info("No orphaned pipelines found")


# ── Incoming message handler ───────────────────────────────────────────────────

def on_telegram_message(text: str, router_session_key: str = "agent:main:telegram:direct:115436097") -> None:
    """
    Main entry point: call this from the Telegram message handler.
    Parses /swarm commands, starts or stops pipelines.
    """
    if not _OPENCLAW_AVAILABLE:
        _send_telegram("⚠️ Swarm unavailable: OpenClaw tools not found")
        return

    task_key, agent_roles, stop_id = _parse_swarm_command(text)

    if stop_id:
        _send_telegram(f"🛑 Stopping pipeline {stop_id}...")
        success = stop_pipeline(stop_id)
        if not success:
            _send_telegram(f"❌ Pipeline {stop_id} not found or already stopped")
        return

    if task_key is None:
        return  # Not a /swarm command

    # Check active pipeline limit
    with _state_lock:
        active_count = sum(
            1 for p in _active_pipelines.values()
            if p.get("status") == "active"
        )

    if active_count >= MAX_ACTIVE_PIPELINES:
        _send_telegram(f"⏳ Swarm busy — {MAX_ACTIVE_PIPELINES} pipelines active. Try again shortly.")
        return

    # Create pipeline
    try:
        pipeline_run_id = init_pipeline(task_key, agent_roles, router_session_key)
    except Exception as e:
        _log_err(f"init_pipeline failed: {e}")
        _send_telegram(f"❌ Pipeline init failed: {e}")
        return

    # Register as active
    with _state_lock:
        _active_pipelines[pipeline_run_id] = {
            "task_key": task_key,
            "agent_roles": agent_roles,
            "status": "active",
            "started_at": time.time(),
            "router_session_key": router_session_key,
        }

    _send_telegram(f"🐝 Swarm started: {task_key} — {len(agent_roles)} agents")

    # Run pipeline loop in background thread
    t = threading.Thread(
        target=run_pipeline_loop,
        args=(pipeline_run_id, task_key, agent_roles, router_session_key),
        daemon=True,
    )
    t.start()


# ── Swarm status for Control UI ────────────────────────────────────────────────

def get_swarm_status() -> list[dict[str, Any]]:
    """
    Return all active + recent pipelines with agent statuses.
    Used by GET /api/swarm-status in viewer_server.py.
    """
    if _sb is None:
        return []

    try:
        _sb.add_swarm_tables()
    except Exception:
        pass

    pipelines = _sb.get_pipeline_runs(limit=20)
    result = []

    for pipeline in pipelines:
        pid = str(pipeline.get("uuid") or pipeline.get("id", ""))
        try:
            agents = _sb.get_agent_executions(pid)
        except Exception:
            agents = []

        stage = "?"
        if agents and _sb:
            stage = _sb.derive_pipeline_stage(agents)

        # Elapsed time
        started_at = pipeline.get("started_at", "") or pipeline.get("updated_at", "")
        elapsed_s = 0
        if started_at:
            try:
                if "T" in str(started_at):
                    from datetime import datetime
                    dt = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
                    elapsed_s = int((datetime.now() - dt.replace(tzinfo=None)).total_seconds())
                else:
                    elapsed_s = int(time.time() - time.time())  # fallback
            except Exception:
                elapsed_s = 0

        result.append({
            "pipeline_run_id": pid,
            "task_key": pipeline.get("task_key", "?"),
            "status": pipeline.get("status", "?"),
            "stage": stage,
            "router_session_key": pipeline.get("router_session_key", ""),
            "agent_roles": [a["agent_role"] for a in agents],
            "agents": [
                {
                    "execution_id": a["execution_id"],
                    "agent_role": a["agent_role"],
                    "status": a["status"],
                    "session_key": a.get("session_key", ""),
                    "result_ref": a.get("result_ref"),
                    "heartbeat_at": a.get("heartbeat_at"),
                }
                for a in agents
            ],
            "elapsed_s": elapsed_s,
            "started_at": started_at,
            "updated_at": pipeline.get("updated_at", ""),
        })

    return result


# ── Module init: migrate schema + recover orphaned ────────────────────────────

if _sb is not None:
    try:
        _sb.add_swarm_tables()
        _log_info("Swarm tables initialised")
    except Exception as e:
        _log_err(f"add_swarm_tables on import failed: {e}")

    try:
        recover_orphaned_pipelines()
    except Exception as e:
        _log_err(f"recover_orphaned_pipelines on import failed: {e}")

_log_info("swarm_router loaded")