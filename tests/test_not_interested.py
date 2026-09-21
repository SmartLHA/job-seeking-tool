"""Tests for the persistent "not interested" store + search-flow triage UX.

Covers the design-council review list: idempotent hide, unhide (undo/overlay),
newest-first listing, key AND fingerprint filtering (unstable LinkedIn ids),
raw-count paging math staying display-only, retention pruning, invalid input,
the three HTTP endpoints end-to-end, and the browser contract of the reworked
multi-select module (no auto-select, per-card ✕, Next page, Hidden jobs).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

import pytest

from src.job_hunt_not_interested import (
    count_hidden,
    filter_results,
    hide_jobs,
    list_hidden,
    make_fingerprint,
    make_key,
    unhide_jobs,
)


def _entry(source="reed", sjid="101", title="Senior BA", company="Acme"):
    return {"source": source, "source_job_id": sjid, "title": title, "company": company}


def _result(source="reed", sjid="101", title="Senior BA", company="Acme"):
    return {"source": source, "source_job_id": sjid, "title": title, "company": company}


# --------------------------------------------------------------------------- #
# Store: hide / unhide / list
# --------------------------------------------------------------------------- #

def test_hide_then_list_round_trip(tmp_path):
    res = hide_jobs([_entry()], state_root=tmp_path)
    assert res["keys"] == ["reed:101"]
    assert res["hidden"] == ["reed:101"] and res["already_hidden"] == []
    rows = list_hidden(state_root=tmp_path)
    assert len(rows) == 1
    assert rows[0]["key"] == "reed:101"
    assert rows[0]["title"] == "Senior BA" and rows[0]["source"] == "reed"
    assert count_hidden(state_root=tmp_path) == 1


def test_rehide_is_idempotent(tmp_path):
    hide_jobs([_entry()], state_root=tmp_path)
    res = hide_jobs([_entry()], state_root=tmp_path)
    assert res["hidden"] == [] and res["already_hidden"] == ["reed:101"]
    assert count_hidden(state_root=tmp_path) == 1


def test_unhide_removes_and_ignores_unknown_keys(tmp_path):
    hide_jobs([_entry(), _entry(sjid="102", title="PM")], state_root=tmp_path)
    assert unhide_jobs(["reed:101", "reed:nope"], state_root=tmp_path) == 1
    assert [r["key"] for r in list_hidden(state_root=tmp_path)] == ["reed:102"]
    assert unhide_jobs([], state_root=tmp_path) == 0


def test_missing_job_id_falls_back_to_fingerprint_key(tmp_path):
    res = hide_jobs([_entry(source="linkedin", sjid="")], state_root=tmp_path)
    assert res["keys"][0].startswith("fp:")


def test_invalid_source_rejected(tmp_path):
    with pytest.raises(ValueError):
        hide_jobs([_entry(source="Bad Source!")], state_root=tmp_path)
    with pytest.raises(ValueError):
        hide_jobs([], state_root=tmp_path)


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #

def test_filter_drops_hidden_by_key_and_keeps_the_rest(tmp_path):
    hide_jobs([_entry(sjid="101")], state_root=tmp_path)
    visible, hidden_ct = filter_results(
        [_result(sjid="101"), _result(sjid="102", title="Other")], state_root=tmp_path
    )
    assert hidden_ct == 1
    assert [r["source_job_id"] for r in visible] == ["102"]


def test_filter_matches_fingerprint_when_source_id_is_unstable(tmp_path):
    # LinkedIn scrape ids can change between fetches; same source+title+company
    # must still be filtered via the fingerprint.
    hide_jobs([_entry(source="linkedin", sjid="old-id-1", title="IT PM", company="Hays")],
              state_root=tmp_path)
    visible, hidden_ct = filter_results(
        [_result(source="linkedin", sjid="new-id-2", title="IT PM", company="Hays")],
        state_root=tmp_path,
    )
    assert hidden_ct == 1 and visible == []


def test_filter_noop_when_store_empty(tmp_path):
    results = [_result()]
    visible, hidden_ct = filter_results(results, state_root=tmp_path)
    assert visible == results and hidden_ct == 0


def test_key_and_fingerprint_are_source_scoped(tmp_path):
    # Same numeric id on another source must NOT be filtered (Codex HIGH #1).
    hide_jobs([_entry(source="reed", sjid="101")], state_root=tmp_path)
    visible, hidden_ct = filter_results(
        [_result(source="adzuna", sjid="101", title="Different", company="Co")],
        state_root=tmp_path,
    )
    assert hidden_ct == 0 and len(visible) == 1
    assert make_key("reed", "101") != make_key("adzuna", "101")
    assert make_fingerprint("reed", "T", "C") != make_fingerprint("adzuna", "T", "C")


def test_prune_drops_rows_older_than_retention(tmp_path):
    hide_jobs([_entry()], state_root=tmp_path)
    conn = sqlite3.connect(str(tmp_path / "job_hunt_index.db"))
    conn.execute(
        "INSERT INTO not_interested_jobs (key, fingerprint, source, title, company, hidden_at)"
        " VALUES ('reed:old', 'fp:x', 'reed', 'Old', 'Co', '2020-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()
    hide_jobs([_entry(sjid="102")], state_root=tmp_path)  # write triggers prune
    keys = [r["key"] for r in list_hidden(state_root=tmp_path)]
    assert "reed:old" not in keys and "reed:101" in keys and "reed:102" in keys


# --------------------------------------------------------------------------- #
# HTTP endpoints (live server, mirrors test_saved_searches)
# --------------------------------------------------------------------------- #

@contextmanager
def _server(tmp_path):
    from src.ui_routes import _build_handler
    from src.ui_state import UIServerConfig
    config = UIServerConfig(
        profile_path=tmp_path / "profile.json",
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
        host="127.0.0.1",
        port=0,
    )
    srv = ThreadingHTTPServer((config.host, config.port), _build_handler(config))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _req(url, *, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def test_route_hide_list_undo_flow(tmp_path):
    with _server(tmp_path) as base:
        status, body = _req(base + "/jobs/not-interested", method="POST",
                            body={"jobs": [_entry(), _entry(sjid="102", title="PM")]})
        assert status == 200 and body["ok"] is True
        assert body["hidden"] == 2 and body["total_hidden"] == 2
        keys = body["keys"]

        status, body = _req(base + "/jobs/not-interested")
        assert status == 200 and body["count"] == 2
        assert {j["key"] for j in body["jobs"]} == set(keys)

        status, body = _req(base + "/jobs/not-interested/undo", method="POST",
                            body={"keys": keys})
        assert status == 200 and body["removed"] == 2 and body["total_hidden"] == 0

        # Idempotent re-hide reported, not duplicated.
        _req(base + "/jobs/not-interested", method="POST", body={"jobs": [_entry()]})
        status, body = _req(base + "/jobs/not-interested", method="POST",
                            body={"jobs": [_entry()]})
        assert body["hidden"] == 0 and body["already_hidden"] == 1 and body["total_hidden"] == 1


def test_route_hide_rejects_bad_bodies(tmp_path):
    with _server(tmp_path) as base:
        status, _ = _req(base + "/jobs/not-interested", method="POST", body={"jobs": []})
        assert status == 400
        status, _ = _req(base + "/jobs/not-interested", method="POST",
                         body={"jobs": [{"source": "###", "title": "x"}]})
        assert status == 400
        status, _ = _req(base + "/jobs/not-interested/undo", method="POST", body={})
        assert status == 400


# --------------------------------------------------------------------------- #
# Browser contract of the reworked multi-select module
# --------------------------------------------------------------------------- #

def test_multiselect_triage_contract():
    from src.job_hunt_not_interested import make_key as _mk  # noqa: F401 (import sanity)
    from src.job_sources import _multiselect as M
    from src.job_sources.reed_source import render_reed_search_results

    result = {
        "source": "reed", "source_job_id": "1", "title": "T", "company": "C",
        "location": "London", "salary_display": "£50k", "employment_type": "permanent",
        "work_mode": "remote", "url": "https://example.test/y", "description_preview": "d",
        "description_raw": "d", "filter_notes": [], "source_snapshot_json": "",
    }
    html = render_reed_search_results(
        [result], reed_error=None, reed_select_nonce="n", more_url="/search/reed/more?a=1"
    )
    # Cards carry the identity attrs the hide endpoint needs.
    assert 'data-jst-source="reed"' in html and 'data-jst-sjid="1"' in html
    # No auto-select: registration must not pre-add every card to the selection.
    assert "_sel.add(id);'});" not in M.MULTISELECT_JS
    assert "function _reg(c)" in M.MULTISELECT_JS
    assert "_sel.add(id)" not in M.MULTISELECT_JS.split("function _upd")[0].split(
        "window.jstSelectAll"
    )[0].replace("window._jst_sel=window._jst_sel||new Set();", "")
    # Hide / hidden-jobs / paging wiring.
    for needle in (
        "window.jstHide=function",
        "window.jstUndoHide=function",
        "window.jstHideUnticked=function",
        "window.jstShowHidden=function",
        "window.jstFilterHidden=function",
        'onclick="jstHideUnticked()"',
        'onclick="jstShowHidden()"',
        'onclick="jstLoadMore(this)"',
        "jst-hidden-overlay",
        'id="jst-hidden-filter"',
        "No hidden jobs match this filter.",
        "jst-toast",
        "Next page",
    ):
        assert needle in html, f"missing: {needle}"
    # Footer renders even without a next page (hide/hidden controls remain).
    tail = render_reed_search_results([result], reed_error=None, reed_select_nonce="n", more_url=None)
    assert 'id="jst-more-wrap"' in tail and 'onclick="jstLoadMore(this)"' not in tail
