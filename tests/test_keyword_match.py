"""Tests for the per-job ATS keyword match (F1)."""
from __future__ import annotations

import pytest

from src.job_hunt_keyword_match import compute_keyword_match


def test_basic_required_preferred_split_and_rate() -> None:
    cv = "Experienced Business Analyst skilled in SQL and stakeholder management."
    r = compute_keyword_match(cv, ["SQL", "Python"], ["Stakeholder Management", "Tableau"])
    assert r.required_matched == ["SQL"]
    assert r.required_missing == ["Python"]
    assert r.preferred_matched == ["Stakeholder Management"]
    assert r.preferred_missing == ["Tableau"]
    # 2 of 4 present → 50
    assert r.match_rate == 50


def test_word_boundary_no_false_positives() -> None:
    # "R" must not match inside "React"; "BA" must not match inside "database".
    cv = "Built a React app backed by a database."
    r = compute_keyword_match(cv, ["R", "BA"], [])
    assert r.required_matched == []
    assert sorted(r.required_missing) == ["BA", "R"]
    assert r.match_rate == 0
    # but a standalone token matches
    assert compute_keyword_match("Modelling in R and SAS.", ["R"], []).required_matched == ["R"]


@pytest.mark.parametrize(
    "keyword,cv,present",
    [
        ("C#", "Backend in C# and .NET.", True),
        (".NET", "Backend in C# and .NET.", True),
        ("C++", "Wrote C++ for low-latency systems.", True),
        ("Node.js", "APIs with Node.js and Express.", True),
        ("CI/CD", "Owned the CI/CD pipeline.", True),
        ("Power BI", "Dashboards in Power BI.", True),
        ("SQL", "Strong SQL skills.", True),
        ("NoSQL", "Used NoSQL stores.", True),
        ("C#", "I know C and C++ well.", False),   # C# absent even though C/C++ present
        ("SQL", "Comfortable with NoSQL only.", False),  # SQL must not match inside NoSQL
    ],
)
def test_punctuation_heavy_keywords(keyword: str, cv: str, present: bool) -> None:
    r = compute_keyword_match(cv, [keyword], [])
    assert (r.required_matched == [keyword]) is present
    assert (r.match_rate == 100) is present


def test_required_wins_dedupe_no_double_count() -> None:
    # "SQL" in both lists → counted once, as required; suppressed from preferred.
    cv = "SQL everywhere."
    r = compute_keyword_match(cv, ["SQL"], ["sql", "Tableau"])
    assert r.required_matched == ["SQL"]
    assert "sql" not in r.preferred_matched and "sql" not in r.preferred_missing
    assert r.preferred_missing == ["Tableau"]
    # total keywords = SQL (req) + Tableau (pref) = 2; 1 present → 50
    assert r.match_rate == 50


def test_null_contract_no_keywords() -> None:
    r = compute_keyword_match("Some CV text", [], [])
    assert r.match_rate is None  # never 100
    assert r.required_missing == [] and r.preferred_missing == []


def test_null_contract_no_cv() -> None:
    r = compute_keyword_match(None, ["SQL"], ["Tableau"])
    assert r.match_rate is None
    assert r.required_missing == ["SQL"]
    assert r.preferred_missing == ["Tableau"]
    assert r.required_matched == []
    assert compute_keyword_match("   ", ["SQL"], []).match_rate is None


def test_overuse_flagged_above_threshold() -> None:
    cv = "SQL SQL SQL SQL SQL — definitely SQL."  # 6× SQL
    r = compute_keyword_match(cv, ["SQL"], [])
    assert "SQL" in r.overused
    # exactly at threshold (4) is NOT flagged
    cv4 = "SQL SQL SQL SQL."
    assert compute_keyword_match(cv4, ["SQL"], []).overused == []


def test_case_insensitive_matching() -> None:
    r = compute_keyword_match("strong python and sql", ["Python", "SQL"], [])
    assert r.required_matched == ["Python", "SQL"]
    assert r.match_rate == 100
