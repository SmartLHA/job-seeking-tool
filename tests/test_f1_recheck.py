"""F1 v2 — ATS keyword-match re-check (design rev 3).

Covers the hardened tailored-CV loader, the baseline/source persistence on
JobAnalysis, the keyword panel renderer, and the /job/{id}/ats-recheck flow,
including the three high-severity items from the Codex review:
  H1 — AJAX panel must equal the post-reload panel (one view-model path).
  H2 — new fields survive save/load; old records default to master/no-baseline.
  H3 — an empty tailored file is a 422 and never overwrites a valid rate.
"""
from __future__ import annotations

import dataclasses
import html
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from src.job_hunt_config import TailoringPolicy
from src.job_hunt_models import JobAnalysis, ScoreBreakdown, ScoreComponent
from src.job_hunt_storage import (
    job_analysis_from_dict,
    job_analysis_to_dict,
    load_job_analysis,
    save_job_analysis,
)
from src.job_hunt_tailoring import EmptyTailoredCVError, load_latest_tailored_cv
from src.ui_render import render_keyword_match_panel
from src.ui_state import UIServerConfig
from src.ui_routes import _build_handler


# ─────────────────────────── loader unit tests ────────────────────────────

def _policy(tmp_path: Path) -> TailoringPolicy:
    out = tmp_path / "output" / "tailored_cvs"
    out.mkdir(parents=True, exist_ok=True)
    return TailoringPolicy(output_dir=out)


def _write_cv(policy: TailoringPolicy, name: str, text: str) -> None:
    (policy.output_dir / name).write_text(text, encoding="utf-8")


def test_loader_returns_none_when_no_tailored_file(tmp_path: Path) -> None:
    assert load_latest_tailored_cv("reed-1", policy=_policy(tmp_path)) is None


def test_loader_prefers_ai_reviewed_over_tailor_output(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    _write_cv(policy, "reed-1.md", "<!-- profile_id: cand-001 -->\nplain tailor output\n")
    _write_cv(policy, "reed-1_ai_reviewed.md", "<!-- ai_reviewed: true | profile_id: cand-001 -->\nAI reviewed body\n")
    assert load_latest_tailored_cv("reed-1", policy=policy) == "AI reviewed body"


def test_loader_strips_only_first_metadata_comment_line(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    body = "Line one\n<!-- not metadata, second line -->\nLine three"
    _write_cv(policy, "reed-1.md", f"<!-- profile_id: cand-001 -->\n{body}\n")
    loaded = load_latest_tailored_cv("reed-1", policy=policy)
    assert loaded == body
    assert "<!-- not metadata" in loaded  # only the FIRST comment line is stripped


def test_loader_keeps_full_text_when_no_header(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    _write_cv(policy, "reed-1.md", "No header here\njust content\n")
    assert load_latest_tailored_cv("reed-1", policy=policy) == "No header here\njust content"


@pytest.mark.parametrize("bad", ["..", ".", "../etc/passwd", "a/b", "x\\y", "", "has space"])
def test_loader_blocks_path_traversal_and_dot_ids(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        load_latest_tailored_cv(bad, policy=_policy(tmp_path))


def test_loader_empty_file_raises_empty_error(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    _write_cv(policy, "reed-1.md", "<!-- profile_id: cand-001 -->\n   \n")  # body blank after header
    with pytest.raises(EmptyTailoredCVError):
        load_latest_tailored_cv("reed-1", policy=policy)


def test_loader_profile_id_fail_closed(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    # matching header → returns body
    _write_cv(policy, "match.md", "<!-- profile_id: cand-001 -->\nbody\n")
    assert load_latest_tailored_cv("match", expected_profile_id="cand-001", policy=policy) == "body"
    # mismatched header → None
    _write_cv(policy, "wrong.md", "<!-- profile_id: someone-else -->\nbody\n")
    assert load_latest_tailored_cv("wrong", expected_profile_id="cand-001", policy=policy) is None
    # absent header → None (fail-closed)
    _write_cv(policy, "nohdr.md", "no metadata line\nbody\n")
    assert load_latest_tailored_cv("nohdr", expected_profile_id="cand-001", policy=policy) is None


# ────────────────────────── storage roundtrip (H2) ──────────────────────────

def _analysis(**overrides) -> JobAnalysis:
    sc = ScoreComponent(value=10.0, reason="ok")
    sb = ScoreBreakdown(
        skills_score=sc, experience_score=sc, location_score=sc,
        salary_score=sc, domain_score=sc, work_mode_score=sc, notes=[],
    )
    base = dict(
        job_id="job-1", match_score=50.0, score_breakdown=sb, decision_reason="ok",
        keyword_match_rate=40, keyword_match_baseline_rate=40, keyword_match_source="master",
    )
    base.update(overrides)
    return JobAnalysis(**base)


def test_analysis_roundtrip_preserves_baseline_and_source(tmp_path: Path) -> None:
    a = _analysis(keyword_match_rate=80, keyword_match_baseline_rate=40, keyword_match_source="tailored")
    save_job_analysis(a, tmp_path / "state")
    loaded = load_job_analysis("job-1", tmp_path / "state")
    assert loaded.keyword_match_baseline_rate == 40
    assert loaded.keyword_match_source == "tailored"
    assert loaded.keyword_match_rate == 80


def test_old_analysis_without_new_keys_loads_with_defaults() -> None:
    payload = job_analysis_to_dict(_analysis())
    payload.pop("keyword_match_baseline_rate", None)
    payload.pop("keyword_match_source", None)
    loaded = job_analysis_from_dict(payload, job_id="job-1")
    assert loaded.keyword_match_baseline_rate is None
    assert loaded.keyword_match_source == "master"


def test_invalid_source_rejected() -> None:
    with pytest.raises(ValueError):
        _analysis(keyword_match_source="bogus")


# ─────────────────────────── panel render unit tests ───────────────────────

def _panel(**over):
    args = dict(
        job_id="reed-1", keyword_match_rate=50,
        keywords_required_matched=["SQL"], keywords_required_missing=["AWS"],
        keywords_preferred_matched=[], keywords_preferred_missing=[],
        keywords_overused=[], keyword_match_baseline_rate=50, keyword_match_source="master",
    )
    args.update(over)
    return render_keyword_match_panel(**args)


def test_panel_master_has_button_no_delta() -> None:
    p = _panel(keyword_match_source="master")
    assert p.count('id="kw-panel-body"') == 1
    assert "Re-check against tailored CV" in p
    assert "&rarr;" not in p  # no delta on the master baseline


def test_panel_tailored_shows_delta_green_when_improved() -> None:
    p = _panel(keyword_match_rate=80, keyword_match_baseline_rate=50, keyword_match_source="tailored")
    assert "was 50%" in p and "now 80%" in p
    assert "var(--apply)" in p  # green when improved


def test_panel_tailored_no_baseline_shows_now_only() -> None:
    p = _panel(keyword_match_rate=80, keyword_match_baseline_rate=None, keyword_match_source="tailored")
    assert "now 80% (tailored CV)" in p
    assert "was " not in p


def test_panel_na_when_rate_none_suppresses_delta() -> None:
    p = _panel(keyword_match_rate=None, keyword_match_baseline_rate=None, keyword_match_source="tailored")
    assert "ATS keyword match — N/A" in p
    assert "now " not in p and "was " not in p


# ─────────────────────────── end-to-end flow tests ─────────────────────────

def _write_profile(tmp_path: Path) -> Path:
    profile_dir = tmp_path / "profile"
    (profile_dir / "docs").mkdir(parents=True, exist_ok=True)
    (profile_dir / "docs" / "master_cv.md").write_text("# Master CV\n", encoding="utf-8")
    profile_path = profile_dir / "candidate_profile.json"
    profile_path.write_text(
        json.dumps({
            "candidate_id": "cand-001", "name": "Mic", "target_roles": ["Business Analyst"],
            "locations": ["London"], "remote_preference": "remote_friendly", "salary_floor_gbp": 50000,
            "right_to_work_uk": True, "skills": ["Stakeholder Management", "Process Mapping", "SQL"],
            "years_experience": 5, "industries": ["finance"], "achievements": ["Improved reporting"],
            "certifications": ["BCS Foundation"], "master_cv_ref": "docs/master_cv.md",
        }),
        encoding="utf-8",
    )
    return profile_path


@contextmanager
def _running_ui_server(tmp_path: Path):
    config = UIServerConfig(
        profile_path=_write_profile(tmp_path),
        state_root=tmp_path / "state", report_dir=tmp_path / "reports",
        host="127.0.0.1", port=0,
    )
    server = ThreadingHTTPServer((config.host, config.port), _build_handler(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", config
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _post(url: str, form: dict | None = None) -> tuple[int, str]:
    data = urllib.parse.urlencode(form or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _evaluate_form(job_id: str, *, required: str, preferred: str) -> dict:
    return {
        "job_id": job_id, "job_title": "Business Analyst", "company": "Example Co",
        "description_raw": "Looking for stakeholder management and SQL.",
        "source_type": "copied_text", "source_ref": "manual-note-001",
        "input_method": "copied_text", "copied_text": "Original copied text",
        "location": "London", "work_mode": "hybrid", "employment_type": "full-time",
        "required_skills": required, "preferred_skills": preferred,
        "required_years_experience": "3", "domain": "finance",
        "salary_min_gbp": "50000", "salary_max_gbp": "55000", "notes": "Reviewed",
    }


def _seed_master_baseline(config, job_id: str, *, rate: int, required_missing, preferred_missing) -> None:
    """Force a known master-CV baseline on the stored analysis."""
    a = load_job_analysis(job_id, config.state_root)
    a = dataclasses.replace(
        a, keyword_match_rate=rate, keyword_match_baseline_rate=rate, keyword_match_source="master",
        keywords_required_missing=list(required_missing), keywords_preferred_missing=list(preferred_missing),
    )
    save_job_analysis(a, config.state_root)


def test_recheck_improves_rate_against_tailored_cv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # tailored CVs resolve under cwd/output/tailored_cvs
    with _running_ui_server(tmp_path) as (base, config):
        assert _post(f"{base}/evaluate", _evaluate_form("job-rc-1", required="Stakeholder Management, SQL", preferred="Power BI"))[0] in (200, 303)
        _seed_master_baseline(config, "job-rc-1", rate=40, required_missing=["SQL"], preferred_missing=["Power BI"])
        cvdir = tmp_path / "output" / "tailored_cvs"
        cvdir.mkdir(parents=True, exist_ok=True)
        (cvdir / "job-rc-1.md").write_text(
            "<!-- profile_id: cand-001 -->\nStakeholder Management, SQL and Power BI all covered.\n", encoding="utf-8",
        )
        status, body = _post(f"{base}/job/job-rc-1/ats-recheck")
        assert status == 200
        data = json.loads(body)
        assert data["ok"] is True
        assert data["baseline"] == 40
        assert data["rate"] > data["baseline"]
        # persisted: source flipped to tailored, baseline retained
        saved = load_job_analysis("job-rc-1", config.state_root)
        assert saved.keyword_match_source == "tailored"
        assert saved.keyword_match_baseline_rate == 40
        assert saved.keyword_match_rate == data["rate"]


def test_recheck_without_tailored_cv_returns_422_and_panel_unchanged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with _running_ui_server(tmp_path) as (base, config):
        _post(f"{base}/evaluate", _evaluate_form("job-rc-2", required="SQL", preferred="Power BI"))
        _seed_master_baseline(config, "job-rc-2", rate=40, required_missing=["SQL"], preferred_missing=[])
        status, body = _post(f"{base}/job/job-rc-2/ats-recheck")
        assert status == 422
        assert json.loads(body)["ok"] is False
        unchanged = load_job_analysis("job-rc-2", config.state_root)
        assert unchanged.keyword_match_source == "master"
        assert unchanged.keyword_match_rate == 40


def test_recheck_unknown_job_returns_404(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with _running_ui_server(tmp_path) as (base, _config):
        # tailored file exists so the loader passes; job/analysis do not exist → 404
        cvdir = tmp_path / "output" / "tailored_cvs"
        cvdir.mkdir(parents=True, exist_ok=True)
        (cvdir / "ghost.md").write_text("<!-- profile_id: cand-001 -->\nbody\n", encoding="utf-8")
        status, body = _post(f"{base}/job/ghost/ats-recheck")
        assert status == 404
        assert json.loads(body)["ok"] is False


def test_recheck_empty_tailored_cv_returns_422_and_does_not_mutate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with _running_ui_server(tmp_path) as (base, config):
        _post(f"{base}/evaluate", _evaluate_form("job-rc-3", required="SQL", preferred="Power BI"))
        _seed_master_baseline(config, "job-rc-3", rate=40, required_missing=["SQL"], preferred_missing=[])
        cvdir = tmp_path / "output" / "tailored_cvs"
        cvdir.mkdir(parents=True, exist_ok=True)
        (cvdir / "job-rc-3.md").write_text("<!-- profile_id: cand-001 -->\n   \n", encoding="utf-8")
        status, body = _post(f"{base}/job/job-rc-3/ats-recheck")
        assert status == 422
        assert "empty" in json.loads(body)["error"].lower()
        unchanged = load_job_analysis("job-rc-3", config.state_root)
        assert unchanged.keyword_match_rate == 40  # not clobbered with None
        assert unchanged.keyword_match_source == "master"


def test_recheck_panel_matches_reload_panel(tmp_path: Path, monkeypatch) -> None:
    """H1 — the AJAX panel must be byte-identical to the post-reload panel,
    even with casing differences and a skill listed as both required & preferred."""
    monkeypatch.chdir(tmp_path)
    with _running_ui_server(tmp_path) as (base, config):
        _post(f"{base}/evaluate", _evaluate_form("job-rc-4", required="Stakeholder Management, SQL", preferred="sql, Power BI"))
        _seed_master_baseline(config, "job-rc-4", rate=20, required_missing=["Stakeholder Management"], preferred_missing=["Power BI"])
        cvdir = tmp_path / "output" / "tailored_cvs"
        cvdir.mkdir(parents=True, exist_ok=True)
        (cvdir / "job-rc-4.md").write_text("<!-- profile_id: cand-001 -->\nSQL and Power BI present here.\n", encoding="utf-8")
        status, body = _post(f"{base}/job/job-rc-4/ats-recheck")
        assert status == 200
        panel_html = json.loads(body)["panel_html"]
        # the exact AJAX panel string must appear verbatim in the reloaded page
        reload_status, reload_body = _get(f"{base}/job/job-rc-4")
        assert reload_status == 200
        assert panel_html in reload_body
