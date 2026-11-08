"""Viewer intent boundary with synthetic sockets, endpoints and home only."""
import importlib
import json
from pathlib import Path
import sys
import types

import pytest


class RequestSocket:
    """A second recv is observable even when the dispatcher catches errors."""
    def __init__(self, request, *, remaining=b"", port=18765):
        self.request, self.remaining, self.port = request, remaining, port
        self.response = b""
        self.reads = 0
        self.closed = self.shutdown_called = False

    def recv(self, size):
        self.reads += 1
        if self.reads == 1:
            return self.request
        if self.remaining:
            result, self.remaining = self.remaining[:size], self.remaining[size:]
            return result
        raise AssertionError("Unexpected deferred body/private read")

    def getsockname(self):
        return "127.0.0.1", self.port

    def sendall(self, data):
        self.response += data

    def shutdown(self, how):
        self.shutdown_called = True

    def close(self):
        self.closed = True

    def setblocking(self, blocking):
        pass


def request_bytes(method="GET", path="/api/health", headers=None, body=b""):
    if headers is None:
        headers = [("Host", "127.0.0.1:18765")]
    lines = [f"{method} {path} HTTP/1.1"] + [f"{k}: {v}" for k, v in headers]
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


@pytest.fixture
def viewer_api(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "viewer"))
    module = importlib.import_module("viewer_server")
    return module


def arm_private_traps(module, monkeypatch):
    calls = {"endpoint": 0, "store": 0, "home": 0, "static": 0}

    def trap(name):
        def reached(*args, **kwargs):
            calls[name] += 1
            raise AssertionError("Private " + name + " reached")
        return reached

    for name in vars(module):
        if name.startswith(("handle_api_", "_handle_api_")):
            monkeypatch.setattr(module, name, trap("endpoint"))
    monkeypatch.setattr(module.kanban_store, "get_board", trap("store"))
    monkeypatch.setattr(module.data_outcomes, "load_jobs", trap("store"))
    monkeypatch.setattr(module, "serve_file", trap("static"))
    monkeypatch.setattr(Path, "home", classmethod(trap("home")))
    # /usage also must not resolve its private file before refusal.
    class PrivateDirectory:
        def __truediv__(self, name):
            return trap("store")()
    monkeypatch.setattr(module, "VIEWER_DIR", PrivateDirectory())
    return calls


BAD_HEADERS = [
    [], [("Host", "evil.invalid:18765")], [("Host", "127.0.0.1:18766")],
    [("Host", "127.0.0.1")], [("Host", "user@127.0.0.1:18765")],
    [("Host", "127.0.0.1:18765/path")], [("Host", "127.0.0.1:18765,localhost:18765")],
    [("Host", "127.0.0.1:18765"), ("hOsT", "127.0.0.1:18765")],
] + [[("Host", "127.0.0.1:18765"), (name, value)] for name, value in [
    ("Origin", "http://foreign.invalid:18765"), ("Origin", "null"), ("Origin", ""),
    ("Origin", "http://localhost:18765"), ("Origin", "http://127.0.0.1:18766"),
    ("Origin", "https://127.0.0.1:18765"), ("Origin", "http://user@127.0.0.1:18765"),
    ("Origin", "http://127.0.0.1:18765/"), ("Origin", "http://127.0.0.1:18765?x"),
    ("Origin", "http://127.0.0.1:18765?"), ("Origin", "http://127.0.0.1:18765#"),
    ("Origin", "http://127.0.0.1:18765 http://foreign.invalid"),
    ("Origin", "http://127.0.0.1:18765\\@foreign.invalid"),
    ("Referer", "http://foreign.invalid/private"), ("Referer", "null"),
    ("Referer", "http://user@127.0.0.1:18765/page"),
    ("Referer", "http://localhost:18765/page"), ("Referer", "http://[::1"),
    ("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Site", "same-site"),
    ("Sec-Fetch-Site", "unknown"),
]] + [[("Host", "127.0.0.1:18765"), (name, value), (name.lower(), value)]
      for name, value in [("Origin", "http://127.0.0.1:18765"),
                          ("Referer", "http://127.0.0.1:18765/page"),
                          ("Sec-Fetch-Site", "same-origin")]]


@pytest.mark.parametrize("headers", BAD_HEADERS)
@pytest.mark.parametrize("path", ["/api/health", "/api/viewer-events", "/usage", "/api/unknown"])
def test_untrusted_get_rejected_before_private_reads(viewer_api, monkeypatch, headers, path):
    calls = arm_private_traps(viewer_api, monkeypatch)
    sock = RequestSocket(request_bytes(path=path, headers=headers))
    viewer_api.handle_request(sock)
    assert sock.response.startswith(b"HTTP/1.1 403 ")
    assert b"Connection: close" in sock.response and b"Access-Control" not in sock.response
    assert sock.closed and sock.shutdown_called and sock.reads == 1
    assert calls == dict.fromkeys(calls, 0)


@pytest.mark.parametrize("headers", [
    [("Host", "127.0.0.1:18765")],
    [("Host", "127.0.0.1:18765"), ("Origin", "http://foreign.invalid")],
    [("Host", "127.0.0.1:18765"), ("Origin", "http://127.0.0.1:18765"),
     ("Referer", "http://foreign.invalid/page")],
    [("Host", "127.0.0.1:18765"), ("Forwarded", "host=127.0.0.1:18765"),
     ("X-Forwarded-Host", "127.0.0.1:18765"), ("X-Forwarded-Proto", "http")],
])
@pytest.mark.parametrize("path", ["/api/kanban", "/api/safe-content-analysis", "/api/health", "/viewer/index.html"])
def test_untrusted_post_closes_before_deferred_body(viewer_api, monkeypatch, headers, path):
    calls = arm_private_traps(viewer_api, monkeypatch)
    headers = headers + [("Content-Length", "8192"), ("Content-Type", "application/json")]
    sock = RequestSocket(request_bytes("POST", path, headers))
    viewer_api.handle_request(sock)
    assert sock.response.startswith(b"HTTP/1.1 403 ") and sock.reads == 1 and sock.closed
    assert calls == dict.fromkeys(calls, 0)


@pytest.mark.parametrize("path", sorted([
    "/api/kanban", "/api/system-kanban", "/api/jobs", "/api/url-parse",
    "/api/text-parse", "/api/job-submit", "/api/safe-content-analysis",
]))
@pytest.mark.parametrize("media", [None, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"])
def test_json_routes_reject_media_before_body_or_mutation(viewer_api, monkeypatch, path, media):
    calls = arm_private_traps(viewer_api, monkeypatch)
    headers = [("Host", "127.0.0.1:18765"), ("Origin", "http://127.0.0.1:18765"),
               ("Content-Length", "12345")]
    if media is not None:
        headers.append(("Content-Type", media))
    sock = RequestSocket(request_bytes("POST", path, headers))
    viewer_api.handle_request(sock)
    assert sock.response.startswith(b"HTTP/1.1 415 ") and sock.reads == 1 and sock.closed
    assert calls == dict.fromkeys(calls, 0)


@pytest.mark.parametrize("alias", ["127.0.0.1", "localhost"])
@pytest.mark.parametrize("source", [None, "Origin", "Referer"])
def test_local_get_and_json_post_retain_endpoint_contract(viewer_api, monkeypatch, alias, source):
    calls = []
    monkeypatch.setattr(viewer_api, "handle_api_kanban", lambda body: (calls.append(body), b'{"ok":true}')[1])
    headers = [("Host", alias + ":18765"), ("X-Forwarded-Host", "foreign.invalid")]
    if source:
        headers += [(source, "http://" + alias + ":18765" + ("/viewer/" if source == "Referer" else ""))]
    sock = RequestSocket(request_bytes(headers=headers, path="/api/kanban"))
    viewer_api.handle_request(sock)
    assert sock.response.startswith(b"HTTP/1.1 200 ") and calls == [b""]
    if source:
        headers += [("Content-Type", "Application/JSON; charset=utf-8"), ("Content-Length", "2")]
        sock = RequestSocket(request_bytes("POST", "/api/kanban", headers), remaining=b"{}")
        viewer_api.handle_request(sock)
        assert sock.response.startswith(b"HTTP/1.1 200 ") and calls == [b"", b"{}"]
        assert sock.reads == 2 and sock.closed
    assert b"Access-Control" not in sock.response


@pytest.mark.parametrize("media", [None, "text/plain", "application/x-www-form-urlencoded"])
def test_post_read_alias_keeps_media_compatibility(viewer_api, monkeypatch, media):
    calls = []
    monkeypatch.setattr(viewer_api, "handle_api_health", lambda: (calls.append(1), b"{}")[1])
    headers = [("Host", "127.0.0.1:18765"), ("Origin", "http://127.0.0.1:18765")]
    if media:
        headers += [("Content-Type", media)]
    sock = RequestSocket(request_bytes("POST", "/api/health", headers))
    viewer_api.handle_request(sock)
    assert sock.response.startswith(b"HTTP/1.1 200 ") and calls == [1]


@pytest.mark.parametrize("method", ["OPTIONS", "PATCH", "DELETE", "PUT", "HEAD"])
def test_unsupported_methods_still_405_after_host_validation(viewer_api, monkeypatch, method):
    calls = arm_private_traps(viewer_api, monkeypatch)
    sock = RequestSocket(request_bytes(method, "/api/jobs", [("Host", "127.0.0.1:18765"),
        ("Origin", "http://foreign.invalid"), ("Content-Length", "100")]))
    viewer_api.handle_request(sock)
    assert sock.response.startswith(b"HTTP/1.1 405 ") and sock.reads == 1 and sock.closed
    assert calls == dict.fromkeys(calls, 0) and b"Access-Control" not in sock.response
    sock = RequestSocket(request_bytes(method, headers=[("Host", "foreign.invalid:18765")]))
    viewer_api.handle_request(sock)
    assert sock.response.startswith(b"HTTP/1.1 403 ")


def test_split_headers_then_refusal_never_assembles_body(viewer_api, monkeypatch):
    calls = arm_private_traps(viewer_api, monkeypatch)
    first = b"POST /api/kanban HTTP/1.1\r\nHost: 127.0.0.1:18765\r\nOri"
    rest = b"gin: null\r\nContent-Length: 10000\r\n\r\n"
    sock = RequestSocket(first, remaining=rest)
    viewer_api.handle_request(sock)
    assert sock.response.startswith(b"HTTP/1.1 403 ") and sock.reads == 2
    assert calls == dict.fromkeys(calls, 0)


def test_safe_content_retains_two_mib_cap_without_body_read(viewer_api):
    sock = RequestSocket(request_bytes("POST", "/api/safe-content-analysis", [
        ("Host", "127.0.0.1:18765"), ("Origin", "http://127.0.0.1:18765"),
        ("Content-Type", "application/json"), ("Content-Length", str(2 * 1024 * 1024 + 1))]))
    viewer_api.handle_request(sock)
    assert sock.response.startswith(b"HTTP/1.1 413 ") and sock.reads == 1 and sock.closed


def test_safe_content_allowed_json_uses_fake_analysis(viewer_api, monkeypatch):
    calls = []
    fake = types.ModuleType("safe_content_api")
    fake.run_pasted_analysis = lambda **kw: (calls.append(kw), {"ok": True})[1]
    monkeypatch.setitem(sys.modules, "safe_content_api", fake)
    body = json.dumps({"content": "Synthetic 香港"}).encode()
    sock = RequestSocket(request_bytes("POST", "/api/safe-content-analysis", [
        ("Host", "127.0.0.1:18765"), ("Origin", "http://127.0.0.1:18765"),
        ("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))], body))
    viewer_api.handle_request(sock)
    assert sock.response.startswith(b"HTTP/1.1 200 ") and len(calls) == 1
    assert calls[0]["content"] == "Synthetic 香港" and b"Access-Control" not in sock.response


def test_public_static_navigation_uses_host_only(viewer_api, monkeypatch, tmp_path):
    public = tmp_path / "public"
    (public / "viewer").mkdir(parents=True)
    (public / "viewer/index.html").write_text("Synthetic public page")
    monkeypatch.setattr(viewer_api, "PROJECT_ROOT", public)
    sock = RequestSocket(request_bytes(path="/viewer/index.html", headers=[
        ("Host", "127.0.0.1:18765"), ("Referer", "http://foreign.invalid/page"),
        ("Sec-Fetch-Site", "cross-site")]))
    viewer_api.handle_request(sock)
    assert sock.response.startswith(b"HTTP/1.1 200 ") and sock.response.endswith(b"Synthetic public page")
    sock = RequestSocket(request_bytes(path="/viewer/index.html", headers=[("Host", "foreign.invalid:18765")]))
    viewer_api.handle_request(sock)
    assert sock.response.startswith(b"HTTP/1.1 403 ")
