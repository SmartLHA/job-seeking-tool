# Browser Enrichment POC Design

## Problem

The Job Seeking Tool sometimes receives incomplete official-source job records. The POC must test whether browse.sh or Browserbase can improve incomplete public records without changing the MVP sourcing model.

## Product Boundary

Official MVP sources remain:

- Reed API
- Adzuna API
- Manual job input fallback

Browser enrichment is optional and enrichment-only. It must not become a primary scraper, source discovery mechanism, application bot, or bypass mechanism.

## Strict Exclusions

- No LinkedIn, Indeed, or Glassdoor browsing.
- No CAPTCHA, login wall, paywall, bot-protection, or anti-automation bypass.
- No stealth mode.
- No persistent login or cookie sessions.
- No auto-apply.
- No CV upload.
- No form submission.
- No unknown domains outside the allowlist.

## Target Scope

Create a self-contained POC under:

```text
poc/browser_enrichment/
```

The POC should contain configuration, sample normalized jobs, deterministic quality scoring, domain policy gates, a dry-run BrowserEnrichmentAgent, a runner, report writer, generated output files, and pytest coverage.

## Required Files

```text
poc/browser_enrichment/
├── README.md
├── config.example.json
├── sample_jobs.json
├── expected_schema.json
├── run_poc.py
├── browser_enrichment_agent.py
├── source_quality.py
├── domain_policy.py
├── report_writer.py
├── output/
│   ├── enriched_jobs.json
│   ├── poc_report.md
│   ├── screenshots/
│   └── snapshots/
└── tests/
    ├── test_domain_policy.py
    ├── test_source_quality.py
    ├── test_enrichment_schema.py
    └── test_decision_gating.py
```

## Implementation Plan

1. Create the POC folder under the project workspace, not the OpenClaw workspace root.
2. Implement `source_quality.py` with deterministic scoring:
   - +30 if description exists and length is at least 800 characters
   - +20 if company exists
   - +15 if salary exists
   - +15 if location exists
   - +10 if apply_url exists
   - +10 if contract_type or job_type exists
3. Implement `domain_policy.py`:
   - `extract_domain(url)`
   - `domain_is_allowed(domain, allowlist)`
   - `domain_is_blocked(domain, blocklist)`
   - `should_enrich(job, config)`
4. Ensure blocklisted domains are rejected before any browser, fetch, or extraction call can occur.
5. Implement dry-run `BrowserEnrichmentAgent` only. It may simulate extracted fields for allowed low-quality sample jobs.
6. Recalculate source quality after enrichment.
7. Preserve per-job failure isolation: one failed enrichment must not stop the full run.
8. Implement `run_poc.py` to load `config.local.json` if present, otherwise `config.example.json`, run dry-run enrichment, write `output/enriched_jobs.json`, write `output/poc_report.md`, and print a terminal summary.
9. Implement the requested pytest coverage.
10. Do not run real browse.sh / Browserbase until dry-run tests pass.

## Test Plan

Scout should run:

```bash
cd "/Users/lhaclaw/.openclaw/workspace/Job Seeking Tool" && python3 -m pytest poc/browser_enrichment/tests -v --tb=short
cd "/Users/lhaclaw/.openclaw/workspace/Job Seeking Tool" && python3 poc/browser_enrichment/run_poc.py
```

If dry-run tests pass, Scout may check CLI availability only:

```bash
which browse
browse --help
browse skills --help
```

Live extraction is gated separately. Do not access LinkedIn, Indeed, Glassdoor, login-required pages, or form-submission pages.

## Acceptance Criteria

- POC folder exists at the requested project path.
- All dry-run tests pass.
- Blocklist works before any browser or fetch call.
- Low-quality allowlisted records are enriched.
- Full-quality records are skipped.
- `output/enriched_jobs.json` is generated.
- `output/poc_report.md` is generated.
- No LinkedIn, Indeed, or Glassdoor browsing.
- No persistent login/cookies.
- No stealth mode.
- No auto-apply or form submission.
- No production pipeline integration.

## Required Final Recommendation

SilverHand must report one of:

- `GO`: dry-run POC is safe to keep as a controlled enrichment experiment.
- `REVISE`: implementation or safety posture needs changes before live browsing.
- `STOP`: POC violates the product or safety boundary.
