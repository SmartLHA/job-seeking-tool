"""Read-only Browse CLI extraction helpers for public pages."""

from __future__ import annotations

import json
import re
import subprocess
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from domain_policy import detect_category, extract_domain, inspect_visible_text
from extraction_profiles import extract_profile
from extraction_quality import score_extraction, usefulness
from link_extractor import extract_useful_links
from text_cleanup import clean_main_content, deduplicate_headings


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"
SNAPSHOT_DIR = OUTPUT_DIR / "snapshots"


EXTRACT_JS = r'''(() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const text = document.body ? document.body.innerText : '';
  const links = Array.from(document.querySelectorAll('a[href]')).slice(0, 220).map(a => ({
    text: clean(a.innerText || a.getAttribute('aria-label') || a.getAttribute('title') || ''),
    aria_label: clean(a.getAttribute('aria-label') || ''),
    title: clean(a.getAttribute('title') || ''),
    href: a.getAttribute('href') || '',
    url: new URL(a.getAttribute('href'), location.href).href
  })).filter(x => x.url);
  const headings = Array.from(document.querySelectorAll('h1,h2,h3')).map(h => clean(h.innerText)).filter(Boolean).slice(0, 40);
  const meta = document.querySelector('meta[name="description"], meta[property="og:description"]');
  const forms = Array.from(document.querySelectorAll('form')).map(f => clean(f.innerText).slice(0, 300));
  const buttons = Array.from(document.querySelectorAll('button,a')).map(el => clean(el.innerText || el.getAttribute('aria-label') || '')).filter(Boolean).slice(0, 120);
    const scripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(s => s.textContent || '').slice(0, 10);
  return JSON.stringify({
    href: location.href,
    title: clean(document.title || document.querySelector('h1')?.innerText),
    h1: clean(document.querySelector('h1')?.innerText),
    meta_description: clean(meta?.getAttribute('content')),
    text,
    headings,
    links,
    buttons,
    form_count: forms.length,
    form_previews: forms,
    file_inputs_count: document.querySelectorAll('input[type="file"]').length,
    password_inputs_count: document.querySelectorAll('input[type="password"]').length,
    json_ld: scripts
  });
})()'''


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        href = values.get("href")
        if not href:
            return
        self._current = {
            "href": href,
            "url": href,
            "text": "",
            "aria_label": values.get("aria-label", ""),
            "title": values.get("title", ""),
        }

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["text"] = f"{self._current['text']} {data}".strip()

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current is not None:
            self.links.append(self._current)
            self._current = None


def run_command(command: list[str], timeout: int = 90) -> tuple[int, str, str]:
    proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def fetch_static_links(url: str, timeout: int = 12) -> list[dict[str, str]]:
    request = Request(url, headers={"User-Agent": "OpenClaw-PublicWebExtraction-POC/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(350_000)
            html = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return []
    parser = AnchorParser()
    parser.feed(html)
    return parser.links[:220]


def parse_browse_json(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    if isinstance(parsed, str):
        return json.loads(parsed)
    return parsed


def parse_snapshot_output(raw: str) -> dict[str, Any]:
    """Extract visible text hints from Browse's accessibility snapshot JSON."""
    if not raw.strip():
        return {"text": "", "headings": [], "links": [], "buttons": []}
    try:
        parsed = json.loads(raw)
        tree = parsed.get("tree", raw) if isinstance(parsed, dict) else raw
    except Exception:
        tree = raw

    headings: list[str] = []
    links: list[dict[str, str]] = []
    buttons: list[str] = []
    text_parts: list[str] = []
    title = ""

    for line in str(tree).splitlines():
        clean = re.sub(r"^\s*\[[^\]]+\]\s*", "", line).strip()
        if not clean:
            continue
        if clean.startswith("RootWebArea:"):
            title = clean.split(":", 1)[1].strip()
            text_parts.append(title)
        elif clean.startswith("heading:"):
            value = clean.split(":", 1)[1].strip()
            headings.append(value)
            text_parts.append(value)
        elif clean.startswith("StaticText:"):
            text_parts.append(clean.split(":", 1)[1].strip())
        elif clean.startswith("paragraph"):
            continue
        elif clean.startswith("link:"):
            value = clean.split(":", 1)[1].strip()
            links.append({"text": value, "url": ""})
            text_parts.append(value)
        elif clean.startswith("button:") or clean.startswith("DisclosureTriangle:"):
            value = clean.split(":", 1)[1].strip()
            buttons.append(value)
            text_parts.append(value)
        elif any(clean.startswith(prefix) for prefix in ("list:", "navigation:", "contentinfo:", "banner", "main", "article", "section")):
            continue

    return {
        "title": title,
        "h1": headings[0] if headings else "",
        "meta_description": "",
        "text": "\n".join(text_parts),
        "headings": headings[:40],
        "links": links[:50],
        "buttons": buttons[:80],
        "json_ld": [],
        "password_inputs_count": 0,
        "file_inputs_count": 0,
        "form_count": 0,
    }


def signal_matches(text: str, patterns: tuple[str, ...], limit: int = 12) -> list[str]:
    hay_lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    found: list[str] = []
    for line in hay_lines:
        low = line.lower()
        if any(pattern in low for pattern in patterns) and line not in found:
            found.append(line[:180])
        if len(found) >= limit:
            break
    return found


def summarize_visible_content(text: str, max_chars: int = 600) -> str | None:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return None
    return clean[:max_chars].rstrip()


def extract_dates_and_author(page_data: dict[str, Any]) -> tuple[str | None, str | None]:
    date_published = None
    author = None
    for raw in page_data.get("json_ld") or []:
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if not isinstance(item, dict):
                continue
            date_published = date_published or item.get("datePublished")
            raw_author = item.get("author")
            if isinstance(raw_author, dict):
                author = author or raw_author.get("name")
            elif isinstance(raw_author, list) and raw_author and isinstance(raw_author[0], dict):
                author = author or raw_author[0].get("name")
            elif isinstance(raw_author, str):
                author = author or raw_author
    return date_published, author


def build_page_record(
    candidate: dict[str, Any],
    page_data: dict[str, Any],
    *,
    status: str,
    reason: str | None,
    screenshot_path: str | None,
    snapshot_path: str | None,
    network_requests_made: int,
) -> dict[str, Any]:
    raw_text = page_data.get("text") or ""
    text = clean_main_content(raw_text)
    raw_inspection = inspect_visible_text(raw_text)
    inspection = inspect_visible_text(text)
    category = detect_category(candidate["url"], text, candidate.get("category"))
    buttons = page_data.get("buttons") or []
    ctas = [
        value for value in buttons
        if any(term in value.lower() for term in ("start", "try", "contact", "demo", "sign up", "apply", "learn more"))
    ][:20]
    date_published, author = extract_dates_and_author(page_data)
    links = extract_useful_links(page_data.get("links") or [], candidate["url"], limit=50)
    profile = extract_profile(category, text, links, page_data.get("h1") or page_data.get("title"))
    pricing_signals = profile["pricing_signals"] or signal_matches(text, ("pricing", "price", "$", "£", "free", "enterprise", "per month"))
    feature_signals = profile["features"] or signal_matches(text, ("feature", "workflow", "automation", "integrations", "dashboard", "templates"))
    job_signals = profile["job_career_signals"] or signal_matches(text, ("job", "career", "role", "employment", "salary", "location", "department"))

    record = {
        "url": candidate["url"],
        "domain": extract_domain(candidate["url"]),
        "category": category,
        "status": status,
        "reason": reason,
        "title": page_data.get("h1") or page_data.get("title") or None,
        "meta_description": page_data.get("meta_description") or None,
        "main_content": text or None,
        "summary": summarize_visible_content(text),
        "concise_summary": profile["concise_summary"],
        "headings": deduplicate_headings(page_data.get("headings") or [])[:40],
        "links": links,
        "useful_links": links,
        "calls_to_action": ctas,
        "key_claims": profile["key_claims"],
        "features": profile["features"],
        "pricing_signals": pricing_signals,
        "feature_signals": feature_signals,
        "job_signals": job_signals,
        "job_career_signals": job_signals,
        "company_signals": signal_matches(text, ("mission", "founded", "team", "company", "customers", "about")),
        "category_profile": profile,
        "date_published": date_published,
        "author": author,
        "content_usefulness": {},
        "extraction_quality": {},
        "browser_metadata": {
            "verified_from_live_page": status == "success",
            "network_requests_made": network_requests_made,
            "screenshot_path": screenshot_path,
            "snapshot_path": snapshot_path,
            "cookie_banner_seen": raw_inspection["cookie_banner_seen"],
            "cookies_accepted": False,
            "login_required": inspection["login_required"] or page_data.get("password_inputs_count", 0) > 0,
            "forms_present": page_data.get("form_count", 0) > 0,
            "form_submission_required_to_view_content": inspection["form_required"] and not inspection["meaningful_text"],
            "form_interaction_performed": False,
            "persistent_session_used": False,
            "stealth_mode_used": False,
            "captcha_seen": inspection["captcha_seen"],
            "captcha_solved": False,
        },
    }
    record["content_usefulness"] = usefulness(record)
    record["extraction_quality"] = score_extraction(record)
    return record


def extract_with_browse(candidate: dict[str, Any], config: dict[str, Any], index: int) -> tuple[dict[str, Any], list[str]]:
    """Open one candidate URL read-only with Browse CLI and extract visible content."""
    commands: list[str] = []
    label = re.sub(r"[^a-z0-9]+", "-", candidate.get("label", f"page-{index}").lower()).strip("-")[:50]
    session = f"oc-public-web-{index}-{int(time.time())}"

    def tracked(command: list[str], timeout: int = 90) -> tuple[int, str, str]:
        commands.append(" ".join(command))
        return run_command(command, timeout=timeout)

    screenshot_path = None
    snapshot_path = None
    network_requests_made = 0
    page_data: dict[str, Any] = {}

    tracked(["browse", "stop", "--session", session, "--force"], timeout=20)
    tracked(["browse", "network", "clear", "--session", session, "--local", "--headless"], timeout=20)
    tracked(["browse", "network", "on", "--session", session, "--local", "--headless"], timeout=30)
    rc, stdout, stderr = tracked(
        ["browse", "open", candidate["url"], "--session", session, "--local", "--headless", "--wait", "load", "--timeout", "60000"],
        timeout=90,
    )
    if rc != 0:
        tracked(["browse", "stop", "--session", session, "--force"], timeout=20)
        record = build_page_record(
            candidate,
            {},
            status="failed",
            reason=f"browse_open_failed:{(stderr or stdout)[:240]}",
            screenshot_path=None,
            snapshot_path=None,
            network_requests_made=0,
        )
        return record, commands

    rc, stdout, stderr = tracked(["browse", "eval", EXTRACT_JS, "--session", session, "--local", "--headless"], timeout=60)
    if rc == 0:
        try:
            page_data = parse_browse_json(stdout)
        except Exception as exc:
            page_data = {"text": "", "title": "", "error": f"eval_parse_failed:{exc}"}
    else:
        page_data = {"text": "", "title": "", "error": f"browse_eval_failed:{(stderr or stdout)[:240]}"}

    static_links = fetch_static_links(candidate["url"])
    if static_links:
        page_data["links"] = (page_data.get("links") or []) + static_links

    if config.get("save_snapshot", True):
        snapshot_file = SNAPSHOT_DIR / f"{index:02d}_{label}.txt"
        rc, stdout, stderr = tracked(
            ["browse", "snapshot", "--session", session, "--local", "--headless", "--compact", "--max-depth", "8"],
            timeout=60,
        )
        if rc == 0:
            snapshot_file.write_text(stdout + "\n", encoding="utf-8")
            snapshot_path = str(snapshot_file)
            if not (page_data.get("text") or "").strip():
                snapshot_data = parse_snapshot_output(stdout)
                snapshot_data["links"] = (page_data.get("links") or []) + (snapshot_data.get("links") or [])
                page_data = snapshot_data

    if config.get("save_screenshot", True):
        screenshot_file = SCREENSHOT_DIR / f"{index:02d}_{label}.png"
        rc, stdout, stderr = tracked(
            ["browse", "screenshot", "--session", session, "--local", "--headless", "--full-page", "--path", str(screenshot_file)],
            timeout=90,
        )
        if rc == 0 and screenshot_file.exists():
            screenshot_path = str(screenshot_file)

    rc, stdout, stderr = tracked(["browse", "network", "path", "--session", session, "--local", "--headless"], timeout=20)
    if rc == 0 and stdout:
        network_path = Path(stdout.splitlines()[-1])
        if network_path.exists():
            network_requests_made = len([item for item in network_path.rglob("*") if item.is_file()])

    tracked(["browse", "network", "off", "--session", session, "--local", "--headless"], timeout=20)
    tracked(["browse", "stop", "--session", session, "--force"], timeout=20)

    inspection = inspect_visible_text(page_data.get("text") or "")
    if inspection["login_required"]:
        status, reason = "skipped", "login_required"
    elif inspection["unavailable"]:
        status, reason = "failed", "page_unavailable_or_removed"
    elif inspection["form_required"] and not (page_data.get("text") or "").strip():
        status, reason = "skipped", "form_submission_required"
    elif not inspection["meaningful_text"]:
        status, reason = "failed", "no_meaningful_visible_text"
    else:
        status, reason = "success", None

    record = build_page_record(
        candidate,
        page_data,
        status=status,
        reason=reason,
        screenshot_path=screenshot_path,
        snapshot_path=snapshot_path,
        network_requests_made=network_requests_made,
    )
    return record, commands
