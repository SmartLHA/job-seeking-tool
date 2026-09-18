"""End-to-end test of the Daily Job Digest (D1–D6) through the REAL HTTP server.

Drives the full user journey over HTTP: create a saved search → Run now (pipeline)
→ digest feed + badge → mark seen → drain the LLM batch → llm-queue + analysis
enrichment → scheduler status. Only the two external dependencies are stubbed:
the source's search_handler (a fixture "reed" override, so no live API) and Gemini
(monkeypatched). Everything else — routes, DB, dedup, scoring, queue — is real.

Purpose: surface integration bugs the per-phase unit tests miss.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import src.job_hunt_llm as llm
import src.job_hunt_scheduler as scheduler
import src.job_sources.source_registry as _reg
from src.job_sources.source_registry import JobSource, register
from src.ui_state import UIServerConfig
from src.ui_routes import _build_handler
from src.job_hunt_storage import ensure_storage_layout, load_job_analysis


@pytest.fixture(autouse=True)
def _restore_source_registry():
    """This E2E overrides the process-global 'reed' source with a fixture; snapshot
    and restore the registry so the mutation never leaks into other test modules."""
    snapshot = dict(_reg._REGISTRY)
    try:
        yield
    finally:
        _reg._REGISTRY.clear()
        _reg._REGISTRY.update(snapshot)


def _fixture_results():
    return [
        {"source": "reed", "source_job_id": "1001", "title": "Business Analyst",
         "company": "Acme", "location": "London",
         "description_raw": "We need Python and SQL for analytics and stakeholder work.",
         "salary_min_gbp": "55000", "salary_max_gbp": "70000",
         "url": "https://www.reed.co.uk/jobs/1001", "work_mode": "hybrid",
         "employment_type": "permanent"},
        {"source": "reed", "source_job_id": "1002", "title": "Data Analyst",
         "company": "Globex", "location": "Manchester",
         "description_raw": "SQL, Python, dashboards and reporting.",
         "salary_min_gbp": "48000", "salary_max_gbp": "60000",
         "url": "https://www.reed.co.uk/jobs/1002", "work_mode": "remote",
         "employment_type": "permanent"},
        # one job that must be SKIPPED — blank source_job_id (not dedupable)
        {"source": "reed", "source_job_id": "", "title": "Bad Job", "company": "X",
         "description_raw": "desc", "url": "https://x/none"},
    ]


def _register_fixture_reed():
    # Override the real "reed" registration with a stub returning canned results.
    register(JobSource(
        source_id="reed", display_name="Reed (fixture)", is_available=lambda: True,
        normalize_search_params=lambda p: dict(p),
        search_handler=lambda params: list(_fixture_results()),
        select_handler=lambda form, config: {},
        render_search_form=lambda values, enabled: "",
        render_results=lambda results, error, nonce, more_url=None: "",
    ))


def _write_profile(tmp_path: Path) -> Path:
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({
        "candidate_id": "cand-001",
        "name": "Mic",
        "skills": ["Python", "SQL", "Stakeholder Management"],
        "target_roles": ["Business Analyst", "Data Analyst"],
        "locations": ["London"],
        "digest_enabled": True,
        "digest_threshold": 0,          # queue everything for AI
        "digest_llm_enabled": True,
        "digest_max_llm_per_run": 10,
        "digest_llm_rpm": 60,           # no real pacing delay in test
        "digest_llm_batch_size": 10,
    }), encoding="utf-8")
    return p


@contextmanager
def _server(tmp_path):
    profile_path = _write_profile(tmp_path)
    state = tmp_path / "state"
    ensure_storage_layout(state)
    config = UIServerConfig(profile_path=profile_path, state_root=state,
                            report_dir=tmp_path / "rep", host="127.0.0.1", port=0)
    handler = _build_handler(config)          # registers real reed/adzuna
    _register_fixture_reed()                  # then override "reed" with the fixture
    srv = ThreadingHTTPServer((config.host, config.port), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", config
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def _get(url):
    try:
        with urllib.request.urlopen(url) as r:
            body = r.read().decode("utf-8")
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def _get_json(url):
    st, body = _get(url)
    return st, json.loads(body)


def _post_json(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else b""
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def test_full_digest_journey(tmp_path, monkeypatch):
    # Deterministic, offline skill extraction + Gemini.
    monkeypatch.setattr(scheduler, "extract_skills_from_text",
                        lambda text: (["python", "sql"], ["dashboards"], None))
    monkeypatch.setattr(llm, "explain_job_match_with_llm",
                        lambda *a, **k: ({"fit": "Strong analyst fit", "risk": "Low",
                                          "action": "Apply", "model_used": "gemini-test"}, None))

    with _server(tmp_path) as (base, config):
        # 1) create a saved search (real create route validates source against enabled)
        st, body = _post_json(base + "/saved-searches",
                              {"name": "BA London", "source_id": "reed",
                               "params": {"keywords": "business analyst", "locationName": "London"}})
        assert st == 201, body
        sid = body["search"]["search_id"]

        # 2) it lists
        st, body = _get_json(base + "/saved-searches")
        assert st == 200 and [s["search_id"] for s in body["searches"]] == [sid]

        # 3) Run now → pipeline scores 2 new jobs, skips the blank-id one, queues for AI
        st, run = _post_json(base + f"/saved-searches/{sid}/run-now")
        assert st == 200 and run["ok"] is True, run
        assert run["jobs_new"] == 2, run
        assert run["jobs_skipped"] == 1, run          # blank source_job_id
        assert run["jobs_llm_queued"] == 2, run

        # 4) last_run recorded on the saved search
        st, body = _get_json(base + "/saved-searches")
        assert body["searches"][0]["last_run_count"] == 2

        # 5) digest feed page renders both jobs (escaped, internal links)
        st, html = _get(base + "/digest")
        assert st == 200
        assert "Business Analyst" in html and "Data Analyst" in html
        assert 'href="/job/reed-1001"' in html
        assert "https://www.reed.co.uk/jobs/1001" not in html   # external url NOT in feed

        # 6) badge count = 2 unseen
        st, body = _get_json(base + "/digest/count")
        assert body["unseen"] == 2

        # 7) filter by source + score
        st, html = _get(base + "/digest?source=reed")
        assert st == 200 and "Business Analyst" in html

        # 8) mark one seen → unseen drops to 1
        st, body = _post_json(base + "/digest/mark-seen", {"job_ids": ["reed-1001"]})
        assert st == 200 and body["marked"] == 1
        st, body = _get_json(base + "/digest/count")
        assert body["unseen"] == 1

        # 9) LLM queue has 2 pending before draining
        st, q = _get_json(base + "/digest/llm-queue")
        assert q["pending"] == 2 and q["done"] == 0

        # 10) drain the LLM batch → both enriched
        st, drained = _post_json(base + "/digest/run-llm-batch")
        assert st == 200 and drained["ok"] is True, drained
        assert drained["processed"] == 2, drained

        # 11) queue now shows done; analysis files enriched
        st, q = _get_json(base + "/digest/llm-queue")
        assert q["done"] == 2 and q["pending"] == 0
        assert q["rpd_used_today"] == 2
        a = load_job_analysis("reed-1001", config.state_root)
        assert a.llm_fit_summary == "Strong analyst fit" and a.llm_model == "gemini-test"

        # 12) digest page now shows the AI badge
        st, html = _get(base + "/digest")
        assert "AI: done" in html

        # 13) scheduler status endpoint responds (daemon not started in test server)
        st, body = _get_json(base + "/scheduler/status")
        assert st == 200 and "running" in body

        # 14) idempotency — a second Run now finds everything already-seen, no new jobs
        st, run2 = _post_json(base + f"/saved-searches/{sid}/run-now")
        assert run2["jobs_new"] == 0 and run2["jobs_already_seen"] == 2

        # 15) the [View] target must actually render — digest jobs have NO outcome
        #     record, which is the most likely integration break.
        st, html = _get(base + "/job/reed-1001")
        assert st == 200, f"/job/{{id}} for a digest job returned {st}"
        assert "Business Analyst" in html


def test_e2e_source_error_is_isolated(tmp_path, monkeypatch):
    """A search_handler that raises must not crash Run now — it returns errors."""
    monkeypatch.setattr(scheduler, "extract_skills_from_text",
                        lambda text: (["python"], [], None))
    with _server(tmp_path) as (base, config):
        st, body = _post_json(base + "/saved-searches",
                              {"name": "boom", "source_id": "reed", "params": {}})
        sid = body["search"]["search_id"]
        # override reed to raise on fetch
        register_boom()
        st, run = _post_json(base + f"/saved-searches/{sid}/run-now")
        assert st == 200 and run["ok"] is True
        assert run["jobs_new"] == 0 and run["errors"]


def test_e2e_xss_title_escaped_on_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "extract_skills_from_text",
                        lambda text: (["python"], [], None))
    payload = '<script>alert(1)</script>'
    with _server(tmp_path) as (base, config):
        register(JobSource(
            source_id="reed", display_name="x", is_available=lambda: True,
            normalize_search_params=lambda p: dict(p),
            search_handler=lambda params: [{
                "source": "reed", "source_job_id": "9", "title": payload,
                "company": payload, "location": payload,
                "description_raw": "python sql", "url": "https://x/9"}],
            select_handler=lambda f, c: {}, render_search_form=lambda v, e: "",
            render_results=lambda r, e, n, m=None: ""))
        st, body = _post_json(base + "/saved-searches", {"name": "x", "source_id": "reed", "params": {}})
        sid = body["search"]["search_id"]
        _post_json(base + f"/saved-searches/{sid}/run-now")
        st, html = _get(base + "/digest")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


def test_e2e_worker_rate_limited_requeues(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "extract_skills_from_text",
                        lambda text: (["python"], [], None))
    def _raise(*a, **k):
        raise llm.RateLimited("429")
    monkeypatch.setattr(llm, "explain_job_match_with_llm", _raise)
    with _server(tmp_path) as (base, config):
        st, body = _post_json(base + "/saved-searches", {"name": "x", "source_id": "reed", "params": {}})
        sid = body["search"]["search_id"]
        _post_json(base + f"/saved-searches/{sid}/run-now")
        st, q = _get_json(base + "/digest/llm-queue")
        assert q["pending"] == 2
        # drain → throttled → both requeued to pending (never dropped)
        st, drained = _post_json(base + "/digest/run-llm-batch")
        assert st == 200 and drained["processed"] == 0
        st, q = _get_json(base + "/digest/llm-queue")
        assert q["pending"] == 2 and q["done"] == 0


def register_boom():
    register(JobSource(
        source_id="reed", display_name="boom", is_available=lambda: True,
        normalize_search_params=lambda p: dict(p),
        search_handler=lambda params: (_ for _ in ()).throw(RuntimeError("api down")),
        select_handler=lambda f, c: {}, render_search_form=lambda v, e: "",
        render_results=lambda r, e, n, m=None: ""))
