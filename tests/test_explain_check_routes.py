"""HTTP integration for server-held advisory explanation checks; no sockets."""
import io
import json
import threading
from email.message import Message
from types import SimpleNamespace

import pytest

from src import job_hunt_explain_check as checker
from src import job_hunt_llm as llm
from src import ui_handlers
from src.ui_routes import _build_handler
from src.ui_state import UIServerConfig


@pytest.fixture
def route_env(tmp_path, monkeypatch):
    config = UIServerConfig(profile_path=tmp_path / "profile.json",
                           state_root=tmp_path / "state", report_dir=tmp_path / "reports",
                           host="127.0.0.1", port=0)
    profile, job, analysis = object(), object(), object()
    monkeypatch.setattr(ui_handlers, "load_candidate_profile", lambda _: profile)
    monkeypatch.setattr(ui_handlers, "load_reviewed_job", lambda *_: job)
    monkeypatch.setattr(ui_handlers, "load_job_analysis", lambda *_: analysis)
    monkeypatch.setattr(llm, "explain_job_match_with_llm", lambda *_: (
        {"fit": "Python matches. SQL matches.", "risk": "Missing COBOL.", "action": "Ask the recruiter.", "model_used": "fake"}, None))
    store = checker.TokenStore()
    service = checker.ExplainCheckService(store, transport=lambda *_args, **_kw: {
        "answers": {"supported": {"type": "noul", "noul": .75}}})
    monkeypatch.setattr(checker, "TOKEN_STORE", store)
    monkeypatch.setattr(checker, "CHECK_SERVICE", service)
    handler_type = _build_handler(config)

    def request(path="/job/synthetic/explain-check", body=None, method="POST", headers=None):
        handler = handler_type.__new__(handler_type)
        handler.command, handler.path = method, path
        raw = json.dumps(body).encode() if body is not None else b""
        handler.headers = Message()
        values = {"Host": "127.0.0.1:9000", "Origin": "http://127.0.0.1:9000",
                  "Content-Type": "application/json", "Content-Length": str(len(raw))}
        values.update(headers or {})
        for name, value in values.items():
            if value is not None:
                handler.headers[name] = value
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.request_version = "HTTP/1.1"
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.server = SimpleNamespace(server_address=("127.0.0.1", 9000))
        getattr(handler, "do_" + method)()
        response = handler.wfile.getvalue()
        status = int(response.split(b" ", 2)[1])
        payload = response.split(b"\r\n\r\n", 1)[1]
        return status, json.loads(payload) if payload.startswith(b"{") else payload, handler

    return SimpleNamespace(request=request, store=store, service=service, config=config,
                           profile=profile, job=job, analysis=analysis)


@pytest.mark.parametrize("headers", [
    {"Host": "evil.example:9000"}, {"Origin": "http://evil.example:9000"},
    {"Origin": None}, {"Referer": "http://evil.example:9000"},
])
def test_check_origin_host_protection_before_read(route_env, monkeypatch, headers):
    monkeypatch.setattr(checker, "run_check", lambda *_: pytest.fail("check dispatched"))
    status, _, handler = route_env.request(body={"check_token": "unused"}, headers=headers)
    assert status == 403
    assert handler.rfile.tell() == 0


def test_check_get_is_405(route_env):
    status, _, handler = route_env.request(method="GET")
    assert status == 405
    assert b"Allow: POST" in handler.wfile.getvalue()


def test_check_unknown_job_404(route_env, monkeypatch):
    def missing(*_):
        raise FileNotFoundError
    monkeypatch.setattr(ui_handlers, "load_reviewed_job", missing)
    status, body, _ = route_env.request(body={"check_token": "unused"})
    assert status == 404 and body["ok"] is False


def test_explain_binds_same_objects_and_keeps_source_server_side(route_env, monkeypatch):
    seen = []
    original = llm.build_explain_fields
    def fields(*args):
        seen.append(args)
        return original(*args)
    def explain(*args):
        seen.append(args)
        return {"fit": "Python matches.", "risk": "Missing COBOL.", "action": "Ask."}, None
    monkeypatch.setattr(llm, "build_explain_fields", fields)
    monkeypatch.setattr(llm, "explain_job_match_with_llm", explain)
    status, body, _ = route_env.request("/job/synthetic/explain")
    assert status == 200 and seen == [(route_env.profile, route_env.job, route_env.analysis)] * 2
    assert "source" not in body
    assert set(body["statements"][0]) == {"id", "section", "text"}
    assert body["statements"][-1]["reason"] == "advice"
    entry = route_env.store.get(body["check_token"], "synthetic")
    assert entry["source"] == llm.explain_source_text(original(*seen[0]))


@pytest.mark.parametrize("kind", ["unknown", "wrong_job", "expired", "superseded", "invalid", "extra", "missing"])
def test_stale_without_work(route_env, monkeypatch, kind):
    token = route_env.store.create("other" if kind == "wrong_job" else "synthetic", "source", {"fit": "Match."})
    if kind == "unknown":
        token = "unknown"
    elif kind == "expired":
        route_env.store.entries[token]["created"] -= 601
    elif kind == "superseded":
        route_env.store.create("synthetic", "new source", {"fit": "New."})
    body = {"check_token": [] if kind == "invalid" else token}
    if kind == "extra":
        body["source"] = "browser source"
    elif kind == "missing":
        body = {}
    monkeypatch.setattr(checker, "run_check", lambda *_: pytest.fail("stale dispatched"))
    status, result, _ = route_env.request(body=body)
    assert status == 200 and result == {"ok": True, "state": "stale"}


def test_results_and_log_use_configured_state_root(route_env):
    _, explanation, _ = route_env.request("/job/synthetic/explain")
    status, body, _ = route_env.request(body={"check_token": explanation["check_token"]})
    assert status == 200 and body["state"] == "done"
    assert body["results"]["fit-0"] == {"verdict": "ok"}
    assert body["results"]["action-0"] == {"verdict": "not_checked", "reason": "advice"}
    with route_env.service.condition:
        assert route_env.service.condition.wait_for(lambda: route_env.service.active is None, timeout=2)
    log = route_env.config.state_root / "logs" / "explain-check.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert records[0]["job_id"] == "synthetic" and records[0]["source"]
    assert log.stat().st_mode & 0o777 == 0o600
    assert "source" not in body


def test_limits_and_source_too_large(route_env, monkeypatch):
    monkeypatch.setattr(llm, "explain_job_match_with_llm", lambda *_: (
        {"fit": "Match. " * 11 + "x" * 601, "risk": "Risk.", "action": "Ask."}, None))
    _, explanation, _ = route_env.request("/job/synthetic/explain")
    assert explanation["statements"][10]["reason"] == "limit"
    _, body, _ = route_env.request(body={"check_token": explanation["check_token"]})
    assert body["results"]["fit-10"]["reason"] == "limit"
    assert body["results"]["fit-11"]["reason"] == "limit"
    with route_env.service.condition:
        assert route_env.service.condition.wait_for(lambda: route_env.service.active is None, timeout=2)
    monkeypatch.setattr(llm, "explain_source_text", lambda _: "漢" * 3000)
    route_env.service.transport = lambda *_args, **_kw: pytest.fail("oversized source dispatched")
    _, explanation, _ = route_env.request("/job/synthetic/explain")
    assert all(row["reason"] == "source_too_large" for row in explanation["statements"] if row["section"] != "action")
    _, body, _ = route_env.request(body={"check_token": explanation["check_token"]})
    assert body["results"]["fit-0"]["reason"] == "source_too_large"


def test_unavailable_model_marks_remaining(route_env):
    def unavailable(*_args, **_kw):
        raise checker.ModelUnavailable("fake unavailable")
    route_env.service.transport = unavailable
    token = route_env.store.create("synthetic", "source", {"fit": "First. Second.", "action": "Ask."})
    _, body, _ = route_env.request(body={"check_token": token})
    assert body["state"] == "partial"
    assert body["results"]["fit-0"]["reason"] == body["results"]["fit-1"]["reason"] == "model_unavailable"


def test_deadline_partial_holds_busy_until_transport_returns_then_retry(route_env, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def transport(*_args, **_kw):
        calls.append(1)
        if len(calls) == 2:
            entered.set()
            assert release.wait(2)
        return {"answers": {"supported": {"type": "noul", "noul": .2}}}
    route_env.service.transport = transport
    token = route_env.store.create("synthetic", "source", {"fit": "First. Second."})
    original = checker.run_check
    monkeypatch.setattr(checker, "run_check", lambda entry: original(entry, deadline_seconds=.03))
    try:
        _, partial, _ = route_env.request(body={"check_token": token})
        assert entered.is_set() and partial["state"] == "partial"
        assert partial["results"]["fit-0"]["verdict"] == "could_not_confirm"
        assert partial["results"]["fit-1"]["reason"] == "time"
        _, busy, _ = route_env.request(body={"check_token": token})
        assert busy == {"ok": True, "state": "busy"}
    finally:
        release.set()
    with route_env.service.condition:
        assert route_env.service.condition.wait_for(lambda: route_env.service.active is None, timeout=2)
    _, retry, _ = route_env.request(body={"check_token": token})
    assert retry["state"] == "done"
    log = route_env.config.state_root / "logs" / "explain-check.jsonl"
    first = json.loads(log.read_text().splitlines()[0])
    assert first["discarded_late_results"][0]["id"] == "fit-1"
