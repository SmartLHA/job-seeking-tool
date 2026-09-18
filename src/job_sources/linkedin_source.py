"""LinkedIn job source adapter.

Best-effort scraper of LinkedIn's public job-search page. No API key required.
See also: src/job_sources/adzuna_source.py (simpler reference model) and
src/job_sources/source_registry.py (interface contract).

# TODO (v2): Cookie-based auth — inject li_at / JSESSIONID cookies to bypass the
# guest rate-limit wall and reach authenticated search results. Not in v1; the
# public (guest) endpoint is used as-is.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from src.job_hunt_parsing import extract_skills_from_text
from src.job_sources._multiselect import (
    ACTION_BAR,
    STAGING_OVERLAY,
    hide_attrs,
    more_button_html,
    multiselect_script,
    select_shell,
)
from src.job_sources.source_registry import JobSource, register
from src.ui_state import (
    _ALLOWED_EMPLOYMENT_TYPES,
    _ALLOWED_WORK_MODES,
    _SELECT_FORM_FIELD_LIMITS,
)
from src.ui_utils import (
    default_form_values,
    escape,
    squash_whitespace,
)

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_CACHE_TTL = 300  # 5 minutes

# Module-level cache DB path. Defaults to the project's standard location; can
# be overridden per-request (select_handler syncs from config) or in tests.
_DEFAULT_DB_PATH = Path("data/state/job_hunt_index.db")
_cache_db_path: Path = _DEFAULT_DB_PATH

# LinkedIn work-mode filter values (f_WT param): "" = any, 1=onsite, 2=remote, 3=hybrid
_WORK_MODE_LI_TO_DISPLAY: dict[str, str] = {
    "": "",
    "1": "onsite",
    "2": "remote",
    "3": "hybrid",
}


# ── Custom exception ──────────────────────────────────────────────────────────

class LinkedInBlockedError(RuntimeError):
    """Raised when LinkedIn blocks the scraping request.

    Triggers: HTTP 999/429/403/401, login redirect, suspiciously short HTML,
    or missing expected DOM elements.
    """


# ── is_available ──────────────────────────────────────────────────────────────

def is_available() -> bool:
    """Always True — LinkedIn public search needs no API key or configuration."""
    return True


# ── SQLite cache ──────────────────────────────────────────────────────────────

def set_cache_db_path(path: Path | str) -> None:
    """Override the SQLite DB path used for the LinkedIn search cache.

    Called automatically from select_handler (which receives config.state_root),
    and can be called directly from tests to use a temporary DB.
    """
    global _cache_db_path
    _cache_db_path = Path(path)


def _cache_key(keywords: str, location: str, work_mode: str, start: int = 0) -> str:
    # ``start`` is part of the key so each pagination page caches separately;
    # otherwise page 2 would serve page 1's cached rows ("More" duplicates).
    raw = f"{keywords}|{location}|{work_mode}|{start}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _open_cache_conn() -> sqlite3.Connection:
    path = _cache_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    conn.execute(
        "CREATE TABLE IF NOT EXISTS linkedin_search_cache "
        "(id TEXT PRIMARY KEY, results_json TEXT, cached_at REAL)"
    )
    conn.commit()
    return conn


def _cache_get(key: str) -> list[dict] | None:
    """Return cached results if they exist and are within TTL, else None."""
    try:
        conn = _open_cache_conn()
        try:
            row = conn.execute(
                "SELECT results_json, cached_at FROM linkedin_search_cache WHERE id = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            if time.time() - row["cached_at"] > _CACHE_TTL:
                conn.execute(
                    "DELETE FROM linkedin_search_cache WHERE id = ?", (key,)
                )
                conn.commit()
                return None
            return json.loads(row["results_json"])
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("LinkedIn cache read failed: %s", exc)
        return None


def _cache_set(key: str, results: list[dict]) -> None:
    try:
        conn = _open_cache_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO linkedin_search_cache "
                "(id, results_json, cached_at) VALUES (?, ?, ?)",
                (key, json.dumps(results), time.time()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("LinkedIn cache write failed: %s", exc)


# ── search params ─────────────────────────────────────────────────────────────

def normalize_search_params(raw: dict) -> dict:
    """Clean and default raw GET params.

    Fields: keywords, location (default "United Kingdom"), work_mode
    ("" any / "1" onsite / "2" remote / "3" hybrid), results_to_take (default 25).
    """
    keywords = squash_whitespace(raw.get("keywords") or "")[:120]
    location = squash_whitespace(raw.get("location", "") or "United Kingdom")[:120] or "United Kingdom"
    work_mode = str(raw.get("work_mode", "")).strip()
    if work_mode not in {"", "1", "2", "3"}:
        work_mode = ""
    try:
        results_to_take = max(1, min(50, int(raw.get("results_to_take", 25))))
    except (TypeError, ValueError):
        results_to_take = 25
    try:
        results_skip = max(0, int(raw.get("results_skip", 0)))
    except (TypeError, ValueError):
        results_skip = 0
    return {
        "keywords": keywords,
        "location": location,
        "work_mode": work_mode,
        "results_to_take": results_to_take,
        "results_skip": results_skip,
    }


# ── blocked-page detection ────────────────────────────────────────────────────

def _is_blocked(final_url: str, html_text: str, status_code: int) -> bool:
    """Return True if LinkedIn is blocking the request.

    Checks (in order):
    - HTTP status 999/429/403/401
    - Login/authwall redirect URL (response URL contains linkedin.com/login or
      linkedin.com/authwall — both are used by LinkedIn as auth gates)
    - Suspiciously short page (< 5000 chars) — indicates an error/CAPTCHA page

    Note: absence of job cards is NOT treated as a block — a valid page can
    legitimately have zero results (search_handler returns [] in that case).
    """
    if status_code in (999, 429, 403, 401):
        return True
    if "linkedin.com/login" in final_url or "linkedin.com/authwall" in final_url:
        return True
    if len(html_text) < 5000:
        return True
    return False


# ── HTML parsing ──────────────────────────────────────────────────────────────

def _extract_job_id_from_url(url: str) -> str | None:
    m = re.search(r"/jobs/view/(\d+)", url)
    return m.group(1) if m else None


def _parse_search_html(html_text: str, work_mode_display: str) -> list[dict]:
    """Parse LinkedIn search result HTML into a list of UI result dicts."""
    from bs4 import BeautifulSoup  # soft-dependency: bs4 is always installed

    soup = BeautifulSoup(html_text, "html.parser")
    cards = soup.select(".base-card")
    if not cards:
        cards = soup.select(".jobs-search__results-list li")

    results: list[dict] = []
    seen_ids: set[str] = set()

    for card in cards:
        title_el = card.select_one("h3.base-search-card__title")
        company_el = card.select_one("h4.base-search-card__subtitle")
        location_el = card.select_one(".job-search-card__location")
        link_el = card.select_one("a[href]")

        title = squash_whitespace(title_el.get_text() if title_el else "")
        company = squash_whitespace(company_el.get_text() if company_el else "")
        location = squash_whitespace(location_el.get_text() if location_el else "")

        raw_href = link_el["href"] if link_el and link_el.get("href") else ""
        job_url = raw_href.split("?")[0] if raw_href else ""
        job_id = _extract_job_id_from_url(job_url) or uuid.uuid4().hex

        # Dedup by job_id
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        # description_preview: first 200 chars of any available card text
        snippet = squash_whitespace(card.get_text())
        description_preview = snippet[:200] if snippet else ""

        results.append({
            "source": "linkedin",
            "source_job_id": job_id,
            "title": title or "Unknown",
            "company": company or "Unknown",
            "location": location,
            "salary_display": "",
            "salary_min_gbp": None,
            "salary_max_gbp": None,
            "employment_type": "",
            "work_mode": work_mode_display,
            "url": job_url,
            "description_preview": description_preview,
            "description_raw": "",
            "filter_notes": "LinkedIn does not provide salary. Results may vary.",
        })

    return results


# ── HTTP fetch ────────────────────────────────────────────────────────────────

def _fetch_search(keywords: str, location: str, work_mode: str, start: int = 0) -> list[dict]:
    """Fetch LinkedIn public job search. Raises LinkedInBlockedError if blocked.

    Uses the `requests` library (already in project requirements). No retries.
    Timeouts: connect=5 s, read=10 s. ``start`` is LinkedIn's result offset, used
    to page through results for the "More jobs" button.
    """
    import requests  # stdlib-level import kept lazy so tests can patch easily

    url = (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords={quote_plus(keywords)}"
        f"&location={quote_plus(location)}"
        f"&f_WT={work_mode}"
        f"&start={max(0, int(start))}"
    )
    headers = {"User-Agent": _USER_AGENT}
    work_mode_display = _WORK_MODE_LI_TO_DISPLAY.get(work_mode, "")

    try:
        response = requests.get(url, headers=headers, timeout=(5, 10), allow_redirects=True)
    except requests.exceptions.Timeout as exc:
        raise TimeoutError(f"LinkedIn request timed out: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"LinkedIn request error: {exc}") from exc

    html_text = response.text
    final_url = response.url  # requests follows redirects; this is the final URL

    if _is_blocked(final_url, html_text, response.status_code):
        raise LinkedInBlockedError("LinkedIn is blocking requests. Try again later.")

    return _parse_search_html(html_text, work_mode_display)


# ── search_handler ─────────────────────────────────────────────────────────────

def search_handler(cleaned_params: dict) -> list[dict]:
    """Fetch LinkedIn jobs, return up to results_to_take results.

    Cache hit (within TTL) skips the HTTP request entirely.
    """
    keywords = cleaned_params.get("keywords", "")
    location = str(cleaned_params.get("location", "United Kingdom"))
    work_mode = str(cleaned_params.get("work_mode", ""))
    results_to_take = int(cleaned_params.get("results_to_take", 25))
    start = int(cleaned_params.get("results_skip", 0) or 0)

    key = _cache_key(keywords, location, work_mode, start)
    cached = _cache_get(key)
    if cached is not None:
        logger.debug("LinkedIn cache hit for key %s", key)
        return cached[:results_to_take]

    results = _fetch_search(keywords, location, work_mode, start=start)
    _cache_set(key, results)  # cache empty results too — avoids repeated hits on zero-result queries
    return results[:results_to_take]


# ── select_handler (lazy description fetch) ───────────────────────────────────

def _fetch_description(job_id: str) -> str:
    """Lazily fetch full job description. Returns "" if blocked or on error."""
    import requests

    url = f"https://www.linkedin.com/jobs/view/{job_id}/"
    headers = {"User-Agent": _USER_AGENT}

    try:
        response = requests.get(url, headers=headers, timeout=(5, 10), allow_redirects=True)
    except requests.exceptions.RequestException:
        return ""

    html_text = response.text
    final_url = response.url

    if _is_blocked(final_url, html_text, response.status_code):
        return ""

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_text, "html.parser")
        desc_el = (
            soup.select_one(".description__text")
            or soup.select_one(".show-more-less-html__markup")
        )
        if desc_el:
            return squash_whitespace(desc_el.get_text())
    except Exception:
        pass
    return ""


def select_handler(post_form: dict, config: Any) -> dict:
    """Validate a LinkedIn select form POST and return evaluate-form values.

    Lazily fetches the full description if not already present in the form.
    Raises ValueError on invalid / tampered input.
    """
    # Sync cache DB path from config so searches and selects share the same DB
    if config is not None and hasattr(config, "state_root"):
        set_cache_db_path(Path(config.state_root) / "job_hunt_index.db")

    cleaned: dict[str, str] = {}
    for key, limit in _SELECT_FORM_FIELD_LIMITS.items():
        raw = post_form.get(key, "") or ""
        value = squash_whitespace(raw) if key != "description_raw" else raw.strip()
        if len(value) > limit:
            raise ValueError(f"{key} is too long")
        cleaned[key] = value

    if cleaned["source"] != "linkedin":
        raise ValueError("This handler only processes LinkedIn results")

    work_mode = cleaned["work_mode"].lower()
    if work_mode not in _ALLOWED_WORK_MODES:
        work_mode = ""

    employment_type = cleaned["employment_type"].lower()
    if employment_type not in _ALLOWED_EMPLOYMENT_TYPES:
        employment_type = ""

    job_id_val = cleaned["source_job_id"]
    description_raw = cleaned["description_raw"]

    # Lazy description fetch: only if description is blank and job_id looks numeric
    if not description_raw and job_id_val and job_id_val.isdigit():
        description_raw = _fetch_description(job_id_val)

    advert_url = cleaned["url"] or ""
    if advert_url and not advert_url.startswith("https://www.linkedin.com/"):
        raise ValueError("url must be a linkedin.com URL or empty")
    source_ref = advert_url or job_id_val
    # Apply-link URL for JobPosting.url: when the scraped href was missing,
    # rebuild the canonical advert URL from the numeric job id so the saved
    # job still links out to LinkedIn to apply. source_ref keeps its
    # documented job_id fallback (unchanged) and the tamper guard above stays.
    apply_url = advert_url or (
        f"https://www.linkedin.com/jobs/view/{job_id_val}"
        if job_id_val and job_id_val.isdigit()
        else ""
    )

    _req_skills, _pref_skills, _skill_warn = extract_skills_from_text(description_raw)
    if _skill_warn:
        logger.warning("LinkedIn select skill extraction: %s", _skill_warn)

    values = default_form_values()
    values.update(
        {
            "job_id": _linkedin_job_id(cleaned),
            "input_method": "linkedin_search",
            "job_url": apply_url,
            "source_type": "linkedin",
            "source_ref": source_ref,
            "source_job_id": job_id_val,
            "job_title": cleaned["title"] or "Unknown",
            "company": cleaned["company"] or "Unknown",
            "location": cleaned["location"],
            "work_mode": "" if work_mode == "unknown" else work_mode,
            "employment_type": "" if employment_type == "unknown" else employment_type,
            "salary_min_gbp": None,
            "salary_max_gbp": None,
            "copied_text": description_raw,
            "description_raw": description_raw,
            "required_skills": ", ".join(_req_skills),
            "preferred_skills": ", ".join(_pref_skills),
            "notes": (
                "Prefilled from LinkedIn search result (best effort). "
                "Review all fields before evaluation."
            ),
        }
    )
    return values


def _linkedin_job_id(form: dict[str, str]) -> str:
    base = form.get("source_job_id") or f"{form.get('title', '')}-{form.get('company', '')}"
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:80]
    return f"linkedin-{slug or uuid.uuid4().hex[:12]}"


# ── render_search_form ────────────────────────────────────────────────────────

def render_search_form(values: dict, enabled: bool) -> str:
    disable_attr = "" if enabled else ' style="opacity:0.5;pointer-events:none;"'
    work_mode_options = [
        ("", "Any"),
        ("2", "Remote"),
        ("3", "Hybrid"),
        ("1", "Onsite"),
    ]
    current_wm = str(values.get("work_mode", ""))
    wm_options_html = "".join(
        f'<option value="{escape(v)}"{" selected" if v == current_wm else ""}>'
        f"{escape(label)}</option>"
        for v, label in work_mode_options
    )
    results_val = escape(str(values.get("results_to_take", 25)))
    return f"""
    <form method="get" action="/search/linkedin" id="linkedin-search-form" class="panel subtle"{disable_attr}>
      <h3>Search LinkedIn <span style="font-size:12px;font-weight:400;color:var(--ink-faint);">(best effort)</span></h3>
      <div class="grid two-col">
        <label><span>Keywords / job title</span><input name="keywords" value="{escape(values.get('keywords', ''))}" placeholder="Business Analyst"></label>
        <label><span>Location</span><input name="location" value="{escape(values.get('location', 'United Kingdom'))}" placeholder="United Kingdom"></label>
        <label><span>Work mode</span><select name="work_mode">{wm_options_html}</select></label>
        <label><span>Results to take</span><input name="results_to_take" inputmode="numeric" value="{results_val}" placeholder="25"></label>
      </div>
      <p class="prefill-status">LinkedIn public search is best-effort. Salary data is unavailable. Results may be rate-limited by LinkedIn.</p>
      <div class="actions">
        <button type="submit">Search LinkedIn</button>
        <a href="/?tab=add_job" class="tab-link active">Manual Fallback</a>
        <a href="/?tab=evaluate" class="tab-link">Evaluate existing details</a>
      </div>
    </form>
    """


# ── render_results ────────────────────────────────────────────────────────────

def _render_select_form(result: dict, nonce: str | None, form_id: str | None = None) -> str:
    field_names = [
        "source", "source_job_id", "title", "company", "location",
        "work_mode", "employment_type", "url", "description_raw",
        "salary_min_gbp", "salary_max_gbp",
    ]
    hidden = [f'<input type="hidden" name="nonce" value="{escape(nonce or "")}">']
    for name in field_names:
        hidden.append(
            f'<input type="hidden" name="{escape(name)}" value="{escape(result.get(name) or "")}">'
        )
    id_attr = f' id="{escape(form_id)}"' if form_id else ""
    return (
        f'<form method="post" action="/select/linkedin"'
        f' class="actions linkedin-select-form"{id_attr} style="display:none;">'
        f'{"".join(hidden)}</form>'
    )


def _render_cards(results: list[dict], nonce: str | None = None, *, skip: int = 0) -> str:
    html: list[str] = []
    for i, result in enumerate(results):
        card_id = f"li-rc-{skip + i}"
        form_id = f"li-rf-{skip + i}"
        title_esc = escape(result.get("title") or "Unknown")
        company_esc = escape(result.get("company") or "Unknown")
        location_esc = escape(result.get("location") or "")
        snippet_esc = escape((result.get("description_preview") or "")[:200])
        mode_esc = escape(result.get("work_mode") or "")
        note_esc = escape(result.get("filter_notes") or "")
        url_val = result.get("url") or ""

        tag_parts: list[str] = []
        if location_esc:
            tag_parts.append(
                f'<span style="font-size:11.5px;padding:3px 9px;border-radius:100px;'
                f'background:var(--surface-sunk);color:var(--ink-soft);border:1px solid var(--line);">'
                f"&#128205; {location_esc}</span>"
            )
        if mode_esc and mode_esc.lower() not in ("", "unknown"):
            tag_parts.append(
                f'<span style="font-size:11.5px;padding:3px 9px;border-radius:100px;'
                f'background:var(--accent-soft);color:var(--accent);border:1px solid transparent;">'
                f"{mode_esc}</span>"
            )
        tags_html = (
            '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;">'
            + "".join(tag_parts)
            + "</div>"
        ) if tag_parts else ""

        notes_html = (
            f'<div style="font-size:11px;color:var(--ink-faint);margin-top:6px;">{note_esc}</div>'
        ) if note_esc else ""

        _safe_url = url_val if url_val.startswith(("https://", "http://")) else ""
        link_html = (
            f' <a href="{escape(_safe_url)}" target="_blank" rel="noopener noreferrer"'
            f' style="font-size:11.5px;color:var(--accent);"'
            f' onclick="event.stopPropagation();">View &#8599;</a>'
        ) if _safe_url else ""

        form_html = _render_select_form(result, nonce, form_id=form_id)

        # Selectable only when the job can be evaluated: an identifier plus a
        # description already in hand, or a numeric job id we can lazy-fetch the
        # description for at select time. Otherwise render disabled.
        _jid = result.get("source_job_id") or ""
        selectable = bool(
            (_jid or result.get("url"))
            and (result.get("description_raw") or str(_jid).isdigit())
        )
        root_class, root_extra, checkbox_html, disabled_note_html = select_shell(
            card_id, selectable=selectable, url=result.get("url")
        )

        html.append(
            f'<div class="{root_class}" id="{card_id}" data-jst-id="{card_id}" data-jst-form="{form_id}"'
            f' data-jst-title="{title_esc}" data-jst-company="{company_esc}"'
            f' data-jst-salary="" data-jst-location="{location_esc}"'
            f"{hide_attrs(result)}"
            f"{root_extra}>"
            f"{form_html}"
            f'<div style="display:flex;gap:13px;align-items:flex-start;">'
            f"{checkbox_html}"
            f'<div style="flex:1;min-width:0;">'
            f'<div style="font-size:15px;font-weight:700;letter-spacing:-0.015em;">'
            f"{title_esc}{link_html}</div>"
            f'<div style="font-size:13px;color:var(--ink-soft);margin-top:2px;">{company_esc}</div>'
            f'<div style="font-size:13px;color:var(--ink-faint);line-height:1.55;margin-top:8px;">'
            f"{snippet_esc}</div>"
            f"{tags_html}"
            f"{notes_html}"
            f"{disabled_note_html}"
            f"</div>"
            f"</div>"
            f"</div>"
        )
    return "".join(html)


def render_results(
    results: list[dict] | None,
    error: str | None,
    nonce: str | None,
    more_url: str | None = None,
) -> str:
    """Return HTML for the LinkedIn results section.

    Mirrors the Adzuna pattern: cards use .jst-rc CSS class and data-jst-*
    attributes so the multi-select JS scaffolding from whichever source loaded
    first (reed/adzuna) is automatically reused.
    """
    if error:
        return (
            '<div style="margin-top:18px;padding:16px 20px;background:var(--skip-bg);'
            "border:1px solid var(--skip-line);border-radius:var(--r-lg);\">"
            '<div style="font-size:14px;font-weight:700;color:var(--skip);margin-bottom:6px;">'
            "LinkedIn search unavailable</div>"
            f'<div style="font-size:13px;color:var(--ink-soft);">{escape(error)}</div>'
            '<div style="margin-top:12px;font-size:13px;">'
            '<a href="/?tab=add_job">Use Manual Fallback</a>'
            "</div></div>"
        )
    if results is None:
        return ""
    if not results:
        return (
            '<div style="margin-top:24px;text-align:center;padding:56px 20px;">'
            '<div style="font-size:15px;font-weight:600;color:var(--ink-soft);">No LinkedIn results found</div>'
            '<div style="font-size:13px;color:var(--ink-faint);margin-top:4px;">'
            "Try broader keywords or location, or continue with manual input.</div>"
            '<div style="margin-top:14px;"><a href="/?tab=add_job">Use Manual Fallback</a></div>'
            "</div>"
        )

    total_str = str(len(results))
    cards_html = _render_cards(results, nonce, skip=0)

    return (
        f'<div style="margin-top:22px;position:relative;">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'margin-bottom:12px;gap:12px;">'
        f'<span style="font-size:11px;font-weight:700;letter-spacing:0.06em;'
        f'text-transform:uppercase;color:var(--ink-faint);">'
        f"LinkedIn results ({total_str}) — best effort</span>"
        f'<button onclick="jstSelectAll()" style="background:none;border:none;color:var(--accent);'
        f'font-size:12.5px;font-weight:600;cursor:pointer;font-family:inherit;">Select all</button>'
        f"</div>"
        f'<div id="jst-cards-container">'
        f"{cards_html}"
        f"{more_button_html(more_url)}"
        f"</div>"
        f"{ACTION_BAR}"
        f"{STAGING_OVERLAY}"
        f"{multiselect_script()}"
        f"</div>"
    )


# ── registration (import-time side effect) ────────────────────────────────────

def _register() -> None:
    register(
        JobSource(
            source_id="linkedin",
            display_name="LinkedIn (best effort)",
            is_available=is_available,
            normalize_search_params=normalize_search_params,
            search_handler=search_handler,
            select_handler=select_handler,
            render_search_form=render_search_form,
            render_results=lambda results, error, nonce, more_url=None: render_results(
                results, error, nonce, more_url=more_url
            ),
            render_cards_fragment=lambda results, *, skip=0, nonce=None: _render_cards(
                results, skip=skip, nonce=nonce
            ),
        )
    )


_register()
