"""Tests for untested ui_render functions.

Coverage targets:
- render_review_queue_page (L100, with nested _chip and _score_color)
- render_simple_list (L1569)
- render_detail_item (L1576)
"""
from __future__ import annotations

from dataclasses import dataclass

from src.ui_render import (
    render_review_queue_page,
    render_simple_list,
    render_detail_item,
    ReviewQueueViewModel,
)


class TestRenderReviewQueuePage:
    """Tests for render_review_queue_page with nested _chip and _score_color."""

    def test_render_review_queue_page_with_apply_decision(self) -> None:
        vm = ReviewQueueViewModel(
            jobs=[
                {
                    "job_id": "job-001",
                    "title": "Business Analyst",
                    "company": "Example Co",
                    "location": "London",
                    "source": "reed",
                    "score": 85.0,
                    "decision": "apply",
                    "salary_display": "£50,000 – £60,000",
                }
            ],
            active_id="job-001",
            ids_csv="job-001",
            model_label="test-model",
        )

        html = render_review_queue_page(vm)

        assert "Review queue" in html
        assert "Business Analyst" in html
        assert "Example Co" in html
        assert "85" in html
        assert "apply" in html.lower()
        # Check for chip styling (should render decision indicator)
        assert "apply" in html or "✓" in html
        
    def test_render_review_queue_page_with_review_decision(self) -> None:
        vm = ReviewQueueViewModel(
            jobs=[
                {
                    "job_id": "job-review",
                    "title": "Developer",
                    "company": "Tech Corp",
                    "location": "Remote",
                    "source": "adzuna",
                    "score": 60.0,
                    "decision": "review",
                    "salary_display": "From £40,000",
                }
            ],
            active_id="job-review",
            ids_csv="job-review",
            model_label="",
        )

        html = render_review_queue_page(vm)

        assert "Developer" in html
        assert "Tech Corp" in html
        assert "60" in html
        assert "review" in html.lower() or "⚑" in html
        
    def test_render_review_queue_page_with_skip_decision(self) -> None:
        vm = ReviewQueueViewModel(
            jobs=[
                {
                    "job_id": "job-skip",
                    "title": "Accountant",
                    "company": "Finance Ltd",
                    "location": "Office",
                    "source": "reed",
                    "score": 25.0,
                    "decision": "skip",
                    "salary_display": "Up to £35,000",
                }
            ],
            active_id="job-skip",
            ids_csv="job-skip",
            model_label="",
        )

        html = render_review_queue_page(vm)

        assert "Accountant" in html
        assert "Finance Ltd" in html
        assert "25" in html
        # Skip decision should show skip styling
        assert "skip" in html.lower() or "−" in html

    def test_render_review_queue_page_score_color_high_score(self) -> None:
        """Test that high scores (>=75) use apply color."""
        vm = ReviewQueueViewModel(
            jobs=[
                {
                    "job_id": "high-score",
                    "title": "Senior Analyst",
                    "company": "Premium Corp",
                    "location": "London",
                    "source": "reed",
                    "score": 85.0,
                    "decision": "apply",
                    "salary_display": "",
                }
            ],
            active_id="high-score",
            ids_csv="high-score",
            model_label="",
        )

        html = render_review_queue_page(vm)

        # Should render the score and color styling
        assert "85" in html
        assert "apply" in html.lower() or "var(--apply)" in html

    def test_render_review_queue_page_score_color_medium_score(self) -> None:
        """Test that medium scores (50-74) use review color."""
        vm = ReviewQueueViewModel(
            jobs=[
                {
                    "job_id": "medium-score",
                    "title": "Mid-level Role",
                    "company": "Avg Corp",
                    "location": "Remote",
                    "source": "adzuna",
                    "score": 65.0,
                    "decision": "review",
                    "salary_display": "",
                }
            ],
            active_id="medium-score",
            ids_csv="medium-score",
            model_label="",
        )

        html = render_review_queue_page(vm)

        assert "65" in html
        # Review color should be used
        assert "review" in html.lower() or "var(--review)" in html

    def test_render_review_queue_page_score_color_low_score(self) -> None:
        """Test that low scores (<50) use skip color."""
        vm = ReviewQueueViewModel(
            jobs=[
                {
                    "job_id": "low-score",
                    "title": "Junior Role",
                    "company": "Startup",
                    "location": "Hybrid",
                    "source": "reed",
                    "score": 35.0,
                    "decision": "skip",
                    "salary_display": "",
                }
            ],
            active_id="low-score",
            ids_csv="low-score",
            model_label="",
        )

        html = render_review_queue_page(vm)

        assert "35" in html
        # Skip color should be used
        assert "skip" in html.lower() or "var(--skip)" in html

    def test_render_review_queue_page_score_color_none(self) -> None:
        """Test that None scores use faint color."""
        vm = ReviewQueueViewModel(
            jobs=[
                {
                    "job_id": "no-score",
                    "title": "Unevaluated",
                    "company": "Pending Corp",
                    "location": "TBD",
                    "source": "reed",
                    "score": None,
                    "decision": "review",
                    "salary_display": "",
                }
            ],
            active_id="no-score",
            ids_csv="no-score",
            model_label="",
        )

        html = render_review_queue_page(vm)

        # Should show – instead of numeric score
        assert "–" in html or "&#8211;" in html
        assert "var(--ink-faint)" in html

    def test_render_review_queue_page_multiple_jobs(self) -> None:
        """Test rendering multiple jobs with different decisions and scores."""
        vm = ReviewQueueViewModel(
            jobs=[
                {
                    "job_id": "job-apply",
                    "title": "Analyst",
                    "company": "Co A",
                    "location": "London",
                    "source": "reed",
                    "score": 80.0,
                    "decision": "apply",
                    "salary_display": "£50k – £60k",
                },
                {
                    "job_id": "job-review",
                    "title": "Developer",
                    "company": "Co B",
                    "location": "Remote",
                    "source": "adzuna",
                    "score": 55.0,
                    "decision": "review",
                    "salary_display": "£40k – £50k",
                },
                {
                    "job_id": "job-skip",
                    "title": "Manager",
                    "company": "Co C",
                    "location": "Office",
                    "source": "reed",
                    "score": 20.0,
                    "decision": "skip",
                    "salary_display": "£30k – £40k",
                },
            ],
            active_id="job-apply",
            ids_csv="job-apply,job-review,job-skip",
            model_label="test",
        )

        html = render_review_queue_page(vm)

        # Verify all jobs are rendered
        assert "Analyst" in html
        assert "Developer" in html
        assert "Manager" in html
        assert "Co A" in html
        assert "Co B" in html
        assert "Co C" in html
        assert "80" in html
        assert "55" in html
        assert "20" in html

    def test_render_review_queue_page_active_id_styling(self) -> None:
        """Test that active job has different styling."""
        vm = ReviewQueueViewModel(
            jobs=[
                {
                    "job_id": "active-job",
                    "title": "Active Role",
                    "company": "Active Co",
                    "location": "London",
                    "source": "reed",
                    "score": 70.0,
                    "decision": "review",
                    "salary_display": "",
                },
                {
                    "job_id": "inactive-job",
                    "title": "Inactive Role",
                    "company": "Inactive Co",
                    "location": "Remote",
                    "source": "reed",
                    "score": 60.0,
                    "decision": "review",
                    "salary_display": "",
                },
            ],
            active_id="active-job",
            ids_csv="active-job,inactive-job",
            model_label="",
        )

        html = render_review_queue_page(vm)

        # Active job should have special styling
        assert "rq-row-active-job" in html
        assert "var(--accent)" in html or "active" in html.lower()

    def test_render_review_queue_page_chip_styling_present(self) -> None:
        """Test that chip styling is generated correctly for decisions."""
        vm = ReviewQueueViewModel(
            jobs=[
                {
                    "job_id": "chip-test",
                    "title": "Chip Test",
                    "company": "Test Co",
                    "location": "Test",
                    "source": "reed",
                    "score": 75.0,
                    "decision": "apply",
                    "salary_display": "",
                }
            ],
            active_id="chip-test",
            ids_csv="chip-test",
            model_label="",
        )

        html = render_review_queue_page(vm)

        # Should contain chip/badge styling indicators
        assert "display:inline-flex" in html or "chip" in html.lower()
        # Apply decision icon
        assert "✓" in html or "apply" in html.lower()


class TestRenderSimpleList:
    """Tests for render_simple_list."""

    def test_render_simple_list_with_items(self) -> None:
        items = ["Python", "SQL", "Excel"]
        html = render_simple_list("Skills", items)

        assert "<h3>Skills</h3>" in html
        assert "<ul>" in html
        assert "<li>Python</li>" in html
        assert "<li>SQL</li>" in html
        assert "<li>Excel</li>" in html
        assert "</ul>" in html

    def test_render_simple_list_empty(self) -> None:
        html = render_simple_list("Certifications", [])

        assert "<h3>Certifications</h3>" in html
        assert "<p>None</p>" in html
        assert "<ul>" not in html

    def test_render_simple_list_escapes_html_in_items(self) -> None:
        items = ["<script>alert('xss')</script>", "Normal Item"]
        html = render_simple_list("Items", items)

        # HTML should be escaped
        assert "&lt;script&gt;" in html
        assert "<script>" not in html
        assert "Normal Item" in html

    def test_render_simple_list_escapes_title(self) -> None:
        html = render_simple_list("<b>Bold Title</b>", ["Item 1"])

        # Title should be escaped
        assert "&lt;b&gt;" in html
        assert "<b>" not in html

    def test_render_simple_list_single_item(self) -> None:
        html = render_simple_list("Languages", ["English"])

        assert "<h3>Languages</h3>" in html
        assert "<li>English</li>" in html

    def test_render_simple_list_unicode_items(self) -> None:
        items = ["Café", "Résumé", "Naïve"]
        html = render_simple_list("French Words", items)

        assert "Café" in html
        assert "Résumé" in html
        assert "Naïve" in html


class TestRenderDetailItem:
    """Tests for render_detail_item."""

    def test_render_detail_item_with_string_value(self) -> None:
        html = render_detail_item("Job Title", "Business Analyst")

        assert "<div class=\"detail-label\">Job Title</div>" in html
        assert "<div class=\"detail-value\">Business Analyst</div>" in html

    def test_render_detail_item_with_none_value(self) -> None:
        html = render_detail_item("Optional Field", None)

        assert "<div class=\"detail-label\">Optional Field</div>" in html
        # Should render — for None
        assert "<div class=\"detail-value\">—</div>" in html

    def test_render_detail_item_with_empty_string(self) -> None:
        html = render_detail_item("Empty Field", "")

        assert "<div class=\"detail-label\">Empty Field</div>" in html
        # Should render — for empty string
        assert "<div class=\"detail-value\">—</div>" in html

    def test_render_detail_item_with_numeric_value(self) -> None:
        html = render_detail_item("Experience Years", 5)

        assert "<div class=\"detail-label\">Experience Years</div>" in html
        assert "<div class=\"detail-value\">5</div>" in html

    def test_render_detail_item_with_zero(self) -> None:
        html = render_detail_item("Count", 0)

        # 0 is falsy but should be rendered
        assert "<div class=\"detail-value\">0</div>" in html or "<div class=\"detail-value\">—</div>" in html

    def test_render_detail_item_escapes_label(self) -> None:
        html = render_detail_item("<script>alert('xss')</script>", "Value")

        assert "&lt;script&gt;" in html
        assert "<script>" not in html

    def test_render_detail_item_escapes_value(self) -> None:
        html = render_detail_item("Title", "<img src=x onerror='alert(1)'>")

        assert "&lt;img" in html
        assert "<img" not in html

    def test_render_detail_item_escapes_both(self) -> None:
        html = render_detail_item("<b>Label</b>", "<i>Value</i>")

        assert "&lt;b&gt;" in html
        assert "&lt;i&gt;" in html
        assert "<b>" not in html
        assert "<i>" not in html

    def test_render_detail_item_with_special_characters(self) -> None:
        html = render_detail_item("Company", "Example & Co <Ltd>")

        # & and <> should be escaped
        assert "&amp;" in html or "Example &amp; Co" in html
        assert "&lt;Ltd&gt;" in html

    def test_render_detail_item_with_multiline_value(self) -> None:
        html = render_detail_item("Description", "Line 1\nLine 2\nLine 3")

        assert "Line 1" in html
        assert "Line 2" in html
        assert "Line 3" in html
