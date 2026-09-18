"""Shared multi-select + triage JS/HTML for job-source result grids.

Used verbatim by every source (Reed, Adzuna, LinkedIn) so they all render the
same select / staging / hide / pagination behaviour. The loader targets the
``jst-cards-container`` / ``jst-more-wrap`` ids, so any source using these
helpers must give its cards container the id ``jst-cards-container``.

Search-flow UX (2026-07):
- Cards start UNSELECTED. Tick = shortlist for batch evaluation (one meaning).
- Per-card ✕ (injected by JS) = "not interested": persisted server-side via
  POST /jobs/not-interested, removed from the DOM, 10s undo toast.
- "Hide unticked on this page" bulk-hides only the VISIBLE unticked cards.
- "Hidden jobs (N)" overlay lists the store (GET /jobs/not-interested) with
  per-row Unhide (POST /jobs/not-interested/undo).
- "Next page" REPLACES the list (forward-only). Ticked jobs from earlier pages
  stay shortlisted: their form fields are captured before the cards are
  removed, so batch evaluation still works across pages.

``STAGING_OVERLAY`` also carries the hidden-jobs overlay and the undo toast so
existing source renderers emit them without any changes.
"""
from __future__ import annotations

from html import escape

_HIDDEN_OVERLAY = (
    '<div id="jst-hidden-overlay" style="display:none;position:fixed;inset:0;z-index:210;'
    'align-items:center;justify-content:center;">'
    '<div style="position:absolute;inset:0;background:rgba(20,18,12,0.45);'
    'backdrop-filter:blur(3px);" onclick="jstCloseHidden()"></div>'
    '<div style="position:relative;width:540px;max-width:95vw;max-height:85vh;'
    'overflow:hidden;background:var(--surface);border:1px solid var(--line);'
    'border-radius:var(--r-xl);box-shadow:var(--shadow-lg);display:flex;flex-direction:column;">'
    '<div style="padding:20px 20px 16px;border-bottom:1px solid var(--line-soft);'
    'display:flex;align-items:center;justify-content:space-between;">'
    '<div style="font-size:16px;font-weight:800;letter-spacing:-0.02em;">'
    'Hidden jobs (<span id="jst-hidden-count-h">0</span>)</div>'
    '<button onclick="jstCloseHidden()" style="width:30px;height:30px;border-radius:var(--r-md);'
    'border:1px solid var(--line);background:var(--surface);cursor:pointer;'
    'font-size:17px;color:var(--ink-faint);font-family:inherit;">\xd7</button>'
    '</div>'
    '<label style="display:grid;gap:5px;padding:12px 20px 8px;font-size:12px;font-weight:600;color:var(--ink-soft);">'
    'Filter by title or company'
    '<input id="jst-hidden-filter" type="search" oninput="jstFilterHidden(this.value)" '
    'placeholder="Search hidden jobs" autocomplete="off" '
    'style="font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface-2);color:var(--ink);">'
    '</label>'
    '<div id="jst-hidden-filter-count" style="padding:0 20px 6px;font-size:12px;color:var(--ink-faint);"></div>'
    '<div id="jst-hidden-list" style="overflow-y:auto;padding:4px 20px 8px;flex:1;"></div>'
    '<div style="padding:12px 20px 16px;border-top:1px solid var(--line-soft);'
    'font-size:11.5px;color:var(--ink-faint);">'
    'Unhidden jobs reappear in future searches, not on the current page.'
    '</div>'
    '</div>'
    '</div>'
)

_UNDO_TOAST = (
    '<div id="jst-toast" style="display:none;position:fixed;left:50%;transform:translateX(-50%);'
    'bottom:24px;z-index:300;align-items:center;gap:14px;background:var(--surface);'
    'border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:var(--shadow-lg);'
    'padding:12px 18px;font-size:13px;color:var(--ink);">'
    '<span id="jst-toast-msg"></span>'
    '<button onclick="jstUndoHide()" style="border:none;background:none;color:var(--accent);'
    'font-weight:700;font-size:13px;cursor:pointer;font-family:inherit;">Undo</button>'
    '<button onclick="jstToastHide()" aria-label="Dismiss" style="border:none;background:none;'
    'color:var(--ink-faint);font-size:15px;cursor:pointer;font-family:inherit;">\xd7</button>'
    '</div>'
)

STAGING_OVERLAY = (
    '<div id="jst-overlay" style="display:none;position:fixed;inset:0;z-index:200;'
    'align-items:center;justify-content:center;">'
    '<div style="position:absolute;inset:0;background:rgba(20,18,12,0.45);'
    'backdrop-filter:blur(3px);" onclick="jstCloseStaging()"></div>'
    '<div style="position:relative;width:540px;max-width:95vw;max-height:85vh;'
    'overflow:hidden;background:var(--surface);border:1px solid var(--line);'
    'border-radius:var(--r-xl);box-shadow:var(--shadow-lg);display:flex;flex-direction:column;">'
    '<div style="padding:20px 20px 16px;border-bottom:1px solid var(--line-soft);'
    'display:flex;align-items:center;justify-content:space-between;">'
    '<div style="font-size:16px;font-weight:800;letter-spacing:-0.02em;">Review queue</div>'
    '<button onclick="jstCloseStaging()" style="width:30px;height:30px;border-radius:var(--r-md);'
    'border:1px solid var(--line);background:var(--surface);cursor:pointer;'
    'font-size:17px;color:var(--ink-faint);font-family:inherit;">\xd7</button>'
    '</div>'
    '<div id="jst-staging-list" style="overflow-y:auto;padding:4px 20px 8px;flex:1;"></div>'
    '<div style="padding:16px 20px;border-top:1px solid var(--line-soft);'
    'display:flex;gap:10px;justify-content:flex-end;align-items:center;">'
    '<button onclick="jstCloseStaging()" style="padding:9px 18px;border-radius:var(--r-md);'
    'font-size:13.5px;font-weight:600;border:1px solid var(--line);background:var(--surface);'
    'color:var(--ink-soft);cursor:pointer;font-family:inherit;">&#8592; Back</button>'
    '<button id="jst-eval-all-btn" onclick="jstEvaluateAll()" style="padding:10px 20px;'
    'border-radius:var(--r-md);font-size:13.5px;font-weight:700;border:none;'
    'background:var(--accent);color:var(--accent-contrast);cursor:pointer;font-family:inherit;">'
    'Evaluate all jobs</button>'
    '</div>'
    '</div>'
    '</div>'
    + _HIDDEN_OVERLAY
    + _UNDO_TOAST
)

ACTION_BAR = (
    '<div id="jst-bar" style="display:none;position:sticky;bottom:0;left:0;right:0;'
    'padding:14px 0;background:linear-gradient(to top,var(--bg) 60%,transparent);pointer-events:none;">'
    '<div style="background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);'
    'padding:14px 16px;box-shadow:var(--shadow-md);display:flex;align-items:center;gap:16px;pointer-events:auto;">'
    '<div style="display:flex;align-items:center;gap:10px;">'
    '<span id="jst-bc" style="font-family:var(--font-mono);font-size:22px;font-weight:700;color:var(--accent);">0</span>'
    '<div style="font-size:13px;font-weight:600;color:var(--ink-soft);">'
    '<div id="jst-bl">jobs shortlisted</div>'
    '<div style="font-size:11.5px;color:var(--ink-faint);font-weight:400;">Review shortlisted jobs, then evaluate all at once</div>'
    '</div></div>'
    '<div style="flex:1;"></div>'
    '<button onclick="jstClearAll()" style="padding:9px 16px;border-radius:var(--r-md);'
    'font-size:13px;font-weight:600;border:1px solid var(--line);background:var(--surface);'
    'color:var(--ink-soft);cursor:pointer;font-family:inherit;">Clear all</button>'
    '<button id="jst-bb" onclick="jstShowStaging()" style="padding:10px 18px;'
    'border-radius:var(--r-md);font-size:13.5px;font-weight:700;border:none;'
    'background:var(--accent);color:var(--accent-contrast);cursor:pointer;font-family:inherit;">'
    'Review shortlisted &#8594;</button>'
    '</div></div>'
)

MULTISELECT_JS = (
    '(function(){'
    'window._jst_sel=window._jst_sel||new Set();'
    'window._jst_jobs=window._jst_jobs||{};'
    'var _sel=window._jst_sel,_jobs=window._jst_jobs;'
    'function _reg(c){'
    'var id=c.dataset.jstId;if(!id)return;'
    'if(!_jobs[id]){'
    '_jobs[id]={title:c.dataset.jstTitle,company:c.dataset.jstCompany,'
    'salary:c.dataset.jstSalary,location:c.dataset.jstLocation,formId:c.dataset.jstForm,'
    'source:c.dataset.jstSource||"",sjid:c.dataset.jstSjid||""};'
    '}'
    'if(!c.querySelector(".jst-x")){'
    'c.style.position="relative";'
    'var xb=document.createElement("button");'
    'xb.className="jst-x";xb.textContent="\\u00d7";'
    'xb.title="Not interested \\u2014 hide this job from future searches";'
    'xb.setAttribute("aria-label","Not interested");'
    'xb.style.cssText="position:absolute;top:10px;right:10px;width:26px;height:26px;'
    'border-radius:var(--r-md);border:1px solid var(--line);background:var(--surface);'
    'color:var(--ink-faint);cursor:pointer;font-size:15px;line-height:1;'
    'display:inline-flex;align-items:center;justify-content:center;font-family:inherit;";'
    '(function(cid){xb.onclick=function(e){e.stopPropagation();jstHide([cid]);};})(id);'
    'c.appendChild(xb);'
    '}'
    '}'
    'document.querySelectorAll(".jst-rc").forEach(_reg);'
    'function _upd(){'
    'document.querySelectorAll(".jst-rc").forEach(function(c){'
    'var id=c.dataset.jstId,on=_sel.has(id);'
    'c.style.borderColor=on?"var(--accent)":"var(--line)";'
    'c.style.boxShadow=on?"0 0 0 3px var(--accent-soft),var(--shadow-sm)":"var(--shadow-sm)";'
    'var cb=document.getElementById("jst-cb-"+id);if(!cb)return;'
    'cb.style.background=on?"var(--accent)":"var(--surface-2)";'
    'cb.style.borderColor=on?"var(--accent)":"var(--line)";'
    'cb.style.color=on?"white":"transparent";'
    'cb.textContent=on?"✓":"";'
    '});'
    'var n=_sel.size,bar=document.getElementById("jst-bar");'
    'if(!bar)return;'
    'bar.style.display=n>0?"flex":"none";'
    'var off=0;_sel.forEach(function(id){if(!document.getElementById(id))off++;});'
    'var el=document.getElementById("jst-bc");if(el)el.textContent=n;'
    'var bl=document.getElementById("jst-bl");'
    'if(bl)bl.textContent=(n===1?"job shortlisted":"jobs shortlisted")'
    '+(off>0?" \\u00b7 "+off+" from earlier page"+(off===1?"":"s"):"");'
    'var bb=document.getElementById("jst-bb");if(bb)bb.textContent="Review "+n+" shortlisted →";'
    '}'
    'function _setHidCount(v){'
    '["jst-hid-count","jst-hidden-count-h"].forEach(function(eid){'
    'var e=document.getElementById(eid);if(e)e.textContent=v;});'
    '}'
    'window.jstToggle=function(id){'
    '_sel.has(id)?_sel.delete(id):_sel.add(id);_upd();'
    '};'
    'window.jstSelectAll=function(){'
    'Object.keys(_jobs).forEach(function(id){_sel.add(id);});_upd();'
    '};'
    'window.jstClearAll=function(){_sel.clear();_upd();};'
    'window.jstToastHide=function(){'
    'var t=document.getElementById("jst-toast");if(t)t.style.display="none";'
    'window._jst_lastHidden=null;'
    '};'
    'function _toast(msg){'
    'var t=document.getElementById("jst-toast"),m=document.getElementById("jst-toast-msg");'
    'if(!t||!m)return;m.textContent=msg;t.style.display="flex";'
    'clearTimeout(window._jst_toast_t);'
    'window._jst_toast_t=setTimeout(jstToastHide,10000);'
    '}'
    'window.jstHide=function(ids){'
    'var payload=[],items=[];'
    'ids.forEach(function(id){'
    'var c=document.getElementById(id),j=_jobs[id];'
    'if(!c||!j)return;'
    'payload.push({source:j.source,source_job_id:j.sjid,title:j.title||"",company:j.company||""});'
    'items.push({id:id,node:c});'
    '});'
    'if(!payload.length)return;'
    'fetch("/jobs/not-interested",{method:"POST",'
    'headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({jobs:payload})})'
    '.then(function(r){return r.json();})'
    '.then(function(d){'
    'if(!d.ok){alert("Hide failed: "+(d.error||"Unknown"));return;}'
    'items.forEach(function(it){it.node.remove();_sel.delete(it.id);delete _jobs[it.id];});'
    'window._jst_lastHidden={keys:d.keys,items:items};'
    '_upd();_setHidCount(d.total_hidden);'
    '_toast(items.length===1?"1 job hidden":items.length+" jobs hidden");'
    '})'
    '.catch(function(err){alert("Request failed: "+err.message);});'
    '};'
    'window.jstUndoHide=function(){'
    'var lh=window._jst_lastHidden;if(!lh)return;'
    'fetch("/jobs/not-interested/undo",{method:"POST",'
    'headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({keys:lh.keys})})'
    '.then(function(r){return r.json();})'
    '.then(function(d){'
    'if(!d.ok){alert("Undo failed: "+(d.error||"Unknown"));return;}'
    'var container=document.getElementById("jst-cards-container");'
    'var fw=document.getElementById("jst-more-wrap");'
    'lh.items.forEach(function(it){'
    'if(container&&!document.getElementById(it.id))container.insertBefore(it.node,fw);'
    '});'
    'jstToastHide();jstRegisterCards(container);_setHidCount(d.total_hidden);'
    '})'
    '.catch(function(err){alert("Request failed: "+err.message);});'
    '};'
    'window.jstHideUnticked=function(){'
    'var ids=[];'
    'document.querySelectorAll(".jst-rc").forEach(function(c){'
    'var id=c.dataset.jstId;if(id&&!_sel.has(id))ids.push(id);'
    '});'
    'if(!ids.length)return;'
    'jstHide(ids);'
    '};'
    'window.jstFilterHidden=function(rawQuery){'
    'var list=document.getElementById("jst-hidden-list"),count=document.getElementById("jst-hidden-filter-count");'
    'if(!list)return;var query=(rawQuery||"").trim().toLowerCase();'
    'var jobs=window._jst_hidden_jobs||[];var shown=jobs.filter(function(j){'
    'return !query||((j.title||"")+" "+(j.company||"")).toLowerCase().indexOf(query)!==-1;});'
    'if(count)count.textContent=query?(shown.length+" of "+jobs.length+" hidden jobs"):(jobs.length+" hidden jobs");'
    'list.textContent="";'
    'if(!jobs.length){list.textContent="No hidden jobs.";return;}'
    'if(!shown.length){list.textContent="No hidden jobs match this filter.";return;}'
    'shown.forEach(function(j){'
    'var row=document.createElement("div");'
    'row.style.cssText="padding:12px 0;border-bottom:1px solid var(--line-soft);display:flex;gap:12px;align-items:center;";'
    'var info=document.createElement("div");info.style.cssText="flex:1;min-width:0;";'
    'var t=document.createElement("div");t.style.cssText="font-size:13.5px;font-weight:700;letter-spacing:-0.015em;";'
    't.textContent=j.title||"(no title)";info.appendChild(t);'
    'var c=document.createElement("div");c.style.cssText="font-size:12px;color:var(--ink-soft);margin-top:2px;";'
    'c.textContent=(j.company||"")+" \\u00b7 "+(j.source||"")+(j.hidden_at?" \\u00b7 hidden "+j.hidden_at.slice(0,10):"");'
    'info.appendChild(c);row.appendChild(info);'
    'var ub=document.createElement("button");ub.textContent="Unhide";'
    'ub.style.cssText="padding:7px 14px;border-radius:var(--r-md);font-size:12.5px;font-weight:600;border:1px solid var(--line);background:var(--surface);color:var(--ink-soft);cursor:pointer;font-family:inherit;";'
    'ub.onclick=function(){ub.disabled=true;fetch("/jobs/not-interested/undo",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({keys:[j.key]})})'
    '.then(function(r){return r.json();}).then(function(dd){if(!dd.ok){ub.disabled=false;alert("Unhide failed: "+(dd.error||"Unknown"));return;}'
    'window._jst_hidden_jobs=(window._jst_hidden_jobs||[]).filter(function(item){return item.key!==j.key;});'
    '_setHidCount(dd.total_hidden);var input=document.getElementById("jst-hidden-filter");jstFilterHidden(input?input.value:"");'
    '}).catch(function(err){ub.disabled=false;alert("Request failed: "+err.message);});};'
    'row.appendChild(ub);list.appendChild(row);'
    '});'
    '};'
    'window.jstShowHidden=function(){'
    'var ov=document.getElementById("jst-hidden-overlay"),list=document.getElementById("jst-hidden-list"),input=document.getElementById("jst-hidden-filter");'
    'if(!ov||!list)return;ov.style.display="flex";'
    'if(input)input.value="";'
    'list.innerHTML="<div style=\'padding:24px;text-align:center;color:var(--ink-faint);font-size:13px;\'>Loading\\u2026</div>";'
    'fetch("/jobs/not-interested").then(function(r){return r.json();})'
    '.then(function(d){'
    'if(!d.ok){list.textContent="Could not load hidden jobs.";return;}'
    '_setHidCount(d.count);'
    'window._jst_hidden_jobs=d.jobs;jstFilterHidden("");'
    '})'
    '.catch(function(){list.textContent="Could not load hidden jobs.";});'
    '};'
    'window.jstCloseHidden=function(){'
    'var ov=document.getElementById("jst-hidden-overlay");if(ov)ov.style.display="none";'
    '};'
    'window.jstShowStaging=function(){'
    'var list=document.getElementById("jst-staging-list");if(!list)return;'
    'while(list.firstChild)list.removeChild(list.firstChild);'
    'if(_sel.size===0)return;'
    '_sel.forEach(function(id){'
    'var j=_jobs[id];if(!j)return;'
    'var row=document.createElement("div");'
    'row.style.cssText="padding:14px 0;border-bottom:1px solid var(--line-soft);display:flex;align-items:flex-start;gap:12px;";'
    'var info=document.createElement("div");info.style.cssText="flex:1;min-width:0;";'
    'var tEl=document.createElement("div");'
    'tEl.style.cssText="font-size:14.5px;font-weight:700;letter-spacing:-0.015em;";'
    'tEl.textContent=j.title;info.appendChild(tEl);'
    'var cEl=document.createElement("div");'
    'cEl.style.cssText="font-size:12.5px;color:var(--ink-soft);margin-top:2px;";'
    'cEl.textContent=j.company+(j.location?" \xb7 "+j.location:"");info.appendChild(cEl);'
    'if(j.salary){'
    'var sw=document.createElement("div");sw.style.marginTop="7px";'
    'var st=document.createElement("span");'
    'st.style.cssText="font-family:var(--font-mono);font-size:11px;padding:2px 8px;'
    'border-radius:100px;background:var(--surface-sunk);color:var(--ink-soft);border:1px solid var(--line);";'
    'st.textContent=j.salary;sw.appendChild(st);info.appendChild(sw);'
    '}'
    'row.appendChild(info);'
    'var rb=document.createElement("button");'
    'rb.style.cssText="width:30px;height:30px;border-radius:var(--r-md);border:1px solid var(--line);'
    'background:var(--surface);color:var(--ink-faint);cursor:pointer;font-size:18px;'
    'display:inline-flex;align-items:center;justify-content:center;font-family:inherit;";'
    'rb.textContent="\xd7";'
    '(function(cid){rb.onclick=function(e){e.stopPropagation();jstRemoveStaging(cid);};})(id);'
    'row.appendChild(rb);list.appendChild(row);'
    '});'
    'var evalBtn=document.getElementById("jst-eval-all-btn");'
    'if(evalBtn){var n2=_sel.size;evalBtn.textContent="Evaluate all "+n2+" job"+(n2===1?"":"s");}'
    'var ov=document.getElementById("jst-overlay");if(ov)ov.style.display="flex";'
    '};'
    'window.jstCloseStaging=function(){'
    'var ov=document.getElementById("jst-overlay");if(ov)ov.style.display="none";'
    '};'
    'window.jstRemoveStaging=function(id){'
    '_sel.delete(id);_upd();jstShowStaging();if(_sel.size===0)jstCloseStaging();'
    '};'
    'window.jstEvaluate=function(id){'
    'var j=_jobs[id];if(!j||!j.formId)return;'
    'var f=document.getElementById(j.formId);if(f)f.submit();'
    '};'
    'window.jstRegisterCards=function(container){'
    '(container||document).querySelectorAll(".jst-rc").forEach(_reg);_upd();'
    '};'
    'window.jstLoadMore=function(btn){'
    'var url=btn.getAttribute("data-next-url");if(!url)return;'
    'btn.disabled=true;btn.textContent="Loading\\u2026";'
    'fetch(url).then(function(r){return r.json();})'
    '.then(function(d){'
    'if(!d.ok){btn.disabled=false;btn.textContent="Next page \\u2192";alert("Failed: "+(d.error||"Unknown"));return;}'
    'var container=document.getElementById("jst-cards-container");'
    'var moreWrap=document.getElementById("jst-more-wrap");'
    'if(!container){btn.disabled=false;return;}'
    'var oldOther=document.getElementById("jst-other-results");'
    'container.querySelectorAll(".jst-rc").forEach(function(c){'
    'var id=c.dataset.jstId;'
    'if(id&&_sel.has(id)){'
    'var j=_jobs[id];'
    'var f=j&&j.formId?document.getElementById(j.formId):null;'
    'if(j&&f){var fd=new FormData(f),o={};fd.forEach(function(v,k){o[k]=v;});j.fields=o;}'
    '}else if(id){delete _jobs[id];}'
    'c.remove();'
    '});'
    'if(oldOther){oldOther.querySelectorAll(".jst-rc").forEach(function(c){'
    'var id=c.dataset.jstId;if(id&&_sel.has(id)){var j=_jobs[id];var f=j&&j.formId?document.getElementById(j.formId):null;'
    'if(j&&f){var fd=new FormData(f),o={};fd.forEach(function(v,k){o[k]=v;});j.fields=o;}}else if(id){delete _jobs[id];}});oldOther.remove();}'
    'var oldNote=document.getElementById("jst-page-note");if(oldNote)oldNote.remove();'
    'window._jst_page=(window._jst_page||1)+1;'
    'var pi=document.getElementById("jst-page-info");'
    'if(pi)pi.textContent="Page "+window._jst_page'
    '+(d.hidden_count?" \\u00b7 "+d.hidden_count+" hidden":"");'
    'if(d.cards_html){'
    'var tmp=document.createElement("div");'
    'tmp.innerHTML=d.cards_html;'
    'while(tmp.firstChild)container.insertBefore(tmp.firstChild,moreWrap);'
    'jstRegisterCards(container);'
    '}'
    'if(d.other_results_html){container.parentElement.insertAdjacentHTML("afterend",d.other_results_html);jstRegisterCards(document);}'
    'if(!d.visible_count){'
    'var note=document.createElement("div");note.id="jst-page-note";'
    'note.style.cssText="text-align:center;padding:36px 20px;color:var(--ink-faint);font-size:13px;";'
    'note.textContent=d.count?("All "+d.count+" jobs on this page are hidden as not interested."):"No more jobs on this page.";'
    'container.insertBefore(note,moreWrap);'
    '}'
    'var nb=document.getElementById("jst-next-btn");'
    'if(!d.has_more){if(nb)nb.style.display="none";}'
    'else if(nb){nb.setAttribute("data-next-url",d.next_url);nb.disabled=false;nb.textContent="Next page \\u2192";}'
    'if(container.parentElement)container.parentElement.scrollIntoView({behavior:"smooth",block:"start"});'
    '_upd();'
    '})'
    '.catch(function(err){btn.disabled=false;btn.textContent="Next page \\u2192";alert("Request failed: "+err.message);});'
    '};'
    'window.jstEvaluateAll=function(){'
    'if(_sel.size===0)return;'
    'var jobs=[];'
    '_sel.forEach(function(id){'
    'var j=_jobs[id];if(!j)return;'
    'var obj=null;'
    'var f=j.formId?document.getElementById(j.formId):null;'
    'if(f){var fd=new FormData(f);obj={};fd.forEach(function(v,k){obj[k]=v;});}'
    'else if(j.fields){obj=j.fields;}'
    'if(obj)jobs.push(obj);'
    '});'
    'if(!jobs.length){alert("No evaluable jobs found.");return;}'
    'var btn=document.getElementById("jst-eval-all-btn");'
    'var list=document.getElementById("jst-staging-list");'
    'if(btn){btn.disabled=true;btn.textContent="Scoring\\u2026";}'
    'if(list){list.innerHTML="<div style=\'text-align:center;padding:36px 20px;\'>'
    '<div style=\'font-size:14px;font-weight:600;color:var(--ink-soft);\'>Evaluating "+jobs.length+" job"+(jobs.length===1?"":"s")+"...<\\/div>'
    '<div style=\'font-size:12.5px;color:var(--ink-faint);margin-top:6px;\'>Fetching descriptions \xb7 scoring against your profile<\\/div>'
    '<\\/div>";}'
    'fetch("/jobs/batch-evaluate",{'
    'method:"POST",'
    'headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({jobs:jobs})'
    '}).then(function(r){return r.json();})'
    '.then(function(d){'
    'if(!d.ok){alert("Evaluation failed: "+(d.error||"Unknown error"));'
    'if(btn){btn.disabled=false;btn.textContent="Evaluate all";}return;}'
    'var ids=d.jobs.map(function(j){return j.job_id;}).join(",");'
    'if(!ids){var em=(d.errors&&d.errors.length)?("\\n\\nReason: "+d.errors[0].error):"";'
    'alert("No jobs were successfully evaluated."+em);'
    'if(btn){btn.disabled=false;btn.textContent="Evaluate all";}return;}'
    'window.location="/review-queue?ids="+encodeURIComponent(ids);'
    '})'
    '.catch(function(err){alert("Request failed: "+err.message);'
    'if(btn){btn.disabled=false;btn.textContent="Evaluate all";}});'
    '};'
    'fetch("/jobs/not-interested").then(function(r){return r.json();})'
    '.then(function(d){if(d&&d.ok)_setHidCount(d.count);}).catch(function(){});'
    '_upd();'
    '})();'
)


def multiselect_script() -> str:
    """Return the ``<script>`` block wiring up select / staging / hide / paging."""
    return f"<script>/* jst multi-select */{MULTISELECT_JS}</script>"


def select_shell(card_id: str, *, selectable: bool, url: str | None = None) -> tuple[str, str, str, str]:
    """Shared enabled/disabled card chrome for every job source.

    A card is only tickable (``jst-rc`` → registered by the multi-select JS) when
    ``selectable`` is True. When False the card is rendered visibly disabled with
    a note, so a job that cannot actually be evaluated can never be shortlisted or
    batch-evaluated (which would otherwise fail with a cryptic validation error).

    Returns ``(root_class, root_extra_attrs, checkbox_html, disabled_note_html)``
    which the source drops into its existing card markup unchanged.
    """
    if selectable:
        root_class = "jst-rc"
        root_extra = (
            f' onclick="jstToggle(\'{escape(card_id)}\')"'
            ' style="background:var(--surface);border:1.5px solid var(--line);border-radius:var(--r-lg);'
            'padding:16px;margin-bottom:10px;cursor:pointer;'
            'transition:border-color .15s,box-shadow .15s;box-shadow:var(--shadow-sm);"'
        )
        checkbox_html = (
            f'<span id="jst-cb-{escape(card_id)}" style="flex-shrink:0;margin-top:2px;width:20px;height:20px;'
            'border-radius:6px;display:inline-flex;align-items:center;justify-content:center;'
            'font-size:13px;font-weight:900;background:var(--surface-2);'
            'border:1.5px solid var(--line);transition:all .14s;pointer-events:none;"></span>'
        )
        return root_class, root_extra, checkbox_html, ""

    root_class = "jst-rc-disabled"
    root_extra = (
        ' title="No description captured for this result — cannot evaluate here."'
        ' style="background:var(--surface);border:1.5px dashed var(--line);border-radius:var(--r-lg);'
        'padding:16px;margin-bottom:10px;opacity:0.6;box-shadow:var(--shadow-sm);"'
    )
    checkbox_html = (
        '<span aria-hidden="true" title="Cannot be shortlisted" style="flex-shrink:0;margin-top:2px;'
        'width:20px;height:20px;border-radius:6px;display:inline-flex;align-items:center;'
        'justify-content:center;font-size:13px;font-weight:900;background:var(--surface-sunk);'
        'border:1.5px dashed var(--line);color:var(--ink-faint);pointer-events:none;">∅</span>'
    )
    _safe_url = url if (url or "").startswith(("https://", "http://")) else ""
    link = (
        f' &middot; <a href="{escape(_safe_url)}" target="_blank" rel="noopener noreferrer"'
        ' style="color:var(--accent);" onclick="event.stopPropagation();">Open original</a>'
        if _safe_url else ""
    )
    disabled_note_html = (
        '<div style="font-size:11.5px;color:var(--ink-faint);margin-top:8px;'
        'padding:6px 10px;border:1px dashed var(--line);border-radius:var(--r-md);">'
        "No description captured for this result, so it can't be evaluated here."
        f" Open the original posting to review it manually.{link}</div>"
    )
    return root_class, root_extra, checkbox_html, disabled_note_html


def hide_attrs(result: dict) -> str:
    """Card data-attributes carrying the identity fields the hide endpoint
    needs (source + source job id; title/company are already card attrs)."""
    return (
        f' data-jst-source="{escape(str(result.get("source") or ""))}"'
        f' data-jst-sjid="{escape(str(result.get("source_job_id") or ""))}"'
    )


def more_button_html(more_url: str | None) -> str:
    """Render the results footer: page indicator, "Hide unticked on this page",
    "Hidden jobs (N)", and — when there is a next page — the "Next page" button.

    Kept under the historical name so existing source renderers need no change;
    unlike the old version it always renders (the hide/hidden controls are
    useful even on the last page)."""
    next_btn = ""
    if more_url:
        next_btn = (
            f'<button id="jst-next-btn" data-next-url="{escape(more_url)}" onclick="jstLoadMore(this)"'
            f' style="padding:10px 22px;border-radius:var(--r-md);font-size:13.5px;font-weight:700;'
            f'border:1px solid var(--line);background:var(--surface);color:var(--ink);'
            f'cursor:pointer;font-family:inherit;">Next page &#8594;</button>'
        )
    return (
        '<div id="jst-more-wrap" style="display:flex;align-items:center;gap:10px;'
        'flex-wrap:wrap;padding:18px 0 6px;">'
        '<span id="jst-page-info" style="font-size:12px;color:var(--ink-faint);">Page 1</span>'
        '<div style="flex:1;"></div>'
        '<button onclick="jstHideUnticked()" title="Hide every job on this page you have not ticked"'
        ' style="padding:9px 16px;border-radius:var(--r-md);font-size:13px;font-weight:600;'
        'border:1px solid var(--line);background:var(--surface);color:var(--ink-soft);'
        'cursor:pointer;font-family:inherit;">Hide unticked on this page</button>'
        '<button onclick="jstShowHidden()"'
        ' style="padding:9px 16px;border-radius:var(--r-md);font-size:13px;font-weight:600;'
        'border:1px solid var(--line);background:var(--surface);color:var(--ink-soft);'
        'cursor:pointer;font-family:inherit;">Hidden jobs (<span id="jst-hid-count">0</span>)</button>'
        + next_btn +
        '</div>'
    )
