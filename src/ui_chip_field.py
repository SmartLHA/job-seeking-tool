"""Vanilla-JS chip/tag input widget (Slice D, 2026-07-21 search/score/filter
plan: docs/tasks/2026-07-21-search-score-filter-plan.md).

Progressive enhancement ONLY: the real ``<input name=...>`` stays in the DOM
with its normal name and comma-joined value, so a no-JS submission behaves
exactly like a plain text field always did (type comma-separated values
directly, still parsed server-side by ``ui_handlers._parse_keyword_terms`` /
``_parse_exclude_terms``). When JS runs, ``CHIP_FIELD_JS`` hides the real
input and renders removable "chip" pills built from its current
comma-separated value, plus a small text box to add more. Every add/remove
re-writes the comma-joined string back into the real (still name-carrying,
just hidden) input, so that hidden field is exactly what gets submitted —
chips are never a second, separate field.
"""
from __future__ import annotations

from src.ui_utils import escape


def render_chip_field(
    *,
    name: str,
    label: str,
    value: str,
    placeholder: str = "",
    max_chips: int | None = None,
    help_text: str = "",
) -> str:
    """Render one chip-capable field. `name`/`value` land on the real input
    exactly as a plain `<input>` would, so this is a drop-in replacement —
    server-side parsing of the submitted field is unchanged."""
    max_attr = f' data-chip-max="{int(max_chips)}"' if max_chips else ""
    help_html = (
        f' <small style="color:var(--ink-faint);font-weight:400;">{escape(help_text)}</small>'
        if help_text
        else ""
    )
    return (
        f'<label class="chip-field"{max_attr}>'
        f"<span>{escape(label)}{help_html}</span>"
        f'<input name="{escape(name)}" value="{escape(value)}" '
        f'placeholder="{escape(placeholder)}" class="chip-real-input">'
        f"</label>"
    )


# Kept as one shared <script> block (like _multiselect.py's MULTISELECT_JS)
# so it only needs embedding once per page regardless of how many chip
# fields are on it. querySelectorAll + per-field init is idempotent.
CHIP_FIELD_JS = (
    "<script>"
    "(function(){"
    "function splitChips(v){"
    "return (v||'').split(',').map(function(s){return s.trim();}).filter(Boolean);"
    "}"
    "function initField(field){"
    "var real=field.querySelector('.chip-real-input');"
    "if(!real||real.dataset.chipInit)return;"
    "real.dataset.chipInit='1';"
    "var maxAttr=field.getAttribute('data-chip-max');"
    "var max=maxAttr?parseInt(maxAttr,10):0;"
    "var chips=splitChips(real.value);"
    "real.style.display='none';"
    "var box=document.createElement('div');"
    "box.className='chip-box';"
    "box.style.cssText='display:flex;flex-wrap:wrap;gap:6px;align-items:center;"
    "border:1px solid var(--line);border-radius:var(--r-md);padding:6px 8px;"
    "background:var(--surface);cursor:text;';"
    "var entry=document.createElement('input');"
    "entry.type='text';"
    "entry.placeholder=real.placeholder||'';"
    "entry.style.cssText='border:none;outline:none;flex:1;min-width:80px;"
    "font:inherit;background:transparent;';"
    "function sync(){real.value=chips.join(', ');}"
    "function render(){"
    "box.innerHTML='';"
    "chips.forEach(function(chip,idx){"
    "var pill=document.createElement('span');"
    "pill.textContent=chip;"
    "pill.style.cssText='display:inline-flex;align-items:center;gap:4px;"
    "background:var(--surface-sunk);border:1px solid var(--line);"
    "border-radius:100px;padding:2px 8px;font-size:12.5px;';"
    "var rm=document.createElement('button');"
    "rm.type='button';rm.textContent='\\u00d7';rm.setAttribute('aria-label','Remove');"
    "rm.style.cssText='border:none;background:transparent;cursor:pointer;"
    "font-size:13px;line-height:1;padding:0;';"
    "rm.addEventListener('click',function(){chips.splice(idx,1);sync();render();});"
    "pill.appendChild(rm);"
    "box.appendChild(pill);"
    "});"
    "box.appendChild(entry);"
    "sync();"
    "}"
    "function addChip(text){"
    "var t=text.trim();if(!t)return;"
    "if(max&&max===1){chips=[t];}"
    "else if(max&&chips.length>=max){/* at cap: ignore silently, cap is enforced server-side too */}"
    "else if(chips.indexOf(t)===-1){chips.push(t);}"
    "entry.value='';render();entry.focus();"
    "}"
    "entry.addEventListener('keydown',function(e){"
    "if(e.key===','||e.key==='Enter'){e.preventDefault();addChip(entry.value);}"
    "else if(e.key==='Backspace'&&!entry.value&&chips.length){chips.pop();sync();render();}"
    "});"
    "entry.addEventListener('blur',function(){if(entry.value.trim())addChip(entry.value);});"
    "box.addEventListener('click',function(e){if(e.target===box)entry.focus();});"
    "field.appendChild(box);"
    "render();"
    "}"
    "document.querySelectorAll('.chip-field').forEach(initField);"
    "})();"
    "</script>"
)
