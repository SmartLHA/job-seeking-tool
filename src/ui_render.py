"""HTML rendering layer — pure functions: data in, string out.

LT-1 Step 4. Imports only :mod:`src.ui_utils`, :mod:`src.ui_state` and stdlib.
No domain modules, no network, no file I/O. Complex page renderers consume
view-model dataclasses built by the handler layer (``_build_*_vm`` in
``job_hunt_ui``). Source-specific rendering lives in ``src/job_sources``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.ui_utils import escape, format_salary_range
from src.ui_state import _HOME_TABS, _PAGE_UPDATED


def _normalize_home_tab(tab: str | None) -> str:
    """Return a safe home tab, defaulting to the Reed-first search shell."""
    if tab in _HOME_TABS:
        return tab
    return "search"


def render_home_page(
    *,
    profile_name: str,
    profile_target_roles: list[str],
    history: list[dict[str, Any]],
    values: dict[str, str],
    error: str | None,
    search_tab_html: str = "",
    tab: str = "search",
    profile_tab_html: str = "",
    evaluate_notice: str | None = None,
    model_label: str = "",
) -> str:
    tab = _normalize_home_tab(tab)
    error_html = f'<div class="panel error">{escape(error)}</div>' if error else ""
    history_html = render_history_table(history)
    add_job_form_html = _render_add_job_tab(values)
    evaluate_notice_html = f'<div class="panel flash success">{escape(evaluate_notice)}</div>' if evaluate_notice else ""
    profile_name_esc = escape(profile_name or "")
    target_roles = escape(", ".join(profile_target_roles) or "—")
    sidebar = _render_sidebar(tab)
    body = f"""
    <div class="app-shell">
      {sidebar}
      <main class="main-content">
        <div class="content-inner">
          <div class="panel subtle" style="display:flex;align-items:center;gap:16px;padding:14px 18px;margin-bottom:var(--gap);">
            <div style="flex:1;min-width:0;">
              <div style="font-size:13px;font-weight:700;color:var(--ink);">{profile_name_esc}</div>
              <div style="font-size:12px;color:var(--ink-faint);margin-top:2px;">{target_roles}</div>
            </div>
          </div>
          {error_html}
          <div id="tab-search" class="tab-content"{' hidden' if tab != 'search' else ''}>
            {search_tab_html}
          </div>
          <div id="tab-evaluate" class="tab-content"{' hidden' if tab != 'evaluate' else ''}>
            {evaluate_notice_html}
            <section class="panel">
              <h2>Evaluate a job</h2>
              <p>Fill in the fields below to save and score a job against your profile. <strong>Reviewed description</strong> is the version used for scoring.</p>
              <form method="post" action="/evaluate" id="job-form">
                {render_input_form(values)}
                <div class="actions"><button type="submit">Evaluate and save</button></div>
              </form>
            </section>
          </div>
          <div id="tab-history" class="tab-content"{' hidden' if tab != 'history' else ''}>
            <section class="panel">
              <h2>Evaluated jobs</h2>
              {history_html}
            </section>
          </div>
          <div id="tab-add_job" class="tab-content"{' hidden' if tab != 'add_job' else ''}>
            {add_job_form_html}
          </div>
          <div id="tab-profile" class="tab-content"{' hidden' if tab != 'profile' else ''}>
            {profile_tab_html}
          </div>
        </div>
      </main>
    </div>
    """
    return render_page("Job Seeking Tool", body, model_label=model_label)


@dataclass(frozen=True)
class ReviewQueueViewModel:
    """View model for render_review_queue_page."""
    jobs: list[dict[str, Any]]
    active_id: str
    ids_csv: str
    model_label: str = ""


def render_review_queue_page(vm: "ReviewQueueViewModel") -> str:
    """Two-panel Review Queue: left sidebar job list, right iframe job detail."""

    jobs_info = vm.jobs
    active_id = vm.active_id
    n = len(jobs_info)

    def _chip(d: str) -> str:
        cfg = {
            "apply":  ("var(--apply)",  "var(--apply-bg)",  "var(--apply-line)",  "✓", "Apply"),
            "review": ("var(--review)", "var(--review-bg)", "var(--review-line)", "⚑", "Review"),
            "skip":   ("var(--skip)",   "var(--skip-bg)",   "var(--skip-line)",   "−", "Skip"),
        }.get(d, ("var(--ink-faint)", "var(--surface-sunk)", "var(--line)", "?", d.title()))
        c, bg, line, icon, label = cfg
        return (
            f'<span style="display:inline-flex;align-items:center;gap:5px;padding:3px 9px 3px 6px;'
            f'border-radius:100px;font-weight:700;font-size:11px;text-transform:uppercase;'
            f'color:{c};background:{bg};border:1px solid {line};">'
            f'<span style="display:inline-flex;align-items:center;justify-content:center;'
            f'width:14px;height:14px;border-radius:100px;background:{c};color:var(--surface-2);font-size:9px;">{icon}</span>'
            f'{escape(label)}</span>'
        )

    def _score_color(score: float | None) -> str:
        if score is None:
            return "var(--ink-faint)"
        return "var(--apply)" if score >= 75 else ("var(--review)" if score >= 50 else "var(--skip)")

    queue_rows = []
    for j in jobs_info:
        jid = escape(j["job_id"])
        active = j["job_id"] == active_id
        score = j["score"]
        score_str = str(int(score)) if score is not None else "–"
        sc = _score_color(score)
        border_color = "var(--accent)" if active else "var(--line)"
        bg_color = "var(--surface-2)" if active else "transparent"
        shadow = "var(--shadow-sm)" if active else "none"
        chip_html = _chip(j["decision"])
        title_esc = escape(j["title"])
        company_esc = escape(j["company"])
        src_esc = escape((j.get("source") or "").upper()[:8])
        src_badge = (
            f'<span style="font-family:var(--font-mono);font-size:10px;font-weight:700;padding:2px 7px;'
            f'border-radius:100px;background:var(--surface-sunk);color:var(--ink-faint);'
            f'border:1px solid var(--line);">{src_esc}</span>'
        )
        queue_rows.append(
            f'<button onclick="rqSwitch({chr(39)}{jid}{chr(39)})" '
            f'id="rq-row-{jid}" '
            f'style="text-align:left;padding:12px 13px;border-radius:var(--r-md);width:100%;'
            f'min-width:0;overflow:hidden;'
            f'border:1px solid {border_color};background:{bg_color};box-shadow:{shadow};'
            f'transition:all .15s;cursor:pointer;font-family:inherit;">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:7px;">'
            f'<span style="font-family:var(--font-mono);font-size:18px;font-weight:700;'
            f'color:{sc};line-height:1;">{score_str}</span>'
            f'{chip_html}'
            f'</div>'
            f'<div style="font-size:13.5px;font-weight:600;letter-spacing:-0.01em;line-height:1.3;'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{title_esc}</div>'
            f'<div style="font-size:12px;color:var(--ink-faint);margin-top:2px;'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{company_esc}</div>'
            f'<div style="display:flex;align-items:center;gap:6px;margin-top:8px;">{src_badge}</div>'
            f'</button>'
        )

    rows_html = "\n".join(queue_rows)
    active_id_esc = escape(active_id)
    n_str = str(n)

    # JS: switch active job by updating iframe src and sidebar highlight
    rq_js = (
        '<script>(function(){'
        'window.rqSwitch=function(jobId){'
        'var iframe=document.getElementById("rq-iframe");'
        'if(iframe)iframe.src="/job/"+encodeURIComponent(jobId)+"?embed=1";'
        'document.querySelectorAll("[id^=\\"rq-row-\\"]").forEach(function(el){'
        'var sel=el.id==="rq-row-"+jobId;'
        'el.style.borderColor=sel?"var(--accent)":"var(--line)";'
        'el.style.background=sel?"var(--surface-2)":"transparent";'
        'el.style.boxShadow=sel?"var(--shadow-sm)":"none";'
        '});'
        '};'
        '})();</script>'
    )

    body = f"""
    <div style="display:flex;flex-direction:column;height:100vh;overflow:hidden;">
      <div style="flex-shrink:0;display:flex;align-items:center;gap:13px;padding:12px 20px;
                  border-bottom:1px solid var(--line);background:var(--surface);z-index:10;">
        <a href="/?tab=search"
           style="display:inline-flex;align-items:center;gap:7px;padding:8px 14px;
                  border-radius:var(--r-md);border:1px solid var(--line);background:var(--surface-2);
                  color:var(--ink);font-size:13px;font-weight:600;text-decoration:none;
                  box-shadow:var(--shadow-sm);">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M19 12H5M11 6l-6 6 6 6"/>
          </svg>
          New search
        </a>
        <div style="width:1px;height:24px;background:var(--line);"></div>
        <div>
          <span style="font-size:15px;font-weight:800;letter-spacing:-0.02em;">Review queue</span>
          <span style="font-family:var(--font-mono);font-size:12px;font-weight:700;
                       margin-left:8px;color:var(--ink-faint);">{n_str} jobs</span>
        </div>
        <div style="flex:1;"></div>
        <span style="font-size:11.5px;color:var(--ink-faint);">Sorted by fit score &#xb7; click a job to view</span>
      </div>
      <div style="flex:1;display:flex;overflow:hidden;">
        <div style="width:300px;flex-shrink:0;border-right:1px solid var(--line);
                    background:var(--surface);display:flex;flex-direction:column;overflow:hidden;">
          <div style="padding:14px 14px 6px;">
            <div style="font-size:10.5px;font-weight:700;letter-spacing:0.07em;
                        text-transform:uppercase;color:var(--ink-faint);">Jobs &#xb7; fit score</div>
          </div>
          <div style="flex:1;overflow-y:auto;padding:0 10px 14px;display:flex;flex-direction:column;gap:6px;">
            {rows_html}
          </div>
        </div>
        <iframe id="rq-iframe" src="/job/{active_id_esc}?embed=1"
                style="flex:1;border:none;height:100%;background:var(--bg);"
                title="Job detail"></iframe>
      </div>
    </div>
    {rq_js}
    """
    return render_page(f"Review queue — {n_str} jobs", body, model_label=vm.model_label)


def _render_profile_tab_section(current_tab: str) -> str:
    """Return HTML for the profile tab content (lazy: placeholder until GET /profile is loaded)."""
    if current_tab == "profile":
        # Content is served via GET /profile endpoint directly
        return "<section class=\"panel\"><p>Loading profile…</p></section>"
    return ""


def _render_add_job_tab(values: dict[str, str]) -> str:
    return f"""
    <section class="panel">
      <h2>Add a new job</h2>
      <p>Paste a job advert or enter a posting URL to prefill the form automatically.</p>
      <div id="add-job-input-step">
        <div class="tab-row" role="tablist" aria-label="Job input method">
          <button type="button" class="tab-button active" data-add-job-tab="paste">Paste Text</button>
          <button type="button" class="tab-button" data-add-job-tab="url">Job URL</button>
        </div>
        <div class="tab-panel active" data-add-job-panel="paste">
          <label><span>Paste job text</span><textarea id="add-job-text" placeholder="Paste the raw job advert text here"></textarea></label>
          <div class="actions"><button type="button" id="add-job-parse-btn">Parse &amp; Preview</button></div>
        </div>
        <div class="tab-panel" data-add-job-panel="url" hidden>
          <label><span>Job posting URL</span><input id="add-job-url" type="url" placeholder="https://example.com/job"></label>
          <div class="actions"><button type="button" id="add-job-parse-url-btn">Parse &amp; Preview</button></div>
        </div>
        <p id="add-job-status" class="prefill-status" aria-live="polite"></p>
      </div>
      <div id="add-job-review-step" hidden>
        <hr style="margin: 20px 0; border: none; border-top: 1px solid #e2e8f0;">
        <h3>Review and edit</h3>
        <p>Review the prefilled fields below, then click <strong>Evaluate</strong> to save and evaluate the job.</p>
        <form method="post" action="/job-submit" id="add-job-form">
          {_render_add_job_form_fields(values)}
          <div class="actions">
            <button type="button" id="add-job-back-btn">← Back</button>
            <button type="submit" id="add-job-submit-btn">Evaluate →</button>
          </div>
        </form>
      </div>
    </section>
    <script>
    (function () {{
      // --- Inner tab switching (Paste / URL within Add Job input step) ---
        'var cvTextarea = document.querySelector("textarea[name=\'master_cv_text']");'
        tabBtn.addEventListener('click', function() {{
          var name = tabBtn.dataset.addJobTab;
          document.querySelectorAll('[data-add-job-tab]').forEach(function(b) {{ b.classList.toggle('active', b.dataset.addJobTab === name); }});
          document.querySelectorAll('[data-add-job-panel]').forEach(function(p) {{
            var show = p.dataset.addJobPanel === name;
            p.classList.toggle('active', show);
            p.hidden = !show;
          }});
        }});
      }});

      var inputStep = document.getElementById('add-job-input-step');
      var reviewStep = document.getElementById('add-job-review-step');
      var status = document.getElementById('add-job-status');
      var form = document.getElementById('add-job-form');
      var backBtn = document.getElementById('add-job-back-btn');

      function setStatus(msg, isError) {{
        if (!status) return;
        status.textContent = msg;
        status.style.color = isError ? '#b91c1c' : '#475569';
      }}

      function showReviewStep() {{
        if (inputStep) inputStep.hidden = true;
        if (reviewStep) reviewStep.hidden = false;
      }}

      function showInputStep() {{
        if (reviewStep) reviewStep.hidden = true;
        if (inputStep) inputStep.hidden = false;
        setStatus('');
      }}

      async function parseAndPreview(mode) {{
        var payload = new URLSearchParams();
        payload.set('prefill_mode', mode);
        if (mode === 'paste') payload.set('job_text', document.getElementById('add-job-text') && document.getElementById('add-job-text').value || '');
        if (mode === 'url') payload.set('job_url', document.getElementById('add-job-url') && document.getElementById('add-job-url').value || '');
        setStatus('Parsing...');
        try {{
          var response = await fetch('/prefill', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' }},
            body: payload.toString()
          }});
          var data = await response.json();
          if (!response.ok || !data.ok) throw new Error(data.error || 'Parse failed');
          // Fill form fields and update badges
          var filledValues = data.values || {{}};
          Object.entries(filledValues).forEach(function(entry) {{
            var name = entry[0];
            var value = entry[1] || '';
            var field = form && form.elements.namedItem(name);
            if (!field) return;
            if (field.tagName === 'TEXTAREA' || field.tagName === 'INPUT') {{
              field.value = value;
            }}
          }});
          // Update field-review badges
          document.querySelectorAll('.field-badge').forEach(function(badge) {{
            var fieldName = badge.dataset.badgeFor;
            var rawValue = filledValues[fieldName];
            var isEmpty = rawValue === null || rawValue === undefined || rawValue === '' || rawValue === 'unknown';
            badge.hidden = false;
            badge.querySelector('.badge-autofilled').hidden = isEmpty;
            badge.querySelector('.badge-notfound').hidden = !isEmpty;
          }});
          setStatus('Prefilled. Review the form below, then click Evaluate.');
          showReviewStep();
        }} catch (err) {{
          setStatus(err.message || 'Parse failed', true);
        }}
      }}

      document.getElementById('add-job-parse-btn').addEventListener('click', function() {{ parseAndPreview('paste'); }});
      document.getElementById('add-job-parse-url-btn').addEventListener('click', function() {{ parseAndPreview('url'); }});
      backBtn && backBtn.addEventListener('click', showInputStep);
    }})();
    </script>
    """


def _render_add_job_form_fields(values: dict[str, str]) -> str:
    """Render all form fields for the Add Job form (hidden inputs + visible fields).

    Fields that came from the parser show a badge:
    - "Auto-filled" (green) when value is non-empty
    - "Not found" (amber) when value is empty/None
    """

    # Fields that can be auto-filled by the parser (badge applies after prefill)
    PARSER_FIELDS = {
        "job_title", "company", "location", "work_mode", "employment_type",
        "required_years_experience", "nice_to_have_years_experience",
        "domain", "salary_min_gbp", "salary_max_gbp",
        "required_skills", "preferred_skills", "notes",
    }

    def _badge(name: str) -> str:
        """Return an inline badge span for parser-filled fields (hidden by default; JS reveals)."""
        if name not in PARSER_FIELDS:
            return ""
        return (
            f' <span class="field-badge" data-badge-for="{escape(name)}" hidden>'
            f'<span class="badge-autofilled" hidden>Auto-filled</span>'
            f'<span class="badge-notfound" hidden>Not found</span>'
            f'</span>'
        )

    def field(name: str, label: str, *, textarea: bool = False, placeholder: str = "") -> str:
        value = escape(values.get(name, ""))
        badge = _badge(name)
        label_span = f'<span>{escape(label)}{badge}</span>'
        if textarea:
            return f'<label>{label_span}<textarea name="{escape(name)}" placeholder="{escape(placeholder)}">{value}</textarea></label>'
        return f'<label>{label_span}<input name="{escape(name)}" value="{value}" placeholder="{escape(placeholder)}"></label>'

    return f"""
      <div class="grid two-col">
        {field('job_id', 'Job id (leave blank to auto-generate)')}
        {field('input_method', 'Input method', placeholder='url or copied_text')}
        {field('job_url', 'Job URL')}
        {field('source_type', 'Saved source type', placeholder='url or copied_text')}
        {field('source_ref', 'Source reference (e.g. URL)')}
        {field('job_title', 'Title')}
        {field('company', 'Company')}
        {field('location', 'Location')}
        {field('work_mode', 'Work mode')}
        {field('employment_type', 'Employment type')}
        {field('required_years_experience', 'Required years experience')}
        {field('nice_to_have_years_experience', 'Nice-to-have years experience')}
        {field('domain', 'Domain')}
        {field('salary_min_gbp', 'Salary min GBP')}
        {field('salary_max_gbp', 'Salary max GBP')}
      </div>
      <div class="grid two-col">
        {field('copied_text', 'Original pasted/context text (reference only)', textarea=True)}
        {field('description_raw', 'Reviewed description used for scoring', textarea=True, placeholder='Cleaned/confirmed description for evaluation')}
      </div>
      <div class="grid two-col">
        {field('required_skills', 'Required skills (comma or newline separated)', textarea=True)}
        {field('preferred_skills', 'Preferred skills (comma or newline separated)', textarea=True)}
      </div>
      {field('notes', 'Notes', textarea=True)}
    """


def render_input_form(values: dict[str, str]) -> str:
    def field(name: str, label: str, *, textarea: bool = False, placeholder: str = "") -> str:
        value = escape(values.get(name, ""))
        if textarea:
            return f'<label><span>{escape(label)}</span><textarea name="{escape(name)}" placeholder="{escape(placeholder)}">{value}</textarea></label>'
        return f'<label><span>{escape(label)}</span><input name="{escape(name)}" value="{value}" placeholder="{escape(placeholder)}"></label>'

    source_snapshot_hidden = f'<input type="hidden" name="source_snapshot_json" value="{escape(values.get("source_snapshot_json", ""))}">' if values.get("source_snapshot_json") else ""
    # Daily Digest D2: carry the stable provider id so the manual flow persists it
    # (dedup key on rebuild). Display-only source_ref/url are separate fields above.
    source_job_id_hidden = f'<input type="hidden" name="source_job_id" value="{escape(values.get("source_job_id", ""))}">' if values.get("source_job_id") else ""
    return f"""
      {source_snapshot_hidden}
      {source_job_id_hidden}
      <section class="panel subtle" id="prefill-panel">
        <h3>Quick prefill</h3>
        <div class="tab-row" role="tablist" aria-label="Prefill method tabs">
          <button type="button" class="tab-button active" data-prefill-tab="paste">Paste</button>
          <button type="button" class="tab-button" data-prefill-tab="url">URL</button>
        </div>
        <div class="tab-panel active" data-prefill-panel="paste">
          <label><span>Paste job text</span><textarea id="prefill-job-text" placeholder="Paste the raw job advert here"></textarea></label>
          <div class="actions"><button type="button" id="prefill-paste-btn">Prefill from paste</button></div>
        </div>
        <div class="tab-panel" data-prefill-panel="url" hidden>
          <label><span>Job posting URL</span><input id="prefill-job-url" type="url" placeholder="https://example.com/job"></label>
          <div class="actions"><button type="button" id="prefill-url-btn">Prefill from URL</button></div>
        </div>
        <p id="prefill-status" class="prefill-status" aria-live="polite"></p>
      </section>
      <div class="grid two-col">
        {field('job_id', 'Job id')}
        {field('input_method', 'Input method used to enter this job', placeholder='url or copied_text')}
        {field('job_url', 'Job URL')}
        {field('source_type', 'Saved source type for this reviewed job', placeholder='url or copied_text')}
        {field('source_ref', 'Source reference (for example URL or note id)')}
        {field('job_title', 'Title')}
        {field('company', 'Company')}
        {field('location', 'Location')}
        {field('work_mode', 'Work mode')}
        {field('employment_type', 'Employment type')}
        {field('required_years_experience', 'Required years experience')}
        {field('nice_to_have_years_experience', 'Nice-to-have years experience')}
        {field('domain', 'Domain')}
        {field('salary_min_gbp', 'Salary min GBP')}
        {field('salary_max_gbp', 'Salary max GBP')}
      </div>
      <div class="grid two-col">
        {field('copied_text', 'Original pasted/context text (reference only)', textarea=True)}
        {field('description_raw', 'Reviewed description used for scoring', textarea=True, placeholder='Cleaned/confirmed description for evaluation')}
      </div>
      <div class="grid two-col">
        {field('required_skills', 'Required skills (comma or newline separated)', textarea=True)}
        {field('preferred_skills', 'Preferred skills (comma or newline separated)', textarea=True)}
      </div>
      {field('notes', 'Notes', textarea=True)}
    """


def render_history_table(history: list[dict[str, Any]]) -> str:
    if not history:
        return "<p>No evaluated jobs saved yet.</p>"

    rows = []
    for item in history:
        rows.append(
            "<tr>"
            f"<td><a href=\"/job?job_id={escape(item['job_id'])}\">{escape(item['job_id'])}</a></td>"
            f"<td>{escape(item['job_title'])}</td>"
            f"<td>{escape(item['company'])}</td>"
            f"<td>{escape(item.get('evaluated_at') or '—')}</td>"
            f"<td>{escape(item['decision'])}</td>"
            f"<td>{item['match_score']:.1f}</td>"
            f"<td>{escape(item['confidence'])}</td>"
            f"<td>{escape(item['outcome_status'] or '—')}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>Job id</th><th>Title</th><th>Company</th><th>Evaluated</th><th>Decision</th><th>Score</th><th>Confidence</th><th>Outcome</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


@dataclass(frozen=True)
class JobPageViewModel:
    """View model for render_job_page — flattened, render-ready primitives."""
    job_id: str
    source_type: str | None
    source_ref: str | None
    url: str | None
    job_title: str
    company: str
    location: str | None
    work_mode: str | None
    employment_type: str | None
    required_years_experience: object | None
    domain: str | None
    salary_min_gbp: object | None
    salary_max_gbp: object | None
    source_quality_score: object | None
    description_raw: str | None
    required_skills: list[str]
    preferred_skills: list[str]
    has_analysis: bool
    match_score: object | None
    ats_score: object | None
    keyword_match_rate: object | None
    keywords_required_matched: list[str]
    keywords_required_missing: list[str]
    keywords_preferred_matched: list[str]
    keywords_preferred_missing: list[str]
    keywords_overused: list[str]
    keyword_match_baseline_rate: object | None
    keyword_match_source: str
    confidence: object | None
    decision: str | None
    decision_reason: str | None
    user_decision: str | None
    effective_decision: str
    score_breakdown_rows: list[tuple]
    blockers: list[str]
    strengths: list[str]
    risk_items: list[str]
    missing_required_skills: list[str]
    missing_preferred_skills: list[str]
    has_outcome: bool
    outcome_status: str | None
    outcome_notes: str | None
    outcome_updated_at: object | None
    outcome_status_options: list[str]
    qualitative_assessment: dict | None
    qualitative_index: dict | None
    qualitative_grade: dict | None
    flash: str | None
    flash_kind: str
    embed: bool
    model_label: str


# F1 v2 — keyword-match panel as a standalone, full-wrapper renderer. Used by BOTH
# first render (render_job_page) and the AJAX re-check handler, so the matched/missing
# lists are guaranteed identical before and after refresh (H1). The handler splats
# `_keyword_match_vm_fields(reviewed_job, updated)` straight into this function.
def render_keyword_match_panel(
    *,
    job_id: str,
    keyword_match_rate: object | None,
    keywords_required_matched: list[str],
    keywords_required_missing: list[str],
    keywords_preferred_matched: list[str],
    keywords_preferred_missing: list[str],
    keywords_overused: list[str],
    keyword_match_baseline_rate: object | None,
    keyword_match_source: str,
) -> str:
    """Return the ATS keyword-match card wrapped in ``<div id="kw-panel-body">``."""
    rate = keyword_match_rate
    baseline = keyword_match_baseline_rate
    source = keyword_match_source

    def _label(text: str) -> str:
        return (
            '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">'
            f'<div style="font-size:11.5px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:var(--ink-faint);">{text}</div>'
            '</div>'
        )

    def _chips(items, present):
        if not items:
            return '<span style="font-size:12px;color:var(--ink-faint);">none</span>'
        if present:
            css = "background:var(--accent-soft);color:var(--accent);"
        else:
            css = "background:var(--skip-bg);color:var(--skip);border:1px solid var(--skip-line);"
        return "".join(
            '<span style="display:inline-block;padding:3px 10px;border-radius:100px;'
            f'font-size:12px;font-weight:600;margin:2px 4px 2px 0;{css}">{escape(c)}</span>'
            for c in items
        )

    kw_rate_str = f"{rate}%" if rate is not None else "N/A"

    # Delta / no-baseline state (only meaningful once a tailored re-check has run).
    delta_html = ""
    if source == "tailored" and rate is not None:
        if baseline is not None:
            color = "var(--apply)" if rate > baseline else "var(--ink-soft)"
            delta_html = (
                f'<div style="margin:2px 0 12px;font-size:13px;font-weight:600;color:{color};">'
                f'was {baseline}% &rarr; now {rate}% (tailored CV)</div>'
            )
        else:
            delta_html = (
                '<div style="margin:2px 0 12px;font-size:13px;font-weight:600;color:var(--ink-soft);">'
                f'now {rate}% (tailored CV)</div>'
            )

    if rate is not None:
        kw_warn = ""
        if keywords_overused:
            kw_warn = (
                '<div style="margin-top:12px;font-size:12.5px;color:var(--skip);background:var(--skip-bg);'
                'border:1px solid var(--skip-line);border-radius:var(--r-md);padding:10px 12px;">'
                + escape("Some keywords repeat a lot (" + ", ".join(keywords_overused) + "). "
                         "ATS flag stuffing (white text, keyword banks, repeating a phrase >3-4 times). "
                         "Weave missing keywords into real achievements instead.")
                + '</div>'
            )
        inner = (
            _label("ATS keyword match — " + kw_rate_str)
            + delta_html
            + '<div style="font-size:11px;color:var(--ink-faint);margin:2px 0 4px;font-weight:600;">Required</div>'
            + _chips(keywords_required_matched, True) + _chips(keywords_required_missing, False)
            + '<div style="font-size:11px;color:var(--ink-faint);margin:12px 0 4px;font-weight:600;">Preferred</div>'
            + _chips(keywords_preferred_matched, True) + _chips(keywords_preferred_missing, False)
            + kw_warn
        )
    else:
        inner = (
            _label("ATS keyword match — N/A")
            + delta_html
            + '<div style="font-size:13px;color:var(--ink-faint);padding:6px 0;">'
            + 'Add your master CV (My Profile) to see which of this job\'s keywords it covers.</div>'
        )

    button_html = (
        '<div style="margin-top:14px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;">'
        f'<button type="button" onclick="atsRecheck(\'{escape(job_id)}\',this)" '
        'style="padding:8px 16px;border-radius:var(--r-md);font-size:13px;font-weight:600;font-family:inherit;'
        'cursor:pointer;background:var(--surface-2);color:var(--ink-soft);border:1px solid var(--line);white-space:nowrap;">'
        'Re-check against tailored CV</button>'
        '<span id="kw-recheck-error" style="font-size:12.5px;color:var(--skip);"></span>'
        '</div>'
    )

    card = (
        '<div style="background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);'
        f'padding:var(--pad);box-shadow:var(--shadow-sm);">{inner}{button_html}</div>'
    )
    return f'<div id="kw-panel-body">{card}</div>'


# Defines window.atsRecheck once per page. The button uses an inline onclick so it
# keeps working after the panel is replaced via outerHTML (swapped-in markup does not
# re-run <script> tags, but inline handlers survive).
_ATS_RECHECK_JS = (
    '<script>'
    'window.atsRecheck=function(jobId,btn){'
    'var e=document.getElementById("kw-recheck-error");if(e)e.textContent="";'
    'var orig=btn.textContent;btn.disabled=true;btn.textContent="Re-checking…";'
    'fetch("/job/"+encodeURIComponent(jobId)+"/ats-recheck",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})'
    '.then(function(r){return r.json().then(function(d){return{ok:r.ok,data:d};});})'
    '.then(function(res){'
    'if(!res.ok){btn.disabled=false;btn.textContent=orig;var er=document.getElementById("kw-recheck-error");if(er)er.textContent=(res.data&&res.data.error)||"Re-check failed";return;}'
    'var panel=document.getElementById("kw-panel-body");'
    'if(panel&&res.data&&res.data.panel_html){panel.outerHTML=res.data.panel_html;}'
    'else{btn.disabled=false;btn.textContent=orig;}'
    '})'
    '.catch(function(err){btn.disabled=false;btn.textContent=orig;var er=document.getElementById("kw-recheck-error");if(er)er.textContent="Request failed: "+err.message;});'
    '};'
    '</script>'
)


def render_job_page(vm: "JobPageViewModel") -> str:
    flash, flash_kind, embed = vm.flash, vm.flash_kind, vm.embed

    flash_class = "flash error" if flash_kind == "error" else "flash success"
    flash_html = f'<div class="panel {flash_class}">{escape(flash)}</div>' if flash else ""

    # ── helpers ──────────────────────────────────────────────────────────────
    def _decision_chip(d: str, large: bool = False) -> str:
        cfg = {
            "apply":  ("var(--apply)",  "var(--apply-bg)",  "var(--apply-line)",  "✓", "Apply"),
            "review": ("var(--review)", "var(--review-bg)", "var(--review-line)", "⚑", "Review"),
            "skip":   ("var(--skip)",   "var(--skip-bg)",   "var(--skip-line)",   "−", "Skip"),
        }.get(d, ("var(--ink-faint)", "var(--surface-sunk)", "var(--line)", "?", d.title()))
        c, bg, line, icon, label = cfg
        if large:
            return (
                f'<span style="display:inline-flex;align-items:center;gap:9px;padding:9px 16px 9px 13px;'
                f'border-radius:100px;font-weight:700;font-size:16px;letter-spacing:-0.01em;'
                f'color:{c};background:{bg};border:1px solid {line};">'
                f'<span style="display:inline-flex;align-items:center;justify-content:center;'
                f'width:22px;height:22px;border-radius:100px;background:{c};color:var(--surface-2);font-size:13px;">{icon}</span>'
                f'{escape(label)}</span>'
            )
        return (
            f'<span style="display:inline-flex;align-items:center;gap:6px;padding:4px 11px 4px 8px;'
            f'border-radius:100px;font-weight:700;font-size:12.5px;letter-spacing:0.01em;text-transform:uppercase;'
            f'color:{c};background:{bg};border:1px solid {line};">'
            f'<span style="display:inline-flex;align-items:center;justify-content:center;'
            f'width:16px;height:16px;border-radius:100px;background:{c};color:var(--surface-2);font-size:10px;">{icon}</span>'
            f'{escape(label)}</span>'
        )

    def _score_dial(value: float, decision: str, size: int = 142) -> str:
        stroke = size * 0.085
        r = (size - stroke) / 2 - 2
        c = 2 * 3.14159265 * r
        pct = max(0.0, min(100.0, float(value))) / 100.0
        offset = c * (1 - pct)
        color_map = {"apply": "var(--apply)", "review": "var(--review)", "skip": "var(--skip)"}
        color = color_map.get(decision, "var(--accent)")
        cx = size / 2
        return (
            f'<div style="position:relative;width:{size}px;height:{size}px;flex-shrink:0;">'
            f'<svg width="{size}" height="{size}" style="transform:rotate(-90deg);">'
            f'<circle cx="{cx}" cy="{cx}" r="{r:.1f}" fill="none" stroke="var(--line)" stroke-width="{stroke:.1f}"/>'
            f'<circle cx="{cx}" cy="{cx}" r="{r:.1f}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke:.1f}" stroke-linecap="round" '
            f'stroke-dasharray="{c:.1f}" stroke-dashoffset="{offset:.1f}"/>'
            f'</svg>'
            f'<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;">'
            f'<div style="font-family:var(--font-mono);font-size:{int(size*0.33)}px;font-weight:700;line-height:1;color:var(--ink);">{int(value)}</div>'
            f'<div style="font-size:{int(size*0.082)}px;font-weight:600;color:var(--ink-faint);letter-spacing:0.08em;margin-top:3px;">FIT SCORE</div>'
            f'</div></div>'
        )

    def _confidence_meter(level: str) -> str:
        pct = {"high": 1.0, "medium": 0.6, "low": 0.3}.get(level, 0.5)
        dots = 5
        filled = round(pct * dots)
        label = {"high": "High", "medium": "Moderate", "low": "Low"}.get(level, level.title())
        pct_str = f"{int(pct * 100)}%"
        dots_html = "".join(
            f'<span style="width:7px;height:7px;border-radius:100px;background:{"var(--ink)" if i < filled else "var(--line)"};display:inline-block;"></span>'
            for i in range(dots)
        )
        return (
            f'<div style="display:flex;align-items:center;gap:9px;">'
            f'<div style="display:flex;gap:3px;">{dots_html}</div>'
            f'<span style="font-size:12.5px;font-weight:600;color:var(--ink-soft);">{escape(label)}</span>'
            f'<span style="font-family:var(--font-mono);font-size:12px;color:var(--ink-faint);">{pct_str}</span>'
            f'</div>'
        )

    def _subscore_bar(label: str, note: str, value: float) -> str:
        tone = "var(--apply)" if value >= 75 else ("var(--review)" if value >= 50 else "var(--skip)")
        return (
            f'<div style="display:grid;grid-template-columns:140px 1fr 38px;align-items:center;gap:14px;padding:8px 0;">'
            f'<div><div style="font-size:13px;font-weight:600;">{escape(label)}</div>'
            f'<div style="font-size:11px;color:var(--ink-faint);margin-top:2px;">{escape(note)}</div></div>'
            f'<div style="height:7px;background:var(--surface-sunk);border-radius:100px;overflow:hidden;border:1px solid var(--line-soft);">'
            f'<div style="height:100%;width:{value:.0f}%;background:{tone};border-radius:100px;"></div></div>'
            f'<div style="font-family:var(--font-mono);font-size:13px;font-weight:600;text-align:right;color:var(--ink-soft);">{value:.0f}</div>'
            f'</div>'
        )

    def _reason_row(kind: str, text: str) -> str:
        cfg = {
            "strength": ("var(--apply)",  "var(--surface-2)", "✓"),
            "blocker":  ("var(--skip)",   "var(--surface-2)", "✕"),
            "gap":      ("var(--review)", "var(--surface-2)", "·"),
        }.get(kind, ("var(--ink-faint)", "var(--surface-2)", "·"))
        c, ic, icon = cfg
        return (
            f'<div style="display:flex;gap:10px;align-items:flex-start;padding:7px 0;">'
            f'<span style="flex-shrink:0;margin-top:1px;width:18px;height:18px;border-radius:100px;'
            f'display:inline-flex;align-items:center;justify-content:center;background:{c};color:{ic};font-size:11px;font-weight:700;">{icon}</span>'
            f'<span style="font-size:13.5px;line-height:1.45;color:var(--ink-soft);">{escape(text)}</span>'
            f'</div>'
        )

    def _section_label(text: str, right: str = "") -> str:
        return (
            f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">'
            f'<div style="font-size:11.5px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:var(--ink-faint);">{text}</div>'
            f'{right}</div>'
        )

    def _card(content: str, raised: bool = False, style: str = "") -> str:
        shadow = "var(--shadow-md)" if raised else "var(--shadow-sm)"
        return (
            f'<div style="background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);'
            f'padding:var(--pad);box-shadow:{shadow};{style}">{content}</div>'
        )

    def _tag(text: str, mono: bool = False) -> str:
        ff = "font-family:var(--font-mono);" if mono else ""
        return (
            f'<span style="display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:100px;'
            f'font-size:11.5px;font-weight:600;{ff}color:var(--ink-soft);background:var(--surface-sunk);'
            f'border:1px solid var(--line);white-space:nowrap;">{escape(text)}</span>'
        )

    def _grade_badge() -> str:
        grade = vm.qualitative_grade or {}
        base = grade.get("base_grade")
        capped = grade.get("capped_grade") or base
        reason = grade.get("cap_reason")
        if not base:
            return ""
        if reason and capped != base:
            text = f"Base grade {base} -> capped {capped}: {reason}"
        elif vm.qualitative_assessment is None:
            text = f"Grade {base} · base grade"
        else:
            text = f"Grade {capped} · qualitative advisory"
        return (
            f'<span style="display:inline-flex;align-items:center;gap:6px;margin-left:10px;vertical-align:middle;'
            f'padding:7px 11px;border-radius:100px;border:1px solid var(--line);background:var(--surface);'
            f'color:var(--ink-soft);font-size:12px;font-weight:700;box-shadow:var(--shadow-sm);">'
            f'{escape(text)}</span>'
        )

    def _grade_warning_banner() -> str:
        grade = vm.qualitative_grade or {}
        warning = grade.get("warning")
        if not warning:
            return ""
        return (
            f'<div style="margin-top:14px;padding:10px 12px;border-radius:var(--r-md);'
            f'border:1px solid var(--review-line);background:var(--review-bg);color:var(--review);'
            f'font-size:13px;font-weight:700;line-height:1.45;">{escape(warning)}</div>'
        )

    def _render_qualitative_panel() -> str:
        assessment = vm.qualitative_assessment
        qrow = vm.qualitative_index or {}
        status = qrow.get("status")
        show_panel = assessment is not None or status in {"running", "pending", "error"}
        force_button = ""
        if assessment is not None or status == "error":
            force_button = (
                f'<button type="submit" name="force" value="1" style="padding:4px 12px;font-size:12px;'
                f'cursor:pointer;border:1px solid var(--line);background:var(--surface);color:var(--ink-soft);'
                f'border-radius:var(--r-md);font-weight:600;font-family:inherit;">Re-run</button>'
            )
        button = (
            f'<form method="post" action="/job/{escape(vm.job_id)}/qualitative-assess" style="margin:0;">'
            f'<button type="submit" style="padding:6px 14px;font-size:12.5px;cursor:pointer;border:1px solid var(--accent);'
            f'background:transparent;color:var(--accent);border-radius:var(--r-md);font-weight:600;font-family:inherit;">'
            f'Qualitative assessment (AI)</button>{force_button}</form>'
        )
        if not show_panel:
            return (
                f'<div style="margin-top:16px;background:var(--surface);border:1px solid var(--line);'
                f'border-radius:var(--r-lg);padding:var(--pad);box-shadow:var(--shadow-sm);">'
                f'{_section_label("Qualitative assessment", right=button)}'
                f'<p style="font-size:12.5px;color:var(--ink-faint);margin:0;">'
                f'This sends the job description and a profile summary to the Gemini API.</p>'
                f'</div>'
            )
        if status in {"running", "pending"} and assessment is None:
            body = '<p style="font-size:13px;color:var(--ink-faint);margin:0;">Assessment is already in flight.</p>'
        elif status == "error" and assessment is None:
            body = (
                f'<div style="font-size:13px;color:var(--skip);background:var(--skip-bg);'
                f'border:1px solid var(--skip-line);border-radius:var(--r-md);padding:10px 12px;">'
                f'Assessment failed: {escape(qrow.get("error_text") or "validation failed")}</div>'
            )
        else:
            dims = assessment.get("dimensions", {}) if isinstance(assessment, dict) else {}
            dim_labels = {
                "seniority_fit": "Seniority fit",
                "culture_signals": "Culture signals",
                "red_flags": "Red flags",
                "role_archetype_alignment": "Role archetype alignment",
            }
            rows = []
            for key, label in dim_labels.items():
                dim = dims.get(key, {})
                if isinstance(dim, dict) and dim.get("tier") == "unknown":
                    rows.append(
                        f'<div style="padding:12px 0;border-bottom:1px solid var(--line-soft);">'
                        f'<div style="font-size:13px;font-weight:700;color:var(--ink);">{escape(label)}: unknown</div>'
                        f'<div style="font-size:13px;color:var(--ink-faint);margin-top:4px;">{escape(dim.get("warning") or "")}</div>'
                        f'</div>'
                    )
                    continue
                evidence = dim.get("evidence", []) if isinstance(dim, dict) else []
                evidence_html = "".join(
                    f'<blockquote style="margin:6px 0 0;padding-left:10px;border-left:3px solid var(--line);'
                    f'font-size:12.5px;color:var(--ink-soft);">{escape(q)}</blockquote>'
                    for q in evidence
                )
                rows.append(
                    f'<div style="padding:12px 0;border-bottom:1px solid var(--line-soft);">'
                    f'<div style="display:flex;align-items:center;gap:8px;justify-content:space-between;">'
                    f'<div style="font-size:13px;font-weight:700;color:var(--ink);">{escape(label)}</div>'
                    f'<span style="font-family:var(--font-mono);font-size:12px;font-weight:700;color:var(--ink-soft);">'
                    f'{escape(str(dim.get("score", "—")))} / 5</span></div>'
                    f'{evidence_html}'
                    f'<div style="font-size:13px;color:var(--ink-soft);margin-top:7px;line-height:1.5;">'
                    f'{escape(dim.get("reasoning") or "")}</div>'
                    f'</div>'
                )
            pq = assessment.get("posting_quality", {}) if isinstance(assessment, dict) else {}
            signals = pq.get("signals", []) if isinstance(pq, dict) else []
            signals_html = "".join(f'<li>{escape(s)}</li>' for s in signals) or '<li>No signals provided.</li>'
            body = (
                "".join(rows)
                + f'<div style="padding-top:12px;">'
                f'<div style="font-size:11.5px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:var(--ink-faint);">Posting quality</div>'
                f'<div style="font-size:13px;margin-top:6px;">Tier: <strong>{escape(pq.get("tier") or "unknown")}</strong></div>'
                f'<ul style="margin:6px 0 0;padding-left:18px;font-size:13px;line-height:1.6;color:var(--ink-soft);">{signals_html}</ul>'
                f'</div>'
            )
        return (
            f'<div style="margin-top:16px;background:var(--surface);border:1px solid var(--line);'
            f'border-radius:var(--r-lg);padding:var(--pad);box-shadow:var(--shadow-sm);">'
            f'{_section_label("Qualitative assessment", right=button)}'
            f'<p style="font-size:12.5px;color:var(--ink-faint);margin:0 0 10px;">'
            f'This sends the job description and a profile summary to the Gemini API.</p>'
            f'{body}</div>'
        )

    qualitative_panel_html = _render_qualitative_panel()

    # ── main analysis block ───────────────────────────────────────────────────
    if vm.has_analysis:
        eff_decision = vm.effective_decision
        job_id_esc = escape(vm.job_id)
        is_overridden = vm.user_decision is not None and vm.user_decision != vm.decision
        _breakdown_right = '<span style="font-size:11px;color:var(--ink-faint);">weighted \xb7 deterministic</span>'
        _breakdown_label = _section_label("Score breakdown", right=_breakdown_right)

        # score dial + verdict card
        breakdown_items = vm.score_breakdown_rows
        subscores_html = "".join(
            _subscore_bar(label, reason, value)
            for label, reason, value in breakdown_items
        )
        ats_str = f"{vm.ats_score} / 100" if vm.ats_score is not None else "N/A"
        # Verdict card's "Keyword match" metric shares this string with the panel.
        kw_rate_str = f"{vm.keyword_match_rate}%" if vm.keyword_match_rate is not None else "N/A"
        # F1 v2 — one rendering path for the panel (first render + AJAX re-check).
        keyword_block_html = render_keyword_match_panel(
            job_id=vm.job_id,
            keyword_match_rate=vm.keyword_match_rate,
            keywords_required_matched=vm.keywords_required_matched,
            keywords_required_missing=vm.keywords_required_missing,
            keywords_preferred_matched=vm.keywords_preferred_matched,
            keywords_preferred_missing=vm.keywords_preferred_missing,
            keywords_overused=vm.keywords_overused,
            keyword_match_baseline_rate=vm.keyword_match_baseline_rate,
            keyword_match_source=vm.keyword_match_source,
        )
        overridden_badge = (
            '<span style="font-size:10px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;'
            'padding:3px 8px;border-radius:100px;background:var(--review-bg);color:var(--review);'
            'border:1px solid var(--review-line);margin-left:8px;">Overridden</span>'
            if is_overridden else ""
        )
        grade_badge = _grade_badge()
        grade_warning = _grade_warning_banner()

        verdict_card_html = (
            f'<div style="margin-top:22px;background:var(--surface);border:1px solid var(--line);'
            f'border-radius:var(--r-lg);overflow:hidden;box-shadow:var(--shadow-md);">'
            # top strip: dial + decision
            f'<div style="display:grid;grid-template-columns:auto 1fr;gap:28px;padding:26px var(--pad);'
            f'align-items:center;border-bottom:1px solid var(--line);background:var(--surface-2);">'
            f'{_score_dial(vm.match_score, eff_decision)}'
            f'<div>'
            f'<div style="font-size:11.5px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;'
            f'color:var(--ink-faint);margin-bottom:10px;">Recommended decision</div>'
            f'{_decision_chip(eff_decision, large=True)}{overridden_badge}{grade_badge}'
            f'{grade_warning}'
            f'<div style="display:flex;align-items:center;gap:28px;margin-top:18px;flex-wrap:wrap;">'
            f'<div>'
            f'<div style="font-size:11px;color:var(--ink-faint);margin-bottom:5px;font-weight:600;">'
            f'Confidence <span style="font-weight:400;">(data completeness)</span></div>'
            f'{_confidence_meter(vm.confidence)}'
            f'</div>'
            f'<div>'
            f'<div style="font-size:11px;color:var(--ink-faint);margin-bottom:5px;font-weight:600;">ATS readiness</div>'
            f'<span style="font-family:var(--font-mono);font-size:13px;font-weight:600;color:var(--ink-soft);">{escape(ats_str)}</span>'
            f'</div>'
            f'<div>'
            f'<div style="font-size:11px;color:var(--ink-faint);margin-bottom:5px;font-weight:600;">Keyword match</div>'
            f'<span style="font-family:var(--font-mono);font-size:13px;font-weight:600;color:var(--ink-soft);" title="Coverage of this job&#39;s keywords in your CV — separate from ATS readiness (which is about clean parsing).">{escape(kw_rate_str)}</span>'
            f'</div>'
            f'</div>'
            f'<p style="margin:12px 0 0;font-size:13px;color:var(--ink-faint);line-height:1.5;">{escape(vm.decision_reason)}</p>'
            f'</div>'
            f'</div>'
            # subscores
            f'<div style="padding:20px var(--pad);">'
            f'{_breakdown_label}'
            f'{subscores_html}'
            f'</div>'
            f'</div>'
        )

        # blockers, strengths, gaps
        _blocker_label = _section_label('<span style="color:var(--skip);">Blockers</span>')
        blocker_rows = "".join(_reason_row("blocker", b) for b in vm.blockers)
        blocker_card = (
            f'<div style="background:var(--surface);border:1px solid var(--skip-line);border-radius:var(--r-lg);'
            f'padding:var(--pad);box-shadow:var(--shadow-sm);">'
            f'{_blocker_label}'
            f'{blocker_rows}</div>'
        ) if vm.blockers else ""
        blocker_col = f'<div style="grid-column:1 / -1;">{blocker_card}</div>' if blocker_card else ""

        strength_rows = "".join(_reason_row("strength", s) for s in vm.strengths) or (
            '<div style="font-size:13px;color:var(--ink-faint);padding:7px 0;">None flagged.</div>'
        )
        _gap_req_skills  = list(vm.missing_required_skills)
        _gap_pref_skills = list(vm.missing_preferred_skills)
        _gap_all = (
            [("Required",  s) for s in _gap_req_skills] +
            [("Preferred", s) for s in _gap_pref_skills]
        )
        if _gap_all:
            _gap_cb_rows = []
            for _gi, (_gtag, _gsk) in enumerate(_gap_all):
                _gsk_esc  = escape(_gsk)
                _gtag_col = "var(--skip)" if _gtag == "Required" else "var(--review)"
                _gap_cb_rows.append(
                    f'<label style="display:flex;gap:10px;align-items:center;padding:7px 0;cursor:pointer;">'
                    f'<input type="checkbox" class="gap-skill-cb" data-skill="{_gsk_esc}" checked '
                    f'style="flex-shrink:0;width:15px;height:15px;cursor:pointer;accent-color:var(--accent);">'
                    f'<span style="flex-shrink:0;margin-top:0;padding:1px 7px;border-radius:100px;'
                    f'font-size:10.5px;font-weight:700;background:{_gtag_col};color:var(--surface-2);">{_gtag}</span>'
                    f'<span style="font-size:13.5px;line-height:1.45;color:var(--ink-soft);">{_gsk_esc}</span>'
                    f'</label>'
                )
            _add_skills_btn = (
                f'<div id="gap-add-status" style="display:none;margin-top:8px;font-size:13px;color:var(--apply);"></div>'
                f'<button id="gap-add-btn" onclick="addGapSkills(\'{job_id_esc}\')" style="'
                f'margin-top:12px;padding:6px 16px;font-size:12.5px;cursor:pointer;'
                f'border:1px solid var(--accent);background:transparent;color:var(--accent);'
                f'border-radius:var(--r-md);font-weight:600;font-family:inherit;">'
                f'Add to my skills</button>'
            )
            gap_rows = "".join(_gap_cb_rows) + _add_skills_btn
        else:
            gap_rows = '<div style="font-size:13px;color:var(--ink-faint);padding:7px 0;">None flagged.</div>'
        display_risk_flags = list(vm.risk_items)
        risk_rows = "".join(_reason_row("gap", r) for r in display_risk_flags)
        risk_card = (
            f'<div style="background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);'
            f'padding:var(--pad);box-shadow:var(--shadow-sm);margin-top:16px;grid-column:1 / -1;">'
            f'{_section_label("Risk flags")}'
            f'{risk_rows}</div>'
        ) if display_risk_flags else ""

        reasons_grid_html = (
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;">'
            f'{blocker_col}'
            f'{_card(_section_label("Strengths") + strength_rows)}'
            f'{_card(_section_label("Gaps") + gap_rows)}'
            f'</div>'
            + (risk_card or "")
        )

        # AI Analysis
        _ai_run_btn = (
            '<button id="ai-explain-btn" onclick="runAiAnalysis()" style="'
            'padding:4px 13px;font-size:12px;cursor:pointer;border:1px solid var(--accent);'
            'background:transparent;color:var(--accent);border-radius:var(--r-md);'
            'font-weight:600;font-family:inherit;">Run Analysis</button>'
        )
        _ai_section_label = _section_label("AI Analysis", right=_ai_run_btn)
        ai_block_html = (
            f'<div style="margin-top:16px;background:var(--surface);border:1px solid var(--line);'
            f'border-radius:var(--r-lg);padding:var(--pad);box-shadow:var(--shadow-sm);">'
            f'{_ai_section_label}'

            # Idle state (shown before first run)
            f'<div id="ai-idle" style="padding:12px 0 4px;color:var(--ink-faint);font-size:13px;">'
            f'Click <strong>Run Analysis</strong> for a Gemini assessment of this match.</div>'

            # Loading state (hidden initially)
            f'<div id="ai-loading" style="display:none;padding:16px 0;text-align:center;'
            f'color:var(--ink-faint);font-size:13px;">Reasoning… this may take up to 30 s</div>'

            # Error state (hidden initially)
            f'<div id="ai-error" style="display:none;padding:12px;margin-top:8px;'
            f'background:color-mix(in srgb,var(--skip) 8%,transparent);'
            f'border:1px solid color-mix(in srgb,var(--skip) 25%,transparent);'
            f'border-radius:var(--r-md);color:var(--skip);font-size:13px;"></div>'

            # Result state — 3 labelled sections (hidden initially)
            f'<div id="ai-result" style="display:none;margin-top:4px;">'

            # Fit
            f'<div style="padding:14px 0;border-bottom:1px solid var(--line);">'
            f'<div style="font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;'
            f'color:var(--accent);margin-bottom:6px;">Fit Assessment</div>'
            f'<div id="ai-fit" style="font-size:13.5px;line-height:1.7;color:var(--ink-soft);"></div>'
            f'</div>'

            # Risk
            f'<div style="padding:14px 0;border-bottom:1px solid var(--line);">'
            f'<div style="font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;'
            f'color:var(--skip);margin-bottom:6px;">Key Risk</div>'
            f'<div id="ai-risk" style="font-size:13.5px;line-height:1.7;color:var(--ink-soft);"></div>'
            f'</div>'

            # Action
            f'<div style="padding:14px 0 6px;">'
            f'<div style="font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;'
            f'color:var(--go);margin-bottom:6px;">Recommended Action</div>'
            f'<div id="ai-action" style="font-size:13.5px;line-height:1.7;color:var(--ink-soft);"></div>'
            f'</div>'

            f'</div>'  # end #ai-result

            # Badge line
            f'<div id="ai-badge" style="display:none;font-size:11px;color:var(--ink-faint);'
            f'font-style:italic;margin-top:2px;padding-top:8px;border-top:1px solid var(--line);">'
            f'</div>'

            f'<script>/* AI Analysis */'
            f'function _aiShow(id){{["ai-idle","ai-loading","ai-error","ai-result"].forEach(function(x){{'
            f'document.getElementById(x).style.display=x===id?"":"none";}});}}'
            f'function runAiAnalysis(){{'
            f'var btn=document.getElementById("ai-explain-btn");'
            f'btn.disabled=true;btn.textContent="Analysing…";'
            f'document.getElementById("ai-badge").style.display="none";'
            f'_aiShow("ai-loading");'
            f'fetch("/job/{job_id_esc}/explain")'
            f'.then(function(r){{return r.json();}})'
            f'.then(function(d){{'
            f'if(d.ok&&d.fit){{'
            f'document.getElementById("ai-fit").textContent=d.fit;'
            f'document.getElementById("ai-risk").textContent=d.risk||"";'
            f'document.getElementById("ai-action").textContent=d.action||"";'
            f'var badge=document.getElementById("ai-badge");'
            f'var modelLabel=d.model_used||"unknown";'
            f'var hasThinking=(modelLabel==="gemini-3-flash-preview"||modelLabel==="gemini-2.5-flash");'
            f'badge.textContent="\xb7 via Gemini ("+(hasThinking?modelLabel+" \xb7 high reasoning":modelLabel)+")";'
            f'badge.style.display="block";'
            f'_aiShow("ai-result");'
            f'btn.textContent="Re-run";'
            f'}}else{{'
            f'document.getElementById("ai-error").textContent=d.error||"LLM unavailable";'
            f'_aiShow("ai-error");'
            f'btn.textContent="Retry";'
            f'}}'
            f'btn.disabled=false;'
            f'}})'
            f'.catch(function(){{'
            f'document.getElementById("ai-error").textContent="Could not reach the AI service.";'
            f'_aiShow("ai-error");'
            f'btn.textContent="Retry";btn.disabled=false;'
            f'}});'
            f'}}'
            f'</script>'
            f'</div>'
        )

        # Override + sticky action bar
        override_js = (
            f'<script>/* override */'
            f'(function(){{'
            f'document.querySelectorAll(".jst-override-btn").forEach(function(btn){{'
            f'btn.addEventListener("click",function(){{'
            f'var jobId=btn.dataset.jobId;var decision=btn.dataset.decision;var current=btn.dataset.current;'
            f'var payload=current===decision?{{user_decision:null}}:{{user_decision:decision}};'
            f'fetch("/job/"+jobId+"/decision",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(payload)}})'
            f'.then(function(r){{return r.json();}})'
            f'.then(function(){{setTimeout(function(){{window.location.reload();}},300);}});'
            f'}});}})();'
            f'</script>'
            f'<script>/* add gap skills */'
            f'function addGapSkills(jobId){{'
            f'var cbs=document.querySelectorAll(".gap-skill-cb:checked");'
            f'var skills=[];'
            f'cbs.forEach(function(cb){{skills.push(cb.dataset.skill);}});'
            f'if(skills.length===0){{return;}}'
            f'var btn=document.getElementById("gap-add-btn");'
            f'var status=document.getElementById("gap-add-status");'
            f'btn.disabled=true;btn.textContent="Adding…";'
            f'fetch("/job/"+jobId+"/add-gap-skills",{{'
            f'method:"POST",'
            f'headers:{{"Content-Type":"application/json"}},'
            f'body:JSON.stringify({{skills:skills}})'
            f'}})'
            f'.then(function(r){{return r.json();}})'
            f'.then(function(d){{'
            f'if(d.ok){{'
            f'status.textContent=d.added&&d.added.length?'
            f'"✓ "+d.added.length+" skill(s) added to your profile.":'
            f'"All selected skills already in your profile.";'
            f'status.style.color=d.added&&d.added.length?"var(--apply)":"var(--ink-faint)";'
            f'status.style.display="block";'
            f'if(d.added&&d.added.length){{'
            f'document.querySelectorAll(".gap-skill-cb").forEach(function(cb){{'
            f'if(d.added.indexOf(cb.dataset.skill)!==-1){{cb.disabled=true;}}'
            f'}});'
            f'}}'
            f'btn.textContent="Add to my skills";'
            f'}}else{{'
            f'status.textContent="Error: "+(d.error||"Unknown error");'
            f'status.style.color="var(--skip)";'
            f'status.style.display="block";'
            f'btn.textContent="Add to my skills";'
            f'}}'
            f'btn.disabled=false;'
            f'}})'
            f'.catch(function(){{'
            f'status.textContent="Could not reach server.";'
            f'status.style.color="var(--skip)";'
            f'status.style.display="block";'
            f'btn.textContent="Add to my skills";btn.disabled=false;'
            f'}});'
            f'}}'
            f'</script>'
        )

        def _override_action_btn(label: str, value: str, cfg_c: str, cfg_bg: str, cfg_line: str) -> str:
            on = eff_decision == value
            border = cfg_line if on else "var(--line)"
            bg = cfg_bg if on else "var(--surface)"
            color = cfg_c if on else "var(--ink-soft)"
            return (
                f'<button type="button" class="jst-override-btn" data-job-id="{job_id_esc}" '
                f'data-decision="{escape(value)}" data-current="{escape(eff_decision)}" '
                f'style="display:inline-flex;align-items:center;gap:7px;padding:9px 15px;border-radius:var(--r-md);'
                f'font-size:13.5px;font-weight:700;font-family:inherit;cursor:pointer;'
                f'border:1px solid {border};background:{bg};color:{color};transition:all .15s;">'
                f'{escape(label)}</button>'
            )

        action_bar_html = (
            f'<div style="position:sticky;bottom:0;margin-top:20px;padding:16px 0;'
            f'background:linear-gradient(to top,var(--bg) 65%,transparent);">'
            f'<div style="background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);'
            f'padding:14px 16px;box-shadow:var(--shadow-md);">'
            f'<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">'
            f'<div style="font-size:12px;color:var(--ink-faint);font-weight:600;">Decide</div>'
            f'<div style="display:flex;gap:8px;">'
            f'{_override_action_btn("Apply",  "apply",  "var(--apply)",  "var(--apply-bg)",  "var(--apply-line)")}'
            f'{_override_action_btn("Review", "review", "var(--review)", "var(--review-bg)", "var(--review-line)")}'
            f'{_override_action_btn("Skip",   "skip",   "var(--skip)",   "var(--skip-bg)",   "var(--skip-line)")}'
            f'</div>'
            f'<div style="flex:1;"></div>'
            f'<button type="button" id="tailor-btn" data-job-id="{job_id_esc}" data-decision="{escape(eff_decision)}" '
            f'style="display:inline-flex;align-items:center;gap:7px;padding:10px 15px;border-radius:var(--r-md);'
            f'font-size:13.5px;font-weight:600;font-family:inherit;cursor:pointer;'
            f'border:1px solid var(--line);background:var(--surface);color:var(--ink);">'
            f'&#10024; Tailor CV</button>'
            f'<button type="button" id="ai-cv-btn" data-job-id="{job_id_esc}" '
            f'style="display:inline-flex;align-items:center;gap:7px;padding:10px 15px;border-radius:var(--r-md);'
            f'font-size:13.5px;font-weight:600;font-family:inherit;cursor:pointer;'
            f'border:1px solid var(--accent);background:transparent;color:var(--accent);">'
            f'&#128161; AI Review CV</button>'
            f'<button type="button" id="cover-btn" '
            f'style="display:inline-flex;align-items:center;gap:7px;padding:10px 15px;border-radius:var(--r-md);'
            f'font-size:13.5px;font-weight:600;font-family:inherit;cursor:pointer;'
            f'border:1px solid var(--line);background:var(--surface);color:var(--ink);">'
            f'&#128196; Cover letter</button>'
            f'<a href="/job/{job_id_esc}/evaluate-form" '
            f'title="Reload this job into the Evaluate form and score it again against your current profile" '
            f'style="display:inline-flex;align-items:center;gap:7px;padding:10px 15px;border-radius:var(--r-md);'
            f'font-size:13.5px;font-weight:600;font-family:inherit;cursor:pointer;text-decoration:none;'
            f'border:1px solid var(--line);background:var(--surface);color:var(--ink-soft);">'
            f'&#8635; Re-evaluate</a>'
            f'</div>'
            f'<div id="tailor-result" style="margin-top:12px;"></div>'
            f'</div>'
            f'</div>'
        )

        # cover letter panel (shown/hidden)
        cover_panel_html = (
            f'<div id="cover-panel" style="display:none;margin-top:16px;background:var(--surface);'
            f'border:1px solid var(--line);border-radius:var(--r-lg);padding:var(--pad);box-shadow:var(--shadow-sm);">'
            f'{_section_label("Cover Letter")}'
            f'<form id="cover-letter-form" style="display:grid;gap:12px;">'
            f'<input type="hidden" name="job_id" value="{job_id_esc}">'
            f'<label style="display:grid;gap:4px;font-size:13.5px;">'
            f'<span style="font-weight:600;">Why this company? <span style="color:var(--skip);">*</span></span>'
            f'<textarea name="why_company_text" rows="3" style="font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface-2);color:var(--ink);resize:vertical;" placeholder="What draws you to this company?"></textarea>'
            f'</label>'
            f'<div style="display:flex;gap:12px;flex-wrap:wrap;">'
            f'<label style="flex:1;min-width:140px;display:grid;gap:4px;font-size:13.5px;">'
            f'<span style="font-weight:600;">Tone</span>'
            f'<select name="tone" style="font:inherit;padding:9px 12px;border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface-2);color:var(--ink);">'
            f'<option value="professional">Professional</option><option value="friendly">Friendly</option><option value="concise">Concise</option>'
            f'</select></label>'
            f'<label style="flex:1;min-width:140px;display:grid;gap:4px;font-size:13.5px;">'
            f'<span style="font-weight:600;">Length</span>'
            f'<select name="length" style="font:inherit;padding:9px 12px;border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface-2);color:var(--ink);">'
            f'<option value="short">Short</option><option value="medium" selected>Medium</option><option value="long">Long</option>'
            f'</select></label></div>'
            f'<label style="display:grid;gap:4px;font-size:13.5px;">'
            f'<span style="font-weight:600;">Key points <span style="color:var(--ink-faint);font-weight:400;">(optional, one per line)</span></span>'
            f'<textarea name="points" rows="3" style="font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface-2);color:var(--ink);resize:vertical;" placeholder="e.g. Led a £2M programme"></textarea>'
            f'</label>'
            f'<div style="display:flex;gap:10px;align-items:center;">'
            f'<button type="submit" style="display:inline-flex;align-items:center;gap:7px;padding:10px 18px;border-radius:var(--r-md);font-size:13.5px;font-weight:600;font-family:inherit;cursor:pointer;background:var(--accent);color:var(--accent-contrast);border:none;">Generate Cover Letter</button>'
            f'<span id="cover-letter-spinner" hidden style="color:var(--ink-faint);font-size:13px;">Generating…</span>'
            f'</div></form>'
            f'<div id="cover-letter-result" style="margin-top:12px;"></div>'
            f'</div>'
        )

        tailor_cover_js = (
            f'<script>/* tailor + cover */'
            f'(function(){{'
            # tailor
            f'var tailorBtn=document.getElementById("tailor-btn");'
            f'if(tailorBtn){{tailorBtn.addEventListener("click",function(){{'
            f'var jobId=tailorBtn.dataset.jobId;'
            f'var resultDiv=document.getElementById("tailor-result");'
            f'tailorBtn.disabled=true;tailorBtn.textContent="Tailoring…";'
            f'if(resultDiv)resultDiv.innerHTML="";'
            f'fetch("/tailor",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{job_id:jobId,manual_selected:true}})}})'
            f'.then(function(r){{return r.json().then(function(d){{return{{ok:r.ok,data:d}};}})}})'
            f'.then(function(res){{'
            f'tailorBtn.disabled=false;'
            f'if(!res.ok){{tailorBtn.textContent="Tailor CV";resultDiv.innerHTML=\'<p style="color:var(--skip);font-size:13px;">\'+( res.data.error||"Error")+\'</p>\';return;}}'
            f'var d=res.data;tailorBtn.textContent="CV Tailored ✓";tailorBtn.style.color="var(--apply)";'
            f'var html=\'<div style="background:var(--apply-bg);border:1px solid var(--apply-line);border-radius:var(--r-md);padding:14px 16px;">\';'
            f'html+=\'<p style="font-weight:600;margin-bottom:6px;color:var(--apply);">CV tailored successfully.</p>\';'
            f'if(d.saved_path)html+=\'<p style="font-size:12px;word-break:break-all;color:var(--ink-faint);">Saved to: <code>\'+d.saved_path+\'</code></p>\';'
            f'if(d.summary)html+=\'<p style="font-size:13px;margin-top:6px;">\'+d.summary+\'</p>\';'
            f'var stats=[];'
            f'if(d.promoted&&d.promoted.length)stats.push(\'<span style="color:var(--apply);">✓ \'+d.promoted.length+\' promoted</span>\');'
            f'if(d.matched&&d.matched.length)stats.push(\'<span style="color:var(--accent);">✓ \'+d.matched.length+\' matched</span>\');'
            f'if(d.missing&&d.missing.length)stats.push(\'<span style="color:var(--skip);">⚠ \'+d.missing.length+\' missing</span>\');'
            f'if(stats.length)html+=\'<p style="font-size:12px;margin-top:6px;">\'+stats.join(" &nbsp; ")+\'</p>\';'
            f'html+=\'</div>\';resultDiv.innerHTML=html;'
            f'}}).catch(function(err){{'
            f'tailorBtn.disabled=false;tailorBtn.textContent="Tailor CV";'
            f'resultDiv.innerHTML=\'<p style="color:var(--skip);font-size:13px;">Request failed: \'+err.message+\'</p>\';'
            f'}});}});}}'
            # AI Review CV
            f'var aiCvBtn=document.getElementById("ai-cv-btn");'
            f'if(aiCvBtn){{aiCvBtn.addEventListener("click",function(){{'
            f'var jobId=aiCvBtn.dataset.jobId;'
            f'var resultDiv=document.getElementById("tailor-result");'
            f'aiCvBtn.disabled=true;aiCvBtn.textContent="Reviewing… (30–60 s)";'
            f'if(resultDiv)resultDiv.innerHTML=\'<p style="color:var(--ink-faint);font-size:13px;padding:8px 0;">Gemini is reviewing your CV against this job — please wait…</p>\';'
            f'fetch("/job/"+jobId+"/ai-review-cv",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{}})}})'
            f'.then(function(r){{return r.json().then(function(d){{return{{ok:r.ok,data:d}};}})}})'
            f'.then(function(res){{'
            f'aiCvBtn.disabled=false;aiCvBtn.textContent="AI Review CV";'
            f'if(!res.ok){{resultDiv.innerHTML=\'<p style="color:var(--skip);font-size:13px;">\'+( res.data.error||"Error")+\'</p>\';return;}}'
            f'var d=res.data;'
            f'window._aiReviewedCvText=d.reviewed_cv||"";'
            f'var html=\'<div style="background:var(--surface);border:1px solid var(--line);border-radius:var(--r-md);padding:16px;">\';'
            f'html+=\'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">\';'
            f'html+=\'<span style="font-weight:700;font-size:13.5px;color:var(--ink);flex:1;">AI-Reviewed CV</span>\';'
            f'html+=\'<span style="font-size:11px;color:var(--ink-faint);">\xb7 via Gemini (\'+( d.model_used||"unknown")+\')</span>\';'
            f'html+=\'<button id="ai-cv-copy-btn" style="padding:4px 12px;font-size:12px;font-family:inherit;font-weight:600;cursor:pointer;border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface-2);color:var(--ink-soft);">Copy</button>\';'
            f'html+=\'</div>\';'
            f'if(d.saved_path)html+=\'<p style="font-size:11.5px;color:var(--ink-faint);margin-bottom:10px;word-break:break-all;">Saved: <code>\'+d.saved_path+\'</code></p>\';'
            f'if(d.changes&&d.changes.length){{'
            f'html+=\'<div style="margin-bottom:12px;padding:10px 12px;background:var(--apply-bg);border:1px solid var(--apply-line);border-radius:var(--r-md);">\';'
            f'html+=\'<div style="font-size:11.5px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:var(--apply);margin-bottom:6px;">Changes made</div>\';'
            f'html+=\'<ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.6;color:var(--ink-soft);">\';'
            f'd.changes.forEach(function(c){{html+=\'<li>\'+c.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")+\'</li>\';}});'
            f'html+=\'</ul></div>\';'
            f'}}'
            f'var safeText=d.reviewed_cv.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");'
            f'html+=\'<pre style="white-space:pre-wrap;word-break:break-word;font-family:inherit;font-size:13.5px;line-height:1.7;color:var(--ink);max-height:560px;overflow-y:auto;background:var(--surface-sunk,#f5f5f5);border:1px solid var(--line);border-radius:var(--r-md);padding:16px 18px;margin:0;">\'+safeText+\'</pre>\';'
            f'html+=\'</div>\';'
            f'resultDiv.innerHTML=html;'
            f'var copyBtn=document.getElementById("ai-cv-copy-btn");'
            f'if(copyBtn){{copyBtn.addEventListener("click",function(){{'
            f'var t=window._aiReviewedCvText;'
            f'if(!t)return;'
            f'navigator.clipboard.writeText(t).then(function(){{'
            f'copyBtn.textContent="Copied ✓";copyBtn.style.color="var(--apply)";'
            f'setTimeout(function(){{copyBtn.textContent="Copy";copyBtn.style.color="";}},1800);'
            f'}}).catch(function(){{alert("Copy failed — please select the text manually.");}});'
            f'}});}}'
            f'}}).catch(function(err){{'
            f'aiCvBtn.disabled=false;aiCvBtn.textContent="AI Review CV";'
            f'resultDiv.innerHTML=\'<p style="color:var(--skip);font-size:13px;">Request failed: \'+err.message+\'</p>\';'
            f'}});}});}}'
            # cover toggle
            f'var coverBtn=document.getElementById("cover-btn");'
            f'var coverPanel=document.getElementById("cover-panel");'
            f'if(coverBtn&&coverPanel){{coverBtn.addEventListener("click",function(){{'
            f'coverPanel.style.display=coverPanel.style.display==="none"?"block":"none";'
            f'}});}}'
            # cover submit
            f'var clForm=document.getElementById("cover-letter-form");'
            f'if(clForm){{clForm.addEventListener("submit",function(e){{'
            f'e.preventDefault();'
            f'var fd=new FormData(clForm);'
            f'var jobId=fd.get("job_id")||"";'
            f'var whyText=(fd.get("why_company_text")||"").trim();'
            f'var tone=fd.get("tone")||"professional";'
            f'var length=fd.get("length")||"medium";'
            f'var pointsRaw=(fd.get("points")||"").trim();'
            f'var points=pointsRaw?pointsRaw.split("\\n").map(function(s){{return s.trim();}}).filter(Boolean):null;'
            f'var spinner=document.getElementById("cover-letter-spinner");'
            f'var resultDiv=document.getElementById("cover-letter-result");'
            f'var submitBtn=clForm.querySelector("button[type=\'submit\']");'
            f'if(!whyText){{resultDiv.innerHTML=\'<p style="color:var(--skip);font-size:13px;">Please fill in Why this company?.</p>\';return;}}'
            f'if(submitBtn)submitBtn.disabled=true;'
            f'if(spinner)spinner.hidden=false;'
            f'resultDiv.innerHTML="";'
            f'var payload={{job_id:jobId,why_company_text:whyText,tone:tone,length:length}};'
            f'if(points)payload.points=points;'
            f'fetch("/cover-letter",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(payload)}})'
            f'.then(function(r){{return r.json().then(function(d){{return{{ok:r.ok,data:d}};}})}})'
            f'.then(function(res){{'
            f'if(submitBtn)submitBtn.disabled=false;'
            f'if(spinner)spinner.hidden=true;'
            f'if(!res.ok){{resultDiv.innerHTML=\'<p style="color:var(--skip);font-size:13px;">\'+( res.data.error||"Error")+\'</p>\';return;}}'
            f'var d=res.data;'
            f'var html=\'<div style="background:var(--apply-bg);border:1px solid var(--apply-line);border-radius:var(--r-md);padding:14px 16px;">\';'
            f'html+=\'<p style="font-weight:600;margin-bottom:6px;color:var(--apply);">Cover letter generated (\'+( d.word_count||"?")+\' words).</p>\';'
            f'if(d.saved_path)html+=\'<p style="font-size:12px;word-break:break-all;color:var(--ink-faint);">Saved to: <code>\'+d.saved_path+\'</code></p>\';'
            f'if(d.letter){{html+=\'<details style="margin-top:10px;"><summary style="cursor:pointer;font-size:13px;font-weight:600;">Preview letter</summary>\';'
            f'html+=\'<pre style="white-space:pre-wrap;font-family:inherit;font-size:12.5px;margin-top:8px;">\'+d.letter.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")+\'</pre></details>\';}}'
            f'html+=\'</div>\';resultDiv.innerHTML=html;'
            f'}}).catch(function(err){{'
            f'if(submitBtn)submitBtn.disabled=false;'
            f'if(spinner)spinner.hidden=true;'
            f'resultDiv.innerHTML=\'<p style="color:var(--skip);font-size:13px;">Request failed: \'+err.message+\'</p>\';'
            f'}});}});}}'
            f'}})();'
            f'</script>'
        )

    else:
        eff_decision = "skip"
        _job_id_esc = escape(vm.job_id)
        verdict_card_html = (
            f'<div style="margin-top:22px;background:var(--surface);border:1px solid var(--line);'
            f'border-radius:var(--r-lg);padding:var(--pad);box-shadow:var(--shadow-sm);">'
            f'<p style="color:var(--ink-faint);font-size:13.5px;margin:0 0 14px;">'
            f'<em>This job has not been evaluated yet.</em></p>'
            f'<a href="/job/{_job_id_esc}/evaluate-form" '
            f'style="display:inline-flex;align-items:center;gap:7px;padding:9px 16px;border-radius:var(--r-md);'
            f'background:var(--accent);color:var(--surface-2);font-size:13px;font-weight:700;text-decoration:none;">'
            f'Review &amp; evaluate this job →</a>'
            f'</div>'
        )
        reasons_grid_html = ""
        ai_block_html = ""
        keyword_block_html = ""
        action_bar_html = ""
        cover_panel_html = ""
        tailor_cover_js = ""
        override_js = ""

    # ── source quality badge ──────────────────────────────────────────────────
    sq = getattr(vm, "source_quality_score", None)
    if sq is not None and sq < 40:
        quality_tag = f'<span style="padding:3px 10px;border-radius:100px;font-size:11.5px;font-weight:600;background:var(--skip-bg);color:var(--skip);border:1px solid var(--skip-line);">Quality {sq} — Low data quality</span>'
    elif sq is not None and sq < 70:
        quality_tag = f'<span style="padding:3px 10px;border-radius:100px;font-size:11.5px;font-weight:600;background:var(--review-bg);color:var(--review);border:1px solid var(--review-line);">Quality {sq} — Review fields carefully</span>'
    else:
        quality_tag = ""

    # ── job header ────────────────────────────────────────────────────────────
    salary_str = format_salary_range(vm.salary_min_gbp, vm.salary_max_gbp)
    source_tag = _tag(vm.source_type or "manual", mono=True)
    source_ref = (vm.source_ref or "").strip()
    url = (vm.url or "").strip()
    # Apply link prefers the canonical advert URL (JobPosting.url); fall back to
    # source_ref only when it is itself a URL. A bare Reed id renders no link.
    if url.lower().startswith(("http://", "https://")):
        apply_url = url
    elif source_ref.lower().startswith(("http://", "https://")):
        apply_url = source_ref
    else:
        apply_url = ""
    source_ref_html = (
        f'<a href="{escape(apply_url)}" target="_blank" rel="noreferrer" '
        f'style="font-size:12px;color:var(--accent);font-weight:600;text-decoration:none;">'
        '↗ View original posting / Apply</a>'
        if apply_url
        else f'<span style="font-size:12px;color:var(--ink-faint);">{escape(source_ref)}</span>'
    )
    job_header_html = (
        f'<div style="display:flex;align-items:flex-start;gap:16px;flex-wrap:wrap;">'
        f'<div style="flex:1;min-width:280px;">'
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;">'
        f'{source_tag}'
        + (f'<span style="font-size:12px;color:var(--ink-faint);">·</span>'
           f'{source_ref_html}' if (source_ref or apply_url) else "")
        + (f'<span style="font-size:12px;color:var(--ink-faint);">·</span>{quality_tag}' if quality_tag else "")
        + '</div>'
        f'<h1 style="margin:0 0 6px;font-size:27px;font-weight:800;letter-spacing:-0.025em;line-height:1.1;">'
        f'{escape(vm.job_title)}</h1>'
        f'<div style="font-size:15px;color:var(--ink-soft);font-weight:500;">{escape(vm.company)}</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:14px;">'
        + (_tag(vm.location) if vm.location else "")
        + (_tag(salary_str, mono=True) if salary_str else "")
        + (_tag(vm.work_mode) if vm.work_mode else "")
        + (_tag(vm.employment_type) if vm.employment_type else "")
        + '</div>'
        '</div>'
        + (
            f'<a href="{escape(apply_url)}" target="_blank" rel="noreferrer" '
            f'style="flex:0 0 auto;align-self:flex-start;display:inline-flex;align-items:center;gap:6px;'
            f'background:var(--accent);color:var(--accent-contrast);padding:11px 20px;border-radius:var(--r-md);'
            f'font-size:14px;font-weight:700;text-decoration:none;white-space:nowrap;box-shadow:var(--shadow-sm);">'
            f'↗ Apply on original posting</a>'
            if apply_url else
            '<span style="flex:0 0 auto;align-self:flex-start;font-size:12.5px;color:var(--ink-faint);'
            'background:var(--surface-sunk);border:1px solid var(--line);padding:8px 12px;border-radius:var(--r-md);">'
            'No application link saved for this job</span>'
        )
        + '</div>'
    )

    # ── outcome tracking ──────────────────────────────────────────────────────
    # Options are pre-filtered to valid state-machine transitions (allowed_next_statuses).
    outcome_current = vm.outcome_status if vm.has_outcome else "not_applied"
    outcome_options = "".join(
        f'<option value="{status}"{" selected" if outcome_current == status else ""}>{status}</option>'
        for status in vm.outcome_status_options
    )
    _next_statuses = [s for s in vm.outcome_status_options if s != outcome_current]
    if _next_statuses:
        outcome_hint_html = (
            f'<p style="font-size:12px;color:var(--ink-faint);margin:0 0 12px;">'
            f'Allowed next: {escape(", ".join(_next_statuses))} '
            f'(re-saving the current status just updates the notes)</p>'
        )
    else:
        outcome_hint_html = (
            f'<p style="font-size:12px;color:var(--ink-faint);margin:0 0 12px;">'
            f'<strong>{escape(outcome_current)}</strong> is a final status — only notes can be updated.</p>'
        )
    # Inline feedback: surface outcome-related flash inside the card (the top
    # banner is easy to miss when the card is below the fold).
    _is_outcome_flash = bool(flash) and str(flash).lower().startswith("outcome")
    if _is_outcome_flash and flash_kind == "error":
        outcome_flash_html = (
            f'<div style="margin:0 0 12px;padding:10px 14px;border-radius:var(--r-md);font-size:13px;font-weight:600;'
            f'background:var(--skip-bg);color:var(--skip);border:1px solid var(--skip-line);">✕ {escape(flash)}</div>'
        )
    elif _is_outcome_flash:
        outcome_flash_html = (
            f'<div style="margin:0 0 12px;padding:10px 14px;border-radius:var(--r-md);font-size:13px;font-weight:600;'
            f'background:var(--apply-bg);color:var(--apply);border:1px solid var(--apply-line);">✓ {escape(flash)}</div>'
        )
    else:
        outcome_flash_html = ""
    outcome_scroll_js = (
        '<script>(function(){var c=document.getElementById("outcome-card");if(c)c.scrollIntoView({block:"center"});})();</script>'
        if _is_outcome_flash else ""
    )
    outcome_section_html = (
        f'<div id="outcome-card" style="margin-top:16px;background:var(--surface);border:1px solid var(--line);'
        f'border-radius:var(--r-lg);padding:var(--pad);box-shadow:var(--shadow-sm);">'
        f'{_section_label("Outcome tracking")}'
        f'{outcome_flash_html}'
        f'<p style="font-size:13px;color:var(--ink-soft);margin-bottom:6px;">'
        f'Current: <strong>{escape(outcome_current)}</strong>'
        f' &nbsp;·&nbsp; Updated: <strong>{escape(str(vm.outcome_updated_at) if vm.has_outcome else "Not tracked yet")}</strong>'
        f'</p>'
        f'{outcome_hint_html}'
        f'<form method="post" action="/outcome">'
        f'<input type="hidden" name="job_id" value="{escape(vm.job_id)}">'
        + ('<input type="hidden" name="embed" value="1">' if embed else "")
        + f'<div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;">'
        f'<label style="display:grid;gap:4px;font-size:13.5px;">'
        f'<span style="font-weight:600;">Status</span>'
        f'<select name="status" style="font:inherit;padding:9px 12px;border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface-2);color:var(--ink);">{outcome_options}</select>'
        f'</label>'
        f'<label style="flex:1;min-width:180px;display:grid;gap:4px;font-size:13.5px;">'
        f'<span style="font-weight:600;">Notes</span>'
        f'<textarea name="notes" rows="2" style="font:inherit;padding:9px 12px;border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface-2);color:var(--ink);resize:vertical;">'
        f'{escape(vm.outcome_notes if vm.has_outcome and vm.outcome_notes else "")}</textarea>'
        f'</label>'
        f'<button type="submit" style="padding:10px 18px;border-radius:var(--r-md);font-size:13.5px;font-weight:600;font-family:inherit;cursor:pointer;background:var(--accent);color:var(--accent-contrast);border:none;white-space:nowrap;align-self:end;">Save outcome</button>'
        f'</div>'
        f'</form>'
        f'</div>'
        f'{outcome_scroll_js}'
    )

    # ── job fields detail (collapsible) ───────────────────────────────────────
    def _kv(label: str, val: Any) -> str:
        v = str(val) if val not in (None, "") else "—"
        return (
            f'<div style="padding:8px 0;border-bottom:1px solid var(--line-soft);">'
            f'<div style="font-size:11px;font-weight:700;color:var(--ink-faint);letter-spacing:0.05em;text-transform:uppercase;margin-bottom:2px;">{escape(label)}</div>'
            f'<div style="font-size:13.5px;color:var(--ink-soft);">{escape(v)}</div>'
            f'</div>'
        )
    def _pill_list(items: list) -> str:
        if not items:
            return '<div style="font-size:13px;color:var(--ink-faint);">None</div>'
        return '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:4px;">' + \
               "".join(f'<span style="padding:3px 10px;border-radius:100px;font-size:12px;font-weight:600;background:var(--surface-sunk);border:1px solid var(--line);color:var(--ink-soft);">{escape(s)}</span>' for s in items) + \
               '</div>'

    fields_html = (
        f'<details style="margin-top:16px;">'
        f'<summary style="cursor:pointer;font-size:13px;font-weight:600;color:var(--ink-faint);'
        f'padding:12px var(--pad);background:var(--surface);border:1px solid var(--line);'
        f'border-radius:var(--r-lg);list-style:none;display:flex;align-items:center;gap:8px;">'
        f'&#9656; Reviewed job fields &amp; description'
        f'</summary>'
        f'<div style="background:var(--surface);border:1px solid var(--line);border-top:none;'
        f'border-radius:0 0 var(--r-lg) var(--r-lg);padding:var(--pad);">'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:0 24px;">'
        f'{_kv("Job ID", vm.job_id)}'
        f'{_kv("Source type", vm.source_type)}'
        f'{_kv("Location", vm.location)}'
        f'{_kv("Work mode", vm.work_mode)}'
        f'{_kv("Employment type", vm.employment_type)}'
        f'{_kv("Salary range", salary_str)}'
        f'{_kv("Required experience", vm.required_years_experience)}'
        f'{_kv("Domain", vm.domain)}'
        f'</div>'
        f'<div style="margin-top:14px;">'
        f'<div style="font-size:11px;font-weight:700;color:var(--ink-faint);letter-spacing:0.05em;text-transform:uppercase;margin-bottom:6px;">Required skills</div>'
        f'{_pill_list(list(vm.required_skills))}'
        f'</div>'
        f'<div style="margin-top:14px;">'
        f'<div style="font-size:11px;font-weight:700;color:var(--ink-faint);letter-spacing:0.05em;text-transform:uppercase;margin-bottom:6px;">Preferred skills</div>'
        f'{_pill_list(list(vm.preferred_skills))}'
        f'</div>'
        f'<div style="margin-top:14px;">'
        f'<div style="font-size:11px;font-weight:700;color:var(--ink-faint);letter-spacing:0.05em;text-transform:uppercase;margin-bottom:8px;">Description</div>'
        f'<pre style="white-space:pre-wrap;font-family:inherit;font-size:12.5px;line-height:1.6;color:var(--ink-soft);margin:0;max-height:340px;overflow-y:auto;padding:12px;background:var(--surface-sunk);border-radius:var(--r-md);border:1px solid var(--line);">{escape(vm.description_raw or "")}</pre>'
        f'</div>'
        f'</div>'
        f'</details>'
    )

    if embed:
        # Embed mode: no sidebar, no back link — used by review-queue iframe
        body = f"""
        <div style="padding:0;overflow-y:auto;">
          <div style="max-width:900px;margin:0 auto;padding:20px 24px 48px;">
            {flash_html}
            {job_header_html}
            {verdict_card_html}
            {qualitative_panel_html}
            {keyword_block_html}
            {reasons_grid_html}
            {ai_block_html}
            {cover_panel_html}
            {action_bar_html}
            {outcome_section_html}
            {fields_html}
            {override_js}
            {tailor_cover_js}
            {_ATS_RECHECK_JS if keyword_block_html else ""}
          </div>
        </div>
        """
        return render_page(f"{vm.job_title} @ {vm.company}", body, model_label=vm.model_label)

    sidebar = _render_sidebar("history")
    body = f"""
    <div class="app-shell">
      {sidebar}
      <main class="main-content">
        <div class="content-inner" style="max-width:900px;">
          <div style="margin-bottom:16px;">
            <a href="/?tab=history" style="font-size:13px;font-weight:600;color:var(--ink-faint);display:inline-flex;align-items:center;gap:6px;text-decoration:none;">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M11 6l-6 6 6 6"/></svg>
              Back to history
            </a>
          </div>
          {flash_html}
          {job_header_html}
          {verdict_card_html}
          {qualitative_panel_html}
          {keyword_block_html}
          {reasons_grid_html}
          {ai_block_html}
          {cover_panel_html}
          {action_bar_html}
          {outcome_section_html}
          {fields_html}
          {override_js}
          {tailor_cover_js}
          {_ATS_RECHECK_JS if keyword_block_html else ""}
        </div>
        <footer style="text-align:center;padding:12px 0 24px;font-size:11px;color:var(--muted);">
          Page updated {_PAGE_UPDATED.get("job", "—")}
        </footer>
      </main>
    </div>
    """
    return render_page(f"{vm.job_title} @ {vm.company}", body, model_label=vm.model_label)


def render_simple_list(title: str, items: list[str]) -> str:
    if not items:
        return f"<h3>{escape(title)}</h3><p>None</p>"
    rendered = "".join(f"<li>{escape(item)}</li>" for item in items)
    return f"<h3>{escape(title)}</h3><ul>{rendered}</ul>"


def render_detail_item(label: str, value: Any) -> str:
    rendered_value = value if value not in (None, "") else "—"
    return (
        f'<div>'
        f'<div class="detail-label">{escape(label)}</div>'
        f'<div class="detail-value">{escape(rendered_value)}</div>'
        f'</div>'
    )


@dataclass(frozen=True)
class ProfilePageViewModel:
    """View model for render_profile_page — primitives only, no domain object."""
    has_profile: bool
    name: str | None
    target_roles: list[str]
    locations: list[str]
    remote_preference: str | None
    salary_floor_gbp: int | None
    right_to_work_uk: object | None
    skills: list[dict]
    years_experience: object | None
    industries: list[str]
    certifications: list[str]
    achievements: list[str]
    master_cv_ref: str | None
    master_cv_text: str | None
    # Daily Digest (D3) settings
    digest_enabled: bool = True
    digest_threshold: int = 70
    digest_run_time: str = "07:00"
    digest_max_per_source: int = 50
    digest_llm_enabled: bool = True
    digest_max_llm_per_run: int = 10
    digest_llm_rpm: int = 4
    digest_llm_rpd: int = 200
    digest_llm_batch_size: int = 4
    digest_llm_batch_interval_min: int = 15


def render_profile_page(
    *,
    profile_id: str,
    vm: "ProfilePageViewModel",
    parsed_cv_text: str | None,
    parsed_filename: str | None,
    errors: dict[str, str],
    form_values: dict[str, str] | None,
    flash: str | None = None,
    model_label: str = "",
    enabled_sources: list[str] | None = None,
) -> str:
    """Render the My Profile tab page."""
    # Saved Searches (Daily Job Digest — D1). Source options come from the
    # handler (which owns the source registry); the render layer stays domain-free.
    _ss_source_options = "".join(
        f'<option value="{escape(s.lower())}">{escape(s)}</option>'
        for s in (enabled_sources or [])
    )
    saved_searches_section = (
        '<section class="panel" id="saved-searches-panel">'
        + '<h2>Saved Searches</h2>'
        + '<p>Reusable searches the daily digest will run on a schedule (auto-run lands in a later phase). '
        + 'Save, enable/disable, or delete them here.</p>'
        + '<div class="grid two-col">'
        + '<label><span>Name</span><input id="ss-name" placeholder="e.g. BA roles, London"></label>'
        + '<label><span>Source</span><select id="ss-source">' + _ss_source_options + '</select></label>'
        + '<label><span>Keywords</span><input id="ss-keywords" placeholder="e.g. business analyst"></label>'
        + '<label><span>Location</span><input id="ss-location" placeholder="e.g. London"></label>'
        + '<label><span>Min salary (GBP)</span><input id="ss-minsalary" type="number" min="0"></label>'
        + '</div>'
        + '<div style="margin-top:10px;">'
        + '<button type="button" id="ss-add-btn">+ Save search</button>'
        + '<span id="ss-status" style="margin-left:12px;color:#475569;font-size:0.85rem;"></span>'
        + '</div>'
        + '<div id="saved-searches-list" style="margin-top:14px;">Loading…</div>'
        + '</section>'
    )

    # Summary
    if vm.has_profile:
        rtw = vm.right_to_work_uk
        summary_rows = [
            ("Name", vm.name or "—"),
            ("Target roles", ", ".join(vm.target_roles) or "—"),
            ("Locations", ", ".join(vm.locations) or "—"),
            ("Remote preference", vm.remote_preference or "—"),
            ("Salary floor", f"£{vm.salary_floor_gbp:,}" if vm.salary_floor_gbp else "—"),
            ("Right to work UK", "Yes" if rtw is True else ("No" if rtw is False else "—")),
            ("Skills", ", ".join(s["name"] for s in vm.skills[:10]) + ("…" if len(vm.skills) > 10 else "") or "—"),
            ("Years experience", str(vm.years_experience) if vm.years_experience else "—"),
            ("Industries", ", ".join(vm.industries[:5]) + ("…" if len(vm.industries) > 5 else "") or "—"),
            ("Certifications", ", ".join(vm.certifications) or "—"),
            ("Achievements", str(len(vm.achievements)) + " listed" if vm.achievements else "—"),
            ("Master CV ref", vm.master_cv_ref or "—"),
        ]
        summary_html = "".join(
            f"<tr><td><strong>{escape(label)}</strong></td><td>{escape(str(val))}</td></tr>"
            for label, val in summary_rows
        )
        summary_section = (
            "<section class=" + '"panel">'
            f"<h2>Current profile summary</h2>"
            f"<table><tbody>{summary_html}</tbody></table></section>"
        )
    else:
        summary_section = (
            "<section class=" + '"panel">'
            "<h2>Current profile summary</h2>"
            "<p><em>No profile saved yet. Fill the form below and click Save.</em></p>"
            "</section>"
        )

    # Flash banner (e.g. after save)
    flash_banner = f'<div class="panel flash success">{escape(flash)}</div>' if flash else ""

    # Error banner
    if errors:
        if "form" in errors:
            error_banner = f'<div class="panel error">{escape(errors["form"])}</div>'
        else:
            error_items = "".join(
                f"<li><strong>{escape(k)}:</strong> {escape(v)}</li>" for k, v in errors.items()
            )
            error_banner = f'<div class="panel error"><ul>{error_items}</ul></div>'
    else:
        error_banner = ""

    # CV status strip
    if vm.has_profile:
        _cv_chars = len(vm.master_cv_text) if vm.master_cv_text else 0
        _cv_ref = vm.master_cv_ref or ""
        if _cv_chars:
            _cv_color = "#16a34a"
            _cv_icon = "&#10003;"
            _cv_label = f"CV on file: {_cv_chars:,} chars"
            if _cv_ref:
                _cv_label += f" | saved to {escape(_cv_ref)}"
        elif _cv_ref:
            _cv_color = "#d97706"
            _cv_icon = "&#9888;"
            _cv_label = f"CV ref set ({escape(_cv_ref)}) but no text stored — re-upload your CV below"
        else:
            _cv_color = "#dc2626"
            _cv_icon = "&#9888;"
            _cv_label = "No CV on file — upload your CV below so Tailor CV and Cover Letter work"
        cv_status_strip = (
            f'<div style="display:flex;align-items:center;gap:8px;padding:8px 14px;'
            f'border-radius:6px;background:#f8fafc;border:1px solid {_cv_color}33;margin-bottom:12px;">'
            f'<span style="color:{_cv_color};font-weight:700;">{_cv_icon}</span>'
            f'<span style="font-size:0.85rem;color:{_cv_color};">{_cv_label}</span>'
            f'</div>'
        )
    else:
        cv_status_strip = ""

    # Form helpers
    fv = form_values or {}

    def fvget(key: str, default: str = "") -> str:
        return escape(fv.get(key, default))

    def objval(key: str) -> str:
        return str(getattr(vm, key, "") or "")

    cv_text = escape(parsed_cv_text or (vm.master_cv_text if vm.has_profile else ""))
    cv_filename_val = escape(parsed_filename or (vm.master_cv_ref if vm.has_profile else ""))
    # For multi-select, split stored value into a set of selected values.
    # Map old single-string values to the aligned option values.
    _REMOTE_COMPAT = {"remote": "remote_only", "hybrid_friendly": "hybrid", "office_only": "onsite"}
    _remote_raw = fvget("remote_preference", objval("remote_preference"))
    remote_selected = set(
        _REMOTE_COMPAT.get(v.strip(), v.strip())
        for v in _remote_raw.split(",") if v.strip()
    )

    def sel_opt_multi(value: str, label: str) -> str:
        s = " selected" if value in remote_selected else ""
        return f'<option value="{escape(value)}"{s}>{escape(label)}</option>'

    # Pre-compute skills JSON for the table (replay from form_values or load from profile)
    _skills_json_replay = fv.get("skills_json", "")
    if _skills_json_replay:
        _skills_init_json = escape(_skills_json_replay)
    else:
        _skills_list = list(vm.skills)
        _skills_init_json = escape(json.dumps(_skills_list, ensure_ascii=False))

    # Build body via string concat - each piece is a single-quoted Python string
    # inner double-quotes inside HTML work via string concatenation: "<attr " + "value" + ">"
    _sidebar_html = _render_sidebar("profile")
    body = (
        '<div class="app-shell">'
        + _sidebar_html
        + '<main class="main-content"><div class="content-inner">'
        + flash_banner
        + error_banner
        + summary_section
        + '<section class="panel">'
        + '<h2>Upload CV</h2>'
        + cv_status_strip
        + '<p>Upload a .txt, .pdf, or .docx file (max 5 MB) to extract your CV text, then edit and save your profile.</p>'
        + '<div style="margin-bottom: 16px;">'
        + '<input type="file" id="cv-file-input" accept=".txt,.pdf,.docx">'
        + '<button type="button" id="cv-upload-btn" style="margin-top:8px;">Parse CV</button>'
        + '<p id="cv-upload-status" style="min-height:1.25rem; margin-top:4px; color:#475569;"></p>'
        + '</div>'
        + '<div id="cv-parsed-preview" hidden style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px;margin-bottom:16px;">'
        + '<p style="color:#2563eb;font-weight:600;">CV parsed! Review the text below and fill in the rest of the form.</p>'
        + '<p style="font-size:0.9em;color:#64748b;">Filename: '
        + cv_filename_val
        + '</p></div></section>'
        + '<section class="panel">'
        + '<h2>Profile details</h2>'
        + '<form method="post" action="/profile/save" id="profile-form">'
        + '<input type="hidden" name="profile_id" value="'
        + escape(profile_id)
        + '">'
        + '<input type="hidden" name="_cv_filename" id="cv-filename-field" value="'
        + cv_filename_val
        + '">'
        + '<input type="hidden" name="master_cv_ref" value="'
        + escape(vm.master_cv_ref if vm.has_profile else "")
        + '">'
        + '<div class="grid two-col">'
        + '<label><span>Name</span><input name="name" value="'
        + fvget("name", objval("name"))
        + '"></label>'
        + '<label><span>Target roles (comma-separated)</span><input name="target_roles" value="'
        + fvget("target_roles", ", ".join(getattr(vm, "target_roles", []) or []))
        + '" placeholder="e.g. Business Analyst, Data Analyst"></label>'
        + '<label><span>Locations (comma-separated)</span><input name="locations" value="'
        + fvget("locations", ", ".join(getattr(vm, "locations", []) or []))
        + '" placeholder="e.g. London, Manchester, Remote"></label>'
        + '<label><span>Remote preference <small style="color:var(--ink-faint);font-weight:400">(hold Cmd/Ctrl to multi-select)</small></span>'
        + '<select multiple id="remote_pref_select" size="4" style="height:auto">'
        + sel_opt_multi("remote_only", "Remote only")
        + sel_opt_multi("hybrid", "Hybrid (remote + office)")
        + sel_opt_multi("flexible", "Flexible (any mode)")
        + sel_opt_multi("onsite", "Office / Onsite")
        + '</select>'
        + '<input type="hidden" name="remote_preference" id="remote_pref_hidden">'
        + '</label>'
        + '<label><span>Salary floor (GBP)</span><input name="salary_floor_gbp" type="number" min="0" value="'
        + fvget("salary_floor_gbp", objval("salary_floor_gbp"))
        + '"></label>'
        + '<label><span>Years experience</span><input name="years_experience" type="number" min="0" step="0.5" value="'
        + fvget("years_experience", objval("years_experience"))
        + '"></label>'
        + '<label><span>Right to work UK</span>'
        + '<select name="right_to_work_uk">'
        + ('<option value="">— not set —</option>'
           '<option value="true"' + (' selected' if (fv.get("right_to_work_uk") or str(getattr(vm, "right_to_work_uk", None))) in ("true","True","1","yes") else '') + '>Yes</option>'
           '<option value="false"' + (' selected' if (fv.get("right_to_work_uk") or str(getattr(vm, "right_to_work_uk", None))) in ("false","False","0","no") else '') + '>No</option>')
        + '</select></label>'
        + '</div>'
        + '<div class="grid two-col" style="margin-top:12px;">'
        + '<div style="grid-column:1/-1;">'
        + '<span style="font-weight:600;font-size:0.875rem;display:block;margin-bottom:4px;">Skills</span>'
        + '<table id="skills-table" style="width:100%;border-collapse:collapse;font-size:0.875rem;">'
        + '<thead><tr>'
        + '<th style="text-align:left;padding:4px 8px;border-bottom:1px solid #e2e8f0;">Name</th>'
        + '<th style="text-align:left;padding:4px 8px;border-bottom:1px solid #e2e8f0;">Level</th>'
        + '<th style="text-align:left;padding:4px 8px;border-bottom:1px solid #e2e8f0;">Years</th>'
        + '<th style="border-bottom:1px solid #e2e8f0;width:40px;"></th>'
        + '</tr></thead>'
        + '<tbody id="skills-tbody"></tbody>'
        + '</table>'
        + '<button type="button" id="add-skill-btn" style="margin-top:6px;font-size:0.8rem;padding:4px 10px;">+ Add skill</button>'
        + '<input type="hidden" name="skills_json" id="skills_json" value="'
        + _skills_init_json
        + '">'
        + '</div>'
        + '<label><span>Industries (comma-separated)</span><input name="industries" value="'
        + fvget("industries", ", ".join(getattr(vm, "industries", []) or []))
        + '" placeholder="Finance, Technology"></label>'
        + '<label><span>Certifications (comma-separated)</span><input name="certifications" value="'
        + fvget("certifications", ", ".join(getattr(vm, "certifications", []) or []))
        + '" placeholder="AWS, PMP, CFA"></label>'
        + '</div>'
        + '<label style="margin-top:12px;"><span>Achievements (one per line)</span>'
        + '<textarea name="achievements" rows="4">'
        + escape(fv.get("achievements") if "achievements" in fv else "\n".join(getattr(vm, "achievements", []) or []))
        + '</textarea>'
        + '</label>'
        + '<label><span>Master CV text</span><textarea name="master_cv_text" rows="8" placeholder="Extracted CV text will appear here after upload, or paste manually...">'
        + cv_text
        + '</textarea></label>'
        # --- Daily Digest settings (D3) — saved with the profile ---
        + '<fieldset style="margin-top:18px;border:1px solid var(--line);border-radius:8px;padding:12px 14px;">'
        + '<legend style="font-weight:600;padding:0 6px;">Daily Digest</legend>'
        + '<div class="grid two-col">'
        + '<label><span>Enabled</span><select name="digest_enabled">'
        + ('<option value="true"' + (' selected' if vm.digest_enabled else '') + '>Yes</option>')
        + ('<option value="false"' + ('' if vm.digest_enabled else ' selected') + '>No</option>')
        + '</select></label>'
        + '<label><span>Show jobs scoring ≥ (0–100)</span><input name="digest_threshold" type="number" min="0" max="100" value="' + escape(str(vm.digest_threshold)) + '"></label>'
        + '<label><span>Run time (HH:MM, local)</span><input name="digest_run_time" value="' + escape(vm.digest_run_time) + '" placeholder="07:00"></label>'
        + '<label><span>Max jobs per saved search (1–200)</span><input name="digest_max_per_source" type="number" min="1" max="200" value="' + escape(str(vm.digest_max_per_source)) + '"></label>'
        + '<label><span>AI analysis on top matches</span><select name="digest_llm_enabled">'
        + ('<option value="true"' + (' selected' if vm.digest_llm_enabled else '') + '>Yes</option>')
        + ('<option value="false"' + ('' if vm.digest_llm_enabled else ' selected') + '>No</option>')
        + '</select></label>'
        + '<label><span>Max AI calls queued per run (0–100)</span><input name="digest_max_llm_per_run" type="number" min="0" max="100" value="' + escape(str(vm.digest_max_llm_per_run)) + '"></label>'
        + '<label><span>AI calls/min (1–60)</span><input name="digest_llm_rpm" type="number" min="1" max="60" value="' + escape(str(vm.digest_llm_rpm)) + '"></label>'
        + '<label><span>AI calls/day (1–1000)</span><input name="digest_llm_rpd" type="number" min="1" max="1000" value="' + escape(str(vm.digest_llm_rpd)) + '"></label>'
        + '<label><span>AI batch size (1–50)</span><input name="digest_llm_batch_size" type="number" min="1" max="50" value="' + escape(str(vm.digest_llm_batch_size)) + '"></label>'
        + '<label><span>AI batch interval min (1–1440)</span><input name="digest_llm_batch_interval_min" type="number" min="1" max="1440" value="' + escape(str(vm.digest_llm_batch_interval_min)) + '"></label>'
        + '</div>'
        + '<p style="font-size:0.8rem;color:var(--ink-faint);margin-top:6px;">AI rate limits apply to the paced LLM worker (Daily Digest D6). Keep calls/min under your Gemini model\'s RPM and calls/day under the free-tier cap.</p>'
        + '</fieldset>'
        + '<div style="margin-top:16px;">'
        + '<button type="submit" id="profile-save-btn">Save Profile</button>'
        + '<span id="profile-save-status" style="margin-left:16px;"></span>'
        + '</div>'
        + '</form>'
        + '</section>'
        + saved_searches_section
        + '</div>'
        + '<script>'
        + '(function () {'
        + 'var fileInput = document.getElementById("cv-file-input");'
        + 'var uploadBtn = document.getElementById("cv-upload-btn");'
        + 'var statusEl = document.getElementById("cv-upload-status");'
        + 'var previewEl = document.getElementById("cv-parsed-preview");'
        + 'var cvTextarea = document.querySelector("textarea[name=master_cv_text]");'
        + 'var cvFilenameField = document.getElementById("cv-filename-field");'
        + 'function setStatus(msg, isError) {'
        + 'if (!statusEl) return;'
        + 'statusEl.textContent = msg;'
        + 'statusEl.style.color = isError ? "#b91c1c" : "#2563eb";'
        + '}'
        + 'uploadBtn && uploadBtn.addEventListener("click", async function() {'
        + 'var file = fileInput && fileInput.files && fileInput.files[0];'
        + 'if (!file) { setStatus("Please select a file first.", true); return; }'
        + 'if (file.size > 5 * 1024 * 1024) { setStatus("File too large. Maximum is 5 MB.", true); return; }'
        + 'var ext = file.name.split(".").pop().toLowerCase();'
        + 'if (!["txt","pdf","docx"].includes(ext)) { setStatus("Unsupported file type. Use .txt, .pdf, or .docx", true); return; }'
        + 'setStatus("Uploading and parsing...");'
        + 'var formData = new FormData();'
        + 'formData.append("cv_file", file);'
        + 'var pidInput = document.querySelector("input[name=\'profile_id\']");'
        + 'if (pidInput && pidInput.value) formData.append("profile_id", pidInput.value);'
        + 'try {'
        + 'var response = await fetch("/profile/parse-cv", { method: "POST", body: formData });'
        + 'var data = await response.json();'
        + 'if (!response.ok || !data.ok) throw new Error(data.error || "Parse failed");'
        + 'if (cvTextarea) cvTextarea.value = data.master_cv_text || "";'
        + 'if (cvFilenameField) cvFilenameField.value = data.filename || file.name;'
        + 'if (previewEl) previewEl.hidden = false;'
        + 'var added = 0;'
        + 'if (data.suggested_skills && data.suggested_skills.length) {'
        + '  var tbody = document.getElementById("skills-tbody");'
        + '  if (tbody && typeof makeRow === "function") {'
        + '    var existing = new Set();'
        + '    var rows = tbody.rows;'
        + '    for (var ri = 0; ri < rows.length; ri++) {'
        + '      var inp = rows[ri].cells[0] && rows[ri].cells[0].querySelector("input");'
        + '      if (inp && inp.value.trim()) existing.add(inp.value.trim().toLowerCase());'
        + '    }'
        + '    data.suggested_skills.forEach(function(name) {'
        + '      if (!existing.has(name.toLowerCase())) {'
        + '        tbody.appendChild(makeRow({ name: name, level: "unspecified", years: null }));'
        + '        existing.add(name.toLowerCase());'
        + '        added++;'
        + '      }'
        + '    });'
        + '  }'
        + '}'
        + 'var skillMsg = added > 0 ? " Added " + added + " skill(s) — set levels then save." : (data.skill_extraction_warning ? " Skill extraction: " + data.skill_extraction_warning : "");'
        + 'var saveMsg = data.auto_saved ? " CV saved automatically." : (data.auto_save_error ? " Auto-save FAILED: " + data.auto_save_error + ". Save manually below." : " Review and save below.");'
        + 'setStatus("CV parsed successfully." + saveMsg + skillMsg);'
        + '} catch(err) {'
        + 'setStatus(err.message || "Parse failed", true);'
        + '}'
        + '});'
        + '})();'
        + '(function () {'
        + 'var LEVELS = ["unspecified","junior","mid","senior","expert"];'
        + 'var tbody = document.getElementById("skills-tbody");'
        + 'var hiddenField = document.getElementById("skills_json");'
        + 'var form = document.getElementById("profile-form");'
        + 'function makeRow(skill) {'
        + '  var tr = document.createElement("tr");'
        + '  var tdName = document.createElement("td"); tdName.style.padding = "4px 8px";'
        + '  var nameInput = document.createElement("input");'
        + '  nameInput.type = "text"; nameInput.placeholder = "e.g. Python"; nameInput.value = skill.name || "";'
        + '  nameInput.style.cssText = "width:100%;box-sizing:border-box;";'
        + '  tdName.appendChild(nameInput);'
        + '  var tdLevel = document.createElement("td"); tdLevel.style.padding = "4px 8px";'
        + '  var levelSel = document.createElement("select");'
        + '  LEVELS.forEach(function(l) {'
        + '    var opt = document.createElement("option"); opt.value = l; opt.textContent = l;'
        + '    if (l === (skill.level || "unspecified")) opt.selected = true;'
        + '    levelSel.appendChild(opt);'
        + '  });'
        + '  tdLevel.appendChild(levelSel);'
        + '  var tdYears = document.createElement("td"); tdYears.style.padding = "4px 8px";'
        + '  var yearsInput = document.createElement("input");'
        + '  yearsInput.type = "number"; yearsInput.min = "0"; yearsInput.step = "1"; yearsInput.style.width = "60px";'
        + '  yearsInput.value = (skill.years != null) ? String(skill.years) : "";'
        + '  tdYears.appendChild(yearsInput);'
        + '  var tdDel = document.createElement("td"); tdDel.style.padding = "4px 8px";'
        + '  var delBtn = document.createElement("button"); delBtn.type = "button"; delBtn.textContent = "✕";'
        + '  delBtn.style.cssText = "background:none;border:none;cursor:pointer;color:#b91c1c;font-size:1rem;padding:0 4px;";'
        + '  delBtn.onclick = function() { tr.remove(); };'
        + '  tdDel.appendChild(delBtn);'
        + '  tr.appendChild(tdName); tr.appendChild(tdLevel); tr.appendChild(tdYears); tr.appendChild(tdDel);'
        + '  return tr;'
        + '}'
        + 'window.makeRow = makeRow;'
        + 'function initTable() {'
        + '  var raw = hiddenField ? hiddenField.value : "[]";'
        + '  var skills = [];'
        + '  try { skills = JSON.parse(raw) || []; } catch(e) {}'
        + '  skills.forEach(function(s) { tbody.appendChild(makeRow(s)); });'
        + '}'
        + 'function serializeTable() {'
        + '  var rows = tbody ? tbody.rows : [];'
        + '  var result = [];'
        + '  for (var i = 0; i < rows.length; i++) {'
        + '    var cells = rows[i].cells;'
        + '    var name = cells[0].querySelector("input").value.trim();'
        + '    if (!name) continue;'
        + '    var level = cells[1].querySelector("select").value;'
        + '    var yearsVal = cells[2].querySelector("input").value.trim();'
        + '    var years = yearsVal !== "" ? parseInt(yearsVal, 10) : null;'
        + '    result.push({ name: name, level: level, years: years, evidence_type: "self-reported" });'
        + '  }'
        + '  return JSON.stringify(result);'
        + '}'
        + 'document.getElementById("add-skill-btn") && document.getElementById("add-skill-btn").addEventListener("click", function() {'
        + '  tbody.appendChild(makeRow({ name: "", level: "unspecified", years: null }));'
        + '});'
        + 'form && form.addEventListener("submit", function() {'
        + '  if (hiddenField) hiddenField.value = serializeTable();'
        + '});'
        + 'initTable();'
        + '})();'
        + '</script>'
        + '<script>'
        + '(function() {'
        + '  var sel = document.getElementById("remote_pref_select");'
        + '  var hid = document.getElementById("remote_pref_hidden");'
        + '  var profileForm = document.querySelector("form[action=\'/profile/save\']");'
        + '  if (sel && hid && profileForm) {'
        + '    profileForm.addEventListener("submit", function() {'
        + '      var vals = Array.from(sel.selectedOptions).map(function(o){return o.value;});'
        + '      hid.value = vals.join(",");'
        + '    });'
        + '  }'
        + '})();'
        + '</script>'
        + '<script>'
        + '(function () {'
        + '  var listEl = document.getElementById("saved-searches-list");'
        + '  var statusEl = document.getElementById("ss-status");'
        + '  var addBtn = document.getElementById("ss-add-btn");'
        + '  if (!listEl) return;'
        + '  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }'
        + '  function setStatus(msg, isErr) { if (statusEl) { statusEl.textContent = msg || ""; statusEl.style.color = isErr ? "#b91c1c" : "#475569"; } }'
        + '  function paramsSummary(p) {'
        + '    p = p || {}; var bits = [];'
        + '    if (p.keywords) bits.push(esc(p.keywords));'
        + '    if (p.locationName) bits.push(esc(p.locationName));'
        + '    if (p.minimumSalary) bits.push("\\u00a3" + esc(p.minimumSalary) + "+");'
        + '    return bits.join(" \\u00b7 ");'
        + '  }'
        + '  function render(searches) {'
        + '    if (!searches.length) { listEl.innerHTML = "<p style=\'color:#64748b;\'><em>No saved searches yet.</em></p>"; return; }'
        + '    var html = searches.map(function(s) {'
        + '      var badge = s.enabled'
        + '        ? "<span style=\'color:#16a34a;font-weight:600;\'>\\u25cf Enabled</span>"'
        + '        : "<span style=\'color:#94a3b8;font-weight:600;\'>\\u25cb Disabled</span>";'
        + '      var lastRun = s.last_run_at ? (" \\u00b7 last run " + esc(s.last_run_at) + " (" + s.last_run_count + ")") : "";'
        + '      return "<div class=\'panel\' style=\'padding:10px 14px;margin-bottom:8px;\' data-id=\'" + esc(s.search_id) + "\'>"'
        + '        + "<div style=\'display:flex;justify-content:space-between;align-items:center;gap:8px;\'>"'
        + '        + "<div><strong>" + esc(s.name) + "</strong> &nbsp;<small style=\'color:#64748b;\'>" + esc(s.source_id) + "</small><br>"'
        + '        + "<small style=\'color:#475569;\'>" + paramsSummary(s.params) + lastRun + "</small></div>"'
        + '        + "<div style=\'white-space:nowrap;\'>" + badge'
        + '        + " <button type=\'button\' class=\'ss-run\' style=\'font-size:0.8rem;padding:3px 8px;\'>Run now</button>"'
        + '        + " <button type=\'button\' class=\'ss-toggle\' style=\'font-size:0.8rem;padding:3px 8px;\'>" + (s.enabled ? "Disable" : "Enable") + "</button>"'
        + '        + " <button type=\'button\' class=\'ss-delete\' style=\'font-size:0.8rem;padding:3px 8px;color:#b91c1c;\'>Delete</button>"'
        + '        + "</div></div></div>";'
        + '    }).join("");'
        + '    listEl.innerHTML = html;'
        + '    listEl.querySelectorAll(".ss-run").forEach(function(b) {'
        + '      b.addEventListener("click", function() { runNow(b.closest("[data-id]").getAttribute("data-id"), b); });'
        + '    });'
        + '    listEl.querySelectorAll(".ss-toggle").forEach(function(b) {'
        + '      b.addEventListener("click", function() { mutate(b.closest("[data-id]").getAttribute("data-id"), "toggle"); });'
        + '    });'
        + '    listEl.querySelectorAll(".ss-delete").forEach(function(b) {'
        + '      b.addEventListener("click", function() { if (confirm("Delete this saved search?")) mutate(b.closest("[data-id]").getAttribute("data-id"), "delete"); });'
        + '    });'
        + '  }'
        + '  async function runNow(id, btn) {'
        + '    setStatus("Running… (this may take a few seconds)");'
        + '    if (btn) btn.disabled = true;'
        + '    try {'
        + '      var r = await fetch("/saved-searches/" + encodeURIComponent(id) + "/run-now", { method: "POST" });'
        + '      var d = await r.json().catch(function(){return {};});'
        + '      if (!r.ok || !d.ok) { setStatus(d.error || "Run failed", true); return; }'
        + '      setStatus("Run done \\u2014 " + d.jobs_new + " new, " + d.jobs_llm_queued + " queued for AI, " + d.jobs_skipped + " skipped, " + d.jobs_already_seen + " already seen.");'
        + '      await load();'
        + '    } catch (e) { setStatus("Run failed", true); }'
        + '    finally { if (btn) btn.disabled = false; }'
        + '  }'
        + '  async function load() {'
        + '    try { var r = await fetch("/saved-searches"); var d = await r.json(); render(d.searches || []); }'
        + '    catch (e) { listEl.innerHTML = "<p style=\'color:#b91c1c;\'>Could not load saved searches.</p>"; }'
        + '  }'
        + '  async function mutate(id, action) {'
        + '    try {'
        + '      var r = await fetch("/saved-searches/" + encodeURIComponent(id) + "/" + action, { method: "POST" });'
        + '      if (!r.ok) { var e = await r.json().catch(function(){return {};}); setStatus(e.error || (action + " failed"), true); return; }'
        + '      await load();'
        + '    } catch (e) { setStatus(action + " failed", true); }'
        + '  }'
        + '  addBtn && addBtn.addEventListener("click", async function() {'
        + '    var name = (document.getElementById("ss-name").value || "").trim();'
        + '    var source = document.getElementById("ss-source").value;'
        + '    var params = {};'
        + '    var kw = (document.getElementById("ss-keywords").value || "").trim();'
        + '    var loc = (document.getElementById("ss-location").value || "").trim();'
        + '    var sal = (document.getElementById("ss-minsalary").value || "").trim();'
        + '    if (kw) params.keywords = kw;'
        + '    if (loc) params.locationName = loc;'
        + '    if (sal) params.minimumSalary = sal;'
        + '    if (!name) { setStatus("Name is required.", true); return; }'
        + '    if (!source) { setStatus("Pick a source.", true); return; }'
        + '    setStatus("Saving…");'
        + '    try {'
        + '      var r = await fetch("/saved-searches", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name, source_id: source, params: params }) });'
        + '      var d = await r.json().catch(function(){return {};});'
        + '      if (!r.ok || !d.ok) { setStatus(d.error || "Save failed", true); return; }'
        + '      document.getElementById("ss-name").value = "";'
        + '      document.getElementById("ss-keywords").value = "";'
        + '      document.getElementById("ss-location").value = "";'
        + '      document.getElementById("ss-minsalary").value = "";'
        + '      setStatus("Saved.");'
        + '      await load();'
        + '    } catch (e) { setStatus("Save failed", true); }'
        + '  });'
        + '  load();'
        + '})();'
        + '</script>'
        + '</div></main></div>'
    )
    return render_page(f"My Profile — {escape(profile_id)}", body, model_label=model_label)


def render_digest_page(
    *,
    entries: list,
    filters: dict,
    sources: list[str],
    saved_searches: list[tuple[str, str]],
    model_label: str = "",
) -> str:
    """Render the Daily Digest feed. PURE: every external job field (title, company,
    location) is HTML-escaped; [View] links only to the internal /job/{id} (the
    external apply URL is intentionally NOT rendered here — the job-detail page
    shows it with an http(s) guard, so no javascript:/data: vector reaches the feed.
    """
    _llm_label = {"pending": "AI: pending", "processing": "AI: running",
                  "done": "AI: done", "failed": "AI: failed", "skipped": "AI: skipped"}

    def _sel(value: str, current: str) -> str:
        return " selected" if value == current else ""

    f_date = str(filters.get("date") or "")
    f_source = str(filters.get("source") or "")
    f_search = str(filters.get("saved_search_id") or "")
    f_seen = str(filters.get("seen") or "all")

    source_opts = '<option value="">All sources</option>' + "".join(
        f'<option value="{escape(s.lower())}"{_sel(s.lower(), f_source)}>{escape(s)}</option>'
        for s in sources
    )
    search_opts = '<option value="">All saved searches</option>' + "".join(
        f'<option value="{escape(sid)}"{_sel(sid, f_search)}>{escape(name)}</option>'
        for sid, name in saved_searches
    )
    seen_opts = "".join(
        f'<option value="{v}"{_sel(v, f_seen)}>{label}</option>'
        for v, label in (("all", "All"), ("unseen", "Unseen only"), ("seen", "Seen only"))
    )

    filter_bar = (
        '<form method="get" action="/digest" class="grid" style="grid-template-columns:repeat(4,1fr);gap:10px;align-items:end;margin-bottom:14px;">'
        + '<label><span>Date</span><input type="date" name="date" value="' + escape(f_date) + '"></label>'
        + '<label><span>Source</span><select name="source">' + source_opts + '</select></label>'
        + '<label><span>Saved search</span><select name="saved_search_id">' + search_opts + '</select></label>'
        + '<label><span>Status</span><select name="seen">' + seen_opts + '</select></label>'
        + '<div style="grid-column:1/-1;"><button type="submit">Apply filters</button> '
        + '<a href="/digest" style="margin-left:8px;">Reset</a></div>'
        + '</form>'
    )

    unseen_n = sum(1 for e in entries if not e.seen)
    has_filter = bool(f_date or f_source or f_search or (f_seen != "all"))

    if not entries:
        empty = (
            '<p style="color:#64748b;"><em>No jobs match these filters.</em> '
            '<a href="/digest">Clear filters</a>.</p>' if has_filter
            else '<p style="color:#64748b;"><em>No digest jobs yet.</em> Save a search in '
                 '<a href="/profile">My Profile</a> and click <strong>Run now</strong>.</p>'
        )
        cards_html = empty
    else:
        rows = []
        for e in entries:
            dot = "#16a34a" if not e.seen else "#cbd5e1"
            bits = [escape(e.company or "")]
            if e.location:
                bits.append(escape(e.location))
            if e.salary_display:
                bits.append(escape(e.salary_display))
            meta = " · ".join(b for b in bits if b)
            sub_bits = []
            if e.saved_search_id:
                sub_bits.append(escape(e.saved_search_id))
            sub_bits.append(escape(e.source_id or ""))
            sub_bits.append(escape(e.digest_date or ""))
            llm = e.llm_status
            llm_badge = (
                f'<span style="font-size:0.72rem;color:#6366f1;margin-left:6px;">{escape(_llm_label.get(llm, ""))}</span>'
                if llm in _llm_label else ""
            )
            rows.append(
                '<div class="panel digest-card" data-id="' + escape(e.job_id) + '" '
                'style="padding:10px 14px;margin-bottom:8px;display:flex;justify-content:space-between;gap:10px;align-items:center;">'
                + '<div>'
                + f'<span style="color:{dot};font-weight:700;">●</span> '
                + f'<strong>{escape(str(e.match_score))}</strong> '
                + f'<span style="color:#475569;">{escape(e.decision or "")}</span> &nbsp;'
                + f'<a href="/job/{escape(e.job_id)}" class="digest-open">{escape(e.title or "(untitled)")}</a>'
                + llm_badge
                + f'<br><small style="color:#64748b;">{" · ".join(sub_bits)}</small>'
                + '</div>'
                + f'<div><a href="/job/{escape(e.job_id)}" class="digest-open">View</a></div>'
                + '</div>'
            )
        cards_html = "".join(rows)

    # Preserve current filters in the mark-all-seen POST body.
    filt_json = json.dumps({
        "date": f_date or None, "source": f_source or None,
        "saved_search_id": f_search or None,
    })

    body = (
        '<div class="app-shell">'
        + _render_sidebar("digest")
        + '<main class="main-content"><div class="content-inner">'
        + '<section class="panel">'
        + '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">'
        + '<h1 style="margin:0;">Daily Digest</h1>'
        + '<div style="display:flex;gap:8px;align-items:center;">'
        + '<button type="button" id="reeval-btn" title="Re-score every digest job against your current profile and threshold">Re-evaluate all</button>'
        + '<button type="button" id="mark-all-seen-btn">Mark all seen</button>'
        + '</div>'
        + '</div>'
        + '<p id="reeval-status" style="color:#6366f1;margin:6px 0 0;display:none;"></p>'
        + f'<p style="color:#475569;">{len(entries)} shown · {unseen_n} unseen</p>'
        + filter_bar
        + '<div id="digest-list">' + cards_html + '</div>'
        + '</section>'
        + '</div></main></div>'
        + '<script>'
        + '(function(){'
        + '  var FILT = ' + filt_json + ';'
        + '  async function markSeen(body){ try{ var r= await fetch("/digest/mark-seen",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}); return r.ok; }catch(e){ return false; } }'
        + '  var allBtn=document.getElementById("mark-all-seen-btn");'
        + '  allBtn && allBtn.addEventListener("click", async function(){ allBtn.disabled=true; var ok=await markSeen(Object.assign({all:true},FILT)); if(ok){ location.reload(); } else { allBtn.disabled=false; alert("Could not mark all seen."); } });'
        + '  var reBtn=document.getElementById("reeval-btn");'
        + '  var reStatus=document.getElementById("reeval-status");'
        + '  reBtn && reBtn.addEventListener("click", async function(){'
        + '    if(!confirm("Re-score every digest job against your current profile and threshold? Jobs that now qualify will reappear as unread and may be queued for AI.")) return;'
        + '    reBtn.disabled=true; reStatus.style.display="block"; reStatus.textContent="Re-evaluating…";'
        + '    try{'
        + '      var r=await fetch("/digest/reevaluate",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});'
        + '      var d=await r.json();'
        + '      if(r.ok && d && d.ok!==false){'
        + '        reStatus.textContent="Re-scored "+d.jobs_rescored+" · "+d.jobs_resurfaced+" resurfaced · "+d.jobs_llm_requeued+" queued for AI"+(d.jobs_dequeued?(" · "+d.jobs_dequeued+" de-queued"):"")+(d.jobs_errored?(" · "+d.jobs_errored+" errors"):"");'
        + '        setTimeout(function(){ location.reload(); }, 1200);'
        + '      } else { reBtn.disabled=false; reStatus.textContent="Re-evaluate failed: "+((d&&d.error)||"unknown error"); }'
        + '    }catch(e){ reBtn.disabled=false; reStatus.textContent="Re-evaluate failed: "+e; }'
        + '  });'
        + '  document.querySelectorAll(".digest-open").forEach(function(a){'
        + '    a.addEventListener("click", async function(ev){'
        + '      if(ev.metaKey||ev.ctrlKey||ev.shiftKey||ev.button!==0) return;'
        + '      ev.preventDefault();'
        + '      var card=a.closest("[data-id]"); var id=card?card.getAttribute("data-id"):null;'
        + '      if(id){ await markSeen({job_ids:[id]}); }'
        + '      window.location.href=a.getAttribute("href");'
        + '    });'
        + '  });'
        + '})();'
        + '</script>'
    )
    return render_page("Daily Digest", body, model_label=model_label)


def _render_sidebar(active_tab: str = "") -> str:
    """Render the left sidebar nav, matching the Claude deliverable design."""
    _svg = lambda paths, sw="1.7": (
        f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths}</svg>'
    )
    icons = {
        "search":   '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',
        "evaluate": '<circle cx="12" cy="12" r="8.2"/><circle cx="12" cy="12" r="3.1"/>'
                    '<path d="M12 3.8v2.4M12 17.8v2.4M3.8 12h2.4M17.8 12h2.4"/>',
        "add":      '<rect x="3.8" y="3.8" width="16.4" height="16.4" rx="3.4"/>'
                    '<path d="M12 8.4v7.2M8.4 12h7.2"/>',
        "history":  '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/>'
                    '<path d="M5.2 3.4v3.1h3.1"/><path d="M12 7.5V12l3 1.8"/>',
        "profile":  '<circle cx="12" cy="8.4" r="3.7"/>'
                    '<path d="M5.5 19.2a6.5 6.5 0 0 1 13 0"/>',
        "lock":     '<rect x="5" y="10.5" width="14" height="9" rx="2.2"/>'
                    '<path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
        "board":    '<rect x="3" y="3" width="7" height="9" rx="1.5"/>'
                    '<rect x="14" y="3" width="7" height="5" rx="1.5"/>'
                    '<rect x="14" y="12" width="7" height="9" rx="1.5"/>',
        "digest":   '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/>'
                    '<path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    }
    nav_items = [
        ("search",   "Find Jobs",   "/?tab=search",   "search"),
        ("evaluate", "Evaluate",    "/?tab=evaluate",  "evaluate"),
        ("add_job",  "Add Job",     "/?tab=add_job",  "add"),
        ("history",  "History",     "/?tab=history",  "history"),
        ("board",    "Board View",  "/board/view",    "board"),
        ("digest",   "Digest",      "/digest",        "digest"),
        ("profile",  "My Profile",  "/profile",       "profile"),
    ]
    items_html = ""
    for key, label, href, icon_name in nav_items:
        is_active = active_tab == key
        badge = ('<span id="digest-badge" style="display:none;margin-left:auto;background:#16a34a;'
                 'color:#fff;border-radius:999px;font-size:0.7rem;padding:1px 7px;"></span>'
                 if key == "digest" else "")
        items_html += (
            f'<a href="{href}" class="nav-item{"  nav-active" if is_active else ""}">'
            f'<span class="nav-icon">{_svg(icons[icon_name])}</span>'
            f'{escape(label)}{badge}</a>\n'
        )
    # Sidebar badge: fetch the unseen digest count on every page (D4).
    badge_script = (
        '<script>(function(){fetch("/digest/count").then(function(r){return r.json();})'
        '.then(function(d){var b=document.getElementById("digest-badge");'
        'if(b&&d&&d.unseen>0){b.textContent=d.unseen;b.style.display="inline-block";}})'
        '.catch(function(){});})();</script>'
    )
    items_html += badge_script
    logo_svg = _svg(icons["evaluate"], sw="1.9")
    lock_svg = (
        f'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f'{icons["lock"]}</svg>'
    )
    return f"""
    <nav class="sidebar" aria-label="Main navigation">
      <div class="sidebar-logo">
        <div class="sidebar-icon">{logo_svg}</div>
        <div>
          <div class="sidebar-title">Job Seeking Tool</div>
          <div class="sidebar-sub">UK · decision support</div>
        </div>
      </div>
      {items_html}
      <div class="sidebar-spacer"></div>
      <div class="sidebar-privacy">
        <div class="sidebar-privacy-title">{lock_svg} Local-first</div>
        <div class="sidebar-privacy-body">Profile, jobs &amp; outcomes stay on this device. Nothing auto-applies.</div>
      </div>
      <div style="padding:8px 18px 14px;font-size:10px;color:var(--ink-faint);letter-spacing:.02em;">
        Page updated {_PAGE_UPDATED.get(active_tab, "—")}
      </div>
    </nav>"""


# LT-2: page CSS/JS lifted out of the render_page f-string into plain module
# constants (single braces, no f-string escaping). The only dynamic value in the
# JS is the model label, substituted via the __MODEL_LABEL__ sentinel at render time.
_PAGE_CSS = """    /* ── Design tokens — mirrors Claude deliverable ── */
    :root {
      --font-sans: "Schibsted Grotesk", system-ui, -apple-system, sans-serif;
      --font-mono: "JetBrains Mono", ui-monospace, monospace;
      --bg:           #F1EDE4;
      --surface:      #FBFAF6;
      --surface-2:    #FFFFFF;
      --surface-sunk: #F4F1E9;
      --ink:          #1B1A16;
      --ink-soft:     #56534B;
      --ink-faint:    #918D81;
      --line:         #E3DDD0;
      --line-soft:    #EDE9DE;
      --accent:       #34467D;
      --accent-ink:   #2A3A6E;
      --accent-soft:  #E5E8F1;
      --accent-contrast: #FFFFFF;
      --apply:       #3A7A55; --apply-bg:   #E6EFE7; --apply-line:  #BFD6C4;
      --review:      #A9772A; --review-bg:  #F4ECD8; --review-line: #E3CFA1;
      --skip:        #A1503C; --skip-bg:    #F2E6E0; --skip-line:   #DDC2B6;
      --shadow-sm: 0 1px 2px rgba(40,35,22,.04), 0 1px 1px rgba(40,35,22,.03);
      --shadow-md: 0 2px 4px rgba(40,35,22,.05), 0 6px 16px rgba(40,35,22,.06);
      --r-sm: 6px; --r-md: 9px; --r-lg: 14px; --r-xl: 20px;
      --pad: 22px; --gap: 16px;
    }
    *, *::before, *::after { box-sizing: border-box; }
    html, body { margin: 0; height: 100%; }
    body { font-family: var(--font-sans); background: var(--bg); color: var(--ink);
            -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }
    .mono { font-family: var(--font-mono); font-feature-settings: "tnum" 1; }

    /* ── App shell ── */
    .app-shell { display: flex; height: 100vh; overflow: hidden; }

    /* ── Sidebar ── */
    .sidebar { width: 230px; flex-shrink: 0; background: var(--surface); border-right: 1px solid var(--line);
                display: flex; flex-direction: column; padding: 20px 14px; overflow-y: auto; }
    .sidebar-logo { display: flex; align-items: center; gap: 11px; padding: 0 8px 22px; }
    .sidebar-icon { width: 34px; height: 34px; border-radius: 9px; background: var(--ink); color: var(--bg);
                     display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .sidebar-title { font-size: 14px; font-weight: 800; letter-spacing: -0.025em; line-height: 1.15; white-space: nowrap; }
    .sidebar-sub { font-size: 10.5px; color: var(--ink-faint); font-weight: 600; letter-spacing: 0.02em; }
    .nav-item { display: flex; align-items: center; gap: 11px; padding: 10px 11px; margin-bottom: 2px;
                 border-radius: var(--r-md); border: 1px solid transparent;
                 font-size: 13.5px; font-weight: 600; letter-spacing: -0.01em;
                 text-decoration: none; color: var(--ink-soft); transition: all .14s; }
    .nav-item:hover { background: var(--surface-sunk); color: var(--ink); text-decoration: none; }
    .nav-item.nav-active { background: var(--surface-2); color: var(--ink);
                            box-shadow: var(--shadow-sm); border-color: var(--line); }
    .nav-item.nav-active .nav-icon { color: var(--accent); }
    .nav-icon { color: var(--ink-faint); display: flex; align-items: center; flex-shrink: 0; }
    .sidebar-spacer { flex: 1; }
    .sidebar-privacy { padding: 13px 12px; border-radius: var(--r-md); background: var(--surface-sunk);
                        border: 1px solid var(--line); margin-top: 12px; }
    .sidebar-privacy-title { display: flex; align-items: center; gap: 8px; color: var(--ink);
                              font-size: 12.5px; font-weight: 700; white-space: nowrap; }
    .sidebar-privacy-body { font-size: 11.5px; color: var(--ink-faint); margin-top: 5px; line-height: 1.45; }

    /* ── Main scroll area ── */
    .main-content { flex: 1; min-width: 0; overflow-y: auto; background: var(--bg); }
    .content-inner { max-width: 920px; margin: 0 auto; padding: 28px 28px; }

    /* ── Cards / panels ── */
    .panel { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-lg);
              padding: var(--pad); margin-bottom: var(--gap); box-shadow: var(--shadow-sm); }
    .panel.subtle { background: var(--surface-sunk); box-shadow: none; border-color: var(--line-soft); }
    .panel.error { border-color: var(--skip-line); background: var(--skip-bg); color: var(--skip); }
    .panel.flash { border-left: 4px solid; }
    .panel.flash.success { border-left-color: var(--apply); background: var(--apply-bg); }
    .panel.flash.error  { border-left-color: var(--skip);  background: var(--skip-bg); }

    /* ── Typography ── */
    h1 { font-size: 22px; font-weight: 800; letter-spacing: -0.03em; margin: 0 0 10px; line-height: 1.2; }
    h2 { font-size: 17px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 10px; }
    h3 { font-size: 14.5px; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 8px; }
    p  { font-size: 14px; line-height: 1.6; color: var(--ink-soft); margin: 0 0 10px; }
    ul, ol { padding-left: 20px; color: var(--ink-soft); font-size: 14px; line-height: 1.7; }
    a  { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }

    /* ── Forms ── */
    label { display: block; margin-bottom: 14px; }
    label span { display: block; font-size: 13px; font-weight: 600; margin-bottom: 5px; color: var(--ink); }
    input, textarea, select {
      width: 100%; box-sizing: border-box; padding: 9px 12px;
      border: 1px solid var(--line); border-radius: var(--r-md);
      font: inherit; font-size: 14px; background: var(--surface-2); color: var(--ink);
      transition: border-color .15s; outline: none;
    }
    input:focus, textarea:focus, select:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
    textarea { min-height: 120px; resize: vertical; }

    /* ── Buttons ── */
    button {
      display: inline-flex; align-items: center; gap: 7px; padding: 9px 15px;
      font: inherit; font-size: 13.5px; font-weight: 600; letter-spacing: -0.01em;
      border-radius: var(--r-md); border: 1px solid var(--accent-ink); cursor: pointer;
      background: var(--accent); color: var(--accent-contrast); transition: all .15s; white-space: nowrap;
    }
    button:hover { background: var(--accent-ink); }
    button.ghost { background: transparent; color: var(--ink); border-color: var(--line); }
    button.ghost:hover { background: var(--surface-sunk); }

    /* ── Grids ── */
    .grid { display: grid; gap: var(--gap); }
    .two-col { grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
    .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: var(--gap); }
    .detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 16px; }
    .detail-label { font-size: 11px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
                     color: var(--ink-faint); margin-bottom: 3px; }
    .detail-value { font-size: 14px; font-weight: 500; color: var(--ink); line-height: 1.4; }

    /* ── Actions row ── */
    .actions { display: flex; gap: 10px; margin-top: 16px; flex-wrap: wrap; align-items: center; }

    /* ── Table ── */
    table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
    th { text-align: left; padding: 9px 12px; font-size: 11px; font-weight: 700; letter-spacing: 0.08em;
          text-transform: uppercase; color: var(--ink-faint); border-bottom: 1px solid var(--line); }
    td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--line-soft);
          vertical-align: top; color: var(--ink-soft); font-size: 13.5px; }
    tr:hover td { background: var(--surface-sunk); }

    /* ── Code ── */
    pre { background: var(--ink); color: #E5DDD0; padding: 16px; border-radius: var(--r-md);
           overflow: auto; white-space: pre-wrap; font-family: var(--font-mono); font-size: 12.5px;
           line-height: 1.6; }

    /* ── Badges ── */
    .badge {
      display: inline-flex; align-items: center; gap: 5px; padding: 3px 9px;
      border-radius: 100px; font-size: 11.5px; font-weight: 600; border: 1px solid var(--line);
      white-space: nowrap; letter-spacing: 0.01em;
    }
    .badge-apply    { color: var(--apply);  background: var(--apply-bg);  border-color: var(--apply-line); }
    .badge-review   { color: var(--review); background: var(--review-bg); border-color: var(--review-line); }
    .badge-skip     { color: var(--skip);   background: var(--skip-bg);   border-color: var(--skip-line); }
    .badge-overridden { color: var(--accent); background: var(--accent-soft); border-color: var(--accent-soft); }
    .badge-quality-low { color: var(--skip);   background: var(--skip-bg);   border-color: var(--skip-line); }
    .badge-quality-mid { color: var(--review); background: var(--review-bg); border-color: var(--review-line); }
    .field-badge { display: inline-block; margin-left: 6px; vertical-align: middle; }
    .badge-autofilled { color: #166534; background: #dcfce7; border: 1px solid #bbf7d0; font-size: 10.5px;
                         font-weight: 700; border-radius: 4px; padding: 1px 6px; }
    .badge-notfound   { color: #92400e; background: #fef3c7; border: 1px solid #fde68a; font-size: 10.5px;
                         font-weight: 700; border-radius: 4px; padding: 1px 6px; }

    /* ── Sub-tabs (within content area) ── */
    .tab-row { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
    .tab-button { background: var(--surface-sunk); color: var(--ink-soft); border-color: var(--line); font-size: 13px; padding: 7px 13px; }
    .tab-button.active { background: var(--ink); color: var(--bg); border-color: var(--ink); }
    .tab-panel[hidden] { display: none; }
    .tab-content[hidden] { display: none; }

    /* ── Score pill ── */
    .score-pill { display: inline-flex; align-items: center; gap: 6px; padding: 5px 13px;
                   border-radius: 100px; font-family: var(--font-mono); font-size: 13.5px; font-weight: 700; border: 1px solid; }

    /* ── Override buttons ── */
    .override-btn { font-size: 12.5px !important; padding: 6px 12px !important; }

    /* ── Reed cards ── */
    .reed-result-card { margin-bottom: 12px; }

    /* ── Prefill status ── */
    .prefill-status { font-size: 13px; color: var(--ink-faint); margin: 8px 0 0; min-height: 1.25rem; }

    /* ── Section label ── */
    .section-label { font-size: 11px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
                      color: var(--ink-faint); margin-bottom: 10px; }

    /* ── Source toggles ── */
    .source-toggles { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }

    /* ── Scrollbar ── */
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-thumb { background: var(--line); border-radius: 20px; border: 3px solid transparent; background-clip: content-box; }
    ::-webkit-scrollbar-thumb:hover { background: var(--ink-faint); background-clip: content-box; border: 3px solid transparent; }
    /* ── AI loading overlay ── */
    #ai-loading-overlay {
      display: none; position: fixed; inset: 0; z-index: 9999;
      background: rgba(27,26,22,.55); backdrop-filter: blur(3px);
      align-items: center; justify-content: center;
    }
    #ai-loading-overlay.visible { display: flex; }
    .ai-loading-card {
      background: var(--surface); border: 1px solid var(--line);
      border-radius: var(--r-lg); padding: 32px 36px; max-width: 380px; width: 90%;
      box-shadow: var(--shadow-md); text-align: center;
    }
    .ai-loading-spinner {
      width: 36px; height: 36px; margin: 0 auto 18px;
      border: 3px solid var(--line); border-top-color: var(--accent);
      border-radius: 50%; animation: ai-spin .8s linear infinite;
    }
    @keyframes ai-spin { to { transform: rotate(360deg); } }
    .ai-loading-title { font-size: 15px; font-weight: 700; color: var(--ink); margin-bottom: 10px; }
    .ai-loading-status {
      font-size: 13px; color: var(--ink-soft); min-height: 2.6em;
      line-height: 1.5; transition: opacity .3s;
    }
    .ai-loading-hint { font-size: 11.5px; color: var(--ink-faint); margin-top: 14px; }
"""

_PAGE_JS = """    /* ── Reed select loading overlay ── */
    (function () {
      var overlay  = document.getElementById('ai-loading-overlay');
      var statusEl = document.getElementById('ai-loading-status');
      if (!overlay || !statusEl) return;

      var STEPS = [
        { at: 0,    text: 'Submitting job details…' },
        { at: 800,  text: 'Calling Gemini (__MODEL_LABEL__) to extract skills…' },
        { at: 5000, text: 'Still extracting — almost there…' },
        { at: 15000, text: 'Almost done, wrapping up the analysis…' },
        { at: 30000, text: 'Taking a bit longer than usual — hang tight…' },
      ];

      function showOverlay() {
        overlay.classList.add('visible');
        var start = Date.now();
        STEPS.forEach(function(step) {
          setTimeout(function() {
            if (!overlay.classList.contains('visible')) return;
            statusEl.style.opacity = '0';
            setTimeout(function() {
              statusEl.textContent = step.text;
              statusEl.style.opacity = '1';
            }, 150);
          }, step.at);
        });
      }

      document.querySelectorAll('form[action="/select/reed"]').forEach(function(form) {
        form.addEventListener('submit', function() {
          showOverlay();
        });
      });
    })();

    document.addEventListener('DOMContentLoaded', () => {
      const tabs = document.querySelectorAll('[data-prefill-tab]');
      const panels = document.querySelectorAll('[data-prefill-panel]');
      const status = document.getElementById('prefill-status');
      const form = document.getElementById('job-form');

      function setStatus(message, isError = false) {
        if (!status) return;
        status.textContent = message;
        status.style.color = isError ? '#b91c1c' : '#475569';
      }

      function showTab(name) {
        tabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.prefillTab === name));
        panels.forEach((panel) => {
          const active = panel.dataset.prefillPanel === name;
          panel.classList.toggle('active', active);
          panel.hidden = !active;
        });
      }

      async function prefill(mode) {
        const payload = new URLSearchParams();
        payload.set('prefill_mode', mode);
        if (mode === 'paste') payload.set('job_text', document.getElementById('prefill-job-text')?.value || '');
        if (mode === 'url') payload.set('job_url', document.getElementById('prefill-job-url')?.value || '');
        setStatus('Prefilling...');
        try {
          const response = await fetch('/prefill', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
            body: payload.toString(),
          });
          const data = await response.json();
          if (!response.ok || !data.ok) throw new Error(data.error || 'Prefill failed');
          Object.entries(data.values || {}).forEach(([name, value]) => {
            const field = form?.elements.namedItem(name);
            if (!field) return;
            field.value = value ?? '';
          });
          setStatus('Form prefilled. Review before saving.');
        } catch (error) {
          setStatus(error.message || 'Prefill failed', true);
        }
      }

      tabs.forEach((tab) => tab.addEventListener('click', () => showTab(tab.dataset.prefillTab)));
      document.getElementById('prefill-paste-btn')?.addEventListener('click', () => prefill('paste'));
      document.getElementById('prefill-url-btn')?.addEventListener('click', () => prefill('url'));
      showTab('paste');
    });
"""


def render_page(title: str, body: str, *, model_label: str = "") -> str:
    _ollama_model_label = escape(model_label)
    _js = _PAGE_JS.replace("__MODEL_LABEL__", _ollama_model_label)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
{_PAGE_CSS}  </style>
</head>
<body>
<div id="ai-loading-overlay" role="status" aria-live="polite">
  <div class="ai-loading-card">
    <div class="ai-loading-spinner"></div>
    <div class="ai-loading-title">Preparing job review…</div>
    <div class="ai-loading-status" id="ai-loading-status">Submitting job details…</div>
    <div class="ai-loading-hint">Powered by Ollama · running locally</div>
  </div>
</div>
{body}
  <script>
{_js}  </script>
</body>
</html>
"""
