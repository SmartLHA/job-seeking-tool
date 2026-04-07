const HOME_PATH = '__dashboard__';
const BASE_PATH = window.location.pathname.replace(/\/viewer\/?$/, '') || '';
const MANIFEST_PATH = `${window.location.pathname.replace(/\/?$/, '/') }documents.json`;

function withBase(path) {
  return `${BASE_PATH}${path}`;
}

let docs = [];

const docSelect = document.getElementById('doc-select');
const docList = document.getElementById('doc-list');
const docTitle = document.getElementById('doc-title');
const docPath = document.getElementById('doc-path');
const viewer = document.getElementById('viewer');
const statusEl = document.getElementById('status');
const refreshBtn = document.getElementById('refresh-btn');
const searchInput = document.getElementById('search-input');

const docCache = new Map();
let currentFilter = '';

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.className = isError ? 'status error' : 'status';
}

function stripMarkdown(text) {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/^[-*]\s+/gm, '')
    .replace(/^\d+\.\s+/gm, '')
    .replace(/\n+/g, ' ')
    .trim();
}

function extractBulletItems(markdown) {
  return markdown
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => /^[-*]\s+/.test(line))
    .map((line) => stripMarkdown(line.replace(/^[-*]\s+/, '').trim()));
}

function toSentenceList(text, limit = 3) {
  return stripMarkdown(text)
    .split(/(?<=[.!?])\s+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, limit);
}

function summarizeItems(items, limit = 3) {
  return items
    .map((item) => stripMarkdown(item))
    .filter(Boolean)
    .slice(0, limit);
}

function renderSummaryList(items) {
  const safeItems = items.filter(Boolean);
  if (!safeItems.length) {
    return '<p class="summary-empty">Nothing captured yet.</p>';
  }
  return `<ul class="summary-list">${safeItems.map((item) => `<li>${item}</li>`).join('')}</ul>`;
}

function extractSection(markdown, heading) {
  const escapedHeading = heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // Match heading line + blank line, then capture until the next ## heading line
  // Using (?=^##\\s+) lookahead (no $) avoids multiline-$ stopping the non-greedy match early
  const regex = new RegExp(`^##\\s+${escapedHeading}\\s*\\n\\n([\\s\\S]*?)(?=^##\\s+)`, 'm');
  const match = markdown.match(regex);
  return match ? match[1].trim() : '';
}

function extractNumberedItems(markdown) {
  return markdown
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => /^\d+\.\s+/.test(line))
    .map((line) => line.replace(/^\d+\.\s+/, '').trim());
}

function buildDashboardSummary() {
  const context = docCache.get('/PROJECT_CONTEXT.md') || '';
  const log = docCache.get('/PROJECT_LOG.md') || '';

  const latestProgressItems = summarizeItems(extractBulletItems(extractSection(context, 'Latest Milestone')));
  const confirmedItems = summarizeItems(extractBulletItems(extractSection(context, 'Confirmed So Far')));
  const pendingItems = summarizeItems(extractNumberedItems(extractSection(context, 'Still Ambiguous / Pending Confirmation')));
  const nextActionItems = summarizeItems(
    extractNumberedItems(extractSection(context, 'Next Recommended Step')).length
      ? extractNumberedItems(extractSection(context, 'Next Recommended Step'))
      : toSentenceList(extractSection(context, 'Next Recommended Step')),
    4
  );
  const discussionItems = summarizeItems(extractBulletItems(extractSection(log, 'What was discussed')));

  return {
    latestDevelopmentActionDone: latestProgressItems.length
      ? latestProgressItems
      : toSentenceList(extractSection(context, 'Latest Progress')),
    latestDiscussionOutcome: confirmedItems.length
      ? confirmedItems
      : discussionItems.length
        ? discussionItems
        : ['No latest discussion outcome captured yet.'],
    outstandingQuestion: pendingItems.length
      ? pendingItems
      : ['No outstanding question recorded yet.'],
    nextAction: nextActionItems.length
      ? nextActionItems
      : ['No next step recorded yet.'],
  };
}

function getFilteredDocs() {
  const query = currentFilter.trim().toLowerCase();
  if (!query) return docs;

  return docs.filter((doc) => {
    const cached = docCache.get(doc.path) || '';
    const haystack = `${doc.label}\n${doc.summary}\n${doc.category}\n${cached}`.toLowerCase();
    return haystack.includes(query);
  });
}

function groupDocsByCategory(items) {
  const groups = new Map();
  for (const doc of items) {
    if (!groups.has(doc.category)) groups.set(doc.category, []);
    groups.get(doc.category).push(doc);
  }
  return [...groups.entries()];
}

function renderDashboard(filteredDocs) {
  const dashboardSummary = buildDashboardSummary();
  const groupedDocs = groupDocsByCategory(filteredDocs);
  const cardsHtml = groupedDocs
    .map(([category, items]) => `
      <section class="dashboard-group">
        <div class="dashboard-group-header">
          <p class="eyebrow">${category}</p>
          <h3>${category}</h3>
          <p>${items.length} document(s)</p>
        </div>
        <div class="dashboard-grid">
          ${items
            .map(
              (doc) => `
                <button type="button" class="dashboard-card" data-doc-path="${doc.path}">
                  <span class="doc-card-topline">${doc.category}</span>
                  <span class="doc-card-title">${doc.label}</span>
                  <span class="doc-card-summary">${doc.summary}</span>
                </button>
              `
            )
            .join('')}
        </div>
      </section>
    `)
    .join('');

  viewer.innerHTML = `
    <section class="dashboard-hero">
      <p class="eyebrow">Dashboard</p>
      <h1>Project document overview</h1>
      <p>Browse the main project memory, planning docs, and progress log from one place.</p>
    </section>

    <section class="dashboard-summary-grid">
      <article class="summary-card">
        <p class="summary-label">Latest development action done</p>
        ${renderSummaryList(dashboardSummary.latestDevelopmentActionDone)}
      </article>
      <article class="summary-card">
        <p class="summary-label">Latest discussion outcome</p>
        ${renderSummaryList(dashboardSummary.latestDiscussionOutcome)}
      </article>
      <article class="summary-card">
        <p class="summary-label">Outstanding question</p>
        ${renderSummaryList(dashboardSummary.outstandingQuestion)}
      </article>
      <article class="summary-card">
        <p class="summary-label">Next action</p>
        ${renderSummaryList(dashboardSummary.nextAction)}
      </article>
    </section>

    ${cardsHtml || '<p class="search-meta">No documents match your current search.</p>'}
  `;

  viewer.querySelectorAll('[data-doc-path]').forEach((button) => {
    button.addEventListener('click', () => loadDoc(button.dataset.docPath));
  });
}

function renderMenu(activePath) {
  const filteredDocs = getFilteredDocs();
  docSelect.innerHTML = '';
  docList.innerHTML = '';

  const homeOption = document.createElement('option');
  homeOption.value = HOME_PATH;
  homeOption.textContent = 'Dashboard';
  if (activePath === HOME_PATH) homeOption.selected = true;
  docSelect.appendChild(homeOption);

  filteredDocs.forEach((doc) => {
    const option = document.createElement('option');
    option.value = doc.path;
    option.textContent = `${doc.category} · ${doc.label}`;
    if (doc.path === activePath) option.selected = true;
    docSelect.appendChild(option);
  });

  if (!filteredDocs.length) {
    docList.innerHTML = '<p class="search-meta">No documents match your search yet.</p>';
    return;
  }

  for (const [category, items] of groupDocsByCategory(filteredDocs)) {
    const section = document.createElement('section');
    section.className = 'doc-category';

    const heading = document.createElement('p');
    heading.className = 'doc-category-title';
    heading.textContent = category;
    section.appendChild(heading);

    for (const doc of items) {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = `doc-link${doc.path === activePath ? ' active' : ''}`;
      card.addEventListener('click', () => loadDoc(doc.path));
      card.innerHTML = `
        <span class="doc-card-topline">${doc.category}</span>
        <span class="doc-card-title">${doc.label}</span>
        <span class="doc-card-summary">${doc.summary}</span>
      `;
      section.appendChild(card);
    }

    docList.appendChild(section);
  }
}

async function fetchDocText(doc) {
  const response = await fetch(withBase(doc.path) + '?t=' + Date.now(), { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const markdown = await response.text();
  docCache.set(doc.path, markdown);
  return markdown;
}

async function fetchManifest() {
  const response = await fetch(MANIFEST_PATH + '?t=' + Date.now(), { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const data = await response.json();
  if (!Array.isArray(data)) {
    throw new Error('Manifest is not an array');
  }
  docs = data;
}

async function prefetchDocs() {
  await Promise.all(
    docs.map(async (doc) => {
      try {
        await fetchDocText(doc);
      } catch {
        // best-effort cache warmup; actual load errors are shown later
      }
    })
  );
}

async function loadDoc(path) {
  const availableDocs = getFilteredDocs();

  if (path === HOME_PATH) {
    renderMenu(HOME_PATH);
    docTitle.textContent = 'Dashboard';
    docPath.textContent = 'Overview of available project documents';
    renderDashboard(availableDocs);
    const matchCount = currentFilter.trim() ? `${availableDocs.length} matching document(s). ` : '';
    setStatus(`${matchCount}Showing dashboard`);
    const url = new URL(window.location.href);
    url.searchParams.set('doc', HOME_PATH);
    window.history.replaceState({}, '', url);
    return;
  }

  const doc = docs.find((item) => item.path === path) || availableDocs[0] || docs[0];
  renderMenu(doc.path);
  docTitle.textContent = doc.label;
  docPath.textContent = doc.path;
  setStatus(`Loading ${doc.label}...`);

  try {
    const markdown = await fetchDocText(doc);
    viewer.innerHTML = markdownToHtml(markdown);
    const matchCount = currentFilter.trim() ? `${availableDocs.length} matching document(s). ` : '';
    setStatus(`${matchCount}Showing ${doc.label}`);
    const url = new URL(window.location.href);
    url.searchParams.set('doc', doc.path);
    window.history.replaceState({}, '', url);
  } catch (error) {
    viewer.innerHTML = '';
    setStatus(`Failed to load ${doc.label}: ${error.message}`, true);
  }
}

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function inlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

function markdownToHtml(markdown) {
  const lines = markdown.replace(/\r/g, '').split('\n');
  const html = [];
  let inList = false;
  let listType = 'ul';
  let inCode = false;
  let codeBuffer = [];
  let inBlockquote = false;

  const closeList = () => {
    if (inList) {
      html.push(`</${listType}>`);
      inList = false;
      listType = 'ul';
    }
  };

  const closeBlockquote = () => {
    if (inBlockquote) {
      html.push('</blockquote>');
      inBlockquote = false;
    }
  };

  for (const line of lines) {
    if (line.startsWith('```')) {
      closeList();
      closeBlockquote();
      if (!inCode) {
        inCode = true;
        codeBuffer = [];
      } else {
        html.push(`<pre><code>${escapeHtml(codeBuffer.join('\n'))}</code></pre>`);
        inCode = false;
        codeBuffer = [];
      }
      continue;
    }

    if (inCode) {
      codeBuffer.push(line);
      continue;
    }

    if (!line.trim()) {
      closeList();
      closeBlockquote();
      continue;
    }

    if (/^#{1,6}\s/.test(line)) {
      closeList();
      closeBlockquote();
      const level = line.match(/^#+/)[0].length;
      const text = line.replace(/^#{1,6}\s*/, '');
      html.push(`<h${level}>${inlineMarkdown(text)}</h${level}>`);
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      closeBlockquote();
      if (!inList || listType !== 'ul') {
        closeList();
        html.push('<ul>');
        inList = true;
        listType = 'ul';
      }
      html.push(`<li>${inlineMarkdown(line.replace(/^[-*]\s+/, ''))}</li>`);
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      closeBlockquote();
      if (!inList || listType !== 'ol') {
        closeList();
        html.push('<ol>');
        inList = true;
        listType = 'ol';
      }
      html.push(`<li>${inlineMarkdown(line.replace(/^\d+\.\s+/, ''))}</li>`);
      continue;
    }

    if (/^>\s?/.test(line)) {
      closeList();
      if (!inBlockquote) {
        html.push('<blockquote>');
        inBlockquote = true;
      }
      html.push(`<p>${inlineMarkdown(line.replace(/^>\s?/, ''))}</p>`);
      continue;
    }

    closeList();
    closeBlockquote();
    html.push(`<p>${inlineMarkdown(line)}</p>`);
  }

  closeList();
  closeBlockquote();

  if (inCode) {
    html.push(`<pre><code>${escapeHtml(codeBuffer.join('\n'))}</code></pre>`);
  }

  return html.join('\n');
}

docSelect.addEventListener('change', (event) => {
  loadDoc(event.target.value);
});

refreshBtn.addEventListener('click', async () => {
  docCache.clear();
  await fetchManifest();
  await prefetchDocs();
  const current = new URL(window.location.href).searchParams.get('doc') || HOME_PATH;
  loadDoc(current);
});

searchInput.addEventListener('input', () => {
  currentFilter = searchInput.value;
  const current = new URL(window.location.href).searchParams.get('doc') || HOME_PATH;
  const filtered = getFilteredDocs();
  const nextDoc = current === HOME_PATH || filtered.some((doc) => doc.path === current)
    ? current
    : filtered[0]?.path || HOME_PATH;
  renderMenu(nextDoc);
  if (filtered.length || nextDoc === HOME_PATH) {
    loadDoc(nextDoc);
  } else {
    docTitle.textContent = 'No matching document';
    docPath.textContent = '';
    viewer.innerHTML = '';
    setStatus('No documents match your current search.', true);
  }
});

const initialDoc = new URL(window.location.href).searchParams.get('doc') || HOME_PATH;
setStatus('Loading manifest...');
fetchManifest()
  .then(() => {
    renderMenu(initialDoc);
    return prefetchDocs();
  })
  .then(() => loadDoc(initialDoc))
  .catch((error) => {
    viewer.innerHTML = '';
    setStatus(`Failed to load documents manifest: ${error.message}`, true);
  });

// Fetch session usage from the combined viewer+usage server
function fetchUsage() {
  const usageEl = document.getElementById('usage-text');
  if (!usageEl) return;
  fetch('/usage', { cache: 'no-store' })
    .then((r) => r.json())
    .then((data) => {
      if (!data.ok) {
        usageEl.textContent = 'Usage: unavailable';
        return;
      }
      const parts = [];
      if (data.tokens_in) parts.push(`${data.tokens_in} in`);
      if (data.tokens_out) parts.push(`${data.tokens_out} out`);
      if (data.context_pct != null) parts.push(`${data.context_pct}% ctx`);
      if (data.cost_usd != null) parts.push(`$${data.cost_usd}`);
      if (data.run_count != null) parts.push(`${data.run_count} runs`);
      if (data.model) parts.push(data.model);
      usageEl.textContent = parts.length ? `Usage: ${parts.join(' · ')}` : 'Usage: no session data';
    })
    .catch(() => {
      usageEl.textContent = 'Usage: offline';
    });
}

fetchUsage();
setInterval(fetchUsage, 60000); // refresh every minute
