"""CV consent checks use synthetic text and mocked providers only."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import job_hunt_llm, job_hunt_parsing, ui_handlers

TEXT = 'Synthetic CV: SQL, Python and stakeholder management.'


@pytest.mark.parametrize('consent', [False, None, 'false', 'true', 1, 'invalid'])
def test_wrapper_requires_explicit_boolean_consent(monkeypatch, consent):
    provider = Mock(side_effect=AssertionError('Provider must remain unused'))
    monkeypatch.setattr(job_hunt_llm, 'extract_cv_skills_with_llm', provider)
    skills, warning = job_hunt_parsing.extract_skills_from_cv(TEXT, use_cloud=consent)
    assert 'SQL' in skills and 'Python' in skills
    assert warning is None
    provider.assert_not_called()


def test_wrapper_default_is_useful_and_local(monkeypatch):
    provider = Mock(side_effect=AssertionError('Provider must remain unused'))
    monkeypatch.setattr(job_hunt_llm, 'extract_cv_skills_with_llm', provider)
    skills, warning = job_hunt_parsing.extract_skills_from_cv(TEXT)
    assert 'SQL' in skills and 'Python' in skills
    assert warning is None
    provider.assert_not_called()


@pytest.mark.parametrize('raises', [False, True])
def test_requested_cloud_failure_returns_real_local_skills(monkeypatch, raises):
    provider = Mock(side_effect=RuntimeError('synthetic outage')) if raises else Mock(return_value=(None, 'synthetic outage'))
    monkeypatch.setattr(job_hunt_llm, 'extract_cv_skills_with_llm', provider)
    skills, warning = job_hunt_parsing.extract_skills_from_cv(TEXT, use_cloud=True)
    assert 'SQL' in skills and 'Python' in skills
    assert 'Gemini' in warning and 'local keyword fallback' in warning
    provider.assert_called_once_with(TEXT)


@pytest.mark.parametrize('value', [None, b'', b'false', b'False', b'true ', b'1', b'yes', b'invalid', b'\xff', b'true'])
def test_handler_consent_controls_provider_and_current_text(monkeypatch, value):
    form = {'cv_file': {'filename': 'synthetic.txt', 'content': TEXT.encode()}}
    if value is not None:
        form['use_cloud'] = {'content': value}
    monkeypatch.setattr(ui_handlers, 'parse_multipart_form', lambda req: form)
    provider = Mock(return_value=(['Synthetic cloud skill'], None))
    monkeypatch.setattr(job_hunt_llm, 'extract_cv_skills_with_llm', provider)
    responder = SimpleNamespace(send_json=Mock())
    ui_handlers.handle_parse_cv(SimpleNamespace(headers={'Content-Type': 'multipart/form-data'}), SimpleNamespace(), responder)
    result = responder.send_json.call_args.args[0]
    assert result['ok'] is True and result['master_cv_text'] == TEXT
    assert result['skill_extraction_warning'] is None
    if value == b'true':
        provider.assert_called_once_with(TEXT)
        assert result['suggested_skills'] == ['Synthetic cloud skill']
    else:
        provider.assert_not_called()
        assert 'SQL' in result['suggested_skills']


def test_handler_requested_cloud_failure_is_useful(monkeypatch):
    form = {'cv_file': {'filename': 'synthetic.txt', 'content': TEXT.encode()}, 'use_cloud': {'content': b'true'}}
    monkeypatch.setattr(ui_handlers, 'parse_multipart_form', lambda req: form)
    monkeypatch.setattr(job_hunt_llm, 'extract_cv_skills_with_llm', Mock(return_value=(None, 'synthetic outage')))
    responder = SimpleNamespace(send_json=Mock())
    ui_handlers.handle_parse_cv(SimpleNamespace(headers={'Content-Type': 'multipart/form-data'}), SimpleNamespace(), responder)
    result = responder.send_json.call_args.args[0]
    assert result['ok'] is True and 'SQL' in result['suggested_skills']
    assert 'local keyword fallback' in result['skill_extraction_warning']


def test_requested_cloud_provider_receives_only_disclosed_text_limit(monkeypatch):
    text = 'SQL ' + 'a' * 11996 + 'NOT_SENT_SUFFIX'
    provider = Mock(return_value=('{"skills": ["SQL"]}', None))
    monkeypatch.setattr(job_hunt_llm, '_call_gemini', provider)
    skills, warning = job_hunt_parsing.extract_skills_from_cv(text, use_cloud=True)
    assert skills == ['SQL'] and warning is None
    prompt = provider.call_args.args[0]
    assert text[:12000] in prompt and 'NOT_SENT_SUFFIX' not in prompt


def _profile_html():
    from src.ui_render import ProfilePageViewModel, render_profile_page
    vm = ProfilePageViewModel(has_profile=True, name='Synthetic', target_roles=[], locations=[],
        remote_preference='hybrid', salary_floor_gbp=0, right_to_work_uk=True, skills=[],
        years_experience=0, industries=[], certifications=[], achievements=[],
        master_cv_ref='', master_cv_text='')
    return render_profile_page(profile_id='synthetic', vm=vm, parsed_cv_text=None,
                               parsed_filename=None, errors={}, form_values=None)


def test_ui_consent_is_unchecked_and_disclosure_is_accurate():
    from html.parser import HTMLParser
    class Inputs(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'input' and attrs.get('id') == 'cv-cloud-consent':
                self.consent = attrs
    parser = Inputs()
    html = _profile_html()
    parser.feed(html)
    assert parser.consent['type'] == 'checkbox' and 'checked' not in parser.consent
    assert 'CV text parsing and skill suggestions run locally by default.' in html
    assert 'send up to 12,000 characters of extracted CV text to Google Gemini' in html
    assert 'Profile, jobs &amp; outcomes stay on this device' not in html
    assert 'Powered by Ollama' not in html
    assert 'Optional Gemini features send relevant text to Google' in html


def test_executed_upload_script_sends_explicit_consent_and_shows_fallback(tmp_path):
    import re
    import shutil
    import subprocess
    html = _profile_html()
    scripts = re.findall(r'<script>(.*?)</script>', html, re.S)
    script = next(s for s in scripts if 'var fileInput = document.getElementById("cv-file-input")' in s)
    script = script[:script.index('})();') + len('})();')]
    # Only execute the actual upload IIFE with synthetic UI and provider responses.
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    prefix = r'''
const assert=require('assert');
let click, sent=[];
const status={style:{},textContent:''}, consent={checked:false};
const file={name:'synthetic.txt',size:20};
const ids={'cv-file-input':{files:[file]},'cv-upload-btn':{addEventListener:(type,fn)=>{assert.equal(type,'click');click=fn;}},
 'cv-upload-status':status,'cv-parsed-preview':{},'cv-cloud-consent':consent,
 'skills-tbody':{rows:[],appendChild:()=>{}}};
global.document={getElementById:id=>ids[id]||null,querySelector:()=>null};
global.FormData=class{constructor(){this.fields={};}append(k,v){this.fields[k]=v;}};
global.makeRow=()=>({});
global.fetch=async(url,opts)=>{assert.equal(url,'/profile/parse-cv');sent.push(opts.body.fields);
return {ok:true,json:async()=>({ok:true,master_cv_text:'Synthetic',suggested_skills:['SQL'],
 skill_extraction_warning:consent.checked?'Gemini unavailable; used local keyword fallback':null})};};
'''
    suffix = r'''
(async()=>{
await click();assert.equal(sent[0].use_cloud,'false');assert.equal(sent[0].cv_file,file);
assert(!status.textContent.includes('fallback'));
consent.checked=true;await click();assert.equal(sent[1].use_cloud,'true');
assert(status.textContent.includes('Added 1 skill'));assert(status.textContent.includes('local keyword fallback'));
console.log('CV upload consent runtime assertions passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    path = tmp_path / 'cv-consent.js'
    path.write_text(prefix + script + suffix)
    result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'CV upload consent runtime assertions passed'


@pytest.mark.parametrize('value', [None, 'false', 'true', 'invalid'])
def test_real_multipart_handler_preserves_consent_boundary(monkeypatch, value):
    boundary = 'synthetic-cv-boundary'
    body = b''
    if value is not None:
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="use_cloud"\r\n\r\n{value}\r\n').encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="cv_file"; filename="synthetic.txt"\r\nContent-Type: text/plain\r\n\r\n{TEXT}\r\n--{boundary}--\r\n').encode()
    provider = Mock(return_value=(['Synthetic cloud skill'], None))
    monkeypatch.setattr(job_hunt_llm, 'extract_cv_skills_with_llm', provider)
    responder = SimpleNamespace(send_json=Mock())
    req = SimpleNamespace(headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}, raw_body=body)
    ui_handlers.handle_parse_cv(req, SimpleNamespace(), responder)
    result = responder.send_json.call_args.args[0]
    assert result['ok'] and result['master_cv_text'] == TEXT
    if value == 'true':
        provider.assert_called_once_with(TEXT)
    else:
        provider.assert_not_called()
        assert 'SQL' in result['suggested_skills']
