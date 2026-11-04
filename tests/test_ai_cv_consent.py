"""C0: the "AI Review CV" button sends nothing to Gemini without per-click consent.

Synthetic CV text only. Every test mocks the writer (``ai_rewrite_cv``) and
the Gemini transport, so no test can reach the network.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import job_hunt_cv_review, job_hunt_llm, ui_handlers, ui_render
from src.job_hunt_config import TailoringPolicy
from src.ui_routes import _parse_request

JOB_ID = "job-1"
SYNTHETIC_CV = "Synthetic Analyst\nSQL reporting and stakeholder management at Example Corp."
LABEL = "Send my CV to Google Gemini for this rewrite and its check"


@pytest.fixture(autouse=True)
def no_gemini_transport(monkeypatch):
    """Belt and braces: even an unmocked writer cannot reach the network."""
    def blocked(*args, **kwargs):
        raise AssertionError("Gemini transport must not be reached from these tests")

    monkeypatch.setattr(job_hunt_cv_review, "REVIEWER_MODEL", "gemini-3.5-flash")
    monkeypatch.setattr(job_hunt_cv_review, "REVIEWER_MODELS", ("gemini-3.5-flash",))
    monkeypatch.setattr(job_hunt_llm, "_call_gemini_reasoning", blocked)
    monkeypatch.setattr(job_hunt_llm, "_call_gemini_model", blocked)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Handler environment: synthetic job/profile, writer mocked, output dir inside tmp_path."""
    output = tmp_path / "tailored"
    output.mkdir()
    monkeypatch.setattr(ui_handlers, "DEFAULT_TAILORING_POLICY", TailoringPolicy(output_dir=output))
    monkeypatch.setattr(ui_handlers, "load_job_analysis", lambda *a: SimpleNamespace(decision="apply", user_decision=None))
    monkeypatch.setattr(ui_handlers, "load_reviewed_job", lambda *a: SimpleNamespace(job_id=JOB_ID))
    state = {"cv": SYNTHETIC_CV}
    monkeypatch.setattr(ui_handlers, "load_candidate_profile", lambda *a: SimpleNamespace(
        candidate_id="synthetic", master_cv_text=state["cv"],
    ))
    writer = Mock(return_value=({"reviewed_cv": "Reviewed synthetic CV", "changes": ["Synthetic change"]}, None, "synthetic-model"))
    monkeypatch.setattr(job_hunt_llm, "ai_rewrite_cv", writer)
    config = SimpleNamespace(profile_path=tmp_path / "profile.json", state_root=tmp_path)
    return SimpleNamespace(output=output, writer=writer, config=config, state=state)


def _call(env, req):
    responder = SimpleNamespace(send_json=Mock())
    ui_handlers.handle_ai_review_cv(req, env.config, responder, JOB_ID)
    (payload,), kwargs = responder.send_json.call_args
    return payload, kwargs.get("status", HTTPStatus.OK)


def _assert_refused(env, payload, status, error):
    assert payload == {"ok": False, "error": error}
    assert status == (HTTPStatus.FORBIDDEN if error == "consent_required" else HTTPStatus.UNPROCESSABLE_ENTITY)
    env.writer.assert_not_called()
    assert list(env.output.iterdir()) == []


# ---- handler: consent gate -------------------------------------------------

NO_CONSENT_REQUESTS = {
    "missing_field": SimpleNamespace(json_body={}),
    "false": SimpleNamespace(json_body={"use_cloud": False}),
    "string_true": SimpleNamespace(json_body={"use_cloud": "true"}),
    "null": SimpleNamespace(json_body={"use_cloud": None}),
    "int_one": SimpleNamespace(json_body={"use_cloud": 1}),
    "malformed_body": SimpleNamespace(json_body=None),
    "non_dict_body": SimpleNamespace(json_body=[True]),
    "bare_true_body": SimpleNamespace(json_body=True),
    "req_none": None,
}


@pytest.mark.parametrize("name", sorted(NO_CONSENT_REQUESTS))
def test_no_exact_true_consent_is_refused_with_no_call_and_no_write(env, name):
    payload, status = _call(env, NO_CONSENT_REQUESTS[name])
    _assert_refused(env, payload, status, "consent_required")


def test_consent_true_calls_the_writer_and_saves(env):
    payload, status = _call(env, SimpleNamespace(json_body={"use_cloud": True}))
    assert status == HTTPStatus.OK
    assert payload["ok"] is True and payload["reviewed_cv"] == "Reviewed synthetic CV"
    env.writer.assert_called_once()
    assert env.writer.call_args.args[0] == SYNTHETIC_CV
    assert (env.output / f"{JOB_ID}_ai_reviewed.md").exists()


def _http_request(raw: bytes, content_type: str = "application/json"):
    """Run the real request parser, so a malformed body is exercised end to end."""
    handler = SimpleNamespace(
        path=f"/job/{JOB_ID}/ai-review-cv", command="POST",
        headers={"Content-Type": content_type, "Content-Length": str(len(raw))},
        rfile=io.BytesIO(raw),
    )
    return _parse_request(handler)


@pytest.mark.parametrize("raw, content_type", [
    (b"{not json", "application/json"),
    (b"", "application/json"),
    (b"{}", "application/json"),
    (b'{"use_cloud": false}', "application/json"),
    (b'{"use_cloud": "true"}', "application/json"),
    (b'{"use_cloud": true}', "text/plain"),
    (b"use_cloud=true", "application/x-www-form-urlencoded"),
])
def test_real_parsed_request_without_exact_true_json_is_refused(env, raw, content_type):
    payload, status = _call(env, _http_request(raw, content_type))
    _assert_refused(env, payload, status, "consent_required")


def test_real_parsed_request_with_true_is_accepted(env):
    payload, status = _call(env, _http_request(b'{"use_cloud": true}'))
    assert status == HTTPStatus.OK and payload["ok"] is True
    env.writer.assert_called_once()


# ---- handler: length limit -------------------------------------------------

@pytest.mark.parametrize("req", [
    SimpleNamespace(json_body={"use_cloud": True}),
    SimpleNamespace(json_body={}),
    None,
], ids=["with_consent", "without_consent", "req_none"])
def test_cv_over_15000_chars_is_refused_before_consent_and_any_call(env, req):
    env.state["cv"] = "x" * 15_001
    payload, status = _call(env, req)
    _assert_refused(env, payload, status, "cv_too_long_for_ai_review")


def test_cv_of_exactly_15000_chars_is_still_allowed(env):
    env.state["cv"] = "x" * 15_000
    payload, status = _call(env, SimpleNamespace(json_body={"use_cloud": True}))
    assert status == HTTPStatus.OK and payload["ok"] is True
    env.writer.assert_called_once()


# ---- page: checkbox, request body, reset, error messages ---------------------

def _job_html(**vm_overrides) -> str:
    from tests.test_cover_letter_form import _vm
    return ui_render.render_job_page(_vm(**vm_overrides))


def test_page_has_unchecked_consent_checkbox_with_exact_label_next_to_button():
    class Inputs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.consent = None
            self.label_text = None
            self._in_label = False
            self._buf = []
            self.order = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "button" and attrs.get("id") == "ai-cv-btn":
                self.order.append("button")
            if tag == "input" and attrs.get("id") == "ai-cv-consent":
                self.consent = attrs
                self.order.append("checkbox")
                self._in_label = True
                self._buf = []

        def handle_data(self, data):
            if self._in_label:
                self._buf.append(data)

        def handle_endtag(self, tag):
            if tag == "label" and self._in_label:
                self.label_text = "".join(self._buf).strip()
                self._in_label = False

    parser = Inputs()
    parser.feed(_job_html())
    assert parser.consent is not None
    assert parser.consent["type"] == "checkbox" and "checked" not in parser.consent
    assert parser.label_text == LABEL
    assert parser.order == ["button", "checkbox"]


def test_sidebar_discloses_per_click_consent_and_keeps_existing_line():
    html = _job_html()
    assert "CV skill suggestions use Gemini only with your consent." in html
    assert "AI CV review sends the CV to Gemini only after the per-click consent." in html


_JS_PREFIX = r"""
const assert = require('assert');
let click = null;
const calls = [];
const consent = {checked: false};
const innerHtmlWrites = [];
// Fake DOM node. textContent is the node's own text (setting it drops the children, as
// in a browser); domText() joins the text of a whole subtree. Every innerHTML write on
// any node is recorded, so a test can prove the AI review flow never writes one.
function element(tag) {
  return {tag, children: [], style: {}, className: '', id: '', attrs: {}, _text: '', listeners: {},
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); this.children = []; },
    set innerHTML(v) { innerHtmlWrites.push(v); },
    get innerHTML() { return innerHtmlWrites[innerHtmlWrites.length - 1] || ''; },
    appendChild(c) { c.parentNode = this; this.children.push(c); return c; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    addEventListener(t, fn) { this.listeners[t] = fn; }
  };
}
const resultDiv = element('div');
const domText = n => n._text + n.children.map(domText).join('');
const btn = {dataset: {jobId: 'job-1'}, disabled: false, textContent: 'AI Review CV',
  addEventListener: (t, fn) => { if (t === 'click') click = fn; }};
const ids = {'ai-cv-btn': btn, 'ai-cv-consent': consent, 'tailor-result': resultDiv};
let nextResponse = null;
global.document = {getElementById: id => ids[id] || null,
  createElement: element};
global.window = {confirm: () => true};
global.fetch = (url, opts) => {
  calls.push({url, method: opts.method, body: JSON.parse(opts.body), checkedWhenSent: consent.checked});
  return Promise.resolve(nextResponse);
};
const respond = (ok, data) => ({ok, json: async () => data});
const flush = () => new Promise(r => setImmediate(r));
"""

_JS_SUFFIX = r"""
(async () => {
  assert(click, 'AI Review CV click handler was not registered');

  // 1. box not ticked: use_cloud false, box stays unchecked, refusal shown as text.
  nextResponse = respond(false, {ok: false, error: 'consent_required'});
  click();
  assert.strictEqual(consent.checked, false);
  await flush();
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].url, '/job/job-1/ai-review-cv');
  assert.strictEqual(calls[0].method, 'POST');
  assert.deepStrictEqual(calls[0].body, {use_cloud: false, consent_scope: 'gemini'});
  assert.strictEqual(btn.disabled, false);
  assert.strictEqual(resultDiv.children.length, 1);
  assert(resultDiv.children[0].textContent.includes('Tick the box'));
  assert.strictEqual(resultDiv.textContent, '');

  // 2. box ticked: use_cloud true is sent, and the box is unchecked as soon as the
  //    request has been sent (before the response arrives).
  consent.checked = true;
  nextResponse = respond(true, {ok: true, reviewed_cv: 'Synthetic rewrite', changes: [], model_used: 'm', saved_path: 'a.md'});
  click();
  assert.strictEqual(calls.length, 2);
  assert.deepStrictEqual(calls[1].body, {use_cloud: true, consent_scope: 'gemini'});
  assert.strictEqual(calls[1].checkedWhenSent, true);
  assert.strictEqual(consent.checked, false, 'checkbox must be unchecked right after the request is sent');
  await flush();
  assert.strictEqual(consent.checked, false);
  assert(domText(resultDiv).includes('Synthetic rewrite'));

  // 3. the box does not stay ticked after a failed request either.
  consent.checked = true;
  global.fetch = (url, opts) => { calls.push({body: JSON.parse(opts.body)}); return Promise.reject(new Error('offline')); };
  click();
  assert.strictEqual(consent.checked, false);
  await flush();
  assert.deepStrictEqual(calls[2].body, {use_cloud: true, consent_scope: 'gemini'});
  assert.strictEqual(consent.checked, false);

  // 4. too-long CV: readable message, set with textContent on a created element.
  global.fetch = (url, opts) => { calls.push({body: JSON.parse(opts.body)}); return Promise.resolve(nextResponse); };
  nextResponse = respond(false, {ok: false, error: 'cv_too_long_for_ai_review'});
  const writesBefore = innerHtmlWrites.length;
  resultDiv.children = [];
  click();
  await flush();
  assert.strictEqual(resultDiv.children.length, 1);
  assert(resultDiv.children[0].textContent.includes('15,000'));
  assert.strictEqual(resultDiv.children[0].tag, 'p');
  // Loading and error messages both use textContent; neither writes innerHTML.
  assert.strictEqual(innerHtmlWrites.length, writesBefore);
  assert(!innerHtmlWrites.slice(writesBefore).some(w => w.includes('15,000')));

  console.log('AI review consent runtime assertions passed');
})().catch(e => { console.error(e); process.exitCode = 1; });
"""


def test_executed_page_script_sends_use_cloud_from_checkbox_and_resets_it(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    scripts = re.findall(r"<script>(.*?)</script>", _job_html(), re.S)
    script = next(s for s in scripts if s.startswith("/* tailor + cover */"))
    path = tmp_path / "ai-cv-consent.js"
    path.write_text(_JS_PREFIX + script + _JS_SUFFIX)
    result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "AI review consent runtime assertions passed"


# ---- C3c: verdict panel, approve and revise, rendered with textContent only -------

_JS_HELPERS = r"""
const RECORDING_FETCH = global.fetch;
const all = n => [n, ...n.children.flatMap(all)];
const findButton = label => all(resultDiv).find(n => n.tag === 'button' && n.textContent === label);
const pageText = () => domText(resultDiv);
const BAD = '<img src=x onerror=alert(1)>';
const ITEM = {id: 's-0', block_key: 'Experience', text: 'Ran the weekly planning meeting',
  verdict: 'UNSUPPORTED', evidence_quote: '', reason: 'No such meeting in the CV.', severity: 'BLOCKER',
  removed: ['Led the weekly planning meeting']};
const SUPPORTED_ITEM = {id: 's-1', block_key: 'Experience', text: 'Only listed as supported',
  verdict: 'SUPPORTED', evidence_quote: 'q', reason: 'fine', severity: 'MINOR', removed: []};
const L0_OPEN = {layer: 0, rule: 'L0-1', text: 'Prepared reports', severity: 'MAJOR',
  detail: 'A number is new.', item_id: null, cleared_by: null};
const L0_CLEARED = {layer: 0, rule: 'L0-4', text: 'Cleared finding text', severity: 'MAJOR',
  detail: 'skill', item_id: 's-1', cleared_by: 's-1'};
function result(verdict, extra) {
  return Object.assign({ok: true, reviewed_cv: 'Summary\nRan the weekly planning meeting\nPrepared reports',
    changes: ['Reworded the summary'], model_used: 'writer-model', saved_path: 'job-1_ai_reviewed.md',
    generation_id: 'gen-1', rewrite_sha256: 'hash-1', revise_round: 0, approval: null,
    review: {verdict, reviewer_model: 'checker-model', items: [], l0_findings: []}}, extra || {});
}
const withFindings = (verdict, extra) => result(verdict, Object.assign({review: {verdict,
  reviewer_model: 'checker-model', items: [ITEM, SUPPORTED_ITEM], l0_findings: [L0_OPEN, L0_CLEARED]}}, extra || {}));
async function load(data) { nextResponse = respond(true, data); click(); await flush(); }
const APPROVAL = {approved_at: 't', generation_id: 'gen-1', rewrite_sha256: 'hash-1'};
const STALE = 'This review is out of date. Run AI Review CV again.';
const BUSY = 'Another AI review is running. Try again in a moment.';
"""


def _run_page_js(tmp_path, body, html=None):
    """Run the real page script in node against the fake DOM, then ``body`` (async).

    ``html`` is the rendered page to take the script from (default: a plain job page). When
    it embeds a saved review (``#ai-cv-saved``), the JSON text is placed on a fake element.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = _job_html() if html is None else html
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    saved = re.search(r'<script type="application/json" id="ai-cv-saved">(.*?)</script>', html, re.S)
    inject = ""
    if saved:
        inject = "ids['ai-cv-saved'] = {textContent: " + json.dumps(saved.group(1)) + "};\n"
    script = next(s for s in scripts if s.startswith("/* tailor + cover */"))
    checks = ("(async () => {\n" + body + "\nconsole.log('ok');\n})()"
              ".catch(e => { console.error(e); process.exitCode = 1; });\n")
    path = tmp_path / "ai-cv-panel.js"
    path.write_text(_JS_PREFIX + inject + script + _JS_HELPERS + checks)
    result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_ai_review_script_never_assigns_inner_html():
    assert "innerHTML" not in ui_render._AI_CV_SCRIPT
    assert "insertAdjacentHTML" not in ui_render._AI_CV_SCRIPT


def test_pass_panel_shows_badge_changes_footer_and_no_actions(tmp_path):
    _run_page_js(tmp_path, r"""
  await load(result('PASS'));
  const t = pageText();
  assert(t.includes('AI-Reviewed CV') && t.includes('writer-model'));
  assert(findButton('Copy'));
  assert(t.includes('PASS — this rewrite will be used for ATS recheck and export'));
  assert(t.includes('Changes made') && t.includes('Reworded the summary'));
  assert(t.includes('Summary') && t.includes('Prepared reports'));
  assert(t.includes('Saved: job-1_ai_reviewed.md'));
  assert(t.includes('Advisory check by a second AI model. PASS does not prove every line is true.'));
  assert(!findButton('Approve this rewrite'));
  assert(!findButton('Revise once with findings'));
  assert(!t.includes('Findings'));
  assert.strictEqual(all(resultDiv).filter(n => n.className.includes('ai-cv-flagged')).length, 0);
  assert.strictEqual(innerHtmlWrites.length, 0);
""")


def test_blocked_panel_lists_findings_flags_lines_and_confirms_before_approve(tmp_path):
    _run_page_js(tmp_path, r"""
  await load(withFindings('BLOCKED'));
  const t = pageText();
  assert(t.includes('BLOCKED — not used until you approve it'));
  // findings: statement, verdict, reason, severity, removed lines; SUPPORTED and cleared ones are not listed
  assert(t.includes('Findings') && t.includes('UNSUPPORTED') && t.includes('No such meeting in the CV.'));
  assert(t.includes('BLOCKER'));
  assert(t.includes('Original lines in this block:') && t.includes('Led the weekly planning meeting'));
  assert(t.includes('L0-1') && t.includes('MAJOR') && t.includes('A number is new.'));
  assert(!t.includes('Only listed as supported') && !t.includes('Cleared finding text'));
  // panel order
  const order = ['AI-Reviewed CV', 'BLOCKED —', 'Findings', 'Changes made', 'Saved:',
                 'Advisory check by a second AI model.'].map(s => t.indexOf(s));
  assert(order.every((p, i) => p >= 0 && (i === 0 || p > order[i - 1])), String(order));
  // flagged rewrite lines carry a marker span and a class; the clean line does not
  const flagged = all(resultDiv).filter(n => n.className.includes('ai-cv-flagged'));
  assert.deepStrictEqual(flagged.map(n => domText(n)),
    ['⚑ Ran the weekly planning meeting', '⚑ Prepared reports']);
  assert(flagged.every(n => n.children[0].className === 'ai-cv-flag' && n.children[0].textContent === '⚑ '));
  const summary = all(resultDiv).find(n => n.className === 'ai-cv-line' && domText(n) === 'Summary');
  assert(summary, 'the unflagged line is a plain ai-cv-line');
  assert(findButton('Approve this rewrite') && findButton('Revise once with findings'));

  // confirm refused: nothing is sent
  const asked = [];
  window.confirm = m => { asked.push(m); return false; };
  const before = calls.length;
  const approve = findButton('Approve this rewrite');
  approve.listeners.click();
  assert.strictEqual(calls.length, before);
  assert.deepStrictEqual(asked, ['This rewrite was BLOCKED by the check. Use it anyway?']);
  assert(!approve.disabled, 'a cancelled confirm leaves the button usable');

  // confirm accepted: POST with generation id and hash, button disabled meanwhile, badge turns approved
  window.confirm = () => true;
  nextResponse = respond(true, {ok: true, verdict: 'BLOCKED', approval: APPROVAL});
  approve.listeners.click();
  assert.strictEqual(approve.disabled, true);
  const sent = calls.at(-1);
  assert.strictEqual(sent.url, '/job/job-1/ai-review-cv/approve');
  assert.strictEqual(sent.method, 'POST');
  assert.deepStrictEqual(sent.body, {generation_id: 'gen-1', rewrite_sha256: 'hash-1'});
  await flush();
  assert(pageText().includes('Approved — this rewrite will be used'));
  assert(!pageText().includes('not used until you approve it'));
  assert(!findButton('Approve this rewrite'));
  assert(findButton('Revise once with findings'), 'revise stays available for an unrevised rewrite');
  assert.strictEqual(innerHtmlWrites.length, 0);
""")


def test_needs_edit_approve_sends_without_confirm(tmp_path):
    _run_page_js(tmp_path, r"""
  await load(withFindings('NEEDS_EDIT'));
  assert(pageText().includes('NEEDS EDIT — not used until you approve it'));
  window.confirm = () => { throw new Error('confirm must only be asked for BLOCKED'); };
  nextResponse = respond(true, {ok: true, verdict: 'NEEDS_EDIT', approval: APPROVAL});
  findButton('Approve this rewrite').listeners.click();
  assert.deepStrictEqual(calls.at(-1).body, {generation_id: 'gen-1', rewrite_sha256: 'hash-1'});
  await flush();
  assert(pageText().includes('Approved — this rewrite will be used'));
  assert.strictEqual(innerHtmlWrites.length, 0);
""")


def test_unchecked_panel_is_not_approved_and_has_no_revise(tmp_path):
    _run_page_js(tmp_path, r"""
  await load(result('UNCHECKED'));
  assert(pageText().includes('Not checked — not approved'));
  assert(findButton('Approve this rewrite'));
  assert(!findButton('Revise once with findings'));
  // a response with no review, or an unknown verdict, is never shown as PASS
  const noReview = result('PASS'); delete noReview.review;
  await load(noReview);
  assert(pageText().includes('Not checked — not approved') && !pageText().includes('PASS —'));
  await load(result('SURPRISE'));
  assert(pageText().includes('Not checked — not approved') && !pageText().includes('PASS —'));
  assert.strictEqual(innerHtmlWrites.length, 0);
""")


def test_revise_sends_consent_unchecks_box_and_renders_round_one(tmp_path):
    _run_page_js(tmp_path, r"""
  await load(withFindings('NEEDS_EDIT'));
  consent.checked = true;
  nextResponse = respond(true, withFindings('BLOCKED', {generation_id: 'gen-2', rewrite_sha256: 'hash-2',
    revise_round: 1, reviewed_cv: 'Second draft line'}));
  findButton('Revise once with findings').listeners.click();
  const sent = calls.at(-1);
  assert.strictEqual(sent.url, '/job/job-1/ai-review-cv/revise');
  assert.strictEqual(sent.method, 'POST');
  assert.deepStrictEqual(sent.body, {use_cloud: true, consent_scope: 'gemini', generation_id: 'gen-1'});
  assert.strictEqual(sent.checkedWhenSent, true);
  assert.strictEqual(consent.checked, false, 'unchecked right after the request is sent');
  assert.strictEqual(btn.disabled, true);
  assert(pageText().includes('please wait'), 'same wait state as a rewrite');
  await flush();
  assert.strictEqual(consent.checked, false);
  assert.strictEqual(btn.disabled, false);
  assert(pageText().includes('Second draft line') && pageText().includes('BLOCKED —'));
  assert(findButton('Approve this rewrite'));
  assert(!findButton('Revise once with findings'), 'round 1 cannot be revised again');

  // unticked box: use_cloud false is sent as it is
  await load(withFindings('BLOCKED'));
  nextResponse = respond(false, {ok: false, error: 'consent_required'});
  findButton('Revise once with findings').listeners.click();
  assert.deepStrictEqual(calls.at(-1).body, {use_cloud: false, consent_scope: 'gemini', generation_id: 'gen-1'});
  await flush();

  // a failed request unchecks the box too, and the previous result is back with its buttons
  await load(withFindings('NEEDS_EDIT'));
  consent.checked = true;
  global.fetch = () => Promise.reject(new Error('offline'));
  findButton('Revise once with findings').listeners.click();
  assert.strictEqual(consent.checked, false);
  await flush();
  assert.strictEqual(consent.checked, false);
  assert(pageText().includes('Revise failed: offline'));
  assert(findButton('Revise once with findings') && findButton('Approve this rewrite'));

  // a box ticked again while the request is pending is cleared when the request fails
  global.fetch = RECORDING_FETCH;
  await load(withFindings('NEEDS_EDIT'));
  consent.checked = true;
  let failRequest;
  global.fetch = () => new Promise((resolve, reject) => { failRequest = reject; });
  findButton('Revise once with findings').listeners.click();
  assert.strictEqual(consent.checked, false);
  consent.checked = true;
  failRequest(new Error('offline'));
  await flush();
  assert.strictEqual(consent.checked, false, 'unchecked after the failed request');
  assert.strictEqual(innerHtmlWrites.length, 0);
""")


def test_every_error_code_is_shown_as_its_message(tmp_path):
    _run_page_js(tmp_path, r"""
  const TICK = 'Tick the box to send your CV to Google Gemini, then click ';
  // rewrite (AI Review CV button)
  const rewriteCases = [
    ['consent_required', TICK + 'AI Review CV again.'],
    ['cv_too_long_for_ai_review', 'Your CV is longer than 15,000 characters, so AI review cannot run on it.'],
    ['stale', STALE], ['busy', BUSY],
    ['No master CV on profile. Upload your CV on the Profile page first.',
     'No master CV on profile. Upload your CV on the Profile page first.'],
  ];
  for (const [code, message] of rewriteCases) {
    nextResponse = respond(false, {ok: false, error: code});
    click(); await flush();
    assert.strictEqual(resultDiv.children.length, 1);
    assert.strictEqual(resultDiv.children[0].textContent, message);
  }

  // revise (button inside the result)
  const reviseCases = [
    ['consent_required', TICK + 'Revise once with findings again.'],
    ['inputs_changed', 'Your CV or profile changed since this review. Run AI Review CV again.'],
    ['not_revisable', 'This rewrite cannot be revised again.'],
    ['stale', STALE], ['busy', BUSY],
    ['writer_failed', 'Revise failed: writer_failed'],
  ];
  for (const [code, message] of reviseCases) {
    await load(withFindings('BLOCKED'));
    nextResponse = respond(false, {ok: false, error: code});
    findButton('Revise once with findings').listeners.click();
    await flush();
    assert(pageText().includes(message), code + ': ' + pageText());
  }
  // a retryable error keeps the result and its revise button; an out-of-date one replaces it
  await load(withFindings('BLOCKED'));
  nextResponse = respond(false, {ok: false, error: 'consent_required'});
  findButton('Revise once with findings').listeners.click(); await flush();
  assert(findButton('Revise once with findings') && pageText().includes('Summary'));
  nextResponse = respond(false, {ok: false, error: 'stale'});
  findButton('Revise once with findings').listeners.click(); await flush();
  assert(!findButton('Revise once with findings') && !pageText().includes('Summary'));

  // approve
  const approveCases = [
    ['stale', STALE], ['busy', BUSY],
    ['bad_request', 'Approve failed: bad_request'],
    ['', 'Approve failed: Error'],
  ];
  for (const [code, message] of approveCases) {
    await load(withFindings('NEEDS_EDIT'));
    nextResponse = respond(false, {ok: false, error: code});
    const approve = findButton('Approve this rewrite');
    approve.listeners.click();
    assert.strictEqual(approve.disabled, true);
    await flush();
    assert(pageText().includes(message), code + ': ' + pageText());
    assert.strictEqual(approve.disabled, false, 'the button works again after a failure');
  }
  await load(withFindings('NEEDS_EDIT'));
  global.fetch = () => Promise.reject(new Error('offline'));
  findButton('Approve this rewrite').listeners.click(); await flush();
  assert(pageText().includes('Approve failed: offline'));
  assert(findButton('Approve this rewrite'));

  // network error on a rewrite
  click(); await flush();
  assert.strictEqual(resultDiv.children[0].textContent, 'Request failed: offline');
  assert.strictEqual(innerHtmlWrites.length, 0);
""")


def test_server_text_appears_only_as_text_and_never_writes_inner_html(tmp_path):
    _run_page_js(tmp_path, r"""
  const evil = withFindings('BLOCKED', {
    reviewed_cv: BAD + '\nPrepared reports', changes: [BAD], saved_path: BAD, model_used: BAD,
    review: {verdict: 'BLOCKED', reviewer_model: BAD,
      items: [Object.assign({}, ITEM, {text: BAD, reason: BAD, removed: [BAD]})],
      l0_findings: [Object.assign({}, L0_OPEN, {detail: BAD})]}});
  await load(evil);
  const holders = all(resultDiv).filter(n => n._text.includes(BAD));
  // statement, reason, removed line, change entry, rewrite line, saved path, L0 detail, model
  assert(holders.length >= 8, 'found ' + holders.length);
  assert(all(resultDiv).every(n => !['img', 'script', 'iframe'].includes(n.tag)));
  assert(holders.every(n => !n.tag.startsWith('<')));
  const flagged = all(resultDiv).filter(n => n.className.includes('ai-cv-flagged'));
  assert(flagged.some(n => domText(n) === '⚑ ' + BAD), 'a rewrite line equal to a statement is flagged');

  // error text, from the server and from the network, on every path
  nextResponse = respond(false, {ok: false, error: BAD});
  click(); await flush();
  assert.strictEqual(resultDiv.children[0].textContent, BAD);
  await load(evil);
  nextResponse = respond(false, {ok: false, error: BAD});
  findButton('Revise once with findings').listeners.click(); await flush();
  assert(pageText().includes('Revise failed: ' + BAD));
  nextResponse = respond(false, {ok: false, error: BAD});
  findButton('Approve this rewrite').listeners.click(); await flush();
  assert(pageText().includes('Approve failed: ' + BAD));
  global.fetch = () => Promise.reject(new Error(BAD));
  click(); await flush();
  assert.strictEqual(resultDiv.children[0].textContent, 'Request failed: ' + BAD);
  assert(all(resultDiv).every(n => n.tag !== 'img'));
  assert.strictEqual(innerHtmlWrites.length, 0, 'the AI review flow never writes innerHTML');
""")


@pytest.mark.parametrize("scope,models", [("gemini", ("gemini-3.5-flash",)),
                                          ("gemini+openai", ("gpt-6-luna", "gemini-3.5-flash"))])
@pytest.mark.parametrize("revise", [False, True])
@pytest.mark.parametrize("sent", [None, "gemini", "gemini+openai"])
def test_scope_gate_both_actions(env, monkeypatch, scope, models, revise, sent):
    monkeypatch.setattr(job_hunt_cv_review, "REVIEWER_MODELS", models)
    generation = Mock()
    monkeypatch.setattr(ui_handlers, "_run_ai_cv_generation", generation)
    # A valid current record lets the revise path reach the mocked generation.
    monkeypatch.setattr(job_hunt_cv_review, "read_review_record", lambda *a: {
        "generation_id": "g", "revise_round": 0, "verdict": "BLOCKED", "l0_findings": [], "items": []})
    monkeypatch.setattr(ui_handlers, "_ai_cv_binding_current", lambda *a: True)
    body = {"use_cloud": True, "generation_id": "g"}
    if sent is not None:
        body["consent_scope"] = sent
    responder = SimpleNamespace(send_json=Mock())
    ui_handlers.handle_ai_review_cv(SimpleNamespace(json_body=body), env.config, responder, JOB_ID, _revise=revise)
    if (sent or "gemini") != scope:
        generation.assert_not_called()
        env.writer.assert_not_called()
        assert responder.send_json.call_args.kwargs["status"] == HTTPStatus.CONFLICT
        assert responder.send_json.call_args.args[0] == {"error": "consent_stale" if sent else "AI services changed - reload the page"}
    else:
        generation.assert_called_once()
    body["use_cloud"] = False
    ui_handlers.handle_ai_review_cv(SimpleNamespace(json_body=body), env.config, responder, JOB_ID, _revise=revise)
    assert responder.send_json.call_args.kwargs["status"] == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize("scope", ["gemini", "gemini+openai"])
def test_scope_page_and_runtime(tmp_path, monkeypatch, scope):
    from dataclasses import replace
    from tests.test_cover_letter_form import _vm
    html = ui_render.render_job_page(replace(_vm(), consent_scope=scope))
    assert 'data-consent-scope="' + scope + '"' in html
    providers = "Google Gemini and OpenAI" if scope == "gemini+openai" else "Google Gemini"
    assert "Send my CV to " + providers + " for this rewrite and its check" in html
    assert "AI CV review sends the CV to " + (providers if scope == "gemini+openai" else "Gemini") + " only after the per-click consent." in html
    script = ui_render._AI_CV_SCRIPT
    prefix = _JS_PREFIX.replace("const consent = {checked: false};", "const consent = {checked: false, dataset: {consentScope: '" + scope + "'}};")
    body = """
(async () => {
  consent.checked=true;
  nextResponse=respond(false,{error:'consent_stale'}); click();
  assert(pageText().includes(EXPECTED_PROGRESS)); await flush();
  assert.deepStrictEqual(calls.at(-1).body,{use_cloud:true,consent_scope:SCOPE});
  assert(pageText().includes('The AI services used for this check have changed. Reload the page and tick the box again.'));
  await load(result('BLOCKED'));
  consent.checked=true; nextResponse=respond(false,{error:'consent_stale'});
  findButton('Revise once with findings').listeners.click(); await flush();
  assert.deepStrictEqual(calls.at(-1).body,{use_cloud:true,consent_scope:SCOPE,generation_id:'gen-1'});
  assert(pageText().includes('The AI services used for this check have changed. Reload the page and tick the box again.'));
  nextResponse=respond(false,{error:'consent_required'}); click(); await flush();
  assert(pageText().includes('Tick the box to send your CV to PROVIDERS, then click AI Review CV again.'));
  await load(result('BLOCKED'));
  nextResponse=respond(false,{error:'consent_required'});
  findButton('Revise once with findings').listeners.click(); await flush();
  assert(pageText().includes('Tick the box to send your CV to PROVIDERS, then click Revise once with findings again.'));
  console.log('ok');
})().catch(e=>{console.error(e);process.exitCode=1;});
""".replace('PROVIDERS', providers).replace('SCOPE', repr(scope)).replace('EXPECTED_PROGRESS', repr('Reviewing your CV against this job' if scope == 'gemini+openai' else 'Gemini is reviewing your CV against this job — please wait…'))
    node = shutil.which('node')
    if not node:
        pytest.skip('node not available')
    path = tmp_path / 'scope.js'
    path.write_text(prefix + script + _JS_HELPERS + body)
    result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_old_script_readable_scope_less_409(tmp_path, env, monkeypatch):
    import json
    monkeypatch.setattr(job_hunt_cv_review, 'REVIEWER_MODELS', ('gpt-6-luna', 'gemini-3.5-flash'))
    payload, status = _call(env, SimpleNamespace(json_body={'use_cloud': True}))
    assert status == HTTPStatus.CONFLICT
    env.writer.assert_not_called()
    git = shutil.which('git')
    if not git:
        pytest.skip('git not available for historical UI script')
    try:
        old = subprocess.run([git, 'show', '0e56f5c:src/ui_render.py'],
                             capture_output=True, text=True, check=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip('historical UI script commit 0e56f5c not available')
    script = re.search(r'_AI_CV_SCRIPT = r"""(.*?)"""', old, re.S).group(1)
    body = """
(async()=>{
 nextResponse=respond(false,SERVER_ERROR);
 click(); await flush();
 assert(pageText().includes('AI services changed - reload the page'));
 await load(result('BLOCKED'));
 nextResponse=respond(false,SERVER_ERROR);
 findButton('Revise once with findings').listeners.click(); await flush();
 assert(pageText().includes('Revise failed: AI services changed - reload the page'));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    node = shutil.which('node')
    if not node:
        pytest.skip('node not available')
    path = tmp_path / 'old-scope.js'
    path.write_text(_JS_PREFIX + script + _JS_HELPERS + body.replace("SERVER_ERROR", json.dumps(payload)))
    result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('scope', ['gemini', 'gemini+openai'])
@pytest.mark.parametrize('page', ['board', 'home', 'profile', 'digest'])
def test_all_sidebar_entrypoints_receive_scope(scope, page):
    if page == 'board':
        html = ui_render.render_board_page({}, consent_scope=scope)
    elif page == 'home':
        html = ui_render.render_home_page(profile_name='Synthetic', profile_target_roles=[], history=[],
                                         values={}, error=None, consent_scope=scope)
    elif page == 'profile':
        html = ui_render.render_profile_page(profile_id='synthetic', vm=ui_handlers._build_profile_page_vm(None),
                                            parsed_cv_text=None, parsed_filename=None, errors={}, form_values=None,
                                            consent_scope=scope)
    else:
        html = ui_render.render_digest_page(entries=[], filters={}, sources=[], saved_searches=[], consent_scope=scope)
    assert ('AI CV review sends the CV to ' + ('Google Gemini and OpenAI' if scope == 'gemini+openai' else 'Gemini')
            + ' only after the per-click consent.') in html
