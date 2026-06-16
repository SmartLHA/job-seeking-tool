from __future__ import annotations

import argparse
import html
import re
import secrets
import shutil
import sys
import uuid
from datetime import datetime, timezone
import time
from dataclasses import dataclass
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, urlparse

from src.job_sources.normalize import normalize_reed
from src.job_sources.reed_client import fetch_reed_jobs
from src.job_hunt_orchestrator import LocalEvaluationRunResult, run_local_evaluation_flow_from_payload
from src.job_hunt_parsing import parse_job_from_text, parse_job_from_url
from src.job_hunt_outcomes import ALLOWED_OUTCOME_STATUSES, create_outcome_record, update_outcome
from src.job_hunt_profile import load_candidate_profile, save_candidate_profile, ProfileValidationError, parse_cv_file, candidate_profile_from_dict
from src.job_hunt_models import CandidateProfile, JobPosting
from src.job_hunt_config import get_enabled_sources, DEFAULT_TAILORING_POLICY
from src.job_hunt_models import effective_decision
from src.job_hunt_tailoring import (
    select_relevant_evidence,
    tailor_cv,
    validate_tailored_cv,
    save_tailored_cv,
    TailoringValidationError,
)
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


@dataclass(frozen=True, slots=True)
class UIServerConfig:
    profile_path: Path
    state_root: Path
    report_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the minimal local browser UI for one-job evaluation.",
    )
    parser.add_argument("--profile", required=True, help="Path to candidate profile JSON")
    parser.add_argument(
        "--state-root",
        default="data/state",
        help="Directory for local raw/reviewed/analysis state (default: data/state)",
    )
    parser.add_argument(
        "--report-dir",
        default="output/reports",
        help="Directory for JSON/CSV report exports (default: output/reports)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9000, help="Bind port (default: 9000)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = UIServerConfig(
        profile_path=Path(args.profile),
        state_root=Path(args.state_root),
        report_dir=Path(args.report_dir),
        host=args.host,
        port=args.port,
    )

    try:
        # Validate startup paths early so browser errors stay simple later.
        load_candidate_profile(config.profile_path)
        ensure_storage_layout(config.state_root)
    except Exception as exc:  # pragma: no cover
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    server = ThreadingHTTPServer((config.host, config.port), _build_handler(config))
    url = f"http://{config.host}:{config.port}"
    print(f"Minimal local UI running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        print("\nUI stopped.")
    finally:
        server.server_close()
    return 0


_ALLOWED_PROFILE_ROOTS = [
    Path("data/demo_profile"),
    Path("data/demo_profile2"),
]
_PROFILE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_MAX_CV_SIZE_BYTES = 5 * 1024 * 1024
_ALLOWED_CV_EXTENSIONS = {".txt", ".pdf", ".docx"}
_ALLOWED_CV_MIMETYPES = {
    "text/plain",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _allowed_profile_dir(profile_id: str) -> Path | None:
    if not _PROFILE_ID_PATTERN.match(profile_id):
        return None
    candidate = Path("data") / profile_id
    for root in _ALLOWED_PROFILE_ROOTS:
        try:
            candidate.resolve().relative_to(root.resolve())
            return root / profile_id
        except ValueError:
            pass
    # Accept any profile_id inside data/ as long as it matches pattern
    # and doesn't escape the data/ directory
    try:
        candidate.resolve().relative_to(Path("data").resolve())
        return candidate
    except ValueError:
        return None


_HOME_TABS = {"search", "evaluate", "history", "add_job", "profile"}


def _normalize_home_tab(tab: str | None) -> str:
    """Return a safe home tab, defaulting to the Reed-first search shell."""
    if tab in _HOME_TABS:
        return tab
    return "search"


def _build_handler(config: UIServerConfig) -> type[BaseHTTPRequestHandler]:
    # db_path lives next to the JSON storage root
    _db_path = Path(config.state_root) / "job_hunt_index.db"
    # Rebuild index if DB is missing (first run or was deleted)
    if not _db_path.exists():
        try:
            from src.job_hunt_index import rebuild_index
            _storage_layout = ensure_storage_layout(config.state_root)
            rebuild_index(_storage_layout, _db_path)
        except Exception:
            pass  # Never crash on startup due to index rebuild failure

    class JobSeekingUIHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                params = parse_qs(parsed.query)
                tab = params.get("tab", ["search"])[0]
                self._render_home(tab=tab)
                return

            if parsed.path == "/search/reed":
                params = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
                self._handle_reed_search(params)
                return

            if parsed.path == "/sources":
                self._send_json({"enabled": get_enabled_sources()})
                return

            if parsed.path == "/jobs":
                self._handle_get_jobs()
                return

            if parsed.path == "/board":
                self._handle_get_board()
                return

            if parsed.path == "/profile":
                params = parse_qs(parsed.query)
                profile_id = params.get("profile_id", ["demo_profile"])[0]
                self._render_profile(profile_id)
                return

            job_id = job_id_from_request_path(self.path)
            if job_id is not None:
                self._render_job(job_id)
                return

            self._send_html(render_page("Not found", "<p>Page not found.</p>"), status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            # Check for JSON-body routes before reading form data
            decision_match = re.match(r"^/job/([^/]+)/decision$", parsed.path)
            if decision_match:
                job_id = decision_match.group(1)
                self._handle_decision_override(job_id)
                return
            if parsed.path == "/jobs/save":
                self._handle_jobs_save()
                return
            if parsed.path == "/tailor":
                self._handle_tailor()
                return
            if parsed.path == "/cover-letter":
                self._handle_cover_letter()
                return
            form = self._read_form_data()
            if parsed.path == "/evaluate":
                self._handle_evaluate(form)
                return
            if parsed.path == "/select/reed":
                self._handle_reed_select(form)
                return
            if parsed.path == "/prefill":
                self._handle_prefill(form)
                return
            if parsed.path == "/job-submit":
                self._handle_job_submit(form)
                return
            if parsed.path == "/outcome":
                self._handle_outcome(form)
                return
            if parsed.path == "/profile/parse-cv":
                self._handle_parse_cv()
                return
            if parsed.path == "/profile/save":
                self._handle_save_profile(form)
                return
            self._send_html(render_page("Not found", "<p>Page not found.</p>"), status=HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def _render_profile(
            self,
            profile_id: str,
            *,
            parsed_cv_text: str | None = None,
            parsed_filename: str | None = None,
            errors: dict[str, str] | None = None,
            form_values: dict[str, str] | None = None,
        ) -> None:
            profile_dir = _allowed_profile_dir(profile_id)
            if profile_dir is None:
                self._send_html(render_page("Invalid profile", "<p>Invalid profile ID.</p>"), status=HTTPStatus.BAD_REQUEST)
                return

            profile_json_path = profile_dir / "candidate_profile.json"
            try:
                profile_obj = load_candidate_profile(profile_json_path)
            except FileNotFoundError:
                profile_obj = None

            page = render_profile_page(
                profile_id=profile_id,
                profile_obj=profile_obj,
                parsed_cv_text=parsed_cv_text,
                parsed_filename=parsed_filename,
                errors=errors or {},
                form_values=form_values,
            )
            self._send_html(page)

        def _handle_parse_cv(self) -> None:
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                self._send_json({"ok": False, "error": "Expected multipart/form-data"}, status=HTTPStatus.BAD_REQUEST)
                return

            try:
                form_data = self._read_multipart_form()
            except Exception as exc:
                self._send_json({"ok": False, "error": f"Failed to parse form data: {exc}"}, status=HTTPStatus.BAD_REQUEST)
                return

            file_item = form_data.get("cv_file")
            if not file_item:
                self._send_json({"ok": False, "error": "No cv_file field provided"}, status=HTTPStatus.BAD_REQUEST)
                return

            filename = file_item.get("filename", "")
            content = file_item.get("content", b"")

            # Extension check
            ext = Path(filename).suffix.lower()
            if ext not in _ALLOWED_CV_EXTENSIONS:
                self._send_json({"ok": False, "error": f"Unsupported file type: {ext}. Accepted: .txt, .pdf, .docx"}, status=HTTPStatus.BAD_REQUEST)
                return

            # Size check
            if len(content) > _MAX_CV_SIZE_BYTES:
                self._send_json({"ok": False, "error": "File too large. Maximum size is 5 MB."}, status=HTTPStatus.PAYLOAD_TOO_LARGE)
                return

            # MIME check (basic)
            content_str = content[:20].decode("latin-1", errors="replace")
            if ext == ".pdf" and not content_str.startswith("%PDF"):
                self._send_json({"ok": False, "error": "File does not appear to be a valid PDF"}, status=HTTPStatus.BAD_REQUEST)
                return

            # Write temp file
            temp_dir = Path("temp_uploads")
            temp_dir.mkdir(exist_ok=True)
            temp_path = temp_dir / f"{uuid.uuid4().hex}{ext}"
            temp_path.write_bytes(content)

            try:
                text = parse_cv_file(temp_path)
            except Exception as exc:
                temp_path.unlink(missing_ok=True)
                self._send_json({"ok": False, "error": f"Could not extract text from file: {exc}"}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                return
            finally:
                temp_path.unlink(missing_ok=True)

            self._send_json({
                "ok": True,
                "master_cv_text": text,
                "filename": filename,
            })

        def _handle_save_profile(self, form: dict[str, str]) -> None:
            profile_id = form.get("profile_id", "").strip()
            if not profile_id:
                self._send_json({"ok": False, "errors": {"profile_id": "Profile ID is required"}}, status=HTTPStatus.BAD_REQUEST)
                return

            profile_dir = _allowed_profile_dir(profile_id)
            if profile_dir is None:
                self._send_json({"ok": False, "errors": {"profile_id": "Invalid profile ID"}}, status=HTTPStatus.BAD_REQUEST)
                return

            profile_json_path = profile_dir / "candidate_profile.json"

            # Build dict from form, then validate via candidate_profile_from_dict
            payload: dict[str, Any] = {}
            for field in ("name", "target_roles", "locations", "remote_preference",
                          "salary_floor_gbp", "right_to_work_uk",
                          "years_experience", "industries", "achievements",
                          "certifications", "master_cv_ref", "master_cv_text"):
                val = form.get(field, "").strip()
                if field in ("target_roles", "locations", "industries", "achievements", "certifications"):
                    payload[field] = [s.strip() for s in val.split(",") if s.strip()] if val else []
                elif field in ("salary_floor_gbp", "years_experience"):
                    payload[field] = float(val) if val else None
                elif field == "right_to_work_uk":
                    payload[field] = val.lower() in ("true", "1", "yes")
                else:
                    payload[field] = val or None

            # Skills: prefer skills_json (list[dict] from JS table), fall back to comma-split string
            skills_json_raw = form.get("skills_json", "").strip()
            if skills_json_raw:
                try:
                    payload["skills"] = json.loads(skills_json_raw)
                except (json.JSONDecodeError, ValueError):
                    payload["skills"] = []
            else:
                skills_val = form.get("skills", "").strip()
                payload["skills"] = [s.strip() for s in skills_val.split(",") if s.strip()] if skills_val else []

            payload["candidate_id"] = profile_id

            try:
                profile_obj = candidate_profile_from_dict(payload)
            except ProfileValidationError as exc:
                self._send_json({"ok": False, "errors": {"form": str(exc)}}, status=HTTPStatus.BAD_REQUEST)
                return

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
                # Update master_cv_ref in profile
                profile_obj.master_cv_ref = str(cv_path)
                save_candidate_profile(profile_obj, profile_json_path)

            self._redirect(f"/profile?profile_id={profile_id}")

        def _read_multipart_form(self) -> dict[str, dict[str, Any]]:
            """Parse a minimal multipart/form-data body."""
            content_type = self.headers.get("Content-Type", "")
            _, options = content_type.split(";", 1)
            _, boundary = options.strip().split("=", 1)
            boundary = boundary.encode()

            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length)

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

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def _render_home(
            self,
            *,
            values: dict[str, str] | None = None,
            error: str | None = None,
            tab: str = "search",
            search_values: dict[str, str] | None = None,
            reed_results: list[dict[str, Any]] | None = None,
            reed_error: str | None = None,
            evaluate_notice: str | None = None,
        ) -> None:
            tab = _normalize_home_tab(tab)
            profile = load_candidate_profile(config.profile_path)
            history = load_recent_job_history(config.state_root)
            profile_tab_html = _render_profile_tab_section(tab)
            reed_select_nonce = create_reed_select_nonce() if reed_results is not None and not reed_error else None
            page = render_home_page(
                profile=profile,
                history=history,
                values=values or default_form_values(),
                error=error,
                tab=tab,
                profile_tab_html=profile_tab_html,
                search_values=search_values,
                reed_results=reed_results,
                reed_error=reed_error,
                reed_select_nonce=reed_select_nonce,
                evaluate_notice=evaluate_notice,
            )
            self._send_html(page)

        def _render_job(
            self,
            job_id: str,
            *,
            flash: str | None = None,
            flash_kind: str = "success",
        ) -> None:
            if not job_id.strip():
                self._redirect("/")
                return

            try:
                reviewed_job = load_reviewed_job(job_id, config.state_root)
            except FileNotFoundError:
                self._send_html(
                    render_page("Job not found", "<p>No saved job was found for that id.</p>"),
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

            page = render_job_page(
                reviewed_job=reviewed_job,
                analysis=analysis,
                outcome=outcome,
                flash=flash,
                flash_kind=flash_kind,
            )
            self._send_html(page)

        def _handle_reed_search(self, params: dict[str, str]) -> None:
            search_values = normalize_reed_search_params(params)
            error: str | None = None
            results: list[dict[str, Any]] = []
            try:
                results = search_reed_jobs_for_ui(search_values)
            except Exception as exc:
                error = f"Reed search failed: {exc}. Manual fallback is still available."
            self._render_home(tab="search", search_values=search_values, reed_results=results, reed_error=error)

        def _handle_reed_select(self, form: dict[str, str]) -> None:
            try:
                values = reed_select_form_to_evaluate_values(form)
            except ValueError as exc:
                self._send_html(render_page("Invalid Reed selection", f"<p>{escape(str(exc))}</p>"), status=HTTPStatus.BAD_REQUEST)
                return
            self._render_home(
                values=values,
                tab="evaluate",
                evaluate_notice="This form was prefilled from a Reed search result. Review and edit the fields before clicking Evaluate.",
            )

        def _handle_evaluate(self, form: dict[str, str]) -> None:
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
                self._render_home(values=values, error=str(exc), tab="evaluate")
                return

            self._render_result(result)

        def _render_result(self, result: LocalEvaluationRunResult) -> None:
            try:
                outcome = load_application_outcome(result.reviewed_job.job_id, config.state_root)
            except FileNotFoundError:
                outcome = None
            # Upsert hook: update index after evaluate flow saves analysis
            try:
                from src.job_hunt_index import upsert_job
                upsert_job(_db_path, {
                    "job_id": result.reviewed_job.job_id,
                    "job_title": result.reviewed_job.job_title,
                    "company": result.reviewed_job.company,
                    "location": result.reviewed_job.location,
                    "source": result.reviewed_job.source_type,
                    "match_score": result.analysis.match_score,
                    "decision": result.analysis.decision,
                    "user_decision": result.analysis.user_decision,
                    "ats_score": result.analysis.ats_score,
                    "tailoring_ready": result.analysis.tailoring_ready,
                    "status": outcome.status if outcome else "not_applied",
                    "updated_at": outcome.updated_at if outcome else None,
                    "salary_min": result.reviewed_job.salary_min_gbp,
                    "salary_max": result.reviewed_job.salary_max_gbp,
                })
            except Exception:
                pass  # Never crash the evaluate flow due to index failure
            page = render_job_page(
                reviewed_job=result.reviewed_job,
                analysis=result.analysis,
                outcome=outcome,
                flash="Job evaluated and saved locally.",
                flash_kind="success",
            )
            self._send_html(page)

        def _handle_prefill(self, form: dict[str, str]) -> None:
            mode = form.get("prefill_mode", "").strip()
            try:
                if mode == "paste":
                    payload = parse_job_from_text(form.get("job_text", ""))
                elif mode == "url":
                    payload = parse_job_from_url(form.get("job_url", ""))
                else:
                    raise ValueError("prefill_mode must be paste or url")
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
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
            self._send_json({"ok": True, "values": values})

        def _handle_job_submit(self, form: dict[str, str]) -> None:
            # Auto-generate job_id if not provided
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
                self._send_json({"ok": False, "errors": {"form": str(exc)}}, status=HTTPStatus.BAD_REQUEST)
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
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                return

            # Upsert hook: update index after job-submit evaluate flow
            try:
                from src.job_hunt_index import upsert_job
                try:
                    outcome_js = load_application_outcome(result.reviewed_job.job_id, config.state_root)
                    js_status = outcome_js.status
                    js_updated_at = outcome_js.updated_at
                except FileNotFoundError:
                    js_status = "not_applied"
                    js_updated_at = None
                upsert_job(_db_path, {
                    "job_id": result.reviewed_job.job_id,
                    "job_title": result.reviewed_job.job_title,
                    "company": result.reviewed_job.company,
                    "location": result.reviewed_job.location,
                    "source": result.reviewed_job.source_type,
                    "match_score": result.analysis.match_score,
                    "decision": result.analysis.decision,
                    "user_decision": result.analysis.user_decision,
                    "ats_score": result.analysis.ats_score,
                    "tailoring_ready": result.analysis.tailoring_ready,
                    "status": js_status,
                    "updated_at": js_updated_at,
                    "salary_min": result.reviewed_job.salary_min_gbp,
                    "salary_max": result.reviewed_job.salary_max_gbp,
                })
            except Exception:
                pass  # Never crash job-submit due to index failure

            # Redirect to GET /job/{job_id} — the existing result page
            self._redirect(f"/job/{result.reviewed_job.job_id}")

        def _handle_outcome(self, form: dict[str, str]) -> None:
            job_id = form.get("job_id", "").strip()
            if not job_id:
                self._redirect("/")
                return

            status = form.get("status", "").strip()
            notes = form.get("notes", "")
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
                self._render_job(job_id, flash=f"Outcome update failed: {exc}", flash_kind="error")
                return

            # Upsert hook: update index with new status after outcome save
            try:
                from src.job_hunt_index import upsert_job
                # Load reviewed job for title/company fields (may not exist for all jobs)
                try:
                    reviewed_job = load_reviewed_job(job_id, config.state_root)
                    rj_title = reviewed_job.job_title
                    rj_company = reviewed_job.company
                    rj_location = reviewed_job.location
                    rj_source = reviewed_job.source_type
                    rj_salary_min = reviewed_job.salary_min_gbp
                    rj_salary_max = reviewed_job.salary_max_gbp
                except FileNotFoundError:
                    rj_title = rj_company = rj_location = rj_source = rj_salary_min = rj_salary_max = None
                try:
                    analysis = load_job_analysis(job_id, config.state_root)
                    rj_match = analysis.match_score
                    rj_decision = analysis.decision
                    rj_user_decision = analysis.user_decision
                    rj_ats = analysis.ats_score
                    rj_tailoring = analysis.tailoring_ready
                except FileNotFoundError:
                    rj_match = rj_decision = rj_user_decision = rj_ats = rj_tailoring = None
                upsert_job(_db_path, {
                    "job_id": job_id,
                    "job_title": rj_title,
                    "company": rj_company,
                    "location": rj_location,
                    "source": rj_source,
                    "match_score": rj_match,
                    "decision": rj_decision,
                    "user_decision": rj_user_decision,
                    "ats_score": rj_ats,
                    "tailoring_ready": rj_tailoring,
                    "status": outcome.status,
                    "updated_at": outcome.updated_at,
                    "salary_min": rj_salary_min,
                    "salary_max": rj_salary_max,
                })
            except Exception:
                pass  # Never crash outcome flow due to index failure

            self._render_job(job_id, flash="Outcome updated.", flash_kind="success")

        def _handle_decision_override(self, job_id: str) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                self._send_json({"error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
                return

            if "user_decision" not in payload:
                self._send_json({"error": "user_decision is required"}, status=HTTPStatus.BAD_REQUEST)
                return

            user_decision = payload["user_decision"]
            if user_decision is not None and user_decision not in ("apply", "review", "skip"):
                self._send_json({"error": "user_decision must be apply, review, skip, or null"}, status=HTTPStatus.BAD_REQUEST)
                return

            note = payload.get("note")

            try:
                analysis = load_job_analysis(job_id, config.state_root)
            except FileNotFoundError:
                self._send_json({"error": f"Job analysis not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
                return

            import dataclasses
            analysis = dataclasses.replace(
                analysis,
                user_decision=user_decision,
                user_decision_note=note,
            )
            save_job_analysis(analysis, config.state_root)

            # Upsert hook: update index with new user_decision after decision override
            try:
                from src.job_hunt_index import upsert_job
                try:
                    reviewed_job_for_idx = load_reviewed_job(job_id, config.state_root)
                    idx_title = reviewed_job_for_idx.job_title
                    idx_company = reviewed_job_for_idx.company
                    idx_location = reviewed_job_for_idx.location
                    idx_source = reviewed_job_for_idx.source_type
                    idx_salary_min = reviewed_job_for_idx.salary_min_gbp
                    idx_salary_max = reviewed_job_for_idx.salary_max_gbp
                except FileNotFoundError:
                    idx_title = idx_company = idx_location = idx_source = idx_salary_min = idx_salary_max = None
                try:
                    outcome_for_idx = load_application_outcome(job_id, config.state_root)
                    idx_status = outcome_for_idx.status
                    idx_updated_at = outcome_for_idx.updated_at
                except FileNotFoundError:
                    idx_status = "not_applied"
                    idx_updated_at = None
                upsert_job(_db_path, {
                    "job_id": job_id,
                    "job_title": idx_title,
                    "company": idx_company,
                    "location": idx_location,
                    "source": idx_source,
                    "match_score": analysis.match_score,
                    "decision": analysis.decision,
                    "user_decision": analysis.user_decision,
                    "ats_score": analysis.ats_score,
                    "tailoring_ready": analysis.tailoring_ready,
                    "status": idx_status,
                    "updated_at": idx_updated_at,
                    "salary_min": idx_salary_min,
                    "salary_max": idx_salary_max,
                })
            except Exception:
                pass  # Never crash decision override due to index failure

            updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            self._send_json({
                "job_id": job_id,
                "engine_decision": analysis.decision,
                "user_decision": analysis.user_decision,
                "updated_at": updated_at,
            })

        def _handle_get_jobs(self) -> None:
            from src.job_hunt_index import query_jobs_list
            jobs = query_jobs_list(_db_path)
            self._send_json({"jobs": jobs})

        def _handle_get_board(self) -> None:
            from src.job_hunt_index import query_board
            board = query_board(_db_path)
            self._send_json(board)

        def _handle_jobs_save(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                self._send_json({"error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
                return

            job_title = (payload.get("job_title") or "").strip()
            company = (payload.get("company") or "").strip()
            if not job_title:
                self._send_json({"error": "job_title is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not company:
                self._send_json({"error": "company is required"}, status=HTTPStatus.BAD_REQUEST)
                return

            # Generate job_id
            job_id = f"manual-{uuid.uuid4().hex[:12]}"

            # Build minimal JobPosting
            job = JobPosting(
                job_id=job_id,
                job_title=job_title,
                company=company,
                description_raw=payload.get("description_raw") or "No description provided.",
                source_type=payload.get("source") or "manual",
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

            # Upsert into index
            from src.job_hunt_index import upsert_job
            upsert_job(_db_path, {
                "job_id": job_id,
                "job_title": job_title,
                "company": company,
                "location": job.location,
                "source": job.source_type,
                "match_score": None,
                "decision": None,
                "user_decision": None,
                "ats_score": None,
                "tailoring_ready": None,
                "status": "not_applied",
                "updated_at": outcome.updated_at,
                "salary_min": job.salary_min_gbp,
                "salary_max": job.salary_max_gbp,
            })

            self._send_json({"job_id": job_id, "status": "not_applied"})

        def _handle_tailor(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                self._send_json({"error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
                return

            job_id = (payload.get("job_id") or "").strip()
            if not job_id:
                self._send_json({"error": "job_id is required"}, status=HTTPStatus.BAD_REQUEST)
                return

            # Step 1: load analysis
            try:
                analysis = load_job_analysis(job_id, config.state_root)
            except FileNotFoundError:
                self._send_json({"error": f"Job analysis not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
                return

            # Step 2: check effective decision gate
            decision = effective_decision(analysis)
            if decision == "skip":
                self._send_json({"error": "Skipped jobs cannot be tailored"}, status=HTTPStatus.FORBIDDEN)
                return
            if decision == "review":
                manual_selected = payload.get("manual_selected")
                if manual_selected is not True:
                    self._send_json(
                        {"error": "Review decisions require manual_selected=true"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return

            # Step 3: load reviewed job
            try:
                job = load_reviewed_job(job_id, config.state_root)
            except FileNotFoundError:
                self._send_json({"error": f"Reviewed job not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
                return

            # Step 4: load profile and master CV
            try:
                profile = load_candidate_profile(config.profile_path)
            except Exception as exc:
                self._send_json({"error": f"Could not load candidate profile: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
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
                        self._send_json({"error": f"Could not load master CV: {exc}"}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                        return
                else:
                    self._send_json({"error": "No master CV available on candidate profile"}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                    return

            # Step 5: select evidence
            evidence = select_relevant_evidence(profile, cv_text, job, analysis)

            # Step 6: tailor CV
            result = tailor_cv(cv_text, evidence, job, profile=profile)

            # Step 7: validate
            try:
                valid = validate_tailored_cv(cv_text, result, profile)
                if not valid:
                    self._send_json({"error": "Tailored CV failed validation"}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                    return
            except TailoringValidationError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                return

            # Step 8: save
            path = save_tailored_cv(job_id, result, profile.candidate_id, DEFAULT_TAILORING_POLICY)

            self._send_json({
                "summary": result.summary,
                "promoted": result.promoted,
                "matched": result.matched,
                "missing": result.missing,
                "markdown": result.markdown,
                "saved_path": str(path),
            })

        def _handle_cover_letter(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                self._send_json({"error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
                return

            job_id = (payload.get("job_id") or "").strip()
            why_company_text = payload.get("why_company_text")
            if not job_id:
                self._send_json({"error": "job_id is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            if why_company_text is None or not str(why_company_text).strip():
                self._send_json({"error": "why_company_text is required"}, status=HTTPStatus.BAD_REQUEST)
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
                self._send_json({"error": f"Job analysis not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
                return

            # Step 2: decision gate
            decision = effective_decision(analysis)
            if decision == "skip":
                self._send_json(
                    {"error": "Cover letter not available for skipped jobs"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return

            # Step 3: load reviewed job
            try:
                job = load_reviewed_job(job_id, config.state_root)
            except FileNotFoundError:
                self._send_json({"error": f"Reviewed job not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
                return

            # Step 4: load profile and master CV
            try:
                profile = load_candidate_profile(config.profile_path)
            except Exception as exc:
                self._send_json({"error": f"Could not load candidate profile: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
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
                    except Exception:
                        cv_text = ""
                else:
                    cv_text = ""

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
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return

            # Step 6: save
            path = save_cover_letter(job_id, letter, profile.candidate_id)

            self._send_json({
                "letter": letter,
                "word_count": len(letter.split()),
                "saved_path": str(path),
            })

        def _read_form_data(self) -> dict[str, str]:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length).decode("utf-8")
            parsed = parse_qs(raw, keep_blank_values=True)
            return {key: values[-1] for key, values in parsed.items()}

        def _send_html(self, body: str, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _redirect(self, location: str) -> None:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", location)
            self.end_headers()

    return JobSeekingUIHandler


def reviewed_job_payload_from_form(form: dict[str, str]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_id": required_text(form, "job_id"),
        "job_title": required_text(form, "job_title"),
        "company": required_text(form, "company"),
        "description_raw": required_text(form, "description_raw"),
        "source_type": required_text(form, "source_type"),
        "source_ref": optional_text(form, "source_ref"),
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
        payload["source_snapshot"] = validate_reed_source_snapshot_json(form.get("source_snapshot_json", ""))
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

        rows.append(
            {
                "job_id": job_id,
                "job_title": reviewed_job.job_title,
                "company": reviewed_job.company,
                "decision": analysis.decision,
                "match_score": analysis.match_score,
                "confidence": analysis.confidence,
                "outcome_status": outcome_status,
            }
        )
    return rows


def render_home_page(
    *,
    profile: Any,
    history: list[dict[str, Any]],
    values: dict[str, str],
    error: str | None,
    tab: str = "search",
    profile_tab_html: str = "",
    search_values: dict[str, str] | None = None,
    reed_results: list[dict[str, Any]] | None = None,
    reed_error: str | None = None,
    reed_select_nonce: str | None = None,
    evaluate_notice: str | None = None,
) -> str:
    tab = _normalize_home_tab(tab)
    error_html = f'<div class="panel error">{escape(error)}</div>' if error else ""
    history_html = render_history_table(history)
    add_job_form_html = _render_add_job_tab(values)
    evaluate_notice_html = f'<div class="panel flash success">{escape(evaluate_notice)}</div>' if evaluate_notice else ""
    body = f"""
    <div class="layout">
      <nav class="top-tabs" aria-label="Main sections">
        <a href="/?tab=search" class="tab-link{" active" if tab == "search" else ""}" data-tab="search">Search Jobs</a>
        <a href="/?tab=evaluate" class="tab-link{" active" if tab == "evaluate" else ""}" data-tab="evaluate">Evaluate</a>
        <a href="/?tab=add_job" class="tab-link{" active" if tab == "add_job" else ""}" data-tab="add_job">Manual Fallback</a>
        <a href="/?tab=history" class="tab-link{" active" if tab == "history" else ""}" data-tab="history">History</a>
        <a href="/profile" class="tab-link{" active" if tab == "profile" else ""}" data-tab="profile">My Profile</a>
      </nav>
      <section class="panel">
        <h1>Job Seeking Tool — minimal local UI</h1>
        <ul>
          <li><strong>Profile:</strong> {escape(profile.name or profile.candidate_id)}</li>
          <li><strong>Target roles:</strong> {escape(', '.join(profile.target_roles) or 'Unknown')}</li>
          <li><strong>Master CV:</strong> {escape(profile.master_cv_ref or 'Not configured')}</li>
        </ul>
      </section>
      {error_html}
      <div id="tab-search" class="tab-content"{' hidden' if tab != 'search' else ''}>
        {_render_search_jobs_tab(search_values=search_values, reed_results=reed_results, reed_error=reed_error, reed_select_nonce=reed_select_nonce)}
      </div>
      <div id="tab-evaluate" class="tab-content"{' hidden' if tab != 'evaluate' else ''}>
        {evaluate_notice_html}
        <section class="panel">
          <h2>Enter and review one job</h2>
          <p><strong>Input method</strong> means how you brought the job in here first. <strong>Source type</strong> means what kind of source the saved reviewed record should represent for scoring and history.</p>
          <p><strong>Original pasted/context text</strong> is saved as reference only. <strong>Reviewed description used for scoring</strong> is the cleaned version you want the evaluation to use.</p>
          <form method="post" action="/evaluate" id="job-form">
            {render_input_form(values)}
            <div class="actions"><button type="submit">Evaluate and save locally</button></div>
          </form>
        </section>
      </div>
      <div id="tab-history" class="tab-content"{' hidden' if tab != 'history' else ''}>
        <section class="panel">
          <h2>Recent evaluated jobs</h2>
          {history_html}
        </section>
      </div>
      <div id="tab-add_job" class="tab-content"{' hidden' if tab != 'add_job' else ''}>
        {add_job_form_html}
      </div>
      <div id="tab-profile" class="tab-content"{' hidden' if tab != 'profile' else ''}>
        {profile_tab_html}
      </div>
    </div>
    """
    return render_page("Minimal local UI", body)


def _render_search_jobs_tab(
    *,
    search_values: dict[str, str] | None = None,
    reed_results: list[dict[str, Any]] | None = None,
    reed_error: str | None = None,
    reed_select_nonce: str | None = None,
) -> str:
    values = {**default_reed_search_values(), **(search_values or {})}
    results_html = render_reed_search_results(reed_results, reed_error=reed_error, reed_select_nonce=reed_select_nonce)
    return f"""
    <section class="panel">
      <h2>Search Jobs</h2>
      <p><strong>Reed-first job search</strong> is the primary way to find roles in this app. Reed is the only source wired in this phase.</p>
      <div class="source-toggles" style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;">
        <span style="background:#0f172a;color:white;border-radius:8px;padding:6px 14px;font-weight:600;font-size:0.875rem;">Reed</span>
        <span title="Coming soon" style="background:#e2e8f0;color:#94a3b8;border-radius:8px;padding:6px 14px;font-weight:600;font-size:0.875rem;cursor:not-allowed;">Adzuna — Coming soon</span>
        <span title="Coming soon" style="background:#e2e8f0;color:#94a3b8;border-radius:8px;padding:6px 14px;font-weight:600;font-size:0.875rem;cursor:not-allowed;">LinkedIn — Coming soon</span>
      </div>
      <form method="get" action="/search/reed" id="reed-search-form" class="panel subtle">
        <h3>Search Reed</h3>
        <div class="grid two-col">
          <label><span>Keywords / job title</span><input name="keywords" value="{escape(values['keywords'])}" placeholder="Business Analyst"></label>
          <label><span>Location</span><input name="locationName" value="{escape(values['locationName'])}" placeholder="London"></label>
          <label><span>Minimum salary</span><input name="minimumSalary" inputmode="numeric" value="{escape(values['minimumSalary'])}" placeholder="50000"></label>
          <label><span>Results to take</span><input name="resultsToTake" inputmode="numeric" value="{escape(values['resultsToTake'])}" placeholder="10"></label>
          <label><span>Work mode</span><select name="workMode">{render_select_options(['any', 'remote', 'hybrid', 'onsite'], values['workMode'])}</select></label>
          <label><span>Employment type</span><select name="employmentType">{render_select_options(['any', 'permanent', 'contract'], values['employmentType'])}</select></label>
        </div>
        <p class="prefill-status">Remote/hybrid and employment type are applied best-effort from Reed fields; unsupported filters are called out in result notes.</p>
        <div class="actions">
          <button type="submit">Search Reed</button>
          <a href="/?tab=add_job" class="tab-link active">Manual Fallback</a>
          <a href="/?tab=evaluate" class="tab-link">Evaluate existing details</a>
        </div>
      </form>
      {results_html}
    </section>
    """



_REED_SELECT_NONCES: dict[str, float] = {}
_REED_SELECT_NONCE_TTL_SECONDS = 15 * 60
_REED_SELECT_FIELD_LIMITS = {
    "source": 20,
    "source_job_id": 120,
    "title": 180,
    "company": 180,
    "location": 180,
    "work_mode": 40,
    "employment_type": 60,
    "url": 500,
    "description_raw": 501,
    "salary_min_gbp": 20,
    "salary_max_gbp": 20,
}
_ALLOWED_REED_WORK_MODES = {"", "unknown", "remote", "hybrid", "onsite"}
_ALLOWED_REED_EMPLOYMENT_TYPES = {"", "unknown", "permanent", "contract", "temporary", "full_time", "part_time"}
_REED_SOURCE_SNAPSHOT_MAX_BYTES = 20 * 1024
_REED_SOURCE_SNAPSHOT_VERSION = "pl-04-v1"


def create_reed_select_nonce() -> str:
    now = time.time()
    expired = [nonce for nonce, created in _REED_SELECT_NONCES.items() if now - created > _REED_SELECT_NONCE_TTL_SECONDS]
    for nonce in expired:
        _REED_SELECT_NONCES.pop(nonce, None)
    nonce = secrets.token_urlsafe(24)
    _REED_SELECT_NONCES[nonce] = now
    return nonce


def consume_reed_select_nonce(nonce: str) -> bool:
    created = _REED_SELECT_NONCES.pop((nonce or "").strip(), None)
    return created is not None and time.time() - created <= _REED_SELECT_NONCE_TTL_SECONDS


def render_reed_select_form(result: dict[str, Any], nonce: str | None) -> str:
    if not nonce or not result.get("source_snapshot_json"):
        return ""
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
    return f'<form method="post" action="/select/reed" class="actions reed-select-form">{"".join(hidden)}<button type="submit">Select / Review this job</button></form>'


def reed_select_form_to_evaluate_values(form: dict[str, str]) -> dict[str, str]:
    if not consume_reed_select_nonce(form.get("nonce", "")):
        raise ValueError("Invalid or expired Reed selection token. Please search again and select the job from the results.")
    cleaned: dict[str, str] = {}
    for key, limit in _REED_SELECT_FIELD_LIMITS.items():
        value = squash_whitespace(form.get(key, "")) if key != "description_raw" else (form.get(key, "") or "").strip()
        if len(value) > limit:
            raise ValueError(f"{key} is too long")
        cleaned[key] = value
    if cleaned["source"] != "reed":
        raise ValueError("Only Reed search results can be selected here")
    work_mode = cleaned["work_mode"].lower()
    if work_mode not in _ALLOWED_REED_WORK_MODES:
        raise ValueError("work_mode has an unsupported value")
    employment_type = cleaned["employment_type"].lower()
    if employment_type not in _ALLOWED_REED_EMPLOYMENT_TYPES:
        raise ValueError("employment_type has an unsupported value")
    salary_min = validate_reed_salary_text(cleaned["salary_min_gbp"], "salary_min_gbp")
    salary_max = validate_reed_salary_text(cleaned["salary_max_gbp"], "salary_max_gbp")
    source_snapshot = validate_reed_source_snapshot_json(form.get("source_snapshot_json", ""))
    values = default_form_values()
    source_job_id = cleaned["source_job_id"]
    source_ref = source_job_id or cleaned["url"]
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
            "copied_text": cleaned["description_raw"],
            "description_raw": cleaned["description_raw"],
            "required_skills": "",
            "preferred_skills": "",
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


def render_select_options(options: list[str], selected: str) -> str:
    return "".join(
        f'<option value="{escape(option)}"{" selected" if option == selected else ""}>{escape(option.title())}</option>'
        for option in options
    )


def default_reed_search_values() -> dict[str, str]:
    return {
        "keywords": "",
        "locationName": "",
        "minimumSalary": "",
        "workMode": "any",
        "employmentType": "any",
        "resultsToTake": "10",
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
    return values


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


def search_reed_jobs_for_ui(search_values: dict[str, str]) -> list[dict[str, Any]]:
    raw_jobs = fetch_reed_jobs(
        search_values["keywords"],
        search_values["locationName"],
        int(search_values["resultsToTake"]),
        save_raw=False,
    )
    return [reed_job_to_ui_result(raw, search_values) for raw in raw_jobs[: int(search_values["resultsToTake"])]]


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


def render_reed_search_results(
    results: list[dict[str, Any]] | None,
    *,
    reed_error: str | None = None,
    reed_select_nonce: str | None = None,
) -> str:
    if reed_error:
        return (
            '<div class="panel error"><h3>Reed search unavailable</h3>'
            f'<p>{escape(reed_error)}</p>'
            '<p>Reed is the only wired search source in this phase. You can still evaluate a job manually.</p>'
            '<p><a href="/?tab=add_job">Use Manual Fallback</a></p></div>'
        )
    if results is None:
        return ""
    if not results:
        return (
            '<div class="panel subtle"><h3>No Reed results found</h3>'
            '<p>No Reed jobs matched this search. Try broader keywords or location, or continue with manual input.</p>'
            '<p><a href="/?tab=add_job">Use Manual Fallback</a></p></div>'
        )
    cards = []
    for result in results:
        url = result.get("url")
        link_html = f'<a href="{escape(url)}" target="_blank" rel="noreferrer">Open Reed advert</a>' if url else "<span>No URL provided</span>"
        notes_html = "".join(f"<li>{escape(note)}</li>" for note in result.get("filter_notes", []))
        select_form_html = render_reed_select_form(result, reed_select_nonce)
        cards.append(f"""
        <article class="panel subtle reed-result-card">
          <h3>{escape(result.get('title') or 'Unknown')}</h3>
          <div class="detail-grid">
            {render_detail_item('Source', result.get('source') or 'reed')}
            {render_detail_item('Source job id', result.get('source_job_id') or 'Unknown')}
            {render_detail_item('Company', result.get('company') or 'Unknown')}
            {render_detail_item('Location', result.get('location') or 'Unknown')}
            {render_detail_item('Salary', result.get('salary_display') or 'Unknown')}
            {render_detail_item('Employment type', result.get('employment_type') or 'Unknown')}
            {render_detail_item('Work mode', result.get('work_mode') or 'Unknown')}
          </div>
          <p>{escape(result.get('description_preview') or '')}</p>
          <p>{link_html}</p>
          <ul>{notes_html}</ul>
          {select_form_html}
        </article>
        """)
    return f'<section class="panel"><h3>Reed results ({len(results)})</h3>{"".join(cards)}</section>'


def _render_profile_tab_section(current_tab: str) -> str:
    """Return HTML for the profile tab content (lazy: placeholder until GET /profile is loaded)."""
    if current_tab == "profile":
        # Content is served via GET /profile endpoint directly
        return "<section class=\"panel\"><p>Loading profile…</p></section>"
    return ""


def _render_add_job_tab(values: dict[str, str]) -> str:
    return f"""
    <section class="panel">
      <h2>Add a new job</h2>
      <p>Paste a job advert or enter a posting URL to prefill the form automatically.</p>
      <div id="add-job-input-step">
        <div class="tab-row" role="tablist" aria-label="Job input method">
          <button type="button" class="tab-button active" data-add-job-tab="paste">Paste Text</button>
          <button type="button" class="tab-button" data-add-job-tab="url">Job URL</button>
        </div>
        <div class="tab-panel active" data-add-job-panel="paste">
          <label><span>Paste job text</span><textarea id="add-job-text" placeholder="Paste the raw job advert text here"></textarea></label>
          <div class="actions"><button type="button" id="add-job-parse-btn">Parse &amp; Preview</button></div>
        </div>
        <div class="tab-panel" data-add-job-panel="url" hidden>
          <label><span>Job posting URL</span><input id="add-job-url" type="url" placeholder="https://example.com/job"></label>
          <div class="actions"><button type="button" id="add-job-parse-url-btn">Parse &amp; Preview</button></div>
        </div>
        <p id="add-job-status" class="prefill-status" aria-live="polite"></p>
      </div>
      <div id="add-job-review-step" hidden>
        <hr style="margin: 20px 0; border: none; border-top: 1px solid #e2e8f0;">
        <h3>Review and edit</h3>
        <p>Review the prefilled fields below, then click <strong>Evaluate</strong> to save and evaluate the job.</p>
        <form method="post" action="/job-submit" id="add-job-form">
          {_render_add_job_form_fields(values)}
          <div class="actions">
            <button type="button" id="add-job-back-btn">← Back</button>
            <button type="submit" id="add-job-submit-btn">Evaluate →</button>
          </div>
        </form>
      </div>
    </section>
    <script>
    (function () {{
      // --- Inner tab switching (Paste / URL within Add Job input step) ---
        'var cvTextarea = document.querySelector("textarea[name=\'master_cv_text']");'
        tabBtn.addEventListener('click', function() {{
          var name = tabBtn.dataset.addJobTab;
          document.querySelectorAll('[data-add-job-tab]').forEach(function(b) {{ b.classList.toggle('active', b.dataset.addJobTab === name); }});
          document.querySelectorAll('[data-add-job-panel]').forEach(function(p) {{
            var show = p.dataset.addJobPanel === name;
            p.classList.toggle('active', show);
            p.hidden = !show;
          }});
        }});
      }});

      var inputStep = document.getElementById('add-job-input-step');
      var reviewStep = document.getElementById('add-job-review-step');
      var status = document.getElementById('add-job-status');
      var form = document.getElementById('add-job-form');
      var backBtn = document.getElementById('add-job-back-btn');

      function setStatus(msg, isError) {{
        if (!status) return;
        status.textContent = msg;
        status.style.color = isError ? '#b91c1c' : '#475569';
      }}

      function showReviewStep() {{
        if (inputStep) inputStep.hidden = true;
        if (reviewStep) reviewStep.hidden = false;
      }}

      function showInputStep() {{
        if (reviewStep) reviewStep.hidden = true;
        if (inputStep) inputStep.hidden = false;
        setStatus('');
      }}

      async function parseAndPreview(mode) {{
        var payload = new URLSearchParams();
        payload.set('prefill_mode', mode);
        if (mode === 'paste') payload.set('job_text', document.getElementById('add-job-text') && document.getElementById('add-job-text').value || '');
        if (mode === 'url') payload.set('job_url', document.getElementById('add-job-url') && document.getElementById('add-job-url').value || '');
        setStatus('Parsing...');
        try {{
          var response = await fetch('/prefill', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' }},
            body: payload.toString()
          }});
          var data = await response.json();
          if (!response.ok || !data.ok) throw new Error(data.error || 'Parse failed');
          // Fill form fields and update badges
          var filledValues = data.values || {{}};
          Object.entries(filledValues).forEach(function(entry) {{
            var name = entry[0];
            var value = entry[1] || '';
            var field = form && form.elements.namedItem(name);
            if (!field) return;
            if (field.tagName === 'TEXTAREA' || field.tagName === 'INPUT') {{
              field.value = value;
            }}
          }});
          // Update field-review badges
          document.querySelectorAll('.field-badge').forEach(function(badge) {{
            var fieldName = badge.dataset.badgeFor;
            var rawValue = filledValues[fieldName];
            var isEmpty = rawValue === null || rawValue === undefined || rawValue === '' || rawValue === 'unknown';
            badge.hidden = false;
            badge.querySelector('.badge-autofilled').hidden = isEmpty;
            badge.querySelector('.badge-notfound').hidden = !isEmpty;
          }});
          setStatus('Prefilled. Review the form below, then click Evaluate.');
          showReviewStep();
        }} catch (err) {{
          setStatus(err.message || 'Parse failed', true);
        }}
      }}

      document.getElementById('add-job-parse-btn').addEventListener('click', function() {{ parseAndPreview('paste'); }});
      document.getElementById('add-job-parse-url-btn').addEventListener('click', function() {{ parseAndPreview('url'); }});
      backBtn && backBtn.addEventListener('click', showInputStep);
    }})();
    </script>
    """


def _render_add_job_form_fields(values: dict[str, str]) -> str:
    """Render all form fields for the Add Job form (hidden inputs + visible fields).

    Fields that came from the parser show a badge:
    - "Auto-filled" (green) when value is non-empty
    - "Not found" (amber) when value is empty/None
    """

    # Fields that can be auto-filled by the parser (badge applies after prefill)
    PARSER_FIELDS = {
        "job_title", "company", "location", "work_mode", "employment_type",
        "required_years_experience", "nice_to_have_years_experience",
        "domain", "salary_min_gbp", "salary_max_gbp",
        "required_skills", "preferred_skills", "notes",
    }

    def _badge(name: str) -> str:
        """Return an inline badge span for parser-filled fields (hidden by default; JS reveals)."""
        if name not in PARSER_FIELDS:
            return ""
        return (
            f' <span class="field-badge" data-badge-for="{escape(name)}" hidden>'
            f'<span class="badge-autofilled" hidden>Auto-filled</span>'
            f'<span class="badge-notfound" hidden>Not found</span>'
            f'</span>'
        )

    def field(name: str, label: str, *, textarea: bool = False, placeholder: str = "") -> str:
        value = escape(values.get(name, ""))
        badge = _badge(name)
        label_span = f'<span>{escape(label)}{badge}</span>'
        if textarea:
            return f'<label>{label_span}<textarea name="{escape(name)}" placeholder="{escape(placeholder)}">{value}</textarea></label>'
        return f'<label>{label_span}<input name="{escape(name)}" value="{value}" placeholder="{escape(placeholder)}"></label>'

    return f"""
      <div class="grid two-col">
        {field('job_id', 'Job id (leave blank to auto-generate)')}
        {field('input_method', 'Input method', placeholder='url or copied_text')}
        {field('job_url', 'Job URL')}
        {field('source_type', 'Saved source type', placeholder='url or copied_text')}
        {field('source_ref', 'Source reference (e.g. URL)')}
        {field('job_title', 'Title')}
        {field('company', 'Company')}
        {field('location', 'Location')}
        {field('work_mode', 'Work mode')}
        {field('employment_type', 'Employment type')}
        {field('required_years_experience', 'Required years experience')}
        {field('nice_to_have_years_experience', 'Nice-to-have years experience')}
        {field('domain', 'Domain')}
        {field('salary_min_gbp', 'Salary min GBP')}
        {field('salary_max_gbp', 'Salary max GBP')}
      </div>
      <div class="grid two-col">
        {field('copied_text', 'Original pasted/context text (reference only)', textarea=True)}
        {field('description_raw', 'Reviewed description used for scoring', textarea=True, placeholder='Cleaned/confirmed description for evaluation')}
      </div>
      <div class="grid two-col">
        {field('required_skills', 'Required skills (comma or newline separated)', textarea=True)}
        {field('preferred_skills', 'Preferred skills (comma or newline separated)', textarea=True)}
      </div>
      {field('notes', 'Notes', textarea=True)}
    """


def render_input_form(values: dict[str, str]) -> str:
    def field(name: str, label: str, *, textarea: bool = False, placeholder: str = "") -> str:
        value = escape(values.get(name, ""))
        if textarea:
            return f'<label><span>{escape(label)}</span><textarea name="{escape(name)}" placeholder="{escape(placeholder)}">{value}</textarea></label>'
        return f'<label><span>{escape(label)}</span><input name="{escape(name)}" value="{value}" placeholder="{escape(placeholder)}"></label>'

    source_snapshot_hidden = f'<input type="hidden" name="source_snapshot_json" value="{escape(values.get("source_snapshot_json", ""))}">' if values.get("source_snapshot_json") else ""
    return f"""
      {source_snapshot_hidden}
      <section class="panel subtle" id="prefill-panel">
        <h3>Quick prefill</h3>
        <div class="tab-row" role="tablist" aria-label="Prefill method tabs">
          <button type="button" class="tab-button active" data-prefill-tab="paste">Paste</button>
          <button type="button" class="tab-button" data-prefill-tab="url">URL</button>
        </div>
        <div class="tab-panel active" data-prefill-panel="paste">
          <label><span>Paste job text</span><textarea id="prefill-job-text" placeholder="Paste the raw job advert here"></textarea></label>
          <div class="actions"><button type="button" id="prefill-paste-btn">Prefill from paste</button></div>
        </div>
        <div class="tab-panel" data-prefill-panel="url" hidden>
          <label><span>Job posting URL</span><input id="prefill-job-url" type="url" placeholder="https://example.com/job"></label>
          <div class="actions"><button type="button" id="prefill-url-btn">Prefill from URL</button></div>
        </div>
        <p id="prefill-status" class="prefill-status" aria-live="polite"></p>
      </section>
      <div class="grid two-col">
        {field('job_id', 'Job id')}
        {field('input_method', 'Input method used to enter this job', placeholder='url or copied_text')}
        {field('job_url', 'Job URL')}
        {field('source_type', 'Saved source type for this reviewed job', placeholder='url or copied_text')}
        {field('source_ref', 'Source reference (for example URL or note id)')}
        {field('job_title', 'Title')}
        {field('company', 'Company')}
        {field('location', 'Location')}
        {field('work_mode', 'Work mode')}
        {field('employment_type', 'Employment type')}
        {field('required_years_experience', 'Required years experience')}
        {field('nice_to_have_years_experience', 'Nice-to-have years experience')}
        {field('domain', 'Domain')}
        {field('salary_min_gbp', 'Salary min GBP')}
        {field('salary_max_gbp', 'Salary max GBP')}
      </div>
      <div class="grid two-col">
        {field('copied_text', 'Original pasted/context text (reference only)', textarea=True)}
        {field('description_raw', 'Reviewed description used for scoring', textarea=True, placeholder='Cleaned/confirmed description for evaluation')}
      </div>
      <div class="grid two-col">
        {field('required_skills', 'Required skills (comma or newline separated)', textarea=True)}
        {field('preferred_skills', 'Preferred skills (comma or newline separated)', textarea=True)}
      </div>
      {field('notes', 'Notes', textarea=True)}
    """


def render_history_table(history: list[dict[str, Any]]) -> str:
    if not history:
        return "<p>No evaluated jobs saved yet.</p>"

    rows = []
    for item in history:
        rows.append(
            "<tr>"
            f"<td><a href=\"/job?job_id={escape(item['job_id'])}\">{escape(item['job_id'])}</a></td>"
            f"<td>{escape(item['job_title'])}</td>"
            f"<td>{escape(item['company'])}</td>"
            f"<td>{escape(item['decision'])}</td>"
            f"<td>{item['match_score']:.1f}</td>"
            f"<td>{escape(item['confidence'])}</td>"
            f"<td>{escape(item['outcome_status'] or '—')}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>Job id</th><th>Title</th><th>Company</th><th>Decision</th><th>Score</th><th>Confidence</th><th>Outcome</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def render_job_page(
    *,
    reviewed_job: Any,
    analysis: Any,
    outcome: Any,
    flash: str | None,
    flash_kind: str = "success",
) -> str:
    flash_class = "flash error" if flash_kind == "error" else "flash success"
    flash_html = f'<div class="panel {flash_class}">{escape(flash)}</div>' if flash else ""
    if analysis is not None:
        breakdown_items = [
            ("Skills", analysis.score_breakdown.skills_score),
            ("Experience", analysis.score_breakdown.experience_score),
            ("Location", analysis.score_breakdown.location_score),
            ("Salary", analysis.score_breakdown.salary_score),
            ("Domain", analysis.score_breakdown.domain_score),
            ("Work mode", analysis.score_breakdown.work_mode_score),
        ]
        breakdown_html = "".join(
            f"<li><strong>{escape(label)}:</strong> {component.value:.1f} — {escape(component.reason)}</li>"
            for label, component in breakdown_items
        )
        eff_decision = effective_decision(analysis)
        override_badge_html = (
            ' <span style="background:#fef3c7;color:#92400e;border-radius:4px;padding:2px 8px;font-size:0.75rem;font-weight:700;">Overridden</span>'
            if analysis.user_decision is not None and analysis.user_decision != analysis.decision
            else ""
        )
        def _override_btn(label: str, value: str) -> str:
            active = "background:#0f172a;color:white;" if eff_decision == value else "background:#e2e8f0;color:#0f172a;"
            return (
                f'<button type="button" class="override-btn" data-job-id="{escape(reviewed_job.job_id)}" '
                f'data-decision="{escape(value)}" data-current="{escape(eff_decision)}" '
                f'style="{active}border:0;border-radius:8px;padding:8px 14px;font:inherit;cursor:pointer;">{escape(label)}</button>'
            )
        override_buttons_html = f"""
        <div style="margin-top:12px;">
          <strong>Override decision:</strong>{override_badge_html}
          <div style="display:flex;gap:8px;margin-top:6px;flex-wrap:wrap;">
            {_override_btn("Apply", "apply")}
            {_override_btn("Review", "review")}
            {_override_btn("Skip", "skip")}
          </div>
          <p id="override-status" style="min-height:1.25rem;margin-top:4px;color:#475569;font-size:0.875rem;"></p>
        </div>
        <script>
        (function() {{
          document.querySelectorAll('.override-btn').forEach(function(btn) {{
            btn.addEventListener('click', function() {{
              var jobId = btn.dataset.jobId;
              var decision = btn.dataset.decision;
              var current = btn.dataset.current;
              // Clicking active button clears the override
              var payload = current === decision ? {{user_decision: null}} : {{user_decision: decision}};
              fetch('/job/' + jobId + '/decision', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(payload)
              }}).then(function(r) {{ return r.json(); }}).then(function(data) {{
                var status = document.getElementById('override-status');
                if (status) status.textContent = 'Decision override saved.';
                setTimeout(function() {{ window.location.reload(); }}, 400);
              }}).catch(function() {{
                var status = document.getElementById('override-status');
                if (status) status.textContent = 'Failed to save override.';
              }});
            }});
          }});
        }})();
        </script>
        """
        summary_grid_html = f"""
        <div class="summary-grid">
          <div><strong>Decision</strong><br>{escape(analysis.decision)}</div>
          <div><strong>Match score</strong><br>{analysis.match_score:.1f}</div>
          <div><strong>Confidence</strong><br>{escape(analysis.confidence)}</div>
          <div><strong>Tailoring</strong><br>{'Eligible when tailored CV support is added' if analysis.tailoring_ready else 'Not eligible yet — tailored CV support is not implemented in this UI'}</div>
        </div>
        <p>{escape(analysis.decision_reason)}</p>
        {override_buttons_html}
        """
        explainable_result_html = f"""
        <section class="panel">
          <h2>Explainable result</h2>
          {render_simple_list('Blockers', [item.label + ': ' + item.reason for item in analysis.blockers])}
          {render_simple_list('Risk flags', [item.label + ': ' + item.reason for item in analysis.risk_flags])}
          {render_simple_list('Strengths', analysis.strengths)}
          {render_simple_list('Missing required skills', analysis.missing_required_skills)}
          {render_simple_list('Missing preferred skills', analysis.missing_preferred_skills)}
          <h3>Score breakdown</h3>
          <ul>{breakdown_html}</ul>
          <h3>ATS readiness</h3>
          <p>{"ATS readiness: " + str(analysis.ats_score) + " / 100" if analysis.ats_score is not None else "ATS score: N/A (no CV on file)"}</p>
        </section>
        """
    else:
        summary_grid_html = '<div class="summary-grid"><div><strong>Decision</strong><br>—</div><div><strong>Match score</strong><br>—</div><div><strong>Confidence</strong><br>—</div><div><strong>Tailoring</strong><br>—</div></div><p><em>Evaluation has not been run for this job yet.</em></p>'
        explainable_result_html = ""
    outcome_options = "".join(
        f'<option value="{status}"{" selected" if outcome and outcome.status == status else ""}>{status}</option>'
        for status in ALLOWED_OUTCOME_STATUSES
    )
    sq = getattr(reviewed_job, "source_quality_score", None)
    if sq is not None and sq < 40:
        quality_badge_html = f'<p><span style="background:#fee2e2;color:#b91c1c;border-radius:6px;padding:3px 10px;font-weight:600;font-size:0.875rem;">Quality: {sq} — Low data quality</span></p>'
    elif sq is not None and sq < 70:
        quality_badge_html = f'<p><span style="background:#fef3c7;color:#92400e;border-radius:6px;padding:3px 10px;font-weight:600;font-size:0.875rem;">Quality: {sq} — Review fields carefully</span></p>'
    else:
        quality_badge_html = ""
    body = f"""
    <div class="layout">
      <nav><a href="/">← Back to entry</a></nav>
      {flash_html}
      <section class="panel">
        <h1>{escape(reviewed_job.job_title)} @ {escape(reviewed_job.company)}</h1>
        {quality_badge_html}
        {summary_grid_html}
      </section>
      {explainable_result_html}
      <section class="panel">
        <h2>Reviewed job fields</h2>
        <div class="detail-grid">
          {render_detail_item('Job id', reviewed_job.job_id)}
          {render_detail_item('Saved source type', reviewed_job.source_type)}
          {render_detail_item('Source reference', reviewed_job.source_ref)}
          {render_detail_item('Location', reviewed_job.location)}
          {render_detail_item('Work mode', reviewed_job.work_mode)}
          {render_detail_item('Employment type', reviewed_job.employment_type)}
          {render_detail_item('Required years experience', reviewed_job.required_years_experience)}
          {render_detail_item('Nice-to-have years experience', reviewed_job.nice_to_have_years_experience)}
          {render_detail_item('Domain', reviewed_job.domain)}
          {render_detail_item('Salary range', format_salary_range(reviewed_job.salary_min_gbp, reviewed_job.salary_max_gbp))}
        </div>
        {render_simple_list('Required skills', reviewed_job.required_skills)}
        {render_simple_list('Preferred skills', reviewed_job.preferred_skills)}
        <h3>Reviewed description used for scoring</h3>
        <pre>{escape(reviewed_job.description_raw)}</pre>
        <h3>Notes</h3>
        <p>{escape(reviewed_job.notes or 'None')}</p>
      </section>
      <section class="panel">
        <h2>Outcome tracking</h2>
        <p>Current status: <strong>{escape(outcome.status if outcome else 'not_applied')}</strong></p>
        <p>Last updated: <strong>{escape(outcome.updated_at if outcome else 'Not tracked yet')}</strong></p>
        <form method="post" action="/outcome">
          <input type="hidden" name="job_id" value="{escape(reviewed_job.job_id)}">
          <label><span>Status</span><select name="status">{outcome_options}</select></label>
          <label><span>Notes</span><textarea name="notes">{escape(outcome.notes if outcome and outcome.notes else '')}</textarea></label>
          <div class="actions"><button type="submit">Save outcome</button></div>
        </form>
      </section>
    </div>
    """
    return render_page(f"{reviewed_job.job_title} @ {reviewed_job.company}", body)


def render_simple_list(title: str, items: list[str]) -> str:
    if not items:
        return f"<h3>{escape(title)}</h3><p>None</p>"
    rendered = "".join(f"<li>{escape(item)}</li>" for item in items)
    return f"<h3>{escape(title)}</h3><ul>{rendered}</ul>"


def render_detail_item(label: str, value: Any) -> str:
    rendered_value = value if value not in (None, "") else "Unknown"
    return f'<div class="panel"><strong>{escape(label)}</strong><br>{escape(rendered_value)}</div>'







def render_profile_page(
    *,
    profile_id: str,
    profile_obj: Any,
    parsed_cv_text: str | None,
    parsed_filename: str | None,
    errors: dict[str, str],
    form_values: dict[str, str] | None,
) -> str:
    """Render the My Profile tab page."""

    # Summary
    if profile_obj:
        summary_rows = [
            ("Name", profile_obj.name or "—"),
            ("Target roles", ", ".join(profile_obj.target_roles) or "—"),
            ("Locations", ", ".join(profile_obj.locations) or "—"),
            ("Remote preference", profile_obj.remote_preference or "—"),
            ("Salary floor", f"£{profile_obj.salary_floor_gbp:,}" if profile_obj.salary_floor_gbp else "—"),
            ("Right to work UK", str(profile_obj.right_to_work_uk) if profile_obj.right_to_work_uk is not None else "—"),
            ("Skills", ", ".join(s.name for s in profile_obj.skills[:10]) + ("…" if len(profile_obj.skills) > 10 else "") or "—"),
            ("Years experience", str(profile_obj.years_experience) if profile_obj.years_experience else "—"),
            ("Industries", ", ".join(profile_obj.industries[:5]) + ("…" if len(profile_obj.industries) > 5 else "") or "—"),
            ("Master CV ref", profile_obj.master_cv_ref or "—"),
        ]
        summary_html = "".join(
            f"<tr><td><strong>{escape(label)}</strong></td><td>{escape(str(val))}</td></tr>"
            for label, val in summary_rows
        )
        summary_section = (
            "<section class=" + '"panel">'
            f"<h2>Current profile summary</h2>"
            f"<table><tbody>{summary_html}</tbody></table></section>"
        )
    else:
        summary_section = (
            "<section class=" + '"panel">'
            "<h2>Current profile summary</h2>"
            "<p><em>No profile saved yet. Fill the form below and click Save.</em></p>"
            "</section>"
        )

    # Error banner
    if errors:
        if "form" in errors:
            error_banner = f'<div class="panel error">{escape(errors["form"])}</div>'
        else:
            error_items = "".join(
                f"<li><strong>{escape(k)}:</strong> {escape(v)}</li>" for k, v in errors.items()
            )
            error_banner = f'<div class="panel error"><ul>{error_items}</ul></div>'
    else:
        error_banner = ""

    # Form helpers
    fv = form_values or {}

    def fvget(key: str, default: str = "") -> str:
        return escape(fv.get(key, default))

    def objval(key: str) -> str:
        return str(getattr(profile_obj, key, "") or "")

    cv_text = escape(parsed_cv_text or (profile_obj.master_cv_text if profile_obj else ""))
    cv_filename_val = escape(parsed_filename or (profile_obj.master_cv_ref if profile_obj else ""))
    remote_sel = fvget("remote_preference", objval("remote_preference"))

    def sel_opt(value: str, label: str) -> str:
        s = " selected" if remote_sel == value else ""
        return f'<option value="{escape(value)}"{s}>{escape(label)}</option>'

    # Pre-compute skills JSON for the table (replay from form_values or load from profile)
    _skills_json_replay = fv.get("skills_json", "")
    if _skills_json_replay:
        _skills_init_json = escape(_skills_json_replay)
    else:
        _skills_list = [
            {"name": s.name, "level": s.level, "years": s.years, "evidence_type": s.evidence_type}
            for s in (profile_obj.skills if profile_obj else [])
        ]
        _skills_init_json = escape(json.dumps(_skills_list, ensure_ascii=False))

    # Build body via string concat - each piece is a single-quoted Python string
    # inner double-quotes inside HTML work via string concatenation: "<attr " + "value" + ">"
    body = (
        '<div class="layout">'
        '<nav class="top-tabs" aria-label="Main sections">'
        '<a href="/?tab=search" class="tab-link">Search Jobs</a>'
        '<a href="/?tab=evaluate" class="tab-link">Evaluate</a>'
        '<a href="/?tab=add_job" class="tab-link">Manual Fallback</a>'
        '<a href="/?tab=history" class="tab-link">History</a>'
        '<a href="/profile" class="tab-link active">My Profile</a>'
        '</nav>'
        + error_banner
        + summary_section
        + '<section class="panel">'
        + '<h2>Upload CV</h2>'
        + '<p>Upload a .txt, .pdf, or .docx file (max 5 MB) to extract your CV text, then edit and save your profile.</p>'
        + '<div style="margin-bottom: 16px;">'
        + '<input type="file" id="cv-file-input" accept=".txt,.pdf,.docx">'
        + '<button type="button" id="cv-upload-btn" style="margin-top:8px;">Parse CV</button>'
        + '<p id="cv-upload-status" style="min-height:1.25rem; margin-top:4px; color:#475569;"></p>'
        + '</div>'
        + '<div id="cv-parsed-preview" hidden style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px;margin-bottom:16px;">'
        + '<p style="color:#2563eb;font-weight:600;">CV parsed! Review the text below and fill in the rest of the form.</p>'
        + '<p style="font-size:0.9em;color:#64748b;">Filename: '
        + cv_filename_val
        + '</p></div></section>'
        + '<section class="panel">'
        + '<h2>Profile details</h2>'
        + '<form method="post" action="/profile/save" id="profile-form">'
        + '<input type="hidden" name="profile_id" value="'
        + escape(profile_id)
        + '">'
        + '<input type="hidden" name="_cv_filename" id="cv-filename-field" value="'
        + cv_filename_val
        + '">'
        + '<div class="grid two-col">'
        + '<label><span>Name</span><input name="name" value="'
        + fvget("name", objval("name"))
        + '"></label>'
        + '<label><span>Target roles (comma-separated)</span><input name="target_roles" value="'
        + fvget("target_roles", ", ".join(getattr(profile_obj, "target_roles", []) or []))
        + '" placeholder="e.g. Business Analyst, Data Analyst"></label>'
        + '<label><span>Locations (comma-separated)</span><input name="locations" value="'
        + fvget("locations", ", ".join(getattr(profile_obj, "locations", []) or []))
        + '" placeholder="e.g. London, Manchester, Remote"></label>'
        + '<label><span>Remote preference</span>'
        + '<select name="remote_preference">'
        + '<option value="">— not set —</option>'
        + sel_opt("remote", "remote")
        + sel_opt("hybrid_friendly", "hybrid_friendly")
        + sel_opt("office_only", "office_only")
        + '</select></label>'
        + '<label><span>Salary floor (GBP)</span><input name="salary_floor_gbp" type="number" min="0" value="'
        + fvget("salary_floor_gbp", objval("salary_floor_gbp"))
        + '"></label>'
        + '<label><span>Years experience</span><input name="years_experience" type="number" min="0" step="0.5" value="'
        + fvget("years_experience", objval("years_experience"))
        + '"></label>'
        + '</div>'
        + '<div class="grid two-col" style="margin-top:12px;">'
        + '<div style="grid-column:1/-1;">'
        + '<span style="font-weight:600;font-size:0.875rem;display:block;margin-bottom:4px;">Skills</span>'
        + '<table id="skills-table" style="width:100%;border-collapse:collapse;font-size:0.875rem;">'
        + '<thead><tr>'
        + '<th style="text-align:left;padding:4px 8px;border-bottom:1px solid #e2e8f0;">Name</th>'
        + '<th style="text-align:left;padding:4px 8px;border-bottom:1px solid #e2e8f0;">Level</th>'
        + '<th style="text-align:left;padding:4px 8px;border-bottom:1px solid #e2e8f0;">Years</th>'
        + '<th style="border-bottom:1px solid #e2e8f0;width:40px;"></th>'
        + '</tr></thead>'
        + '<tbody id="skills-tbody"></tbody>'
        + '</table>'
        + '<button type="button" id="add-skill-btn" style="margin-top:6px;font-size:0.8rem;padding:4px 10px;">+ Add skill</button>'
        + '<input type="hidden" name="skills_json" id="skills_json" value="'
        + _skills_init_json
        + '">'
        + '</div>'
        + '<label><span>Industries (comma-separated)</span><input name="industries" value="'
        + fvget("industries", ", ".join(getattr(profile_obj, "industries", []) or []))
        + '" placeholder="Finance, Technology"></label>'
        + '<label><span>Certifications (comma-separated)</span><input name="certifications" value="'
        + fvget("certifications", ", ".join(getattr(profile_obj, "certifications", []) or []))
        + '" placeholder="AWS, PMP, CFA"></label>'
        + '</div>'
        + '<label style="margin-top:12px;"><span>Achievements (one per line)</span>'
        + '<textarea name="achievements" rows="4">'
        + fvget("achievements", "\\n".join(getattr(profile_obj, "achievements", []) or []))
        + '</textarea>'
        + '</label>'
        + '<label><span>Master CV text</span><textarea name="master_cv_text" rows="8" placeholder="Extracted CV text will appear here after upload, or paste manually...">'
        + cv_text
        + '</textarea></label>'
        + '<div style="margin-top:16px;">'
        + '<button type="submit" id="profile-save-btn">Save Profile</button>'
        + '<span id="profile-save-status" style="margin-left:16px;"></span>'
        + '</div>'
        + '</form>'
        + '</section>'
        + '</div>'
        + '<script>'
        + '(function () {'
        + 'var fileInput = document.getElementById("cv-file-input");'
        + 'var uploadBtn = document.getElementById("cv-upload-btn");'
        + 'var statusEl = document.getElementById("cv-upload-status");'
        + 'var previewEl = document.getElementById("cv-parsed-preview");'
        + 'var cvTextarea = document.querySelector("textarea[name=master_cv_text]");'
        + 'var cvFilenameField = document.getElementById("cv-filename-field");'
        + 'function setStatus(msg, isError) {'
        + 'if (!statusEl) return;'
        + 'statusEl.textContent = msg;'
        + 'statusEl.style.color = isError ? "#b91c1c" : "#2563eb";'
        + '}'
        + 'uploadBtn && uploadBtn.addEventListener("click", async function() {'
        + 'var file = fileInput && fileInput.files && fileInput.files[0];'
        + 'if (!file) { setStatus("Please select a file first.", true); return; }'
        + 'if (file.size > 5 * 1024 * 1024) { setStatus("File too large. Maximum is 5 MB.", true); return; }'
        + 'var ext = file.name.split(".").pop().toLowerCase();'
        + 'if (!["txt","pdf","docx"].includes(ext)) { setStatus("Unsupported file type. Use .txt, .pdf, or .docx", true); return; }'
        + 'setStatus("Uploading and parsing...");'
        + 'var formData = new FormData();'
        + 'formData.append("cv_file", file);'
        + 'try {'
        + 'var response = await fetch("/profile/parse-cv", { method: "POST", body: formData });'
        + 'var data = await response.json();'
        + 'if (!response.ok || !data.ok) throw new Error(data.error || "Parse failed");'
        + 'if (cvTextarea) cvTextarea.value = data.master_cv_text || "";'
        + 'if (cvFilenameField) cvFilenameField.value = data.filename || file.name;'
        + 'if (previewEl) previewEl.hidden = false;'
        + 'setStatus("CV parsed successfully. Review and save below.");'
        + '} catch(err) {'
        + 'setStatus(err.message || "Parse failed", true);'
        + '}'
        + '});'
        + '})();'
        + '(function () {'
        + 'var LEVELS = ["unspecified","junior","mid","senior","expert"];'
        + 'var tbody = document.getElementById("skills-tbody");'
        + 'var hiddenField = document.getElementById("skills_json");'
        + 'var form = document.getElementById("profile-form");'
        + 'function makeRow(skill) {'
        + '  var tr = document.createElement("tr");'
        + '  var tdName = document.createElement("td"); tdName.style.padding = "4px 8px";'
        + '  var nameInput = document.createElement("input");'
        + '  nameInput.type = "text"; nameInput.placeholder = "e.g. Python"; nameInput.value = skill.name || "";'
        + '  nameInput.style.cssText = "width:100%;box-sizing:border-box;";'
        + '  tdName.appendChild(nameInput);'
        + '  var tdLevel = document.createElement("td"); tdLevel.style.padding = "4px 8px";'
        + '  var levelSel = document.createElement("select");'
        + '  LEVELS.forEach(function(l) {'
        + '    var opt = document.createElement("option"); opt.value = l; opt.textContent = l;'
        + '    if (l === (skill.level || "unspecified")) opt.selected = true;'
        + '    levelSel.appendChild(opt);'
        + '  });'
        + '  tdLevel.appendChild(levelSel);'
        + '  var tdYears = document.createElement("td"); tdYears.style.padding = "4px 8px";'
        + '  var yearsInput = document.createElement("input");'
        + '  yearsInput.type = "number"; yearsInput.min = "0"; yearsInput.step = "1"; yearsInput.style.width = "60px";'
        + '  yearsInput.value = (skill.years != null) ? String(skill.years) : "";'
        + '  tdYears.appendChild(yearsInput);'
        + '  var tdDel = document.createElement("td"); tdDel.style.padding = "4px 8px";'
        + '  var delBtn = document.createElement("button"); delBtn.type = "button"; delBtn.textContent = "✕";'
        + '  delBtn.style.cssText = "background:none;border:none;cursor:pointer;color:#b91c1c;font-size:1rem;padding:0 4px;";'
        + '  delBtn.onclick = function() { tr.remove(); };'
        + '  tdDel.appendChild(delBtn);'
        + '  tr.appendChild(tdName); tr.appendChild(tdLevel); tr.appendChild(tdYears); tr.appendChild(tdDel);'
        + '  return tr;'
        + '}'
        + 'function initTable() {'
        + '  var raw = hiddenField ? hiddenField.value : "[]";'
        + '  var skills = [];'
        + '  try { skills = JSON.parse(raw) || []; } catch(e) {}'
        + '  skills.forEach(function(s) { tbody.appendChild(makeRow(s)); });'
        + '}'
        + 'function serializeTable() {'
        + '  var rows = tbody ? tbody.rows : [];'
        + '  var result = [];'
        + '  for (var i = 0; i < rows.length; i++) {'
        + '    var cells = rows[i].cells;'
        + '    var name = cells[0].querySelector("input").value.trim();'
        + '    if (!name) continue;'
        + '    var level = cells[1].querySelector("select").value;'
        + '    var yearsVal = cells[2].querySelector("input").value.trim();'
        + '    var years = yearsVal !== "" ? parseInt(yearsVal, 10) : null;'
        + '    result.push({ name: name, level: level, years: years, evidence_type: "self-reported" });'
        + '  }'
        + '  return JSON.stringify(result);'
        + '}'
        + 'document.getElementById("add-skill-btn") && document.getElementById("add-skill-btn").addEventListener("click", function() {'
        + '  tbody.appendChild(makeRow({ name: "", level: "unspecified", years: null }));'
        + '});'
        + 'form && form.addEventListener("submit", function() {'
        + '  if (hiddenField) hiddenField.value = serializeTable();'
        + '});'
        + 'initTable();'
        + '})();'
        + '</script>'
    )
    return render_page(f"My Profile — {escape(profile_id)}", body)


def format_salary_range(min_salary: int | None, max_salary: int | None) -> str:
    if min_salary is None and max_salary is None:
        return "Unknown"
    if min_salary is not None and max_salary is not None:
        return f"£{min_salary:,} – £{max_salary:,}"
    if min_salary is not None:
        return f"From £{min_salary:,}"
    return f"Up to £{max_salary:,}"


def render_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; background: #f5f7fb; color: #1f2937; }}
    .layout {{ max-width: 1080px; margin: 0 auto; padding: 24px; }}
    .panel {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
    .error {{ border-left: 4px solid #b91c1c; }}
    .flash {{ border-left-width: 4px; border-left-style: solid; }}
    .flash.success {{ border-left-color: #2563eb; background: #eff6ff; }}
    .flash.error {{ border-left-color: #b91c1c; background: #fef2f2; }}
    .grid {{ display: grid; gap: 12px; }}
    .two-col {{ grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }}
    .subtle {{ background: #f8fafc; box-shadow: inset 0 0 0 1px #e2e8f0; }}
    .tab-row {{ display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }}
    .tab-button {{ background: #e2e8f0; color: #0f172a; }}
    .tab-button.active {{ background: #0f172a; color: white; }}
    .tab-panel[hidden] {{ display: none; }}
    .tab-content[hidden] {{ display: none; }}
    .top-tabs {{ display: flex; gap: 4px; margin-bottom: 16px; background: white; border-radius: 12px; padding: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); flex-wrap: wrap; }}
    .tab-link {{ padding: 8px 16px; border-radius: 8px; color: #475569; font-weight: 600; text-decoration: none; }}
    .tab-link:hover {{ background: #f1f5f9; color: #0f172a; }}
    .tab-link.active {{ background: #0f172a; color: white; }}
    .prefill-status {{ min-height: 1.25rem; margin: 8px 0 0; color: #475569; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }}
    .detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 16px; }}
    label {{ display: block; margin-bottom: 12px; }}
    label span {{ display: block; font-weight: 600; margin-bottom: 6px; }}
    input, textarea, select {{ width: 100%; box-sizing: border-box; padding: 10px; border: 1px solid #cbd5e1; border-radius: 8px; font: inherit; }}
    textarea {{ min-height: 120px; }}
    button {{ background: #0f172a; color: white; border: 0; border-radius: 8px; padding: 10px 16px; font: inherit; cursor: pointer; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }}
    pre {{ background: #0f172a; color: #e5e7eb; padding: 16px; border-radius: 8px; overflow: auto; white-space: pre-wrap; }}
    a {{ color: #2563eb; text-decoration: none; }}
    .actions {{ margin-top: 12px; }}
    .field-badge {{ display: inline-block; margin-left: 6px; vertical-align: middle; }}
    .badge-autofilled {{ display: inline-block; background: #dcfce7; color: #166534; font-size: 0.7rem; font-weight: 700; border-radius: 4px; padding: 1px 6px; }}
    .badge-notfound {{ display: inline-block; background: #fef3c7; color: #92400e; font-size: 0.7rem; font-weight: 700; border-radius: 4px; padding: 1px 6px; }}
  </style>
</head>
<body>
{body}
  <script>
    document.addEventListener('DOMContentLoaded', () => {{
      const tabs = document.querySelectorAll('[data-prefill-tab]');
      const panels = document.querySelectorAll('[data-prefill-panel]');
      const status = document.getElementById('prefill-status');
      const form = document.getElementById('job-form');

      function setStatus(message, isError = false) {{
        if (!status) return;
        status.textContent = message;
        status.style.color = isError ? '#b91c1c' : '#475569';
      }}

      function showTab(name) {{
        tabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.prefillTab === name));
        panels.forEach((panel) => {{
          const active = panel.dataset.prefillPanel === name;
          panel.classList.toggle('active', active);
          panel.hidden = !active;
        }});
      }}

      async function prefill(mode) {{
        const payload = new URLSearchParams();
        payload.set('prefill_mode', mode);
        if (mode === 'paste') payload.set('job_text', document.getElementById('prefill-job-text')?.value || '');
        if (mode === 'url') payload.set('job_url', document.getElementById('prefill-job-url')?.value || '');
        setStatus('Prefilling...');
        try {{
          const response = await fetch('/prefill', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' }},
            body: payload.toString(),
          }});
          const data = await response.json();
          if (!response.ok || !data.ok) throw new Error(data.error || 'Prefill failed');
          Object.entries(data.values || {{}}).forEach(([name, value]) => {{
            const field = form?.elements.namedItem(name);
            if (!field) return;
            field.value = value ?? '';
          }});
          setStatus('Form prefilled. Review before saving.');
        }} catch (error) {{
          setStatus(error.message || 'Prefill failed', true);
        }}
      }}

      tabs.forEach((tab) => tab.addEventListener('click', () => showTab(tab.dataset.prefillTab)));
      document.getElementById('prefill-paste-btn')?.addEventListener('click', () => prefill('paste'));
      document.getElementById('prefill-url-btn')?.addEventListener('click', () => prefill('url'));
      showTab('paste');
    }});
  </script>
</body>
</html>
"""


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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
