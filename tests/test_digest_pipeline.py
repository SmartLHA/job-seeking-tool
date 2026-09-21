"""Tests for Daily Job Digest phase D3 — the deterministic pipeline.

Uses a stubbed JobSource (the real Reed/Adzuna APIs aren't reachable offline) so
dedup, scoring, queueing, skip-logging, the global LLM cap, and counter semantics
are all verified deterministically. Skill extraction is monkeypatched to keep runs
fast and offline (the real extract_skills_from_text tries Ollama first).
"""
from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from src.job_hunt_profile import candidate_profile_from_dict
from src.job_hunt_saved_searches import SavedSearch, save_saved_search
from src.job_hunt_storage import ensure_storage_layout
from src.job_hunt_index import is_already_indexed, open_db
from src.job_hunt_digest import query_digest
from src.job_sources.source_registry import JobSource, register
import src.job_hunt_scheduler as scheduler
from src.job_hunt_scheduler import run_digest_pipeline


@pytest.fixture(autouse=True)
def _fast_skills(monkeypatch):
    # Deterministic, offline skill extraction (real one tries Ollama first).
    monkeypatch.setattr(scheduler, "extract_skills_from_text",
                        lambda text: (["python", "sql"], ["excel"], None))


def _register_stub(results, source_id="stub"):
    register(JobSource(
        source_id=source_id, display_name="Stub", is_available=lambda: True,
        normalize_search_params=lambda p: dict(p),
        search_handler=lambda params: list(results),
        select_handler=lambda form, config: {},
        render_search_form=lambda values, enabled: "",
        render_results=lambda results, error, nonce, more_url=None: "",
    ))


def _profile(threshold=0, **extra):
    return candidate_profile_from_dict({
        "candidate_id": "cand-001",
        "skills": ["python", "sql"],
        "target_roles": ["Data Analyst"],
        "locations": ["London"],
        "digest_threshold": threshold,
        **extra,
    })


def _result(sjid="100", **over):
    base = {
        "source": "stub", "source_job_id": sjid, "title": "Data Analyst",
        "company": "Acme", "location": "London",
        "description_raw": "We need python and sql for analytics.",
        "salary_min_gbp": "50000", "salary_max_gbp": "60000",
        "url": "https://acme/jobs/" + sjid, "work_mode": "hybrid",
        "employment_type": "permanent",
    }
    base.update(over)
    return base


def _setup(tmp_path):
    ensure_storage_layout(tmp_path)
    db = tmp_path / "job_hunt_index.db"
    open_db(db).close()
    config = types.SimpleNamespace(state_root=tmp_path, profile_path=tmp_path / "p.json")
    return config, db


def _search(source_id="stub", params=None, sid="s1"):
    return SavedSearch(sid, "BA London", source_id, params or {}, True,
                       "2026-06-24T00:00:00", None, 0)


# --------------------------------------------------------------------------- #

def test_pipeline_scores_and_indexes_new_job(tmp_path):
    config, db = _setup(tmp_path)
    _register_stub([_result("100")])
    r = run_digest_pipeline(config=config, saved_searches=[_search()], profile=_profile(), db_path=db)
    assert (r.jobs_fetched, r.jobs_new, r.jobs_scored, r.jobs_skipped) == (1, 1, 1, 0)
    assert r.searches_run == 1
    assert is_already_indexed(db, "stub", "100")
    entries = query_digest(db_path=db)
    assert len(entries) == 1 and entries[0].source_id == "stub"


def test_pipeline_dedups_already_seen(tmp_path):
    config, db = _setup(tmp_path)
    _register_stub([_result("100")])
    run_digest_pipeline(config=config, saved_searches=[_search()], profile=_profile(), db_path=db)
    r2 = run_digest_pipeline(config=config, saved_searches=[_search()], profile=_profile(), db_path=db)
    assert r2.jobs_new == 0
    assert r2.jobs_already_seen == 1


def test_pipeline_skips_blank_id(tmp_path):
    config, db = _setup(tmp_path)
    _register_stub([_result(sjid="")])
    r = run_digest_pipeline(config=config, saved_searches=[_search()], profile=_profile(), db_path=db)
    assert r.jobs_skipped == 1 and r.jobs_new == 0
    logs = list((tmp_path / "logs").glob("digest_skipped_jobs_*.jsonl"))
    assert logs, "skip should be logged"
    assert "missing_source_job_id" in logs[0].read_text()


def test_pipeline_skips_blank_description(tmp_path):
    config, db = _setup(tmp_path)
    _register_stub([_result("101", description_raw="   ")])
    r = run_digest_pipeline(config=config, saved_searches=[_search()], profile=_profile(), db_path=db)
    assert r.jobs_skipped == 1 and r.jobs_new == 0
    logs = list((tmp_path / "logs").glob("*.jsonl"))
    assert "missing_description_raw" in logs[0].read_text()


def test_pipeline_queues_high_match(tmp_path):
    config, db = _setup(tmp_path)
    _register_stub([_result("100")])
    r = run_digest_pipeline(config=config, saved_searches=[_search()],
                            profile=_profile(threshold=0, digest_llm_enabled=True), db_path=db)
    assert r.jobs_llm_queued == 1
    conn = open_db(db)
    try:
        assert conn.execute("SELECT llm_status FROM jobs").fetchone()["llm_status"] == "pending"
    finally:
        conn.close()


def test_pipeline_llm_disabled_queues_nothing(tmp_path):
    config, db = _setup(tmp_path)
    _register_stub([_result("100")])
    r = run_digest_pipeline(config=config, saved_searches=[_search()],
                            profile=_profile(threshold=0, digest_llm_enabled=False), db_path=db)
    assert r.jobs_llm_queued == 0


def test_global_llm_cap_spans_searches(tmp_path):
    config, db = _setup(tmp_path)
    # two searches via two stub sources, each returning one high-match job
    _register_stub([_result("100")], source_id="stub")
    _register_stub([_result("200")], source_id="stub2")
    searches = [_search("stub", sid="s1"), _search("stub2", sid="s2")]
    prof = _profile(threshold=0, digest_llm_enabled=True, digest_max_llm_per_run=1)
    r = run_digest_pipeline(config=config, saved_searches=searches, profile=prof, db_path=db)
    assert r.jobs_new == 2
    assert r.jobs_llm_queued == 1   # cap is global to the run, not per-search


def test_unknown_source_recorded_as_error(tmp_path):
    config, db = _setup(tmp_path)
    r = run_digest_pipeline(config=config, saved_searches=[_search("nope")], profile=_profile(), db_path=db)
    assert r.searches_run == 0 and r.jobs_new == 0
    assert any("unknown source" in e for e in r.errors)


def test_max_per_source_caps_results(tmp_path):
    config, db = _setup(tmp_path)
    _register_stub([_result(str(i)) for i in range(10)])
    prof = _profile(threshold=0, digest_max_per_source=3)
    r = run_digest_pipeline(config=config, saved_searches=[_search()], profile=prof, db_path=db)
    assert r.jobs_fetched == 3 and r.jobs_new == 3


def test_one_bad_result_does_not_abort_run(tmp_path, monkeypatch):
    config, db = _setup(tmp_path)
    _register_stub([_result("100"), _result("101"), _result("102")])

    # Make the 2nd conversion blow up; the run must still process 1st and 3rd.
    real = scheduler.reviewed_job_payload_from_ui_result
    def flaky(result, *, source_id=None):
        if result.get("source_job_id") == "101":
            raise RuntimeError("boom")
        return real(result, source_id=source_id)
    monkeypatch.setattr(scheduler, "reviewed_job_payload_from_ui_result", flaky)

    r = run_digest_pipeline(config=config, saved_searches=[_search()], profile=_profile(), db_path=db)
    assert r.jobs_new == 2 and r.jobs_skipped == 1
    logs = list((tmp_path / "logs").glob("*.jsonl"))
    assert "evaluation_error" in logs[0].read_text()


def test_persist_failure_is_error_not_skip(tmp_path, monkeypatch):
    # A failure AFTER successful eval (e.g. upsert) must count as scored + error,
    # never as a skip (Codex: counters were conflated).
    config, db = _setup(tmp_path)
    _register_stub([_result("100")])
    monkeypatch.setattr(scheduler, "upsert_job",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    r = run_digest_pipeline(config=config, saved_searches=[_search()], profile=_profile(), db_path=db)
    assert r.jobs_scored == 1      # eval succeeded
    assert r.jobs_new == 0         # never indexed
    assert r.jobs_skipped == 0     # NOT a skip
    assert r.errors and "persist/index failed" in r.errors[0]


def test_non_dict_result_does_not_abort(tmp_path):
    config, db = _setup(tmp_path)
    _register_stub(["not-a-dict", _result("100")])
    r = run_digest_pipeline(config=config, saved_searches=[_search()], profile=_profile(), db_path=db)
    assert r.jobs_new == 1 and r.jobs_skipped == 1


def test_mapper_uses_authoritative_source_id():
    from src.ui_utils import reviewed_job_payload_from_ui_result
    # result claims source "REED" but the saved search says "stub" → job_id uses stub
    payload = reviewed_job_payload_from_ui_result(
        {"source": "REED", "source_job_id": "9", "title": "T", "company": "C",
         "description_raw": "d", "url": "u"}, source_id="stub")
    assert payload["job_id"] == "stub-9"
    assert payload["source_type"] == "stub"


def test_mapper_salary_handles_currency_and_commas():
    from src.ui_utils import reviewed_job_payload_from_ui_result
    p = reviewed_job_payload_from_ui_result(
        {"source": "reed", "source_job_id": "1", "title": "T", "company": "C",
         "description_raw": "d", "salary_min_gbp": "£60,000", "salary_max_gbp": "75000"},
        source_id="reed")
    assert p["salary_min_gbp"] == 60000 and p["salary_max_gbp"] == 75000


# --------------------------------------------------------------------------- #
# run-now route (through the real dispatcher + server)
# --------------------------------------------------------------------------- #

def test_run_now_route(tmp_path, monkeypatch):
    import json as _json
    import threading
    import urllib.request
    import urllib.error
    from http.server import ThreadingHTTPServer
    from src.ui_state import UIServerConfig
    from src.ui_routes import _build_handler
    import src.ui_handlers as handlers

    # deterministic skills inside the server process too
    monkeypatch.setattr(scheduler, "extract_skills_from_text",
                        lambda text: (["python", "sql"], [], None))

    state = tmp_path / "state"
    ensure_storage_layout(state)
    # a real profile file for _load_active_profile
    prof_path = tmp_path / "profile.json"
    prof_path.write_text(_json.dumps({"candidate_id": "cand-001", "skills": ["python"],
                                      "digest_threshold": 0}), encoding="utf-8")
    _register_stub([_result("100")])
    # save a stub-source saved search directly (the create route only allows enabled sources)
    monkeypatch.setattr("src.job_hunt_saved_searches.get_enabled_sources", lambda: ["stub"])
    save_saved_search(_search(sid="route1"), state_root=state)

    config = UIServerConfig(profile_path=prof_path, state_root=state,
                            report_dir=tmp_path / "rep", host="127.0.0.1", port=0)
    srv = ThreadingHTTPServer((config.host, config.port), _build_handler(config))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        # unknown id → 404
        try:
            urllib.request.urlopen(urllib.request.Request(base + "/saved-searches/nope/run-now", method="POST"))
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 404
        # real run → ok + counts
        with urllib.request.urlopen(urllib.request.Request(base + "/saved-searches/route1/run-now", method="POST")) as resp:
            body = _json.loads(resp.read())
        assert body["ok"] is True
        assert body["jobs_new"] == 1
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)
