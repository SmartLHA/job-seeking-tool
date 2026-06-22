"""UI utility helpers — pure functions.

Leaf module (LT-1 Step 3): imports only stdlib and :mod:`src.ui_state`. No domain
modules, no network, no file I/O. Every function takes data and returns data.

``raw_input_payload_from_form`` intentionally stays in ``job_hunt_ui`` because it
depends on the Reed source snapshot validator and is therefore not pure.
"""
from __future__ import annotations

import html
import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse



def reviewed_job_payload_from_form(form: dict[str, str]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_id": required_text(form, "job_id"),
        "job_title": required_text(form, "job_title"),
        "company": required_text(form, "company"),
        "description_raw": required_text(form, "description_raw"),
        "source_type": required_text(form, "source_type"),
        "source_ref": optional_text(form, "source_ref"),
        "url": optional_text(form, "job_url"),
        "location": optional_text(form, "location"),
        "work_mode": optional_text(form, "work_mode"),
        "employment_type": optional_text(form, "employment_type"),
        "required_skills": split_lines_or_commas(form.get("required_skills", "")),
        "preferred_skills": split_lines_or_commas(form.get("preferred_skills", "")),
        "required_years_experience": optional_float(form, "required_years_experience"),
        "nice_to_have_years_experience": optional_float(form, "nice_to_have_years_experience"),
        "domain": optional_text(form, "domain"),
        "notes": optional_text(form, "notes"),
        "salary_min_gbp": optional_int(form, "salary_min_gbp"),
        "salary_max_gbp": optional_int(form, "salary_max_gbp"),
    }
    return payload


def job_id_from_request_path(path: str) -> str | None:
    parsed = urlparse(path)
    if parsed.path == "/job":
        params = parse_qs(parsed.query)
        return params.get("job_id", [""])[0]
    if parsed.path.startswith("/job/"):
        job_id = parsed.path.removeprefix("/job/").strip().strip("/")
        return job_id or None
    return None


def create_select_nonce() -> str:
    # MT-7: stateless token. Nonce enforcement was removed — this is a local-only
    # server where an in-memory CSRF store gave no security benefit and produced
    # "Invalid or expired selection token" errors across dev-reloader restarts.
    # The token is still emitted as a hidden form field as a placeholder should
    # real CSRF protection ever be wanted; nothing validates it server-side.
    return secrets.token_urlsafe(24)


def render_select_options(options: list[str], selected: str) -> str:
    return "".join(
        f'<option value="{escape(option)}"{" selected" if option == selected else ""}>{escape(option.title())}</option>'
        for option in options
    )


def squash_whitespace(value: str) -> str:
    return " ".join((value or "").split())


def normalize_optional_int_text(value: str) -> str:
    text = (value or "").strip().replace(",", "")
    if not text:
        return ""
    try:
        number = int(float(text))
    except ValueError:
        return ""
    return str(max(0, number))


def format_salary_range(min_salary: int | None, max_salary: int | None) -> str:
    if min_salary is None and max_salary is None:
        return "Unknown"
    if min_salary is not None and max_salary is not None:
        return f"£{min_salary:,} – £{max_salary:,}"
    if min_salary is not None:
        return f"From £{min_salary:,}"
    return f"Up to £{max_salary:,}"


def default_form_values() -> dict[str, str]:
    return {
        "job_id": "",
        "input_method": "copied_text",
        "job_url": "",
        "source_type": "copied_text",
        "source_ref": "",
        "job_title": "",
        "company": "",
        "location": "",
        "work_mode": "",
        "employment_type": "",
        "required_years_experience": "",
        "nice_to_have_years_experience": "",
        "domain": "",
        "salary_min_gbp": "",
        "salary_max_gbp": "",
        "copied_text": "",
        "description_raw": "",
        "required_skills": "",
        "preferred_skills": "",
        "notes": "",
        "source_snapshot_json": "",
    }


def stringify_form_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)


def split_lines_or_commas(value: str) -> list[str]:
    parts = []
    for chunk in value.replace("\n", ",").split(","):
        cleaned = chunk.strip()
        if cleaned:
            parts.append(cleaned)
    return parts


def required_text(form: dict[str, str], key: str) -> str:
    value = form.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def optional_text(form: dict[str, str], key: str) -> str | None:
    value = form.get(key, "").strip()
    return value or None


def optional_float(form: dict[str, str], key: str) -> float | None:
    value = form.get(key, "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{key} must be numeric") from exc


def optional_int(form: dict[str, str], key: str) -> int | None:
    value = form.get(key, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc


def escape(value: Any) -> str:
    return html.escape("" if value is None else str(value))
