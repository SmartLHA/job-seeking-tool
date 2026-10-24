"""Real DOM handling of transient pagination errors and explicit restarts."""
import json
from urllib.parse import urlparse

import pytest

from src.job_sources._multiselect import multiselect_script
from test_review_queue_browser import queue_browser  # existing required-browser fixture


@pytest.mark.parametrize("mode", ["transient", "restart", "unsafe-restart"])
def test_more_failure_retains_cards_and_selection(queue_browser, mode, tmp_path):
    from playwright.sync_api import expect

    origin = "http://search-replay.invalid"
    cursor_url = "/search/reed/more?searchId=synthetic&resultsSkip=1"
    error = '<img id="injected" src=x onerror="window.__injected=1"> Expired 香港'
    restart_url = "/search/reed?keywords=Analyst%20%22%3C%3E%22&location=Test"
    response = {"ok": False, "error": error}
    if mode != "transient":
        response.update(restart_required=True, restart_url=restart_url if mode == "restart" else "javascript:window.__injected=1")
    document = '''<!doctype html><meta charset="utf-8"><style>
        :root{--accent:red;--line:gray;--accent-soft:pink;--shadow-sm:0 0 0 black}</style>
        <div id="jst-cards-container"><div id="selected" class="jst-rc"
        data-jst-id="selected" data-jst-title="Synthetic" data-jst-company="Company"
        data-jst-form="job-form" data-jst-source="reed" data-jst-sjid="synthetic">
        <form id="job-form"><input name="title" value="Synthetic selected"></form>
        <span id="jst-cb-selected"></span>Keep this selected card</div>
        <div id="jst-more-wrap"><button id="jst-next-btn"
        data-next-url="''' + cursor_url + '''" onclick="jstLoadMore(this)">Next page</button></div></div>''' + multiselect_script()
    requests, blocked, errors, dialogs = [], [], [], []
    context = queue_browser.new_context(service_workers="block", offline=True)
    context.add_init_script("window.__injected=0;")

    def serve(route):
        parsed = urlparse(route.request.url)
        if parsed.netloc == "search-replay.invalid" and parsed.scheme == "http":
            requests.append(route.request.url)
            if parsed.path == "/search/reed":
                route.fulfill(content_type="text/html", body=document)
                return
            if parsed.path == "/jobs/not-interested":
                route.fulfill(content_type="application/json", body='{"ok":true,"count":0}')
                return
            if parsed.path == "/search/reed/more":
                route.fulfill(status=200 if mode == "transient" else 409,
                              content_type="application/json", body=json.dumps(response))
                return
        blocked.append(route.request.url)
        route.abort()

    context.route("**/*", serve)
    page = context.new_page()
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    try:
        page.goto(origin + "/search/reed", wait_until="networkidle")
        page.evaluate("jstToggle('selected')")
        button = page.locator("#jst-next-btn")
        old_cards = page.locator("#selected").inner_html()
        button.click()
        if mode == "transient":
            expect(button).to_be_enabled()
            page.wait_for_function("document.querySelector('#jst-next-btn').textContent.includes('Next page')")
            assert len(dialogs) == 1 and error in dialogs[0]
            assert page.locator("#jst-search-restart").count() == 0
            button.click()
            page.wait_for_function("document.querySelector('#jst-next-btn').textContent.includes('Next page')")
            assert requests.count(origin + cursor_url) == 2
        else:
            notice = page.locator("#jst-search-restart")
            expect(notice).to_be_visible()
            expect(button).to_be_disabled()
            assert error in notice.inner_text()
            links = notice.locator("a")
            assert links.count() == (1 if mode == "restart" else 0)
            if mode == "restart":
                assert links.get_attribute("href") == origin + restart_url
                assert links.inner_text() == "Restart search"
            assert dialogs == [] and requests.count(origin + cursor_url) == 1
        assert button.get_attribute("data-next-url") == cursor_url
        assert page.locator("#selected").inner_html() == old_cards
        assert page.evaluate("Array.from(window._jst_sel)") == ["selected"]
        assert page.evaluate("window._jst_jobs.selected.fields.title") == "Synthetic selected"
        assert page.locator("#injected").count() == 0 and page.evaluate("window.__injected") == 0
        assert page.url == origin + "/search/reed"
        assert errors == [] and blocked == []
        evidence = {"mode": mode, "browser": queue_browser.version, "requests": requests,
                    "blocked": blocked, "errors": errors, "selected": ["selected"], "restart": response}
        (tmp_path / "search-replay-browser.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        print("BROWSER CHECK:", json.dumps(evidence, ensure_ascii=False))
    finally:
        context.close()
