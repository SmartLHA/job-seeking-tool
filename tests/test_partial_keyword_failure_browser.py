"""Real DOM check of the partly failed keyword notice in jstLoadMore (AC11 of
docs/tasks/2026-11-06-partial-keyword-failure-notice-spec.md). Stubbed responses only."""
import json
from urllib.parse import urlparse, parse_qs

import pytest

from src.job_sources._multiselect import multiselect_script
from test_review_queue_browser import queue_browser  # existing required-browser fixture

NOTE = ('<div id="jst-keyword-failure-note"><div>Some keywords could not be searched</div>'
        '<ul><li><strong>broken</strong>: Reed request timed out</li></ul>'
        '<div>Next page tries these keywords again.</div></div>')


def _card(key):
    return (f'<div id="{key}" class="jst-rc" data-jst-id="{key}" data-jst-title="T" data-jst-company="C" '
            f'data-jst-form="f-{key}" data-jst-source="reed" data-jst-sjid="{key}">'
            f'<form id="f-{key}"><input name="title" value="{key}"></form><span id="jst-cb-{key}"></span>Card {key}</div>')


# page number -> More JSON the stub serves
RESPONSES = {
    "2": {"ok": True, "cards_html": "", "other_results_html": "", "has_more": True,
          "next_url": "/search/reed/more?page=3", "count": 0, "visible_count": 0, "hidden_count": 0,
          "keyword_failure_html": NOTE},
    "3": {"ok": True, "cards_html": _card("fresh"), "other_results_html": "", "has_more": True,
          "next_url": "/search/reed/more?page=4", "count": 1, "visible_count": 1, "hidden_count": 0},
    "4": {"ok": True, "cards_html": _card("late"), "other_results_html": "", "has_more": True,
          "next_url": "/search/reed/more?page=5", "count": 1, "visible_count": 1, "hidden_count": 0,
          "keyword_failure_html": NOTE},
    "5": {"ok": True, "cards_html": "", "other_results_html": "", "has_more": False,
          "next_url": "/search/reed/more?page=6", "count": 0, "visible_count": 0, "hidden_count": 0},
}


@pytest.mark.required_browser
def test_keyword_failure_notice_lifecycle(queue_browser, tmp_path):
    from playwright.sync_api import expect

    origin = "http://keyword-failure.invalid"
    document = ('<!doctype html><meta charset="utf-8"><style>'
                ':root{--accent:red;--line:gray;--accent-soft:pink;--shadow-sm:0 0 0 black}</style>'
                '<section id="panel"><div id="jst-cards-container">' + _card("first") +
                '<div id="jst-more-wrap"><button id="jst-next-btn" data-next-url="/search/reed/more?page=2" '
                'onclick="jstLoadMore(this)">Next page</button></div></div></section>' + multiselect_script())
    requests, blocked, errors = [], [], []
    context = queue_browser.new_context(service_workers="block", offline=True)

    def serve(route):
        parsed = urlparse(route.request.url)
        if parsed.netloc == "keyword-failure.invalid" and parsed.scheme == "http":
            requests.append(route.request.url)
            if parsed.path == "/search/reed":
                route.fulfill(content_type="text/html", body=document)
                return
            if parsed.path == "/jobs/not-interested":
                route.fulfill(content_type="application/json", body='{"ok":true,"count":0}')
                return
            if parsed.path == "/search/reed/more":
                page_no = parse_qs(parsed.query)["page"][0]
                route.fulfill(content_type="application/json", body=json.dumps(RESPONSES[page_no]))
                return
        blocked.append(route.request.url)
        route.abort()

    context.route("**/*", serve)
    page = context.new_page()
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("dialog", lambda dialog: (errors.append("dialog: " + dialog.message), dialog.dismiss()))
    button = page.locator("#jst-next-btn")
    note = page.locator("#jst-keyword-failure-note")

    def click_and_wait(expected_page):
        button.click()
        page.wait_for_function(
            "n => document.querySelector('#jst-next-btn').getAttribute('data-next-url').endsWith('page=' + n)"
            " && !document.querySelector('#jst-next-btn').disabled", arg=str(expected_page))

    try:
        page.goto(origin + "/search/reed", wait_until="networkidle")
        # 1. Response with the field and no results: notice in the container, first child,
        #    and no "No more jobs" text.
        click_and_wait(3)
        expect(note).to_have_count(1)
        assert page.evaluate("document.querySelector('#jst-cards-container').firstElementChild.id") == "jst-keyword-failure-note"
        assert page.evaluate("document.querySelector('#jst-keyword-failure-note').parentElement.id") == "jst-cards-container"
        assert "No more jobs on this page." not in page.locator("#jst-cards-container").inner_text()
        assert page.locator("#jst-page-note").count() == 0
        assert "Reed request timed out" in note.inner_text()
        # 2. Next successful response without the field removes it.
        click_and_wait(4)
        expect(note).to_have_count(0)
        assert page.locator("#fresh").count() == 1
        # 3. Response with the field and cards: notice above the cards.
        click_and_wait(5)
        expect(note).to_have_count(1)
        order = page.evaluate("Array.from(document.querySelector('#jst-cards-container').children).map(e => e.id)")
        assert order.index("jst-keyword-failure-note") < order.index("late")
        # 4. No field and no results: notice goes, the ordinary empty-page text stays.
        button.click()
        page.wait_for_function("document.querySelector('#jst-next-btn').style.display === 'none'")
        expect(note).to_have_count(0)
        assert "No more jobs on this page." in page.locator("#jst-cards-container").inner_text()
        assert errors == [] and blocked == []
        evidence = {"browser": queue_browser.version, "requests": requests, "order_with_cards": order}
        (tmp_path / "keyword-failure-browser.json").write_text(json.dumps(evidence, indent=2))
        print("BROWSER CHECK:", json.dumps(evidence))
    finally:
        context.close()
