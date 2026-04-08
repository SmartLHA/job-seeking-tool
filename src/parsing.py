from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib import robotparser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

DEFAULT_USER_AGENT = "JobSeekingTool/1.0"
FETCH_TIMEOUT_SECONDS = 10
KNOWN_WORK_MODES = ("remote", "hybrid", "onsite", "on-site")
KNOWN_EMPLOYMENT_TYPES = (
    "full-time",
    "part-time",
    "contract",
    "permanent",
    "temporary",
    "internship",
)
KNOWN_SKILLS = (
    "sql",
    "python",
    "power bi",
    "tableau",
    "stakeholder management",
    "process mapping",
    "agile",
    "scrum",
    "data analysis",
    "business analysis",
    "requirements gathering",
)


class JobParsingError(ValueError):
    """Raised when job parsing or fetching fails."""


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag in {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "div", "section", "article", "li"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)
            self._parts.append(" ")

    def get_text(self) -> str:
        joined = "".join(self._parts)
        lines = [re.sub(r"\s+", " ", line).strip() for line in joined.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def parse_job_from_text(raw_text: str, *, source_ref: str | None = None) -> dict[str, object]:
    cleaned = _clean_text(raw_text)
    if not cleaned:
        raise JobParsingError("No job text was provided")

    title = _extract_field(cleaned, [r"job title\s*[:\-]\s*(.+)", r"title\s*[:\-]\s*(.+)"])
    company = _extract_field(cleaned, [r"company\s*[:\-]\s*(.+)", r"employer\s*[:\-]\s*(.+)"])
    location = _extract_field(cleaned, [r"location\s*[:\-]\s*(.+)"])
    salary_min, salary_max = _extract_salary_range(cleaned)
    work_mode = _extract_keyword(cleaned, KNOWN_WORK_MODES)
    employment_type = _extract_keyword(cleaned, KNOWN_EMPLOYMENT_TYPES)
    years = _extract_years(cleaned)
    skills = _extract_skills(cleaned)

    lines = [line for line in cleaned.splitlines() if line.strip()]
    inferred_title = title or (lines[0] if lines else "Unknown title")
    inferred_company = company or _extract_company_from_lines(lines) or "Unknown company"

    return {
        "job_id": _build_job_id(inferred_title, inferred_company),
        "job_title": inferred_title,
        "company": inferred_company,
        "description_raw": cleaned,
        "source_type": "url" if source_ref else "copied_text",
        "source_ref": source_ref,
        "location": location,
        "work_mode": _normalise_work_mode(work_mode),
        "employment_type": employment_type,
        "required_skills": skills,
        "preferred_skills": [],
        "required_years_experience": years,
        "nice_to_have_years_experience": None,
        "domain": None,
        "notes": None,
        "salary_min_gbp": salary_min,
        "salary_max_gbp": salary_max,
    }


def parse_job_from_url(url: str) -> dict[str, object]:
    cleaned_url = url.strip()
    if not cleaned_url:
        raise JobParsingError("URL is required")
    if not _is_fetch_allowed(cleaned_url):
        raise JobParsingError("Fetching this URL is blocked by robots.txt")

    request = Request(cleaned_url, headers={"User-Agent": DEFAULT_USER_AGENT})
    try:
        with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise JobParsingError(f"URL fetch failed: HTTP {exc.code}") from exc
    except URLError as exc:
        raise JobParsingError(f"URL fetch failed: {exc.reason}") from exc

    text = _extract_text_from_html(html)
    if not text:
        raise JobParsingError("Could not extract readable job text from the URL")
    return parse_job_from_text(text, source_ref=cleaned_url)


def _is_fetch_allowed(url: str) -> bool:
    parsed = urlparse(url)
    robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")
    parser = robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except Exception:
        return True
    return parser.can_fetch(DEFAULT_USER_AGENT, url)


def _extract_text_from_html(content: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(content)
    return parser.get_text()


def _clean_text(value: str) -> str:
    return "\n".join(line.strip() for line in value.strip().splitlines() if line.strip())


def _extract_field(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_salary_range(text: str) -> tuple[int | None, int | None]:
    values = [int(number.replace(",", "")) for number in re.findall(r"£\s*([0-9]{2,3}(?:,[0-9]{3})*)", text)]
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], None
    return min(values), max(values)


def _extract_years(text: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\+?\s+years?", text, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def _extract_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
    lowered = text.casefold()
    for keyword in keywords:
        if keyword.casefold() in lowered:
            return keyword
    return None


def _normalise_work_mode(value: str | None) -> str | None:
    if value == "on-site":
        return "onsite"
    return value


def _extract_skills(text: str) -> list[str]:
    lowered = text.casefold()
    found: list[str] = []
    for skill in KNOWN_SKILLS:
        if skill in lowered:
            found.append(skill.title() if skill != "sql" else "SQL")
    return found


def _extract_company_from_lines(lines: list[str]) -> str | None:
    for index, line in enumerate(lines[:4]):
        if re.search(r"\b(?:at|@)\b", line, flags=re.IGNORECASE):
            parts = re.split(r"\b(?:at|@)\b", line, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
        if index == 1 and line and len(line.split()) <= 6:
            return line.strip()
    return None


def _build_job_id(title: str, company: str) -> str:
    base = f"{title}-{company}".casefold()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:80] or "job-review"
