# Technical Feasibility Assessment: `browse.sh` Integration
**Date:** 2026-05-20
**Project:** Job Seeking Tool

## 1. Executive Summary
Integration of `browse.sh` is highly feasible and directly addresses the primary risks identified in the Job Seeking Tool project: scraping stability, anti-bot mitigation, and token efficiency. It provides a managed bridge between local prototyping and cloud production.

## 2. Comparative Analysis

| Feature | Current Approach (Basic Fetch/Crawler) | Proposed `browse.sh` Integration |
| :--- | :--- | :--- |
| **Parsing** | Raw HTML (Token Heavy) | Structured/Domain-specific Skills (Efficient) |
| **CAPTCHA/IP** | Manual/Fragile | Automated Cloud (Browserbase) |
| **Maintenance** | High (DOM changes break parser) | Lower (Community-maintained Skills) |
| **Costs** | High (Input Tokens) | Low (Optimized extraction) |
| **Env Parity** | Low (Often fails in prod/headless) | High (Identical local/cloud runtime) |

## 3. Implementation Path

### Phase A: POC (Handy)
1.  Setup `browse` CLI in dev environment.
2.  Define a specific LinkedIn or Indeed job-parsing skill.
3.  Execute a benchmark:
    - Compare success rate of `raw_html_fetch` vs `browse_skill_fetch`.
    - Measure Token Usage: Raw HTML (Full) vs. Skill-extracted JSON.

### Phase B: Integration Architecture (Handy/Scout)
- Create `BrowseIngestor` class under `job_sources/`.
- Implement a strategy pattern:
    - If `target_site` in `BROWSE_SKILLS` registry → use `BrowseIngestor`.
    - Else → use `DefaultIngestor` (fallback).

### Phase C: Operational Stability
- **Stealth Mode:** Enabled for production via `browse cloud` flags.
- **Identity Management:** Leverage Browserbase session/cookie store for persistent login (if needed for LinkedIn).

## 4. Risks & Mitigations
*   **Skill Staleness:** If a target site updates their DOM, the community skill may fail.
    *   *Mitigation:* Implement a "Circuit Breaker" to fallback to raw HTML parsing if `browse` skill fails 3 consecutive times.
*   **Dependency:** reliance on Browserbase cloud.
    *   *Mitigation:* Modular design. The project remains engine-agnostic; `browse.sh` is just one of many potential drivers.

## 5. Cost-Benefit Conclusion
*   **Cost:** Initial development effort (approx 2-3 days). Browserbase cloud costs are usage-based (low for current volume).
*   **Benefit:** Massive reduction in long-term maintenance/debugging time; significantly better job-data accuracy.

---
**Recommendation:** Proceed with Phase A (POC) to validate the "Token Reduction" hypothesis before committing to full integration.
