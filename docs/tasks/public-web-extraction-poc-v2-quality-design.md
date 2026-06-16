# Public Web Extraction POC v2 Quality Design

Status: design draft for staged OpenClaw pipeline  
Owner: SilverHand  
Date: 2026-05-22  
Scope: private controlled research POC only

## Problem

The v1 public web extraction POC is approved for private controlled research, but extraction quality is still thin. It captures visible page content and basic signals, but it needs stronger useful-link capture, category-specific field extraction, cleaner text, per-page markdown exports, and a structured research summary artifact before any further decision.

## Confirmed Evidence

- Existing POC path: `/Users/lhaclaw/AI-Project-Workspace/job_hunt_Job Seeking Tool/poc/public_web_extraction/`
- Current v1 output files are internally consistent after the previous correction:
  - `output/candidate_preflight.json`
  - `output/extracted_pages.json`
  - `output/extraction_report.md`
- Current v1 safety fields already split form state into:
  - `forms_present`
  - `form_submission_required_to_view_content`
  - `form_interaction_performed`
- Current v1 tests were reported as `16/16` passing after the mismatch fix.

## Non-Goals

- No production integration.
- No account automation, login, cookie acceptance, form submission, file upload, persistent sessions, stealth mode, CAPTCHA solving, or account/state-changing actions.
- No automatic job application workflow.
- No broad crawler. Candidate URL list only.
- No paywall bypass or anti-bot bypass.

## Requirements

1. Expand candidates to 20 public candidate pages.
2. Extract at most 10 pages per run.
3. Improve link extraction so useful links are captured and classified.
4. Add category-specific extraction profiles for:
   - `product_homepage`
   - `pricing_page`
   - `blog_article`
   - `careers_landing`
   - `company_about`
   - `documentation`
5. Add text cleanup:
   - remove animation and letter-spaced artifacts
   - remove repeated cookie banner text from `main_content`
   - deduplicate headings
   - remove duplicated navigation/footer blocks where possible
6. Add one markdown export per successfully extracted page.
7. Add `output/research_summary.json` with one object per successful extracted page containing:
   - `url`
   - `domain`
   - `category`
   - `title`
   - `concise_summary`
   - `key_claims`
   - `features`
   - `pricing_signals`
   - `job_career_signals`
   - `useful_links`
   - `confidence_score`
8. Add `output/extraction_report_v2.md` summary.
9. Add tests for:
   - link extraction
   - text cleanup
   - category-specific extraction
   - markdown export
   - `research_summary.json` schema

## Proposed Implementation

Keep the POC self-contained under `poc/public_web_extraction/`.

Recommended new or changed modules:

- `content_extractor.py`
  - Keep Browse CLI read-only flow.
  - Use extracted DOM link data plus snapshot fallback.
  - Normalize and clean extracted text before record construction.
  - Continue to enforce safety metadata defaults.
- `text_cleanup.py`
  - Normalize whitespace.
  - Collapse letter-spaced artifacts such as `N o t i o n`.
  - Remove repeated cookie/banner phrases.
  - Deduplicate repeated heading and nav/footer blocks.
- `link_extractor.py`
  - Normalize URLs.
  - Drop empty, duplicate, fragment-only, javascript, mailto, and low-value links.
  - Classify links by usefulness: docs, pricing, careers, about, contact, support, product, blog, API, legal.
  - Keep source text and resolved URL.
- `extraction_profiles.py`
  - Per-category field extraction rules using deterministic text/link heuristics.
  - Return `key_claims`, `features`, `pricing_signals`, `job_career_signals`, and category confidence hints.
- `markdown_exporter.py`
  - Export one `.md` per successful page under `output/markdown/`.
  - Include URL, domain, category, title, summary, key claims, useful links, and cleaned content excerpt.
- `research_summary.py`
  - Build `output/research_summary.json`.
  - Keep schema deterministic and compact.
- `report_writer.py`
  - Add v2 report writer or parameterized report path for `extraction_report_v2.md`.

## Safety Constraints

Implementation must preserve:

- public pages only
- candidate list only
- no login
- no cookie acceptance
- no persistent sessions
- no stealth mode
- no form submission
- no file upload
- no CAPTCHA solving
- no account/state-changing actions

`login_required` must mean core content is blocked behind login, not that a page merely contains a sign-in link.

## Acceptance Criteria

- `candidate_pages.json` contains exactly 20 candidates.
- `config.example.json` keeps `max_pages_per_run` at 10.
- Running `python3.14 poc/public_web_extraction/run_preflight.py` succeeds and writes `output/candidate_preflight.json`.
- Running `python3.14 poc/public_web_extraction/run_live_extraction.py` succeeds and writes:
  - `output/extracted_pages.json`
  - `output/research_summary.json`
  - `output/extraction_report_v2.md`
  - `output/markdown/*.md` for successful pages
- Running `python3.14 -m pytest poc/public_web_extraction/tests -v` passes.
- Safety result remains zero for:
  - cookies accepted
  - form submitted / form interaction performed
  - persistent session used
  - stealth mode used
  - CAPTCHA solved
  - account/state-changing actions
  - safety violations

## Test Plan

Add focused unit tests under `poc/public_web_extraction/tests/`:

- `test_link_extractor.py`
  - useful links retained and classified
  - duplicate and unsafe links removed
- `test_text_cleanup.py`
  - cookie text removed
  - letter-spaced artifacts collapsed
  - headings deduplicated
  - repeated nav/footer content reduced
- `test_extraction_profiles.py`
  - category-specific profile fields populate for representative text/link fixtures
- `test_markdown_export.py`
  - per-page markdown file is generated with expected front matter/sections
- `test_research_summary.py`
  - schema fields exist
  - summary only includes successful pages
  - confidence score comes from extraction quality

## Required Final Evidence

Final report to Mic must include:

- files changed
- commands used
- test result
- `extraction_report_v2.md` summary
- sample `research_summary.json` entries
- remaining limitations
- recommendation: GO / REVISE / STOP

