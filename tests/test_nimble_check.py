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


def test_frozen_rubric_wording_is_unchanged():
    # The blind check keeps the pre-2026-10-19 1/3/5 wording on purpose so
    # results stay comparable; the app prompt moved to 5 described levels
    # (Slice 3). This pins the frozen copy against accidental edits.
    from src.job_hunt_qualitative import DIMENSIONS

    assert set(nc.DIMENSION_RUBRIC) == set(DIMENSIONS)
    assert nc.DIMENSION_RUBRIC == {
        "seniority_fit": ("clearly too junior/senior", "unclear or partial match", "strong seniority match"),
        "culture_signals": ("evidence of poor fit or unhealthy signals", "little/no evidence", "strong positive signals"),
        "red_flags": ("material red flags", "limited/unclear warning signs", "no meaningful red flags in the JD"),
        "role_archetype_alignment": ("poor alignment with target roles", "mixed/unclear", "strong archetype match"),
    }


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


@pytest.mark.parametrize("score,expected", [(0.0, 1.0), (4.0, 5.0), (3.999, 4.999)])
def test_parse_accepts_the_edges_of_the_valid_ranges(score, expected):
    resp = _answers(scores={"red_flags": score}, rf=0.0, cu=1.0, tokens=0)
    out = nc.parse_response(resp)
    assert out["scores_1to5"]["red_flags"] == pytest.approx(expected)
    assert out["rf"] == 0.0 and out["cu"] == 1.0 and out["input_tokens"] == 0
    for tier in ("high_confidence", "unknown_caution", "suspicious"):
        assert nc.parse_response(_answers(tier=tier))["tier"] == tier


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
        # malformed values (review finding 4)
        lambda r: r["answers"]["rf"].__setitem__("noul", -0.01),
        lambda r: r["answers"]["cu"].__setitem__("noul", float("nan")),
        lambda r: r["answers"]["cu"].__setitem__("noul", float("inf")),
        lambda r: r["answers"]["red_flags"].__setitem__("score", 4.01),   # zero-based 5 levels: max 4
        lambda r: r["answers"]["red_flags"].__setitem__("score", 5.0),
        lambda r: r["answers"]["red_flags"].__setitem__("score", -0.01),
        lambda r: r["answers"]["red_flags"].__setitem__("score", float("nan")),
        lambda r: r["answers"]["seniority_fit"].__setitem__("score", float("inf")),
        lambda r: r["answers"]["seniority_fit"].__setitem__("score", float("-inf")),
        lambda r: r["answers"]["posting_tier"].__setitem__("choice", "very_high_confidence"),
        lambda r: r["answers"]["posting_tier"].__setitem__("choice", ""),
        lambda r: r["usage"].__setitem__("input_tokens", -1),
        lambda r: r["usage"].__setitem__("input_tokens", 12.5),
        lambda r: r["usage"].__setitem__("input_tokens", True),
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


# ---------------------------------------------------------------------------
# Counting, "not tested" rule, harmful cases, report
# ---------------------------------------------------------------------------
def _result(rf=0.1, cu=0.1, *, tokens=1000, questions=7, status="ok", digest="dig-aaaaaaaaaaaa", error=None):
    """`tokens` is usage.input_tokens, a SUM over the `questions` per-question prompts."""
    if status != "ok":
        return {"job_id": "x", "status": status, "error": error or "boom", "model_digest": digest}
    return {
        "job_id": "x", "status": "ok", "error": None, "rf": rf, "cu": cu,
        "scores_1to5": {"seniority_fit": 3.0, "culture_signals": 2.5, "red_flags": 4.25, "role_archetype_alignment": 1.0},
        "tier": "unknown_caution", "input_tokens": tokens, "questions_sent": questions,
        "per_question_tokens": nc.per_question_tokens(tokens, questions), "output_tokens": 30, "latency_s": 2.5,
        "token_flag": nc.per_question_tokens(tokens, questions) > nc.TOKEN_WARN, "model_digest": digest,
    }


def _joined(job_id, rf="", cu="", *, rf_p=0.1, cu_p=0.1, grade="B", jd_chars=2000, result="default", title=None):
    row = {
        "job_id": job_id, "title": title or f"Title {job_id}", "company": "Co", "jd_chars": str(jd_chars),
        "base_grade": grade, "decision": "review", "link": f"http://x/job/{job_id}", "RF": rf, "CU": cu,
    }
    for q, raw in (("RF", rf), ("CU", cu)):
        row[f"{q}_value"], row[f"{q}_status"] = nc.parse_label(raw)
    row["result"] = _result(rf_p, cu_p) if result == "default" else result
    return row


def test_count_at_the_0_5_boundary():
    assert nc.nimble_yes(0.5) is True
    assert nc.nimble_yes(0.4999) is False
    assert nc.nimble_yes(0.5001) is True
    rows = [
        _joined("a", "y", "y", rf_p=0.5, cu_p=0.5),       # boundary counts as Nimble yes
        _joined("b", "n", "n", rf_p=0.4999, cu_p=0.4999),  # just below counts as no
    ]
    rf = nc.count_question(rows, "RF")
    assert (rf["both"], rf["neither"], rf["owner_only"], rf["nimble_only"]) == (1, 1, 0, 0)
    assert nc.THRESHOLD == 0.5


def test_count_categories_and_blank_invalid_missing_result():
    rows = [
        _joined("both", "y", "n", rf_p=0.9),
        _joined("neither", "n", "n", rf_p=0.1),
        _joined("missed", "y", "n", rf_p=0.2),       # owner yes, Nimble no
        _joined("extra", "n", "n", rf_p=0.8),        # owner no, Nimble yes
        _joined("blank", "", ""),
        _joined("bad", "maybe", "n"),
        _joined("noresult", "y", "n", result=_result(status="error")),
        _joined("notrun", "n", "n", result=None),
    ]
    c = nc.count_question(rows, "RF")
    assert c["both"] == 1 and c["neither"] == 1 and c["owner_only"] == 1 and c["nimble_only"] == 1
    # owner_yes counts ALL valid owner labels (both, missed, noresult); the rest use successful results only
    assert c["owner_yes"] == 3 and c["nimble_yes"] == 2 and c["compared"] == 4
    assert c["unlabelled"] == 1 and c["invalid"] == 1 and c["no_result"] == 2 and c["no_result_owner_yes"] == 1


def test_owner_yes_counts_all_labels_even_when_a_nimble_request_failed():
    failed = _result(status="error")
    # 3 owner yes, one of them has a failed request: still tested, owner_yes stays 3
    rows = [
        _joined("a", "y", "n", rf_p=0.9), _joined("b", "y", "n", rf_p=0.1),
        _joined("c", "y", "n", result=failed), _joined("d", "n", "n", rf_p=0.1),
    ]
    c = nc.count_question(rows, "RF")
    assert c["owner_yes"] == 3 and c["tested"] is True
    assert c["compared"] == 3 and c["no_result"] == 1 and c["no_result_owner_yes"] == 1
    assert (c["both"], c["owner_only"], c["neither"], c["nimble_only"]) == (1, 1, 1, 0)
    # 3 owner yes with Nimble fine, plus 1 extra failed job: still 3 and tested
    rows = [_joined(x, "y", "n", rf_p=0.9) for x in "abc"] + [_joined("d", "n", "n", result=failed)]
    c = nc.count_question(rows, "RF")
    assert c["owner_yes"] == 3 and c["tested"] is True and c["no_result"] == 1 and c["no_result_owner_yes"] == 0
    # a request that was never run counts the same way
    rows = [_joined(x, "y", "n", result=None) for x in "abc"]
    c = nc.count_question(rows, "RF")
    assert c["owner_yes"] == 3 and c["tested"] is True and c["compared"] == 0 and c["nimble_yes"] == 0
    # and the report says tested, with the failed jobs reported separately
    report = nc.build_report([_joined("a", "y", "n", result=failed), _joined("b", "y", "n", rf_p=0.9),
                              _joined("c", "y", "n", rf_p=0.9)], date_str="2026-10-11")
    rf_section = report.split("## RF")[1].split("## CU")[0]
    assert "Not tested" not in rf_section and "Agreement on yes/no" in rf_section
    assert "| Owner yes (all valid labels) | 3 |" in rf_section
    assert "| Labelled but no Nimble result (failed or not run) | 1 |" in rf_section
    assert "|   of which owner yes | 1 |" in rf_section


def test_not_tested_rule_fewer_than_3_owner_yes():
    two = [_joined("a", "y", "n"), _joined("b", "y", "n"), _joined("c", "n", "n")]
    three = two + [_joined("d", "y", "n")]
    assert nc.count_question(two, "RF")["tested"] is False
    assert nc.count_question(three, "RF")["tested"] is True
    # CU has zero owner yes in both sets
    assert nc.count_question(three, "CU")["tested"] is False

    report_two = nc.build_report(two, date_str="2026-10-11")
    assert report_two.count("**Not tested**") == 2  # RF (2 yes) and CU (0 yes)
    report_three = nc.build_report(three, date_str="2026-10-11")
    assert report_three.count("**Not tested**") == 1  # only CU
    assert "Agreement on yes/no" in report_three


def test_harmful_cases_only_grade_a_or_b_nimble_yes_owner_no():
    rows = [
        _joined("hit-a", "n", "n", rf_p=0.9, grade="A"),
        _joined("hit-b", "n", "n", rf_p=0.5, grade="B", title="Hit B Title"),
        _joined("grade-c", "n", "n", rf_p=0.9, grade="C"),
        _joined("owner-yes", "y", "n", rf_p=0.9, grade="A"),
        _joined("nimble-no", "n", "n", rf_p=0.2, grade="A"),
        _joined("blank", "", "", rf_p=0.9, grade="A"),
        _joined("invalid", "x", "n", rf_p=0.9, grade="A"),
        _joined("no-result", "n", "n", grade="A", result=None),
    ]
    assert [r["job_id"] for r in nc.harmful_cases(rows, "RF")] == ["hit-a", "hit-b"]
    assert nc.harmful_cases(rows, "CU") == []
    report = nc.build_report(rows, date_str="2026-10-11")
    section = report.split("## Harmful cases")[1].split("## Stub jobs")[0]
    assert "Hit B Title" in section and "hit-a" in section
    assert "grade-c" not in section and "owner-yes" not in section
    assert "**CU:** none" in section


def test_report_header_and_stub_section_is_separate():
    rows = [
        _joined("full-1", "y", "n", rf_p=0.9),
        _joined("stub-1", "y", "y", rf_p=0.9, cu_p=0.9, jd_chars=300, title="Stub One"),
    ]
    report = nc.build_report(rows, date_str="2026-10-11")
    assert "Indicative - small sample" in report
    assert "2026-10-11" in report and "dig-aaaaaaaaaaaa" in report and "0.50" in report
    assert "nimble:9b-q4_K_M" in report
    stub_section = report.split("## Stub jobs")[1].split("## Per-job table")[0]
    per_job = report.split("## Per-job table (full ads)")[1].split("## Label problems")[0]
    assert "stub-1" in stub_section and "stub-1" not in per_job
    assert "full-1" in per_job and "full-1" not in stub_section
    # headline counts use full ads only: one owner yes (full-1), not two
    rf_section = report.split("## RF")[1].split("## CU")[0]
    assert "| Owner yes (all valid labels) | 1 |" in rf_section


def test_report_per_job_table_has_recorded_fields_and_flags_big_inputs():
    rows = [
        _joined("big", "n", "n", result=_result(tokens=49_007)),   # 7 questions -> 7,001 per question
        _joined("ok", "n", "n", result=_result(tokens=49_000)),    # 7,000 per question: not flagged
        _joined("smoke", "n", "n", result=_result(tokens=7_626)),  # old false alarm: 1,089 per question
    ]
    report = nc.build_report(rows, date_str="2026-10-11")
    for dim in nc.DIMENSIONS:
        assert f"{dim} (1-5, unvalidated)" in report  # the 4 score columns are marked like the tier
    assert "unvalidated, display only" in report  # and the report says so in words
    assert "unknown_caution" in report and "unvalidated" in report
    big_line = next(l for l in report.splitlines() if l.startswith("| big "))
    ok_line = next(l for l in report.splitlines() if l.startswith("| ok "))
    smoke_line = next(l for l in report.splitlines() if l.startswith("| smoke "))
    assert "per-question tokens > 7000" in big_line and "49007" in big_line and "2.50" in big_line and "dig-aaaaaaaa" in big_line
    assert "| 7 | 49007 | 7001 |" in big_line  # questions sent, sum, per question
    assert "per-question tokens > 7000" not in ok_line
    assert "| 7 | 7626 | 1089 |" in smoke_line and "per-question tokens > 7000" not in smoke_line
    assert "input_tokens (sum over N questions)" in report and "per-question tokens" in report
    assert "sum over the per-question prompts" in report  # explanatory header line
    assert "3.00" in big_line and "2.50" in big_line and "4.25" in big_line  # 1-5 scores, 2 decimals


def test_report_lists_blank_invalid_labels_and_errors_never_guesses():
    rows = [
        _joined("blank-1", "", ""),
        _joined("bad-1", "maybe", "n"),
        _joined("err-1", "n", "n", result=_result(status="error", error="HTTP 500: boom")),
        _joined("skip-1", "n", "n", result=_result(status="skipped", error="JD over limit")),
        _joined("none-1", "n", "n", result=None),
    ]
    report = nc.build_report(rows, date_str="2026-10-11", notes=["duplicate job_id z: later row skipped"])
    labels = report.split("## Label problems")[1].split("## Errors and skipped jobs")[0]
    assert "RF blank on 1 job(s): blank-1" in labels
    assert "invalid on `bad-1`: 'maybe'" in labels
    errors = report.split("## Errors and skipped jobs")[1]
    assert "err-1`: error: HTTP 500: boom" in errors
    assert "skip-1`: skipped: JD over limit" in errors
    assert "none-1`: no result recorded" in errors
    assert "duplicate job_id z" in report
    c = nc.count_question(rows, "RF")
    assert c["compared"] == 0  # blank, invalid, error, skipped, missing are never compared


def test_report_warns_on_mixed_digests_and_escapes_pipes():
    rows = [
        _joined("a", "n", "n", result=_result(digest="d1")),
        _joined("b", "n", "n", result=_result(digest="d2"), title="Pipe | Title"),
    ]
    report = nc.build_report(rows, date_str="2026-10-11")
    assert "more than one model digest" in report
    assert "Pipe \\| Title" in report


# ---------------------------------------------------------------------------
# Run: results cache / resume / errors / stops (requests mocked)
# ---------------------------------------------------------------------------
def _label_rows(*job_ids):
    return [{"job_id": j, "RF_status": "blank", "CU_status": "blank"} for j in job_ids]


class Calls:
    def __init__(self):
        self.states = []


def _install_fake_nimble(monkeypatch, behaviour=None):
    """Mock requests.post (systemone) and requests.get (tags). `behaviour(state)` may
    return a FakeResp or raise; default is an ok answer."""
    calls = Calls()

    def fake_post(url, **kwargs):
        state = json.loads(kwargs["data"])["state"]
        calls.states.append(state)
        if behaviour is not None:
            out = behaviour(state)
            if out is not None:
                return out
        return FakeResp(200, _answers())

    monkeypatch.setattr(nc.requests, "post", fake_post)
    monkeypatch.setattr(
        nc.requests, "get", lambda url, **kw: FakeResp(200, {"models": [{"name": nc.MODEL, "digest": "digest-123"}]})
    )
    return calls


def _state_with_jobs(tmp_path, ids, jd_len=1500):
    state = tmp_path / "state"
    for j in ids:
        _write_job(state, j, jd_len, jd=f"JD-{j} " + "x" * jd_len)
    return state


def test_run_checks_records_results_and_resume_skips_done_jobs(tmp_path, monkeypatch):
    state = _state_with_jobs(tmp_path, ["a", "b"])
    results_dir = tmp_path / "out" / "results"
    calls = _install_fake_nimble(monkeypatch)
    kw = dict(state_root=state, results_dir=results_dir, target_roles=["BA"], digest="digest-123", progress=lambda m: None)
    first = nc.run_checks(_label_rows("a", "b"), **kw)
    assert len(calls.states) == 2
    assert first["a"]["status"] == "ok" and first["a"]["model_digest"] == "digest-123"
    assert (results_dir / "a.json").exists() and (results_dir / "b.json").exists()
    saved = json.loads((results_dir / "a.json").read_text())
    assert saved["scores_1to5"]["seniority_fit"] == 3.0 and saved["input_tokens"] == 1234 and saved["latency_s"] >= 0
    assert saved["questions_sent"] == 7 and saved["per_question_tokens"] == 176

    again = nc.run_checks(_label_rows("a", "b"), **kw)
    assert len(calls.states) == 2  # nothing re-sent
    assert again["a"] == first["a"]

    forced = nc.run_checks(_label_rows("a", "b"), force=True, **kw)
    assert len(calls.states) == 4
    assert forced["b"]["status"] == "ok"


def test_resume_after_stop_only_asks_remaining_jobs(tmp_path, monkeypatch):
    state = _state_with_jobs(tmp_path, ["a", "b", "c"])
    results_dir = tmp_path / "out" / "results"

    def die_on_b(state_text):
        if state_text.startswith("JD-b"):
            raise nc.requests.exceptions.ConnectionError("refused")

    _install_fake_nimble(monkeypatch, die_on_b)
    kw = dict(state_root=state, results_dir=results_dir, target_roles=["BA"], digest="d", progress=lambda m: None)
    with pytest.raises(nc.OllamaUnavailable):
        nc.run_checks(_label_rows("a", "b", "c"), **kw)
    assert (results_dir / "a.json").exists() and not (results_dir / "b.json").exists()

    calls = _install_fake_nimble(monkeypatch)
    nc.run_checks(_label_rows("a", "b", "c"), **kw)
    assert [s[:4] for s in calls.states] == ["JD-b", "JD-c"]  # a was skipped


def test_per_job_http_error_is_recorded_and_run_continues_then_retried(tmp_path, monkeypatch):
    state = _state_with_jobs(tmp_path, ["a", "b", "c"])
    results_dir = tmp_path / "out" / "results"

    def fail_b(state_text):
        if state_text.startswith("JD-b"):
            return FakeResp(500, {"error": "boom"})

    calls = _install_fake_nimble(monkeypatch, fail_b)
    kw = dict(state_root=state, results_dir=results_dir, target_roles=["BA"], digest="d", progress=lambda m: None)
    out = nc.run_checks(_label_rows("a", "b", "c"), **kw)
    assert [out[j]["status"] for j in "abc"] == ["ok", "error", "ok"]
    assert "HTTP 500" in out["b"]["error"]
    assert len(calls.states) == 3
    # error results are not "done": the next run retries only b
    calls2 = _install_fake_nimble(monkeypatch)
    out2 = nc.run_checks(_label_rows("a", "b", "c"), **kw)
    assert [s[:4] for s in calls2.states] == ["JD-b"] and out2["b"]["status"] == "ok"


def test_missing_job_empty_and_overlong_jd_are_recorded_not_fatal(tmp_path, monkeypatch):
    state = tmp_path / "state"
    _write_job(state, "empty", 0, jd="   ")
    _write_job(state, "huge", 0, jd="y" * (nc.MAX_JD_CHARS + 1))
    results_dir = tmp_path / "out" / "results"
    calls = _install_fake_nimble(monkeypatch)
    kw = dict(state_root=state, results_dir=results_dir, target_roles=["BA"], digest="d", progress=lambda m: None)
    out = nc.run_checks(_label_rows("empty", "huge", "missing"), **kw)
    assert out["empty"]["status"] == "error"
    assert out["huge"]["status"] == "skipped" and "14000" in out["huge"]["error"]
    assert out["missing"]["status"] == "error" and "missing" in out["missing"]["error"]
    assert calls.states == []  # none of them was sent to Nimble


def test_shape_error_stops_the_run_and_keeps_saved_results(tmp_path, monkeypatch):
    state = _state_with_jobs(tmp_path, ["a", "b", "c"])
    results_dir = tmp_path / "out" / "results"
    bad = _answers()
    bad["answers"].pop("rf")
    calls = _install_fake_nimble(monkeypatch, lambda s: FakeResp(200, bad) if s.startswith("JD-b") else None)
    kw = dict(state_root=state, results_dir=results_dir, target_roles=["BA"], digest="d", progress=lambda m: None)
    with pytest.raises(nc.ShapeError, match="job b"):
        nc.run_checks(_label_rows("a", "b", "c"), **kw)
    assert len(calls.states) == 2  # c was never sent
    assert (results_dir / "a.json").exists()  # already-saved result kept
    assert not (results_dir / "b.json").exists() and not (results_dir / "c.json").exists()  # not an error record
    assert not list(results_dir.glob("*.tmp"))


def test_malformed_values_also_stop_the_run(tmp_path, monkeypatch):
    state = _state_with_jobs(tmp_path, ["a"])
    bad = _answers(tier="not_a_tier")
    _install_fake_nimble(monkeypatch, lambda s: FakeResp(200, bad))
    with pytest.raises(nc.ShapeError, match="posting_tier"):
        nc.run_checks(_label_rows("a"), state_root=state, results_dir=tmp_path / "r", target_roles=["BA"], digest="d", progress=lambda m: None)


def test_run_command_stops_with_message_and_exit_3_on_shape_error(tmp_path, monkeypatch, capsys):
    state, out = _export_for_run(tmp_path, ids=("reed-1", "reed-2", "reed-3"))
    bad = _answers()
    bad["answers"]["cu"] = {"type": "score", "score": 1.0}
    _install_fake_nimble(monkeypatch, lambda s: FakeResp(200, bad) if s.startswith("JD-reed-2") else None)
    args = ["run", "--state-root", str(state), "--out-dir", str(out), "--profile", str(tmp_path / "none.json")]
    assert nc.main(args) == 3
    err = capsys.readouterr().err
    assert "shape differs from the spec" in err and "reed-2" in err and "already saved are kept" in err
    assert (out / "results" / "reed-1.json").exists() and not (out / "results" / "reed-2.json").exists()
    assert not list(out.glob("report-*.md"))


def test_save_result_refuses_a_tmp_path_that_resolves_under_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    victim = data / "victim.txt"
    monkeypatch.setattr(nc, "DATA_DIR", data)
    results_dir = tmp_path / "out" / "results"  # itself outside data/
    results_dir.mkdir(parents=True)
    (results_dir / "a.json.tmp").symlink_to(victim)  # planted: <job_id>.json.tmp -> under data/
    with pytest.raises(ValueError, match="under data"):
        nc.save_result(results_dir, {"job_id": "a", "status": "ok"})
    assert not victim.exists()  # nothing was written through the symlink
    assert not (results_dir / "a.json").exists()


def test_save_result_refuses_a_final_path_that_resolves_under_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(nc, "DATA_DIR", data)
    results_dir = tmp_path / "out" / "results"
    results_dir.mkdir(parents=True)
    (results_dir / "a.json").symlink_to(data / "victim.json")
    with pytest.raises(ValueError, match="under data"):
        nc.save_result(results_dir, {"job_id": "a", "status": "ok"})
    assert not (data / "victim.json").exists() and not (results_dir / "a.json.tmp").exists()


def test_save_result_normal_write_leaves_no_tmp_file(tmp_path):
    results_dir = tmp_path / "out" / "results"
    nc.save_result(results_dir, {"job_id": "a", "status": "ok"})
    assert json.loads((results_dir / "a.json").read_text())["status"] == "ok"
    assert [p.name for p in results_dir.iterdir()] == ["a.json"]


def test_run_command_reports_write_guard_refusal_as_exit_2(tmp_path, monkeypatch, capsys):
    state, out = _export_for_run(tmp_path, ids=("reed-1",))
    _install_fake_nimble(monkeypatch)
    monkeypatch.setattr(nc, "DATA_DIR", tmp_path / "data")
    (out / "results").mkdir()
    (tmp_path / "data").mkdir()
    (out / "results" / "reed-1.json.tmp").symlink_to(tmp_path / "data" / "victim.txt")
    args = ["run", "--state-root", str(state), "--out-dir", str(out), "--profile", str(tmp_path / "none.json")]
    assert nc.main(args) == 2
    assert "under data" in capsys.readouterr().err
    assert not (tmp_path / "data" / "victim.txt").exists()


def test_unsafe_job_id_is_not_run_and_not_written(tmp_path, monkeypatch):
    calls = _install_fake_nimble(monkeypatch)
    results_dir = tmp_path / "out" / "results"
    out = nc.run_checks(
        _label_rows("../evil"), state_root=tmp_path, results_dir=results_dir, target_roles=[], digest="d", progress=lambda m: None
    )
    assert out["../evil"]["status"] == "error" and calls.states == []
    assert not results_dir.exists()
    with pytest.raises(ValueError):
        nc.result_path(results_dir, "a/b")


def test_per_question_tokens_divides_the_sum_and_rounds_to_int():
    assert nc.per_question_tokens(7626, 7) == 1089  # the smoke result: 1,089.4 per question
    assert nc.per_question_tokens(490, 2) == 245
    assert nc.per_question_tokens(188, 1) == 188
    assert isinstance(nc.per_question_tokens(7626, 7), int)
    assert nc.per_question_tokens(100, 0) == 100  # never divides by zero


@pytest.mark.parametrize(
    "roles,total,flagged",
    [
        (["BA"], 49_000, False),   # 7 questions: 7,000 per question is not over the limit
        (["BA"], 49_007, True),    # 7 questions: 7,001 per question is flagged
        (["BA"], 7_626, False),    # the live smoke result: the sum alone must not flag
        (["BA"], 7_001, False),    # the old rule flagged this; per question it is 1,000
        ([], 42_000, False),       # no target_roles: 6 questions sent
        ([], 42_006, True),
    ],
)
def test_check_job_flags_only_on_tokens_per_question(monkeypatch, roles, total, flagged):
    dims = nc.requested_dimensions(roles)
    calls = _install_fake_nimble(monkeypatch, lambda s: FakeResp(200, _answers(tokens=total, dims=dims)))
    rec = nc.check_job("a", "some jd", roles, "d")
    n = 7 if roles else 6
    assert rec["status"] == "ok" and rec["input_tokens"] == total
    assert rec["questions_sent"] == n and rec["per_question_tokens"] == round(total / n)
    assert rec["token_flag"] is flagged
    assert len(calls.states) == 1


def test_check_job_with_empty_target_roles_omits_alignment_and_parses(monkeypatch):
    sent = {}

    def capture(state_text):
        return FakeResp(200, _answers(dims=nc.requested_dimensions([])))

    calls = _install_fake_nimble(monkeypatch, capture)
    rec = nc.check_job("a", "jd", [], "d")
    assert rec["status"] == "ok"
    assert set(rec["scores_1to5"]) == {"seniority_fit", "culture_signals", "red_flags"}
    assert len(calls.states) == 1


# ---------------------------------------------------------------------------
# run command end to end (mocked) and smoke
# ---------------------------------------------------------------------------
def _export_for_run(tmp_path, ids=("reed-1", "reed-2")):
    state, out = tmp_path / "state", tmp_path / "out"
    for j in ids:
        _write_job(state, j, 1500, jd=f"JD-{j} " + "x" * 1500)
    assert nc.main(["export", "--state-root", str(state), "--out-dir", str(out)]) == 0
    return state, out


def _fill_labels(out: Path, labels: dict[str, tuple[str, str]]):
    path = out / "labels.csv"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    new = []
    for line in lines:
        cells = next(csv.reader([line])) if not line.startswith("#") else None
        if cells and cells[0] in labels:
            cells[-2], cells[-1] = labels[cells[0]]
            line = ",".join(f'"{c}"' if "," in c else c for c in cells)
        new.append(line)
    path.write_text("\n".join(new) + "\n", encoding="utf-8")


def test_run_command_writes_results_and_dated_report(tmp_path, monkeypatch, capsys):
    state, out = _export_for_run(tmp_path)
    _fill_labels(out, {"reed-1": ("y", "n"), "reed-2": ("n", "n")})
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"target_roles": ["Business Analyst"]}), encoding="utf-8")
    calls = _install_fake_nimble(monkeypatch)
    code = nc.main(["run", "--state-root", str(state), "--out-dir", str(out), "--profile", str(profile)])
    assert code == 0
    assert len(calls.states) == 2
    report = (out / f"report-{nc.date.today().isoformat()}.md").read_text(encoding="utf-8")
    assert "Indicative - small sample" in report and "digest-123" in report
    assert (out / "results" / "reed-1.json").exists()
    # re-run: nothing re-sent
    assert nc.main(["run", "--state-root", str(state), "--out-dir", str(out), "--profile", str(profile)]) == 0
    assert len(calls.states) == 2
    assert nc.main(["run", "--force", "--state-root", str(state), "--out-dir", str(out), "--profile", str(profile)]) == 0
    assert len(calls.states) == 4


def test_run_command_stops_cleanly_when_ollama_down_or_model_missing(tmp_path, monkeypatch, capsys):
    state, out = _export_for_run(tmp_path)
    args = ["run", "--state-root", str(state), "--out-dir", str(out), "--profile", str(tmp_path / "none.json")]

    def refused(url, **kw):
        raise nc.requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(nc.requests, "get", refused)
    assert nc.main(args) == 1
    assert "Is Ollama running" in capsys.readouterr().err

    monkeypatch.setattr(nc.requests, "get", lambda url, **kw: FakeResp(200, {"models": []}))
    assert nc.main(args) == 1
    assert "not listed" in capsys.readouterr().err
    assert not list(out.glob("report-*.md"))


def test_run_command_model_not_found_during_post_stops(tmp_path, monkeypatch, capsys):
    state, out = _export_for_run(tmp_path)
    _install_fake_nimble(
        monkeypatch, lambda s: FakeResp(404, {"error": 'model "nimble:9b-q4_K_M" not found, try pulling it first'})
    )
    args = ["run", "--state-root", str(state), "--out-dir", str(out), "--profile", str(tmp_path / "none.json")]
    assert nc.main(args) == 1
    assert "was not found" in capsys.readouterr().err
    assert not list(out.glob("report-*.md"))


def test_run_command_needs_labels_csv_and_refuses_data_out_dir(tmp_path, monkeypatch, capsys):
    assert nc.main(["run", "--out-dir", str(tmp_path / "empty")]) == 2
    assert "export" in capsys.readouterr().err
    monkeypatch.setattr(nc, "DATA_DIR", tmp_path / "data")
    assert nc.main(["run", "--out-dir", str(tmp_path / "data" / "x")]) == 2
    assert not (tmp_path / "data").exists()


def test_run_command_warns_when_nothing_is_labelled_yet(tmp_path, monkeypatch, capsys):
    state, out = _export_for_run(tmp_path, ids=("reed-1",))
    _install_fake_nimble(monkeypatch)
    nc.main(["run", "--state-root", str(state), "--out-dir", str(out), "--profile", str(tmp_path / "none.json")])
    assert "no labels found" in capsys.readouterr().err


def test_load_target_roles(tmp_path, capsys):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"target_roles": [" BA ", "", "PM"]}), encoding="utf-8")
    assert nc.load_target_roles(p) == ["BA", "PM"]
    p.write_text(json.dumps({"target_roles": "not a list"}), encoding="utf-8")
    assert nc.load_target_roles(p) == []
    assert nc.load_target_roles(tmp_path / "missing.json") == []
    assert "could not read profile" in capsys.readouterr().err


def test_smoke_prints_keys_tokens_latency_only_and_uses_builtin_sample(tmp_path, monkeypatch, capsys):
    calls = _install_fake_nimble(monkeypatch, lambda s: FakeResp(200, _answers(rf=0.123456, tokens=777, dims=nc.requested_dimensions(nc.SMOKE_ROLES))))
    monkeypatch.chdir(tmp_path)
    assert nc.main(["run", "--smoke"]) == 0
    out = capsys.readouterr().out
    assert calls.states == [nc.SMOKE_JD]  # the built-in sample, not a stored job
    assert "answer keys:" in out and "posting_tier" in out and "rf" in out
    assert "input_tokens (sum over 7 questions): 777" in out
    assert "per-question tokens: 111" in out and "latency_s:" in out
    assert "0.123456" not in out  # no answer values printed
    assert list(tmp_path.iterdir()) == []  # smoke writes nothing


def test_smoke_shape_mismatch_and_unreachable(tmp_path, monkeypatch, capsys):
    bad = _answers(dims=nc.requested_dimensions(nc.SMOKE_ROLES))
    bad["answers"]["cu"] = {"type": "score", "score": 1.0}
    _install_fake_nimble(monkeypatch, lambda s: FakeResp(200, bad))
    assert nc.main(["run", "--smoke"]) == 3
    captured = capsys.readouterr()
    assert "SHAPE MISMATCH" in captured.err and "answer keys:" in captured.out

    def refused(url, **kw):
        raise nc.requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(nc.requests, "post", refused)
    assert nc.main(["run", "--smoke"]) == 1
    assert "Is Ollama running" in capsys.readouterr().err
