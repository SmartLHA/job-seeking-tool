from __future__ import annotations

import re


def score_cv(cv_text: str, job_keywords: list[str]) -> dict[str, float | int]:
    """
    Score a CV/cover letter on how well it parses through an ATS screening system.

    Args:
        cv_text: Raw text content of the CV/cover letter.
        job_keywords: List of keyword strings from the job posting to check against.

    Returns:
        Dictionary with overall score (0-100) and four metric scores (0-25 each):
        {
            "overall": int,           # sum of all 4, max 100
            "keyword_density": float, # 0-25
            "format_score": int,      # 0-25
            "section_presence": int,   # 0-25
            "length_score": int        # 0-25
        }
    """
    keyword_density = _score_keyword_density(cv_text, job_keywords)
    format_score = _score_format(cv_text)
    section_presence = _score_section_presence(cv_text)
    length_score = _score_length(cv_text)

    overall = keyword_density + format_score + section_presence + length_score

    return {
        "overall": int(overall),
        "keyword_density": keyword_density,
        "format_score": format_score,
        "section_presence": section_presence,
        "length_score": length_score,
    }


def _score_keyword_density(cv_text: str, job_keywords: list[str]) -> float:
    """Keyword density: matched keywords / total keywords, scaled to 0-25."""
    if not job_keywords:
        return 25.0

    cv_lower = cv_text.lower()
    matched = sum(1 for kw in job_keywords if kw.lower() in cv_lower)
    return (matched / len(job_keywords)) * 25.0


def _score_format(cv_text: str) -> int:
    """
    Format score: plain text friendly = 25, tables/columns/headers = 0.
    Checks for: <table, | (pipe tables), multi-column layouts, section headers.
    """
    text_lower = cv_text.lower()

    # Check for HTML table tags
    if re.search(r"<table", text_lower) or re.search(r"</table>", text_lower):
        return 0

    # Check for pipe-table characters (| col | col |)
    if re.search(r"\|\s*\S+\s*\|", cv_text):
        return 0

    # Check for multi-column layout indicators (multiple spaces used as tabula alignment)
    # e.g., "Name    John    Surname    Doe"
    lines = cv_text.splitlines()
    for line in lines:
        # If line has large whitespace gaps suggesting columnar alignment
        if re.search(r" {4,}", line):
            return 0

    # QW-2: ALL-CAPS section headings (SKILLS / EXPERIENCE / EDUCATION) are the
    # standard, ATS-friendly format — they must NOT be penalised. The previous
    # code returned 0 here, scoring well-structured CVs *below* unstructured text.

    return 25


def _score_section_presence(cv_text: str) -> int:
    """
    Section presence: each detected section (summary, experience, skills) = 8pt, max 25.
    Uses regex to detect presence of key CV sections.
    """
    text_lower = cv_text.lower()

    score = 0

    # Summary/Profile section - use word boundary for "summary"
    if re.search(r"\bsummary\b", text_lower):
        score += 8

    # Experience/Employment section - use word boundary
    if re.search(r"\bexperience\b", text_lower):
        score += 8

    # Skills section - use word boundary
    if re.search(r"\bskills\b", text_lower):
        score += 9  # 9 to reach max 25 with 3 sections (8+8+9=25)

    return min(score, 25)


def _score_length(cv_text: str) -> int:
    """
    Length score: word count 300-800 = 25, outside this range = 0.
    """
    words = cv_text.split()
    count = len(words)

    if 300 <= count <= 800:
        return 25

    return 0