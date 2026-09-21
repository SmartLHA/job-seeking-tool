"""D (2026-09-20): small UI issues from ui-functions-audit-2026-09-19 section 6.3."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src import ui_render

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "src" / "ui_render.py").read_text()


def _scripts(html: str) -> list[str]:
    return re.findall(r"<script>(.*?)</script>", html, re.S)


def _node_check(js: str, tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    f = tmp_path / "s.js"
    f.write_text(js)
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_qualitative_form_uses_fetch_with_loading_and_error(tmp_path):
    js = ui_render._QUAL_ASSESS_JS
    assert 'form[data-qual-assess]' in js and "fetch(form.action" in js
    assert "Running assessment" in js and "Assessment failed" in js
    assert 'data-qual-assess="1"' in SRC and 'class="qual-assess-status"' in SRC
    assert 'action="/job/{escape(vm.job_id)}/qualitative-assess"' in SRC   # route unchanged
    _node_check(re.search(r"<script>(.*)</script>", js, re.S).group(1), tmp_path)


def test_copy_failure_is_inline_not_alert():
    assert 'alert("Copy failed' not in SRC
    assert 'ai-cv-copy-msg' in SRC and "Copy failed — please select the text manually." in SRC


def _home() -> str:
    return ui_render.render_home_page(
        profile_name="P", profile_target_roles=["BA"], history=[], values={}, error=None, tab="history",
    )


def test_home_nav_marks_current_item_and_keeps_link_role():
    """D3: ARIA tab roles on the home nav were tried and reverted: role=tab replaces the
    link role that test_shared_shell_has_no_mobile_document_overflow (get_by_role
    "link") depends on, and the items are real page navigations. The active item now
    carries aria-current="page" instead."""
    html = _home()
    assert re.search(r'<a href="/\?tab=history" class="nav-item  nav-active" aria-current="page">', html)
    assert re.search(r'<a href="/\?tab=search" class="nav-item">', html)
    assert 'role="tab"' not in html.split('aria-label="Job input method"')[0]
    assert html.count('aria-current="page"') == 1
    assert 'id="tab-history" class="tab-content"' in html


def test_review_queue_stacks_on_mobile_and_has_back_link(tmp_path):
    vm = ui_render.ReviewQueueViewModel(
        jobs=[{"job_id": "j1", "title": "BA", "company": "Acme", "score": 70, "decision": "review", "source": "reed"}],
        active_id="j1", ids_csv="j1",
    )
    html = ui_render.render_review_queue_page(vm)
    assert "@media (max-width:640px)" in html
    assert ".rq-panels{flex-direction:column" in html
    # single link to search (the existing "New search"); no redundant second one
    assert html.count('href="/?tab=search"') == 1 and "New search" in html
    assert "Back to search results" not in html
    assert 'class="rq-frame"' in html and 'class="rq-list"' in html
    for js in _scripts(html):
        _node_check(js, tmp_path)


def test_job_page_qualitative_form_present():
    from tests.test_cover_letter_form import _vm

    html = ui_render.render_job_page(_vm())
    assert 'data-qual-assess="1"' in html and 'class="qual-assess-status"' in html
    assert "fetch(form.action" in html
    assert 'alert("Copy failed' not in html


def test_every_inline_script_on_job_page_passes_node_check(tmp_path):
    """No exclusions: every inline <script> in the rendered job page must parse."""
    from tests.test_cover_letter_form import _vm

    scripts = _scripts(ui_render.render_job_page(_vm()))
    assert len(scripts) >= 7
    for i, js in enumerate(scripts):
        d = tmp_path / str(i)
        d.mkdir()
        _node_check(js, d)


def test_override_handler_behaviour(tmp_path):
    """Run the real override script under node with a stub DOM: clicking a different
    decision POSTs it; clicking the current one POSTs null; both hit /job/<id>/decision."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    from tests.test_cover_letter_form import _vm

    html = ui_render.render_job_page(_vm())
    js = next(s for s in _scripts(html) if s.startswith("/* override */"))
    harness = """
const calls=[];let handlers=[];
function mk(dec,cur){return {dataset:{jobId:"job-001",decision:dec,current:cur},
  addEventListener(ev,fn){handlers.push(fn);}};}
const btns=[mk("skip","apply"),mk("apply","apply")];
global.document={querySelectorAll(sel){ if(sel!==".jst-override-btn") throw new Error(sel);
  return {forEach(cb){btns.forEach(cb);}};}};
global.window={location:{reload(){}}};
global.setTimeout=function(){};
global.fetch=function(url,opts){calls.push([url,JSON.parse(opts.body),opts.method]);
  return Promise.resolve({json(){return Promise.resolve({});}});};
""" + js + """
handlers[0](); handlers[1]();
console.log(JSON.stringify(calls));
"""
    f = tmp_path / "h.js"
    f.write_text(harness)
    r = subprocess.run([node, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    import json
    calls = json.loads(r.stdout.strip())
    assert calls == [
        ["/job/job-001/decision", {"user_decision": "skip"}, "POST"],
        ["/job/job-001/decision", {"user_decision": None}, "POST"],
    ]
