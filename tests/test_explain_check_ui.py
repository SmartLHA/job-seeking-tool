"""Execute the rendered explanation/check script against a minimal browser DOM."""
from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from src import ui_render
from tests.test_cover_letter_form import _vm


HARNESS = r'''
const assert=require('assert');
class Element {
 constructor(){this.style={};this.children=[];this._text='';this.disabled=false;}
 set textContent(value){this._text=value;this.children=[];}
 get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
 set innerHTML(value){throw new Error('model text must not use innerHTML');}
 appendChild(child){this.children.push(child);return child;}
}
const elements={};
global.document={getElementById(id){return elements[id]||(elements[id]=new Element());},createElement(){return new Element();}};
const requests=[];
global.fetch=(url,opts)=>new Promise((resolve,reject)=>requests.push({url,opts,resolve,reject}));
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const reply=async(index,data,httpOk=true)=>{requests[index].resolve({ok:httpOk,json:()=>Promise.resolve(data)});await flush();};
const explanation=(token)=>({ok:true,fit:'legacy fit',risk:'legacy risk',action:'legacy action',check_token:token,
 statements:[{id:'fit-0',section:'fit',text:'<img src=x onerror=alert(1)>'},{id:'fit-1',section:'fit',text:'Second fit.'},
 {id:'risk-0',section:'risk',text:'Risk.'},{id:'action-0',section:'action',text:'Apply.'}]});
const label=id=>_aiStatements[id].label.textContent;
const status=()=>elements['ai-check-status'].textContent;
const explanationFour=(token)=>{const d=explanation(token);d.statements.splice(3,0,{id:'risk-1',section:'risk',text:'Second risk.'});return d;};
const explanationOne=(token)=>({ok:true,fit:'f',risk:'r',action:'a',check_token:token,
 statements:[{id:'fit-0',section:'fit',text:'Only fit.'},{id:'action-0',section:'action',text:'Apply.'}]});
const allOk={'fit-0':{verdict:'ok'},'fit-1':{verdict:'ok'},'risk-0':{verdict:'ok'},'risk-1':{verdict:'ok'},'action-0':{verdict:'ok'}};
const DONE_FOUR='Local check done: 4 sentences checked, 0 could not be confirmed';
'''


@pytest.mark.parametrize('scenario', [
    r'''
runAiAnalysis();await reply(0,explanation('one'));
assert(requests[1].url.endsWith('/explain-check'));assert.equal(requests[1].opts.method,'POST');
assert.deepEqual(JSON.parse(requests[1].opts.body),{check_token:'one'});
assert.equal(elements['ai-check-status'].textContent,'Checking against the information Gemini was given (local model)...');
assert.equal(elements['ai-fit'].children[0].id,'fit-0');
assert.equal(elements['ai-fit'].children[0]._text,'<img src=x onerror=alert(1)>');
assert.equal(label('action-0'),'advice - not checked');
await reply(1,{ok:true,state:'partial',results:{'risk-0':{verdict:'not_checked',reason:'time'},'unknown':{verdict:'could_not_confirm'},'fit-1':{verdict:'could_not_confirm'},'fit-0':{verdict:'ok'}}});
assert.equal(label('fit-0'),'');assert.equal(label('risk-0'),'not checked (time)');
assert.equal(label('fit-1'),'⚠ Local check could not confirm this from the information given to Gemini - may be wrong');
assert.equal(_aiStatements['risk-0'].label.style.color,'var(--ink-faint)');
assert.equal(elements['ai-check-footer'].style.display,'');
''',
    r'''
runAiAnalysis();await reply(0,explanation('old'));const oldLabel=_aiStatements['action-0'].label;
runAiAnalysis();assert.equal(_aiToken,null);assert.equal(oldLabel.textContent,'');
assert.equal(elements['ai-check-status'].textContent,'');assert.equal(elements['ai-check-footer'].style.display,'none');
await reply(2,explanation('new'));
await reply(1,{ok:true,state:'done',results:{'fit-0':{verdict:'could_not_confirm'}}});
assert.equal(label('fit-0'),'');assert.equal(elements['ai-check-status'].textContent,'Checking against the information Gemini was given (local model)...');
await reply(3,{ok:true,state:'stale'});assert.equal(label('fit-0'),'not checked (re-run)');
''',
    r'''
runAiAnalysis();await reply(0,explanation('one'));requests[1].reject(new Error('offline'));await flush();
assert.equal(elements['ai-result'].style.display,'');assert(elements['ai-fit'].textContent.includes('<img'));
assert.equal(elements['ai-check-status'].textContent,'Local check unavailable');
runAiAnalysis();await reply(2,explanation('two'));await reply(3,{ok:false,error:'failed'},false);
assert.equal(elements['ai-check-status'].textContent,'Local check unavailable');assert.equal(elements['ai-result'].style.display,'');
''',
    r'''
runAiAnalysis();await reply(0,explanation('one'));await reply(1,{ok:true,state:'busy'});
assert.equal(elements['ai-check-again'].style.display,'');_aiCheck(_aiToken);
assert.deepEqual(JSON.parse(requests[2].opts.body),{check_token:'one'});
_aiCheck(_aiToken);await reply(3,{ok:true,state:'done',results:{'fit-0':{verdict:'ok'}}});
await reply(2,{ok:true,state:'done',results:{'fit-0':{verdict:'could_not_confirm'}}});
assert.equal(label('fit-0'),'');assert.equal(elements['ai-check-again'].style.display,'none');
''',
    r'''
runAiAnalysis();await reply(0,{ok:true,fit:'Old fit <b>literal</b>',risk:'Old risk',action:'Old action'});
assert.equal(requests.length,1);assert.equal(elements['ai-fit'].textContent,'Old fit <b>literal</b>');
assert.equal(elements['ai-risk'].textContent,'Old risk');assert.equal(elements['ai-action'].textContent,'Old action');
assert.equal(elements['ai-check-footer'].style.display,'none');
''',
    # Summary line: done, nothing flagged. The action result must not be counted (4, not 5).
    r'''
runAiAnalysis();await reply(0,explanationFour('one'));
assert.equal(status(),'Checking against the information Gemini was given (local model)...');
await reply(1,{ok:true,state:'done',results:allOk});
assert.equal(status(),DONE_FOUR);
''',
    # Summary line: singular wording when exactly one sentence was checked and flagged.
    r'''
runAiAnalysis();await reply(0,explanationOne('one'));
await reply(1,{ok:true,state:'done',results:{'fit-0':{verdict:'could_not_confirm'},'action-0':{verdict:'could_not_confirm'}}});
assert.equal(status(),'Local check done: 1 sentence checked, 1 could not be confirmed');
''',
    # Summary line: partial. K counts not_checked plus statements with no result; action never counts.
    r'''
runAiAnalysis();await reply(0,explanationFour('one'));
await reply(1,{ok:true,state:'partial',results:{'fit-0':{verdict:'ok'},'fit-1':{verdict:'could_not_confirm'},
 'risk-0':{verdict:'not_checked',reason:'time'},'action-0':{verdict:'could_not_confirm'}}});
assert.equal(status(),'Local check stopped early: 2 checked, 1 could not be confirmed, 2 not checked');
''',
    # Summary line: a response for an old token must not overwrite the summary of the current run.
    r'''
runAiAnalysis();await reply(0,explanationFour('old'));
runAiAnalysis();await reply(2,explanationFour('new'));
await reply(3,{ok:true,state:'done',results:allOk});
assert.equal(status(),DONE_FOUR);
await reply(1,{ok:true,state:'partial',results:{'fit-0':{verdict:'could_not_confirm'}}});
assert.equal(status(),DONE_FOUR);assert.equal(label('fit-0'),'');
''',
    # Summary line: a late reply from a superseded request for the SAME token must not overwrite it either.
    r'''
runAiAnalysis();await reply(0,explanationFour('one'));await reply(1,{ok:true,state:'busy'});
_aiCheck(_aiToken);_aiCheck(_aiToken);
await reply(3,{ok:true,state:'done',results:allOk});
assert.equal(status(),DONE_FOUR);
await reply(2,{ok:true,state:'partial',results:{'fit-0':{verdict:'could_not_confirm'}}});
assert.equal(status(),DONE_FOUR);assert.equal(label('fit-0'),'');
''',
])
def test_explanation_check_browser_behaviour(tmp_path, scenario):
    node = shutil.which('node')
    if not node:
        pytest.skip('node not available')
    html = ui_render.render_job_page(_vm())
    assert 'Local check, advisory only. No label does not mean verified.' in html
    assert '>Check again</button>' in html
    script = next(s for s in re.findall(r'<script>(.*?)</script>', html, re.S) if s.startswith('/* AI Analysis */'))
    path = tmp_path / 'explain-check.js'
    path.write_text(HARNESS + script + '\n(async()=>{\n' + scenario + '\n})().catch(error=>{console.error(error);process.exitCode=1;});')
    result = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
