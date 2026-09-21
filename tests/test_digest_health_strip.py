"""F2 (audit 2026-09-20): digest page health strip and Run LLM batch button."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src import ui_handlers
from src.ui_render import render_digest_page


def _html() -> str:
    return render_digest_page(entries=[], filters={}, sources=[], saved_searches=[])


def test_strip_and_button_present() -> None:
    html = _html()
    assert 'id="digest-health"' in html
    assert 'id="health-quota"' in html
    assert 'id="health-scheduler"' in html
    assert 'id="run-llm-batch-btn"' in html
    # loading and error states
    assert "loading" in html and "unavailable" in html


def test_fetch_targets_and_button_route_in_html() -> None:
    html = _html()
    assert 'fetch("/digest/llm-queue")' in html
    assert 'fetch("/scheduler/status")' in html
    assert 'fetch("/digest/run-llm-batch",{method:"POST"' in html


def test_targets_are_existing_routes() -> None:
    routes = Path(ui_handlers.__file__).with_name("ui_routes.py").read_text()
    for path in ('"/digest/llm-queue"', '"/scheduler/status"', '"/digest/run-llm-batch"'):
        assert path in routes


class _Resp:
    def send_json(self, payload, status=None) -> None:
        self.json_sent = payload


def test_llm_queue_handler_reports_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ui_handlers, "_index_db_path", lambda c: tmp_path / "idx.db")
    monkeypatch.setattr(ui_handlers, "_load_active_profile", lambda c: SimpleNamespace(digest_llm_rpd=123))
    resp = _Resp()
    ui_handlers.handle_llm_queue(None, SimpleNamespace(), resp)
    assert resp.json_sent["rpd_limit"] == 123
    assert "rpd_used_today" in resp.json_sent


def test_llm_queue_handler_limit_none_when_profile_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ui_handlers, "_index_db_path", lambda c: tmp_path / "idx.db")

    def boom(c):
        raise RuntimeError("no profile")

    monkeypatch.setattr(ui_handlers, "_load_active_profile", boom)
    resp = _Resp()
    ui_handlers.handle_llm_queue(None, SimpleNamespace(), resp)
    assert resp.json_sent["rpd_limit"] is None
