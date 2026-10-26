"""C0: the "AI Review CV" button sends nothing to Gemini without per-click consent.

Synthetic CV text only. Every test mocks the writer (``ai_rewrite_cv``) and
the Gemini transport, so no test can reach the network.
"""
from __future__ import annotations

import io
import re
import shutil
import subprocess
from html.parser import HTMLParser
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import job_hunt_llm, ui_handlers, ui_render
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

def _job_html() -> str:
    from tests.test_cover_letter_form import _vm
    return ui_render.render_job_page(_vm())


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
const resultDiv = {
  children: [], textContent: '',
  set innerHTML(v) { innerHtmlWrites.push(v); }, get innerHTML() { return innerHtmlWrites[innerHtmlWrites.length - 1] || ''; },
  appendChild(c) { this.children.push(c); },
};
const btn = {dataset: {jobId: 'job-1'}, disabled: false, textContent: 'AI Review CV',
  addEventListener: (t, fn) => { if (t === 'click') click = fn; }};
const ids = {'ai-cv-btn': btn, 'ai-cv-consent': consent, 'tailor-result': resultDiv};
let nextResponse = null;
global.document = {getElementById: id => ids[id] || null,
  createElement: tag => ({tag, style: {}, textContent: ''})};
global.window = {};
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
  assert.deepStrictEqual(calls[0].body, {use_cloud: false});
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
  assert.deepStrictEqual(calls[1].body, {use_cloud: true});
  assert.strictEqual(calls[1].checkedWhenSent, true);
  assert.strictEqual(consent.checked, false, 'checkbox must be unchecked right after the request is sent');
  await flush();
  assert.strictEqual(consent.checked, false);
  assert(resultDiv.innerHTML.includes('Synthetic rewrite'));

  // 3. the box does not stay ticked after a failed request either.
  consent.checked = true;
  global.fetch = (url, opts) => { calls.push({body: JSON.parse(opts.body)}); return Promise.reject(new Error('offline')); };
  click();
  assert.strictEqual(consent.checked, false);
  await flush();
  assert.deepStrictEqual(calls[2].body, {use_cloud: true});
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
  // only the "please wait" line was written through innerHTML; the error text was not.
  assert.strictEqual(innerHtmlWrites.length, writesBefore + 1);
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
