"""Tests for scripts/nimble_check.py (Nimble blind check).

No live HTTP: `requests` is always mocked. State is built in tmp_path; the real data/
directory is never touched.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts import nimble_check as nc


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
def _write_job(
    state: Path,
    job_id: str,
    jd_len: int,
    *,
    match_score: float | None = 74.0,
    decision: str = "review",
    user_decision: str | None = None,
    title: str | None = None,
    company: str = "Acme Ltd",
    jd: str | None = None,
) -> None:
    (state / "reviewed_jobs").mkdir(parents=True, exist_ok=True)
    (state / "analyses").mkdir(parents=True, exist_ok=True)
    (state / "reviewed_jobs" / f"{job_id}.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "job_title": title or f"Title {job_id}",
                "company": company,
                "description_raw": jd if jd is not None else "x" * jd_len,
            }
        ),
        encoding="utf-8",
    )
    if match_score is not None:
        (state / "analyses" / f"{job_id}.json").write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "match_score": match_score,
                    "decision": decision,
                    "user_decision": user_decision,
                }
            ),
            encoding="utf-8",
        )


def _ids(jobs: list[dict]) -> list[str]:
    return [j["job_id"] for j in jobs]


def _job(job_id: str, n: int) -> dict:
    return {"job_id": job_id, "title": "t", "company": "c", "jd": "x" * n}


def _state_listing(root: Path) -> list[tuple[str, int]]:
    return sorted((str(p.relative_to(root)), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# Export: selection
# ---------------------------------------------------------------------------
def test_selection_length_bands():
    jobs = [
        _job("a-1000", 1000),   # lower edge of the main band
        _job("a-14000", 14000),  # upper edge of the main band
        _job("a-999", 999),      # gap: neither main nor stub
        _job("a-521", 521),      # gap: just over the stub limit
        _job("a-520", 520),      # stub
        _job("a-14001", 14001),  # over the cap: excluded
    ]
    assert _ids(nc.select_jobs(jobs)) == ["a-1000", "a-14000", "a-520"]


def test_selection_over_14000_never_exported():
    jobs = [_job("big-1", 14001), _job("big-2", 50000), _job("ok-1", 2000)]
    assert _ids(nc.select_jobs(jobs)) == ["ok-1"]


def test_selection_excludes_demo_test_edge_fixtures():
    jobs = [
        _job("demo-job-001", 2000),
        _job("test-job-1", 2000),
        _job("edge-onsite-role", 2000),
        _job("demo-stub", 100),
        _job("reed-1", 2000),
        _job("reed-stub", 100),
    ]
    assert _ids(nc.select_jobs(jobs)) == ["reed-1", "reed-stub"]


def test_selection_stubs_are_first_five_by_job_id_and_deterministic():
    names = ["s-07", "s-03", "s-09", "s-01", "s-05", "s-02", "s-08", "s-04", "s-06"]
    jobs = [_job(n, 300) for n in names]
    first = _ids(nc.select_jobs(jobs))
    assert first == ["s-01", "s-02", "s-03", "s-04", "s-05"]
    # Same result for any input order and on a repeat call.
    assert _ids(nc.select_jobs(list(reversed(jobs)))) == first
    assert _ids(nc.select_jobs(jobs)) == first


def test_selection_main_jobs_come_before_stubs_and_blank_jd_is_not_a_stub():
    jobs = [_job("z-main", 1500), _job("a-stub", 100), _job("m-blank", 0)]
    jobs.append({"job_id": "n-spaces", "title": "", "company": "", "jd": "   "})
    assert _ids(nc.select_jobs(jobs)) == ["z-main", "a-stub"]


def test_selection_counts_match_spec_shape():
    jobs = [_job(f"m-{i:02d}", 1000 + i) for i in range(30)]
    jobs += [_job(f"s-{i:02d}", 400) for i in range(47)]
    selected = nc.select_jobs(jobs)
    assert len(selected) == 35
    assert sum(1 for j in selected if len(j["jd"]) <= nc.STUB_MAX_CHARS) == 5


# ---------------------------------------------------------------------------
# Export: grade / decision / link / rows
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "score,grade",
    [(80, "A"), (79.9, "B"), (72, "B"), (71.9, "C"), (65, "C"), (50, "D"), (49.9, "F")],
)
def test_base_grade_reuses_derive_base_grade(score, grade):
    assert nc.grade_and_decision({"match_score": score, "decision": "review"})[0] == grade


def test_decision_is_effective_decision_user_overrides_engine():
    assert nc.grade_and_decision({"match_score": 90, "decision": "apply", "user_decision": None})[1] == "apply"
    assert nc.grade_and_decision({"match_score": 90, "decision": "apply", "user_decision": "skip"})[1] == "skip"


def test_missing_or_unusable_analysis_gives_blank_grade_and_decision():
    assert nc.grade_and_decision(None) == ("", "")
    assert nc.grade_and_decision({"match_score": None, "decision": "review"}) == ("", "review")


def test_job_link_uses_ui_job_path_and_quotes_id():
    assert nc.job_link("adzuna-123") == "http://127.0.0.1:9000/job/adzuna-123"
    assert nc.job_link("a b/c", "http://127.0.0.1:9100/") == "http://127.0.0.1:9100/job/a%20b%2Fc"


def test_build_export_rows_columns_and_values(tmp_path):
    _write_job(tmp_path, "reed-1", 1500, match_score=81, decision="apply", user_decision="review")
    rows = nc.build_export_rows(nc.load_reviewed_jobs(tmp_path), tmp_path)
    assert rows == [
        ["reed-1", "Title reed-1", "Acme Ltd", 1500, "A", "review", "http://127.0.0.1:9000/job/reed-1", "", ""]
    ]


def test_load_reviewed_jobs_uses_file_stem_and_survives_bad_file(tmp_path, capsys):
    _write_job(tmp_path, "reed-1", 1500)
    (tmp_path / "reviewed_jobs" / "broken.json").write_text("{not json", encoding="utf-8")
    jobs = nc.load_reviewed_jobs(tmp_path)
    assert _ids(jobs) == ["reed-1"]
    assert "broken.json" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Export: file writing and CLI
# ---------------------------------------------------------------------------
def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig").splitlines()


def test_export_writes_comment_header_columns_and_blank_label_cells(tmp_path):
    state, out = tmp_path / "state", tmp_path / "out"
    _write_job(state, "reed-1", 1500)
    _write_job(state, "reed-2", 300)
    assert nc.main(["export", "--state-root", str(state), "--out-dir", str(out)]) == 0
    lines = _lines(out / "labels.csv")
    assert lines[0].startswith("#")
    assert nc.RF_QUESTION.lower()[:20] in lines[0].lower()
    assert "clash with what the role requires" in lines[0]
    assert lines[1].split(",") == nc.CSV_COLUMNS
    rows = list(csv.reader(lines[2:]))
    assert [r[0] for r in rows] == ["reed-1", "reed-2"]
    assert all(r[-2:] == ["", ""] for r in rows)


def test_export_refuses_overwrite_without_force(tmp_path, capsys):
    state, out = tmp_path / "state", tmp_path / "out"
    _write_job(state, "reed-1", 1500)
    args = ["export", "--state-root", str(state), "--out-dir", str(out)]
    assert nc.main(args) == 0
    labels = out / "labels.csv"
    labels.write_text(labels.read_text(encoding="utf-8-sig") + "# my marker\n", encoding="utf-8")
    before = labels.read_bytes()
    assert nc.main(args) == 2
    assert "--force" in capsys.readouterr().err
    assert labels.read_bytes() == before  # untouched
    assert nc.main(args + ["--force"]) == 0
    assert labels.read_bytes() != before  # overwritten only with --force


def test_export_does_not_modify_state_and_creates_nothing_there(tmp_path):
    state, out = tmp_path / "state", tmp_path / "out"
    _write_job(state, "reed-1", 1500)
    before = _state_listing(state)
    assert nc.main(["export", "--state-root", str(state), "--out-dir", str(out)]) == 0
    assert _state_listing(state) == before


def test_refuse_data_path_blocks_data_dir_and_children_only(tmp_path):
    data = tmp_path / "data"
    with pytest.raises(ValueError):
        nc.refuse_data_path(data / "x" / "labels.csv", data_dir=data)
    with pytest.raises(ValueError):
        nc.refuse_data_path(data, data_dir=data)
    nc.refuse_data_path(tmp_path / "archive" / "labels.csv", data_dir=data)
    nc.refuse_data_path(tmp_path / "database" / "labels.csv", data_dir=data)  # prefix look-alike is fine


def test_export_refuses_out_dir_under_data(tmp_path, monkeypatch):
    monkeypatch.setattr(nc, "DATA_DIR", tmp_path / "data")
    state = tmp_path / "state"
    _write_job(state, "reed-1", 1500)
    target = tmp_path / "data" / "oops"
    assert nc.main(["export", "--state-root", str(state), "--out-dir", str(target)]) == 2
    assert not target.exists()


# ---------------------------------------------------------------------------
# No live HTTP in pytest: any un-mocked requests call fails the test.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_live_http(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("live HTTP attempted in pytest")

    monkeypatch.setattr(nc.requests, "post", blocked)
    monkeypatch.setattr(nc.requests, "get", blocked)


class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _answers(*, rf=0.2, cu=0.7, scores=None, tier="unknown_caution", dims=nc.DIMENSIONS, tokens=1234):
    scores = scores or {}
    answers = {
        "rf": {"type": "noul", "noul": rf},
        "cu": {"type": "noul", "noul": cu},
        "posting_tier": {"type": "choice", "choice": tier, "probabilities": {tier: 0.9}, "confidence": 0.9},
    }
    for d in dims:
        answers[d] = {"type": "score", "score": scores.get(d, 2.0), "legend": {"0": "a"}, "probabilities": {"0": 1.0}, "confidence": 0.5}
    return {"model": nc.MODEL, "answers": answers, "usage": {"input_tokens": tokens, "output_tokens": 40}}


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------
def test_build_request_shape_and_frozen_questions():
    req = nc.build_request("THE JD", ["Business Analyst", "IT Project Manager"])
    assert req["model"] == "nimble:9b-q4_K_M"
    assert req["state"] == "THE JD"
    assert req["keep_alive"] == "30m"
    q = req["questions"]
    assert q["rf"] == {"type": "noul", "instructions": nc.RF_QUESTION}
    assert q["cu"] == {"type": "noul", "instructions": nc.CU_QUESTION}
    assert nc.RF_QUESTION == "Does this job ad show material red flags?"
    assert nc.CU_QUESTION == "Does the ad's culture or working style clash with what the role requires?"
    for name in nc.DIMENSIONS:
        assert q[name]["type"] == "score"
        assert len(q[name]["criteria"]) == 5
    assert q["posting_tier"]["type"] == "choice"
    assert set(q["posting_tier"]["criteria"]) == {"high_confidence", "unknown_caution", "suspicious"}
    assert set(q) == {"rf", "cu", "posting_tier", *nc.DIMENSIONS}


def test_build_request_target_roles_in_alignment_and_seniority_instructions():
    q = nc.build_request("jd", ["Business Analyst", "  IT Project Manager  ", ""])["questions"]
    assert "Business Analyst, IT Project Manager" in q["role_archetype_alignment"]["instructions"]
    assert "Business Analyst, IT Project Manager" in q["seniority_fit"]["instructions"]
    assert "target roles" not in q["red_flags"]["instructions"].lower()


@pytest.mark.parametrize("roles", [[], None, ["", "   "], ()])
def test_build_request_empty_target_roles_does_not_break(roles):
    req = nc.build_request("jd text", roles)
    assert "role_archetype_alignment" not in req["questions"]
    assert {"rf", "cu", "seniority_fit", "culture_signals", "red_flags", "posting_tier"} <= set(req["questions"])
    assert "Candidate target roles" not in req["questions"]["seniority_fit"]["instructions"]
    assert nc.requested_dimensions(roles) == ("seniority_fit", "culture_signals", "red_flags")
    json.dumps(req)  # serialisable


def test_score_levels_use_rubric_for_1_3_5_and_between_for_2_4():
    for name, (low, mid, high) in nc.DIMENSION_RUBRIC.items():
        levels = nc.score_levels(name)
        assert levels[0] == low and levels[2] == mid and levels[4] == high
        assert levels[1].startswith("Between") and low in levels[1] and mid in levels[1]
        assert levels[3].startswith("Between") and mid in levels[3] and high in levels[3]


def test_rubric_wording_has_not_drifted_from_qualitative_prompt():
    from src.job_hunt_models import CandidateProfile
    from src.job_hunt_qualitative import DIMENSIONS, build_qualitative_prompt

    assert set(nc.DIMENSION_RUBRIC) == set(DIMENSIONS)
    prompt = build_qualitative_prompt("jd", CandidateProfile(candidate_id="c1", target_roles=["Business Analyst"]))
    for name, (low, mid, high) in nc.DIMENSION_RUBRIC.items():
        line = next(l for l in prompt.splitlines() if l.startswith(f"- {name}:"))
        assert f"1 = {low}" in line and f"3 = {mid}" in line and f"5 = {high}" in line


def test_tier_criteria_match_app_tiers():
    from src.job_hunt_qualitative import POSTING_QUALITY_TIERS

    assert set(nc.TIER_CRITERIA) == POSTING_QUALITY_TIERS


def test_request_for_largest_allowed_ad_fits_body_limit():
    req = nc.build_request("x" * nc.MAX_JD_CHARS, ["Business Analyst"])
    assert len(json.dumps(req).encode()) < nc.MAX_BODY_BYTES


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------
def test_parse_noul_score_zero_based_to_1_5_and_choice():
    resp = _answers(rf=0.4, cu=0.5, scores={"seniority_fit": 0.0, "culture_signals": 2.5, "red_flags": 4.0, "role_archetype_alignment": 3.25}, tier="suspicious", tokens=900)
    out = nc.parse_response(resp)
    assert out["rf"] == 0.4 and out["cu"] == 0.5
    assert out["scores_1to5"] == {"seniority_fit": 1.0, "culture_signals": 3.5, "red_flags": 5.0, "role_archetype_alignment": 4.25}
    assert out["tier"] == "suspicious"
    assert out["input_tokens"] == 900 and out["output_tokens"] == 40
    assert "rf" in out["answer_keys"] and "posting_tier" in out["answer_keys"]


def test_parse_only_requested_dimensions():
    dims = nc.requested_dimensions([])
    out = nc.parse_response(_answers(dims=dims), dimensions=dims)
    assert set(out["scores_1to5"]) == set(dims)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.pop("answers"),
        lambda r: r["answers"].pop("rf"),
        lambda r: r["answers"].__setitem__("cu", {"type": "score", "score": 1.0}),
        lambda r: r["answers"]["rf"].__setitem__("noul", 1.5),
        lambda r: r["answers"]["rf"].__setitem__("noul", True),
        lambda r: r["answers"]["red_flags"].__setitem__("score", "high"),
        lambda r: r["answers"]["posting_tier"].pop("choice"),
        lambda r: r.pop("usage"),
    ],
)
def test_parse_shape_differences_raise_shape_error(mutate):
    resp = _answers()
    mutate(resp)
    with pytest.raises(nc.ShapeError):
        nc.parse_response(resp)


# ---------------------------------------------------------------------------
# HTTP layer (requests mocked)
# ---------------------------------------------------------------------------
def test_post_systemone_success_returns_json_and_latency(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"], seen["kwargs"] = url, kwargs
        return FakeResp(200, _answers())

    monkeypatch.setattr(nc.requests, "post", fake_post)
    data, latency = nc.post_systemone(nc.build_request("jd", ["BA"]))
    assert seen["url"] == "http://127.0.0.1:11434/v1/systemone"
    assert json.loads(seen["kwargs"]["data"])["state"] == "jd"
    assert data["usage"]["input_tokens"] == 1234
    assert latency >= 0


def test_connection_refused_stops_with_is_ollama_running(monkeypatch):
    def fake_post(url, **kwargs):
        raise nc.requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(nc.requests, "post", fake_post)
    with pytest.raises(nc.OllamaUnavailable, match="Is Ollama running"):
        nc.post_systemone(nc.build_request("jd"))


def test_connect_timeout_is_treated_as_unreachable(monkeypatch):
    def fake_post(url, **kwargs):
        raise nc.requests.exceptions.ConnectTimeout("slow")

    monkeypatch.setattr(nc.requests, "post", fake_post)
    with pytest.raises(nc.OllamaUnavailable):
        nc.post_systemone(nc.build_request("jd"))


def test_model_not_found_404_stops_with_clear_message(monkeypatch):
    err = {"error": 'model "nimble:9b-q4_K_M" not found, try pulling it first'}
    monkeypatch.setattr(nc.requests, "post", lambda url, **kw: FakeResp(404, err))
    with pytest.raises(nc.ModelNotFound, match="not found"):
        nc.post_systemone(nc.build_request("jd"))


def test_other_http_error_is_a_per_job_error_not_a_stop(monkeypatch):
    monkeypatch.setattr(nc.requests, "post", lambda url, **kw: FakeResp(500, {"error": "boom"}))
    with pytest.raises(nc.NimbleHTTPError, match="HTTP 500: boom"):
        nc.post_systemone(nc.build_request("jd"))
    # A 404 that is not about the model is also a per-job error.
    monkeypatch.setattr(nc.requests, "post", lambda url, **kw: FakeResp(404, None, text="404 page not found"))
    with pytest.raises(nc.NimbleHTTPError, match="HTTP 404"):
        nc.post_systemone(nc.build_request("jd"))


def test_read_timeout_and_bad_json_are_per_job_errors(monkeypatch):
    def timeout_post(url, **kwargs):
        raise nc.requests.exceptions.ReadTimeout("slow")

    monkeypatch.setattr(nc.requests, "post", timeout_post)
    with pytest.raises(nc.NimbleHTTPError, match="timed out"):
        nc.post_systemone(nc.build_request("jd"), timeout=5)
    monkeypatch.setattr(nc.requests, "post", lambda url, **kw: FakeResp(200, None))
    with pytest.raises(nc.NimbleHTTPError, match="not JSON"):
        nc.post_systemone(nc.build_request("jd"))


def test_oversize_body_is_refused_before_any_http_call():
    req = nc.build_request("x" * (nc.MAX_BODY_BYTES + 1))
    with pytest.raises(nc.NimbleHTTPError, match="byte limit"):
        nc.post_systemone(req)  # the autouse fixture would fail the test on any HTTP call


def test_fetch_model_digest_found_missing_and_down(monkeypatch):
    tags = {"models": [{"name": "other:1", "digest": "zzz"}, {"name": nc.MODEL, "model": nc.MODEL, "digest": "abc123"}]}
    monkeypatch.setattr(nc.requests, "get", lambda url, **kw: FakeResp(200, tags))
    assert nc.fetch_model_digest() == "abc123"
    monkeypatch.setattr(nc.requests, "get", lambda url, **kw: FakeResp(200, {"models": []}))
    with pytest.raises(nc.ModelNotFound):
        nc.fetch_model_digest()

    def down(url, **kw):
        raise nc.requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(nc.requests, "get", down)
    with pytest.raises(nc.OllamaUnavailable, match="Is Ollama running"):
        nc.fetch_model_digest()


# ---------------------------------------------------------------------------
# Label CSV parsing and joining
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("y", ("y", "ok")), ("Y", ("y", "ok")), (" yes ", ("y", "ok")), ("YES", ("y", "ok")),
        ("n", ("n", "ok")), ("No", ("n", "ok")),
        ("", (None, "blank")), ("   ", (None, "blank")), (None, (None, "blank")),
        ("maybe", (None, "invalid")), ("?", (None, "invalid")), ("1", (None, "invalid")), ("yn", (None, "invalid")),
    ],
)
def test_parse_label(raw, expected):
    assert nc.parse_label(raw) == expected


def _write_labels(path: Path, body_rows: list[list[str]], *, comment=True, bom=True, header=None) -> Path:
    lines = []
    if comment:
        lines.append("# Blind labels, with a comment,,,,,,,,")
    lines.append(",".join(header or nc.CSV_COLUMNS))
    lines += [",".join(r) for r in body_rows]
    path.write_text(("﻿" if bom else "") + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def _row(job_id, rf="", cu="", grade="B", jd_chars="2000"):
    return [job_id, "Title", "Co", jd_chars, grade, "review", f"http://x/job/{job_id}", rf, cu]


def test_read_labels_skips_comment_and_bom_and_reports_blank_and_invalid(tmp_path):
    path = _write_labels(tmp_path / "labels.csv", [_row("a", "y", "n"), _row("b", "", "maybe"), _row("c", " YES ", "")])
    rows, notes = nc.read_labels(path)
    assert [r["job_id"] for r in rows] == ["a", "b", "c"]
    assert notes == []
    a, b, c = rows
    assert (a["RF_value"], a["RF_status"], a["CU_value"], a["CU_status"]) == ("y", "ok", "n", "ok")
    assert (b["RF_value"], b["RF_status"]) == (None, "blank")
    assert (b["CU_value"], b["CU_status"]) == (None, "invalid") and b["CU"] == "maybe"  # raw kept for the report
    assert (c["RF_value"], c["RF_status"]) == ("y", "ok") and c["CU_status"] == "blank"


def test_read_labels_exported_file_roundtrip(tmp_path):
    state, out = tmp_path / "state", tmp_path / "out"
    _write_job(state, "reed-1", 1500, title='A, "quoted" title')
    nc.main(["export", "--state-root", str(state), "--out-dir", str(out)])
    rows, notes = nc.read_labels(out / "labels.csv")
    assert [r["job_id"] for r in rows] == ["reed-1"]
    assert rows[0]["title"] == 'A, "quoted" title'
    assert rows[0]["RF_status"] == rows[0]["CU_status"] == "blank"


def test_read_labels_duplicate_job_id_skipped_and_noted(tmp_path):
    path = _write_labels(tmp_path / "labels.csv", [_row("a", "y", "y"), _row("a", "n", "n")])
    rows, notes = nc.read_labels(path)
    assert len(rows) == 1 and rows[0]["RF_value"] == "y"
    assert any("duplicate job_id a" in n for n in notes)


def test_read_labels_short_rows_are_padded_and_missing_columns_rejected(tmp_path):
    path = _write_labels(tmp_path / "labels.csv", [["a", "T", "C", "1500", "A", "apply", "http://x"]])
    rows, _ = nc.read_labels(path)
    assert rows[0]["RF_status"] == "blank" and rows[0]["CU_status"] == "blank"
    bad = _write_labels(tmp_path / "bad.csv", [["a", "T"]], header=["job_id", "title"])
    with pytest.raises(nc.LabelsFormatError, match="missing columns"):
        nc.read_labels(bad)
    empty = tmp_path / "empty.csv"
    empty.write_text("# only a comment\n", encoding="utf-8")
    with pytest.raises(nc.LabelsFormatError):
        nc.read_labels(empty)


def test_join_labels_to_results_by_job_id(tmp_path):
    rows, _ = nc.read_labels(_write_labels(tmp_path / "labels.csv", [_row("a", "y", "n"), _row("b", "n", "n")]))
    results = {"b": {"job_id": "b", "rf": 0.9}, "zzz": {"job_id": "zzz"}}
    joined = nc.join_rows(rows, results)
    assert [j["job_id"] for j in joined] == ["a", "b"]  # label order, extra result ignored
    assert joined[0]["result"] is None
    assert joined[1]["result"] == {"job_id": "b", "rf": 0.9}
    assert joined[1]["RF_value"] == "n"
