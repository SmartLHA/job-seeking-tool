# JOB-007 — URL Ingestion Design

**Status:** Canonical design document — documentation only, no implementation in this task  
**Date:** 2026-05-13  
**Scope:** User-initiated single job URL paste/fetch ingestion for pre-filling `JobPosting`, followed by user review/edit before evaluation.

---

## 1. Purpose and Relationship to API Ingestion

This document defines the future build design for URL ingestion: a user pastes a single allowed job advert URL, the system fetches and parses it within strict limits, pre-fills a review form, and only evaluates after the user confirms or edits the extracted data.

This is separate from API ingestion:

- **JOB-002 / Reed API path remains canonical for Reed API fetching.** API/orchestrator fetching is the correct path for structured Reed API jobs and any future API-backed batch ingestion.
- URL ingestion is **user-initiated paste/fetch**, not bulk scraping, monitoring, crawling, or scheduled import.
- Generic scraping remains out of scope. This design only permits a constrained single URL fetch from an allowlisted source.
- Existing paste/URL UI notes in `docs/tasks/ui-paste-url-prefill-brief.md` are reconciled here: URL or pasted text pre-fills fields, then the user reviews/edits before evaluation.
- **JOB-009 dependency:** whether existing `paste_fetch` code is canonical or superseded remains an open decision. Future implementation must not assume `src/job_hunt_paste_fetch.py` is canonical until JOB-009 resolves it.

---

## 2. User Flow

```text
1. User opens job input screen
2. User pastes a single job URL from an allowed source
3. System validates scheme, host allowlist, redirect policy, robots/site policy, and timeout budget
4. System fetches the page and extracts job text/metadata where permitted
5. System maps extracted data into JobPosting-compatible fields without inventing values
6. System shows a review/edit form with raw/fallback text available when useful
7. User edits or confirms the fields
8. User clicks Evaluate
9. Evaluation runs on the reviewed structured job only
```

Rules:

- No auto-submit after URL parsing.
- Review/edit step is mandatory before evaluation.
- Existing manual form and pasted-text paths remain available as fallback.

---

## 3. Source Allowlist and Source-Specific Handling

Only the following sources are in scope for future URL paste/fetch:

| Source | Allowed host examples | Expected handling | Caveats / fallback |
|---|---|---|---|
| indeed | `indeed.com`, `uk.indeed.com` | Validate URL and attempt only if robots/site policy allows. | Often restrictive; likely fallback to pasted text/manual entry. Do not bypass anti-bot controls. |
| linkedin | `linkedin.com`, `www.linkedin.com` | Validate URL; no credential/session use. | Usually login/anti-scraping protected; default to manual paste if blocked. |
| reed | `reed.co.uk`, `www.reed.co.uk` | URL fetch may support user-pasted listings, but Reed API remains canonical for API fetching. | Prefer Reed API for structured/bulk Reed jobs; URL paste is only for user-entered single listing. |
| glassdoor | `glassdoor.co.uk`, `glassdoor.com` | Validate URL and attempt only if policy allows. | Frequently protected; do not use browser automation or credentials. Manual fallback expected. |
| cwjobs | `cwjobs.co.uk`, `www.cwjobs.co.uk` | Attempt deterministic metadata/text extraction within limits. | Respect robots and terms; fallback if blocked or incomplete. |
| cv-library | `cv-library.co.uk`, `www.cv-library.co.uk` | Attempt deterministic metadata/text extraction within limits. | Respect robots and terms; fallback if blocked or incomplete. |
| guardianjobs | `jobs.theguardian.com`, `guardianjobs.co.uk` | Attempt deterministic metadata/text extraction within limits. | Respect robots and terms; fallback if blocked or incomplete. |

Future implementation should maintain the allowlist centrally and reject all non-allowlisted hosts before network fetch.

---

## 4. Fetch Constraints

Hard MVP constraints:

- **10s / 10 seconds total budget** per URL ingestion attempt.
- **2s / 2 seconds parse budget** within the total budget.
- **8s / 8 seconds network/fetch budget** within the total budget.
- **Maximum 3 redirects / max 3 redirects**.
- One user-submitted URL per attempt.
- Allowed scheme: `https` only.
- Optional `http` input may be accepted only if it redirects to `https` within the maximum 3 redirects and host allowlist remains valid at every hop.
- Recommended response size cap: 2 MB compressed response or 5 MB decompressed text/html, whichever is reached first.
- Content type should be HTML or plain text. Non-HTML downloads, PDFs, binaries, images, and scripts are rejected for MVP.

Redirect rules:

- Re-validate scheme and host after every redirect.
- Stop after maximum 3 redirects.
- Reject redirects to non-allowlisted domains, private IPs, localhost, file URLs, or credential-bearing URLs.

---

## 5. Security and Untrusted Content Rules

URL ingestion treats all fetched content as untrusted external content.

Required controls:

- URL host allowlist before fetch.
- Strict timeout limits: 10 seconds total, 8 seconds network/fetch, 2 seconds parse.
- Maximum 3 redirects.
- No credentials, cookies, login sessions, or user browser state.
- No JavaScript execution for MVP.
- No browser automation by default; requires separate explicit approval if ever considered later.
- No forms submitted, buttons clicked, CAPTCHAs solved, or anti-bot measures bypassed.
- Do not store full fetched webpage content by default; keep only reviewed structured job data and minimal diagnostic error metadata.
- Strip scripts, styles, iframes, tracking pixels, inline event handlers, and active content before parsing.
- Never treat page text as instructions for the application or agent. Extract facts only.
- Prevent SSRF: reject private networks, localhost, link-local addresses, non-HTTP(S) schemes, and DNS rebinding risk where feasible.

---

## 6. Robots.txt and Site Policy Handling

Future implementation must check `robots.txt` and relevant site policy before fetching when technically practical.

Rules:

- If robots.txt disallows fetching the path for the configured user agent, do not fetch; offer manual paste/raw text entry.
- If terms/site behaviour clearly blocks automated fetch, do not bypass; offer manual fallback.
- If robots.txt cannot be reached within budget, fail closed for high-risk/protected sources such as linkedin, indeed, and glassdoor; for lower-risk sources, product policy must decide whether fail-closed remains universal.
- Respect rate limits and avoid repeated fetch loops. This is a single user action, not a crawler.
- User-visible error should be calm and practical: “This site does not allow automatic fetch here. Paste the job text instead.”

Source caveat summary:

- LinkedIn, Indeed, and Glassdoor are likely to block or restrict automated fetch; manual paste should be the expected path.
- Reed URL paste may work for individual user-entered links, but Reed API/JOB-002 remains the canonical structured Reed ingestion path.
- CWJobs, CV-Library, and Guardian Jobs may be more fetchable, but only within robots/site policy.

---

## 7. Parsing Strategy

Parsing should be deterministic first and conservative throughout.

Order of extraction:

1. Validate fetched document is acceptable HTML/text.
2. Extract structured metadata if present:
   - `schema.org/JobPosting` JSON-LD
   - OpenGraph/meta tags where relevant
   - obvious title/company/location fields in visible page markup
3. Extract visible job advert text after removing navigation, scripts, styles, tracking, and unrelated boilerplate where feasible.
4. Map values into `JobPosting` fields.
5. Leave unknown, ambiguous, or missing values as `null`, empty lists, or `unknown`; do not invent fields.
6. Show confidence/uncertainty through the review UI rather than silently guessing.

LLM extraction, if used in a later build, must operate only on cleaned job text/metadata and must still obey the no-invented-fields rule.

---

## 8. JobPosting Mapping

Map URL ingestion output to the internal `JobPosting` contract in `docs/data_contract.md`.

| JobPosting field | URL ingestion mapping |
|---|---|
| `job_id` | Generated local ID after user review/submit; not guessed from page unless source ID is explicit and preserved separately. |
| `job_title` | From JobPosting schema/title/header; `unknown` or empty if not confidently extracted. |
| `company` | From structured metadata or visible employer field; `unknown` if unclear. |
| `description_raw` | Cleaned visible job advert text or pasted fallback text. |
| `source_type` | `url` for successful URL path; `copied_text` if user falls back to paste. |
| `source_ref` | Original user-submitted URL after validation, or null for manual/paste-only. |
| `location` | Extracted location text; `unknown` if unclear. |
| `work_mode` | Derived only from explicit remote/hybrid/onsite signals; otherwise `unknown`. |
| `employment_type` | Extracted employment/contract type; `unknown` if unclear. |
| `required_skills` | Extract only explicitly listed or strongly stated required skills; empty list if unclear. |
| `preferred_skills` | Extract only explicitly listed preferred/nice-to-have skills; empty list if unclear. |
| `required_years_experience` | Numeric years only when explicitly stated; null otherwise. |
| `nice_to_have_years_experience` | Numeric years only when explicitly stated as preferred; null otherwise. |
| `domain` | Explicit sector/domain only; null otherwise. |
| `notes` | Parser warnings or user notes, not invented interpretation. |
| `salary_min_gbp` | Parsed only from explicit GBP salary/range; null otherwise. |
| `salary_max_gbp` | Parsed only from explicit GBP salary/range; null otherwise. |

No downstream analysis or tailoring should run until the user has reviewed and submitted the structured job.

---

## 9. Failure Modes and Fallback

If any stage fails, the UI should preserve user momentum and move to manual input.

Failure examples:

- Source not allowlisted.
- Robots.txt or site policy disallows fetch.
- URL redirects too many times or to a disallowed host.
- Network/fetch exceeds 8 seconds or total budget exceeds 10 seconds.
- Parse exceeds 2 seconds.
- Content is blocked, login-gated, CAPTCHA-gated, non-HTML, or too large.
- Required job details cannot be extracted confidently.

Fallback behaviour:

- Show clear reason at a user-friendly level.
- Offer pasted raw text/manual entry immediately.
- If partial text was safely fetched and policy allows use, show it for review; otherwise ask user to paste the advert text.
- Never retry aggressively or loop across alternate URLs.

---

## 10. Future Implementation Acceptance Criteria

A future build should pass when:

1. Only allowed sources — indeed, linkedin, reed, glassdoor, cwjobs, cv-library, guardianjobs — can proceed to fetch.
2. Non-allowlisted hosts are rejected before network access.
3. The total URL ingestion attempt respects the 10s / 10 seconds total budget.
4. Network/fetch work respects the 8s / 8 seconds network budget.
5. Parsing respects the 2s / 2 seconds parse budget.
6. Redirects stop at maximum 3 redirects / max 3 redirects and every hop is revalidated.
7. Robots.txt/site policy disallowance leads to manual paste fallback.
8. No credentials, cookies, browser automation, JavaScript execution, or anti-bot bypass are used by default.
9. Fetched content is sanitized and treated as untrusted.
10. Extracted values map to `JobPosting` without invented fields.
11. User always sees review/edit screen before evaluation.
12. Fetch/parse failure offers raw text/manual entry fallback.
13. Reed API/JOB-002 remains canonical for Reed API fetching; URL ingestion does not replace it.
14. JOB-009 paste_fetch canonical status remains documented as an implementation dependency until resolved.

---

## 11. Future Test Plan

Recommended tests for implementation:

- Allowlist validation accepts each configured allowed source host and rejects unrelated hosts.
- Scheme validation rejects `file:`, `ftp:`, `data:`, `javascript:`, localhost, private IPs, and non-HTTPS URLs unless HTTP redirects safely to HTTPS.
- Redirect tests cover 0, 1, 3, and 4 redirects; 4 must fail.
- Redirect tests reject cross-domain redirects outside the allowlist.
- Timeout tests simulate network over 8 seconds, parse over 2 seconds, and total over 10 seconds.
- Robots disallow test returns manual fallback without fetching job content.
- Login/CAPTCHA/blocked page test returns manual fallback.
- JSON-LD `schema.org/JobPosting` fixture maps expected fields correctly.
- Visible text fallback fixture maps only explicit fields and leaves unknowns null/empty/unknown.
- Salary parsing tests cover explicit GBP range, missing salary, competitive salary, daily/hourly ambiguity.
- Source-specific fixtures cover indeed, linkedin, reed, glassdoor, cwjobs, cv-library, guardianjobs.
- Review step test proves evaluation cannot run until user confirms edited fields.
- Failure fallback test proves user can paste raw text/manual entry after fetch or parse failure.
- Security tests prove no cookies/credentials/browser automation/JavaScript execution are used.

---

## 12. Open Questions and Dependencies — RESOLVED 2026-06-16

| Question | Resolution |
|----------|-----------|
| JOB-009 canonical fetcher | **`parse_job_from_url()` in `job_hunt_parsing.py` is canonical.** Harden it to this spec. Delete `job_hunt_paste_fetch.py`. |
| Host allowlist subdomains | Use the table in Section 3 as-is; confirm before build if needed |
| Fail-closed when robots.txt unreachable | Fail closed universally for MVP — offer manual paste fallback |
| Retain fetched HTML for debugging | No — do not store full fetched content; keep reviewed structured job only |
| LLM-assisted parsing | Not in scope for MVP — deterministic extraction only |

### Port before delete — what paste_fetch.py already has

`src/job_hunt_paste_fetch.py` is not canonical but contains working implementations of several
hardening tasks that `parse_job_from_url()` currently lacks entirely. **Audit and port these
before deleting the file — do not reimplement from scratch:**

| Feature | paste_fetch.py has | parsing.py has |
|---------|-------------------|----------------|
| Robots.txt with TTL cache | `RobotsCache` class, 5-min per-host TTL | Basic check, no caching — refetches every time |
| Redirect loop detection | `detect_redirect_loop()` via canonicalized URL comparison | None |
| Per-hop redirect budget | Remaining-budget timeout tracked per hop | Single flat `FETCH_TIMEOUT_SECONDS` |
| Structured error types | `timeout \| blocked \| redirect_loop \| unsupported_domain \| fetch_error` | None |

**Behavioral reversal required for robots.txt:** `paste_fetch.py` line 129 explicitly fails
**open** on robots.txt errors (`# On any error (timeout, connection, parse), optimistically allow`).
This spec requires **fail closed** (Section 6). When porting `RobotsCache`, flip this: any error
fetching or parsing robots.txt must return `False` (blocked), not `True` (allowed).

Port these from `paste_fetch.py` into `parse_job_from_url()` as part of the hardening work,
then delete the file.

### Hardening tasks for parse_job_from_url()

The existing implementation in `job_hunt_parsing.py` does basic robots check + 10s timeout but
does not fully satisfy this spec. Required changes:

1. Add host allowlist validation (Section 3) before any network access
2. Split timeout into 8s network + 2s parse budgets — **port per-hop budget tracking from paste_fetch.py**
3. Add per-hop redirect revalidation — scheme + host allowlist check at each hop, max 3 hops — **port `detect_redirect_loop()` from paste_fetch.py**
4. Add content-type guard — reject non-HTML/text responses before parsing (Section 4)
5. Add content-size guard — reject >2MB compressed / >5MB decompressed (Section 4)
6. Harden robots.txt handling — fail closed; **port `RobotsCache` (with TTL) from paste_fetch.py** instead of refetching on every call
7. Strip scripts/styles/iframes/tracking before text extraction (Section 5)
8. SSRF prevention — reject private IPs, localhost, link-local addresses (Section 5)

After hardening, delete `src/job_hunt_paste_fetch.py` and remove any imports of it.
