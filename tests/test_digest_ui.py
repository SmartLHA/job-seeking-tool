"""Tests for Daily Job Digest phase D4 — feed UI, filters, mark-seen, XSS escaping."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

import pytest

from src.job_hunt_index import open_db, set_digest_meta, set_llm_status, upsert_job
from src.job_hunt_digest import DigestEntry, mark_all_seen, query_digest, unseen_count
from src.ui_render import render_digest_page
from src.ui_state import UIServerConfig
from src.ui_routes import _build_handler


def _db(tmp_path):
    return tmp_path / "job_hunt_index.db"


def _row(job_id, source, sjid, score=80, ssid=None, **kw):
    base = {"job_id": job_id, "job_title": "BA", "company": "Co", "location": "London",
            "source": source, "source_job_id": sjid, "apply_url": f"https://x/{sjid}",
            "match_score": score, "decision": "apply", "status": "not_applied"}
    base.update(kw)
    return base, ssid


def _seed(db, job_id, source="reed", sjid="1", score=80, ssid="ss-1", date="2026-06-24"):
    row, _ = _row(job_id, source, sjid, score=score)
    upsert_job(db, row)
    set_digest_meta(db, job_id, digest_date=date, saved_search_id=ssid)


# --------------------------------------------------------------------------- #
# Extended query filters
# --------------------------------------------------------------------------- #

def test_query_filter_by_source(tmp_path):
    db = _db(tmp_path)
    _seed(db, "reed-1", "reed", "1")
    _seed(db, "adzuna-1", "adzuna", "1")
    assert {e.job_id for e in query_digest(db_path=db, source_id="reed")} == {"reed-1"}


def test_query_filter_by_saved_search(tmp_path):
    db = _db(tmp_path)
    _seed(db, "reed-1", "reed", "1", ssid="ss-a")
    _seed(db, "reed-2", "reed", "2", ssid="ss-b")
    assert {e.job_id for e in query_digest(db_path=db, saved_search_id="ss-b")} == {"reed-2"}


def test_query_filter_seen_states(tmp_path):
    db = _db(tmp_path)
    _seed(db, "reed-1", "reed", "1")
    _seed(db, "reed-2", "reed", "2")
    from src.job_hunt_digest import mark_seen
    mark_seen(["reed-1"], db_path=db)
    assert {e.job_id for e in query_digest(db_path=db, seen=False)} == {"reed-2"}
    assert {e.job_id for e in query_digest(db_path=db, seen=True)} == {"reed-1"}
    assert len(query_digest(db_path=db, seen=None)) == 2


def test_query_entry_has_llm_status(tmp_path):
    db = _db(tmp_path)
    _seed(db, "reed-1", "reed", "1")
    set_llm_status(db, "reed-1", "pending")
    assert query_digest(db_path=db)[0].llm_status == "pending"


def test_mark_all_seen_scoped_to_filter(tmp_path):
    db = _db(tmp_path)
    _seed(db, "reed-1", "reed", "1", ssid="ss-a")
    _seed(db, "reed-2", "reed", "2", ssid="ss-b")
    # only mark the ss-a one
    assert mark_all_seen(db_path=db, saved_search_id="ss-a") == 1
    assert unseen_count(db_path=db) == 1


# --------------------------------------------------------------------------- #
# Render: XSS escaping + internal-only View link
# --------------------------------------------------------------------------- #

def _entry(**kw):
    base = dict(job_id="reed-1", title="BA", company="Co", match_score=80, decision="apply",
                source_id="reed", saved_search_id="ss-1", digest_date="2026-06-24", seen=False,
                salary_display="£50k", location="London", url="https://x/1", llm_status=None)
    base.update(kw)
    return DigestEntry(**base)


def test_render_escapes_hostile_external_text():
    payload = '<img src=x onerror=alert(1)>'
    html = render_digest_page(entries=[_entry(title=payload, company=payload, location=payload)],
                              filters={}, sources=["Reed"], saved_searches=[])
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_render_does_not_emit_external_apply_url():
    html = render_digest_page(entries=[_entry(url="javascript:alert(1)")],
                              filters={}, sources=["Reed"], saved_searches=[])
    assert "javascript:alert(1)" not in html
    # View links go to the internal job route only
    assert 'href="/job/reed-1"' in html


def test_render_empty_states_differ():
    no_jobs = render_digest_page(entries=[], filters={}, sources=["Reed"], saved_searches=[])
    assert "No digest jobs yet" in no_jobs
    no_match = render_digest_page(entries=[], filters={"source": "reed"}, sources=["Reed"], saved_searches=[])
    assert "No jobs match these filters" in no_match


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@contextmanager
def _server(tmp_path):
    config = UIServerConfig(profile_path=tmp_path / "p.json", state_root=tmp_path / "state",
                            report_dir=tmp_path / "rep", host="127.0.0.1", port=0)
    srv = ThreadingHTTPServer((config.host, config.port), _build_handler(config))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", config
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def _post(url, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_route_get_digest_renders(tmp_path):
    with _server(tmp_path) as (base, config):
        db = config.state_root / "job_hunt_index.db"
        _seed(db, "reed-1", "reed", "1")
        with urllib.request.urlopen(base + "/digest") as r:
            html = r.read().decode()
        assert "Daily Digest" in html and 'href="/job/reed-1"' in html


def test_route_mark_seen_modes(tmp_path):
    with _server(tmp_path) as (base, config):
        db = config.state_root / "job_hunt_index.db"
        _seed(db, "reed-1", "reed", "1")
        _seed(db, "reed-2", "reed", "2")
        # job_ids mode
        st, body = _post(base + "/digest/mark-seen", {"job_ids": ["reed-1"]})
        assert st == 200 and body["marked"] == 1
        # both modes → 400
        st, _ = _post(base + "/digest/mark-seen", {"all": True, "job_ids": ["reed-2"]})
        assert st == 400
        # non-list job_ids → 400
        st, _ = _post(base + "/digest/mark-seen", {"job_ids": "reed-2"})
        assert st == 400
        # all mode marks the rest
        st, body = _post(base + "/digest/mark-seen", {"all": True})
        assert st == 200 and body["marked"] == 1


def test_route_mark_seen_strict_validation(tmp_path):
    with _server(tmp_path) as (base, config):
        db = config.state_root / "job_hunt_index.db"
        _seed(db, "reed-1", "reed", "1")
        # {all:false} → 400 (not a valid mode)
        assert _post(base + "/digest/mark-seen", {"all": False})[0] == 400
        # neither mode → 400
        assert _post(base + "/digest/mark-seen", {})[0] == 400
        # all-mode with invalid date must NOT widen scope → 400
        assert _post(base + "/digest/mark-seen", {"all": True, "date": "2026-99-99"})[0] == 400
        # all-mode with unknown source → 400
        assert _post(base + "/digest/mark-seen", {"all": True, "source": "hacker"})[0] == 400
        # non-string job_ids → 400
        assert _post(base + "/digest/mark-seen", {"job_ids": [1, {}]})[0] == 400
        # the row is still unseen (none of the bad requests marked anything)
        assert unseen_count(db_path=db) == 1


def test_route_mark_seen_oversized_400(tmp_path):
    with _server(tmp_path) as (base, config):
        st, _ = _post(base + "/digest/mark-seen", {"job_ids": [f"j{i}" for i in range(501)]})
        assert st == 400


def test_route_digest_invalid_filters_ignored(tmp_path):
    with _server(tmp_path) as (base, config):
        db = config.state_root / "job_hunt_index.db"
        _seed(db, "reed-1", "reed", "1")
        # garbage date + unknown source should not 500; page still renders
        with urllib.request.urlopen(base + "/digest?date=notadate&source=hacker") as r:
            assert r.status == 200
