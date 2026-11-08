"""Actual Chromium requests against owned Viewer sockets and synthetic stores."""
import importlib
import json
from pathlib import Path
import socketserver
import threading
import time
import types
from urllib.parse import urlsplit

import pytest
from browser_support import playwright_sync


@pytest.fixture
def viewer_browser_server(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "viewer"))
    module = importlib.import_module("viewer_server")
    public = tmp_path / "public"
    (public / "viewer").mkdir(parents=True)
    (public / "viewer/index.html").write_text('<!doctype html><meta charset="utf-8"><title>Synthetic Viewer</title>')
    monkeypatch.setattr(module, "PROJECT_ROOT", public)
    monkeypatch.setattr(module.kanban_store, "DATA_FILE", tmp_path / "kanban.json")
    calls = {"health": 0, "kanban": 0, "topic": 0}
    records = []
    original_kanban = module.handle_api_kanban

    def kanban(body):
        calls["kanban"] += 1
        return original_kanban(body)

    def health():
        calls["health"] += 1
        return b'{"synthetic":"private"}'

    def topic(name):
        calls["topic"] += 1
        return 1.0

    monkeypatch.setattr(module, "handle_api_kanban", kanban)
    monkeypatch.setattr(module, "handle_api_health", health)
    monkeypatch.setattr(module, "_get_topic_version", topic)
    # No real /dev/fd observation is needed for this synthetic SSE fixture.
    real_listdir = module.os.listdir
    monkeypatch.setattr(module.os, "listdir", lambda path: [] if path == "/dev/fd" else real_listdir(path))
    stopping = threading.Event()
    monkeypatch.setattr(module, "time", types.SimpleNamespace(
        time=lambda: time.time() + (301 if stopping.is_set() else 0),
        sleep=lambda duration: stopping.wait(0.01)))

    class RecordedSocket:
        def __init__(self, sock):
            self.sock, self.headers, self.logged = sock, b"", False

        def recv(self, size):
            result = self.sock.recv(size)
            if b"\r\n\r\n" not in self.headers:
                self.headers += result
            return result

        def sendall(self, data):
            if not self.logged and data.startswith(b"HTTP/1.1 "):
                line = self.headers.split(b"\r\n", 1)[0].decode()
                records.append({"request": line, "status": int(data.split(b" ")[1]),
                                "cors": b"Access-Control" in data.split(b"\r\n\r\n")[0]})
                self.logged = True
            return self.sock.sendall(data)

        def __getattr__(self, name):
            return getattr(self.sock, name)

    class ViewerHandler(socketserver.BaseRequestHandler):
        def handle(self):
            module.handle_request(RecordedSocket(self.request))

    class ForeignHandler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.recv(8192)
            body = b'<!doctype html><meta charset="utf-8"><title>Synthetic foreign page</title>'
            self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: ' +
                                 str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body)

    class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True

    servers = [Server(("127.0.0.1", 0), handler) for handler in (ViewerHandler, ForeignHandler)]
    threads = [threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.01}) for s in servers]
    for thread in threads:
        thread.start()
    port, foreign_port = [s.server_address[1] for s in servers]
    try:
        yield {"origin": f"http://127.0.0.1:{port}", "alias": f"http://localhost:{port}",
               "foreign": f"http://127.0.0.1:{foreign_port}", "calls": calls, "records": records,
               "store": tmp_path / "kanban.json"}
    finally:
        stopping.set()
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
        deadline = time.monotonic() + 2
        while module._SSE_CONNECTIONS and time.monotonic() < deadline:
            stopping.wait(0.01)
        assert module._SSE_CONNECTIONS == 0


@pytest.fixture
def boundary_browser():
    sync_playwright, _ = playwright_sync()
    import os
    with sync_playwright() as pw:
        # Dedicated alias allowance: existing global browser fences are unchanged.
        browser = pw.chromium.launch(headless=True,
            executable_path=os.environ.get("JOB_TOOL_TEST_CHROMIUM_EXECUTABLE"),
            args=["--disable-background-networking",
                  "--host-resolver-rules=MAP localhost 127.0.0.1, MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"])
        try:
            yield browser
        finally:
            browser.close()


def exact_owned_page(browser, fixture):
    allowed = {tuple((p.scheme, p.hostname, p.port))
               for p in map(urlsplit, [fixture["origin"], fixture["alias"], fixture["foreign"]])}
    assert all(scheme == "http" and host in {"127.0.0.1", "localhost"} and port
               for scheme, host, port in allowed)
    blocked = []
    context = browser.new_context(service_workers="block")
    page = context.new_page()
    session = context.new_cdp_session(page)

    def restrict(event):
        p = urlsplit(event["request"]["url"])
        if (p.scheme, p.hostname, p.port) in allowed:
            session.send("Fetch.continueRequest", {"requestId": event["requestId"]})
        else:
            blocked.append(event["request"]["url"])
            session.send("Fetch.failRequest", {"requestId": event["requestId"], "errorReason": "BlockedByClient"})

    # Playwright context.route auto-fulfills CORS preflights. A page-local CDP
    # fence keeps exact origins while letting the real server answer OPTIONS.
    session.on("Fetch.requestPaused", restrict)
    session.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
    return context, page, blocked


@pytest.mark.required_browser
@pytest.mark.parametrize("alias", ["origin", "alias"])
def test_actual_browser_same_origin_json_get_and_sse(boundary_browser, viewer_browser_server, alias, tmp_path):
    fixture = viewer_browser_server
    context, page, blocked = exact_owned_page(boundary_browser, fixture)
    try:
        page.goto(fixture[alias] + "/viewer/index.html")
        get = page.evaluate("async () => {const r=await fetch('/api/health');return [r.status,await r.json()]}")
        assert get == [200, {"synthetic": "private"}]
        post = page.evaluate('''async () => {const r=await fetch('/api/kanban',{
            method:'POST', headers:{'Content-Type':'application/json; charset=utf-8'},
            body:JSON.stringify({action:'upsert',column_id:'backlog',card:{title:'Synthetic 香港'}})});
            return [r.status,await r.json()]}''')
        assert post[0] == 200
        assert post[1]["columns"][0]["cards"][0]["title"] == "Synthetic 香港"
        event = page.evaluate('''() => new Promise((resolve,reject)=>{
            const e=new EventSource('/api/viewer-events?topics=cache-stats');
            const timer=setTimeout(()=>{e.close();reject(new Error('missing SSE'))},5000);
            e.onmessage=m=>{clearTimeout(timer);e.close();resolve(JSON.parse(m.data))};
            e.onerror=()=>{clearTimeout(timer);e.close();reject(new Error('SSE error'))};})''')
        assert event == {"topic": "cache-stats", "version": 1, "reason": "update"}
        assert fixture["calls"]["health"] == 1 and fixture["calls"]["kanban"] == 1
        assert fixture["calls"]["topic"] >= 1 and fixture["store"].exists()
        assert not any(r["cors"] for r in fixture["records"]) and blocked == []
        evidence = {"browser": boundary_browser.version, "origin": fixture[alias],
                    "calls": fixture["calls"], "responses": fixture["records"], "sse": event}
        (tmp_path / "browser-evidence.json").write_text(json.dumps(evidence, indent=2))
        print("BROWSER CHECK:", json.dumps(evidence))
    finally:
        context.close()


@pytest.mark.required_browser
@pytest.mark.parametrize("source", ["foreign", "alias"])
def test_actual_browser_foreign_requests_cannot_read_mutate_or_stream(boundary_browser, viewer_browser_server, source, tmp_path):
    fixture = viewer_browser_server
    context, page, blocked = exact_owned_page(boundary_browser, fixture)
    try:
        page.goto(fixture[source] + "/viewer/index.html")
        target = fixture["origin"]
        # Simple requests reach the boundary; failures must also be visible server-side.
        attempts = page.evaluate('''async target => {
            const attempt=async (path, options) => {try {const r=await fetch(target+path,options);
                return {readable:true,status:r.status,body:await r.text()}}
                catch(e){return {readable:false,name:e.name}}};
            return [await attempt('/api/health'),
                await attempt('/api/kanban',{method:'POST',headers:{'Content-Type':'text/plain'},body:'{}'}),
                await attempt('/api/kanban',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})];
        }''', target)
        assert attempts == [{"readable": False, "name": "TypeError"}] * 3
        sse = page.evaluate('''target => new Promise(resolve=>{
            const e=new EventSource(target+'/api/viewer-events?topics=cache-stats');
            const timer=setTimeout(()=>{e.close();resolve('timeout')},5000);
            e.onmessage=()=>{clearTimeout(timer);e.close();resolve('message')};
            e.onerror=()=>{clearTimeout(timer);e.close();resolve('error')};})''', target)
        assert sse == "error"
        # Browser form navigation is not stopped by CORS. Assert the server refusal.
        _, BrowserError = playwright_sync()
        try:
            with page.expect_navigation() as navigation:
                page.evaluate('''target=>{const f=document.createElement('form');f.method='POST';
                    f.action=target+'/api/kanban';f.enctype='application/x-www-form-urlencoded';
                    const i=document.createElement('input');i.name='action';i.value='delete';
                    f.append(i);document.body.append(f);f.submit()}''', target)
        except BrowserError as exc:
            # Chromium rejects a navigation with an empty 403 response body.
            assert "net::ERR_HTTP_RESPONSE_CODE_FAILURE" in str(exc)
        else:
            assert navigation.value.status == 403
        assert fixture["calls"] == {"health": 0, "kanban": 0, "topic": 0}
        assert not fixture["store"].exists() and blocked == []
        records = fixture["records"]
        assert any(r["request"].startswith("OPTIONS /api/kanban ") and r["status"] == 405 for r in records)
        for prefix in ["GET /api/health ", "GET /api/viewer-events?", "POST /api/kanban "]:
            matching = [r for r in records if r["request"].startswith(prefix)]
            assert matching and all(r["status"] == 403 and not r["cors"] for r in matching)
        assert len([r for r in records if r["request"].startswith("POST /api/kanban ")]) == 2
        evidence = {"browser": boundary_browser.version, "source": fixture[source], "target": target,
                    "attempts": attempts, "sse": sse, "calls": fixture["calls"], "responses": records}
        (tmp_path / "browser-evidence.json").write_text(json.dumps(evidence, indent=2))
        print("BROWSER CHECK:", json.dumps(evidence))
    finally:
        context.close()
