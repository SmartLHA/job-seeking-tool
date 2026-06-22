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
    source_ref = source_job_id or cleaned["url"]

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

    _req_skills, _pref_skills, _skill_warn = extract_skills_from_text(full_description)
    if _skill_warn:
        logger.warning("Reed select skill extraction: %s", _skill_warn)
    values.update(
        {
            "job_id": reed_selected_job_id(cleaned),
            "input_method": "reed_search",
            "job_url": cleaned["url"],
            "source_type": "reed",
            "source_ref": source_ref,
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

        html.append(
            f'<div class="jst-rc" id="{card_id}" data-jst-id="{card_id}" data-jst-form="{form_id}"'
            f' data-jst-title="{title_esc}" data-jst-company="{company_esc}"'
            f' data-jst-salary="{salary_esc}" data-jst-location="{location_esc}"'
            f' onclick="jstToggle(\'{card_id}\')"'
            f' style="background:var(--surface);border:1.5px solid var(--line);border-radius:var(--r-lg);'
            f'padding:16px;margin-bottom:10px;cursor:pointer;'
            f'transition:border-color .15s,box-shadow .15s;box-shadow:var(--shadow-sm);">'
            f'{form_html}'
            f'<div style="display:flex;gap:13px;align-items:flex-start;">'
            f'<span id="jst-cb-{card_id}" style="flex-shrink:0;margin-top:2px;width:20px;height:20px;'
            f'border-radius:6px;display:inline-flex;align-items:center;justify-content:center;'
            f'font-size:13px;font-weight:900;background:var(--surface-2);'
            f'border:1.5px solid var(--line);transition:all .14s;pointer-events:none;"></span>'
            f'<div style="flex:1;min-width:0;">'
            f'<div style="font-size:15px;font-weight:700;letter-spacing:-0.015em;">{title_esc}</div>'
            f'<div style="font-size:13px;color:var(--ink-soft);margin-top:2px;">{company_esc}</div>'
            f'<div style="font-size:13px;color:var(--ink-faint);line-height:1.55;margin-top:8px;">{snippet_esc}</div>'
            f'{tags_html}'
            f'{notes_html}'
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

    # ── staging overlay ───────────────────────────────────────────────────────
    staging_overlay = (
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
    )

    # ── sticky action bar ─────────────────────────────────────────────────────
    action_bar = (
        '<div id="jst-bar" style="display:none;position:sticky;bottom:0;left:0;right:0;'
        'padding:14px 0;background:linear-gradient(to top,var(--bg) 60%,transparent);pointer-events:none;">'
        '<div style="background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);'
        'padding:14px 16px;box-shadow:var(--shadow-md);display:flex;align-items:center;gap:16px;pointer-events:auto;">'
        '<div style="display:flex;align-items:center;gap:10px;">'
        '<span id="jst-bc" style="font-family:var(--font-mono);font-size:22px;font-weight:700;color:var(--accent);">0</span>'
        '<div style="font-size:13px;font-weight:600;color:var(--ink-soft);">'
        '<div id="jst-bl">jobs selected</div>'
        '<div style="font-size:11.5px;color:var(--ink-faint);font-weight:400;">Review selected jobs, then evaluate all at once</div>'
        '</div></div>'
        '<div style="flex:1;"></div>'
        '<button onclick="jstClearAll()" style="padding:9px 16px;border-radius:var(--r-md);'
        'font-size:13px;font-weight:600;border:1px solid var(--line);background:var(--surface);'
        'color:var(--ink-soft);cursor:pointer;font-family:inherit;">Clear all</button>'
        '<button id="jst-bb" onclick="jstShowStaging()" style="padding:10px 18px;'
        'border-radius:var(--r-md);font-size:13.5px;font-weight:700;border:none;'
        'background:var(--accent);color:var(--accent-contrast);cursor:pointer;font-family:inherit;">'
        'Review selected &#8594;</button>'
        '</div></div>'
    )

    # ── JavaScript ────────────────────────────────────────────────────────────
    # Plain string (no f-string) keeps backslash escaping simple.
    # JS uses double quotes for strings; Python uses single quotes for this string.
    _js = (
        '(function(){'
        'window._jst_sel=window._jst_sel||new Set();'
        'window._jst_jobs=window._jst_jobs||{};'
        'var _sel=window._jst_sel,_jobs=window._jst_jobs;'
        'document.querySelectorAll(".jst-rc").forEach(function(c){'
        'var id=c.dataset.jstId;if(!id)return;'
        '_jobs[id]={title:c.dataset.jstTitle,company:c.dataset.jstCompany,'
        'salary:c.dataset.jstSalary,location:c.dataset.jstLocation,formId:c.dataset.jstForm};'
        '_sel.add(id);'
        '});'
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
        'var el=document.getElementById("jst-bc");if(el)el.textContent=n;'
        'var bl=document.getElementById("jst-bl");if(bl)bl.textContent=n===1?"job selected":"jobs selected";'
        'var bb=document.getElementById("jst-bb");if(bb)bb.textContent="Review "+n+" selected →";'
        '}'
        'window.jstToggle=function(id){'
        '_sel.has(id)?_sel.delete(id):_sel.add(id);_upd();'
        '};'
        'window.jstSelectAll=function(){'
        'Object.keys(_jobs).forEach(function(id){_sel.add(id);});_upd();'
        '};'
        'window.jstClearAll=function(){_sel.clear();_upd();};'
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
        '(container||document).querySelectorAll(".jst-rc").forEach(function(c){'
        'var id=c.dataset.jstId;if(!id||_jobs[id])return;'
        '_jobs[id]={title:c.dataset.jstTitle,company:c.dataset.jstCompany,'
        'salary:c.dataset.jstSalary,location:c.dataset.jstLocation,formId:c.dataset.jstForm};'
        '_sel.add(id);'
        '});_upd();'
        '};'
        'window.jstLoadMore=function(btn){'
        'var url=btn.getAttribute("data-next-url");if(!url)return;'
        'btn.disabled=true;btn.textContent="Loading…";'
        'fetch(url).then(function(r){return r.json();})'
        '.then(function(d){'
        'if(!d.ok){btn.disabled=false;btn.textContent="More jobs";alert("Failed: "+(d.error||"Unknown"));return;}'
        'var container=document.getElementById("jst-cards-container");'
        'var moreWrap=document.getElementById("jst-more-wrap");'
        'if(container&&d.cards_html){'
        'var tmp=document.createElement("div");'
        'tmp.innerHTML=d.cards_html;'
        'while(tmp.firstChild)container.insertBefore(tmp.firstChild,moreWrap);'
        'jstRegisterCards(container);'
        '}'
        'if(!d.has_more){'
        'if(moreWrap)moreWrap.style.display="none";'
        '}else{'
        'btn.setAttribute("data-next-url",d.next_url);'
        'btn.disabled=false;btn.textContent="More jobs";'
        '}'
        '})'
        '.catch(function(err){btn.disabled=false;btn.textContent="More jobs";alert("Request failed: "+err.message);});'
        '};'
        'window.jstEvaluateAll=function(){'
        'if(_sel.size===0)return;'
        'var jobs=[];'
        '_sel.forEach(function(id){'
        'var j=_jobs[id];if(!j||!j.formId)return;'
        'var f=document.getElementById(j.formId);if(!f)return;'
        'var fd=new FormData(f),obj={};'
        'fd.forEach(function(v,k){obj[k]=v;});'
        'jobs.push(obj);'
        '});'
        'if(!jobs.length){alert("No evaluable jobs found.");return;}'
        'var btn=document.getElementById("jst-eval-all-btn");'
        'var list=document.getElementById("jst-staging-list");'
        'if(btn){btn.disabled=true;btn.textContent="Scoring…";}'
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
        'if(!ids){alert("No jobs were successfully evaluated.");'
        'if(btn){btn.disabled=false;btn.textContent="Evaluate all";}return;}'
        'window.location="/review-queue?ids="+encodeURIComponent(ids);'
        '})'
        '.catch(function(err){alert("Request failed: "+err.message);'
        'if(btn){btn.disabled=false;btn.textContent="Evaluate all";}});'
        '};'
        '_upd();'
        '})();'
    )

    more_btn_html = ""
    if more_url:
        more_btn_html = (
            f'<div id="jst-more-wrap" style="text-align:center;padding:18px 0 6px;">'
            f'<button data-next-url="{escape(more_url)}" onclick="jstLoadMore(this)"'
            f' style="padding:10px 28px;border-radius:var(--r-md);font-size:13.5px;font-weight:700;'
            f'border:1px solid var(--line);background:var(--surface);color:var(--ink);'
            f'cursor:pointer;font-family:inherit;">More jobs</button>'
            f'</div>'
        )

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
        f'{more_btn_html}'
        f'</div>'
        f'{action_bar}'
        f'{staging_overlay}'
        f'<script>/* jst multi-select */{_js}</script>'
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
    ))


_register()
