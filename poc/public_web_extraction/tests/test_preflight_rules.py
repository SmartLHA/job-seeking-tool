import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

import run_preflight


CONFIG = {
    "candidate_url_only_mode": True,
    "blocklist": [],
}


def test_preflight_records_failed_page_safely(monkeypatch):
    candidate = {"url": "https://example.com/missing", "category": "blog_article"}
    monkeypatch.setattr(run_preflight, "fetch_visible_probe", lambda url: (404, "not found", "http_404"))
    result = run_preflight.preflight_candidate(candidate, [candidate], CONFIG)
    assert result["status"] == "failed"
    assert result["reason"] == "http_404"


def test_login_required_page_is_skipped_by_preflight(monkeypatch):
    candidate = {"url": "https://example.com/private", "category": "documentation"}
    html = "<html><body>Login required. Sign in required to view this documentation.</body></html>"
    monkeypatch.setattr(run_preflight, "fetch_visible_probe", lambda url: (200, html, None))
    result = run_preflight.preflight_candidate(candidate, [candidate], CONFIG)
    assert result["status"] == "failed"
    assert result["reason"] == "login_required"
    assert result["login_required"] is True


def test_cookie_banner_observation_does_not_fail_if_content_visible(monkeypatch):
    candidate = {"url": "https://example.com/product", "category": "product_homepage"}
    body = "This website uses cookies. " + ("Visible product content. " * 40)
    monkeypatch.setattr(run_preflight, "fetch_visible_probe", lambda url: (200, f"<body>{body}</body>", None))
    result = run_preflight.preflight_candidate(candidate, [candidate], CONFIG)
    assert result["status"] == "passed"
    assert result["cookie_banner_seen"] is True


def test_form_submission_required_is_blocked(monkeypatch):
    candidate = {"url": "https://example.com/upload", "category": "unknown"}
    html = "<body>Submit application. Upload CV.</body>"
    monkeypatch.setattr(run_preflight, "fetch_visible_probe", lambda url: (200, html, None))
    result = run_preflight.preflight_candidate(candidate, [candidate], CONFIG)
    assert result["status"] == "failed"
    assert result["reason"] == "form_submission_required"
    assert result["forms_present"] is False
    assert result["form_submission_required_to_view_content"] is True
    assert result["form_interaction_performed"] is False


def test_sign_in_link_does_not_count_as_login_required(monkeypatch):
    candidate = {"url": "https://example.com/docs", "category": "documentation"}
    body = "Sign in Docs " + ("Visible public documentation content. " * 40)
    monkeypatch.setattr(run_preflight, "fetch_visible_probe", lambda url: (200, f"<body>{body}</body>", None))
    result = run_preflight.preflight_candidate(candidate, [candidate], CONFIG)
    assert result["status"] == "passed"
    assert result["login_required"] is False
