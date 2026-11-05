"""Shared optional-local / mandatory-CI browser test boundary."""
import os
from urllib.parse import urlsplit

import pytest


def browser_required():
    return os.environ.get("JOB_TOOL_REQUIRE_BROWSER") == "1"


def playwright_sync():
    try:
        from playwright.sync_api import sync_playwright, Error
    except ImportError:
        message = "Browser tests require Playwright; install the development requirements."
        if browser_required():
            pytest.fail(message, pytrace=False)
        pytest.skip(message + " Set JOB_TOOL_REQUIRE_BROWSER=1 to require execution.")
    return sync_playwright, Error


def launch_chromium(playwright):
    try:
        return playwright.chromium.launch(
            headless=True,
            executable_path=os.environ.get("JOB_TOOL_TEST_CHROMIUM_EXECUTABLE"),
            args=["--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"],
        )
    except Exception as exc:
        message = "Chromium browser test launch failed: " + str(exc)
        if browser_required():
            pytest.fail(message, pytrace=False)
        if "Executable doesn't exist" in str(exc):
            pytest.skip(message + " Set JOB_TOOL_REQUIRE_BROWSER=1 to require execution.")
        raise


def loopback_page(browser, *origins, **options):
    """A fresh context may reach only its exact synthetic loopback server(s)."""
    allowed = set()
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or parsed.username:
            raise ValueError("Browser integration origin must be an explicit 127.0.0.1 server")
        allowed.add((parsed.scheme, parsed.hostname, parsed.port))
    if not allowed:
        raise ValueError("Browser integration needs an owned loopback origin")
    context = browser.new_context(service_workers="block", **options)

    def restrict(route):
        parsed = urlsplit(route.request.url)
        if (parsed.scheme, parsed.hostname, parsed.port) in allowed:
            route.continue_()
        else:
            route.abort("blockedbyclient")

    context.route("**/*", restrict)
    return context.new_page()


def fail_required_skip(item, report):
    if browser_required() and item.get_closest_marker("required_browser") and report.skipped:
        reason = str(report.longrepr)
        report.outcome = "failed"
        report.longrepr = "Required browser test skipped: " + item.nodeid + "\n" + reason
