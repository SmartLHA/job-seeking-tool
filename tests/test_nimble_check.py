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
