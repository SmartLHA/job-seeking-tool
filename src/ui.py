from __future__ import annotations

import argparse
import html
import sys
from dataclasses import dataclass
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, urlparse

from src.orchestrator import LocalEvaluationRunResult, run_local_evaluation_flow_from_payload
from src.parsing import parse_job_from_text, parse_job_from_url
from src.outcomes import ALLOWED_OUTCOME_STATUSES, create_outcome_record, update_outcome
from src.profile import load_candidate_profile
from src.storage import (
    ensure_storage_layout,
    load_application_outcome,
    load_job_analysis,
    load_reviewed_job,
    save_application_outcome,
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
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
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


def _build_handler(config: UIServerConfig) -> type[BaseHTTPRequestHandler]:
    class JobSeekingUIHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._render_home()
                return

            job_id = job_id_from_request_path(self.path)
            if job_id is not None:
                self._render_job(job_id)
                return

            self._send_html(render_page("Not found", "<p>Page not found.</p>"), status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            form = self._read_form_data()
            if parsed.path == "/evaluate":
                self._handle_evaluate(form)
                return
            if parsed.path == "/prefill":
                self._handle_prefill(form)
                return
            if parsed.path == "/outcome":
                self._handle_outcome(form)
                return
            self._send_html(render_page("Not found", "<p>Page not found.</p>"), status=HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def _render_home(self, *, values: dict[str, str] | None = None, error: str | None = None) -> None:
            profile = load_candidate_profile(config.profile_path)
            history = load_recent_job_history(config.state_root)
            page = render_home_page(
                profile=profile,
                history=history,
                values=values or default_form_values(),
                error=error,
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
                analysis = load_job_analysis(job_id, config.state_root)
                try:
                    outcome = load_application_outcome(job_id, config.state_root)
                except FileNotFoundError:
                    outcome = None
            except FileNotFoundError:
                self._send_html(
                    render_page("Job not found", "<p>No saved job was found for that id.</p>"),
                    status=HTTPStatus.NOT_FOUND,
                )
                return

            page = render_job_page(
                reviewed_job=reviewed_job,
                analysis=analysis,
                outcome=outcome,
                flash=flash,
                flash_kind=flash_kind,
            )
            self._send_html(page)

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
                self._render_home(values=values, error=str(exc))
                return

            self._render_result(result)

        def _render_result(self, result: LocalEvaluationRunResult) -> None:
            try:
                outcome = load_application_outcome(result.reviewed_job.job_id, config.state_root)
            except FileNotFoundError:
                outcome = None
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
            else:
                submitted_url = form.get("job_url", "").strip()
                values["input_method"] = "url"
                values["job_url"] = submitted_url
                values["source_ref"] = submitted_url or values.get("source_ref", "")
            self._send_json({"ok": True, "values": values})

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

            self._render_job(job_id, flash="Outcome updated.", flash_kind="success")

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
    return {
        "input_method": input_method,
        "source_type": reviewed_job_payload["source_type"],
        "source_ref": reviewed_job_payload.get("source_ref"),
        "job_url": optional_text(form, "job_url"),
        "copied_text": optional_text(form, "copied_text"),
        "description_raw": reviewed_job_payload["description_raw"],
    }


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


def render_home_page(*, profile: Any, history: list[dict[str, Any]], values: dict[str, str], error: str | None) -> str:
    error_html = f'<div class="panel error">{escape(error)}</div>' if error else ""
    history_html = render_history_table(history)
    body = f"""
    <div class="layout">
      <section class="panel">
        <h1>Job Seeking Tool — minimal local UI</h1>
        <p>This is a thin local shell over the current evaluation flow. Fill the reviewed fields, then run one saved local evaluation.</p>
        <ul>
          <li><strong>Profile:</strong> {escape(profile.name or profile.candidate_id)}</li>
          <li><strong>Target roles:</strong> {escape(', '.join(profile.target_roles) or 'Unknown')}</li>
          <li><strong>Master CV:</strong> {escape(profile.master_cv_ref or 'Not configured')}</li>
        </ul>
      </section>
      {error_html}
      <section class="panel">
        <h2>Enter and review one job</h2>
        <p><strong>Input method</strong> means how you brought the job in here first. <strong>Source type</strong> means what kind of source the saved reviewed record should represent for scoring and history.</p>
        <p><strong>Original pasted/context text</strong> is saved as reference only. <strong>Reviewed description used for scoring</strong> is the cleaned version you want the evaluation to use.</p>
        <form method="post" action="/evaluate" id="job-form">
          {render_input_form(values)}
          <div class="actions"><button type="submit">Evaluate and save locally</button></div>
        </form>
      </section>
      <section class="panel">
        <h2>Recent evaluated jobs</h2>
        {history_html}
      </section>
    </div>
    """
    return render_page("Minimal local UI", body)


def render_input_form(values: dict[str, str]) -> str:
    def field(name: str, label: str, *, textarea: bool = False, placeholder: str = "") -> str:
        value = escape(values.get(name, ""))
        if textarea:
            return f'<label><span>{escape(label)}</span><textarea name="{escape(name)}" placeholder="{escape(placeholder)}">{value}</textarea></label>'
        return f'<label><span>{escape(label)}</span><input name="{escape(name)}" value="{value}" placeholder="{escape(placeholder)}"></label>'

    return f"""
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
    outcome_options = "".join(
        f'<option value="{status}"{" selected" if outcome and outcome.status == status else ""}>{status}</option>'
        for status in ALLOWED_OUTCOME_STATUSES
    )
    body = f"""
    <div class="layout">
      <nav><a href="/">← Back to entry</a></nav>
      {flash_html}
      <section class="panel">
        <h1>{escape(reviewed_job.job_title)} @ {escape(reviewed_job.company)}</h1>
        <div class="summary-grid">
          <div><strong>Decision</strong><br>{escape(analysis.decision)}</div>
          <div><strong>Match score</strong><br>{analysis.match_score:.1f}</div>
          <div><strong>Confidence</strong><br>{escape(analysis.confidence)}</div>
          <div><strong>Tailoring</strong><br>{'Eligible when tailored CV support is added' if analysis.tailoring_ready else 'Not eligible yet — tailored CV support is not implemented in this UI'}</div>
        </div>
        <p>{escape(analysis.decision_reason)}</p>
      </section>
      <section class="panel">
        <h2>Explainable result</h2>
        {render_simple_list('Blockers', [item.label + ': ' + item.reason for item in analysis.blockers])}
        {render_simple_list('Risk flags', [item.label + ': ' + item.reason for item in analysis.risk_flags])}
        {render_simple_list('Strengths', analysis.strengths)}
        {render_simple_list('Missing required skills', analysis.missing_required_skills)}
        {render_simple_list('Missing preferred skills', analysis.missing_preferred_skills)}
        <h3>Score breakdown</h3>
        <ul>{breakdown_html}</ul>
      </section>
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
