"""Feature A (2026-09-22): bulk paste of job URLs / JD texts on the Add & Evaluate tab."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src import ui_render

NODE = shutil.which("node")


def _add_tab_html() -> str:
    return ui_render.render_home_page(
        profile_name="P", profile_target_roles=["BA"], history=[], values={}, error=None, tab="add_job",
    )


def _scripts(html: str) -> list[str]:
    return re.findall(r"<script>(.*?)</script>", html, re.S)


def test_rendered_tab_has_bulk_controls():
    html = _add_tab_html()
    for needle in ('id="bulk-input"', 'id="bulk-run-btn"', ">Add all<", 'id="bulk-results"',
                   'id="bulk-results-body"', 'id="bulk-stop-btn"', 'data-add-job-tab="bulk"',
                   'data-add-job-panel="bulk"', 'id="bulk-review-link"'):
        assert needle in html, needle
    assert any(s.startswith("/* bulk-paste */") for s in _scripts(html))


def test_every_inline_script_passes_node_check(tmp_path):
    if not NODE:
        pytest.skip("node not available")
    for i, js in enumerate(_scripts(_add_tab_html())):
        f = tmp_path / f"s{i}.js"
        f.write_text(js)
        r = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, (i, r.stderr)


def _run_node(tmp_path: Path, body: str):
    if not NODE:
        pytest.skip("node not available")
    js = next(s for s in _scripts(_add_tab_html()) if s.startswith("/* bulk-paste */"))
    (tmp_path / "bulk.js").write_text(js)
    harness = "const B=require('./bulk.js');\n" + body
    (tmp_path / "h.js").write_text(harness)
    r = subprocess.run([NODE, str(tmp_path / "h.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())


def test_classify_blank_duplicate_text_invalid_and_cap(tmp_path):
    out = _run_node(tmp_path, r"""
const a=B.classify("\n  https://a.example/1  \n\nhttps://a.example/1\nnot a url\nhttps://b.example/2\n");
const b=B.classify("Job title: BA\nCompany: X\n---\nhttps://c.example/3\nhttps://d.example/4\n---\n\n---\nSecond text");
const many=Array.from({length:20},(_, i)=>"https://x.example/"+i).join("\n");
const c=B.classify(many);
console.log(JSON.stringify({a:a,b:b,c:{n:c.items.length,truncated:c.truncated,total:c.total}}));
""")
    a = out["a"]
    assert [(i["kind"], i["value"]) for i in a["items"]] == [
        ("url", "https://a.example/1"), ("invalid", "not a url"), ("url", "https://b.example/2")]
    assert a["duplicates"] == 1 and a["items"][1]["error"] == "not a URL"
    b = out["b"]
    assert [i["kind"] for i in b["items"]] == ["text", "url", "url", "text"]
    assert b["items"][0]["value"] == "Job title: BA\nCompany: X"
    assert out["c"] == {"n": 15, "truncated": True, "total": 20}


def test_run_all_failure_never_stops_others_and_escapes_nothing_into_html(tmp_path):
    out = _run_node(tmp_path, r"""
const hdr=(t)=>({get:()=>t});
const seen=new Set(); const submitted=[];
function fetchStub(url,opts){
  if(opts.method==='GET') return Promise.resolve({ok:seen.has(url),status:seen.has(url)?200:404});
  const body=new URLSearchParams(opts.body);
  if(url==='/prefill'){
    if(body.get('job_url')==='https://bad.example/x')
      return Promise.resolve({ok:false,status:400,json:()=>Promise.resolve({ok:false,error:'<script>alert(1)</script> boom'})});
    return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({ok:true,values:{job_title:'T',job_id:'t-co'}})});
  }
  submitted.push(body.get('job_id')); seen.add('/job/'+body.get('job_id'));
  return Promise.resolve({ok:true,status:200,url:'http://h/job/j-1',headers:hdr('text/html'),
    text:()=>Promise.resolve('<button class="jst-override-btn" data-job-id="j-1" data-decision="apply" data-current="review">x</button><div style="a">72</div><div style="b">FIT SCORE</div>')});
}
const rows={};
(async()=>{
  const items=B.classify("https://bad.example/x\nhttps://ok.example/1\nnope").items;
  const s=await B.runAll(items,fetchStub,{onRow:(i,st)=>{rows[i]=st;},shouldStop:()=>false});
  console.log(JSON.stringify({s:s,rows:rows,txt:B.summaryText(s,''),submitted:submitted}));
})();
""")
    assert out["s"] == {"saved": 1, "refreshed": 0, "failed": 2, "stopped": 0, "reviewIds": ["j-1"]}
    assert re.fullmatch(r"t-co-[0-9a-f]{6}", out["submitted"][0])
    assert out["rows"]["0"] == {"status": "failed", "error": "<script>alert(1)</script> boom"}
    assert out["rows"]["1"] == {"status": "saved", "jobId": "j-1", "decision": "review", "score": "72", "unread": False}
    assert out["rows"]["2"] == {"status": "failed", "error": "not a URL"}
    assert out["txt"] == "1 new, 0 refreshed, 2 failed"


def test_make_job_id_deterministic_charset_and_length(tmp_path):
    out = _run_node(tmp_path, r"""
(async()=>{
  const u1={kind:'url',value:'https://a.example/1'}, u2={kind:'url',value:'https://a.example/2'};
  const t1={kind:'text',value:'Some  JD\n text'}, t2={kind:'text',value:' some  jd text '};
  const r={
    a:await B.makeJobId('ba-acme',u1), a2:await B.makeJobId('ba-acme',u1), b:await B.makeJobId('ba-acme',u2),
    t1:await B.makeJobId('x',t1), t2:await B.makeJobId('x',t2),
    long:await B.makeJobId('x'.repeat(300),u1), odd:await B.makeJobId('../a b/é',u1), empty:await B.makeJobId('',u1)};
  console.log(JSON.stringify(r));
})();
""")
    assert out["a"] == out["a2"] and out["a"] != out["b"]
    assert out["t1"] != out["t2"]  # whitespace-normalised but case-sensitive
    for v in out.values():
        assert re.fullmatch(r"[A-Za-z0-9._-]{8,128}", v) and v not in (".", "..")
    assert len(out["long"]) == 128 and out["a"].startswith("ba-acme-")
    assert not out["odd"].startswith((".", "/"))


def test_unreadable_job_page_shows_decision_not_read(tmp_path):
    out = _run_node(tmp_path, r"""
(async()=>{
  const f=(url,o)=>{
    if(url==='/prefill') return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({ok:true,values:{job_id:'a'}})});
    if(o.method==='GET') return Promise.resolve({ok:false,status:404});
    return Promise.resolve({ok:true,status:200,url:'http://h/job/a-1',headers:{get:()=>'text/html'},text:()=>Promise.resolve('<html>changed markup</html>')});
  };
  const rows={};
  const s=await B.runAll(B.classify('https://a.example/1').items,f,{onRow:(i,st)=>{rows[i]=st;},shouldStop:()=>false});
  console.log(JSON.stringify({s:s,rows:rows}));
})();
""")
    assert out["s"]["saved"] == 1 and out["s"]["failed"] == 0 and out["s"]["reviewIds"] == []
    assert out["rows"]["0"]["status"] == "saved" and out["rows"]["0"]["unread"] is True
    assert "saved (decision not read)" in ui_render._BULK_PASTE_JS


def test_dom_wiring_never_uses_innerhtml():
    js = ui_render._BULK_PASTE_JS
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "outerHTML" not in js


def _playwright():
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Playwright is not installed")
    return sync_playwright, PlaywrightError


class _StubApp:
    """Tiny same-origin server: the real rendered Add tab plus stub /prefill, /job-submit (303) and /job/<id>.

    /job/<id> is 404 until that id has been submitted (stateful), like the real app. Both
    "alpha" URLs prefill the SAME slug (same title+company), as the real /prefill does.
    """

    def __init__(self, delay_s: float = 0.0):
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import parse_qs

        decisions = {"alpha": ("review", 61), "gamma": ("apply", 80)}
        page_html = _add_tab_html().encode()
        self.submitted: list[str] = []
        submitted = self.submitted

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def _send(self, status, ctype, body, headers=None):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.startswith("/job/"):
                    jid = self.path.rsplit("/", 1)[-1]
                    if jid not in submitted:
                        self._send(404, "text/html", b"not found")
                        return
                    dec, score = decisions[jid.split("-")[0]]
                    self._send(200, "text/html", (
                        f'<html><button class="jst-override-btn" data-job-id="{jid}" data-decision="skip" '
                        f'data-current="{dec}">s</button><div>{score}</div><div>FIT SCORE</div></html>').encode())
                else:
                    self._send(200, "text/html", page_html)

            def do_POST(self):
                time.sleep(delay_s)
                form = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()).items()}
                if self.path == "/prefill":
                    if "bad-item" in form.get("job_url", ""):
                        self._send(400, "application/json", json.dumps(
                            {"ok": False, "error": "Blocked <script>window.__xss=1</script>"}).encode())
                    else:
                        title = "alpha" if "alpha" in form["job_url"] else "gamma"
                        self._send(200, "application/json", json.dumps(
                            {"ok": True, "values": {"job_title": title, "job_id": f"{title}-co"}}).encode())
                elif self.path == "/job-submit":
                    submitted.append(form["job_id"])
                    self._send(303, "text/plain", b"", {"Location": f"/job/{form['job_id']}"})
                else:
                    self._send(404, "text/plain", b"")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _launch(pw, PlaywrightError):
    try:
        return pw.chromium.launch(headless=True)
    except PlaywrightError as exc:
        pytest.skip(f"Chromium unavailable: {exc}")


def test_bulk_browser_three_items_one_failing_and_stop():
    sync_playwright, PlaywrightError = _playwright()
    app = _StubApp()
    app2 = _StubApp(delay_s=0.4)
    try:
        with sync_playwright() as pw:
            browser = _launch(pw, PlaywrightError)
            try:
                errors: list[str] = []
                page = browser.new_page()
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"{app.base}/")
                page.click('[data-add-job-tab="bulk"]')
                page.fill("#bulk-input", "https://x.example/alpha\nhttps://x.example/bad-item\nhttps://x.example/gamma")
                page.click("#bulk-run-btn")
                page.wait_for_function("document.getElementById('bulk-summary').textContent.includes('new')")
                rows = page.locator("#bulk-results-body tr")
                assert rows.count() == 3
                assert page.locator('#bulk-results-body tr[data-status="saved"]').count() == 2
                assert page.locator('#bulk-results-body tr[data-status="failed"]').count() == 1
                assert page.inner_text("#bulk-summary").startswith("2 new, 0 refreshed, 1 failed")
                # failure text is shown literally, never executed
                assert "<script>window.__xss=1</script>" in rows.nth(1).inner_text()
                assert page.evaluate("window.__xss") is None
                assert page.locator("#bulk-results-body script").count() == 0
                assert re.fullmatch(r"/job/alpha-co-[0-9a-f]{6}", rows.nth(0).locator("a").get_attribute("href"))
                assert re.fullmatch(r"/job/gamma-co-[0-9a-f]{6}", rows.nth(2).locator("a").get_attribute("href"))
                assert "Review 61" in rows.nth(0).inner_text() and "Apply 80" in rows.nth(2).inner_text()
                # Review queue link: only the review-decision job
                link = page.locator("#bulk-review-link")
                assert link.is_visible() and link.get_attribute("href") == "/review-queue?ids=" + app.submitted[0]
                assert errors == []

                # Stop halts the loop: the in-flight item finishes, the rest are not run.
                page2 = browser.new_page()
                page2.goto(f"{app2.base}/")
                page2.click('[data-add-job-tab="bulk"]')
                page2.fill("#bulk-input", "https://x.example/alpha\nhttps://x.example/gamma\nhttps://x.example/alpha2")
                page2.click("#bulk-run-btn")
                page2.wait_for_selector('#bulk-results-body tr[data-status="fetching"]')
                page2.click("#bulk-stop-btn")
                page2.wait_for_function("document.getElementById('bulk-summary').textContent.includes('stopped')")
                assert page2.locator('#bulk-results-body tr[data-status="stopped"]').count() == 2
                assert page2.locator('#bulk-results-body tr[data-status="saved"]').count() == 1
                assert page2.inner_text("#bulk-summary").startswith("1 new, 0 refreshed, 0 failed, 2 not run (stopped)")
            finally:
                browser.close()
    finally:
        app.close()
        app2.close()


def test_bulk_browser_same_title_different_postings_and_readd():
    sync_playwright, PlaywrightError = _playwright()
    app = _StubApp()
    try:
        with sync_playwright() as pw:
            browser = _launch(pw, PlaywrightError)
            try:
                page = browser.new_page()
                page.goto(f"{app.base}/")
                page.click('[data-add-job-tab="bulk"]')
                # two DIFFERENT postings, same title+company slug
                page.fill("#bulk-input", "https://x.example/alpha-1\nhttps://x.example/alpha-2")
                page.click("#bulk-run-btn")
                page.wait_for_function("document.getElementById('bulk-summary').textContent.includes('new')")
                assert page.inner_text("#bulk-summary").startswith("2 new, 0 refreshed, 0 failed")
                assert len(app.submitted) == 2 and app.submitted[0] != app.submitted[1]
                hrefs = [page.locator("#bulk-results-body a").nth(i).get_attribute("href") for i in range(2)]
                assert hrefs[0] != hrefs[1]
                # the SAME posting again: same id, labelled refreshed, counted separately
                page.fill("#bulk-input", "https://x.example/alpha-1")
                page.click("#bulk-run-btn")
                page.wait_for_function("document.getElementById('bulk-summary').textContent.includes('refreshed')"
                                       " && !document.getElementById('bulk-run-btn').disabled")
                assert app.submitted[2] == app.submitted[0]
                assert page.inner_text("#bulk-summary").startswith("0 new, 1 refreshed, 0 failed")
                row = page.locator("#bulk-results-body tr").nth(0)
                assert row.get_attribute("data-status") == "refreshed"
                assert "already saved \u2014 refreshed" in row.inner_text()
            finally:
                browser.close()
    finally:
        app.close()


def test_bulk_browser_real_endpoints_text_blocks_and_not_a_url(tmp_path):
    """No stubs: two pasted JD texts go through the real /prefill + /job-submit."""
    sync_playwright, PlaywrightError = _playwright()
    from tests.test_ui import _running_ui_server

    with _running_ui_server(tmp_path) as (base_url, config):
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(headless=True)
            except PlaywrightError as exc:
                pytest.skip(f"Chromium unavailable: {exc}")
            try:
                page = browser.new_page()
                page.goto(f"{base_url}/?tab=add_job")
                page.click('[data-add-job-tab="bulk"]')
                page.fill("#bulk-input", "Job title: Business Analyst\nCompany: Example Ltd\nLocation: Chester\n"
                          "Skills: stakeholder management, SQL\n---\nJob title: Data Analyst\nCompany: Other Ltd\n"
                          "Location: Leeds\nSkills: SQL, Python")
                page.click("#bulk-run-btn")
                page.wait_for_function("document.getElementById('bulk-summary').textContent.includes('new')",
                                       timeout=60000)
                assert page.locator('#bulk-results-body tr[data-status="saved"]').count() == 2
                hrefs = [page.locator("#bulk-results-body a").nth(i).get_attribute("href") for i in range(2)]
                assert all(h.startswith("/job/") for h in hrefs) and hrefs[0] != hrefs[1]
                # decision + score were scraped from the real /job/<id> page
                cells = [page.locator("#bulk-results-body tr").nth(i).locator("td").nth(2).inner_text() for i in range(2)]
                assert all(re.fullmatch(r"(Apply|Review|Skip) \d{1,3}", c) for c in cells), cells
                assert (config.state_root).exists()
            finally:
                browser.close()
