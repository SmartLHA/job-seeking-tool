"""Feature C: application package zip (export bundle)."""
from __future__ import annotations

import dataclasses
import io
import json
import zipfile
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import pytest

from src import job_hunt_export, ui_handlers
from src.job_hunt_config import TailoringPolicy
from src.job_hunt_cover_letter import cover_letter_dir, load_cover_letter, save_cover_letter
from src.job_hunt_export import build_package, package_filename, validate_job_id
from src.job_hunt_models import Blocker, JobAnalysis, JobPosting, RiskFlag, ScoreBreakdown, ScoreComponent
from src.job_hunt_storage import (
    ensure_storage_layout,
    save_job_analysis,
    save_qualitative_assessment,
    save_reviewed_job,
)
from src.ui_render import JobPageViewModel, render_job_page
from src.ui_routes import UIResponder
from src.ui_state import UIServerConfig

CV_BODY = "# Jane CV\n\nBusiness analyst with SQL."
LETTER = "Dear hiring manager,\n\nI would like to apply."


def _comp(v=3.0):
    return ScoreComponent(value=v, reason="because")


def _analysis(job_id="job-1", decision="apply"):
    return JobAnalysis(
        job_id=job_id, match_score=82.5,
        score_breakdown=ScoreBreakdown(_comp(), _comp(), _comp(), _comp(), _comp(), _comp()),
        blockers=[Blocker(code="b1", label="Visa", reason="needs *sponsorship*", severity="medium")],
        missing_required_skills=["Python"],
        risk_flags=[RiskFlag(code="r1", label="Contract", reason="fixed term")],
        decision=decision, decision_reason="Strong fit", confidence="high",
    )


def _write_cv(cv_dir: Path, job_id: str, profile_id: str, body=CV_BODY, reviewed=False):
    cv_dir.mkdir(parents=True, exist_ok=True)
    name = f"{job_id}_ai_reviewed.md" if reviewed else f"{job_id}.md"
    (cv_dir / name).write_text(f"<!-- profile_id: {profile_id} -->\n{body}\n", encoding="utf-8")


class _Profile:
    candidate_id = "cand-1"
    # personal fields that must never leak
    name = "Jane Secret Person"
    email = "jane.secret@example.com"


@pytest.fixture
def env(tmp_path):
    state = tmp_path / "state"
    ensure_storage_layout(state)
    save_reviewed_job(JobPosting(
        job_id="job-1", job_title="Business Analyst", company="Acme *Ltd*",
        description_raw="Do analysis.", source_type="copied_text", source_ref="/private/raw/x.txt",
        location="London", work_mode=None, employment_type=None,
        required_skills=["SQL", "Python"], salary_min_gbp=50000, salary_max_gbp=60000,
        url="https://example.com/job/1"), state)
    out = tmp_path / "output"
    policy = TailoringPolicy(output_dir=out / "tailored_cvs")
    return {"state": state, "out": out, "policy": policy, "tmp": tmp_path}


def _build(env, job_id="job-1", profile=_Profile):
    data, manifest = build_package(
        job_id, profile, state_root=env["state"], policy=env["policy"], cover_letter_base=env["out"])
    return data, manifest


def _open(data):
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert zf.testzip() is None
    return zf


def test_full_package_contents_and_analysis_text(env):
    _write_cv(env["policy"].output_dir, "job-1", "cand-1")
    save_cover_letter("job-1", LETTER, "cand-1", base_dir=env["out"])
    save_job_analysis(_analysis(), env["state"])
    save_qualitative_assessment("job-1", {"dimensions": {"culture_signals": {
        "score": 4, "reasoning": "Friendly team", "evidence": ["x"]}}}, env["state"])
    data, manifest = _build(env)
    zf = _open(data)
    assert zf.namelist() == ["README.txt", "cv.md", "cover_letter.txt", "analysis.md", "job.json"]
    assert manifest["missing"] == {}
    assert zf.read("cv.md").decode().strip() == CV_BODY
    assert "<!--" not in zf.read("cv.md").decode()
    assert zf.read("cover_letter.txt").decode().startswith("Dear hiring manager")
    md = zf.read("analysis.md").decode()
    assert "# Analysis: Business Analyst at Acme \\*Ltd\\*" in md
    assert "- Decision: apply" in md and "- Match score: 82.5" in md
    assert "- Grade: " in md
    assert "## Matched required skills\n- SQL\n" in md
    assert "## Missing required skills\n- Python\n" in md
    assert "Visa (medium): needs \\*sponsorship\\*" in md
    assert "Contract: fixed term" in md
    assert "culture\\_signals: 4 - Friendly team" in md
    job = json.loads(zf.read("job.json"))
    assert job["title"] == "Business Analyst" and job["source_url"] == "https://example.com/job/1"
    assert job["salary_min_gbp"] == 50000 and job["description"] == "Do analysis."
    assert "source_ref" not in job and "/private/raw" not in zf.read("job.json").decode()
    readme = zf.read("README.txt").decode()
    assert "Business Analyst at Acme *Ltd*" in readme and "Missing:" not in readme


def test_cv_only_lists_missing_parts(env):
    _write_cv(env["policy"].output_dir, "job-1", "cand-1", reviewed=True)
    data, manifest = _build(env)
    zf = _open(data)
    assert zf.namelist() == ["README.txt", "cv.md", "job.json"]
    assert set(manifest["missing"]) == {"cover_letter.txt", "analysis.md"}
    readme = zf.read("README.txt").decode()
    assert "cover_letter.txt: not generated yet" in readme
    assert "analysis.md: job has not been evaluated yet" in readme


def test_nothing_generated_is_partial_not_error(env):
    data, manifest = _build(env)
    zf = _open(data)
    assert zf.namelist() == ["README.txt", "job.json"]
    assert list(manifest["missing"]) == ["cv.md", "cover_letter.txt", "analysis.md"]
    assert "Missing:" in zf.read("README.txt").decode()


def test_unknown_job_raises_file_not_found(env):
    with pytest.raises(FileNotFoundError):
        _build(env, "nope-1")


def test_profile_mismatch_cv_is_missing(env):
    _write_cv(env["policy"].output_dir, "job-1", "someone-else")
    data, manifest = _build(env)
    assert "cv.md" in manifest["missing"] and "cv.md" not in _open(data).namelist()
    assert "different profile" in manifest["missing"]["cv.md"]


def test_no_profile_cv_is_missing(env):
    _write_cv(env["policy"].output_dir, "job-1", "cand-1")
    _, manifest = _build(env, profile=None)
    assert "cv.md" in manifest["missing"]


def test_secrets_never_in_zip(env):
    (env["tmp"] / ".env").write_text("REED_API_KEY=SUPERSECRETKEY")
    raw = env["state"] / "raw_inputs"
    raw.mkdir(exist_ok=True)
    (raw / "job-1.json").write_text('{"text": "RAW_INPUT_MARKER"}')
    _write_cv(env["policy"].output_dir, "job-1", "cand-1")
    save_cover_letter("job-1", LETTER, "cand-1", base_dir=env["out"])
    save_job_analysis(_analysis(), env["state"])
    data, _ = _build(env)
    zf = _open(data)
    blob = b"".join(zf.read(n) for n in zf.namelist())
    for needle in (b"SUPERSECRETKEY", b"RAW_INPUT_MARKER", b"jane.secret@example.com", b"Jane Secret Person", b"REED_API_KEY"):
        assert needle not in blob
    assert not any(n.startswith((".env", "raw_inputs")) or "/" in n for n in zf.namelist())


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "x" * 500, "..", ".", "a b", "x%00", "id;rm", None])
def test_validate_rejects_bad_ids(bad):
    with pytest.raises(ValueError):
        validate_job_id(bad)
    with pytest.raises(ValueError):
        package_filename(bad)


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "x" * 500, "..", None])
def test_build_package_rejects_before_any_file_access(env, bad):
    with patch.object(job_hunt_export, "load_reviewed_job") as a, \
         patch.object(job_hunt_export, "load_latest_tailored_cv") as b, \
         patch.object(job_hunt_export, "load_cover_letter") as c, \
         patch.object(job_hunt_export, "load_job_analysis") as d:
        with pytest.raises(ValueError):
            _build(env, bad)
    for m in (a, b, c, d):
        m.assert_not_called()


def test_cover_letter_round_trip_from_tmp_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_cover_letter("job-1") is None
    p = save_cover_letter("job-1", LETTER, "cand-1")
    assert p == cover_letter_dir() / "job-1.txt" and (tmp_path / "output" / "cover_letters" / "job-1.txt").exists()
    assert load_cover_letter("job-1") == LETTER
    other = tmp_path / "elsewhere"
    save_cover_letter("job-2", "B", "c", base_dir=other)
    assert load_cover_letter("job-2", other) == "B" and load_cover_letter("job-2") is None


@pytest.mark.parametrize("bad", ["../x", "a/b", "", ".."])
def test_load_cover_letter_rejects_bad_id(bad):
    with pytest.raises(ValueError):
        load_cover_letter(bad)


# ── responder ────────────────────────────────────────────────────────────────

class _Handler:
    def __init__(self):
        self.wfile = io.BytesIO()
        self.sent = []
        self.status = None

    def send_response(self, s):
        self.status = s

    def send_header(self, k, v):
        self.sent.append((k, v))

    def end_headers(self):
        pass


def test_send_bytes_headers_and_body():
    h = _Handler()
    UIResponder(h).send_bytes(HTTPStatus.OK, b"abc", "application/zip", {"Content-Disposition": 'attachment; filename="a.zip"'})
    assert h.status == HTTPStatus.OK and h.wfile.getvalue() == b"abc"
    assert ("Content-Type", "application/zip") in h.sent and ("Content-Length", "3") in h.sent
    assert ("Content-Disposition", 'attachment; filename="a.zip"') in h.sent


@pytest.mark.parametrize("hdr", [{"X": "a\r\nSet-Cookie: b=1"}, {"X\n": "v"}])
def test_send_bytes_rejects_header_injection(hdr):
    h = _Handler()
    with pytest.raises(ValueError):
        UIResponder(h).send_bytes(HTTPStatus.OK, b"x", "application/zip", hdr)
    assert h.status is None and h.wfile.getvalue() == b""


# ── route handler ────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self):
        self.status = self.json_sent = self.data = self.ctype = self.headers = None

    def send_json(self, payload, status=HTTPStatus.OK):
        self.json_sent, self.status = payload, status

    def send_bytes(self, status, data, content_type, headers=None):
        self.status, self.data, self.ctype, self.headers = status, data, content_type, headers


@pytest.fixture
def config(env, monkeypatch):
    prof = env["tmp"] / "profile.json"
    prof.write_text(json.dumps({
        "candidate_id": "cand-1", "name": "T", "target_roles": ["BA"], "locations": ["London"],
        "remote_preference": "remote_friendly", "salary_floor_gbp": 45000, "right_to_work_uk": True,
        "skills": [], "years_experience": 3, "industries": []}))
    monkeypatch.chdir(env["tmp"])  # default policy + cover-letter dir are cwd-relative
    return UIServerConfig(profile_path=prof, state_root=env["state"], report_dir=env["tmp"] / "r")


def test_route_registered():
    import inspect
    from src import ui_routes
    assert "export\\.zip" in inspect.getsource(ui_routes)
    assert ui_routes.handle_job_export is ui_handlers.handle_job_export


@pytest.mark.parametrize("bad", ["../etc/passwd", "a/b", "", "x" * 500, "a b"])
def test_route_400_bad_id_no_file_access(config, bad):
    r = _Resp()
    with patch.object(job_hunt_export, "load_reviewed_job") as ld, \
         patch.object(ui_handlers, "load_candidate_profile") as lp:
        ui_handlers.handle_job_export(None, config, r, bad)
    assert r.status == HTTPStatus.BAD_REQUEST and r.data is None
    ld.assert_not_called()
    lp.assert_not_called()


def test_route_404_unknown_job(config):
    r = _Resp()
    ui_handlers.handle_job_export(None, config, r, "nope-1")
    assert r.status == HTTPStatus.NOT_FOUND


def _job_file(config, job_id="job-1"):
    return next(config.state_root.rglob(f"reviewed_jobs/{job_id}.json"))


@pytest.mark.parametrize("content,expected", [
    ("{not json", HTTPStatus.NOT_FOUND),                 # malformed JSON
    ("[1, 2]", HTTPStatus.NOT_FOUND),                    # valid JSON, not an object
    ('{"job_title": 5, "bogus_field": 1}', HTTPStatus.UNPROCESSABLE_ENTITY),  # valid JSON, bad fields
])
def test_route_corrupt_job_file_is_clean_json_error_never_500(config, content, expected):
    _job_file(config).write_text(content)
    r = _Resp()
    ui_handlers.handle_job_export(None, config, r, "job-1")
    assert r.status == expected and r.data is None
    assert r.json_sent["ok"] is False and isinstance(r.json_sent["error"], str)


@pytest.mark.parametrize("decision", ["apply", "review", "skip"])
def test_route_200_any_decision(config, env, decision):
    save_job_analysis(_analysis(decision=decision), env["state"])
    save_cover_letter("job-1", LETTER, "cand-1")  # default cwd-relative dir (tmp cwd)
    _write_cv(Path("output/tailored_cvs"), "job-1", "cand-1")
    r = _Resp()
    ui_handlers.handle_job_export(None, config, r, "job-1")
    assert r.status == HTTPStatus.OK and r.ctype == "application/zip"
    cd = r.headers["Content-Disposition"]
    assert cd == 'attachment; filename="application-package-job-1.zip"'
    import re
    assert re.fullmatch(r'attachment; filename="[A-Za-z0-9._-]+"', cd)
    zf = _open(r.data)
    assert {"cv.md", "cover_letter.txt", "analysis.md", "job.json"} <= set(zf.namelist())
    assert f"- Decision: {decision}" in zf.read("analysis.md").decode()


def test_route_200_partial_when_nothing_generated(config):
    r = _Resp()
    ui_handlers.handle_job_export(None, config, r, "job-1")
    assert r.status == HTTPStatus.OK
    assert _open(r.data).namelist() == ["README.txt", "job.json"]


# ── rendered page ────────────────────────────────────────────────────────────

def test_job_page_has_download_button():
    values = {}
    for f in dataclasses.fields(JobPageViewModel):
        t = str(f.type)
        values[f.name] = [] if t.startswith("list") else False if t.startswith("bool") else (
            "" if t.startswith("str") and "None" not in t else None)
    values.update(job_id="job-001", job_title="BA", company="Ex", has_analysis=True, match_score=85.0,
                  confidence="high", decision="apply", effective_decision="apply", flash_kind="info",
                  model_label="m", source_type="copied_text")
    html = render_job_page(JobPageViewModel(**values))
    assert 'href="/job/job-001/export.zip"' in html and "download" in html and "Download package" in html
