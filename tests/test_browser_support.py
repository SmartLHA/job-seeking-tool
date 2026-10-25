"""Required mode fails closed while optional local browser use stays explicit."""
import builtins
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from browser_support import fail_required_skip, launch_chromium, loopback_page, playwright_sync


@pytest.mark.parametrize("required", [False, True])
def test_missing_playwright_is_skip_only_in_optional_mode(monkeypatch, required):
    monkeypatch.setenv("JOB_TOOL_REQUIRE_BROWSER", "1" if required else "0")
    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "playwright.sync_api":
            raise ImportError("Synthetic missing dependency")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(pytest.fail.Exception if required else pytest.skip.Exception):
        playwright_sync()


@pytest.mark.parametrize("required", [False, True])
def test_missing_chromium_is_skip_only_in_optional_mode(monkeypatch, required):
    monkeypatch.setenv("JOB_TOOL_REQUIRE_BROWSER", "1" if required else "0")
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=Mock(side_effect=RuntimeError("Executable doesn't exist: synthetic"))))
    with pytest.raises(pytest.fail.Exception if required else pytest.skip.Exception):
        launch_chromium(playwright)


@pytest.mark.parametrize("required", [False, True])
def test_unexpected_browser_launch_failure_never_silently_skips(monkeypatch, required):
    monkeypatch.setenv("JOB_TOOL_REQUIRE_BROWSER", "1" if required else "0")
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=Mock(side_effect=RuntimeError("Synthetic launch failure"))))
    with pytest.raises(pytest.fail.Exception if required else RuntimeError):
        launch_chromium(playwright)


@pytest.mark.parametrize("phase", ["setup", "call", "teardown"])
@pytest.mark.parametrize("required,marked", [(True, True), (False, True), (True, False)])
def test_required_selected_skip_becomes_failure(monkeypatch, phase, required, marked):
    monkeypatch.setenv("JOB_TOOL_REQUIRE_BROWSER", "1" if required else "0")
    item = SimpleNamespace(nodeid="synthetic-browser", get_closest_marker=lambda _: marked)
    report = SimpleNamespace(skipped=True, outcome="skipped", when=phase, longrepr="Synthetic skipped case")
    fail_required_skip(item, report)
    assert report.outcome == ("failed" if required and marked else "skipped")
    if required and marked:
        assert "synthetic-browser" in report.longrepr


def test_loopback_context_blocks_every_other_origin():
    context = Mock()
    browser = SimpleNamespace(new_context=Mock(return_value=context))
    loopback_page(browser, "http://127.0.0.1:12345", viewport={"width": 390, "height": 844})
    browser.new_context.assert_called_once_with(service_workers="block", viewport={"width": 390, "height": 844})
    restrict = context.route.call_args.args[1]
    for url, allowed in [("http://127.0.0.1:12345/job/1", True), ("http://127.0.0.1:12346/", False),
                         ("http://localhost:12345/", False), ("https://external.invalid/", False)]:
        route = SimpleNamespace(request=SimpleNamespace(url=url), continue_=Mock(), abort=Mock())
        restrict(route)
        assert route.continue_.called is allowed and route.abort.called is not allowed


@pytest.mark.parametrize("origin", ["https://127.0.0.1:12345", "http://external.invalid:12345", "http://127.0.0.1", "http://user@127.0.0.1:12345"])
def test_browser_context_rejects_unowned_origin(origin):
    browser = Mock()
    with pytest.raises(ValueError):
        loopback_page(browser, origin)
    browser.new_context.assert_not_called()
