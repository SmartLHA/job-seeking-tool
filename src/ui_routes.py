"""HTTP server, request dispatch, and CLI entry point (LT-1 Step 6).

Builds the :class:`BaseHTTPRequestHandler` subclass whose ``do_GET``/``do_POST``
parse the request into a :class:`UIRequest`, wrap the socket in a
:class:`UIResponder`, and dispatch to the standalone handlers in
:mod:`src.ui_handlers`. Pure routing — no business logic. Source modules are
imported here purely for their registration side effect.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Sequence
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

from src.ui_state import UIServerConfig
from src.ui_utils import escape, job_id_from_request_path
from src.ui_render import render_page
from src.job_hunt_profile import load_candidate_profile
from src.job_hunt_storage import ensure_storage_layout
from src.ui_handlers import (
    render_home,
    render_job,
    render_profile,
    handle_sources,
    handle_parse_cv,
    handle_save_profile,
    handle_job_explain,
    handle_qualitative_assess,
    handle_evaluate_form,
    handle_source_search,
    handle_source_select,
    handle_evaluate,
    handle_prefill,
    handle_job_submit,
    handle_outcome,
    handle_decision_override,
    handle_add_gap_skills,
    handle_ai_review_cv,
    handle_ats_recheck,
    handle_get_jobs,
    handle_get_board,
    handle_get_board_view,
    handle_batch_evaluate,
    handle_search_reed_more,
    handle_source_search_more,
    handle_get_review_queue,
    handle_jobs_save,
    handle_tailor,
    handle_cover_letter,
    handle_saved_searches_list,
    handle_saved_searches_create,
    handle_saved_search_delete,
    handle_saved_search_toggle,
    handle_digest_count,
    handle_digest,
    handle_digest_mark_seen,
    handle_run_now,
    handle_scheduler_status,
    handle_run_llm_batch,
    handle_digest_reevaluate,
    handle_llm_queue,
    handle_jobs_hide,
    handle_jobs_unhide,
    handle_jobs_hidden_list,
)

# Source registration (startup side effect). Adding a source = one import line.
from src.job_sources import reed_source as _reed_source  # noqa: F401  (registration side effect)
from src.job_sources import adzuna_source as _adzuna_src  # noqa: F401  (registration side effect)
from src.job_sources import linkedin_source as _linkedin_src  # noqa: F401  (registration side effect)


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
    # Load .env so REED_API_KEY (and others) are available to sub-modules
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # python-dotenv not installed; env vars must be set externally

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        from src.job_hunt_llm import _model as _get_model
        _model_label = _get_model()
    except Exception:
        _model_label = ""
    config = UIServerConfig(
        profile_path=Path(args.profile),
        state_root=Path(args.state_root),
        report_dir=Path(args.report_dir),
        host=args.host,
        port=args.port,
        model_label=_model_label,
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

    # D5/D6 daemons: auto-start, each no-ops while its profile toggle is off (and the
    # LLM worker also no-ops without a Gemini key). get_profile re-reads fresh each cycle.
    scheduler = worker = None
    try:
        from src.job_hunt_scheduler import DigestScheduler, LLMQueueWorker
        from src.ui_handlers import set_daemons

        def _get_profile():
            return load_candidate_profile(config.profile_path)

        scheduler = DigestScheduler(config, get_profile=_get_profile)
        worker = LLMQueueWorker(config, get_profile=_get_profile)
        scheduler.start()
        worker.start()
        set_daemons(scheduler=scheduler, worker=worker)
        print("Digest scheduler + LLM worker started (gated by your My Profile toggles).")
    except Exception as exc:  # pragma: no cover - never block the server on daemon startup
        logger.warning("Could not start digest daemons: %s", exc)

    print(f"Minimal local UI running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        print("\nUI stopped.")
    finally:
        # serve_forever() has already returned here; close the socket, then stop the
        # daemon threads (best-effort, bounded join).
        server.server_close()
        for d in (worker, scheduler):
            if d is not None:
                try:
                    d.stop()
                except Exception:  # pragma: no cover
                    pass
    return 0


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
            try:
                self._do_GET_inner()
            except Exception as exc:
                logger.exception("Unhandled error in do_GET: %s", exc)
                try:
                    UIResponder(self).send_html(render_page("Server error", f"<p>Internal error: {escape(str(exc))}</p>", model_label=config.model_label), status=HTTPStatus.INTERNAL_SERVER_ERROR)
                except Exception:
                    pass

        def _do_GET_inner(self) -> None:
            req = _parse_request(self)
            responder = UIResponder(self)
            parsed = urlparse(self.path)
            if parsed.path == "/":
                render_home(req, config, responder, tab=req.query.get("tab", "search"))
                return
            source_more_match = re.match(r"^/search/([a-z0-9_-]+)/more$", parsed.path)
            if source_more_match:
                handle_source_search_more(req, config, responder, source_more_match.group(1))
                return
            source_search_match = re.match(r"^/search/([a-z0-9_-]+)$", parsed.path)
            if source_search_match:
                handle_source_search(req, config, responder, source_search_match.group(1))
                return
            if parsed.path == "/sources":
                handle_sources(req, config, responder)
                return
            if parsed.path == "/jobs":
                handle_get_jobs(req, config, responder)
                return
            if parsed.path == "/jobs/not-interested":
                handle_jobs_hidden_list(req, config, responder)
                return
            if parsed.path == "/saved-searches":
                handle_saved_searches_list(req, config, responder)
                return
            if parsed.path == "/digest/count":
                handle_digest_count(req, config, responder)
                return
            if parsed.path == "/digest":
                handle_digest(req, config, responder)
                return
            if parsed.path == "/digest/llm-queue":
                handle_llm_queue(req, config, responder)
                return
            if parsed.path == "/scheduler/status":
                handle_scheduler_status(req, config, responder)
                return
            if parsed.path == "/board":
                handle_get_board(req, config, responder)
                return
            if parsed.path == "/board/view":
                handle_get_board_view(req, config, responder)
                return
            if parsed.path == "/profile":
                profile_id = req.query.get("profile_id", config.profile_path.stem)
                render_profile(req, config, responder, profile_id, flash=req.query.get("flash"))
                return
            explain_match = re.match(r"^/job/([^/]+)/explain$", parsed.path)
            if explain_match:
                handle_job_explain(req, config, responder, explain_match.group(1))
                return
            evaluate_form_match = re.match(r"^/job/([^/]+)/evaluate-form$", parsed.path)
            if evaluate_form_match:
                handle_evaluate_form(req, config, responder, evaluate_form_match.group(1))
                return
            job_id = job_id_from_request_path(self.path)
            if job_id is not None:
                render_job(req, config, responder, job_id)
                return
            if parsed.path == "/review-queue":
                handle_get_review_queue(req, config, responder)
                return
            responder.send_html(render_page("Not found", "<p>Page not found.</p>", model_label=config.model_label), status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            try:
                self._do_POST_inner()
            except Exception as exc:
                logger.exception("Unhandled error in do_POST: %s", exc)
                try:
                    UIResponder(self).send_json({"ok": False, "error": f"Internal server error: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                except Exception:
                    pass

        def _do_POST_inner(self) -> None:
            req = _parse_request(self)
            responder = UIResponder(self)
            parsed = urlparse(self.path)
            decision_match = re.match(r"^/job/([^/]+)/decision$", parsed.path)
            if decision_match:
                handle_decision_override(req, config, responder, decision_match.group(1))
                return
            add_gap_match = re.match(r"^/job/([^/]+)/add-gap-skills$", parsed.path)
            if add_gap_match:
                handle_add_gap_skills(req, config, responder, add_gap_match.group(1))
                return
            ai_cv_match = re.match(r"^/job/([^/]+)/ai-review-cv$", parsed.path)
            if ai_cv_match:
                handle_ai_review_cv(req, config, responder, ai_cv_match.group(1))
                return
            ats_recheck_match = re.match(r"^/job/([^/]+)/ats-recheck$", parsed.path)
            if ats_recheck_match:
                handle_ats_recheck(req, config, responder, ats_recheck_match.group(1))
                return
            qualitative_match = re.match(r"^/job/([^/]+)/qualitative-assess$", parsed.path)
            if qualitative_match:
                handle_qualitative_assess(req, config, responder, qualitative_match.group(1))
                return
            if parsed.path == "/jobs/batch-evaluate":
                handle_batch_evaluate(req, config, responder)
                return
            if parsed.path == "/jobs/save":
                handle_jobs_save(req, config, responder)
                return
            if parsed.path == "/jobs/not-interested":
                handle_jobs_hide(req, config, responder)
                return
            if parsed.path == "/jobs/not-interested/undo":
                handle_jobs_unhide(req, config, responder)
                return
            if parsed.path == "/saved-searches":
                handle_saved_searches_create(req, config, responder)
                return
            if parsed.path == "/digest/mark-seen":
                handle_digest_mark_seen(req, config, responder)
                return
            if parsed.path == "/digest/run-llm-batch":
                handle_run_llm_batch(req, config, responder)
                return
            if parsed.path == "/digest/reevaluate":
                handle_digest_reevaluate(req, config, responder)
                return
            ss_delete_match = re.match(r"^/saved-searches/([^/]+)/delete$", parsed.path)
            if ss_delete_match:
                handle_saved_search_delete(req, config, responder, ss_delete_match.group(1))
                return
            ss_toggle_match = re.match(r"^/saved-searches/([^/]+)/toggle$", parsed.path)
            if ss_toggle_match:
                handle_saved_search_toggle(req, config, responder, ss_toggle_match.group(1))
                return
            ss_run_match = re.match(r"^/saved-searches/([^/]+)/run-now$", parsed.path)
            if ss_run_match:
                handle_run_now(req, config, responder, ss_run_match.group(1))
                return
            if parsed.path == "/tailor":
                handle_tailor(req, config, responder)
                return
            if parsed.path == "/cover-letter":
                handle_cover_letter(req, config, responder)
                return
            if parsed.path == "/profile/parse-cv":
                handle_parse_cv(req, config, responder)
                return
            if parsed.path == "/evaluate":
                handle_evaluate(req, config, responder)
                return
            source_select_match = re.match(r"^/select/([a-z0-9_-]+)$", parsed.path)
            if source_select_match:
                handle_source_select(req, config, responder, source_select_match.group(1))
                return
            if parsed.path == "/prefill":
                handle_prefill(req, config, responder)
                return
            if parsed.path == "/job-submit":
                handle_job_submit(req, config, responder)
                return
            if parsed.path == "/outcome":
                handle_outcome(req, config, responder)
                return
            if parsed.path == "/profile/save":
                handle_save_profile(req, config, responder)
                return
            responder.send_html(render_page("Not found", "<p>Page not found.</p>", model_label=config.model_label), status=HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    return JobSeekingUIHandler


@dataclass
class UIResponder:
    handler: Any

    def send_html(self, body: str, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = body.encode("utf-8")
        self.handler.send_response(status)
        self.handler.send_header("Content-Type", "text/html; charset=utf-8")
        self.handler.send_header("Content-Length", str(len(encoded)))
        self.handler.end_headers()
        self.handler.wfile.write(encoded)

    def send_json(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.handler.send_response(status)
        self.handler.send_header("Content-Type", "application/json; charset=utf-8")
        self.handler.send_header("Content-Length", str(len(encoded)))
        self.handler.end_headers()
        self.handler.wfile.write(encoded)

    def redirect(self, location: str) -> None:
        self.handler.send_response(HTTPStatus.SEE_OTHER)
        self.handler.send_header("Location", location)
        self.handler.end_headers()


@dataclass
class UIRequest:
    method: str
    path: str
    query: dict
    form: dict
    json_body: Any
    raw_body: bytes
    headers: Any
    content_type: str


def _parse_request(handler) -> "UIRequest":
    parsed = urlparse(handler.path)
    query = {k: v[-1] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
    headers = handler.headers
    content_type = headers.get("Content-Type", "") or ""
    raw_body = b""
    if handler.command == "POST":
        length = int(headers.get("Content-Length", "0") or "0")
        if length:
            raw_body = handler.rfile.read(length)
    form: dict = {}
    json_body = None
    if "multipart/form-data" in content_type:
        pass
    elif content_type.startswith("application/json"):
        try:
            json_body = json.loads(raw_body.decode("utf-8") or "null")
        except Exception:
            json_body = None
    elif raw_body:
        form = {k: v[-1] for k, v in parse_qs(raw_body.decode("utf-8"), keep_blank_values=True).items()}
    return UIRequest(handler.command, handler.path, query, form, json_body, raw_body, headers, content_type)
