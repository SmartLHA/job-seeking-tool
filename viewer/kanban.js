/**
 * Kanban Board — modern, Linear-inspired design.
 */
const API = '/api/kanban';

// ─── State ────────────────────────────────────────────────────────────────────
let board = null;
let draggedCardId = null;
let draggedFromCol = null;
let modalTags = [];
let searchQuery = '';

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadBoard();
  wireSearch();

  // Modal event handlers — must be after DOM is ready
  document.getElementById('cardModal').addEventListener('click', e => {
    if (e.target === e.currentTarget) e.currentTarget.classList.remove('open');
  });
  document.getElementById('modalClose').onclick = () => document.getElementById('cardModal').classList.remove('open');
  document.getElementById('cancelBtn').onclick = () => document.getElementById('cardModal').classList.remove('open');
  document.getElementById('deleteBtn').onclick = () => {
    const id = document.getElementById('fCardId').value;
    if (id && confirm('確定刪除？')) { deleteCard(id); closeModal(); }
  };
  document.getElementById('saveBtn').onclick = saveCard;
  document.getElementById('fTitle').addEventListener('keydown', e => {
    if (e.key === 'Enter') saveCard();
  });
  document.getElementById('priorityOptions').addEventListener('click', e => {
    const opt = e.target.closest('.priority-option');
    if (!opt) return;
    document.querySelectorAll('.priority-option').forEach(o => o.classList.remove('selected'));
    opt.classList.add('selected');
    opt.querySelector('input')?.setAttribute('checked', 'true');
  });
  document.getElementById('tagInput').addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      const val = e.target.value.trim().replace(',', '');
      if (val && !modalTags.includes(val)) {
        modalTags.push(val);
        e.target.value = '';
        renderModalTags();
      }
    }
    if (e.key === 'Backspace' && !e.target.value && modalTags.length) {
      modalTags.pop();
      renderModalTags();
    }
  });
});

async function loadBoard() {
  try {
    const resp = await fetch(API);
    if (!resp.ok) throw new Error(await resp.text());
    board = await resp.json();
    render();
    setStatus('已同步', 'saved');
  } catch (e) {
    setStatus('載入失敗: ' + e.message, 'error');
    document.getElementById('board').innerHTML = `<div class="loading-overlay" style="color:var(--red)">❌ 載入失敗: ${e.message}</div>`;
  }
}

// ─── Render ───────────────────────────────────────────────────────────────────
function render() {
  const el = document.getElementById('board');
  const query = searchQuery.toLowerCase();

  el.innerHTML = board.columns.map(col => {
    const filteredCards = col.cards.filter(c =>
      !query || c.title.toLowerCase().includes(query) ||
      (c.description || '').toLowerCase().includes(query) ||
      (c.tags || []).some(t => t.toLowerCase().includes(query))
    );

    return `
    <div class="column" data-column-id="${col.id}">
      <div class="column-header">
        <span class="column-icon">${col.id === 'backlog' ? '📥' : col.id === 'in-progress' ? '🔄' : col.id === 'blocked' ? '🚫' : '✅'}</span>
        <span class="column-title">${col.title}</span>
        <span class="column-count-badge">${col.cards.length}</span>
        <button class="column-add-btn" data-column="${col.id}" title="新增任務">+</button>
      </div>
      <div class="column-cards" data-column="${col.id}">
        ${filteredCards.length === 0
          ? `<div class="empty-column"><div class="empty-column-icon">📭</div>暫無任務</div>`
          : filteredCards.map(card => renderCard(card)).join('')
        }
      </div>
      <div class="column-footer">
        <button class="add-card-footer-btn" data-column="${col.id}">
          <span>+</span> 新增任務
        </button>
      </div>
    </div>`;
  }).join('');

  wireDragDrop();
  wireCardEvents();
  wireColumnButtons();
}

function renderCard(card) {
  const pri = card.priority || 'medium';
  const tags = (card.tags || []).map(t => `<span class="tag">${escHtml(t)}</span>`).join('');
  const link = card.link ? `<a class="card-link-chip" href="${escAttr(card.link)}" target="_blank" rel="noopener">🔗</a>` : '';

  return `
    <div class="card" draggable="true" data-card-id="${card.id}">
      <div class="card-top">
        <span class="priority-dot ${pri}" title="優先級: ${pri}"></span>
        <span class="card-title">${escHtml(card.title)}</span>
      </div>
      ${card.description ? `<div class="card-description">${escHtml(card.description)}</div>` : ''}
      ${tags || link ? `<div class="card-meta">${tags}${link}</div>` : ''}
      <div class="card-actions">
        <button class="card-action-btn copy-btn" title="複製標題" data-title="${escAttr(card.title)}" onclick="copyCardTitle(this)">📋</button>
        <button class="card-action-btn edit-btn" title="編輯">✏️</button>
        <button class="card-action-btn delete delete-btn" title="刪除">🗑️</button>
      </div>
    </div>`;
}

// ─── Drag & Drop ──────────────────────────────────────────────────────────────
function wireDragDrop() {
  document.querySelectorAll('.card[draggable]').forEach(card => {
    card.addEventListener('dragstart', e => {
      draggedCardId = card.dataset.cardId;
      draggedFromCol = card.closest('.column-cards').dataset.column;
      card.classList.add('is-dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', draggedCardId);
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('is-dragging');
      draggedCardId = null;
      draggedFromCol = null;
      document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
    });
  });

  document.querySelectorAll('.column-cards').forEach(zone => {
    zone.addEventListener('dragover', e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      zone.classList.add('drag-over');
    });
    zone.addEventListener('dragleave', e => {
      if (!zone.contains(e.relatedTarget)) zone.classList.remove('drag-over');
    });
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('drag-over');
      const toCol = zone.dataset.column;
      const cardId = e.dataTransfer.getData('text/plain') || draggedCardId;
      if (!cardId) return;

      // Find insert position
      const cards = [...zone.querySelectorAll('.card:not(.is-dragging)')];
      let toIndex = cards.length;
      for (let i = 0; i < cards.length; i++) {
        const r = cards[i].getBoundingClientRect();
        if (e.clientY < r.top + r.height / 2) { toIndex = i; break; }
      }

      // Optimistic local update for same-column moves
      if (draggedFromCol === toCol) {
        for (const c of board.columns) {
          const idx = c.cards.findIndex(x => x.id === cardId);
          if (idx !== -1) {
            const [moved] = c.cards.splice(idx, 1);
            c.cards.splice(toIndex > idx ? toIndex - 1 : toIndex, 0, moved);
            break;
          }
        }
        render();
      }

      moveCard(cardId, toCol, toIndex < cards.length ? toIndex : null);
    });
  });
}

async function moveCard(cardId, toCol, toIndex) {
  setStatus('儲存中...', 'saving');
  try {
    const resp = await fetch(API, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ action: 'move', card_id: cardId, to_column: toCol, to_index: toIndex }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    board = await resp.json();
    render();
    setStatus('已同步', 'saved');
  } catch (e) {
    setStatus('移動失敗: ' + e.message, 'error');
  }
}

// ─── Card Events ──────────────────────────────────────────────────────────────
function wireCardEvents() {
  document.querySelectorAll('.card').forEach(card => {
    card.addEventListener('click', e => {
      if (!board) return;
      if (e.target.closest('.card-action-btn') || e.target.closest('.card-link-chip')) return;
      const col = card.closest('.column-cards').dataset.column;
      const obj = findCard(card.dataset.cardId, col);
      if (obj) openModal(col, obj);
    });

    card.querySelector('.edit-btn')?.addEventListener('click', e => {
      e.stopPropagation();
      if (!board) return;
      const col = card.closest('.column-cards').dataset.column;
      const obj = findCard(card.dataset.cardId, col);
      if (obj) openModal(col, obj);
    });

    card.querySelector('.delete-btn')?.addEventListener('click', e => {
      e.stopPropagation();
      if (!board) return;
      const cardId = card.dataset.cardId;
      if (confirm('確定刪除這個任務？')) deleteCard(cardId);
    });
  });
}

function findCard(cardId, colId) {
  const col = board.columns.find(c => c.id === colId);
  return col ? col.cards.find(c => c.id === cardId) : null;
}

// ─── Column Buttons ───────────────────────────────────────────────────────────
function wireColumnButtons() {
  document.querySelectorAll('.column-add-btn, .add-card-footer-btn').forEach(btn => {
    btn.addEventListener('click', () => openModal(btn.dataset.column, null));
  });
}

// ─── Modal ────────────────────────────────────────────────────────────────────
function openModal(columnId, card) {
  const modal = document.getElementById('cardModal');
  const titleEl = document.getElementById('modalTitle');
  const fTitle = document.getElementById('fTitle');
  const fDesc = document.getElementById('fDesc');
  const fLink = document.getElementById('fLink');
  const fCardId = document.getElementById('fCardId');
  const fColumn = document.getElementById('fColumn');
  const deleteBtn = document.getElementById('deleteBtn');
  const priOptions = document.querySelectorAll('.priority-option');

  if (card) {
    titleEl.textContent = '編輯任務';
    fCardId.value = card.id;
    fColumn.value = columnId;
    fTitle.value = card.title || '';
    fDesc.value = card.description || '';
    fLink.value = card.link || '';
    modalTags = [...(card.tags || [])];

    priOptions.forEach(opt => {
      const val = opt.dataset.value;
      opt.classList.toggle('selected', val === (card.priority || 'medium'));
      opt.querySelector('input')?.setAttribute('checked', val === (card.priority || 'medium'));
    });
    deleteBtn.style.display = 'flex';
  } else {
    titleEl.textContent = '新增任務';
    fCardId.value = '';
    fColumn.value = columnId;
    fTitle.value = '';
    fDesc.value = '';
    fLink.value = '';
    modalTags = [];
    priOptions.forEach(opt => {
      const val = opt.dataset.value;
      const isMedium = val === 'medium';
      opt.classList.toggle('selected', isMedium);
      opt.querySelector('input')?.setAttribute('checked', isMedium);
    });
    deleteBtn.style.display = 'none';
  }

  renderModalTags();
  modal.classList.add('open');
  setTimeout(() => fTitle.focus(), 100);
}

function renderModalTags() {
  const area = document.getElementById('tagsArea');
  const input = document.getElementById('tagInput');
  area.querySelectorAll('.tag-edit').forEach(t => t.remove());
  modalTags.forEach((tag, i) => {
    const el = document.createElement('span');
    el.className = 'tag-edit';
    el.innerHTML = `${escHtml(tag)}<button onclick="removeModalTag(${i})">×</button>`;
    area.insertBefore(el, input);
  });
}

window.removeModalTag = function(i) {
  modalTags.splice(i, 1);
  renderModalTags();
};

function closeModal() {
  document.getElementById('cardModal').classList.remove('open');
}

async function saveCard() {
  const cardId = document.getElementById('fCardId').value;
  const columnId = document.getElementById('fColumn').value;
  const title = document.getElementById('fTitle').value.trim();
  const description = document.getElementById('fDesc').value.trim();
  const link = document.getElementById('fLink').value.trim();
  const priority = document.querySelector('.priority-option.selected')?.dataset.value || 'medium';

  if (!title) { alert('請輸入標題'); return; }

  setStatus('儲存中...', 'saving');
  try {
    const resp = await fetch(API, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        action: 'upsert',
        column_id: columnId,
        card: { id: cardId || undefined, title, description, priority, tags: [...modalTags], link },
      }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    board = await resp.json();
    render();
    closeModal();
    setStatus('已同步', 'saved');
  } catch (e) {
    setStatus('儲存失敗: ' + e.message, 'error');
  }
}

async function deleteCard(cardId) {
  setStatus('刪除中...', 'saving');
  try {
    const resp = await fetch(API, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ action: 'delete', card_id: cardId }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    board = await resp.json();
    render();
    setStatus('已同步', 'saved');
  } catch (e) {
    setStatus('刪除失敗: ' + e.message, 'error');
  }
}

// ─── Header Add Button ────────────────────────────────────────────────────────
// (addAnyBtn not in HTML — skipped)

// ─── Search ───────────────────────────────────────────────────────────────────
function wireSearch() {
  const input = document.getElementById('searchInput');
  if (!input) return;
  let timer;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      searchQuery = input.value.trim();
      render();
    }, 200);
  });
}

// ─── Status ───────────────────────────────────────────────────────────────────
function setStatus(msg, type) {
  const el = document.getElementById('statusMsg');
  if (!el) return;
  const cls = type === 'saved' ? 'status-saved' : type === 'saving' ? 'status-saving' : '';
  el.innerHTML = `<span class="status-pill ${cls}">${msg}</span>`;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
function escHtml(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function escAttr(s) { return String(s||'').replace(/"/g,'&quot;'); }
function copyCardTitle(btn) {
  const title = btn.dataset.title;
  navigator.clipboard.writeText(title).then(() => {
    btn.textContent = '✅';
    setTimeout(() => { btn.textContent = '📋'; }, 1200);
  });
}
