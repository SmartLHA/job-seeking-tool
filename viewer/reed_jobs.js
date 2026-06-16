/**
 * reed_jobs.js — Reed.co.uk Job Search integration.
 *
 * UI flow:
 *   reedSearch()       → fetch + render job list table
 *   selectJob(job)     → show detail panel (job object passed in)
 *   closeDetail()      → hide detail panel
 */

const API_BASE = '/api/reed';

// ── State ───────────────────────────────────────────────────────────────────
let lastResults = [];

// ── Core fetch ─────────────────────────────────────────────────────────────
async function reedCall(endpoint, params = {}) {
  const url = new URL(API_BASE + endpoint, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v !== '' && v != null && v !== false) url.searchParams.set(k, String(v));
  }
  const res = await fetch(url.toString(), { cache: 'no-store' });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

// ── Search ──────────────────────────────────────────────────────────────────
async function reedSearch() {
  const statusEl = document.getElementById('reed-status');
  const tableWrap = document.getElementById('reed-table-wrap');
  const emptyEl = document.getElementById('reed-empty');
  const tbody = document.getElementById('reed-tbody');
  const searchBtn = document.getElementById('reed-search-btn');

  const el = (id) => document.getElementById(id);
  const val = (id, fallback = '') => el(id)?.value?.trim?.() ?? fallback;
  const checked = (id, fallback = false) => el(id)?.checked ?? fallback;

  const params = {
    keywords: val('f-keywords'),
    locationName: val('f-location'),
    distanceFromLocation: val('f-distance', '15') || 15,
    resultsToTake: val('f-take', '20') || 20,
  };
  const minSalary = val('f-min-salary');
  const maxSalary = val('f-max-salary');
  if (minSalary) params.minimumSalary = minSalary;
  if (maxSalary) params.maximumSalary = maxSalary;

  if (!checked('f-permanent', true)) params.permanent = 'false';
  if (checked('f-contract')) params.contract = 'true';
  if (checked('f-temp')) params.temp = 'true';
  if (checked('f-parttime')) params.partTime = 'true';
  if (!checked('f-fulltime', true)) params.fullTime = 'false';
  if (checked('f-graduate')) params.graduate = 'true';

  if (searchBtn) searchBtn.disabled = true;
  if (statusEl) {
    statusEl.innerHTML = '<span class="reed-spinner"></span>Searching...';
    statusEl.className = 'reed-status';
  }
  if (tableWrap) tableWrap.style.display = 'none';
  if (emptyEl) emptyEl.style.display = 'none';
  if (typeof closeDetail === 'function') closeDetail();

  try {
    const data = await reedCall('/search', params);
    lastResults = data.results || [];
    renderTable(lastResults);
    const count = lastResults.length;
    if (statusEl) {
      statusEl.textContent = count > 0
        ? `✓ Found ${count} job${count !== 1 ? 's' : ''} on Reed.co.uk — ${data.totalResults.toLocaleString()} total`
        : 'No jobs found. Try different keywords or location.';
    }
    if (count > 0) {
      if (tableWrap) tableWrap.style.display = '';
    } else {
      if (emptyEl) emptyEl.style.display = '';
    }
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = 'Search failed: ' + err.message;
      statusEl.className = 'reed-status error';
    }
    throw err;
  } finally {
    if (searchBtn) searchBtn.disabled = false;
  }
}

// ── Table render ────────────────────────────────────────────────────────────
function renderTable(jobs) {
  const tbody = document.getElementById('reed-tbody');
  tbody.innerHTML = '';
  if (!jobs.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:24px;">No results</td></tr>';
    return;
  }

  for (const job of jobs) {
    const tr = document.createElement('tr');
    tr.dataset.jobId = job.jobId;

    // Title + inline link
    const titleTd = document.createElement('td');
    titleTd.className = 'col-title';
    const titleDiv = document.createElement('div');
    titleDiv.className = 'job-title-cell';
    titleDiv.textContent = job.jobTitle || '—';
    if (job.jobUrl) {
      const link = document.createElement('a');
      link.className = 'reed-link';
      link.href = job.jobUrl;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'View on Reed ↗';
      titleDiv.appendChild(link);
    }
    titleTd.appendChild(titleDiv);

    // Company
    const companyTd = document.createElement('td');
    companyTd.className = 'col-company';
    companyTd.textContent = job.employerName || '—';

    // Location
    const locTd = document.createElement('td');
    locTd.className = 'col-location';
    locTd.textContent = job.locationName || '—';

    // Salary
    const salaryTd = document.createElement('td');
    salaryTd.className = 'col-salary';
    salaryTd.innerHTML = formatSalary(job);

    // Job type badge
    const typeTd = document.createElement('td');
    typeTd.className = 'col-type';
    typeTd.innerHTML = formatJobTypeBadge(job);

    // Posted date
    const postedTd = document.createElement('td');
    postedTd.className = 'col-posted';
    postedTd.textContent = job.date || '—';

    // Applications
    const appsTd = document.createElement('td');
    appsTd.className = 'col-apps';
    const apps = job.applications;
    appsTd.textContent = (apps != null) ? (apps >= 1000 ? (apps / 1000).toFixed(1) + 'k' : apps) : '—';

    // External link icon
    const linkTd = document.createElement('td');
    linkTd.className = 'col-link';
    if (job.jobUrl) {
      const icon = document.createElement('a');
      icon.className = 'ext-link';
      icon.href = job.jobUrl;
      icon.target = '_blank';
      icon.rel = 'noopener noreferrer';
      icon.textContent = '↗';
      icon.title = 'View on Reed.co.uk';
      linkTd.appendChild(icon);
    }

    tr.appendChild(titleTd);
    tr.appendChild(companyTd);
    tr.appendChild(locTd);
    tr.appendChild(salaryTd);
    tr.appendChild(typeTd);
    tr.appendChild(postedTd);
    tr.appendChild(appsTd);
    tr.appendChild(linkTd);

    tr.addEventListener('click', (e) => {
      // Don't trigger if clicking the direct link icon
      if (e.target.tagName === 'A' && e.target.classList.contains('ext-link')) return;
      selectJob(job);
    });

    tbody.appendChild(tr);
  }
}

// ── Salary formatter ──────────────────────────────────────────────────────────
function formatSalary(job) {
  const min = job.minimumSalary;
  const max = job.maximumSalary;
  if (!min && !max) return '<span class="no-salary">Not specified</span>';
  const fmt = (n) => n != null ? '£' + Number(n).toLocaleString() : '';
  if (min && max) return `<span class="salary-range">${fmt(min)} – ${fmt(max)}</span>`;
  if (min) return `<span class="salary-range">From ${fmt(min)}</span>`;
  return `<span class="salary-range">Up to ${fmt(max)}</span>`;
}

// ── Job type badge ───────────────────────────────────────────────────────────
function formatJobTypeBadge(job) {
  const badges = [];
  const ct = (job.contractType || '').toLowerCase();
  if (ct === 'permanent') badges.push('<span class="job-type-badge badge-perm">Permanent</span>');
  else if (ct === 'contract') badges.push('<span class="job-type-badge badge-contract">Contract</span>');
  else if (ct === 'temporary') badges.push('<span class="job-type-badge badge-temp">Temp</span>');
  if (job.partTime) badges.push('<span class="job-type-badge badge-parttime">Part-Time</span>');
  if (job.fullTime) badges.push('<span class="job-type-badge badge-fulltime">Full-Time</span>');
  return badges.length ? badges.join(' ') : '<span class="no-salary">—</span>';
}

// ── Job detail ───────────────────────────────────────────────────────────────
async function selectJob(job) {
  window._selectedJob = job;

  // Highlight row
  document.querySelectorAll('#reed-tbody tr').forEach((tr) => {
    tr.classList.toggle('selected', String(tr.dataset.jobId) === String(job.jobId));
  });

  const panel = document.getElementById('detail-panel');
  const titleEl = document.getElementById('d-title');
  const metaEl = document.getElementById('d-meta');
  const bodyEl = document.getElementById('d-body');
  const applyLink = document.getElementById('d-apply-link');

  panel.classList.remove('hidden');
  titleEl.textContent = job.jobTitle || '—';

  const salaryStr = formatDetailSalary(job);
  const metaItems = [
    job.employerName ? `<span class="meta-item"><strong>${escHtml(job.employerName)}</strong></span>` : '',
    job.locationName ? `<span class="meta-item">📍 ${escHtml(job.locationName)}</span>` : '',
    salaryStr ? `<span class="meta-item detail-salary">${salaryStr}</span>` : '',
    job.date ? `<span class="meta-item">📅 ${escHtml(job.date)}</span>` : '',
    job.expirationDate ? `<span class="meta-item">⏰ Closes ${escHtml(job.expirationDate)}</span>` : '',
  ].filter(Boolean);
  metaEl.innerHTML = metaItems.join('');

  applyLink.href = job.jobUrl || job.externalUrl || '#';
  applyLink.style.display = (job.jobUrl || job.externalUrl) ? '' : 'none';

  bodyEl.innerHTML = '<p><span class="reed-spinner"></span>Loading full details…</p>';

  try {
    const fullJob = await getJobDetail(job.jobId);
    window._selectedJob = fullJob;
    renderDetailContent(fullJob);
  } catch (err) {
    bodyEl.innerHTML = `<p style="color:var(--danger);font-size:0.85rem;">Failed to load: ${escHtml(err.message)}</p>`;
    renderDetailContent(job); // show what we have
  }
}

function renderDetailContent(job) {
  const bodyEl = document.getElementById('d-body');
  const tab = window._currentDetailTab || 'desc';

  if (tab === 'info') {
    bodyEl.innerHTML = renderJobInfoPanel(job);
  } else {
    bodyEl.innerHTML = renderJobDescription(job);
  }
}

window._currentDetailTab = 'desc';
window.switchDetailTab = function(tab) {
  window._currentDetailTab = tab;
  document.querySelectorAll('.detail-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === tab);
  });
  const job = window._selectedJob;
  if (job) renderDetailContent(job);
};

function renderJobDescription(job) {
  let html = '';
  const desc = job.jobDescription || '';

  if (desc) {
    html += `<h4>Job Description</h4>`;
    // If HTML content, trust it; otherwise escape
    html += desc.includes('<') ? desc : escHtml(desc).replace(/\n\n/g, '</p><p>').replace(/\n/g, '<br>');
  }

  if (job.applicationCount != null || job.applications != null) {
    const count = job.applicationCount ?? job.applications;
    html += `<h4>Applications</h4>`;
    html += `<p><span class="app-count">${count.toLocaleString()}</span> application${count !== 1 ? 's' : ''} so far</p>`;
  }

  if (job.externalUrl) {
    html += `<h4>External Application</h4>`;
    html += `<p><a href="${escHtml(job.externalUrl)}" target="_blank" rel="noopener" style="color:var(--accent);">→ Apply on company site ↗</a></p>`;
  }

  return html || '<p style="color:var(--muted);">No description available for this job.</p>';
}

function renderJobInfoPanel(job) {
  const fmt = (n) => n != null ? '£' + Number(n).toLocaleString() : '—';
  const min = job.minimumSalary ?? job.yearlyMinimumSalary;
  const max = job.maximumSalary ?? job.yearlyMaximumSalary;
  const salaryType = job.salaryType ? `per ${job.salaryType.replace('per ', '')}` : '';

  const rows = [
    ['Job ID', job.jobId],
    ['Employer', job.employerName],
    ['Location', job.locationName],
    ['Contract Type', job.contractType || '—'],
    ['Job Type', job.fullTime ? 'Full-Time' : job.partTime ? 'Part-Time' : '—'],
    ['Salary Min', min ? fmt(min) : '—'],
    ['Salary Max', max ? fmt(max) : '—'],
    ['Salary Type', salaryType],
    ['Currency', job.currency || '—'],
    ['Applications', (job.applicationCount ?? job.applications)?.toLocaleString() ?? '—'],
    ['Posted', job.date || '—'],
    ['Expires', job.expirationDate || '—'],
    [' reed.co.uk URL', job.jobUrl ? `<a href="${escHtml(job.jobUrl)}" target="_blank" rel="noopener" style="color:var(--accent);">Open ↗</a>` : '—'],
    ['External URL', job.externalUrl ? `<a href="${escHtml(job.externalUrl)}" target="_blank" rel="noopener" style="color:var(--accent);">External site ↗</a>` : '—'],
  ];

  let html = '<h4>Job Information</h4>';
  html += '<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">';
  for (const [label, value] of rows) {
    html += `<tr style="border-bottom:1px solid var(--border);">`;
    html += `<td style="padding:8px 0;color:var(--muted);width:120px;font-size:0.78rem;">${escHtml(label)}</td>`;
    html += `<td style="padding:8px 0;color:var(--text);">${value}</td>`;
    html += `</tr>`;
  }
  html += '</table>';
  return html;
}

async function getJobDetail(jobId) {
  const cached = lastResults.find((j) => String(j.jobId) === String(jobId));
  if (cached) return cached;
  return reedCall(`/jobs/${jobId}`);
}

window.closeDetail = function() {
  const panel = document.getElementById('detail-panel');
  if (panel) panel.classList.add('hidden');
  document.querySelectorAll('#reed-tbody tr').forEach(r => r.classList.remove('selected'));
  window._selectedJob = null;
};

function formatDetailSalary(job) {
  const min = job.minimumSalary ?? job.yearlyMinimumSalary;
  const max = job.maximumSalary ?? job.yearlyMaximumSalary;
  if (!min && !max) return '';
  const fmt = (n) => n != null ? '£' + Number(n).toLocaleString() : '';
  const period = job.salaryType ? ` / ${job.salaryType}` : '';
  if (min && max) return `${fmt(min)} – ${fmt(max)}${period}`;
  if (min) return `From ${fmt(min)}${period}`;
  return `Up to ${fmt(max)}${period}`;
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
