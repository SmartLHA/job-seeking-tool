"""Reed job source.

All Reed-specific rendering, normalisation, snapshot and registration logic.
Extracted from ``job_hunt_ui.py`` (MT-1). This module is self-contained: the UI
layer discovers it only through :mod:`src.job_sources.source_registry`.

Shared UI helpers (``escape``, ``format_salary_range`` …) come from ``ui_utils``
and shared constants from ``ui_state`` — this module has no dependency on
``job_hunt_ui``, so there is no circular import.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from src.job_hunt_parsing import extract_skills_from_text
from src.job_sources.normalize import normalize_reed
from src.job_sources.reed_client import fetch_reed_jobs
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
    _SELECT_FORM_FIELD_LIMITS,
    _ALLOWED_WORK_MODES,
    _ALLOWED_EMPLOYMENT_TYPES,
)
from src.ui_utils import (
    escape,
    squash_whitespace,
    normalize_optional_int_text,
    render_select_options,
    default_form_values,
    format_salary_range,
)

logger = logging.getLogger(__name__)


def _render_reed_search_form(values: dict[str, str], enabled: bool) -> str:
    """Render the Reed search ``<form>`` block.

    Registered as the ``render_search_form`` callable for the Reed
    :class:`~src.job_sources.source_registry.JobSource`.  Adding a new job
    source means creating an analogous function in its own module and
    registering it — no changes needed here.
    """
    disable_attr = "" if enabled else ' style="opacity:0.5;pointer-events:none;"'
    return f"""
    <form method="get" action="/search/reed" id="reed-search-form" class="panel subtle"{disable_attr}>
      <h3>Search Reed</h3>
      <div class="grid two-col">
        <label><span>Keywords / job title</span><input name="keywords" value="{escape(values.get('keywords', ''))}" placeholder="Business Analyst"></label>
        <label><span>Location</span><input name="locationName" value="{escape(values.get('locationName', ''))}" placeholder="London"></label>
        <label><span>Minimum salary</span><input name="minimumSalary" inputmode="numeric" value="{escape(values.get('minimumSalary', ''))}" placeholder="50000"></label>
        <label><span>Results to take</span><input name="resultsToTake" inputmode="numeric" value="{escape(values.get('resultsToTake', '10'))}" placeholder="10"></label>
        <label><span>Work mode</span><select name="workMode">{render_select_options(['any', 'remote', 'hybrid', 'onsite'], values.get('workMode', 'any'))}</select></label>
        <label><span>Employment type</span><select name="employmentType">{render_select_options(['any', 'permanent', 'contract'], values.get('employmentType', 'any'))}</select></label>
      </div>
      <p class="prefill-status">Remote/hybrid and employment type are applied best-effort from Reed fields; unsupported filters are called out in result notes.</p>
      <div class="actions">
        <button type="submit">Search Reed</button>
        <a href="/?tab=add_job" class="tab-link active">Manual Fallback</a>
        <a href="/?tab=evaluate" class="tab-link">Evaluate existing details</a>
      </div>
    </form>
    """


_REED_SOURCE_SNAPSHOT_MAX_BYTES = 20 * 1024


_REED_SOURCE_SNAPSHOT_VERSION = "pl-04-v1"


def render_reed_select_form(result: dict[str, Any], nonce: str | None, form_id: str | None = None) -> str:
    if not nonce or not result.get("source_snapshot_json"):
        return f'<form{(" id=" + chr(34) + escape(form_id) + chr(34)) if form_id else ""} style="display:none;"></form>'
    field_names = [
        "source",
        "source_job_id",
        "title",
        "company",
        "location",
        "work_mode",
        "employment_type",
        "url",
        "description_raw",
        "salary_min_gbp",
        "salary_max_gbp",
        "source_snapshot_json",
    ]
    hidden = [f'<input type="hidden" name="nonce" value="{escape(nonce)}">']
    for name in field_names:
        hidden.append(f'<input type="hidden" name="{escape(name)}" value="{escape(result.get(name) or "")}">')
    id_attr = f' id="{escape(form_id)}"' if form_id else ""
    return f'<form method="post" action="/select/reed" class="actions reed-select-form"{id_attr} style="display:none;">{"".join(hidden)}</form>'


def reed_select_form_to_evaluate_values(form: dict[str, str], config: "object | None" = None) -> dict[str, str]:
    # MT-7: nonce enforcement removed (local-only server). The hidden "nonce"
    # field is accepted but not validated.
    cleaned: dict[str, str] = {}
    for key, limit in _SELECT_FORM_FIELD_LIMITS.items():
        value = squash_whitespace(form.get(key, "")) if key != "description_raw" else (form.get(key, "") or "").strip()
        if len(value) > limit:
            raise ValueError(f"{key} is too long")
        cleaned[key] = value
    if cleaned["source"] != "reed":
        raise ValueError("This handler only processes Reed search results")
    work_mode = cleaned["work_mode"].lower()
    if work_mode not in _ALLOWED_WORK_MODES:
        raise ValueError("work_mode has an unsupported value")
    employment_type = cleaned["employment_type"].lower()
    if employment_type not in _ALLOWED_EMPLOYMENT_TYPES:
        raise ValueError("employment_type has an unsupported value")
    salary_min = validate_reed_salary_text(cleaned["salary_min_gbp"], "salary_min_gbp")
    salary_max = validate_reed_salary_text(cleaned["salary_max_gbp"], "salary_max_gbp")
    source_snapshot = validate_reed_source_snapshot_json(form.get("source_snapshot_json", ""))
    values = default_form_values()
    source_job_id = cleaned["source_job_id"]
    # Prefer the advert URL so saved jobs retain a working application link.
    advert_url = cleaned["url"] or ""

    # Fetch the full job description from Reed's detail API.
    # The search results page only carries a 500-char preview; the detail API
    # returns the complete jobDescription HTML which is required for accurate
    # skill extraction. Fall back to the truncated preview on any failure.
    full_description = cleaned["description_raw"]
    if source_job_id:
        from src.job_sources.reed_client import fetch_reed_job_detail
        from src.job_sources.normalize import strip_html
        detail = fetch_reed_job_detail(source_job_id)
        if detail and detail.get("jobDescription"):
            full_description = strip_html(detail["jobDescription"]).strip()
            logger.info(
                "Reed detail fetched for %s — description length: %d chars",
                source_job_id, len(full_description),
            )
        else:
            logger.warning(
                "Reed detail unavailable for %s — using truncated preview (%d chars)",
                source_job_id, len(full_description),
            )
        # When the search result carried no advert URL, fall back to the
        # detail API's canonical jobUrl so the saved job keeps an apply link.
        if not advert_url and detail and detail.get("jobUrl"):
            advert_url = str(detail["jobUrl"]).strip()

    # source_ref keeps the advert URL when known, else the bare Reed id (still
    # identifying via job_id and the source snapshot). The advert URL itself is
    # stored separately as job_url -> JobPosting.url for the apply link.
    source_ref = advert_url or source_job_id

    _req_skills, _pref_skills, _skill_warn = extract_skills_from_text(full_description)
    if _skill_warn:
        logger.warning("Reed select skill extraction: %s", _skill_warn)
    values.update(
        {
            "job_id": reed_selected_job_id(cleaned),
            "input_method": "reed_search",
            "job_url": advert_url,
            "source_type": "reed",
            "source_ref": source_ref,
            "source_job_id": source_job_id or "",   # dedup key (C1) — survives to JobPosting
            "job_title": cleaned["title"] or "Unknown",
            "company": cleaned["company"] or "Unknown",
            "location": cleaned["location"],
            "work_mode": "" if work_mode == "unknown" else work_mode,
            "employment_type": "" if employment_type == "unknown" else employment_type,
            "salary_min_gbp": salary_min,
            "salary_max_gbp": salary_max,
            "copied_text": full_description,
            "description_raw": full_description,
            "required_skills": ", ".join(_req_skills),
            "preferred_skills": ", ".join(_pref_skills),
            "notes": "Prefilled from Reed search result. Review all fields before evaluation.",
            "source_snapshot_json": serialize_reed_source_snapshot(source_snapshot),
        }
    )
    return values


def serialize_reed_source_snapshot(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_reed_source_snapshot_json(value: str) -> dict[str, Any]:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("source_snapshot_json is required for Reed-selected jobs")
    if len(raw.encode("utf-8")) > _REED_SOURCE_SNAPSHOT_MAX_BYTES:
        raise ValueError("source_snapshot_json exceeds 20KB limit")
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("source_snapshot_json must be valid JSON") from exc
    if not isinstance(snapshot, dict):
        raise ValueError("source_snapshot_json must be a JSON object")
    canonical = serialize_reed_source_snapshot(snapshot)
    if len(canonical.encode("utf-8")) > _REED_SOURCE_SNAPSHOT_MAX_BYTES:
        raise ValueError("source_snapshot_json exceeds 20KB limit")
    if snapshot.get("source") != "reed":
        raise ValueError("source_snapshot.source must be reed")
    if snapshot.get("capture_stage") != "select":
        raise ValueError("source_snapshot.capture_stage must be select")
    captured_at = snapshot.get("captured_at")
    if not isinstance(captured_at, str) or not captured_at.strip():
        raise ValueError("source_snapshot.captured_at is required")
    try:
        datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("source_snapshot.captured_at must be an ISO timestamp") from exc
    if not isinstance(snapshot.get("description_raw"), str) or not snapshot["description_raw"].strip():
        raise ValueError("source_snapshot.description_raw is required")
    if not isinstance(snapshot.get("snapshot_version"), str) or not snapshot["snapshot_version"].strip():
        raise ValueError("source_snapshot.snapshot_version is required")
    has_source_ref = any(isinstance(snapshot.get(key), str) and snapshot[key].strip() for key in ("source_job_id", "url"))
    if not has_source_ref:
        raise ValueError("source_snapshot requires source_job_id or url")
    return snapshot


def validate_reed_salary_text(value: str, field_name: str) -> str:
    if not value:
        return ""
    if not value.isdigit():
        raise ValueError(f"{field_name} must be numeric")
    return str(max(0, int(value)))


def reed_selected_job_id(cleaned: dict[str, str]) -> str:
    base = cleaned.get("source_job_id") or f"{cleaned.get('title', '')}-{cleaned.get('company', '')}"
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:80]
    return f"reed-{slug or uuid.uuid4().hex[:12]}"


def default_reed_search_values() -> dict[str, str]:
    return {
        "keywords": "",
        "locationName": "",
        "minimumSalary": "",
        "workMode": "any",
        "employmentType": "any",
        "resultsToTake": "10",
        "resultsSkip": "0",
    }


def normalize_reed_search_params(params: dict[str, str]) -> dict[str, str]:
    values = default_reed_search_values()
    values["keywords"] = squash_whitespace(params.get("keywords", ""))[:120]
    values["locationName"] = squash_whitespace(params.get("locationName", ""))[:120]
    values["minimumSalary"] = normalize_optional_int_text(params.get("minimumSalary", ""))
    values["workMode"] = params.get("workMode", "any").strip().lower()
    if values["workMode"] not in {"any", "remote", "hybrid", "onsite"}:
        values["workMode"] = "any"
    values["employmentType"] = params.get("employmentType", "any").strip().lower()
    if values["employmentType"] not in {"any", "permanent", "contract"}:
        values["employmentType"] = "any"
    try:
        requested_take = int(params.get("resultsToTake", values["resultsToTake"]))
    except (TypeError, ValueError):
        requested_take = int(values["resultsToTake"])
    values["resultsToTake"] = str(max(1, min(50, requested_take)))
    try:
        requested_skip = int(params.get("resultsSkip", "0"))
    except (TypeError, ValueError):
        requested_skip = 0
    values["resultsSkip"] = str(max(0, requested_skip))
    return values


def search_reed_jobs_for_ui(search_values: dict[str, str]) -> list[dict[str, Any]]:
    take = int(search_values["resultsToTake"])
    skip = int(search_values.get("resultsSkip", "0"))
    raw_jobs = fetch_reed_jobs(
        search_values["keywords"],
        search_values["locationName"],
        take,
        skip=skip,
        save_raw=False,
    )
    return [reed_job_to_ui_result(raw, search_values) for raw in raw_jobs[:take]]


def reed_job_to_ui_result(raw_job: dict[str, Any], search_values: dict[str, str]) -> dict[str, Any]:
    normalized = normalize_reed(raw_job)
    salary_display = format_reed_salary_display(normalized.get("salary_min"), normalized.get("salary_max"), normalized.get("salary_text"))
    description = squash_whitespace(normalized.get("description") or "")
    result = {
        "source": "reed",
        "source_job_id": normalize_reed_source_job_id(normalized.get("external_id")),
        "title": normalized.get("title") or "Unknown",
        "company": normalized.get("company") or "Unknown",
        "location": normalized.get("location") or "Unknown",
        "salary_display": salary_display,
        "salary_min_gbp": normalize_reed_salary_value(normalized.get("salary_min")),
        "salary_max_gbp": normalize_reed_salary_value(normalized.get("salary_max")),
        "employment_type": normalized.get("contract_type") or "Unknown",
        "work_mode": normalized.get("remote_type") or "Unknown",
        "url": normalized.get("original_url") or normalized.get("apply_url") or None,
        "description_preview": description[:280],
        "description_raw": truncate_reed_description(description),
        "filter_notes": reed_filter_notes(normalized, search_values),
    }
    if (result.get("source_job_id") or result.get("url")) and result.get("description_raw"):
        result["source_snapshot_json"] = serialize_reed_source_snapshot(build_reed_source_snapshot(result))
    else:
        result["source_snapshot_json"] = ""
    return result


def build_reed_source_snapshot(result: dict[str, Any]) -> dict[str, Any]:
    snapshot = {
        "source": "reed",
        "source_job_id": result.get("source_job_id") or "",
        "title": result.get("title") or "",
        "company": result.get("company") or "",
        "location": result.get("location") or "",
        "salary_min_gbp": result.get("salary_min_gbp") or "",
        "salary_max_gbp": result.get("salary_max_gbp") or "",
        "employment_type": result.get("employment_type") or "",
        "work_mode": result.get("work_mode") or "",
        "url": result.get("url") or "",
        "description_raw": result.get("description_raw") or "",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "capture_stage": "select",
        "snapshot_version": _REED_SOURCE_SNAPSHOT_VERSION,
    }
    validate_reed_source_snapshot_json(serialize_reed_source_snapshot(snapshot))
    return snapshot


def normalize_reed_source_job_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text and text.lower() not in {"none", "null", "unknown"} else None


def normalize_reed_salary_value(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return str(max(0, int(float(value))))
    except (TypeError, ValueError):
        return ""


def truncate_reed_description(description: str) -> str:
    text = description or ""
    if len(text) <= 500:
        return text
    return text[:500].rstrip() + "…"


def format_reed_salary_display(salary_min: Any, salary_max: Any, salary_text: Any = None) -> str:
    if salary_text:
        return str(salary_text)
    min_value = parse_reed_salary_number(salary_min)
    max_value = parse_reed_salary_number(salary_max)
    if min_value is not None and max_value is not None:
        return format_salary_range(min_value, max_value)
    if min_value is not None:
        return format_salary_range(min_value, None)
    if max_value is not None:
        return format_salary_range(None, max_value)
    return "Unknown"


def parse_reed_salary_number(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def reed_filter_notes(normalized: dict[str, Any], search_values: dict[str, str]) -> list[str]:
    notes: list[str] = []
    requested_salary = search_values.get("minimumSalary")
    if requested_salary:
        notes.append("Minimum salary is passed to Reed only as a best-effort display filter in this PL.")
    requested_work_mode = search_values.get("workMode", "any")
    actual_work_mode = (normalized.get("remote_type") or "unknown").lower()
    if requested_work_mode != "any" and actual_work_mode != requested_work_mode:
        notes.append(f"Requested work mode '{requested_work_mode}' was not confirmed by Reed fields; shown as '{actual_work_mode}'.")
    requested_employment = search_values.get("employmentType", "any")
    actual_employment = (normalized.get("contract_type") or "unknown").lower()
    if requested_employment != "any" and actual_employment != requested_employment:
        notes.append(f"Requested employment type '{requested_employment}' was not confirmed by Reed fields; shown as '{actual_employment}'.")
    if not notes:
        notes.append("Reed result normalized for display; filters are best-effort in PL-02.")
    return notes


def _render_reed_cards_fragment(
    results: list[dict[str, Any]],
    *,
    skip: int = 0,
    nonce: str | None = None,
) -> str:
    """Return the raw cards HTML for `results`, with IDs offset by `skip`.
    Used by both the full results render and the /search/reed/more AJAX endpoint."""
    html = []
    for i, result in enumerate(results):
        card_id   = f"jrc-{skip + i}"
        form_id   = f"jrf-{skip + i}"
        title_esc    = escape(result.get("title") or "Unknown")
        company_esc  = escape(result.get("company") or "Unknown")
        location_esc = escape(result.get("location") or "")
        salary_esc   = escape(result.get("salary_display") or "")
        snippet_esc  = escape((result.get("description_preview") or "")[:200])
        emp_esc      = escape(result.get("employment_type") or "")
        mode_esc     = escape(result.get("work_mode") or "")

        tag_parts = []
        if location_esc:
            tag_parts.append(
                f'<span style="font-size:11.5px;padding:3px 9px;border-radius:100px;'
                f'background:var(--surface-sunk);color:var(--ink-soft);border:1px solid var(--line);">'
                f'&#128205; {location_esc}</span>'
            )
        if salary_esc:
            tag_parts.append(
                f'<span style="font-family:var(--font-mono);font-size:11px;padding:3px 9px;'
                f'border-radius:100px;background:var(--surface-sunk);color:var(--ink-soft);'
                f'border:1px solid var(--line);">{salary_esc}</span>'
            )
        if emp_esc and emp_esc.lower() not in ("", "unknown"):
            tag_parts.append(
                f'<span style="font-size:11.5px;padding:3px 9px;border-radius:100px;'
                f'background:var(--surface-sunk);color:var(--ink-soft);border:1px solid var(--line);">'
                f'{emp_esc}</span>'
            )
        if mode_esc and mode_esc.lower() not in ("", "unknown"):
            tag_parts.append(
                f'<span style="font-size:11.5px;padding:3px 9px;border-radius:100px;'
                f'background:var(--accent-soft);color:var(--accent);border:1px solid transparent;">'
                f'{mode_esc}</span>'
            )
        tags_html = (
            '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;">'
            + "".join(tag_parts) + '</div>'
        ) if tag_parts else ""

        notes_items = result.get("filter_notes") or []
        notes_html = ""
        if notes_items:
            notes_html = (
                '<div style="font-size:11px;color:var(--ink-faint);margin-top:6px;">'
                + escape(" \xb7 ".join(notes_items)) + '</div>'
            )

        form_html = render_reed_select_form(result, nonce, form_id=form_id)

        # A card can only be evaluated if it carries a source snapshot (built at
        # search time from the job's id/url + description). Without it the Reed
        # audit guard rejects evaluation, so the card must NOT be selectable —
        # otherwise ticking it produces a cryptic "source_snapshot_json is
        # required" error at evaluate time.
        selectable = bool(result.get("source_snapshot_json"))
        root_class, root_extra, checkbox_html, disabled_note_html = select_shell(
            card_id, selectable=selectable, url=result.get("url")
        )

        html.append(
            f'<div class="{root_class}" id="{card_id}" data-jst-id="{card_id}" data-jst-form="{form_id}"'
            f' data-jst-title="{title_esc}" data-jst-company="{company_esc}"'
            f' data-jst-salary="{salary_esc}" data-jst-location="{location_esc}"'
            f'{hide_attrs(result)}'
            f'{root_extra}>'
            f'{form_html}'
            f'<div style="display:flex;gap:13px;align-items:flex-start;">'
            f'{checkbox_html}'
            f'<div style="flex:1;min-width:0;">'
            f'<div style="font-size:15px;font-weight:700;letter-spacing:-0.015em;">{title_esc}</div>'
            f'<div style="font-size:13px;color:var(--ink-soft);margin-top:2px;">{company_esc}</div>'
            f'<div style="font-size:13px;color:var(--ink-faint);line-height:1.55;margin-top:8px;">{snippet_esc}</div>'
            f'{tags_html}'
            f'{notes_html}'
            f'{disabled_note_html}'
            f'</div>'
            f'</div>'
            f'</div>'
        )
    return "".join(html)


def render_reed_search_results(
    results: list[dict[str, Any]] | None,
    *,
    reed_error: str | None = None,
    reed_select_nonce: str | None = None,
    more_url: str | None = None,
) -> str:
    if reed_error:
        return (
            '<div style="margin-top:18px;padding:16px 20px;background:var(--skip-bg);'
            'border:1px solid var(--skip-line);border-radius:var(--r-lg);">'
            '<div style="font-size:14px;font-weight:700;color:var(--skip);margin-bottom:6px);">Reed search unavailable</div>'
            f'<div style="font-size:13px;color:var(--ink-soft);">{escape(reed_error)}</div>'
            '<div style="margin-top:12px;font-size:13px;">'
            '<a href="/?tab=add_job">Use Manual Fallback</a>'
            '</div></div>'
        )
    if results is None:
        return ""
    if not results:
        return (
            '<div style="margin-top:24px;text-align:center;padding:56px 20px;">'
            '<div style="font-size:15px;font-weight:600;color:var(--ink-soft);">No Reed results found</div>'
            '<div style="font-size:13px;color:var(--ink-faint);margin-top:4px;">Try broader keywords or location, or continue with manual input.</div>'
            '<div style="margin-top:14px;">'
            '<a href="/?tab=add_job">Use Manual Fallback</a>'
            '</div></div>'
        )

    total = len(results)
    total_str = str(total)

    # ── build job cards (delegate to shared helper) ───────────────────────────
    cards_html = _render_reed_cards_fragment(results, skip=0, nonce=reed_select_nonce)

    return (
        f'<div style="margin-top:22px;position:relative;">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;gap:12px;">'
        f'<span style="font-size:11px;font-weight:700;letter-spacing:0.06em;'
        f'text-transform:uppercase;color:var(--ink-faint);">Reed results ({total_str})</span>'
        f'<button onclick="jstSelectAll()" style="background:none;border:none;color:var(--accent);'
        f'font-size:12.5px;font-weight:600;cursor:pointer;font-family:inherit;">Select all</button>'
        f'</div>'
        f'<div id="jst-cards-container">'
        f'{cards_html}'
        f'{more_button_html(more_url)}'
        f'</div>'
        f'{ACTION_BAR}'
        f'{STAGING_OVERLAY}'
        f'{multiselect_script()}'
        f'</div>'
    )


def _is_reed_available() -> bool:
    import os
    _ensure_reed_env_loaded()
    return bool(os.getenv("REED_API_KEY"))


def _ensure_reed_env_loaded() -> None:
    """Load .env for Reed availability check (mirrors reed_client._ensure_env_loaded)."""
    import os
    if os.getenv("REED_API_KEY"):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def _register() -> None:
    """Register the Reed source. Called at import time (startup side effect)."""
    register(JobSource(
        source_id="reed",
        display_name="Reed",
        is_available=_is_reed_available,
        normalize_search_params=normalize_reed_search_params,
        search_handler=search_reed_jobs_for_ui,
        select_handler=reed_select_form_to_evaluate_values,
        render_search_form=_render_reed_search_form,
        render_results=lambda results, error, nonce, more_url=None: render_reed_search_results(
            results, reed_error=error, reed_select_nonce=nonce, more_url=more_url
        ),
        render_cards_fragment=lambda results, *, skip=0, nonce=None: _render_reed_cards_fragment(
            results, skip=skip, nonce=nonce
        ),
    ))


_register()
