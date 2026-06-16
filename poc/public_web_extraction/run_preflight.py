#!/usr/bin/env python3
"""Preflight public candidate pages before Browse CLI extraction."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from domain_policy import detect_category, inspect_visible_text, normalize_url, validate_candidate_url


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_visible_probe(url: str, timeout: int = 12) -> tuple[int | None, str, str | None]:
    request = Request(url, headers={"User-Agent": "OpenClaw-PublicWebExtraction-POC/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            raw = response.read(250_000)
            text = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            return status, text, None
    except HTTPError as exc:
        raw = exc.read(80_000)
        text = raw.decode("utf-8", errors="replace")
        return exc.code, text, f"http_{exc.code}"
    except URLError as exc:
        return None, "", f"url_error:{exc.reason}"
    except Exception as exc:
        return None, "", f"fetch_error:{exc}"


def html_to_text(html: str) -> str:
    import re

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def preflight_candidate(candidate: dict, candidates: list[dict], config: dict) -> dict:
    url = normalize_url(candidate.get("url"))
    policy = validate_candidate_url(url, candidates, config)
    record = {
        "url": url,
        "category": candidate.get("category") or "unknown",
        "label": candidate.get("label"),
        "status": "failed",
        "reason": None,
        "http_status": None,
        "meaningful_visible_text": False,
        "login_required": False,
        "cookie_banner_seen": False,
        "captcha_seen": False,
        "forms_present": False,
        "form_submission_required_to_view_content": False,
        "form_interaction_performed": False,
        "detected_category": "unknown",
    }
    if not policy.allowed:
        record["reason"] = policy.reason
        return record

    status, html, error = fetch_visible_probe(url)
    text = html_to_text(html)
    inspection = inspect_visible_text(text)
    record.update(
        {
            "http_status": status,
            "meaningful_visible_text": inspection["meaningful_text"],
            "login_required": inspection["login_required"],
            "cookie_banner_seen": inspection["cookie_banner_seen"],
            "captcha_seen": inspection["captcha_seen"],
            "forms_present": "<form" in html.lower(),
            "form_submission_required_to_view_content": inspection["form_required"] and not inspection["meaningful_text"],
            "form_interaction_performed": False,
            "detected_category": detect_category(url, text, candidate.get("category")),
        }
    )

    if error and status not in {403, 404, 410, 429}:
        record["reason"] = error
    elif status in {403, 404, 410, 429}:
        record["reason"] = f"http_{status}"
    elif inspection["login_required"]:
        record["reason"] = "login_required"
    elif inspection["unavailable"]:
        record["reason"] = "page_unavailable_or_removed"
    elif inspection["form_required"] and not inspection["meaningful_text"]:
        record["reason"] = "form_submission_required"
    elif not inspection["meaningful_text"]:
        record["reason"] = "no_meaningful_visible_text"
    else:
        record["status"] = "passed"
        record["reason"] = None
    return record


def run() -> dict:
    config = load_json(BASE_DIR / "config.example.json")
    candidates = load_json(BASE_DIR / "candidate_pages.json")
    results = [preflight_candidate(candidate, candidates, config) for candidate in candidates]
    payload = {
        "total_candidate_pages": len(candidates),
        "passed_count": sum(1 for item in results if item["status"] == "passed"),
        "failed_count": sum(1 for item in results if item["status"] != "passed"),
        "results": results,
    }
    output = BASE_DIR / "output" / "candidate_preflight.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run()
    print(json.dumps({"total": result["total_candidate_pages"], "passed": result["passed_count"], "failed": result["failed_count"]}, indent=2))
