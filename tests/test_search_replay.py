"""Synthetic handler/state regressions for atomic, bounded More-page replay."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qsl, urlsplit

import pytest

from src import ui_handlers
from src.job_sources import search_state as state
from src.job_sources.reed_source import normalize_reed_search_params
from src.ui_state import UIServerConfig


def job(key, **fields):
    return {"source": "reed", "source_job_id": key, "title": "Synthetic " + key,
            "company": "Company " + key, "location": "Test", **fields}


def query_from(url):
    return dict(parse_qsl(urlsplit(url).query))


@pytest.fixture(autouse=True)
def clean_searches():
    state._reset_for_tests()
    yield
    state._reset_for_tests()


@pytest.fixture
def search_env(tmp_path, monkeypatch):
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"candidate_id": "synthetic"}))
    config = UIServerConfig(profile_path=profile, state_root=tmp_path / "state", report_dir=tmp_path / "reports")
    calls, captured, raw = [], [], []

    def fetch(values):
        calls.append(dict(values))
        rows = [job(values["keywords"] + values["resultsSkip"])]
        raw[:] = rows
        return rows

    def fragment(rows, *, skip, nonce):
        return json.dumps([row["source_job_id"] for row in rows]) + ":" + str(nonce)

    source = SimpleNamespace(source_id="reed", display_name="Synthetic",
        normalize_search_params=normalize_reed_search_params,
        search_handler=fetch, render_cards_fragment=fragment)
    monkeypatch.setattr("src.job_sources.source_registry.get_source", lambda _: source)
    monkeypatch.setattr("src.job_sources.relevance.bucket_jobs_by_relevance", lambda rows, _: (rows, []))
    monkeypatch.setattr(ui_handlers, "render_home", lambda *args, **kw: (captured.append(kw) or "Prepared HTML"))
    env = SimpleNamespace(config=config, source=source, calls=calls, captured=captured, raw=raw)

    def initial(**params):
        responder = Mock()
        ui_handlers.handle_source_search(SimpleNamespace(query={"keywords": "Analyst", "resultsToTake": "1", **params}), config, responder, "reed")
        env.query = query_from(captured[-1]["search_values"]["_more_url"])
        return responder

    def more(query=None, responder=None, config_override=None, source_id="reed"):
        responder = responder or Mock()
        ui_handlers.handle_source_search_more(SimpleNamespace(query=query or env.query), config_override or config, responder, source_id)
        return responder

    env.initial, env.more = initial, more
    return env


def test_lost_send_and_concurrent_retry_replay_exact_response(search_env):
    env = search_env
    env.initial()
    sent = []

    def lose(payload):
        sent.append(copy.deepcopy(payload))
        raise ConnectionError("Synthetic lost response")

    with pytest.raises(ConnectionError):
        env.more(responder=SimpleNamespace(send_json=lose))
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: env.more().send_json.call_args.args[0], range(4)))
    assert responses == [sent[0]] * 4
    assert len(env.calls) == 2
    assert responses[0]["cards_html"] and responses[0]["next_url"]
    # Neither caller mutation nor later adapter mutation can alter the replay.
    responses[0]["cards_html"] = "caller changed"
    env.raw[0]["title"] = "adapter changed"
    assert env.more().send_json.call_args.args[0] == sent[0]
    assert state._STATE[env.query["searchId"]]["seen"][-1]["title"] != "adapter changed"


def test_concurrent_first_preparation_fetches_once(search_env):
    env = search_env
    env.initial()
    entered, release = threading.Event(), threading.Event()
    original = env.source.search_handler

    def fetch(values):
        entered.set()
        assert release.wait(5)
        return original(values)

    env.source.search_handler = fetch
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(env.more)
        assert entered.wait(5)
        others = [pool.submit(env.more) for _ in range(2)]
        release.set()
        payloads = [future.result(5).send_json.call_args.args[0] for future in [first, *others]]
    assert payloads == [payloads[0]] * 3 and len(env.calls) == 2


@pytest.mark.parametrize("failure", ["source", "main-render", "other-render", "serialization"])
def test_failed_preparation_consumes_nothing_and_retry_keeps_card(search_env, monkeypatch, failure):
    env = search_env
    env.initial()
    sid = env.query["searchId"]
    before = copy.deepcopy(state._STATE[sid]["seen"])
    fetch, render = env.source.search_handler, env.source.render_cards_fragment

    def fail(*args, **kwargs):
        raise ValueError("Synthetic preparation failure")

    if failure == "source":
        env.source.search_handler = fail
    elif failure == "main-render":
        env.source.render_cards_fragment = fail
    elif failure == "other-render":
        monkeypatch.setattr(ui_handlers, "_render_other_results_fragment", fail)
    else:
        env.source.render_cards_fragment = lambda *args, **kwargs: {"not JSON serializable"}
    payload = env.more().send_json.call_args.args[0]
    assert payload["ok"] is False and "restart_required" not in payload
    assert state._STATE[sid]["seen"] == before
    assert state._STATE[sid]["replays"] == {}
    env.source.search_handler, env.source.render_cards_fragment = fetch, render
    monkeypatch.undo()
    # Restore fixture wiring removed by undo, including its synthetic renderer.
    monkeypatch.setattr("src.job_sources.source_registry.get_source", lambda _: env.source)
    monkeypatch.setattr("src.job_sources.relevance.bucket_jobs_by_relevance", lambda rows, _: (rows, []))
    result = env.more().send_json.call_args.args[0]
    assert result["ok"] is True and "Analyst1" in result["cards_html"]


def test_initial_render_failure_and_source_failure_do_not_seed(search_env, monkeypatch):
    env = search_env
    monkeypatch.setattr(ui_handlers, "render_home", Mock(side_effect=ValueError("Synthetic render failure")))
    with pytest.raises(ValueError, match="render failure"):
        env.initial()
    assert not state._STATE
    env.source.search_handler = Mock(side_effect=ValueError("Synthetic source failure"))
    renderer = Mock(return_value="Error HTML")
    monkeypatch.setattr(ui_handlers, "render_home", renderer)
    ui_handlers.handle_source_search(SimpleNamespace(query={"keywords": "Analyst"}), env.config, Mock(), "reed")
    assert not state._STATE and "search failed" in renderer.call_args.kwargs["reed_error"]


@pytest.mark.parametrize("change", ["query", "exclude", "source", "profile-id", "profile-path", "state-root", "hidden"])
def test_search_binding_changes_require_restart_before_fetch(search_env, change):
    from src.job_hunt_not_interested import hide_jobs
    env = search_env
    env.initial()
    query, config, source_id = dict(env.query), env.config, "reed"
    if change == "query":
        query["keywords"] = "Different"
    elif change == "exclude":
        query["excludeKeywords"] = "Director"
    elif change == "source":
        source_id = "adzuna"
    elif change == "profile-id":
        config.profile_path.write_text(json.dumps({"candidate_id": "different"}))
    elif change in {"profile-path", "state-root"}:
        config = copy.copy(config)
        if change == "profile-path":
            new_profile = config.profile_path.with_name("other-profile.json")
            new_profile.write_bytes(config.profile_path.read_bytes())
            object.__setattr__(config, "profile_path", new_profile)
        else:
            object.__setattr__(config, "state_root", config.state_root.with_name("other-state"))
    else:
        hide_jobs([job("hidden")], state_root=config.state_root)
    response = env.more(query, config_override=config, source_id=source_id).send_json.call_args
    assert response.kwargs["status"] == 409
    assert response.args[0]["restart_required"] is True
    assert response.args[0]["restart_url"].startswith("/search/" + source_id + "?")
    assert "searchId=" not in response.args[0]["restart_url"] and len(env.calls) == 1


@pytest.mark.parametrize("change", ["profile", "hidden"])
def test_binding_change_during_prepare_does_not_commit(search_env, change):
    from src.job_hunt_not_interested import hide_jobs
    env = search_env
    env.initial()
    original = env.source.render_cards_fragment

    def mutate(rows, **kwargs):
        if change == "profile":
            env.config.profile_path.write_text(json.dumps({"candidate_id": "changed"}))
        else:
            hide_jobs([job("hidden")], state_root=env.config.state_root)
        return original(rows, **kwargs)

    env.source.render_cards_fragment = mutate
    response = env.more().send_json.call_args
    assert response.kwargs["status"] == 409
    entry = state._STATE[env.query["searchId"]]
    assert len(entry["seen"]) == 1 and entry["replays"] == {}


def test_both_buckets_dedup_atomically_and_successor_filters_seen(search_env, monkeypatch):
    env = search_env
    env.initial()
    env.source.search_handler = lambda values: [job("new"), job("other"), job("new")]
    monkeypatch.setattr("src.job_sources.relevance.bucket_jobs_by_relevance", lambda rows, _: (rows[:1], rows[1:]))
    monkeypatch.setattr(ui_handlers, "_render_other_results_fragment", lambda source, rows, **kw: json.dumps([row["source_job_id"] for row in rows]))
    payload = env.more().send_json.call_args.args[0]
    assert payload["visible_count"] == 2 and payload["other_results_html"] == '["other"]'
    assert env.more(query_from(payload["next_url"])).send_json.call_args.args[0]["visible_count"] == 0


def test_hidden_and_excluded_lookahead_advances_full_cursor(search_env):
    from src.job_hunt_not_interested import hide_jobs
    env = search_env
    hide_jobs([job("hidden")], state_root=env.config.state_root)
    env.initial(excludeKeywords="Director")
    calls = []

    def fetch(values):
        offset = int(values["resultsSkip"])
        calls.append(offset)
        return [job("hidden" if offset == 1 else "director" if offset == 2 else "visible",
                    title="Director" if offset == 2 else "Synthetic role " + str(offset))]

    env.source.search_handler = fetch
    payload = env.more().send_json.call_args.args[0]
    assert calls == [1, 2, 3]
    assert payload["visible_count"] == 1 and payload["hidden_count"] == 2
    assert query_from(payload["next_url"])["resultsSkip"] == "4"
    assert env.more().send_json.call_args.args[0] == payload and calls == [1, 2, 3]


def test_partial_failure_replays_then_successor_retries_failed_term(search_env):
    env = search_env
    phase, calls = [0], []

    def fetch(values):
        term, offset = values["keywords"], int(values["resultsSkip"])
        calls.append((phase[0], term, offset))
        if term == "Fail" and phase[0] < 2:
            raise ValueError("Synthetic retryable failure")
        return [job(term + str(offset))] if term == "Good" or phase[0] == 2 else []

    env.source.search_handler = fetch
    env.initial(keywords="Fail, Good")
    phase[0] = 1
    partial = env.more().send_json.call_args.args[0]
    assert partial["ok"] and query_from(partial["next_url"])["keywordCursors"] == "0,2"
    before = len(calls)
    phase[0] = 2
    assert env.more().send_json.call_args.args[0] == partial and len(calls) == before
    recovered = env.more(query_from(partial["next_url"])).send_json.call_args.args[0]
    assert recovered["ok"] and calls[before:] == [(2, "Fail", 0), (2, "Good", 2)]


def seed(sid="search", cursor=(1, (1,))):
    state.commit_initial_search(sid, "binding", [], cursor)
    return sid


def page(sid="search", cursor=(1, (1,)), text="page", successor=(2, (2,))):
    def produce(draft):
        draft.filter_new([job(text)])
        return state.PreparedSearchPage({"ok": True, "html": text}, successor)
    return state.prepare_page(sid, "binding", cursor, produce, current_binding=lambda: "binding")


def test_expiry_at_boundary_unknown_and_unissued_cursor_restart(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(state.time, "time", lambda: now[0])
    seed()
    with pytest.raises(state.SearchRestartRequired):
        page(cursor=(7, (7,)))
    now[0] += state.SEARCH_STATE_TTL_SECONDS
    with pytest.raises(state.SearchRestartRequired):
        page()
    with pytest.raises(state.SearchRestartRequired):
        page("unknown")
    assert not state._STATE


def test_search_count_is_capped_after_insert(monkeypatch):
    monkeypatch.setattr(state, "MAX_TRACKED_SEARCHES", 2)
    for number in range(4):
        seed(str(number))
        assert len(state._STATE) <= 2
    assert list(state._STATE) == ["2", "3"]
    with pytest.raises(state.SearchRestartRequired):
        page("0")


@pytest.mark.parametrize("bound", ["pages", "bytes"])
def test_evicted_cursor_restarts_and_history_stays_bounded(monkeypatch, bound):
    monkeypatch.setattr(state, "MAX_REPLAY_PAGES_PER_SEARCH", 2 if bound == "pages" else 8)
    if bound == "bytes":
        monkeypatch.setattr(state, "MAX_REPLAY_BYTES_PER_SEARCH", 60)
    seed()
    for offset in range(1, 7):
        page(cursor=(offset, (offset,)), text="page" + str(offset), successor=(offset+1, (offset+1,)))
    entry = state._STATE["search"]
    assert len(entry["replays"]) <= 2 and "issued" not in entry
    assert entry["next_cursor"] == (7, (7,))
    with pytest.raises(state.SearchRestartRequired):
        page()
    assert page(cursor=(6, (6,)))["html"] == "page6"


def test_global_byte_cap_evicts_search_explicitly(monkeypatch):
    monkeypatch.setattr(state, "MAX_TOTAL_REPLAY_BYTES", 45)
    seed("old")
    page("old", text="old payload")
    seed("new")
    page("new", text="new payload")
    assert sum(entry["replay_bytes"] for entry in state._STATE.values()) <= 45
    with pytest.raises(state.SearchRestartRequired):
        page("old")


@pytest.mark.parametrize("bound", ["bytes", "seen"])
def test_overlarge_page_requires_restart_without_commit(monkeypatch, bound):
    seed()
    if bound == "bytes":
        monkeypatch.setattr(state, "MAX_REPLAY_BYTES_PER_SEARCH", 1)
    else:
        monkeypatch.setattr(state, "MAX_SEEN_JOBS_PER_SEARCH", 0)
    with pytest.raises(state.SearchRestartRequired):
        page()
    entry = state._STATE["search"]
    assert entry["seen"] == [] and entry["replays"] == {} and entry["next_cursor"] == (1, (1,))


def test_pruning_does_not_wait_for_a_busy_search(monkeypatch):
    monkeypatch.setattr(state, "MAX_TRACKED_SEARCHES", 1)
    seed("busy")
    entered, release = threading.Event(), threading.Event()

    def produce(draft):
        entered.set()
        assert release.wait(5)
        return state.PreparedSearchPage({"ok": True}, None)

    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(state.prepare_page, "busy", "binding", (1, (1,)), produce,
                              current_binding=lambda: "binding")
        assert entered.wait(5)
        seed("replacement")
        release.set()
        with pytest.raises(state.SearchRestartRequired):
            running.result(5)
    assert list(state._STATE) == ["replacement"]


def test_seen_keeps_scalar_dedup_fields_without_adapter_metadata():
    original = job("initial", description_raw="Synthetic description", source_quality={"nested": [1]})
    state.commit_initial_search("search", "binding", [original], (1, (1,)))
    original["title"] = "Later adapter mutation"
    initial = state._STATE["search"]["seen"][0]
    assert initial["title"] == "Synthetic initial" and "source_quality" not in initial
    fresh = job("fresh", description_preview="Another description", source_quality={"nested": [2]})

    def produce(draft):
        assert draft.filter_new([fresh]) == [fresh]
        return state.PreparedSearchPage({"ok": True, "html": "frozen"}, None)

    state.prepare_page("search", "binding", (1, (1,)), produce, current_binding=lambda: "binding")
    fresh["description_preview"] = "Later mutation"
    assert state._STATE["search"]["seen"][-1]["description_preview"] == "Another description"
    assert all("source_quality" not in row for row in state._STATE["search"]["seen"])


def test_expiry_during_render_and_changed_cached_binding_restart_without_work(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(state.time, "time", lambda: now[0])
    seed()

    def expire(draft):
        now[0] += state.SEARCH_STATE_TTL_SECONDS
        return state.PreparedSearchPage({"ok": True}, None)

    with pytest.raises(state.SearchRestartRequired):
        state.prepare_page("search", "binding", (1, (1,)), expire, current_binding=lambda: "binding")
    assert not state._STATE
    seed()
    page()
    producer = Mock(side_effect=AssertionError("Cached retries must not fetch/render"))
    with pytest.raises(state.SearchRestartRequired):
        state.prepare_page("search", "binding", (1, (1,)), producer, current_binding=lambda: "changed")
    producer.assert_not_called()
