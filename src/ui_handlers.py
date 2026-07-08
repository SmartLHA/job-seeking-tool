"""Request handlers — standalone functions (LT-1 Step 5).

Each handler takes ``(req, config, responder)``: a parsed :class:`UIRequest`, the
server :class:`UIServerConfig`, and a :class:`UIResponder` for sending the reply.
No handler touches the raw HTTP object, so each is testable without a live
server. This module imports the render layer, pure utils, shared state and the
domain modules; it is imported by ``ui_routes`` (dispatch) and ``job_hunt_ui``.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

from src.ui_state import (
    _MAX_CV_SIZE_BYTES,
    _ALLOWED_CV_EXTENSIONS,
)
from src.ui_utils import (
    escape,
    default_form_values,
    form_values_from_reviewed_job,
    stringify_form_value,
    optional_text,
    reviewed_job_payload_from_form,
    create_select_nonce,
    render_select_options,
)
from src.ui_render import (
    ProfilePageViewModel,
    JobPageViewModel,
    ReviewQueueViewModel,
    render_page,
    render_home_page,
    render_job_page,
    render_keyword_match_panel,
    render_profile_page,
    render_review_queue_page,
    _render_sidebar,
    _render_profile_tab_section,
    _normalize_home_tab,
)

from src.job_hunt_orchestrator import run_local_evaluation_flow_from_payload
from src.job_hunt_parsing import parse_job_from_text, parse_job_from_url
from src.job_hunt_outcomes import ALLOWED_OUTCOME_STATUSES, allowed_next_statuses, create_outcome_record, update_outcome
from src.job_hunt_profile import load_candidate_profile, save_candidate_profile, ProfileValidationError, parse_cv_file, candidate_profile_from_dict
from src.job_hunt_models import JobPosting, Skill
from src.job_hunt_config import get_enabled_sources, DEFAULT_TAILORING_POLICY
from src.job_hunt_models import effective_decision
from src.job_hunt_tailoring import (
    select_relevant_evidence,
    tailor_cv,
    validate_tailored_cv,
    save_tailored_cv,
    load_latest_tailored_cv,
    EmptyTailoredCVError,
    TailoringValidationError,
)
from src.job_hunt_keyword_match import compute_keyword_match
from src.job_hunt_cover_letter import generate_cover_letter_text, save_cover_letter
from src.job_hunt_storage import (
    ensure_storage_layout,
    load_application_outcome,
    load_job_analysis,
    load_reviewed_job,
    save_application_outcome,
    save_job_analysis,
    save_reviewed_job,
)

from src.job_sources import reed_source as _reed_source
from src.job_hunt_saved_searches import (
    SavedSearch,
    SavedSearchError,
    SavedSearchNotFound,
    create_saved_search,
    delete_saved_search,
    list_saved_searches,
    load_saved_search,
    toggle_saved_search,
    update_last_run,
)


# MT-5: anchor profile storage to an absolute path derived from the project root
# (this file lives at <root>/src/ui_handlers.py) so reads/writes always hit the
# same `data/` directory regardless of the process's current working directory.
_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
_ALLOWED_PROFILE_ROOTS = [
    _DATA_ROOT / "demo_profile",
    _DATA_ROOT / "demo_profile2",
]


_PROFILE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _allowed_profile_dir(profile_id: str) -> Path | None:
    if not _PROFILE_ID_PATTERN.match(profile_id):
        return None
    candidate = _DATA_ROOT / profile_id
    for root in _ALLOWED_PROFILE_ROOTS:
        try:
            candidate.resolve().relative_to(root.resolve())
            return root / profile_id
        except ValueError:
            pass
    # Accept any profile_id inside data/ as long as it matches pattern
    # and doesn't escape the data/ directory
    try:
        candidate.resolve().relative_to(_DATA_ROOT.resolve())
        return candidate
    except ValueError:
        return None


def _index_db_path(config) -> Path:
    return Path(config.state_root) / "job_hunt_index.db"


_UPSERT_LOAD = object()  # sentinel: "load this piece from disk if not supplied"


def _upsert_job_to_index(config, job_id, *, reviewed_job=_UPSERT_LOAD,
                         analysis=_UPSERT_LOAD, outcome=_UPSERT_LOAD) -> None:
    """Canonical SQLite-index upsert (QW-7) — replaces 6 copy-pasted blocks.

    Any of ``reviewed_job`` / ``analysis`` / ``outcome`` may be passed by a caller
    that already has it in memory; anything left unset is loaded from disk by
    ``job_id``. Missing pieces become NULL columns. Non-fatal: logs and swallows
    errors so an index hiccup never breaks the user-facing flow.
    """
    try:
        from src.job_hunt_index import upsert_job
        if reviewed_job is _UPSERT_LOAD:
            try:
                reviewed_job = load_reviewed_job(job_id, config.state_root)
            except FileNotFoundError:
                reviewed_job = None
        if analysis is _UPSERT_LOAD:
            try:
                analysis = load_job_analysis(job_id, config.state_root)
            except FileNotFoundError:
                analysis = None
        if outcome is _UPSERT_LOAD:
            try:
                outcome = load_application_outcome(job_id, config.state_root)
            except FileNotFoundError:
                outcome = None
        upsert_job(_index_db_path(config), {
            "job_id": job_id,
            "job_title": getattr(reviewed_job, "job_title", None),
            "company": getattr(reviewed_job, "company", None),
            "location": getattr(reviewed_job, "location", None),
            "source": getattr(reviewed_job, "source_type", None),
            "match_score": getattr(analysis, "match_score", None),
            "decision": getattr(analysis, "decision", None),
            "user_decision": getattr(analysis, "user_decision", None),
            "ats_score": getattr(analysis, "ats_score", None),
            "tailoring_ready": getattr(analysis, "tailoring_ready", None),
            "status": outcome.status if outcome else "not_applied",
            "updated_at": outcome.updated_at if outcome else None,
            "salary_min": getattr(reviewed_job, "salary_min_gbp", None),
            "salary_max": getattr(reviewed_job, "salary_max_gbp", None),
        })
    except Exception as _idx_exc:
        logger.warning("Index upsert failed (non-fatal): %s", _idx_exc)


def handle_sources(req, config, responder) -> None:
    responder.send_json({"enabled": get_enabled_sources()})


def render_profile(req, config, responder, profile_id, *, parsed_cv_text=None, parsed_filename=None, errors=None, form_values=None, flash=None):
    profile_dir = _allowed_profile_dir(profile_id)
    if profile_dir is None:
        responder.send_html(render_page("Invalid profile", "<p>Invalid profile ID.</p>", model_label=config.model_label), status=HTTPStatus.BAD_REQUEST)
        return

    profile_json_path = profile_dir / "candidate_profile.json"
    try:
        profile_obj = load_candidate_profile(profile_json_path)
    except FileNotFoundError:
        # Fall back to startup profile when profile_id matches its stem
        # (e.g. profile_id="mic_profile" and config.profile_path="data/mic_profile.json")
        if config.profile_path.stem == profile_id and config.profile_path.exists():
            try:
                profile_obj = load_candidate_profile(config.profile_path)
            except Exception as _exc:
                logger.warning("Could not load fallback profile %s: %s", config.profile_path, _exc)
                profile_obj = None
        else:
            profile_obj = None

    page = render_profile_page(
        profile_id=profile_id,
        vm=_build_profile_page_vm(profile_obj),
        parsed_cv_text=parsed_cv_text,
        parsed_filename=parsed_filename,
        errors=errors or {},
        form_values=form_values,
        flash=flash,
        model_label=config.model_label,
        enabled_sources=get_enabled_sources(),
    )
    responder.send_html(page)


def handle_parse_cv(req, config, responder):
    content_type = req.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        responder.send_json({"ok": False, "error": "Expected multipart/form-data"}, status=HTTPStatus.BAD_REQUEST)
        return

    try:
        form_data = parse_multipart_form(req)
    except Exception as exc:
        responder.send_json({"ok": False, "error": f"Failed to parse form data: {exc}"}, status=HTTPStatus.BAD_REQUEST)
        return

    file_item = form_data.get("cv_file")
    if not file_item:
        responder.send_json({"ok": False, "error": "No cv_file field provided"}, status=HTTPStatus.BAD_REQUEST)
        return

    filename = file_item.get("filename", "")
    content = file_item.get("content", b"")

    # Extension check
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_CV_EXTENSIONS:
        responder.send_json({"ok": False, "error": f"Unsupported file type: {ext}. Accepted: .txt, .pdf, .docx"}, status=HTTPStatus.BAD_REQUEST)
        return

    # Size check
    if len(content) > _MAX_CV_SIZE_BYTES:
        responder.send_json({"ok": False, "error": "File too large. Maximum size is 5 MB."}, status=HTTPStatus.PAYLOAD_TOO_LARGE)
        return

    # MIME check (basic)
    content_str = content[:20].decode("latin-1", errors="replace")
    if ext == ".pdf" and not content_str.startswith("%PDF"):
        responder.send_json({"ok": False, "error": "File does not appear to be a valid PDF"}, status=HTTPStatus.BAD_REQUEST)
        return

    # Write to a proper OS temp file (avoids CWD dependency)
    import tempfile
    fd, temp_path_str = tempfile.mkstemp(suffix=ext)
    temp_path = Path(temp_path_str)
    try:
        with open(fd, "wb") as fh:
            fh.write(content)
        text = parse_cv_file(temp_path)
    except Exception as exc:
        responder.send_json({"ok": False, "error": f"Could not extract text from file: {exc}"}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
        return
    finally:
        temp_path.unlink(missing_ok=True)

    # Extract skills from CV text so the profile skills table can be pre-populated.
    # Uses LLM (Ollama) when available for open-ended extraction; keyword fallback otherwise.
    skill_extraction_warning: str | None = None
    try:
        from src.job_hunt_parsing import extract_skills_from_cv
        suggested_skills, skill_extraction_warning = extract_skills_from_cv(text)
    except Exception as _ske:
        suggested_skills = []
        skill_extraction_warning = f"Skill extraction failed: {_ske}"

    # Auto-save CV to profile if profile_id was included in the upload form.
    # This means the user never has to click "Save Profile" just to persist their CV.
    auto_saved = False
    profile_id_item = form_data.get("profile_id")
    if profile_id_item:
        _pid = profile_id_item.get("content", b"").decode("utf-8").strip()
        if _pid:
            try:
                _profile_dir = _allowed_profile_dir(_pid)
                if _profile_dir is not None:
                    _profile_dir.mkdir(parents=True, exist_ok=True)
                    _profile_json = _profile_dir / "candidate_profile.json"
                    # Load existing profile (fall back to startup profile if dir version missing)
                    try:
                        _profile_obj = load_candidate_profile(_profile_json)
                    except FileNotFoundError:
                        if config.profile_path.stem == _pid and config.profile_path.exists():
                            _profile_obj = load_candidate_profile(config.profile_path)
                        else:
                            _profile_obj = candidate_profile_from_dict({"candidate_id": _pid})
                    # Write CV file alongside the profile
                    _cv_ext = ext if ext in _ALLOWED_CV_EXTENSIONS else ".txt"
                    _docs_dir = _profile_dir / "docs"
                    _docs_dir.mkdir(parents=True, exist_ok=True)
                    _cv_path = _docs_dir / f"master_cv{_cv_ext}"
                    _cv_path.write_text(text, encoding="utf-8")
                    # Update only the CV fields — leave everything else intact
                    _profile_obj.master_cv_text = text
                    _profile_obj.master_cv_ref = str(_cv_path.resolve())
                    save_candidate_profile(_profile_obj, _profile_json)
                    # Keep startup profile in sync
                    if config.profile_path.stem == _pid:
                        save_candidate_profile(_profile_obj, config.profile_path)
                    auto_saved = True
            except Exception as _save_exc:
                logger.warning("CV auto-save failed for profile_id=%r: %s", _pid, _save_exc)
                _auto_save_error = str(_save_exc)

    responder.send_json({
        "ok": True,
        "master_cv_text": text,
        "filename": filename,
        "suggested_skills": suggested_skills,
        "skill_extraction_warning": skill_extraction_warning,
        "auto_saved": auto_saved,
        "auto_save_error": locals().get("_auto_save_error"),
    })


def handle_save_profile(req, config, responder):
    form = req.form
    profile_id = form.get("profile_id", "").strip()
    if not profile_id:
        responder.send_json({"ok": False, "errors": {"profile_id": "Profile ID is required"}}, status=HTTPStatus.BAD_REQUEST)
        return

    profile_dir = _allowed_profile_dir(profile_id)
    if profile_dir is None:
        responder.send_json({"ok": False, "errors": {"profile_id": "Invalid profile ID"}}, status=HTTPStatus.BAD_REQUEST)
        return

    profile_json_path = profile_dir / "candidate_profile.json"

    # Build dict from form, then validate via candidate_profile_from_dict
    payload: dict[str, Any] = {}
    for field in ("name", "target_roles", "locations", "remote_preference",
                  "salary_floor_gbp", "right_to_work_uk",
                  "years_experience", "industries", "achievements",
                  "certifications", "master_cv_ref", "master_cv_text"):
        val = form.get(field, "").strip()
        if field == "achievements":
            # Textarea uses one-per-line; fall back to comma-split for old data
            if "\n" in val:
                payload[field] = [s.strip() for s in val.splitlines() if s.strip()]
            else:
                payload[field] = [s.strip() for s in val.split(",") if s.strip()] if val else []
        elif field in ("target_roles", "locations", "industries", "certifications"):
            payload[field] = [s.strip() for s in val.split(",") if s.strip()] if val else []
        elif field == "salary_floor_gbp":
            payload[field] = int(float(val)) if val else None
        elif field == "years_experience":
            payload[field] = float(val) if val else None
        elif field == "right_to_work_uk":
            payload[field] = True if val.lower() in ("true", "1", "yes") else (False if val.lower() in ("false", "0", "no") else None)
        else:
            payload[field] = val or None

    # Skills: prefer skills_json (list[dict] from JS table), fall back to comma-split string
    skills_json_raw = form.get("skills_json", "").strip()
    if skills_json_raw:
        try:
            payload["skills"] = json.loads(skills_json_raw)
        except (json.JSONDecodeError, ValueError) as _skj_exc:
            logger.warning("Could not parse skills_json field: %s — defaulting to empty", _skj_exc)
            payload["skills"] = []
    else:
        skills_val = form.get("skills", "").strip()
        payload["skills"] = [s.strip() for s in skills_val.split(",") if s.strip()] if skills_val else []

    payload["candidate_id"] = profile_id

    # Daily Digest (D3) settings — preserve current values when the form omits a field
    # so editing the rest of the profile never silently resets digest prefs.
    try:
        _existing = load_candidate_profile(profile_json_path)
    except Exception:
        _existing = None
    if _existing is None and config.profile_path.stem == profile_id:
        try:
            _existing = load_candidate_profile(config.profile_path)
        except Exception:
            _existing = None

    def _digest_default(attr, fallback):
        return getattr(_existing, attr, fallback) if _existing is not None else fallback

    for _bf, _fb in (("digest_enabled", True), ("digest_llm_enabled", True)):
        _v = form.get(_bf, "").strip()
        payload[_bf] = _v if _v else str(_digest_default(_bf, _fb)).lower()
    for _nf, _fb in (("digest_threshold", 70), ("digest_max_per_source", 50),
                     ("digest_max_llm_per_run", 10), ("digest_llm_rpm", 4),
                     ("digest_llm_rpd", 200), ("digest_llm_batch_size", 4),
                     ("digest_llm_batch_interval_min", 15)):
        _v = form.get(_nf, "").strip()
        payload[_nf] = _v if _v else _digest_default(_nf, _fb)
    _rt = form.get("digest_run_time", "").strip()
    payload["digest_run_time"] = _rt if _rt else _digest_default("digest_run_time", "07:00")

    try:
        profile_obj = candidate_profile_from_dict(payload)
    except ProfileValidationError as exc:
        responder.send_json({"ok": False, "errors": {"form": str(exc)}}, status=HTTPStatus.BAD_REQUEST)
        return

    profile_dir.mkdir(parents=True, exist_ok=True)
    save_candidate_profile(profile_obj, profile_json_path)

    # If master_cv_text was provided, save master CV file
    if profile_obj.master_cv_text:
        docs_dir = profile_dir / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        cv_ext = ".txt"
        if form.get("_cv_filename"):
            cv_ext = Path(form["_cv_filename"]).suffix.lower()
            if cv_ext not in _ALLOWED_CV_EXTENSIONS:
                cv_ext = ".txt"
        cv_path = docs_dir / f"master_cv{cv_ext}"
        cv_path.write_text(profile_obj.master_cv_text, encoding="utf-8")
        # Store as absolute path to avoid ambiguous relative resolution
        profile_obj.master_cv_ref = str(cv_path.resolve())
        save_candidate_profile(profile_obj, profile_json_path)

    # Keep startup profile in sync when profile_id matches its stem
    # so that tailor/cover-letter/evaluate all see the latest data
    if config.profile_path.stem == profile_id:
        save_candidate_profile(profile_obj, config.profile_path)

    # Build flash message so the user knows exactly what was saved
    cv_chars = len(profile_obj.master_cv_text) if profile_obj.master_cv_text else 0
    cv_note = f"CV: {cv_chars:,} chars on file." if cv_chars else "No CV on file — upload a CV file above."
    flash_msg = f"Profile saved. {cv_note}"
    from urllib.parse import quote as _quote
    responder.redirect(f"/profile?profile_id={profile_id}&flash={_quote(flash_msg)}")


def parse_multipart_form(req):
    """Parse a minimal multipart/form-data body."""
    content_type = req.headers.get("Content-Type", "")
    # MT-4: a multipart Content-Type without a boundary= parameter used to crash
    # with a cryptic "not enough values to unpack"; check explicitly and raise a
    # clear error that the handler surfaces to the browser.
    if "boundary=" not in content_type:
        raise ValueError("multipart/form-data request is missing the boundary parameter")
    boundary = content_type.split("boundary=", 1)[1].strip().strip('"').encode()

    body = req.raw_body

    result: dict[str, dict[str, Any]] = {}
    parts = body.split(b"--" + boundary)
    for part in parts:
        part = part.strip()
        if not part or part.startswith(b"--\r\n") or part == b"--":
            continue
        # Split headers from body (split on \r\n\r\n)
        idx = part.find(b"\r\n\r\n")
        if idx < 0:
            continue
        header_block = part[:idx].decode("latin-1")
        body_bytes = part[idx + 4:]
        # Get filename from Content-Disposition
        filename = None
        field_name = None
        for line in header_block.split("\r\n"):
            if ";" in line:
                parts_h = line.split(";")
                for p in parts_h:
                    p = p.strip()
                    if p.startswith("name=") and '"' in p:
                        field_name = p.split("=")[1].strip('"')
                    if p.startswith("filename=") and '"' in p:
                        filename = p.split("=")[1].strip('"')
        if field_name:
            result[field_name] = {"filename": filename or "", "content": body_bytes.rstrip(b"\r\n")}
    return result


def render_home(req, config, responder, *, values=None, error=None, tab='search', search_values=None, reed_results=None, reed_error=None, evaluate_notice=None):
    tab = _normalize_home_tab(tab)
    profile = load_candidate_profile(config.profile_path)
    history = load_recent_job_history(config.state_root)
    profile_tab_html = _render_profile_tab_section(tab)
    search_nonce = create_select_nonce() if reed_results is not None and not reed_error else None
    search_tab_html = _render_search_jobs_tab(
        search_values=search_values,
        reed_results=reed_results,
        reed_error=reed_error,
        reed_select_nonce=search_nonce,
    )
    page = render_home_page(
        profile_name=profile.name or profile.candidate_id,
        profile_target_roles=list(profile.target_roles or []),
        history=history,
        values=values or default_form_values(),
        error=error,
        search_tab_html=search_tab_html,
        tab=tab,
        profile_tab_html=profile_tab_html,
        evaluate_notice=evaluate_notice,
        model_label=config.model_label,
    )
    responder.send_html(page)


def render_job(req, config, responder, job_id, *, flash=None, flash_kind='success', embed=None):
    if not job_id.strip():
        responder.redirect("/")
        return

    # ?embed=1 → render without sidebar (used by review-queue iframe).
    # POST handlers can pass embed= explicitly since their path has no query.
    if embed is None:
        _qp = parse_qs(urlparse(req.path).query)
        embed = _qp.get("embed", [""])[0] == "1"

    try:
        reviewed_job = load_reviewed_job(job_id, config.state_root)
    except FileNotFoundError:
        responder.send_html(
            render_page("Job not found", "<p>No saved job was found for that id.</p>", model_label=config.model_label),
            status=HTTPStatus.NOT_FOUND,
        )
        return
    try:
        analysis = load_job_analysis(job_id, config.state_root)
    except FileNotFoundError:
        analysis = None
    try:
        outcome = load_application_outcome(job_id, config.state_root)
    except FileNotFoundError:
        outcome = None

    page = render_job_page(_build_job_page_vm(
        reviewed_job, analysis, outcome,
        flash=flash, flash_kind=flash_kind, embed=embed,
        model_label=config.model_label,
    ))
    responder.send_html(page)


def handle_evaluate_form(req, config, responder, job_id):
    """GET /job/<id>/evaluate-form — reload a saved job into the Evaluate form.

    Bridges the bookmark -> evaluate gap: a job saved via POST /jobs/save has no
    analysis, so we prefill the manual Evaluate tab with its stored fields for
    explicit user review, preserving job_id so the existing POST /evaluate path
    updates the same record. Read-only (no side effects).
    """
    if not job_id.strip():
        responder.redirect("/")
        return
    try:
        reviewed_job = load_reviewed_job(job_id, config.state_root)
    except FileNotFoundError:
        responder.send_html(
            render_page("Job not found", "<p>No saved job was found for that id.</p>", model_label=config.model_label),
            status=HTTPStatus.NOT_FOUND,
        )
        return
    values = form_values_from_reviewed_job(reviewed_job)
    render_home(
        req, config, responder,
        values=values, tab="evaluate",
        evaluate_notice="Review the saved details below, then Evaluate. Add any missing skills or description first.",
    )


def handle_job_explain(req, config, responder, job_id):
    """GET /job/{id}/explain — return LLM explanation as JSON."""
    from src.job_hunt_llm import explain_job_match_with_llm
    if not job_id.strip():
        responder.send_json({"ok": False, "error": "Missing job id"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        reviewed_job = load_reviewed_job(job_id, config.state_root)
    except FileNotFoundError:
        responder.send_json({"ok": False, "error": "Job not found"}, status=HTTPStatus.NOT_FOUND)
        return
    try:
        analysis = load_job_analysis(job_id, config.state_root)
    except FileNotFoundError:
        responder.send_json({"ok": False, "error": "No analysis found for this job"}, status=HTTPStatus.NOT_FOUND)
        return
    try:
        profile = load_candidate_profile(config.profile_path)
    except Exception as exc:
        responder.send_json({"ok": False, "error": f"Could not load profile: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    explanation, explain_error = explain_job_match_with_llm(profile, reviewed_job, analysis)
    if explanation is None:
        responder.send_json({"ok": False, "error": explain_error or "LLM unavailable"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
        return
    responder.send_json({"ok": True, **explanation})


def _take_skip_param_keys(search_values: dict) -> tuple[str, str]:
    """Return the (take_key, skip_key) param names a source uses for paging.

    Reed/Adzuna emit camelCase ``resultsToTake``/``resultsSkip``; LinkedIn emits
    snake_case ``results_to_take``/``results_skip``. Detect by which take key the
    source's normaliser produced."""
    if "resultsToTake" in search_values:
        return "resultsToTake", "resultsSkip"
    return "results_to_take", "results_skip"


def _parse_exclude_terms(raw: str) -> list[str]:
    """Split the exclude-keywords field into normalised terms.

    Accepts a comma-separated string (multiple values); each term is trimmed and
    casefolded, blanks dropped, duplicates removed while preserving order."""
    seen: set[str] = set()
    terms: list[str] = []
    for part in (raw or "").split(","):
        term = " ".join(part.casefold().split())
        if term and term not in seen:
            seen.add(term)
            terms.append(term)
    return terms


def _apply_exclude_filter(results, raw_exclude: str):
    """Drop results whose job title contains any excluded term (substring, case-
    insensitive). Returns (kept_results, excluded_count). Matches title only so a
    passing mention in the description never over-filters."""
    terms = _parse_exclude_terms(raw_exclude)
    if not terms or not results:
        return results, 0
    kept = []
    excluded = 0
    for r in results:
        title = " ".join(str(r.get("title") or "").casefold().split())
        if any(t in title for t in terms):
            excluded += 1
        else:
            kept.append(r)
    return kept, excluded


def handle_source_search(req, config, responder, source_id):
    params = req.query
    from src.job_sources.source_registry import get_source
    source = get_source(source_id)
    if source is None:
        responder.send_html(
            render_page("Unknown source", f"<p>No registered job source: <code>{escape(source_id)}</code>.</p>", model_label=config.model_label),
            status=HTTPStatus.NOT_FOUND,
        )
        return
    from urllib.parse import urlencode as _urlencode_ss
    search_values = source.normalize_search_params(params)
    search_values["_source_id"] = source_id  # carried through to _render_search_jobs_tab
    # Exclude-keywords: normalisers drop unknown keys, so read the raw field here
    # and carry it in search_values so it survives form re-render and paging.
    exclude_raw = (params.get("excludeKeywords") or "").strip()
    if exclude_raw:
        search_values["excludeKeywords"] = exclude_raw
    error: str | None = None
    results: list[dict[str, Any]] = []
    try:
        results = source.search_handler(search_values)
    except Exception as exc:
        error = f"{source.display_name} search failed: {exc}. Manual fallback is still available."
    # Filter out not-interested jobs (display-only: paging math below stays on
    # the RAW count so the skip cursor still advances one full source page).
    _raw_count = len(results)
    if not error and results:
        try:
            from src.job_hunt_not_interested import filter_results as _filter_ni
            results, _hidden_ct = _filter_ni(results, state_root=config.state_root)
            if _hidden_ct:
                search_values["_hidden_count"] = str(_hidden_ct)
        except Exception as exc:  # never let the hide-store break search
            logger.warning("not-interested filter failed: %s", exc)
    # Exclude-keyword title filter (display-only, same as the hide filter).
    if not error and results:
        results, _excl_ct = _apply_exclude_filter(results, exclude_raw)
        if _excl_ct:
            search_values["_excluded_count"] = str(_excl_ct)
    # Build "More jobs" URL for ANY source: same params, skip cursor advanced by
    # one page. Sources differ in param naming (Reed/Adzuna use camelCase
    # resultsToTake/resultsSkip; LinkedIn uses snake_case results_to_take/
    # results_skip), so pick whichever the source's normaliser emitted.
    take_key, skip_key = _take_skip_param_keys(search_values)
    try:
        _take = int(search_values.get(take_key, "10") or "10")
    except (TypeError, ValueError):
        _take = 10
    if not error and _take > 0 and _raw_count >= _take:
        try:
            _cur_skip = int(search_values.get(skip_key, "0") or "0")
        except (TypeError, ValueError):
            _cur_skip = 0
        _more_params = {
            str(k): str(v) for k, v in search_values.items()
            if not str(k).startswith("_") and k != skip_key
        }
        _more_params[skip_key] = str(_cur_skip + _take)
        search_values["_more_url"] = f"/search/{source_id}/more?" + _urlencode_ss(_more_params)
    render_home(req, config, responder, tab="search", search_values=search_values, reed_results=results, reed_error=error)


def handle_source_select(req, config, responder, source_id):
    form = req.form
    from src.job_sources.source_registry import get_source
    source = get_source(source_id)
    if source is None:
        responder.send_html(
            render_page("Unknown source", f"<p>No registered job source: <code>{escape(source_id)}</code>.</p>", model_label=config.model_label),
            status=HTTPStatus.NOT_FOUND,
        )
        return
    try:
        values = source.select_handler(form, config)
    except ValueError as exc:
        responder.send_html(
            render_page("Invalid selection", f"<p>{escape(str(exc))}</p>", model_label=config.model_label),
            status=HTTPStatus.BAD_REQUEST,
        )
        return
    render_home(req, config, responder, 
        values=values,
        tab="evaluate",
        evaluate_notice=f"This form was prefilled from a {source.display_name} search result. Review and edit the fields before clicking Evaluate.",
    )


def handle_evaluate(req, config, responder):
    form = req.form
    values = {**default_form_values(), **form}
    try:
        reviewed_job_payload = reviewed_job_payload_from_form(form)
        raw_input_payload = raw_input_payload_from_form(form, reviewed_job_payload)
        result = run_local_evaluation_flow_from_payload(
            profile_path=config.profile_path,
            reviewed_job_payload=reviewed_job_payload,
            state_root=config.state_root,
            report_dir=config.report_dir,
            raw_input_payload=raw_input_payload,
            raw_input_id=reviewed_job_payload["job_id"],
        )
    except Exception as exc:
        render_home(req, config, responder, values=values, error=str(exc), tab="evaluate")
        return

    render_result(req, config, responder, result)


def render_result(req, config, responder, result):
    try:
        outcome = load_application_outcome(result.reviewed_job.job_id, config.state_root)
    except FileNotFoundError:
        outcome = None
    # Upsert hook (QW-7)
    _upsert_job_to_index(config, result.reviewed_job.job_id, reviewed_job=result.reviewed_job, analysis=result.analysis, outcome=outcome)
    page = render_job_page(_build_job_page_vm(
        result.reviewed_job, result.analysis, outcome,
        flash="Job evaluated and saved locally.", flash_kind="success",
        model_label=config.model_label,
    ))
    responder.send_html(page)


def handle_prefill(req, config, responder):
    form = req.form
    mode = form.get("prefill_mode", "").strip()
    try:
        if mode == "paste":
            payload = parse_job_from_text(form.get("job_text", ""))
        elif mode == "url":
            payload = parse_job_from_url(form.get("job_url", ""))
        else:
            raise ValueError("prefill_mode must be paste or url")
    except Exception as exc:
        responder.send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        return

    values = default_form_values()
    values.update({key: stringify_form_value(value) for key, value in payload.items() if key in values})
    if mode == "paste":
        values["input_method"] = "copied_text"
        values["copied_text"] = form.get("job_text", "")
        values["source_type"] = "copied_text"
        values["source_ref"] = "manual"
    else:
        submitted_url = form.get("job_url", "").strip()
        values["input_method"] = "url"
        values["job_url"] = submitted_url
        values["source_type"] = "url"
        values["source_ref"] = submitted_url or values.get("source_ref", "")
    responder.send_json({"ok": True, "values": values})


def handle_job_submit(req, config, responder):
    form = req.form
    job_id = form.get("job_id", "").strip()
    if not job_id:
        title_part = form.get("job_title", "").strip() or "job"
        company_part = form.get("company", "").strip() or "unknown"
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        import re
        slug = re.sub(r"[^a-z0-9]+", "-", (title_part + "-" + company_part).lower()).strip("-")
        job_id = f"{slug}-{ts}"
        form = {**form, "job_id": job_id}

    # Build and validate reviewed job payload
    try:
        reviewed_job_payload = reviewed_job_payload_from_form(form)
    except ValueError as exc:
        responder.send_json({"ok": False, "errors": {"form": str(exc)}}, status=HTTPStatus.BAD_REQUEST)
        return

    raw_input_payload = raw_input_payload_from_form(form, reviewed_job_payload)

    try:
        result = run_local_evaluation_flow_from_payload(
            profile_path=config.profile_path,
            reviewed_job_payload=reviewed_job_payload,
            state_root=config.state_root,
            report_dir=config.report_dir,
            raw_input_payload=raw_input_payload,
            raw_input_id=reviewed_job_payload["job_id"],
        )
    except Exception as exc:
        responder.send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
        return

    # Upsert hook (QW-7)
    _upsert_job_to_index(config, result.reviewed_job.job_id, reviewed_job=result.reviewed_job, analysis=result.analysis)

    # Redirect to GET /job/{job_id} — the existing result page
    responder.redirect(f"/job/{result.reviewed_job.job_id}")


def handle_outcome(req, config, responder):
    form = req.form
    job_id = form.get("job_id", "").strip()
    if not job_id:
        responder.redirect("/")
        return

    status = form.get("status", "").strip()
    notes = form.get("notes", "")
    embed = form.get("embed", "") == "1"
    try:
        try:
            current = load_application_outcome(job_id, config.state_root)
            outcome = update_outcome(current, status=status, notes=notes)
        except FileNotFoundError:
            outcome = create_outcome_record(job_id, notes="Initial local tracking record")
            if status != outcome.status or (notes or "").strip():
                outcome = update_outcome(outcome, status=status, notes=notes)
        save_application_outcome(outcome, config.state_root)
    except Exception as exc:
        render_job(req, config, responder, job_id, flash=f"Outcome update failed: {exc}", flash_kind="error", embed=embed)
        return

    # Upsert hook (QW-7)
    _upsert_job_to_index(config, job_id, outcome=outcome)

    render_job(req, config, responder, job_id, flash="Outcome updated.", flash_kind="success", embed=embed)


def handle_decision_override(req, config, responder, job_id):
    raw = req.raw_body.decode("utf-8")
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        responder.send_json({"error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
        return

    if "user_decision" not in payload:
        responder.send_json({"error": "user_decision is required"}, status=HTTPStatus.BAD_REQUEST)
        return

    user_decision = payload["user_decision"]
    if user_decision is not None and user_decision not in ("apply", "review", "skip"):
        responder.send_json({"error": "user_decision must be apply, review, skip, or null"}, status=HTTPStatus.BAD_REQUEST)
        return

    note = payload.get("note")

    try:
        analysis = load_job_analysis(job_id, config.state_root)
    except FileNotFoundError:
        responder.send_json({"error": f"Job analysis not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
        return

    import dataclasses
    analysis = dataclasses.replace(
        analysis,
        user_decision=user_decision,
        user_decision_note=note,
    )
    save_job_analysis(analysis, config.state_root)

    # Upsert hook (QW-7)
    _upsert_job_to_index(config, job_id, analysis=analysis)

    updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    responder.send_json({
        "job_id": job_id,
        "engine_decision": analysis.decision,
        "user_decision": analysis.user_decision,
        "updated_at": updated_at,
    })


def handle_add_gap_skills(req, config, responder, job_id):
    """POST /job/{id}/add-gap-skills — append selected gap skills to the active profile."""
    raw = req.raw_body.decode("utf-8")
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        responder.send_json({"ok": False, "error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
        return

    skills_input = payload.get("skills", [])
    if not isinstance(skills_input, list):
        responder.send_json({"ok": False, "error": "'skills' must be a list"}, status=HTTPStatus.BAD_REQUEST)
        return

    # Normalise: strip, deduplicate, drop empty, and cap length (QW-9 — bound
    # unbounded strings before they accumulate in the profile JSON).
    _SKILL_NAME_MAX = 120
    incoming = list(dict.fromkeys(
        s.strip()[:_SKILL_NAME_MAX]
        for s in skills_input if isinstance(s, str) and s.strip()
    ))
    if not incoming:
        responder.send_json({"ok": True, "added": [], "skipped": []})
        return

    # Load the active profile
    profile_path = config.profile_path
    try:
        profile_obj = load_candidate_profile(profile_path)
    except FileNotFoundError:
        responder.send_json({"ok": False, "error": "Profile not found — save your profile first"}, status=HTTPStatus.NOT_FOUND)
        return

    existing_names = {s.name.lower() for s in profile_obj.skills}
    added: list[str] = []
    skipped: list[str] = []
    new_skills = list(profile_obj.skills)  # copy
    for skill_name in incoming:
        if skill_name.lower() in existing_names:
            skipped.append(skill_name)
        else:
            new_skills.append(Skill(name=skill_name, level="unspecified"))
            existing_names.add(skill_name.lower())
            added.append(skill_name)

    if added:
        import dataclasses
        updated_profile = dataclasses.replace(profile_obj, skills=new_skills)
        save_candidate_profile(updated_profile, profile_path)
        logger.info("Added %d gap skill(s) to profile for job %s: %s", len(added), job_id, added)

    responder.send_json({"ok": True, "added": added, "skipped": skipped})


def handle_ai_review_cv(req, config, responder, job_id):
    """POST /job/{id}/ai-review-cv — Gemini lightly rewrites the master CV for this job."""
    from src.job_hunt_llm import ai_review_cv_with_llm

    # Load analysis
    try:
        analysis = load_job_analysis(job_id, config.state_root)
    except FileNotFoundError:
        responder.send_json({"ok": False, "error": f"Job analysis not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
        return

    # Decision gate: same as tailor (skip = blocked)
    decision = effective_decision(analysis)
    if decision == "skip":
        responder.send_json({"ok": False, "error": "Skipped jobs cannot have CV reviewed"}, status=HTTPStatus.FORBIDDEN)
        return

    # Load job
    try:
        job = load_reviewed_job(job_id, config.state_root)
    except FileNotFoundError:
        responder.send_json({"ok": False, "error": f"Reviewed job not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
        return

    # Load profile + CV text
    try:
        profile = load_candidate_profile(config.profile_path)
    except Exception as exc:
        responder.send_json({"ok": False, "error": f"Could not load profile: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        return

    cv_text: str | None = profile.master_cv_text
    if not cv_text:
        if profile.master_cv_ref:
            try:
                from src.job_hunt_profile import load_master_cv
                cv_ref_path = Path(profile.master_cv_ref)
                if not cv_ref_path.is_absolute():
                    cv_ref_path = config.profile_path.parent / cv_ref_path
                cv_text = load_master_cv(cv_ref_path)
            except Exception as exc:
                responder.send_json({"ok": False, "error": f"CV file could not be read: {exc}. Re-upload on the Profile page."}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                return
        else:
            responder.send_json({"ok": False, "error": "No master CV on profile. Upload your CV on the Profile page first."}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
            return

    # Call LLM
    result, error, model_used = ai_review_cv_with_llm(cv_text, profile, job, analysis)
    if result is None:
        responder.send_json({"ok": False, "error": error or "AI CV review failed"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        return

    reviewed_cv = result["reviewed_cv"]
    changes = result["changes"]

    # Save to tailored_cvs/{job_id}_ai_reviewed.md
    try:
        from src.job_hunt_config import DEFAULT_TAILORING_POLICY
        output_dir = DEFAULT_TAILORING_POLICY.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        save_path = output_dir / f"{job_id}_ai_reviewed.md"
        save_path.write_text(
            f"<!-- ai_reviewed: true | model: {model_used} | profile_id: {profile.candidate_id} -->\n{reviewed_cv.strip()}\n",
            encoding="utf-8",
        )
        logger.info("AI-reviewed CV saved to %s", save_path)
    except Exception as exc:
        logger.warning("Could not save AI-reviewed CV (non-fatal): %s", exc)
        save_path = None

    responder.send_json({
        "ok": True,
        "reviewed_cv": reviewed_cv,
        "changes": changes,
        "saved_path": str(save_path) if save_path else None,
        "model_used": model_used or "unknown",
    })


# F1 v2 — serialize the load→replace→save of each job's analysis so a double-click
# or a recheck racing a re-evaluation can't interleave partial writes. Process-local
# only: correct for the single-user local server, not multi-process.
_ATS_RECHECK_LOCKS: "defaultdict[str, threading.Lock]" = defaultdict(threading.Lock)


def handle_ats_recheck(req, config, responder, job_id):
    """POST /job/{id}/ats-recheck — re-score keyword match against the latest tailored CV."""
    with _ATS_RECHECK_LOCKS[job_id]:
        # Tailored CV first (path-safety / empty-file gates) before any state read.
        try:
            tailored = load_latest_tailored_cv(job_id)
        except EmptyTailoredCVError:
            responder.send_json(
                {"ok": False, "error": "Tailored CV is empty — re-tailor your CV first."},
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
            return
        except ValueError:
            responder.send_json({"ok": False, "error": f"Invalid job id: {job_id}"}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            reviewed_job = load_reviewed_job(job_id, config.state_root)
        except FileNotFoundError:
            responder.send_json({"ok": False, "error": f"Reviewed job not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            analysis = load_job_analysis(job_id, config.state_root)
        except FileNotFoundError:
            responder.send_json({"ok": False, "error": "Evaluate this job first."}, status=HTTPStatus.NOT_FOUND)
            return

        if tailored is None:
            responder.send_json(
                {"ok": False, "error": "No tailored CV saved yet — tailor your CV first."},
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
            return

        km = compute_keyword_match(tailored, list(reviewed_job.required_skills), list(reviewed_job.preferred_skills))

        # Seed the baseline from the stored master rate on the first re-check; keep it
        # thereafter so the delta always reads "was {master} → now {tailored}".
        baseline = (
            analysis.keyword_match_baseline_rate
            if analysis.keyword_match_baseline_rate is not None
            else analysis.keyword_match_rate
        )

        updated = dataclasses.replace(
            analysis,
            keyword_match_rate=km.match_rate,
            keywords_required_missing=km.required_missing,
            keywords_preferred_missing=km.preferred_missing,
            keywords_overused=km.overused,
            keyword_match_baseline_rate=baseline,
            keyword_match_source="tailored",
        )
        save_job_analysis(updated, config.state_root)

    # Render the panel through the SAME derived view-model path used on reload (H1),
    # so the chips before and after a refresh are identical.
    panel_html = render_keyword_match_panel(
        job_id=job_id, **_keyword_match_vm_fields(reviewed_job, updated)
    )
    responder.send_json({"ok": True, "rate": km.match_rate, "baseline": baseline, "panel_html": panel_html})


def handle_get_jobs(req, config, responder):
    from src.job_hunt_index import query_jobs_list
    jobs = query_jobs_list(_index_db_path(config))
    responder.send_json({"jobs": jobs})


def handle_get_board(req, config, responder):
    from src.job_hunt_index import query_board
    board = query_board(_index_db_path(config))
    responder.send_json(board)


def handle_get_board_view(req, config, responder):
    import json as _json
    from src.job_hunt_index import query_board
    board = query_board(_index_db_path(config))
    board_json = _json.dumps(board, indent=2, ensure_ascii=False)
    sidebar = _render_sidebar("board")
    body = f"""
    <div class="app-shell">
      {sidebar}
      <main class="main-content">
        <section class="panel">
          <h2>Board View</h2>
          <p style="color:var(--ink-faint);font-size:0.875rem;margin-bottom:16px;">
            A full kanban board UI is coming soon. Raw board data is shown below for debugging.
          </p>
          <pre style="background:var(--surface-sunk);border:1px solid var(--line);border-radius:8px;
                      padding:16px;overflow:auto;font-size:0.78rem;line-height:1.5;max-height:70vh;">{escape(board_json)}</pre>
        </section>
      </main>
    </div>"""
    responder.send_html(render_page("Board View — Job Seeking Tool", body, model_label=config.model_label))


def handle_batch_evaluate(req, config, responder):
    """POST /jobs/batch-evaluate — evaluate N jobs deterministically, return JSON."""
    raw = req.raw_body.decode("utf-8")
    try:
        body = json.loads(raw)
        jobs_data = body.get("jobs", []) if isinstance(body, dict) else []
    except (json.JSONDecodeError, AttributeError):
        responder.send_json({"ok": False, "error": "Invalid JSON"}, status=HTTPStatus.BAD_REQUEST)
        return
    if not isinstance(jobs_data, list) or not jobs_data:
        responder.send_json({"ok": False, "error": "jobs must be a non-empty array"}, status=HTTPStatus.BAD_REQUEST)
        return
    _MAX_BATCH = 20
    if len(jobs_data) > _MAX_BATCH:
        responder.send_json({"ok": False, "error": f"Batch limited to {_MAX_BATCH} jobs"}, status=HTTPStatus.BAD_REQUEST)
        return
    results: list[dict] = []
    errors: list[dict] = []
    for i, job_form in enumerate(jobs_data):
        if not isinstance(job_form, dict):
            errors.append({"index": i, "error": "Each job entry must be an object"})
            continue
        try:
            # Dispatch to the per-source select handler by the card's "source"
            # field so non-Reed sources (Adzuna, …) batch-evaluate too. Falls
            # back to Reed for back-compat with any source-less payloads.
            from src.job_sources.source_registry import get_source as _get_source
            _src_id = (job_form.get("source") or "reed").strip().lower()
            _src = _get_source(_src_id)
            if _src is None:
                raise ValueError(f"Unknown job source: {_src_id}")
            values = _src.select_handler(job_form, config)
            reviewed_job_payload = reviewed_job_payload_from_form(values)
            raw_input_payload = raw_input_payload_from_form(values, reviewed_job_payload)
            result = run_local_evaluation_flow_from_payload(
                profile_path=config.profile_path,
                reviewed_job_payload=reviewed_job_payload,
                state_root=config.state_root,
                report_dir=config.report_dir,
                raw_input_payload=raw_input_payload,
                raw_input_id=reviewed_job_payload["job_id"],
            )
            # Upsert hook (QW-7)
            _upsert_job_to_index(config, result.reviewed_job.job_id, reviewed_job=result.reviewed_job, analysis=result.analysis)
            sal_parts: list[str] = []
            if result.reviewed_job.salary_min_gbp:
                sal_parts.append(f"£{int(result.reviewed_job.salary_min_gbp):,}")
            if result.reviewed_job.salary_max_gbp:
                sal_parts.append(f"£{int(result.reviewed_job.salary_max_gbp):,}")
            results.append({
                "job_id": result.reviewed_job.job_id,
                "title": result.reviewed_job.job_title,
                "company": result.reviewed_job.company,
                "location": result.reviewed_job.location or "",
                "source": result.reviewed_job.source_type or "reed",
                "score": result.analysis.match_score,
                "decision": result.analysis.decision or "review",
                "salary_display": " – ".join(sal_parts) if sal_parts else "",
            })
        except Exception as exc:
            logger.warning("Batch evaluate job %d failed: %s", i, exc)
            errors.append({"index": i, "error": str(exc)})
    responder.send_json({"ok": True, "jobs": results, "errors": errors})


def handle_source_search_more(req, config, responder, source_id):
    """GET /search/{source_id}/more?... — AJAX endpoint returning the next page of
    cards as JSON, for any source that registered a ``render_cards_fragment``.

    Works for Reed, Adzuna and LinkedIn alike: it normalises the query through the
    source's own normaliser (so each source's param naming and skip cursor are
    honoured), re-runs the search one page deep, and renders the bare cards with
    their ids offset by ``skip`` so they never collide with already-shown cards."""
    from urllib.parse import urlencode as _urlencode
    from src.job_sources.source_registry import get_source
    source = get_source(source_id)
    if source is None or source.render_cards_fragment is None:
        responder.send_json(
            {"ok": False, "error": f"Source '{source_id}' does not support pagination."}
        )
        return
    search_values = source.normalize_search_params(req.query)
    take_key, skip_key = _take_skip_param_keys(search_values)
    try:
        take = int(search_values.get(take_key, "10") or "10")
    except (TypeError, ValueError):
        take = 10
    try:
        skip = int(search_values.get(skip_key, "0") or "0")
    except (TypeError, ValueError):
        skip = 0
    try:
        results = source.search_handler(search_values)
    except Exception as exc:
        responder.send_json({"ok": False, "error": str(exc)})
        return
    # Display-only not-interested filter; has_more / next skip stay on the RAW
    # count so the cursor still advances one full source page.
    raw_count = len(results)
    hidden_count = 0
    if results:
        try:
            from src.job_hunt_not_interested import filter_results as _filter_ni
            results, hidden_count = _filter_ni(results, state_root=config.state_root)
        except Exception as exc:
            logger.warning("not-interested filter failed: %s", exc)
    # Exclude-keyword title filter — read the raw field carried in the query.
    exclude_raw = (req.query.get("excludeKeywords") or "").strip()
    if results and exclude_raw:
        results, _excl_ct = _apply_exclude_filter(results, exclude_raw)
        hidden_count += _excl_ct
    nonce = create_select_nonce()
    cards_html = source.render_cards_fragment(results, skip=skip, nonce=nonce)
    has_more = take > 0 and raw_count >= take
    next_params = {
        str(k): str(v) for k, v in search_values.items()
        if not str(k).startswith("_") and k != skip_key
    }
    if exclude_raw:
        next_params["excludeKeywords"] = exclude_raw
    next_params[skip_key] = str(skip + take)
    next_url = f"/search/{source_id}/more?" + _urlencode(next_params)
    responder.send_json({
        "ok": True,
        "cards_html": cards_html,
        "has_more": has_more,
        "next_url": next_url,
        "count": raw_count,
        "visible_count": len(results),
        "hidden_count": hidden_count,
    })


def handle_search_reed_more(req, config, responder):
    """Back-compat shim for the old Reed-only route; delegates to the generic
    handler. Retained so existing imports/links keep working."""
    handle_source_search_more(req, config, responder, "reed")


def _read_json_body(req, responder) -> dict | None:
    """Parse a JSON object request body; sends a 400 and returns None on error."""
    try:
        body = json.loads(req.raw_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        responder.send_json({"ok": False, "error": "Invalid JSON"}, status=HTTPStatus.BAD_REQUEST)
        return None
    if not isinstance(body, dict):
        responder.send_json({"ok": False, "error": "Body must be a JSON object"}, status=HTTPStatus.BAD_REQUEST)
        return None
    return body


def handle_jobs_hide(req, config, responder):
    """POST /jobs/not-interested — persist jobs as not-interested (idempotent).

    Body: ``{"jobs": [{"source", "source_job_id", "title", "company"}, ...]}``
    Returns the per-entry ``keys`` (kept client-side for undo) plus counts."""
    from src.job_hunt_not_interested import count_hidden, hide_jobs
    body = _read_json_body(req, responder)
    if body is None:
        return
    jobs = body.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        responder.send_json({"ok": False, "error": "jobs must be a non-empty array"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        result = hide_jobs(jobs, state_root=config.state_root)
    except (ValueError, TypeError) as exc:
        responder.send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        return
    responder.send_json({
        "ok": True,
        "keys": result["keys"],
        "hidden": len(result["hidden"]),
        "already_hidden": len(result["already_hidden"]),
        "total_hidden": count_hidden(state_root=config.state_root),
    })


def handle_jobs_unhide(req, config, responder):
    """POST /jobs/not-interested/undo — remove keys from the not-interested
    store. Serves both the undo toast and the Hidden jobs overlay's Unhide.
    Body: ``{"keys": ["source:id", ...]}``"""
    from src.job_hunt_not_interested import count_hidden, unhide_jobs
    body = _read_json_body(req, responder)
    if body is None:
        return
    keys = body.get("keys")
    if not isinstance(keys, list) or not keys:
        responder.send_json({"ok": False, "error": "keys must be a non-empty array"}, status=HTTPStatus.BAD_REQUEST)
        return
    removed = unhide_jobs([str(k) for k in keys], state_root=config.state_root)
    responder.send_json({
        "ok": True,
        "removed": removed,
        "total_hidden": count_hidden(state_root=config.state_root),
    })


def handle_jobs_hidden_list(req, config, responder):
    """GET /jobs/not-interested — all hidden jobs, newest first, for the
    Hidden jobs overlay."""
    from src.job_hunt_not_interested import list_hidden
    rows = list_hidden(state_root=config.state_root)
    responder.send_json({"ok": True, "jobs": rows, "count": len(rows)})


def handle_get_review_queue(req, config, responder):
    """GET /review-queue?ids=id1,id2,...[&active=id] — two-panel review page."""
    from urllib.parse import parse_qs as _parse_qs, urlparse as _urlparse2
    _parsed = _urlparse2(req.path)
    _params = _parse_qs(_parsed.query)
    ids_raw = _params.get("ids", [""])[0]
    active_id = _params.get("active", [""])[0].strip()
    job_ids = [jid.strip() for jid in ids_raw.split(",") if jid.strip()]
    if not job_ids:
        responder.send_html(render_page("Review Queue", '<p>No jobs specified. <a href="/">&#8592; Back</a></p>', model_label=config.model_label))
        return
    jobs_info: list[dict] = []
    for job_id in job_ids:
        try:
            rj = load_reviewed_job(job_id, config.state_root)
            an = load_job_analysis(job_id, config.state_root)
            sal_parts2: list[str] = []
            if rj.salary_min_gbp:
                sal_parts2.append(f"£{int(rj.salary_min_gbp):,}")
            if rj.salary_max_gbp:
                sal_parts2.append(f"£{int(rj.salary_max_gbp):,}")
            jobs_info.append({
                "job_id": job_id,
                "title": rj.job_title or "Unknown",
                "company": rj.company or "Unknown",
                "location": rj.location or "",
                "source": rj.source_type or "reed",
                "score": an.match_score if an else None,
                "decision": (effective_decision(an) if an else "review"),
                "salary_display": " – ".join(sal_parts2) if sal_parts2 else "",
            })
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.warning("review-queue: could not load job %s: %s", job_id, exc)
    if not jobs_info:
        responder.send_html(render_page("Review Queue", '<p>No evaluated jobs found. <a href="/">&#8592; Back</a></p>', model_label=config.model_label))
        return
    jobs_info.sort(key=lambda j: (j["score"] or 0), reverse=True)
    if not active_id or not any(j["job_id"] == active_id for j in jobs_info):
        active_id = jobs_info[0]["job_id"]
    ids_csv = ",".join(j["job_id"] for j in jobs_info)
    responder.send_html(render_review_queue_page(ReviewQueueViewModel(jobs=jobs_info, active_id=active_id, ids_csv=ids_csv, model_label=config.model_label)))


def handle_jobs_save(req, config, responder):
    raw = req.raw_body.decode("utf-8")
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        responder.send_json({"error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
        return

    job_title = (payload.get("job_title") or "").strip()
    company = (payload.get("company") or "").strip()
    if not job_title:
        responder.send_json({"error": "job_title is required"}, status=HTTPStatus.BAD_REQUEST)
        return
    if not company:
        responder.send_json({"error": "company is required"}, status=HTTPStatus.BAD_REQUEST)
        return

    # Generate job_id
    job_id = f"manual-{uuid.uuid4().hex[:12]}"

    # Build minimal JobPosting
    job = JobPosting(
        job_id=job_id,
        job_title=job_title,
        company=company,
        description_raw=payload.get("description_raw") or "No description provided.",
        source_type=payload.get("source_type") or payload.get("source", "manual"),
        source_ref=payload.get("source_ref"),
        location=payload.get("location") or None,
        work_mode=None,
        employment_type=None,
        salary_min_gbp=payload.get("salary_min_gbp") or None,
        salary_max_gbp=payload.get("salary_max_gbp") or None,
    )
    save_reviewed_job(job, config.state_root)

    # Create outcome record
    from src.job_hunt_outcomes import create_outcome_record
    outcome = create_outcome_record(job_id)
    save_application_outcome(outcome, config.state_root)

    # Upsert into index (QW-7)
    _upsert_job_to_index(config, job_id, reviewed_job=job, analysis=None, outcome=outcome)

    responder.send_json({"job_id": job_id, "status": "not_applied"})


# --------------------------------------------------------------------------- #
# Saved Searches (Daily Job Digest — phase D1)
# --------------------------------------------------------------------------- #

def _saved_search_to_json(s: SavedSearch) -> dict[str, Any]:
    return {
        "search_id": s.search_id,
        "name": s.name,
        "source_id": s.source_id,
        "params": dict(s.params),
        "enabled": s.enabled,
        "created_at": s.created_at,
        "last_run_at": s.last_run_at,
        "last_run_count": s.last_run_count,
    }


def handle_saved_searches_list(req, config, responder):
    """GET /saved-searches — JSON list of all saved searches."""
    searches = list_saved_searches(state_root=config.state_root)
    responder.send_json({"searches": [_saved_search_to_json(s) for s in searches]})


def handle_saved_searches_create(req, config, responder):
    """POST /saved-searches — create a saved search from a JSON body
    ``{name, source_id, params}``."""
    try:
        raw = req.raw_body.decode("utf-8")
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        responder.send_json({"ok": False, "error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
        return
    if not isinstance(payload, dict):
        responder.send_json({"ok": False, "error": "Body must be a JSON object"}, status=HTTPStatus.BAD_REQUEST)
        return

    name = payload.get("name")
    source_id = payload.get("source_id") or payload.get("source")
    # Use a real default (not `or {}`) so invalid falsy params ([] , "") reach
    # _validate_params and are rejected rather than silently coerced to {} (Codex MED).
    params = payload.get("params", {})

    # source_id must be a registered/enabled source (case-insensitive)
    enabled_sources = {s.lower() for s in get_enabled_sources()}
    if not isinstance(source_id, str) or source_id.strip().lower() not in enabled_sources:
        responder.send_json(
            {"ok": False, "error": f"Unknown source_id (enabled: {sorted(enabled_sources)})"},
            status=HTTPStatus.BAD_REQUEST,
        )
        return

    try:
        search = create_saved_search(name, source_id, params, state_root=config.state_root)
    except SavedSearchError as exc:
        responder.send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        return

    responder.send_json(
        {"ok": True, "search": _saved_search_to_json(search)},
        status=HTTPStatus.CREATED,
    )


def handle_saved_search_delete(req, config, responder, search_id):
    """POST /saved-searches/{id}/delete — idempotent delete."""
    try:
        deleted = delete_saved_search(search_id, state_root=config.state_root)
    except SavedSearchError:
        responder.send_json({"ok": False, "error": "Invalid search_id"}, status=HTTPStatus.BAD_REQUEST)
        return
    if not deleted:
        responder.send_json({"ok": False, "error": "Saved search not found"}, status=HTTPStatus.NOT_FOUND)
        return
    responder.send_json({"ok": True, "deleted": True})


def handle_digest_count(req, config, responder):
    """GET /digest/count — JSON `{unseen: N}` for the sidebar badge.
    Returns 0 until the D3 pipeline starts populating digest rows."""
    from src.job_hunt_digest import unseen_count
    responder.send_json({"unseen": unseen_count(db_path=_index_db_path(config))})


def _load_active_profile(config):
    """Load the candidate profile for digest runs (startup profile)."""
    return load_candidate_profile(config.profile_path)


def handle_run_now(req, config, responder, search_id):
    """POST /saved-searches/{id}/run-now — synchronously run ONE saved search through
    the digest pipeline and return the DigestRunResult JSON. No LLM calls (D3)."""
    from src.job_hunt_scheduler import run_digest_pipeline
    try:
        search = load_saved_search(search_id, state_root=config.state_root)
    except SavedSearchNotFound:
        responder.send_json({"ok": False, "error": "Saved search not found"}, status=HTTPStatus.NOT_FOUND)
        return
    except SavedSearchError:
        responder.send_json({"ok": False, "error": "Invalid search_id"}, status=HTTPStatus.BAD_REQUEST)
        return

    try:
        profile = _load_active_profile(config)
    except Exception as exc:
        responder.send_json({"ok": False, "error": f"Could not load profile: {exc}"},
                            status=HTTPStatus.INTERNAL_SERVER_ERROR)
        return

    result = run_digest_pipeline(
        config=config,
        saved_searches=[search],
        profile=profile,
        db_path=_index_db_path(config),
    )
    # Record run metadata on the saved search (best-effort).
    try:
        update_last_run(search_id, state_root=config.state_root, count=result.jobs_new)
    except Exception as exc:
        logger.warning("run-now: could not update last_run for %s: %s", search_id, exc)

    payload = {"ok": True, **result.to_dict()}
    responder.send_json(payload)


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DIGEST_MARK_MAX = 500


def _valid_iso_date(value) -> bool:
    """True only for a real calendar date in YYYY-MM-DD form (rejects 2026-99-99)."""
    if not isinstance(value, str) or not _ISO_DATE.match(value):
        return False
    from datetime import date as _date
    try:
        _date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _parse_digest_filters(query, config):
    """Strictly parse digest feed filters from the query string. Unknown/invalid
    values are dropped (not 500). Returns a dict for query_digest + the raw values
    for the render layer."""
    enabled = {s.lower() for s in get_enabled_sources()}
    date = query.get("date", "").strip()
    if not _valid_iso_date(date):
        date = ""
    source = query.get("source", "").strip().lower()
    if source not in enabled:
        source = ""
    saved_search_id = query.get("saved_search_id", "").strip()
    try:
        from src.job_hunt_saved_searches import validate_search_id
        validate_search_id(saved_search_id) if saved_search_id else None
    except Exception:
        saved_search_id = ""
    seen_raw = query.get("seen", "all").strip().lower()
    seen = {"unseen": False, "seen": True}.get(seen_raw, None)
    return {
        "date": date or None,
        "source_id": source or None,
        "saved_search_id": saved_search_id or None,
        "seen": seen,
    }, {"date": date, "source": source, "saved_search_id": saved_search_id, "seen": seen_raw}


def handle_digest(req, config, responder):
    """GET /digest — the digest feed page with date/source/saved-search/seen filters."""
    from src.job_hunt_digest import query_digest
    from src.ui_render import render_digest_page

    filters, raw = _parse_digest_filters(req.query, config)
    entries = query_digest(db_path=_index_db_path(config), limit=200, **filters)
    try:
        searches = [(s.search_id, s.name) for s in list_saved_searches(state_root=config.state_root)]
    except Exception:
        searches = []
    page = render_digest_page(
        entries=entries,
        filters=raw,
        sources=get_enabled_sources(),
        saved_searches=searches,
        model_label=config.model_label,
    )
    responder.send_html(page)


def handle_digest_mark_seen(req, config, responder):
    """POST /digest/mark-seen — body must be exactly ONE mode:
    `{"job_ids": [...]}` (bounded list) or `{"all": true, <optional filters>}`."""
    from src.job_hunt_digest import mark_all_seen, mark_seen

    raw = req.raw_body.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        responder.send_json({"ok": False, "error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
        return
    if not isinstance(payload, dict):
        responder.send_json({"ok": False, "error": "Body must be a JSON object"}, status=HTTPStatus.BAD_REQUEST)
        return

    has_all = "all" in payload
    has_ids = "job_ids" in payload
    db_path = _index_db_path(config)

    def _bad(msg):
        responder.send_json({"ok": False, "error": msg}, status=HTTPStatus.BAD_REQUEST)

    # Exactly one mode: `all:true` (no job_ids) XOR `job_ids:[...]` (no `all`).
    if has_all and has_ids:
        _bad("Provide either all:true or job_ids, not both")
        return
    if not has_all and not has_ids:
        _bad("Provide all:true or job_ids")
        return

    if has_all:
        if payload.get("all") is not True:
            _bad("all must be true")
            return
        # All-mode filters must be valid when supplied — never silently widen scope.
        date = payload.get("date")
        source = payload.get("source")
        ssid = payload.get("saved_search_id")
        if date is not None and not _valid_iso_date(date):
            _bad("invalid date")
            return
        if source is not None and not (
            isinstance(source, str) and source.lower() in {s.lower() for s in get_enabled_sources()}
        ):
            _bad("invalid source")
            return
        if ssid is not None and not (isinstance(ssid, str) and ssid.strip()):
            _bad("invalid saved_search_id")
            return
        marked = mark_all_seen(
            db_path=db_path,
            date=date if isinstance(date, str) else None,
            source_id=source.lower() if isinstance(source, str) and source else None,
            saved_search_id=ssid if isinstance(ssid, str) and ssid else None,
        )
        responder.send_json({"ok": True, "marked": marked})
        return

    # id mode
    job_ids = payload.get("job_ids")
    if not isinstance(job_ids, list):
        _bad("job_ids must be a list")
        return
    if not all(isinstance(j, str) and j.strip() for j in job_ids):
        _bad("job_ids must all be non-empty strings")
        return
    if len(job_ids) > _DIGEST_MARK_MAX:
        _bad(f"too many job_ids (max {_DIGEST_MARK_MAX})")
        return
    marked = mark_seen(job_ids, db_path=db_path)
    responder.send_json({"ok": True, "marked": marked})


# Set by the server at startup (D5/D6) so status/manual-drain handlers can reach
# the live daemons. None when daemons aren't running (e.g. unit tests).
_DIGEST_SCHEDULER = None
_LLM_WORKER = None


def set_daemons(scheduler=None, worker=None) -> None:
    global _DIGEST_SCHEDULER, _LLM_WORKER
    _DIGEST_SCHEDULER = scheduler
    _LLM_WORKER = worker


def handle_scheduler_status(req, config, responder):
    """GET /scheduler/status — live status from the D5 scheduler daemon when running."""
    if _DIGEST_SCHEDULER is not None:
        responder.send_json(_DIGEST_SCHEDULER.status())
        return
    responder.send_json({
        "running": False, "last_run": None, "next_run": None, "last_error": None,
        "note": "Scheduler daemon not running; use Run now per saved search.",
    })


def handle_run_llm_batch(req, config, responder):
    """POST /digest/run-llm-batch — drain ONE paced LLM batch synchronously now."""
    from src.job_hunt_scheduler import drain_llm_batch
    try:
        profile = _load_active_profile(config)
    except Exception as exc:
        responder.send_json({"ok": False, "error": f"Could not load profile: {exc}"},
                            status=HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    result = drain_llm_batch(config=config, profile=profile, db_path=_index_db_path(config))
    responder.send_json({"ok": True, **result.to_dict()})


def handle_digest_reevaluate(req, config, responder):
    """POST /digest/reevaluate — re-score every indexed digest job against the
    current profile/threshold (OQ-2). Synchronous, no LLM call here (crossed-up jobs
    are only queued for the paced worker). Returns the ReevalResult JSON."""
    from src.job_hunt_scheduler import reevaluate_digest_jobs
    try:
        profile = _load_active_profile(config)
    except Exception as exc:
        responder.send_json({"ok": False, "error": f"Could not load profile: {exc}"},
                            status=HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    result = reevaluate_digest_jobs(config=config, profile=profile, db_path=_index_db_path(config))
    responder.send_json({"ok": True, **result.to_dict()})


def handle_llm_queue(req, config, responder):
    """GET /digest/llm-queue — queue counts + RPD usage."""
    from src.job_hunt_scheduler import llm_queue_stats
    responder.send_json(llm_queue_stats(db_path=_index_db_path(config)))


def handle_saved_search_toggle(req, config, responder, search_id):
    """POST /saved-searches/{id}/toggle — flip enabled."""
    try:
        search = toggle_saved_search(search_id, state_root=config.state_root)
    except SavedSearchNotFound:
        responder.send_json({"ok": False, "error": "Saved search not found"}, status=HTTPStatus.NOT_FOUND)
        return
    except SavedSearchError:
        responder.send_json({"ok": False, "error": "Invalid search_id"}, status=HTTPStatus.BAD_REQUEST)
        return
    responder.send_json({"ok": True, "enabled": search.enabled, "search": _saved_search_to_json(search)})


def handle_tailor(req, config, responder):
    raw = req.raw_body.decode("utf-8")
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        responder.send_json({"error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
        return

    job_id = (payload.get("job_id") or "").strip()
    if not job_id:
        responder.send_json({"error": "job_id is required"}, status=HTTPStatus.BAD_REQUEST)
        return

    # Step 1: load analysis
    try:
        analysis = load_job_analysis(job_id, config.state_root)
    except FileNotFoundError:
        responder.send_json({"error": f"Job analysis not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
        return

    # Step 2: check effective decision gate
    decision = effective_decision(analysis)
    if decision == "skip":
        responder.send_json({"error": "Skipped jobs cannot be tailored"}, status=HTTPStatus.FORBIDDEN)
        return
    if decision == "review":
        manual_selected = payload.get("manual_selected")
        if manual_selected is not True:
            responder.send_json(
                {"error": "Review decisions require manual_selected=true"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

    # Step 3: load reviewed job
    try:
        job = load_reviewed_job(job_id, config.state_root)
    except FileNotFoundError:
        responder.send_json({"error": f"Reviewed job not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
        return

    # Step 4: load profile and master CV
    try:
        profile = load_candidate_profile(config.profile_path)
    except Exception as exc:
        responder.send_json({"error": f"Could not load candidate profile: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        return

    # Resolve master CV text: try master_cv_text field, then resolve from master_cv_ref
    cv_text: str | None = profile.master_cv_text
    if not cv_text:
        if profile.master_cv_ref:
            try:
                from src.job_hunt_profile import load_master_cv
                cv_ref_path = Path(profile.master_cv_ref)
                if not cv_ref_path.is_absolute():
                    cv_ref_path = config.profile_path.parent / cv_ref_path
                cv_text = load_master_cv(cv_ref_path)
            except Exception as exc:
                responder.send_json({"error": f"CV file could not be read ({profile.master_cv_ref}): {exc}. Re-upload your CV on the Profile page."}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                return
        else:
            responder.send_json({"error": "No master CV on profile. Go to Profile → upload your CV file → click Save (or Parse CV to auto-save)."}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
            return

    # Step 5: select evidence
    evidence = select_relevant_evidence(profile, cv_text, job, analysis)

    # Step 6: tailor CV
    result = tailor_cv(cv_text, evidence, job, profile=profile)

    # Step 7: validate
    try:
        valid = validate_tailored_cv(cv_text, result, profile)
        if not valid:
            responder.send_json({"error": "Tailored CV failed validation"}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
            return
    except TailoringValidationError as exc:
        responder.send_json({"error": str(exc)}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
        return

    # Step 8: save
    path = save_tailored_cv(job_id, result, profile.candidate_id, DEFAULT_TAILORING_POLICY)

    responder.send_json({
        "summary": result.summary,
        "promoted": result.promoted,
        "matched": result.matched,
        "missing": result.missing,
        "markdown": result.markdown,
        "saved_path": str(path),
    })


def handle_cover_letter(req, config, responder):
    raw = req.raw_body.decode("utf-8")
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        responder.send_json({"error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
        return

    job_id = (payload.get("job_id") or "").strip()
    why_company_text = payload.get("why_company_text")
    if not job_id:
        responder.send_json({"error": "job_id is required"}, status=HTTPStatus.BAD_REQUEST)
        return
    if why_company_text is None or not str(why_company_text).strip():
        responder.send_json({"error": "why_company_text is required"}, status=HTTPStatus.BAD_REQUEST)
        return
    why_company_text = str(why_company_text)

    tone = str(payload.get("tone") or "professional")
    length = str(payload.get("length") or "standard")
    points = payload.get("points") or None
    if points is not None and not isinstance(points, list):
        points = None

    # Step 1: load analysis
    try:
        analysis = load_job_analysis(job_id, config.state_root)
    except FileNotFoundError:
        responder.send_json({"error": f"Job analysis not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
        return

    # Step 2: decision gate
    decision = effective_decision(analysis)
    if decision == "skip":
        responder.send_json(
            {"error": "Cover letter not available for skipped jobs"},
            status=HTTPStatus.BAD_REQUEST,
        )
        return

    # Step 3: load reviewed job
    try:
        job = load_reviewed_job(job_id, config.state_root)
    except FileNotFoundError:
        responder.send_json({"error": f"Reviewed job not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
        return

    # Step 4: load profile and master CV
    try:
        profile = load_candidate_profile(config.profile_path)
    except Exception as exc:
        responder.send_json({"error": f"Could not load candidate profile: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        return

    cv_text: str | None = profile.master_cv_text
    if not cv_text:
        if profile.master_cv_ref:
            try:
                from src.job_hunt_profile import load_master_cv
                cv_ref_path = Path(profile.master_cv_ref)
                if not cv_ref_path.is_absolute():
                    cv_ref_path = config.profile_path.parent / cv_ref_path
                cv_text = load_master_cv(cv_ref_path)
            except Exception as exc:
                responder.send_json({"error": f"CV file could not be read ({profile.master_cv_ref}): {exc}. Re-upload your CV on the Profile page."}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                return
        else:
            responder.send_json({"error": "No master CV on profile. Go to Profile → upload your CV file → click Save (or Parse CV to auto-save)."}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
            return

    # Step 5: generate cover letter
    try:
        letter = generate_cover_letter_text(
            profile,
            cv_text or "",
            job,
            analysis,
            why_company_text,
            tone=tone,
            length=length,
            points=points,
        )
    except ValueError as exc:
        responder.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        return

    # Step 6: save
    path = save_cover_letter(job_id, letter, profile.candidate_id)

    responder.send_json({
        "letter": letter,
        "word_count": len(letter.split()),
        "saved_path": str(path),
    })


def raw_input_payload_from_form(
    form: dict[str, str],
    reviewed_job_payload: dict[str, Any],
) -> dict[str, Any]:
    input_method = optional_text(form, "input_method") or reviewed_job_payload["source_type"]
    payload = {
        "input_method": input_method,
        "source_type": reviewed_job_payload["source_type"],
        "source_ref": reviewed_job_payload.get("source_ref"),
        "job_url": optional_text(form, "job_url"),
        "copied_text": optional_text(form, "copied_text"),
        "description_raw": reviewed_job_payload["description_raw"],
    }
    if input_method == "reed_search" or reviewed_job_payload["source_type"] == "reed":
        payload["source_snapshot"] = _reed_source.validate_reed_source_snapshot_json(form.get("source_snapshot_json", ""))
    return payload


def load_recent_job_history(state_root: str | Path, *, limit: int = 10) -> list[dict[str, Any]]:
    layout = ensure_storage_layout(state_root)
    rows: list[dict[str, Any]] = []
    for path in sorted(layout.analyses_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        job_id = path.stem
        try:
            analysis = load_job_analysis(job_id, layout.root)
            reviewed_job = load_reviewed_job(job_id, layout.root)
            try:
                outcome = load_application_outcome(job_id, layout.root)
                outcome_status = outcome.status
            except FileNotFoundError:
                outcome_status = None
        except Exception:
            continue

        try:
            evaluated_at = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        except Exception:
            evaluated_at = None

        rows.append(
            {
                "job_id": job_id,
                "job_title": reviewed_job.job_title,
                "company": reviewed_job.company,
                "decision": analysis.decision,
                "match_score": analysis.match_score,
                "confidence": analysis.confidence,
                "outcome_status": outcome_status,
                "evaluated_at": evaluated_at,
            }
        )
    return rows


def _render_shared_search_form(values: dict[str, str], buttons_html: str) -> str:
    """One set of search criteria shared by every source. Each source has its own
    submit button (rendered into ``buttons_html``) that posts these same fields to
    its ``/search/{source_id}`` endpoint via the button's ``formaction``. All
    registered sources normalise this identical field set, so the criteria only
    need to be entered once."""
    return f"""
    <form method="get" action="/search/reed" id="job-search-form" class="panel subtle">
      <h3>Search criteria</h3>
      <div class="grid two-col">
        <label><span>Keywords / job title</span><input name="keywords" value="{escape(values.get('keywords', ''))}" placeholder="Business Analyst"></label>
        <label><span>Exclude keywords <small style="color:var(--ink-faint);font-weight:400;">(comma-separated; title match)</small></span><input name="excludeKeywords" value="{escape(values.get('excludeKeywords', ''))}" placeholder="trainee, junior, graduate"></label>
        <label><span>Location</span><input name="locationName" value="{escape(values.get('locationName', ''))}" placeholder="London"></label>
        <label><span>Minimum salary</span><input name="minimumSalary" inputmode="numeric" value="{escape(values.get('minimumSalary', ''))}" placeholder="50000"></label>
        <label><span>Results to take</span><input name="resultsToTake" inputmode="numeric" value="{escape(values.get('resultsToTake', '10'))}" placeholder="10"></label>
        <label><span>Work mode</span><select name="workMode">{render_select_options(['any', 'remote', 'hybrid', 'onsite'], values.get('workMode', 'any'))}</select></label>
        <label><span>Employment type</span><select name="employmentType">{render_select_options(['any', 'permanent', 'contract'], values.get('employmentType', 'any'))}</select></label>
      </div>
      <p class="prefill-status">Remote/hybrid, employment type and minimum salary are applied best-effort per source; unsupported filters are called out in result notes.</p>
      <div class="actions">
        {buttons_html}
        <a href="/?tab=add_job" class="tab-link">Manual Fallback</a>
        <a href="/?tab=evaluate" class="tab-link">Evaluate existing details</a>
      </div>
    </form>
    """


def _render_search_jobs_tab(
    *,
    search_values: dict[str, str] | None = None,
    reed_results: list[dict[str, Any]] | None = None,
    reed_error: str | None = None,
    reed_select_nonce: str | None = None,
) -> str:
    from src.job_sources.source_registry import all_sources
    enabled_sources = [s.lower() for s in get_enabled_sources()]
    sources = all_sources()

    # Prefill the shared criteria from the last search if there was one, so the
    # values persist and the other source's button can be clicked without
    # re-typing. All sources normalise the same field set, so any source's empty
    # default works as the baseline.
    active_search_source = (search_values or {}).get("_source_id")
    if search_values and active_search_source:
        form_values = search_values
    elif sources:
        form_values = sources[0].normalize_search_params({})
    else:
        form_values = {}

    # One submit button per source; disabled (greyed) when the source is not in
    # ENABLED_SOURCES. Each enabled button posts the shared criteria to its own
    # /search/{source_id} endpoint via formaction.
    buttons_html = ""
    for source in sources:
        enabled = source.source_id in enabled_sources
        if enabled:
            buttons_html += (
                f'<button type="submit" formaction="/search/{escape(source.source_id)}">'
                f'Search {escape(source.display_name)}</button>\n'
            )
        else:
            buttons_html += (
                f'<button type="button" disabled title="Coming soon" '
                f'style="opacity:0.5;cursor:not-allowed;">Search {escape(source.display_name)} — disabled</button>\n'
            )

    form_html = _render_shared_search_form(form_values, buttons_html)

    # Results: only the source actually searched renders results (single active
    # source, unchanged). Each source keeps its own results renderer.
    source_results_html = ""
    for source in sources:
        if active_search_source == source.source_id:
            source_results_html += source.render_results(
                reed_results,
                reed_error,
                reed_select_nonce,
                search_values.get("_more_url") if search_values else None,
            )

    # Not-interested note: explains short (or fully empty) pages caused by the
    # server-side hide filter, so a filtered page never looks broken.
    hidden_note_html = ""
    _hidden_ct = (search_values or {}).get("_hidden_count")
    if active_search_source and _hidden_ct:
        if reed_results:
            _note = f"{escape(_hidden_ct)} job(s) on this page are hidden as not interested."
        else:
            _note = (
                f"All {escape(_hidden_ct)} job(s) on this page are hidden as not interested. "
                "Use Next page, or unhide jobs from the Hidden jobs list on any results page."
            )
        hidden_note_html = (
            '<div style="margin-top:14px;padding:10px 14px;border:1px dashed var(--line);'
            'border-radius:var(--r-md);font-size:12.5px;color:var(--ink-faint);">'
            f'{_note}</div>'
        )

    # Exclude-keyword note: explains jobs removed by the title exclude filter.
    excluded_note_html = ""
    _excl_ct = (search_values or {}).get("_excluded_count")
    if active_search_source and _excl_ct:
        _excl_terms = escape((search_values or {}).get("excludeKeywords", ""))
        excluded_note_html = (
            '<div style="margin-top:14px;padding:10px 14px;border:1px dashed var(--line);'
            'border-radius:var(--r-md);font-size:12.5px;color:var(--ink-faint);">'
            f'{escape(_excl_ct)} job(s) on this page hidden by exclude keywords ({_excl_terms}).</div>'
        )

    return f"""
    <section class="panel">
      <h2>Search Jobs</h2>
      <p>Enter your criteria once, then pick a board. Search across connected job boards. Active sources are driven by <code>/sources</code> config.</p>
      {form_html}
      {hidden_note_html}
      {excluded_note_html}
      {source_results_html}
    </section>
    """


_SKILL_GAP_CODES_VM = {"missing-required-skills", "missing-preferred-skills"}


def _kw_canon(value: str) -> str:
    """Canonical keyword key: casefold + whitespace-collapse (matches F1 matcher)."""
    return " ".join(value.casefold().split())


def _keyword_match_vm_fields(reviewed_job, analysis) -> dict:
    """Rebuild matched lists for display from job skills - stored missing lists
    (canonical key; required wins over preferred), per the F1 design."""
    req_missing = {_kw_canon(k) for k in analysis.keywords_required_missing}
    pref_missing = {_kw_canon(k) for k in analysis.keywords_preferred_missing}
    required_canon = {_kw_canon(k) for k in reviewed_job.required_skills}
    req_matched = [k for k in reviewed_job.required_skills if _kw_canon(k) not in req_missing]
    # preferred: drop any keyword that is also required (required wins), then split
    pref_candidates = [k for k in reviewed_job.preferred_skills if _kw_canon(k) not in required_canon]
    pref_matched = [k for k in pref_candidates if _kw_canon(k) not in pref_missing]
    return dict(
        keyword_match_rate=analysis.keyword_match_rate,
        keywords_required_matched=req_matched,
        keywords_required_missing=list(analysis.keywords_required_missing),
        keywords_preferred_matched=pref_matched,
        keywords_preferred_missing=list(analysis.keywords_preferred_missing),
        keywords_overused=list(analysis.keywords_overused),
        keyword_match_baseline_rate=analysis.keyword_match_baseline_rate,
        keyword_match_source=analysis.keyword_match_source,
    )


def _build_job_page_vm(reviewed_job, analysis, outcome, *, flash, flash_kind="success",
                       embed=False, model_label="") -> "JobPageViewModel":
    if analysis is not None:
        sb = analysis.score_breakdown
        rows = [
            ("Skills",     sb.skills_score.reason,     sb.skills_score.value),
            ("Experience", sb.experience_score.reason, sb.experience_score.value),
            ("Location",   sb.location_score.reason,   sb.location_score.value),
            ("Salary",     sb.salary_score.reason,     sb.salary_score.value),
            ("Domain",     sb.domain_score.reason,     sb.domain_score.value),
            ("Work mode",  sb.work_mode_score.reason,  sb.work_mode_score.value),
        ]
        a = dict(
            has_analysis=True, match_score=analysis.match_score, ats_score=analysis.ats_score,
            confidence=analysis.confidence, decision=analysis.decision,
            decision_reason=analysis.decision_reason, user_decision=analysis.user_decision,
            effective_decision=effective_decision(analysis), score_breakdown_rows=rows,
            blockers=[f"{b.label}: {b.reason}" for b in analysis.blockers],
            strengths=list(analysis.strengths),
            risk_items=[f"{r.label}: {r.reason}" for r in analysis.risk_flags
                        if r.code not in _SKILL_GAP_CODES_VM],
            missing_required_skills=list(analysis.missing_required_skills),
            missing_preferred_skills=list(analysis.missing_preferred_skills),
            **_keyword_match_vm_fields(reviewed_job, analysis),
        )
    else:
        a = dict(
            has_analysis=False, match_score=None, ats_score=None, confidence=None,
            decision=None, decision_reason=None, user_decision=None, effective_decision="skip",
            score_breakdown_rows=[], blockers=[], strengths=[], risk_items=[],
            missing_required_skills=[], missing_preferred_skills=[],
            keyword_match_rate=None, keywords_required_matched=[], keywords_required_missing=[],
            keywords_preferred_matched=[], keywords_preferred_missing=[], keywords_overused=[],
            keyword_match_baseline_rate=None, keyword_match_source="master",
        )
    return JobPageViewModel(
        job_id=reviewed_job.job_id, source_type=reviewed_job.source_type,
        source_ref=reviewed_job.source_ref, url=getattr(reviewed_job, "url", None),
        job_title=reviewed_job.job_title,
        company=reviewed_job.company, location=reviewed_job.location,
        work_mode=reviewed_job.work_mode, employment_type=reviewed_job.employment_type,
        required_years_experience=reviewed_job.required_years_experience, domain=reviewed_job.domain,
        salary_min_gbp=reviewed_job.salary_min_gbp, salary_max_gbp=reviewed_job.salary_max_gbp,
        source_quality_score=getattr(reviewed_job, "source_quality_score", None),
        description_raw=reviewed_job.description_raw,
        required_skills=list(reviewed_job.required_skills),
        preferred_skills=list(reviewed_job.preferred_skills),
        has_outcome=outcome is not None,
        outcome_status=outcome.status if outcome else None,
        outcome_notes=outcome.notes if outcome else None,
        outcome_updated_at=outcome.updated_at if outcome else None,
        outcome_status_options=allowed_next_statuses(outcome.status if outcome else None),
        flash=flash, flash_kind=flash_kind, embed=embed, model_label=model_label, **a,
    )


def _build_profile_page_vm(profile_obj: Any) -> "ProfilePageViewModel":
    if profile_obj is None:
        return ProfilePageViewModel(
            has_profile=False, name=None, target_roles=[], locations=[],
            remote_preference=None, salary_floor_gbp=None, right_to_work_uk=None,
            skills=[], years_experience=None, industries=[], certifications=[],
            achievements=[], master_cv_ref=None, master_cv_text=None,
        )
    return ProfilePageViewModel(
        has_profile=True,
        name=profile_obj.name,
        target_roles=list(profile_obj.target_roles or []),
        locations=list(profile_obj.locations or []),
        remote_preference=profile_obj.remote_preference,
        salary_floor_gbp=profile_obj.salary_floor_gbp,
        right_to_work_uk=profile_obj.right_to_work_uk,
        skills=[{"name": s.name, "level": s.level, "years": s.years,
                 "evidence_type": s.evidence_type} for s in (profile_obj.skills or [])],
        years_experience=profile_obj.years_experience,
        industries=list(profile_obj.industries or []),
        certifications=list(profile_obj.certifications or []),
        achievements=list(profile_obj.achievements or []),
        master_cv_ref=profile_obj.master_cv_ref,
        master_cv_text=profile_obj.master_cv_text,
        digest_enabled=profile_obj.digest_enabled,
        digest_threshold=profile_obj.digest_threshold,
        digest_run_time=profile_obj.digest_run_time,
        digest_max_per_source=profile_obj.digest_max_per_source,
        digest_llm_enabled=profile_obj.digest_llm_enabled,
        digest_max_llm_per_run=profile_obj.digest_max_llm_per_run,
        digest_llm_rpm=profile_obj.digest_llm_rpm,
        digest_llm_rpd=profile_obj.digest_llm_rpd,
        digest_llm_batch_size=profile_obj.digest_llm_batch_size,
        digest_llm_batch_interval_min=profile_obj.digest_llm_batch_interval_min,
    )
