# Public Web Extraction POC

This POC tests whether the Browserbase `browse` CLI can extract useful visible public web content for personal research, competitor research, market scanning, product design, and job-seeking support.

It is intentionally separate from `poc/browser_enrichment/`, which remains the job-page-only browser enrichment POC.

## POC Guardrails

- Public pages may be opened for observation and extraction.
- Pages with cookie banners may be opened, but the runner must not click accept or reject; it only records whether a banner appears.
- Pages that require login are marked `login_required` and skipped.
- Pages that show rate limit, 403, 404, expired, removed, or blocked are recorded as failed/skipped with a reason.
- Do not enter usernames, passwords, email addresses, phone numbers, or personal details.
- Do not use Mic's personal accounts.
- Do not accept cookies.
- Do not store persistent sessions.
- Do not use stealth mode, proxy rotation, CAPTCHA solving, or anti-bot bypass.
- Do not submit forms.
- Do not upload files.
- Do not click apply buttons.
- Do not auto-apply.
- Do not perform purchases, subscriptions, messages, follows, likes, comments, bookings, or account actions.
- Do not modify remote website state.
- Do not run uncontrolled crawling. Only visit URLs explicitly listed in `candidate_pages.json`.
- Do not print secrets, API keys, cookies, or tokens.

## Safety Model

This POC may observe public pages and extract visible text/metadata. It must not bypass controls or perform actions.

## Files

- `candidate_pages.json`: explicit candidate URL list and assigned categories.
- `config.example.json`: read-only safety config.
- `run_preflight.py`: checks candidate reachability and basic public-content gates.
- `run_live_extraction.py`: opens only preflight-passed candidates with Browse CLI.
- `content_extractor.py`: read-only Browse CLI extraction helper.
- `extraction_quality.py`: deterministic scoring.
- `report_writer.py`: writes the Markdown summary.

## Commands

```bash
python3.14 poc/public_web_extraction/run_preflight.py
python3.14 poc/public_web_extraction/run_live_extraction.py
python3.14 -m pytest poc/public_web_extraction/tests -v
```

## Recommendation Rules

- `GO`: at least 5 public pages extracted successfully, average quality score >= 70, and safety violations = 0.
- `REVISE`: 2-4 pages extracted successfully, or average quality score < 70.
- `STOP`: any safety violation, or 0 successful extractions.
