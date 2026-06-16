"""Deterministic text cleanup for the public web extraction POC."""

from __future__ import annotations

import re


COOKIE_PATTERNS = (
    r"(?i)\b(this website|we|our site)\s+uses cookies\b[^.\n]*(?:\.|\n|$)",
    r"(?i)\baccept all cookies\b",
    r"(?i)\breject all cookies\b",
    r"(?i)\bmanage cookies\b",
    r"(?i)\bcookie preferences\b",
    r"(?i)\bcookie policy\b",
)

NAV_FOOTER_EXACT = {
    "pricing",
    "product",
    "products",
    "solutions",
    "resources",
    "customers",
    "company",
    "about",
    "careers",
    "blog",
    "docs",
    "documentation",
    "contact",
    "support",
    "sign in",
    "login",
    "privacy",
    "terms",
}


def collapse_letter_spaced_artifacts(text: str) -> str:
    """Collapse short runs such as 'N o t i o n' while leaving normal prose alone."""

    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        compact = value.replace(" ", "")
        if len(compact) < 3 or len(compact) > 24:
            return value
        return compact

    return re.sub(r"\b(?:[A-Za-z]\s+){2,}[A-Za-z]\b", replace, text or "")


def normalize_whitespace(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def remove_cookie_banner_text(text: str) -> str:
    cleaned = text or ""
    for pattern in COOKIE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned)
    return cleaned


def deduplicate_headings(headings: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for heading in headings or []:
        clean = normalize_whitespace(collapse_letter_spaced_artifacts(heading))
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def reduce_repeated_blocks(text: str) -> str:
    """Remove repeated headings/nav/footer-like lines without deleting body prose."""

    lines = [line.strip() for line in (text or "").splitlines()]
    counts: dict[str, int] = {}
    for line in lines:
        key = line.lower()
        if key:
            counts[key] = counts.get(key, 0) + 1

    kept: list[str] = []
    seen_short: set[str] = set()
    for line in lines:
        if not line:
            if kept and kept[-1]:
                kept.append("")
            continue
        key = line.lower()
        word_count = len(key.split())
        is_nav = key in NAV_FOOTER_EXACT or (word_count <= 4 and counts.get(key, 0) > 1)
        if is_nav and key in seen_short:
            continue
        if is_nav:
            seen_short.add(key)
        kept.append(line)
    return "\n".join(kept)


def clean_main_content(text: str) -> str:
    cleaned = collapse_letter_spaced_artifacts(text or "")
    cleaned = remove_cookie_banner_text(cleaned)
    cleaned = normalize_whitespace(cleaned)
    cleaned = reduce_repeated_blocks(cleaned)
    return normalize_whitespace(cleaned)
