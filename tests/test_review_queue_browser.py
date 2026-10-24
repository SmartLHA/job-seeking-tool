"""Review Queue IDs remain inert data through real browser selection events."""
from __future__ import annotations

import json
import os
from urllib.parse import quote, urlparse

import pytest

from src.ui_render import ReviewQueueViewModel, render_review_queue_page


JOB_IDS = [
    "quote');window.__rqInjected=1;//",
    r"backslash\suffix",
    "Unicode-香港-🎯",
    'markup-\"><img id="rq-injected" src="https://injected.invalid/x" onerror="window.__rqInjected=1">',
    "slash/and?query#fragment!'()*",
]
ORIGIN = "http://review-queue.invalid"


@pytest.fixture(scope="module")
def queue_browser():
    required = os.environ.get("JOB_TOOL_REQUIRE_BROWSER") == "1"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if required:
            pytest.fail("Required browser tests need Playwright installed.")
        pytest.skip("Playwright is unavailable; set JOB_TOOL_REQUIRE_BROWSER=1 to require it.")
    with sync_playwright() as playwright:
        executable = os.environ.get("JOB_TOOL_TEST_CHROMIUM_EXECUTABLE")
        try:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=executable,
                args=["--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND"],
            )
        except Exception as exc:
            if required or "Executable doesn't exist" not in str(exc):
                raise
            pytest.skip("Chromium is unavailable; set JOB_TOOL_REQUIRE_BROWSER=1 to require it.")
        try:
            yield browser
        finally:
            browser.close()


@pytest.mark.parametrize("active_id", JOB_IDS, ids=["quote", "backslash", "unicode", "markup", "url-delimiters"])
def test_review_queue_ids_stay_data_in_browser(queue_browser, active_id, tmp_path):
    from playwright.sync_api import expect

    vm = ReviewQueueViewModel(jobs=[{
        "job_id": job_id, "title": f"Synthetic job {index}", "company": "Synthetic company",
        "score": 90 - index, "decision": "apply", "source": "synthetic",
    } for index, job_id in enumerate(JOB_IDS)], active_id=active_id, ids_csv=",".join(JOB_IDS))
    rendered = render_review_queue_page(vm)
    blocked = []
    documents = []
    errors = []
    context = queue_browser.new_context(service_workers="block", offline=True)
    context.add_init_script("window.__rqInjected = 0;")

    def serve_synthetic(route):
        parsed = urlparse(route.request.url)
        if parsed.scheme == "http" and parsed.netloc == "review-queue.invalid":
            if parsed.path == "/review-queue":
                documents.append(route.request.url)
                route.fulfill(status=200, content_type="text/html", body=rendered)
                return
            if parsed.path.startswith("/job/"):
                documents.append(route.request.url)
                route.fulfill(status=200, content_type="text/html", body="<!doctype html><p>Synthetic job detail</p>")
                return
        blocked.append(route.request.url)
        route.abort()

    context.route("**/*", serve_synthetic)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    selections = []
    try:
        page.goto(ORIGIN + "/review-queue", wait_until="networkidle")
        rows = page.locator("button[data-rq-job-id]")
        assert rows.count() == len(JOB_IDS)
        assert rows.evaluate_all("nodes => nodes.map(node => node.dataset.rqJobId)") == JOB_IDS
        assert page.locator("button[data-rq-job-id][onclick]").count() == 0
        expected_initial = "/job/" + quote(active_id, safe="") + "?embed=1"
        assert page.locator("#rq-iframe").get_attribute("src") == expected_initial
        assert ORIGIN + expected_initial in documents
        colors = page.evaluate("""() => {
            const probe = document.createElement('span');
            document.body.appendChild(probe);
            const resolved = {};
            for (const name of ['--accent', '--line', '--surface-2']) {
                probe.style.color = 'var(' + name + ')';
                resolved[name] = getComputedStyle(probe).color;
            }
            probe.remove();
            return resolved;
        }""")

        def check_selection(index):
            expected = "/job/" + quote(JOB_IDS[index], safe="") + "?embed=1"
            assert page.locator("#rq-iframe").get_attribute("src") == expected
            assert page.locator("#rq-iframe").evaluate("node => node.src") == ORIGIN + expected
            for row_index in range(len(JOB_IDS)):
                row = rows.nth(row_index)
                expect(row).to_have_css("border-color", colors["--accent" if row_index == index else "--line"])
                expect(row).to_have_css("background-color", colors["--surface-2"] if row_index == index else "rgba(0, 0, 0, 0)")
                if row_index == index:
                    expect(row).not_to_have_css("box-shadow", "none")
                else:
                    expect(row).to_have_css("box-shadow", "none")
            selections.append({"id": JOB_IDS[index], "src": expected})
            assert page.locator("#rq-injected").count() == 0
            assert page.evaluate("window.__rqInjected") == 0

        check_selection(JOB_IDS.index(active_id))
        for index, job_id in enumerate(JOB_IDS):
            expected_url = ORIGIN + "/job/" + quote(job_id, safe="") + "?embed=1"
            with page.expect_request(expected_url):
                rows.nth(index).locator("div").first.click()
            check_selection(index)
        for key, index in [("Enter", 0), ("Space", 1)]:
            rows.nth(index).focus()
            expected_url = ORIGIN + "/job/" + quote(JOB_IDS[index], safe="") + "?embed=1"
            with page.expect_request(expected_url):
                page.keyboard.press(key)
            check_selection(index)
        assert errors == []
        assert all(urlparse(url).hostname == "fonts.googleapis.com" for url in blocked)
        assert page.locator("#rq-injected").count() == 0
        assert page.evaluate("window.__rqInjected") == 0
        evidence = {"active_id": active_id, "selections": selections, "documents": documents,
                    "blocked_requests": blocked, "page_errors": errors, "browser": queue_browser.version}
        (tmp_path / "review-queue-browser.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        print("BROWSER CHECK:", json.dumps(evidence, ensure_ascii=False))
    finally:
        context.close()
