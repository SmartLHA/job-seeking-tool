"""Synthetic, offline coverage for durable per-search run history."""
import json
import sqlite3
from types import SimpleNamespace

import pytest

import src.job_hunt_scheduler as scheduler
import src.job_hunt_saved_searches as searches
import src.job_sources.source_registry as registry
from src.job_hunt_profile import candidate_profile_from_dict
from src.job_hunt_index import open_db
from src.job_hunt_storage import ensure_storage_layout


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = dict(registry._REGISTRY)
    monkeypatch.setattr(scheduler, "extract_skills_from_text", lambda text: (["python"], [], None))
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(original)


def search(sid="s1", **kwargs):
    return searches.SavedSearch(sid, "Synthetic", kwargs.get("source", "stub"),
                               kwargs.get("params", {}), kwargs.get("enabled", True),
                               "2026-11-05", None, 0)


def source(results=(), *, fail=None, normalize=None):
    def fetch(params):
        if fail:
            raise fail
        return results
    registry.register(registry.JobSource("stub", "Stub", lambda: True,
        normalize or (lambda p: dict(p)), fetch, lambda *a: {}, lambda *a: "", lambda *a: ""))


def setup(tmp_path):
    ensure_storage_layout(tmp_path)
    db = tmp_path / "job_hunt_index.db"
    open_db(db).close()
    return SimpleNamespace(state_root=tmp_path, profile_path=tmp_path / "profile.json"), db


def run(tmp_path, ss=None, **kwargs):
    config, db = setup(tmp_path)
    return scheduler.run_digest_pipeline(config=config, saved_searches=ss or [search()],
        profile=candidate_profile_from_dict({"candidate_id": "synthetic", "skills": ["python"]}),
        db_path=db, **kwargs)


def record(tmp_path, sid="s1", **kwargs):
    searches.record_search_run(sid, state_root=tmp_path, trigger="manual",
        started_at="2026-11-05T10:00:00", finished_at="2026-11-05T10:00:01", **kwargs)


def test_storage_reopen_bounds_order_and_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(searches, "get_enabled_sources", lambda: ["stub"])
    searches.save_saved_search(search(), state_root=tmp_path)
    for n in range(25):
        record(tmp_path, jobs_fetched=n, errors=["s1: <script>" + "x" * 600] * 25)
    rows = searches.list_search_runs("s1", state_root=tmp_path)
    assert len(rows) == 20
    assert [r["jobs_fetched"] for r in rows] == list(range(24, 4, -1))
    assert len(rows[0]["errors"]) == 20
    assert all(len(e) == 500 and e.startswith("<script>") for e in rows[0]["errors"])
    assert rows[0]["status"] == "partial"
    assert searches.delete_saved_search("s1", state_root=tmp_path)
    assert searches.list_search_runs("s1", state_root=tmp_path) == []


def test_old_database_unchanged_and_opaque_id_not_validated(tmp_path):
    conn = sqlite3.connect(tmp_path / "job_hunt_index.db")
    conn.execute(searches._TABLE_SQL)
    conn.execute("INSERT INTO saved_searches VALUES (?,?,?,?,?,?,?,?)",
                 ("old", "Old", "reed", '{"keywords":"BA"}', 1, "yesterday", None, 7))
    conn.commit()
    before = conn.execute("SELECT * FROM saved_searches").fetchall()
    conn.close()
    record(tmp_path, sid="opaque/id", errors=["opaque/id/problem", "opaque/id: other"])
    assert searches.list_search_runs("opaque/id", state_root=tmp_path)[0]["errors"] == ["problem", "other"]
    conn = sqlite3.connect(tmp_path / "job_hunt_index.db")
    assert conn.execute("SELECT * FROM saved_searches").fetchall() == before
    conn.close()


def test_scheduled_each_enabled_and_manual_counts(tmp_path):
    source([None, {"source_job_id": "1", "description_raw": "", "title": "Blank"}])
    result = run(tmp_path, [search(), search("s2"), search("off", enabled=False)])
    assert result.jobs_fetched == 4
    for sid in ("s1", "s2"):
        row = searches.list_search_runs(sid, state_root=tmp_path)[0]
        assert (row["trigger"], row["jobs_fetched"], row["jobs_skipped"], row["status"]) == ("scheduled", 2, 2, "ok")
    assert searches.list_search_runs("off", state_root=tmp_path) == []
    run(tmp_path, trigger="manual")
    assert searches.list_search_runs("s1", state_root=tmp_path)[0]["trigger"] == "manual"


def test_failed_fetch_and_unknown_source_rows(tmp_path):
    source(fail=RuntimeError("synthetic timeout"))
    result = run(tmp_path, [search(), search("missing", source="absent")])
    assert len(result.errors) == 2
    for sid in ("s1", "missing"):
        row = searches.list_search_runs(sid, state_root=tmp_path)[0]
        assert row["status"] == "failed" and row["errors"]
        assert not row["errors"][0].startswith(sid + ": ")


@pytest.mark.parametrize("write_fails", [False, True])
def test_unexpected_exception_preserves_identity(tmp_path, monkeypatch, write_fails):
    failure = RuntimeError("original iteration error")
    def broken():
        yield None
        raise failure
    source(broken())
    if write_fails:
        monkeypatch.setattr(scheduler, "record_search_run", lambda *a, **k: (_ for _ in ()).throw(ValueError("write")))
    with pytest.raises(RuntimeError) as caught:
        run(tmp_path)
    assert caught.value is failure
    if not write_fails:
        row = searches.list_search_runs("s1", state_root=tmp_path)[0]
        assert row["status"] == "partial" and row["jobs_fetched"] == 1
        assert "original iteration error" in row["errors"][0]


def test_policy_failure_records_all_enabled_and_reraises(tmp_path, monkeypatch):
    failure = RuntimeError("policy unavailable")
    monkeypatch.setattr(scheduler, "get_active_scoring_policy", lambda **k: (_ for _ in ()).throw(failure))
    with pytest.raises(RuntimeError) as caught:
        run(tmp_path, [search(), search("s2"), search("off", enabled=False)])
    assert caught.value is failure
    for sid in ("s1", "s2"):
        assert searches.list_search_runs(sid, state_root=tmp_path)[0]["status"] == "failed"
    assert searches.list_search_runs("off", state_root=tmp_path) == []


def test_write_failure_is_visible_and_does_not_stop_next_search(tmp_path, monkeypatch):
    source([None])
    monkeypatch.setattr(scheduler, "record_search_run", lambda *a, **k: (_ for _ in ()).throw(ValueError("disk unavailable")))
    result = run(tmp_path, [search(), search("s2")])
    assert result.searches_run == 2 and result.jobs_fetched == 2
    assert result.errors == [f"{sid}: run record not saved: disk unavailable" for sid in ("s1", "s2")]


def test_dataclass_roundtrip_and_old_dict():
    result = scheduler.DigestRunResult("a", "b", 1, 2, 3, 4, 5, 6, 7, ["problem"], 8, 9, 10)
    assert scheduler.DigestRunResult(**result.to_dict()) == result
    old = result.to_dict()
    for key in ("jobs_below_floor", "jobs_salary_unknown", "jobs_held_over"):
        del old[key]
    assert scheduler.DigestRunResult(**old).jobs_held_over == 0


class Responder:
    def send_json(self, payload, **kwargs):
        self.payload, self.status = payload, kwargs.get("status", 200)


def test_profile_failure_records_manual_without_changing_reply(tmp_path, monkeypatch):
    import src.ui_handlers as handlers
    config, _ = setup(tmp_path)
    monkeypatch.setattr(handlers, "load_saved_search", lambda *a, **k: search())
    monkeypatch.setattr(handlers, "_load_active_profile", lambda *a: (_ for _ in ()).throw(ValueError("bad profile")))
    responder = Responder()
    handlers.handle_run_now(None, config, responder, "s1")
    assert responder.status == 500
    assert responder.payload == {"ok": False, "error": "Could not load profile: bad profile"}
    row = searches.list_search_runs("s1", state_root=tmp_path)[0]
    assert row["trigger"] == "manual" and row["status"] == "failed"
    monkeypatch.setattr(searches, "record_search_run", lambda *a, **k: (_ for _ in ()).throw(ValueError("disk")))
    handlers.handle_run_now(None, config, responder, "s1")
    assert responder.status == 500


def test_list_route_keeps_all_errors_and_read_failure_tolerates(tmp_path, monkeypatch):
    import src.ui_handlers as handlers
    config, _ = setup(tmp_path)
    monkeypatch.setattr(handlers, "list_saved_searches", lambda **k: [search()])
    record(tmp_path, errors=["one", "two", "<script>"])
    responder = Responder()
    handlers.handle_saved_searches_list(None, config, responder)
    assert responder.payload["searches"][0]["runs"][0]["errors"] == ["one", "two", "<script>"]
    monkeypatch.setattr(searches, "list_search_runs", lambda *a, **k: (_ for _ in ()).throw(ValueError("read")))
    handlers.handle_saved_searches_list(None, config, responder)
    assert responder.payload["searches"][0]["runs"] == []


def test_record_all_counts_and_salary_floor(tmp_path):
    counts = {key: n for n, key in enumerate(searches._RUN_COUNTERS, 1)}
    record(tmp_path, salary_floor=65000, **counts)
    row = searches.list_search_runs("s1", state_root=tmp_path)[0]
    assert row["salary_floor"] == 65000
    assert {key: row[key] for key in counts} == counts


def test_run_now_http_history(tmp_path, monkeypatch):
    """Socket acceptance coverage: run only by the orchestrator outside sandbox."""
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from src.ui_state import UIServerConfig
    from src.ui_routes import _build_handler
    import src.ui_handlers as handlers
    source([None])
    state = tmp_path / "state"
    ensure_storage_layout(state)
    monkeypatch.setattr(searches, "get_enabled_sources", lambda: ["stub"])
    searches.save_saved_search(search(), state_root=state)
    monkeypatch.setattr(handlers, "_load_active_profile", lambda c:
                        candidate_profile_from_dict({"candidate_id": "synthetic"}))
    config = UIServerConfig(profile_path=tmp_path / "unused.json", state_root=state,
                            report_dir=tmp_path / "reports", host="127.0.0.1", port=0)
    server = ThreadingHTTPServer((config.host, config.port), _build_handler(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = urllib.request.Request(base + "/saved-searches/s1/run-now",
                                         method="POST", headers={"Origin": base})
        with urllib.request.urlopen(request) as response:
            assert json.loads(response.read())["ok"] is True
        with urllib.request.urlopen(base + "/saved-searches") as response:
            row = json.loads(response.read())["searches"][0]["runs"][0]
        assert (row["trigger"], row["jobs_fetched"]) == ("manual", 1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("counts,status,summary", [
    ({"errors": ["s1: timeout"]}, "failed", "Run failed: timeout. No jobs were fetched."),
    ({"errors": ["s1/problem", "second", "third"]}, "failed", "Run failed: problem. No jobs were fetched. (+2 more)"),
    ({"jobs_fetched": 3, "jobs_new": 1, "errors": ["s1: timeout"]}, "partial", "Run finished with 1 problem(s): fetched 3, 1 new. First: timeout"),
    ({}, "ok", "Run done: Stub returned no jobs for this search."),
    ({"jobs_fetched": 2, "jobs_already_seen": 2}, "ok", "Run done: fetched 2, nothing new (2 already seen)."),
    ({"jobs_fetched": 12, "jobs_new": 2, "jobs_llm_queued": 1, "jobs_skipped": 2,
      "jobs_already_seen": 3, "jobs_below_floor": 4, "jobs_salary_unknown": 5, "jobs_held_over": 1},
     "ok", "Run done: fetched 12, 2 new (1 queued for AI, 2 skipped, 3 already seen, 4 below salary floor, 5 salary unknown, 1 not attempted (budget reached))."),
])
def test_summary_table(counts, status, summary, tmp_path, monkeypatch):
    assert searches.search_run_summary(counts, search_id="s1", source_name="Stub") == {
        "run_status": status, "summary": summary}
    import src.ui_handlers as handlers
    config, _ = setup(tmp_path)
    source()
    monkeypatch.setattr(handlers, "load_saved_search", lambda *a, **k: search())
    monkeypatch.setattr(handlers, "_load_active_profile", lambda c: object())
    result_counts = {key: counts.get(key, 0) for key in searches._RUN_COUNTERS}
    result = scheduler.DigestRunResult(started_at="a", finished_at="b", searches_run=1,
                                      errors=counts.get("errors", []), **result_counts)
    monkeypatch.setattr(scheduler, "run_digest_pipeline", lambda **k: result)
    responder = Responder()
    handlers.handle_run_now(None, config, responder, "s1")
    assert responder.payload["ok"] is True
    assert responder.payload["run_status"] == status
    assert responder.payload["summary"] == summary


@pytest.mark.parametrize("failed", [False, True])
def test_run_now_response_summary_without_socket(tmp_path, monkeypatch, failed):
    import src.ui_handlers as handlers
    config, _ = setup(tmp_path)
    source(fail=RuntimeError("timeout") if failed else None)
    monkeypatch.setattr(handlers, "load_saved_search", lambda *a, **k: search())
    monkeypatch.setattr(handlers, "_load_active_profile", lambda c:
                        candidate_profile_from_dict({"candidate_id": "synthetic"}))
    responder = Responder()
    handlers.handle_run_now(None, config, responder, "s1")
    assert responder.payload["ok"] is True
    assert responder.payload["run_status"] == ("failed" if failed else "ok")
    assert responder.payload["summary"] == (
        "Run failed: fetch failed: timeout. No jobs were fetched." if failed
        else "Run done: Stub returned no jobs for this search.")
    assert "run_status" not in scheduler.DigestRunResult("a", "b", 0, 0, 0, 0, 0, 0, 0, []).to_dict()
    assert "summary" not in scheduler.DigestRunResult("a", "b", 0, 0, 0, 0, 0, 0, 0, []).to_dict()


def test_disabled_run_before_profile_without_row(tmp_path, monkeypatch):
    import src.ui_handlers as handlers
    config, _ = setup(tmp_path)
    monkeypatch.setattr(handlers, "load_saved_search", lambda *a, **k: search(enabled=False))
    def forbidden(*a):
        raise AssertionError("profile must not load")
    monkeypatch.setattr(handlers, "_load_active_profile", forbidden)
    responder = Responder()
    handlers.handle_run_now(None, config, responder, "s1")
    assert responder.payload == {"ok": True, "run_status": "not_run",
                                 "summary": "Not run: this saved search is disabled."}
    assert searches.list_search_runs("s1", state_root=tmp_path) == []


def test_list_summaries_newest_and_source_fallback(tmp_path, monkeypatch):
    import src.ui_handlers as handlers
    config, _ = setup(tmp_path)
    source()
    monkeypatch.setattr(handlers, "list_saved_searches", lambda **k: [search()])
    for n in range(25):
        record(tmp_path, jobs_fetched=n, errors=["one", "two", "<script>"])
    responder = Responder()
    handlers.handle_saved_searches_list(None, config, responder)
    rows = responder.payload["searches"][0]["runs"]
    assert len(rows) == 20
    assert [r["jobs_fetched"] for r in rows] == list(range(24, 4, -1))
    assert rows[0]["errors"] == ["one", "two", "<script>"]
    for row in rows:
        assert row["summary"] == f'Run finished with 3 problem(s): fetched {row["jobs_fetched"]}, nothing new. First: one'
        assert row["run_status"] == "partial"
    assert handlers._saved_search_source_name(search()) == "Stub"
    assert handlers._saved_search_source_name(search(source="missing")) == "Missing"


def test_served_profile_script_summary_and_history_escape():
    from src.ui_render import ProfilePageViewModel, render_profile_page
    vm = ProfilePageViewModel(has_profile=False, name="", target_roles=[], locations=[],
        remote_preference="", salary_floor_gbp=None, right_to_work_uk=False, skills=[],
        years_experience=0, industries=[], certifications=[], achievements=[],
        master_cv_ref="", master_cv_text="")
    page = render_profile_page(profile_id="synthetic", vm=vm, parsed_cv_text=None,
                               parsed_filename=None, errors={}, form_values=None)
    assert 'setStatus(d.summary, d.run_status === "failed" || d.run_status === "partial")' in page
    script = page[page.index('var listEl = document.getElementById("saved-searches-list")'):]
    assert "Run done" not in script
    for escaped in ('esc(run.finished_at)', 'esc(run.summary)', 'esc(error)',
                    'esc(run.trigger === "manual" ? "Run now" : "scheduled")', 'esc(s.last_run_count)'):
        assert escaped in script
    assert 'runs.map(function(run)' in script
    assert 'runText(runs[0])' in script
    assert 'Run history (' in script and 'Last run ' in script and ' new)' in script
    assert 'run.run_status === "failed" || run.run_status === "partial" ? "#b91c1c"' in script


def test_partial_multicount_summary():
    counts = {"jobs_fetched": 8, "jobs_new": 2, "jobs_skipped": 3,
              "jobs_salary_unknown": 1, "errors": ["s1: first", "s1/second"]}
    assert searches.search_run_summary(counts, search_id="s1", source_name="Stub") == {
        "run_status": "partial",
        "summary": "Run finished with 2 problem(s): fetched 8, 2 new (3 skipped, 1 salary unknown). First: first"}


@pytest.mark.parametrize("outcome", ["ok", "failed", "disabled"])
def test_http_step4_run_now_and_served_profile(tmp_path, monkeypatch, outcome):
    """Actual HTTP acceptance coverage; requires separately authorized socket execution."""
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from src.ui_state import UIServerConfig
    from src.ui_routes import _build_handler
    import src.ui_handlers as handlers

    source(fail=RuntimeError("timeout") if outcome == "failed" else None)
    state = tmp_path / "state"
    ensure_storage_layout(state)
    monkeypatch.setattr(searches, "get_enabled_sources", lambda: ["stub"])
    searches.save_saved_search(search(enabled=outcome != "disabled"), state_root=state)
    profile = candidate_profile_from_dict({"candidate_id": "synthetic",
                                          "digest_enabled": False, "digest_llm_enabled": False})
    def active_profile(config):
        if outcome == "disabled":
            raise AssertionError("disabled search must not load profile")
        return profile
    monkeypatch.setattr(handlers, "_load_active_profile", active_profile)
    monkeypatch.setattr(handlers, "_allowed_profile_dir", lambda pid: tmp_path / "synthetic-profile")
    monkeypatch.setattr(handlers, "load_candidate_profile", lambda path: profile)
    monkeypatch.setattr(handlers, "get_enabled_sources", lambda: ["stub"])
    config = UIServerConfig(profile_path=tmp_path / "synthetic.json", state_root=state,
                            report_dir=tmp_path / "reports", host="127.0.0.1", port=0)
    server = ThreadingHTTPServer((config.host, config.port), _build_handler(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = urllib.request.Request(base + "/saved-searches/s1/run-now", method="POST",
                                         headers={"Origin": base})
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read())
        assert payload["ok"] is True
        assert payload["run_status"] == {"ok": "ok", "failed": "failed", "disabled": "not_run"}[outcome]
        assert payload["summary"] == {
            "ok": "Run done: Stub returned no jobs for this search.",
            "failed": "Run failed: fetch failed: timeout. No jobs were fetched.",
            "disabled": "Not run: this saved search is disabled.",
        }[outcome]
        with urllib.request.urlopen(base + "/saved-searches") as response:
            rows = json.loads(response.read())["searches"][0]["runs"]
        if outcome == "disabled":
            assert rows == []
        else:
            assert rows[0]["summary"] == payload["summary"]
            assert rows[0]["trigger"] == "manual"
        with urllib.request.urlopen(base + "/profile?profile_id=synthetic") as response:
            page = response.read().decode()
        script = page[page.index('var listEl = document.getElementById("saved-searches-list")'):]
        assert 'setStatus(d.summary, d.run_status === "failed" || d.run_status === "partial")' in script
        assert "Run done" not in script
        assert 'esc(run.summary)' in script and 'esc(error)' in script
        assert 'esc(run.finished_at)' in script and 'Run history (' in script
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
