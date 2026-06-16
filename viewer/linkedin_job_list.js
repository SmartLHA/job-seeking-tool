const JOBS = [
  {
    id: 1,
    title: 'Business Analyst',
    company: 'HSBC',
    location: 'London',
    salaryLabel: null,
    postedDays: 2,
    workMode: 'Hybrid',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-vallum-associates-4402297784',
    summary: 'Map target-state processes for digital banking programmes and drive requirements through delivery squads.',
    skills: ['Agile', 'Stakeholder management', 'Payments']
  },
  {
    id: 2,
    title: 'Senior Business Analyst',
    company: 'Barclays',
    location: 'Glasgow',
    salaryLabel: null,
    postedDays: 5,
    workMode: 'Hybrid',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-hsbc-4404448527',
    summary: 'Lead discovery and requirements decomposition for a complex transformation portfolio across operations and risk.',
    skills: ['Operating model design', 'Workshops', 'Finance']
  },
  {
    id: 3,
    title: 'Digital Business Analyst',
    company: 'Monzo',
    location: 'Remote (UK)',
    salaryLabel: null,
    postedDays: 1,
    workMode: 'Remote',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-endava-4397218558',
    summary: 'Shape product change for customer journeys, define measurable outcomes, and partner with design and data teams.',
    skills: ['Product discovery', 'SQL', 'Experimentation']
  },
  {
    id: 4,
    title: 'Technical Business Analyst',
    company: 'Capgemini',
    location: 'Manchester',
    salaryLabel: null,
    postedDays: 7,
    workMode: 'Hybrid',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-alpha-bank-london-4404177718',
    summary: 'Translate technical constraints into business-friendly options for cloud migration and data integration projects.',
    skills: ['API mapping', 'Azure', 'User stories']
  },
  {
    id: 5,
    title: 'Business Process Analyst',
    company: 'BP',
    location: 'Sunbury-on-Thames',
    salaryLabel: null,
    postedDays: 11,
    workMode: 'On-site',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-liberty-towers-4399945938',
    summary: 'Document current-state workflows and identify automation opportunities across operational teams.',
    skills: ['Process mapping', 'Lean', 'Continuous improvement']
  },
  {
    id: 6,
    title: 'Lead BA - Data & Reporting',
    company: 'Lloyds Banking Group',
    location: 'Leeds',
    salaryLabel: null,
    postedDays: 3,
    workMode: 'Hybrid',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-sanderson-4402942041',
    summary: 'Own data requirements, KPI definitions, and governance processes for enterprise reporting change.',
    skills: ['Data modelling', 'Regulatory reporting', 'Jira']
  },
  {
    id: 7,
    title: 'Junior Business Analyst',
    company: 'Aviva',
    location: 'Norwich',
    salaryLabel: null,
    postedDays: 9,
    workMode: 'Hybrid',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-work-force-nexus-4390789875',
    summary: 'Support senior analysts with documentation, backlog refinement, and stakeholder notes for insurance change projects.',
    skills: ['Documentation', 'Excel', 'Communication']
  },
  {
    id: 8,
    title: 'Contract Business Analyst',
    company: 'Deloitte',
    location: 'London',
    salaryLabel: null,
    postedDays: 4,
    workMode: 'Hybrid',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-solirius-reply-4384852278',
    summary: 'Deliver rapid discovery and future-state process design for a public sector service redesign programme.',
    skills: ['Consulting', 'Discovery', 'Public sector']
  },
  {
    id: 9,
    title: 'Business Analyst - CRM',
    company: 'Salesforce',
    location: 'Reading',
    salaryLabel: null,
    postedDays: 6,
    workMode: 'Remote',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-main-capital-partners-4404555969',
    summary: 'Gather customer requirements, model CRM workflows, and coordinate delivery with platform specialists.',
    skills: ['CRM', 'Backlog management', 'SaaS']
  },
  {
    id: 10,
    title: 'Operations Business Analyst',
    company: 'NatWest',
    location: 'Edinburgh',
    salaryLabel: null,
    postedDays: 12,
    workMode: 'Hybrid',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-city-of-london-police-4405362331',
    summary: 'Drive process improvement across operations, controls, and service metrics in a regulated environment.',
    skills: ['Operations', 'Risk', 'Service design']
  },
  {
    id: 11,
    title: 'Business Analyst - E-commerce',
    company: 'ASOS',
    location: 'London',
    salaryLabel: null,
    postedDays: 8,
    workMode: 'Hybrid',
    link: 'https://uk.linkedin.com/jobs/view/business-group-analyst-at-lazard-asset-management-4403715913',
    summary: 'Partner with merchandising and engineering teams to streamline checkout, fulfilment, and stock workflows.',
    skills: ['E-commerce', 'Customer journeys', 'KPI tracking']
  },
  {
    id: 12,
    title: 'Business Systems Analyst',
    company: 'Amazon',
    location: 'Cambridge',
    salaryLabel: null,
    postedDays: 2,
    workMode: 'On-site',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-tripadvisor-4394703167',
    summary: 'Define system requirements and workflow metrics for logistics tooling used by cross-functional operational teams.',
    skills: ['Systems analysis', 'Metrics', 'Stakeholder alignment']
  },
  {
    id: 13,
    title: 'Product Analyst',
    company: 'Revolut',
    location: 'London',
    salaryLabel: null,
    postedDays: 1,
    workMode: 'Hybrid',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-tata-consultancy-services-4403985383',
    summary: 'Use data and qualitative insight to refine roadmap priorities and customer lifecycle improvements.',
    skills: ['SQL', 'Product analytics', 'A/B testing']
  },
  {
    id: 14,
    title: 'Business Analyst - Healthcare',
    company: 'NHS Digital',
    location: 'Leeds',
    salaryLabel: null,
    postedDays: 10,
    workMode: 'Remote',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-brown-brown-uk-4401737328',
    summary: 'Support digital health services with clear requirements, process redesign, and accessible service improvements.',
    skills: ['Healthcare', 'Service design', 'Accessibility']
  },
  {
    id: 15,
    title: 'Transformation Analyst',
    company: 'EY',
    location: 'Birmingham',
    salaryLabel: null,
    postedDays: 14,
    workMode: 'Hybrid',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-digital-gurus-4396460548',
    summary: 'Support transformation engagements with business case analysis, stakeholder interviews, and process redesign.',
    skills: ['Transformation', 'Business cases', 'Facilitation']
  },
  {
    id: 16,
    title: 'Business Analyst - Fintech',
    company: 'Wise',
    location: 'Shoreditch, London',
    salaryLabel: null,
    postedDays: 3,
    workMode: 'Hybrid',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-the-british-museum-4406511472',
    summary: 'Help scale international payments products by clarifying workflow gaps and operational requirements.',
    skills: ['Payments', 'Cross-border', 'Discovery']
  },
  {
    id: 17,
    title: 'Business Analyst - Insurance Change',
    company: 'Legal & General',
    location: 'Hove',
    salaryLabel: null,
    postedDays: 6,
    workMode: 'Hybrid',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-atrium-4398819801',
    summary: 'Own requirements quality for policy administration enhancements and service operations change.',
    skills: ['Insurance', 'Requirements', 'Process improvement']
  },
  {
    id: 18,
    title: 'Remote Business Analyst',
    company: 'Octopus Energy',
    location: 'Remote (UK)',
    salaryLabel: null,
    postedDays: 5,
    workMode: 'Remote',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-legatics-4391159848',
    summary: 'Translate service pain points into prioritised product and operational improvements for customer platforms.',
    skills: ['Operations', 'Customer service', 'Prioritisation']
  },
  {
    id: 19,
    title: 'Senior Technical BA',
    company: 'Skyscanner',
    location: 'Edinburgh',
    salaryLabel: null,
    postedDays: 7,
    workMode: 'Remote',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-at-investigo-4393299853',
    summary: 'Partner with platform engineering to define interfaces, migration sequencing, and rollout requirements.',
    skills: ['Platform', 'APIs', 'Migration']
  },
  {
    id: 20,
    title: 'Business Analyst - Supply Chain',
    company: 'Tesco',
    location: 'Welwyn Garden City',
    salaryLabel: null,
    postedDays: 13,
    workMode: 'On-site',
    link: 'https://uk.linkedin.com/jobs/view/business-analyst-buy-side-target-operating-model-at-sgi-4404558345',
    summary: 'Improve planning, warehouse, and replenishment processes with clear requirements and operational insight.',
    skills: ['Supply chain', 'Forecasting', 'Process mapping']
  }
];

const state = {
  selectedJobId: null,
  isLoadingMore: false,
  nextGeneratedId: JOBS.length + 1
};

const elements = {
  keyword: document.getElementById('filter-keyword'),
  location: document.getElementById('filter-location'),
  days: document.getElementById('filter-days'),
  salaryMin: document.getElementById('filter-salary-min'),
  modeBoxes: Array.from(document.querySelectorAll('input[name="mode"]')),
  jobList: document.getElementById('job-list'),
  loadMoreBtn: document.getElementById('btn-load-more'),
  loadMoreStatus: document.getElementById('load-more-status'),
  filterSummary: document.getElementById('filter-summary'),
  clearBtn: document.getElementById('btn-clear-filters'),
  emptyState: document.getElementById('empty-state'),
  detailPanel: document.getElementById('detail-panel'),
  detailOverlay: document.getElementById('detail-overlay'),
  detailTitle: document.getElementById('detail-title'),
  detailCompany: document.getElementById('detail-company'),
  detailContent: document.getElementById('detail-content'),
  closeDetail: document.getElementById('btn-close-detail')
};

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function getSelectedModes() {
  return elements.modeBoxes.filter((box) => box.checked).map((box) => box.value);
}

function getFilters() {
  return {
    keyword: elements.keyword.value.trim().toLowerCase(),
    location: elements.location.value.trim().toLowerCase(),
    rawKeyword: elements.keyword.value.trim(),
    rawLocation: elements.location.value.trim(),
    maxDays: elements.days.value ? Number(elements.days.value) : null,
    minSalary: elements.salaryMin.value ? Number(elements.salaryMin.value) : null,
    modes: getSelectedModes()
  };
}

function updateUrlParams() {
  const filters = getFilters();
  const params = new URLSearchParams();

  if (filters.keyword) params.set('keyword', filters.keyword);
  if (filters.location) params.set('location', filters.location);
  if (filters.maxDays) params.set('days', String(filters.maxDays));
  if (filters.minSalary) params.set('salaryMin', String(filters.minSalary));
  if (filters.modes.length) params.set('mode', filters.modes.join(','));

  const query = params.toString();
  const nextUrl = query ? `${window.location.pathname}?${query}` : window.location.pathname;
  window.history.replaceState({}, '', nextUrl);
}

function loadUrlParams() {
  const params = new URLSearchParams(window.location.search);
  elements.keyword.value = params.get('keyword') || '';
  elements.location.value = params.get('location') || '';
  elements.days.value = params.get('days') || '';
  elements.salaryMin.value = params.get('salaryMin') || '';

  const modes = (params.get('mode') || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);

  elements.modeBoxes.forEach((box) => {
    box.checked = modes.includes(box.value);
  });
}

function filterJobs() {
  const filters = getFilters();

  return JOBS.filter((job) => {
    const haystack = `${job.title} ${job.company} ${job.location} ${job.summary} ${job.skills.join(' ')}`.toLowerCase();
    const keywordMatch = !filters.keyword || haystack.includes(filters.keyword);
    const locationMatch = !filters.location || job.location.toLowerCase().includes(filters.location);
    const daysMatch = !filters.maxDays || job.postedDays <= filters.maxDays;
    const salaryMatch = !filters.minSalary || job.salaryMin >= filters.minSalary;
    const modeMatch = !filters.modes.length || filters.modes.includes(job.workMode);

    return keywordMatch && locationMatch && daysMatch && salaryMatch && modeMatch;
  });
}

function formatPosted(job) {
  return `${job.postedDays} day${job.postedDays === 1 ? '' : 's'} ago`;
}

function createSkillChips(skills) {
  return skills.map((skill) => `<span class="skill-chip">${escapeHtml(skill)}</span>`).join('');
}

function normalizeSkills(skills, description) {
  if (Array.isArray(skills) && skills.length) {
    return skills.map((skill) => String(skill).trim()).filter(Boolean);
  }

  if (typeof description !== 'string' || !description.trim()) {
    return [];
  }

  return description
    .split(/[,\n•|]/)
    .map((part) => part.trim())
    .filter((part) => part && part.length <= 40)
    .slice(0, 8);
}

function normalizeFetchedJob(job) {
  const description = typeof job.description === 'string' ? job.description.trim() : '';
  const postedDays = Number(job.posted_days_ago);
  const nextId = job.id ?? `linkedin-${state.nextGeneratedId}`;

  state.nextGeneratedId += 1;

  return {
    id: nextId,
    title: job.title || 'Untitled role',
    company: job.company || 'Unknown company',
    location: job.location || 'Location not listed',
    salaryLabel: null,
    salaryMin: null,
    postedDays: Number.isFinite(postedDays) ? postedDays : 7,
    workMode: job.work_mode || 'Hybrid',
    link: job.url || '#',
    summary: description || 'No summary provided for this role yet.',
    skills: normalizeSkills(job.skills, description)
  };
}

function setLoadMoreState(isLoading, message = '', isError = false) {
  state.isLoadingMore = isLoading;
  elements.loadMoreBtn.disabled = isLoading;
  elements.loadMoreBtn.textContent = isLoading ? 'Loading...' : 'Load More Jobs';
  elements.loadMoreStatus.textContent = message;
  elements.loadMoreStatus.classList.toggle('is-error', isError);
}

function renderDetail(job) {
  if (!job) {
    state.selectedJobId = null;
    elements.detailTitle.textContent = 'Select a job';
    elements.detailCompany.textContent = 'Choose a role from the list.';
    elements.detailContent.innerHTML = '<p class="detail-placeholder">Choose a role from the list to see company, salary, work mode, and summary details.</p>';
    elements.detailPanel.classList.remove('open');
    elements.detailPanel.classList.add('is-empty');
    elements.detailPanel.setAttribute('aria-hidden', 'true');
    elements.detailOverlay.hidden = true;
    return;
  }

  state.selectedJobId = job.id;
  elements.detailTitle.textContent = job.title;
  elements.detailCompany.textContent = job.company;
  elements.detailContent.innerHTML = `
    <p class="detail-meta">${escapeHtml(job.location)} · ${escapeHtml(job.workMode)} · ${formatPosted(job)}</p>
    <div class="detail-block">
      <span class="detail-label">Salary</span>
      <p class="detail-value">${job.salaryLabel ? escapeHtml(job.salaryLabel) : 'N/A'}</p>
    </div>
    <div class="detail-block">
      <span class="detail-label">Key skills</span>
      <div class="detail-skills">${job.skills.length ? createSkillChips(job.skills) : '<p class="detail-value">No skills listed</p>'}</div>
    </div>
    <div class="detail-block">
      <span class="detail-label">Job summary</span>
      <div class="detail-description">
        <p class="detail-summary">${escapeHtml(job.summary)}</p>
        ${job.skills.length ? `<div><span class="detail-label">Full skills list</span><div class="detail-skill-list">${createSkillChips(job.skills)}</div></div>` : ''}
      </div>
    </div>
    <div class="detail-actions">
      <a class="action-link secondary" href="${job.link}" target="_blank" rel="noreferrer noopener">Open in LinkedIn</a>
      <a class="action-link primary" href="${job.link}" target="_blank" rel="noreferrer noopener">Apply on LinkedIn</a>
    </div>
  `;

  elements.detailPanel.classList.remove('is-empty');
  elements.detailPanel.classList.add('open');
  elements.detailPanel.setAttribute('aria-hidden', 'false');
  elements.detailOverlay.hidden = window.innerWidth > 1180;
}

function renderCards(jobs) {
  elements.jobList.innerHTML = jobs
    .map((job) => {
      const activeClass = job.id === state.selectedJobId ? 'is-active' : '';
      return `
        <article class="job-card ${activeClass}" data-job-id="${job.id}" tabindex="0" role="button" aria-label="Open ${escapeHtml(job.title)} at ${escapeHtml(job.company)}">
          <div class="job-card-main">
            <div class="job-card-header">
              <span class="job-company">${escapeHtml(job.company)}</span>
              <span class="job-title">${escapeHtml(job.title)}</span>
            </div>
            <div class="job-meta">${escapeHtml(job.location)} · ${escapeHtml(job.workMode)} · ${formatPosted(job)}</div>
            <div class="job-skills">${createSkillChips(job.skills.slice(0, 3))}</div>
            <div class="job-card-footer">
              <span class="job-salary">Salary: ${job.salaryLabel ? escapeHtml(job.salaryLabel) : 'N/A'}</span>
            </div>
          </div>
          <a class="job-link-icon" href="${job.link}" target="_blank" rel="noreferrer noopener" aria-label="Open ${escapeHtml(job.title)} at ${escapeHtml(job.company)} on LinkedIn">↗</a>
        </article>
      `;
    })
    .join('');

  elements.emptyState.hidden = jobs.length > 0;

  elements.jobList.querySelectorAll('.job-card').forEach((card) => {
    const id = card.dataset.jobId;
    const job = jobs.find((item) => String(item.id) === id);

    card.addEventListener('click', () => renderDetail(job));
    card.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        renderDetail(job);
      }
    });
  });

  elements.jobList.querySelectorAll('.job-link-icon').forEach((link) => {
    link.addEventListener('click', (event) => event.stopPropagation());
  });
}

function render() {
  const jobs = filterJobs();
  elements.filterSummary.textContent = `Showing ${jobs.length} role${jobs.length === 1 ? '' : 's'}`;

  if (state.selectedJobId && !jobs.some((job) => job.id === state.selectedJobId)) {
    renderDetail(null);
  }

  renderCards(jobs);
  updateUrlParams();
}

async function loadMoreJobs() {
  if (state.isLoadingMore) {
    return;
  }

  const filters = getFilters();
  const keyword = filters.rawKeyword || 'business analyst';
  const location = filters.rawLocation || 'United Kingdom';
  const workModes = filters.modes.length
    ? filters.modes.map((mode) => {
        if (mode === 'On-site') return 'onsite';
        return mode.toLowerCase();
      })
    : ['remote', 'hybrid', 'onsite'];
  const url = `/cgi-bin/linkedin_scraper.py?keyword=${encodeURIComponent(keyword)}&location=${encodeURIComponent(location)}&days=7&work_mode=${workModes.join(',')}`;

  setLoadMoreState(true, 'Fetching more jobs from LinkedIn...');

  try {
    const response = await fetch(url);

    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }

    const payload = await response.json();
    const incomingJobs = Array.isArray(payload.jobs) ? payload.jobs.map(normalizeFetchedJob) : [];
    const existingIds = new Set(JOBS.map((job) => String(job.id)));
    const uniqueJobs = incomingJobs.filter((job) => {
      const id = String(job.id);
      if (existingIds.has(id)) {
        return false;
      }
      existingIds.add(id);
      return true;
    });

    if (!uniqueJobs.length) {
      setLoadMoreState(false, 'No additional jobs were returned this time.');
      return;
    }

    JOBS.push(...uniqueJobs);
    render();
    setLoadMoreState(false, `Loaded ${uniqueJobs.length} more job${uniqueJobs.length === 1 ? '' : 's'}.`);
  } catch (error) {
    console.error('Unable to load more jobs', error);
    setLoadMoreState(false, 'Sorry, more jobs could not be loaded right now. Please try again.', true);
  }
}

function clearFilters() {
  elements.keyword.value = '';
  elements.location.value = '';
  elements.days.value = '';
  elements.salaryMin.value = '';
  elements.modeBoxes.forEach((box) => {
    box.checked = false;
  });
  render();
}

function bindEvents() {
  [elements.keyword, elements.location, elements.days, elements.salaryMin].forEach((element) => {
    element.addEventListener('input', render);
    element.addEventListener('change', render);
  });

  elements.modeBoxes.forEach((box) => box.addEventListener('change', render));
  elements.clearBtn.addEventListener('click', clearFilters);
  elements.loadMoreBtn.addEventListener('click', loadMoreJobs);
  elements.closeDetail.addEventListener('click', () => renderDetail(null));
  elements.detailOverlay.addEventListener('click', () => renderDetail(null));
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && elements.detailPanel.classList.contains('open')) {
      renderDetail(null);
    }
  });
  window.addEventListener('resize', () => {
    if (state.selectedJobId) {
      elements.detailOverlay.hidden = window.innerWidth > 1180;
    }
  });
}

loadUrlParams();
bindEvents();
render();
