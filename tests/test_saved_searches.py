"""Tests for Daily Job Digest phase D1 — Saved Searches (SQLite-backed).

Covers the design-council D1 review list: CRUD round-trip, opaque-uuid ids,
duplicate names both persist, idempotent toggle/delete, unknown-id behaviour,
search_id validation on every operation, params coercion/limits, corrupt-row
resilience, and concurrent writes.
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

from src.ui_state import UIServerConfig
from src.ui_routes import _build_handler

from src.job_hunt_saved_searches import (
    _MAX_PARAM_KEY_LEN,
    _MAX_PARAMS,
    SavedSearch,
    SavedSearchError,
    SavedSearchNotFound,
    create_saved_search,
    delete_saved_search,
    list_saved_searches,
    load_saved_search,
    save_saved_search,
    toggle_saved_search,
    update_last_run,
    validate_search_id,
)


# --------------------------------------------------------------------------- #
# Create / load / list round-trip
# --------------------------------------------------------------------------- #

def test_create_then_load_round_trip(tmp_path):
    s = create_saved_search(
        "BA roles, London", "reed", {"keywords": "business analyst", "location": "London"},
        state_root=tmp_path,
    )
    loaded = load_saved_search(s.search_id, state_root=tmp_path)
    assert loaded == s
    assert loaded.enabled is True
    assert loaded.params == {"keywords": "business analyst", "location": "London"}
    assert loaded.last_run_at is None
    assert loaded.last_run_count == 0


def test_search_id_is_opaque_uuid_hex(tmp_path):
    s = create_saved_search("X", "reed", {}, state_root=tmp_path)
    assert len(s.search_id) == 32
    assert s.search_id.isalnum()
    # uuid hex is never a slug of the name
    assert "ba" not in s.search_id or s.search_id != "x"


def test_list_newest_first(tmp_path):
    a = create_saved_search("A", "reed", {}, state_root=tmp_path)
    b = create_saved_search("B", "adzuna", {}, state_root=tmp_path)
    ids = [s.search_id for s in list_saved_searches(state_root=tmp_path)]
    assert set(ids) == {a.search_id, b.search_id}
    assert len(ids) == 2


def test_list_empty_when_none(tmp_path):
    assert list_saved_searches(state_root=tmp_path) == []


# --------------------------------------------------------------------------- #
# Duplicate names (the slug-collision bug the uuid PK fixes)
# --------------------------------------------------------------------------- #

def test_duplicate_names_both_persist(tmp_path):
    a = create_saved_search("Data Science", "reed", {}, state_root=tmp_path)
    b = create_saved_search("data-science", "reed", {}, state_root=tmp_path)
    assert a.search_id != b.search_id
    assert len(list_saved_searches(state_root=tmp_path)) == 2
    # neither overwrote the other
    assert load_saved_search(a.search_id, state_root=tmp_path).name == "Data Science"
    assert load_saved_search(b.search_id, state_root=tmp_path).name == "data-science"


# --------------------------------------------------------------------------- #
# Toggle (idempotent flip, not a fixed set)
# --------------------------------------------------------------------------- #

def test_toggle_flips_enabled(tmp_path):
    s = create_saved_search("X", "reed", {}, state_root=tmp_path)
    assert s.enabled is True
    t1 = toggle_saved_search(s.search_id, state_root=tmp_path)
    assert t1.enabled is False
    t2 = toggle_saved_search(s.search_id, state_root=tmp_path)
    assert t2.enabled is True


def test_toggle_unknown_id_raises_not_found(tmp_path):
    with pytest.raises(SavedSearchNotFound):
        toggle_saved_search("deadbeef", state_root=tmp_path)


# --------------------------------------------------------------------------- #
# Delete (idempotent)
# --------------------------------------------------------------------------- #

def test_delete_removes_row(tmp_path):
    s = create_saved_search("X", "reed", {}, state_root=tmp_path)
    assert delete_saved_search(s.search_id, state_root=tmp_path) is True
    assert list_saved_searches(state_root=tmp_path) == []
    with pytest.raises(SavedSearchNotFound):
        load_saved_search(s.search_id, state_root=tmp_path)


def test_delete_unknown_id_is_idempotent(tmp_path):
    assert delete_saved_search("deadbeef", state_root=tmp_path) is False


# --------------------------------------------------------------------------- #
# load unknown id
# --------------------------------------------------------------------------- #

def test_load_unknown_id_raises_not_found(tmp_path):
    with pytest.raises(SavedSearchNotFound):
        load_saved_search("deadbeef", state_root=tmp_path)


# --------------------------------------------------------------------------- #
# update_last_run
# --------------------------------------------------------------------------- #

def test_update_last_run(tmp_path):
    s = create_saved_search("X", "reed", {}, state_root=tmp_path)
    update_last_run(s.search_id, state_root=tmp_path, count=8)
    loaded = load_saved_search(s.search_id, state_root=tmp_path)
    assert loaded.last_run_count == 8
    assert loaded.last_run_at is not None


# --------------------------------------------------------------------------- #
# validate_search_id — applied on EVERY operation (input hygiene)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", [
    "../etc/passwd", "..", ".", "a/b", "a\\b", "", " ", "x" * 65,
    "a b", "id;DROP", "%2e%2e", None, 123,
])
def test_validate_search_id_rejects_bad(bad):
    with pytest.raises(SavedSearchError):
        validate_search_id(bad)


@pytest.mark.parametrize("op", ["load", "delete", "toggle"])
def test_malformed_id_rejected_on_every_op(tmp_path, op):
    bad = "../etc/passwd"
    with pytest.raises(SavedSearchError):
        if op == "load":
            load_saved_search(bad, state_root=tmp_path)
        elif op == "delete":
            delete_saved_search(bad, state_root=tmp_path)
        else:
            toggle_saved_search(bad, state_root=tmp_path)


def test_validate_search_id_accepts_uuid_hex(tmp_path):
    s = create_saved_search("X", "reed", {}, state_root=tmp_path)
    assert validate_search_id(s.search_id) == s.search_id


# --------------------------------------------------------------------------- #
# Input validation: name, source_id, params
# --------------------------------------------------------------------------- #

def test_blank_name_rejected(tmp_path):
    with pytest.raises(SavedSearchError):
        create_saved_search("   ", "reed", {}, state_root=tmp_path)


def test_overlong_name_rejected(tmp_path):
    with pytest.raises(SavedSearchError):
        create_saved_search("x" * 201, "reed", {}, state_root=tmp_path)


def test_blank_source_id_rejected(tmp_path):
    with pytest.raises(SavedSearchError):
        create_saved_search("X", "  ", {}, state_root=tmp_path)


def test_source_id_lowercased(tmp_path):
    s = create_saved_search("X", "Reed", {}, state_root=tmp_path)
    assert s.source_id == "reed"


def test_valid_lowercase_source_id_accepted(tmp_path):
    s = create_saved_search("X", "reed", {}, state_root=tmp_path)
    assert s.source_id == "reed"


def test_create_saved_search_rejects_unregistered_source_id(tmp_path):
    with pytest.raises(SavedSearchError):
        create_saved_search("X", "indeed", {}, state_root=tmp_path)
    assert not (tmp_path / "job_hunt_index.db").exists()


@pytest.mark.parametrize("bad_source_id", ["bad/source", "with space", "../x", "id;drop"])
def test_create_saved_search_rejects_charset_invalid_source_id(tmp_path, bad_source_id):
    with pytest.raises(SavedSearchError):
        create_saved_search("X", bad_source_id, {}, state_root=tmp_path)
    assert not (tmp_path / "job_hunt_index.db").exists()


def test_non_mapping_params_rejected(tmp_path):
    with pytest.raises(SavedSearchError):
        create_saved_search("X", "reed", ["not", "a", "dict"], state_root=tmp_path)


def test_params_values_coerced_to_str(tmp_path):
    s = create_saved_search("X", "reed", {"distance": 10, "remote": True}, state_root=tmp_path)
    assert s.params == {"distance": "10", "remote": "True"}


def test_params_defensively_copied(tmp_path):
    src = {"keywords": "ba"}
    s = create_saved_search("X", "reed", src, state_root=tmp_path)
    src["keywords"] = "mutated"
    assert s.params == {"keywords": "ba"}  # not aliased to caller's dict


def _hand_built_saved_search(**overrides):
    fields = {
        "search_id": "abc123",
        "name": "Hand built",
        "source_id": "reed",
        "params": {"keywords": "ba"},
        "enabled": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_run_at": None,
        "last_run_count": 0,
    }
    fields.update(overrides)
    return SavedSearch(**fields)


def test_save_saved_search_rejects_hand_built_invalid_name_without_write(tmp_path):
    search = _hand_built_saved_search(name="   ")
    with pytest.raises(SavedSearchError):
        save_saved_search(search, state_root=tmp_path)
    assert not (tmp_path / "job_hunt_index.db").exists()


@pytest.mark.parametrize("bad_source_id", ["", "x" * 41, "bad/source", "with space", "../x", "id;drop"])
def test_save_saved_search_rejects_hand_built_invalid_source_id(tmp_path, bad_source_id):
    search = _hand_built_saved_search(source_id=bad_source_id)
    with pytest.raises(SavedSearchError):
        save_saved_search(search, state_root=tmp_path)
    assert not (tmp_path / "job_hunt_index.db").exists()


def test_save_saved_search_rejects_hand_built_unregistered_source_id(tmp_path):
    search = _hand_built_saved_search(source_id="indeed")
    with pytest.raises(SavedSearchError):
        save_saved_search(search, state_root=tmp_path)
    assert not (tmp_path / "job_hunt_index.db").exists()


@pytest.mark.parametrize("bad_params", [
    ["not", "a", "mapping"],
    {"q": "x" * 501},
    {f"k{i}": "v" for i in range(_MAX_PARAMS + 1)},
    {123: "v"},
    {"   ": "v"},
    {"x" * (_MAX_PARAM_KEY_LEN + 1): "v"},
])
def test_save_saved_search_rejects_hand_built_invalid_params(tmp_path, bad_params):
    search = _hand_built_saved_search(params=bad_params)
    with pytest.raises(SavedSearchError):
        save_saved_search(search, state_root=tmp_path)
    assert not (tmp_path / "job_hunt_index.db").exists()


def test_save_saved_search_accepts_valid_hand_built_search(tmp_path):
    search = _hand_built_saved_search()
    save_saved_search(search, state_root=tmp_path)
    assert load_saved_search(search.search_id, state_root=tmp_path) == search


# --------------------------------------------------------------------------- #
# Resilience: a corrupt params blob must not crash the whole list
# --------------------------------------------------------------------------- #

def test_corrupt_params_blob_does_not_crash_list(tmp_path):
    good = create_saved_search("good", "reed", {"k": "v"}, state_root=tmp_path)
    # hand-corrupt one row's params directly in the DB
    db = tmp_path / "job_hunt_index.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO saved_searches (search_id, name, source_id, params, enabled, created_at, last_run_count) "
        "VALUES ('bad0', 'bad', 'reed', '{not json', 1, '2026-01-01T00:00:00', 0)"
    )
    conn.commit()
    conn.close()
    items = list_saved_searches(state_root=tmp_path)
    assert len(items) == 2
    bad = next(s for s in items if s.search_id == "bad0")
    assert bad.params == {}  # degraded, not crashed
    assert next(s for s in items if s.search_id == good.search_id).params == {"k": "v"}


# --------------------------------------------------------------------------- #
# Concurrency: parallel creates do not corrupt or lose rows
# --------------------------------------------------------------------------- #

def test_concurrent_creates_all_persist(tmp_path):
    n = 20
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            create_saved_search(f"s{i}", "reed", {"i": str(i)}, state_root=tmp_path)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(list_saved_searches(state_root=tmp_path)) == n


# --------------------------------------------------------------------------- #
# Route integration (GET/POST through the real dispatch + server)
# --------------------------------------------------------------------------- #

@contextmanager
def _server(tmp_path):
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


def test_route_create_list_toggle_delete_flow(tmp_path):
    with _server(tmp_path) as base:
        status, body = _req(base + "/saved-searches", method="POST",
                            body={"name": "BA London", "source_id": "reed",
                                  "params": {"keywords": "business analyst"}})
        assert status == 201 and body["ok"] is True
        sid = body["search"]["search_id"]

        status, body = _req(base + "/saved-searches")
        assert status == 200
        assert [s["search_id"] for s in body["searches"]] == [sid]
        assert body["searches"][0]["enabled"] is True

        status, body = _req(base + f"/saved-searches/{sid}/toggle", method="POST")
        assert status == 200 and body["enabled"] is False

        status, body = _req(base + f"/saved-searches/{sid}/delete", method="POST")
        assert status == 200 and body["deleted"] is True

        status, body = _req(base + "/saved-searches")
        assert body["searches"] == []


def test_route_create_invalid_falsy_params_400(tmp_path):
    # [] and "" are falsy but invalid — must be rejected, not coerced to {}
    with _server(tmp_path) as base:
        for bad in ([], ""):
            status, body = _req(base + "/saved-searches", method="POST",
                                body={"name": "X", "source_id": "reed", "params": bad})
            assert status == 400, f"params={bad!r} should 400"


def test_route_create_unknown_source_400(tmp_path):
    with _server(tmp_path) as base:
        status, body = _req(base + "/saved-searches", method="POST",
                            body={"name": "X", "source_id": "monster"})
        assert status == 400 and body["ok"] is False


def test_route_create_malformed_json_400(tmp_path):
    with _server(tmp_path) as base:
        request = urllib.request.Request(
            base + "/saved-searches", data=b"{not json",
            method="POST", headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(request)
            assert False, "expected 400"
        except urllib.error.HTTPError as exc:
            assert exc.code == 400


def test_route_delete_unknown_id_404(tmp_path):
    with _server(tmp_path) as base:
        status, _ = _req(base + "/saved-searches/abc123/delete", method="POST")
        assert status == 404


def test_route_toggle_unknown_id_404(tmp_path):
    with _server(tmp_path) as base:
        status, _ = _req(base + "/saved-searches/abc123/toggle", method="POST")
        assert status == 404


def test_route_malformed_id_does_not_match_single_segment(tmp_path):
    # "../state" contains a slash, so the single-segment route never matches → 404
    with _server(tmp_path) as base:
        status, _ = _req(base + "/saved-searches/..%2Fstate/delete", method="POST")
        assert status in (400, 404)


def test_profile_page_renders_saved_searches_section(tmp_path):
    with _server(tmp_path) as base:
        request = urllib.request.Request(base + "/profile", method="GET")
        with urllib.request.urlopen(request) as resp:
            html_text = resp.read().decode("utf-8")
    assert "Saved Searches" in html_text
    assert 'id="saved-searches-list"' in html_text
    # source dropdown is populated from the enabled-sources registry
    assert 'value="reed"' in html_text
