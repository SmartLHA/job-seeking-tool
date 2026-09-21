"""Slice A (2026-07-21 search/score/filter plan): local relevance filter.

Fixture required by the plan's acceptance criteria: searching "Business
Analysis" must bucket "Store Manager" into Other results while keeping
"Business Analyst", "BA" and "Senior BA" in main results.
"""
from __future__ import annotations

from src.job_sources.relevance import (
    bucket_jobs_by_relevance,
    is_relevant_description,
    is_relevant_title,
)


def _job(title, description="A generic role description with no special terms."):
    return {"title": title, "description": description}


def test_business_analysis_query_matches_ba_variants_not_store_manager():
    query = "Business Analysis"
    jobs = [
        _job("Business Analyst"),
        _job("BA"),
        _job("Senior BA"),
        _job("Store Manager"),
    ]

    matches, other = bucket_jobs_by_relevance(jobs, query)

    match_titles = {j["title"] for j in matches}
    other_titles = {j["title"] for j in other}
    assert match_titles == {"Business Analyst", "BA", "Senior BA"}
    assert other_titles == {"Store Manager"}


def test_never_hard_drops_every_job_ends_up_somewhere():
    jobs = [_job("Business Analyst"), _job("Store Manager"), _job("Warehouse Operative")]
    matches, other = bucket_jobs_by_relevance(jobs, "Business Analysis")
    assert len(matches) + len(other) == len(jobs)


def test_blank_query_treats_everything_as_relevant():
    jobs = [_job("Business Analyst"), _job("Store Manager")]
    matches, other = bucket_jobs_by_relevance(jobs, "")
    assert len(matches) == 2
    assert other == []


def test_title_is_primary_signal():
    # Title has no overlap and description also has no overlap -> Other.
    assert is_relevant_title("Store Manager", "Business Analysis") is False
    # Title itself matches directly.
    assert is_relevant_title("Business Analyst", "Business Analysis") is True


def test_description_is_weak_secondary_signal_only_when_title_fails():
    # Title mismatches, but description literally contains a query content
    # word ("analysis") -> rescued into matches via the weak secondary signal.
    job = _job(
        "Office Coordinator",
        description="Supports the business analysis team with scheduling and admin.",
    )
    matches, other = bucket_jobs_by_relevance([job], "Business Analysis")
    assert matches == [job]
    assert other == []


def test_description_signal_requires_exact_unstemmed_word():
    # is_relevant_description is deliberately stricter than the title check:
    # no stemming, so a related-but-different word does not rescue a job.
    assert is_relevant_description("We need an analytical thinker.", "Business Analysis") is False
    assert is_relevant_description("This covers business operations.", "Business Analysis") is True


def test_derived_acronym_is_not_hardcoded_to_business_analyst():
    # The acronym is derived from whatever query is given, not a fixed BA
    # alias table — e.g. "Quality Assurance" -> "qa".
    jobs = [_job("QA Engineer"), _job("Quality Assurance Lead"), _job("Store Manager")]
    matches, other = bucket_jobs_by_relevance(jobs, "Quality Assurance")
    match_titles = {j["title"] for j in matches}
    assert match_titles == {"QA Engineer", "Quality Assurance Lead"}
    assert {j["title"] for j in other} == {"Store Manager"}


def test_punctuation_and_plural_variants_normalise():
    jobs = [_job("Business-Analyst"), _job("Business Analysts")]
    matches, _other = bucket_jobs_by_relevance(jobs, "Business Analysis")
    assert {j["title"] for j in matches} == {"Business-Analyst", "Business Analysts"}
