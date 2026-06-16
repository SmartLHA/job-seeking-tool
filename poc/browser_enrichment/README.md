# Browser Enrichment POC

Controlled dry-run proof of concept for optional browser-based enrichment of incomplete public job records.

## Boundary

Official MVP sources remain Reed API, Adzuna API, and manual input fallback. This POC is enrichment-only for incomplete public records and is not a source discovery crawler or application bot.

The dry-run simulation performs no actual network requests. It does not call `browse.sh`, Browserbase, Playwright, requests, curl, or any live browser. Enrichment is deterministic local data generation after policy gates pass.

`config.example.json` defaults `browser_enrichment_enabled` to `false`. The standalone runner enables only the local dry-run simulation path at runtime so the POC can produce sample output without enabling live browser enrichment.

## Safety Rules

- Do not scrape LinkedIn, Indeed, or Glassdoor.
- Do not bypass CAPTCHA, login walls, paywalls, bot protection, or anti-automation controls.
- Do not use stealth mode.
- Do not use persistent login or cookie sessions.
- Do not auto-apply, upload CVs, submit forms, or browse unknown domains.
- Blocklisted domains are rejected before the enrichment hook can run.

## Quality Gates

- `quality_score >= 70`: normal analysis, enrichment skipped.
- `quality_score 40-69`: analysis allowed, Apply gated to Review.
- `quality_score < 40`: skip/manual enrichment.

Scoring is deterministic:

- +30 description length >= 800
- +20 company
- +15 salary
- +15 location
- +10 apply_url
- +10 contract_type or job_type

## Run

```bash
cd "/Users/lhaclaw/.openclaw/workspace/Job Seeking Tool"
python3.14 poc/browser_enrichment/run_poc.py
```

The runner loads `config.local.json` when present, otherwise `config.example.json`.

## Test

```bash
cd "/Users/lhaclaw/.openclaw/workspace/Job Seeking Tool"
python3.14 -m pytest poc/browser_enrichment/tests -v --tb=short
```
