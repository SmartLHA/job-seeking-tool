"""Synthetic actual-page callback regressions for the result text boundary."""
from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from browser_support import launch_chromium, loopback_page, playwright_sync
from src import ui_render
from src.ui_render import JobPageViewModel


HOSTILE = ('<img id="s2-injected" src=x onerror="window.__s2Executed++">'
           '<svg onload="window.__s2Executed++"></svg>'
           '<script>window.__s2Executed++</script> "quotes" \'single\' & £ 中文\nnext line')


def _vm():
    """Construct the real page model using only synthetic values."""
    values = {}
    for field in dataclasses.fields(JobPageViewModel):
        kind = str(field.type)
        values[field.name] = [] if kind.startswith('list') else False if kind.startswith('bool') else '' if kind.startswith('str') and 'None' not in kind else None
    values.update(job_id='s2-synthetic', job_title=HOSTILE, company='Synthetic Co',
                  has_analysis=True, match_score=85.0, confidence='high',
                  decision='apply', effective_decision='apply', flash_kind='info',
                  model_label='synthetic', source_type='copied_text')
    return JobPageViewModel(**values)


def test_actual_rendered_result_callback_has_no_html_assignment():
    tree = ast.parse(inspect.getsource(ui_render.render_job_page))
    assignment = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'tailor_cover_js' for target in node.targets))
    assert not any(isinstance(node, ast.FormattedValue) for node in ast.walk(assignment.value))
    assert [node.id for node in ast.walk(assignment.value) if isinstance(node, ast.Name)] == ['_AI_CV_SCRIPT']
    html = ui_render.render_job_page(_vm())
    script = next(s for s in re.findall(r'<script>(.*?)</script>', html, re.S)
                  if s.startswith('/* tailor + cover */'))
    assert ui_render._AI_CV_SCRIPT in script
    for sink in ('.innerHTML', '.outerHTML', 'insertAdjacentHTML', 'document.write'):
        assert sink not in script
    assert 'tcNode("pre"' in script
    assert 'textContent' in script
    assert '<img id="s2-injected"' not in html


@pytest.fixture
def synthetic_page():
    """Serve only this synthetic page and two fake same-origin JSON producers."""
    state = SimpleNamespace(response={}, status=200, calls=[])
    html = ui_render.render_job_page(_vm()).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path != '/job':
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def do_POST(self):
            if self.path not in {'/tailor', '/cover-letter'}:
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            state.calls.append((self.path, body))
            output = json.dumps(state.response).encode()
            self.send_response(state.status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(output)))
            self.end_headers()
            self.wfile.write(output)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    sync, _ = playwright_sync()
    try:
        with sync() as playwright:
            browser = launch_chromium(playwright)
            page = loopback_page(browser, origin)
            # Catch local execution independently of any attempted network access.
            # Rejections below exercise the actual callback catch, with hostile text.
            page.add_init_script('''window.__s2Executed=0; window.__s2Calls=[];
                const nativeFetch=window.fetch.bind(window);
                window.fetch=(url,opts)=>{
                    window.__s2Calls.push({url,body:JSON.parse(opts.body)});
                    if(window.__s2Reject) return Promise.reject(new Error(window.__s2Reject));
                    return nativeFetch(url,opts);
                };''')
            page.goto(origin + '/job')
            yield SimpleNamespace(page=page, state=state)
            page.context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


def _safe(page, selector):
    snapshot = {'executions': page.evaluate('window.__s2Executed'),
        'injected_nodes': page.locator('#s2-injected').count(),
        'inline_handlers': page.locator(selector + ' *').evaluate_all(
            '(nodes)=>nodes.flatMap(n=>Array.from(n.attributes).filter(a=>a.name.startsWith("on")).map(a=>a.name))')}
    print('S2 DOM boundary:', json.dumps(snapshot))
    assert snapshot == {'executions': 0, 'injected_nodes': 0, 'inline_handlers': []}
    assert page.locator(selector + ' img,' + selector + ' svg,' + selector + ' script').count() == 0
    assert page.locator(selector + ' [onerror],' + selector + ' [onload],' + selector + ' a').count() == 0
    assert page.locator('#s2-injected').count() == 0


@pytest.mark.required_browser
@pytest.mark.parametrize('hostile_counts', [False, True], ids=['ordinary-counts', 'hostile-counts'])
def test_tailor_callback_renders_strings_and_counts_as_literal_text(synthetic_page, hostile_counts):
    page, state = synthetic_page.page, synthetic_page.state
    item = {'length': HOSTILE} if hostile_counts else ['synthetic']
    state.response = {'saved_path': HOSTILE, 'summary': HOSTILE,
                      'promoted': item, 'matched': item, 'missing': item}
    page.click('#tailor-btn')
    page.wait_for_function('document.querySelector("#tailor-btn").textContent === "CV Tailored ✓"')
    _safe(page, '#tailor-result')
    assert state.calls == [('/tailor', {'job_id': 's2-synthetic', 'manual_selected': True})]
    assert page.locator('#tailor-result code').text_content() == HOSTILE
    assert page.locator('#tailor-result p').nth(2).text_content() == HOSTILE
    count = HOSTILE if hostile_counts else '1'
    assert page.locator('#tailor-result span').all_text_contents() == [
        f'✓ {count} promoted', f'✓ {count} matched', f'⚠ {count} missing']
    assert page.locator('#tailor-btn').is_enabled()


def _cover_inputs(page):
    page.click('#cover-btn')
    assert page.locator('#cover-panel').is_visible()
    page.locator('[name=why_company_text]').fill('  Synthetic reason\nsecond line  ')
    page.locator('[name=points]').fill('  First point \n\n Second point  ')


@pytest.mark.required_browser
def test_cover_callback_preserves_text_newlines_controls_and_payload(synthetic_page):
    page, state = synthetic_page.page, synthetic_page.state
    _cover_inputs(page)
    state.response = {'word_count': HOSTILE, 'saved_path': HOSTILE, 'letter': HOSTILE}
    page.locator('#cover-letter-form button[type=submit]').click()
    page.wait_for_function('!!document.querySelector("#cover-letter-result pre")')
    _safe(page, '#cover-letter-result')
    assert state.calls == [('/cover-letter', {'job_id': 's2-synthetic',
        'why_company_text': 'Synthetic reason\nsecond line', 'tone': 'professional',
        'length': 'standard', 'points': ['First point', 'Second point']})]
    assert page.locator('#cover-letter-result p').first.text_content() == f'Cover letter generated ({HOSTILE} words).'
    assert page.locator('#cover-letter-result code').text_content() == HOSTILE
    assert page.locator('#cover-letter-result pre').text_content() == HOSTILE
    assert page.locator('#cover-letter-result summary').text_content() == 'Preview letter'
    assert page.locator('#cover-letter-spinner').is_hidden()
    assert page.locator('#cover-letter-form button[type=submit]').is_enabled()
    page.click('#cover-btn')
    assert page.locator('#cover-panel').is_hidden()


@pytest.mark.required_browser
@pytest.mark.parametrize('flow', ['tailor', 'cover'])
@pytest.mark.parametrize('failure', ['http', 'rejection'])
def test_result_errors_are_literal_and_controls_recover(synthetic_page, flow, failure):
    page, state = synthetic_page.page, synthetic_page.state
    state.response, state.status = {'error': HOSTILE}, 422
    if failure == 'rejection':
        page.evaluate('(value)=>window.__s2Reject=value', HOSTILE)
    if flow == 'tailor':
        page.click('#tailor-btn')
        selector = '#tailor-result'
    else:
        _cover_inputs(page)
        page.locator('#cover-letter-form button[type=submit]').click()
        selector = '#cover-letter-result'
    expected = ('Request failed: ' if failure == 'rejection' else '') + HOSTILE
    page.wait_for_function('([selector,text])=>document.querySelector(selector).textContent===text', arg=[selector, expected])
    assert page.locator(selector + ' p').text_content() == expected
    if flow == 'tailor':
        assert page.locator('#tailor-btn').is_enabled()
        assert page.locator('#tailor-btn').text_content() == 'Tailor CV'
    else:
        assert page.locator('#cover-letter-spinner').is_hidden()
        assert page.locator('#cover-letter-form button[type=submit]').is_enabled()
    _safe(page, selector)


@pytest.mark.required_browser
def test_cover_validation_keeps_defaults_and_omits_empty_points(synthetic_page):
    page, state = synthetic_page.page, synthetic_page.state
    page.click('#cover-btn')
    page.locator('#cover-letter-form button[type=submit]').click()
    assert page.locator('#cover-letter-result').text_content() == 'Please fill in Why this company?.'
    assert state.calls == []
    page.locator('[name=why_company_text]').fill(' synthetic ')
    state.response = {'letter': 'plain\nletter', 'word_count': 2}
    page.locator('#cover-letter-form button[type=submit]').click()
    page.wait_for_function('!!document.querySelector("#cover-letter-result pre")')
    assert state.calls == [('/cover-letter', {'job_id': 's2-synthetic',
        'why_company_text': 'synthetic', 'tone': 'professional', 'length': 'standard'})]
    _safe(page, '#cover-letter-result')


@pytest.mark.required_browser
def test_ai_shared_result_keeps_original_copy_consent_and_bound_actions(synthetic_page):
    page = synthetic_page.page
    original = 'Synthetic CV\n' + HOSTILE
    data = {'ok': True, 'reviewed_cv': original, 'changes': [HOSTILE],
        'model_used': HOSTILE, 'saved_path': HOSTILE, 'generation_id': 's2-gen',
        'rewrite_sha256': 's2-hash', 'revise_round': 0, 'approval': None,
        'review': {'verdict': 'BLOCKED', 'reviewer_model': HOSTILE,
            'items': [{'id': 's2-item', 'block_key': HOSTILE, 'text': HOSTILE.split('\n')[0],
                'verdict': 'UNSUPPORTED', 'evidence_quote': HOSTILE, 'reason': HOSTILE,
                'severity': 'BLOCKER', 'removed': [HOSTILE]}], 'l0_findings': []}}
    calls = []

    def respond(route):
        path = route.request.url.split('/ai-review-cv', 1)[1]
        calls.append((path, route.request.post_data_json))
        if path == '/approve':
            body = {'ok': True, 'approval': {'approved_at': 'synthetic',
                'generation_id': 's2-gen', 'rewrite_sha256': 's2-hash'}}
        elif path == '/revise':
            body = dict(data, generation_id='s2-gen-2', rewrite_sha256='s2-hash-2', revise_round=1)
        else:
            assert path == ''
            body = data
        route.fulfill(status=200, content_type='application/json', body=json.dumps(body))

    page.route('**/job/s2-synthetic/ai-review-cv**', respond)
    page.evaluate('''() => {
        window.__s2Clipboard=[];
        Object.defineProperty(navigator,'clipboard',{configurable:true,
            value:{writeText:async text=>{window.__s2Clipboard.push(text);}}});
    }''')
    page.locator('#ai-cv-consent').check()
    page.click('#ai-cv-btn')
    page.wait_for_selector('.ai-cv-panel')
    assert not page.locator('#ai-cv-consent').is_checked()
    assert calls == [('', {'use_cloud': True})]
    assert page.locator('.ai-cv-flagged').count() >= 1
    assert HOSTILE in page.locator('#tailor-result').text_content()
    _safe(page, '#tailor-result')
    page.click('#ai-cv-copy-btn')
    page.wait_for_function('window.__s2Clipboard.length===1')
    assert page.evaluate('window.__s2Clipboard') == [original]
    page.once('dialog', lambda dialog: dialog.accept())
    page.get_by_role('button', name='Approve this rewrite', exact=True).click()
    page.wait_for_function('document.querySelector(".ai-cv-badge").textContent.includes("Approved")')
    assert calls[-1] == ('/approve', {'generation_id': 's2-gen', 'rewrite_sha256': 's2-hash'})
    page.locator('#ai-cv-consent').check()
    page.get_by_role('button', name='Revise once with findings', exact=True).click()
    page.wait_for_function('!Array.from(document.querySelectorAll(".ai-cv-panel button")).some(b=>b.textContent==="Revise once with findings")')
    assert calls[-1] == ('/revise', {'use_cloud': True, 'generation_id': 's2-gen'})
    assert not page.locator('#ai-cv-consent').is_checked()
    assert page.get_by_role('button', name='Revise once with findings', exact=True).count() == 0
    _safe(page, '#tailor-result')
