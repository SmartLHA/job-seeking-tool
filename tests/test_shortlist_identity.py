"""Exact shortlist identity and real shared-JS pagination, with synthetic jobs only."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest

from src.job_sources import _multiselect as M
from src.job_sources.adzuna_source import _render_adzuna_cards_fragment
from src.job_sources.linkedin_source import _render_cards
from src.job_sources.reed_source import _render_reed_cards_fragment
from src.ui_handlers import _render_other_results_fragment, _render_search_jobs_tab

RENDERERS = {
    "reed": _render_reed_cards_fragment,
    "adzuna": _render_adzuna_cards_fragment,
    "linkedin": _render_cards,
}


def _job(source, job_id, title="Original", **changes):
    row = dict(source=source, source_job_id=job_id, title=title, company="Synthetic Co",
               location="London", salary_display="£50k", employment_type="permanent",
               work_mode="remote", url=f"https://example.test/{source}/{job_id}",
               description_preview="Synthetic description", description_raw="Synthetic description",
               filter_notes="" if source == "linkedin" else [], source_snapshot_json='{"synthetic":true}')
    row.update(changes)
    return row


class _Cards(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.cards, self.ids, self.stack = [], [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "div":
            card = None
            if attrs.get("class") in ("jst-rc", "jst-rc-disabled"):
                card = dict(attrs=attrs, fields={})
                self.cards.append(card)
            self.stack.append(card)
        if tag == "input":
            card = next((item for item in reversed(self.stack) if item is not None), None)
            if card is not None:
                card["fields"][attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "div":
            self.stack.pop()


def _cards(source, rows, *, skip=0, nonce="n"):
    return _Cards(RENDERERS[source](rows, skip=skip, nonce=nonce))


@pytest.mark.parametrize("source", RENDERERS)
def test_identity_is_stable_across_offsets_and_metadata_changes(source):
    first = _cards(source, [_job(source, "42")], nonce="old").cards[0]
    later = _cards(source, [_job(source, "42", "Changed", url="https://example.test/new")], skip=99, nonce="new").cards[0]
    assert first["attrs"]["data-jst-id"] == later["attrs"]["data-jst-id"]
    assert later["fields"]["title"] == "Changed"
    assert later["fields"]["nonce"] == "new"


@pytest.mark.parametrize("source", RENDERERS)
def test_url_fallback_missing_identity_and_duplicate_markup(source):
    fallback = _job(source, None, url="https://example.test/stable?a=1&b=2")
    first = _cards(source, [fallback]).cards[0]
    second = _cards(source, [dict(fallback, source_job_id="   ", title="Changed")], skip=13).cards[0]
    assert first["attrs"]["data-jst-id"] == second["attrs"]["data-jst-id"]
    anonymous = _cards(source, [_job(source, None, url=" ")]).cards[0]
    assert anonymous["attrs"]["class"] == "jst-rc-disabled"
    assert "data-jst-id" not in anonymous["attrs"]
    assert not anonymous["fields"]
    repeated = _cards(source, [_job(source, "42"), _job(source, "42", "Latest")])
    assert len(repeated.cards) == 1
    assert repeated.cards[0]["fields"]["title"] == "Latest"
    assert len(repeated.ids) == len(set(repeated.ids))
    assert _cards(source, [_job(source, 0)]).cards[0]["attrs"]["class"] == "jst-rc"


def test_same_provider_id_is_distinct_across_sources_and_identity_kinds():
    ids = [_cards(source, [_job(source, "42")]).cards[0]["attrs"]["data-jst-id"] for source in RENDERERS]
    assert len(set(ids)) == 3
    assert M.job_identity("reed", {"source_job_id": "https://example.test/x"}) != M.job_identity("reed", {"url": "https://example.test/x"})


@pytest.mark.parametrize("source", RENDERERS)
def test_other_bucket_omits_exact_main_identity_without_fuzzy_matching(source):
    main = [_job(source, "42")]
    other = [dict(main[0], title="Changed title"), _job(source, "43", title="Original")]
    adapter = SimpleNamespace(source_id=source, render_cards_fragment=RENDERERS[source])
    html = _render_other_results_fragment(adapter, other, skip=1, nonce="n", main_results=main)
    parsed = _Cards(RENDERERS[source](main, nonce="n") + html)
    assert len(parsed.cards) == 2
    assert len(parsed.ids) == len(set(parsed.ids))
    assert [row["fields"]["source_job_id"] for row in parsed.cards] == ["42", "43"]
    assert "Other results (1)" in html


_NODE_DOM = r'''
const assert=require('assert');
global.window=global;
let main=[], other=null, submissions=[];
const response=fixture.response;
class Element {
 constructor(id=''){this.id=id;this.style={};this.children=[];this.dataset={};this.className='';}
 appendChild(c){this.children.push(c);c.parentElement=this;return c;}
 setAttribute(k,v){this[k]=v;}
 getAttribute(k){return this[k];}
 querySelector(sel){return this.children.find(c=>'.'+c.className===sel)||null;}
 querySelectorAll(sel){return this.children.filter(c=>c.className==='jst-rc');}
 remove(){if(this===other){other=null;return;}main=main.filter(c=>c!==this);if(other)other.children=other.children.filter(c=>c!==this);}
 scrollIntoView(){}
}
function card(row){const a=row.attrs,c=new Element(a.id);c.className=a.class;c.fields=row.fields;
 for(const [k,v] of Object.entries(a)){if(k.startsWith('data-jst-'))c.dataset['jst'+k.slice(8).replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]=v;}
 c.form=new Element(c.dataset.jstForm);c.form.fields=row.fields;
 c.checkbox=new Element('jst-cb-'+c.id);return c;}
function active(){return main.concat(other?other.children:[]);}
const wrap=new Element('jst-more-wrap'),container=new Element('jst-cards-container');
container.querySelectorAll=()=>main.slice();
container.insertBefore=c=>{if(c.parentElement)c.parentElement.children.shift();main.push(c);c.parentElement=container;};
container.parentElement=new Element();
container.parentElement.insertAdjacentHTML=(position,html)=>{assert.equal(position,'afterend');other=new Element('jst-other-results');fixture.fragments[html].forEach(r=>other.appendChild(card(r)));};
const ui={};['jst-bar','jst-bc','jst-bl','jst-bb','jst-next-btn','jst-eval-all-btn','jst-staging-list','jst-overlay','jst-page-info'].forEach(id=>ui[id]=new Element(id));
ui['jst-next-btn']['data-next-url']='/next';
global.document={
 querySelectorAll:()=>active().filter(c=>c.className==='jst-rc'),
 getElementById(id){if(id==='jst-cards-container')return container;if(id==='jst-more-wrap')return wrap;if(id==='jst-other-results')return other;
  const found=active().flatMap(c=>[c,c.form,c.checkbox]).filter(e=>e.id===id);assert(found.length<=1,'duplicate DOM id '+id);return found[0]||ui[id]||null;},
 createElement(){const e=new Element();Object.defineProperty(e,'innerHTML',{set(html){this.children=fixture.fragments[html].map(card);this.children.forEach(c=>c.parentElement=this);}});Object.defineProperty(e,'firstChild',{get(){return this.children[0];}});return e;}
};
global.FormData=class{constructor(f){this.fields=f.fields;}forEach(fn){Object.entries(this.fields).forEach(([k,v])=>fn(v,k));}};
global.alert=()=>{};
global.fetch=(url,opts)=>{if(url==='/next')return Promise.resolve({json:()=>Promise.resolve(response)});
 if(url==='/jobs/batch-evaluate'){submissions.push(JSON.parse(opts.body).jobs);return Promise.resolve({json:()=>Promise.resolve({ok:false,error:'Synthetic stop'})});}
 assert.equal(url,'/jobs/not-interested');return Promise.resolve({json:()=>Promise.resolve({ok:true,count:0})});};
main=fixture.first.map(card);if(!fixture.delayedOther){other=new Element('jst-other-results');fixture.firstOther.forEach(r=>other.appendChild(card(r)));}
'''


@pytest.mark.parametrize("source", RENDERERS)
def test_real_renderers_and_shared_js_replace_page_preserve_correct_payloads(source, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    # Merged multi-keyword first page exceeds take=2; old offset IDs collided
    # between selected row index 2 and the different first job on the next page.
    rows = [_job(source, str(i), f"First {i}") for i in range(5)]
    old_other = _job(source, "50", "Earlier Other")
    repeat = _job(source, "50", "Current repeat", company="Current Co", location="Reading")
    adapter = SimpleNamespace(source_id=source, render_cards_fragment=RENDERERS[source])
    new_main_html = RENDERERS[source]([_job(source, "99", "Different next job"), repeat, dict(repeat)], skip=2, nonce="current-nonce")
    new_other_html = _render_other_results_fragment(adapter, [repeat, _job(source, "60", "New Other")], skip=4, nonce="current-nonce", main_results=[repeat])
    fixture = dict(first=_cards(source, rows, nonce="old-nonce").cards,
                   firstOther=_cards(source, [old_other], skip=5, nonce="old-nonce").cards,
                   fragments={new_main_html: _Cards(new_main_html).cards, new_other_html: _Cards(new_other_html).cards},
                   response=dict(ok=True, cards_html=new_main_html, other_results_html=new_other_html, visible_count=3, has_more=False))
    script = "const fixture=" + json.dumps(fixture) + ";\n" + _NODE_DOM + M.MULTISELECT_JS + r'''
(async()=>{
const oldId=main[2].dataset.jstId,repeatId=other.children[0].dataset.jstId;
jstToggle(oldId);jstToggle(repeatId);
jstLoadMore(ui['jst-next-btn']);await new Promise(setImmediate);
assert.equal(main.length,2);assert.equal(other.children.length,1);
const newId=main[0].dataset.jstId;
assert.notEqual(oldId,newId);assert.equal(main[1].dataset.jstId,repeatId);
assert.equal(_jst_sel.size,2);assert.equal(_jst_jobs[repeatId].title,'Current repeat');
assert.equal(_jst_jobs[repeatId].company,'Current Co');assert.equal(_jst_jobs[repeatId].location,'Reading');
assert.equal(_jst_jobs[repeatId].fields.nonce,'current-nonce');
jstToggle(newId);jstEvaluateAll();await new Promise(setImmediate);
assert.equal(submissions.length,1);assert.equal(submissions[0].length,3);
assert.deepEqual(submissions[0].map(j=>j.source_job_id),['2','50','99']);
assert.deepEqual(submissions[0].map(j=>j.title),['First 2','Current repeat','Different next job']);
assert.deepEqual(submissions[0].map(j=>j.nonce),['old-nonce','current-nonce','current-nonce']);
assert(submissions[0].every(j=>j.source===fixture.first[0].fields.source));
// Deselect then re-register current fields before reselecting the same identity.
jstToggle(repeatId);main[1].fields.title='After reselect';main[1].fields.nonce='reselect-nonce';
main[1].dataset.jstTitle='After reselect';jstRegisterCards(document);jstToggle(repeatId);
jstEvaluateAll();await new Promise(setImmediate);
const selected=submissions[1].find(j=>j.source_job_id==='50');
assert.equal(selected.title,'After reselect');assert.equal(selected.nonce,'reselect-nonce');
assert.equal(_jst_sel.size,3);assert.equal(_jst_jobs[repeatId].title,'After reselect');
console.log('identity pagination assertions passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    path = tmp_path / "shortlist.js"
    path.write_text(script)
    completed = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "identity pagination assertions passed"


def test_shared_js_distinguishes_sources_and_refreshes_stable_url_fallback(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    first = [_cards(source, [_job(source, "7", source.title())], nonce="initial").cards[0]
             for source in RENDERERS]
    fallback = _job("adzuna", None, "URL original", url="https://example.test/fallback")
    first += _cards("adzuna", [fallback], nonce="initial").cards
    current = dict(fallback, source_job_id="   ", title="URL current", company="Current fallback Co")
    html = RENDERERS["adzuna"]([current], skip=20, nonce="fallback-current")
    fixture = dict(first=first, firstOther=[], fragments={html: _Cards(html).cards},
                   response=dict(ok=True, cards_html=html, other_results_html="", visible_count=1, has_more=False))
    script = "const fixture=" + json.dumps(fixture) + ";\n" + _NODE_DOM + M.MULTISELECT_JS + r'''
(async()=>{
const ids=main.map(c=>c.dataset.jstId);assert.equal(new Set(ids).size,4);
ids.forEach(jstToggle);assert.equal(_jst_sel.size,4);
jstLoadMore(ui['jst-next-btn']);await new Promise(setImmediate);
assert.equal(main.length,1);assert.equal(main[0].dataset.jstId,ids[3]);assert.equal(_jst_sel.size,4);
assert.equal(_jst_jobs[ids[3]].title,'URL current');jstEvaluateAll();await new Promise(setImmediate);
assert.equal(submissions[0].length,4);
assert.deepEqual(submissions[0].slice(0,3).map(j=>[j.source,j.source_job_id,j.title]),
 [['reed','7','Reed'],['adzuna','7','Adzuna'],['linkedin','7','Linkedin']]);
const urlJob=submissions[0][3];assert.equal(urlJob.source,'adzuna');
assert.equal(urlJob.url,'https://example.test/fallback');assert.equal(urlJob.title,'URL current');
assert.equal(urlJob.company,'Current fallback Co');assert.equal(urlJob.nonce,'fallback-current');
console.log('cross-source and URL fallback assertions passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    path = tmp_path / "shortlist-mixed.js"
    path.write_text(script)
    completed = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "cross-source and URL fallback assertions passed"


@pytest.mark.parametrize("source", RENDERERS)
@pytest.mark.parametrize("only_other", [False, True])
def test_initial_other_is_registered_after_markup_with_selection_scaffolding(source, only_other, tmp_path, monkeypatch):
    monkeypatch.setattr("src.ui_handlers.get_enabled_sources", lambda: list(RENDERERS))
    main_rows = [] if only_other else [_job(source, "1", "Main job")]
    html = _render_search_jobs_tab(search_values={"_source_id": source}, reed_results=main_rows,
                                   reed_other_results=[_job(source, "2", "Other job")], reed_select_nonce="initial")
    assert html.count(M.MULTISELECT_JS) == 1
    assert html.count('id="jst-bar"') == 1
    assert html.count('id="jst-overlay"') == 1
    marker = html.index('<details id="jst-other-results"')
    registration = 'if(window.jstRegisterCards){jstRegisterCards(document);}'
    assert html.index(M.MULTISELECT_JS) < marker < html.index(registration)
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    fixture = dict(first=_Cards(html[:marker]).cards, firstOther=_Cards(html[marker:]).cards,
                   fragments={}, response={}, delayedOther=True)
    js = next(js for js in re.findall(r"<script>(.*?)</script>", html, re.S) if M.MULTISELECT_JS in js)
    script = "const fixture=" + json.dumps(fixture) + ";\n" + _NODE_DOM + js + r'''
other=new Element('jst-other-results');fixture.firstOther.forEach(r=>other.appendChild(card(r)));
''' + registration + r'''
(async()=>{
const id=other.children[0].dataset.jstId;assert.equal(_jst_jobs[id].title,'Other job');
jstToggle(id);jstEvaluateAll();await new Promise(setImmediate);
assert.equal(submissions[0].length,1);assert.equal(submissions[0][0].source_job_id,'2');
assert.equal(submissions[0][0].title,'Other job');assert.equal(submissions[0][0].nonce,'initial');
console.log('initial Other registration assertions passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    path = tmp_path / "shortlist-initial-other.js"
    path.write_text(script)
    completed = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "initial Other registration assertions passed"
