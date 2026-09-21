"""Regression tests for the shared multi-select / load-more module.

After consolidating Reed and Adzuna onto ``src/job_sources/_multiselect.py``
(LinkedIn already used it), every source's search-results HTML must wire up the
same browser contract. These tests assert that contract directly rather than
diffing the ~6KB JS blob, so harmless JS edits don't cause false failures while a
genuinely broken "More jobs" button (e.g. a missing ``jstLoadMore`` definition,
the latent Adzuna bug this work fixed) is still caught.
"""
from __future__ import annotations

from src.job_sources import _multiselect as M
from src.job_sources.adzuna_source import render_adzuna_search_results
from src.job_sources.linkedin_source import render_results as render_linkedin
from src.job_sources.reed_source import render_reed_search_results

_REED = {
    "source": "reed", "source_job_id": "1", "title": "T", "company": "C",
    "location": "London", "salary_display": "£50k", "employment_type": "permanent",
    "work_mode": "remote", "url": "https://example.test/y", "description_preview": "d",
    "description_raw": "d", "filter_notes": [], "source_snapshot_json": "",
}
_ADZUNA = {k: v for k, v in _REED.items() if k != "source_snapshot_json"}
_ADZUNA["source"] = "adzuna"
_LINKEDIN = {
    "source": "linkedin", "source_job_id": "1", "title": "T", "company": "C",
    "location": "London", "salary_display": "", "salary_min_gbp": None,
    "salary_max_gbp": None, "employment_type": "", "work_mode": "Remote",
    "url": "https://www.linkedin.com/jobs/view/1/", "description_preview": "d",
    "description_raw": "", "filter_notes": "LinkedIn does not provide salary.",
}


def _render_all_with_more():
    return {
        "reed": render_reed_search_results(
            [_REED], reed_error=None, reed_select_nonce="n", more_url="/search/reed/more?a=1"),
        "adzuna": render_adzuna_search_results(
            [_ADZUNA], adzuna_error=None, adzuna_select_nonce="n", more_url="/search/adzuna/more?a=1"),
        "linkedin": render_linkedin(
            [_LINKEDIN], None, "n", more_url="/search/linkedin/more?a=1"),
    }


def test_every_source_wires_the_load_more_contract() -> None:
    # The button calls jstLoadMore(this); jstLoadMore must be defined; the button
    # must carry the data-next-url the loader reads. This is exactly the contract
    # Adzuna silently violated before consolidation.
    for source, html in _render_all_with_more().items():
        assert 'onclick="jstLoadMore(this)"' in html, f"{source}: button not wired"
        assert "window.jstLoadMore=function(btn)" in html, f"{source}: jstLoadMore undefined"
        assert "data-next-url=" in html, f"{source}: missing data-next-url"


def test_sources_share_the_single_multiselect_source_of_truth() -> None:
    # Reed/Adzuna/LinkedIn must all embed the *shared* JS + overlay + action bar,
    # not a private copy that can drift.
    for source, html in _render_all_with_more().items():
        assert M.MULTISELECT_JS in html, f"{source}: not using shared MULTISELECT_JS"
        assert M.STAGING_OVERLAY in html, f"{source}: not using shared STAGING_OVERLAY"
        assert M.ACTION_BAR in html, f"{source}: not using shared ACTION_BAR"


def test_no_more_button_when_more_url_absent() -> None:
    # With more_url=None the button (and only the button) disappears; the JS is
    # still present so already-rendered cards stay selectable.
    html = render_reed_search_results([_REED], reed_error=None, reed_select_nonce="n", more_url=None)
    assert 'onclick="jstLoadMore(this)"' not in html
    assert "window.jstLoadMore=function(btn)" in html  # loader still defined, just unused
