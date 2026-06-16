# Gap Analysis - SilverHand
**Date:** 2026-05-20
**Scope:** Cross-check of design documents against implementation in `src/`, `tests/`, and `viewer/`.

## Summary

The project has moved beyond the 2026-05-12 state. Reed-only ingestion is now wired through the orchestrator and UI, tailoring truth validation is no longer a stub, and cover-letter tests now exist. The remaining gaps are mostly source-scope mismatches, URL ingestion safety, stale documentation, and last-mile generation/UI integration.

## Current Verified Gaps

### 1. API ingestion design still describes Reed + Adzuna, but implementation is Reed-only
- **Design:** `docs/tasks/job-ingestion-api-design.md` still defines Reed as primary and Adzuna as secondary, with parallel fetch and cross-source deduplication.
- **Implementation:** `src/job_hunt_orchestrator.py` exposes `run_reed_evaluation_flow()` only. It imports `fetch_reed_jobs` and `normalize_reed`, not Adzuna fetch/normalization.
- **Tests:** `tests/test_orchestrator.py` explicitly asserts the Reed flow does not require Adzuna.
- **Gap:** The design doc needs a status correction or a new implementation slice if Adzuna should return to scope.

### 2. Source quality gating is designed but not enforced in the decision path
- **Design:** `docs/tasks/job-ingestion-api-design.md` says low-quality source records should force Review, exclude `<40` quality jobs, and prevent Apply for insufficient descriptions.
- **Implementation:** Normalization computes `source_quality`, and the Reed orchestrator records it in notes, but `JobPosting` and `JobAnalysis` do not carry source quality as a first-class field. `evaluate_reviewed_job()` calls `score_job()` and `decide_application()` without source-quality overrides.
- **Gap:** Reed API jobs can be evaluated without the designed quality gate. Low quality currently appears as notes, not control logic.

### 3. URL ingestion design is stricter than the wired URL prefill path
- **Design:** `docs/tasks/url-ingestion-design.md` requires allowlisted hosts, HTTPS-first validation, max 3 redirects with per-hop revalidation, 8s network + 2s parse budget, fail-closed robots handling for risky sources, content-size/type controls, and no credentials/browser state.
- **Implementation:** The UI `POST /prefill` path calls `parse_job_from_url()` in `src/job_hunt_parsing.py`, not `job_hunt_paste_fetch.py`. That function checks robots, then `urlopen()`s the URL with a 10s timeout, but does not enforce the full allowlist/redirect/scheme/size/content-type/security budget from the design.
- **Gap:** Existing URL prefill should not be treated as compliant with the canonical URL ingestion design until JOB-009 resolves the canonical path and safety controls are implemented.

### 4. `job_hunt_paste_fetch.py` exists but is not the active UI fetcher
- **Design/status:** `docs/tasks/url-ingestion-design.md` correctly marks JOB-009 as the open decision on whether `paste_fetch` is canonical.
- **Implementation:** Search shows `fetch_job_page()` is not called by the current UI. `src/job_hunt_ui.py` uses `parse_job_from_url()` from `job_hunt_parsing.py`; `job_hunt_paste_fetch.py` is effectively an unused parallel fetcher.
- **Gap:** There are two URL-fetch implementations with different safety properties and no canonical decision.

### 5. Tailored CV generation exists, but the UI still says it is not implemented
- **Design:** `docs/tailoring_spec.md` says CV tailoring is implemented, with `save_tailored_cv()` and eligibility rules.
- **Implementation:** `src/job_hunt_tailoring.py` contains deterministic tailoring, validation, and saving.
- **UI:** `src/job_hunt_ui.py` renders `Eligible when tailored CV support is added` or `tailored CV support is not implemented in this UI`.
- **Gap:** Backend tailoring exists, but there is no UI action/path to generate, save, or preview a tailored CV.

### 6. Cover-letter generation is implemented and tested, but not product-wired
- **Design:** `docs/tasks/cover-letter-spec-draft.md` expects cover-letter generation and tests.
- **Implementation:** `src/job_hunt_cover_letter.py` and `tests/test_cover_letter.py` exist. `src/job_hunt_tailoring.py` exposes `generate_cover_letter_text()`.
- **Gap:** The main orchestrator/UI does not trigger or save cover letters after Apply/Review decisions. It remains a module-level capability, not an end-to-end workflow.

### 7. ATS scorer exists but is not materially integrated
- **Design:** `docs/tasks/ats-score-deferred.md` expects `score_cv()` and integration/exposure.
- **Implementation:** `src/job_hunt_ats_scorer.py` exists and has tests. `src/job_hunt_scoring.py` imports `score_cv`, but the function is not used in `score_job()`, evaluation output, reporting, or UI display.
- **Gap:** ATS scoring is present as a standalone module, not an integrated product signal.

### 8. Viewer/Reed HTML canon resolved 2026-05-20
- **Resolution:** `viewer/reed_jobs_v4.html` is the only retained standalone Reed job viewer. Older Reed HTML variants were already absent by the time of this cleanup, and the remaining nav link was updated to v4.
- **Docs:** `viewer/README.md` now identifies v4 as canonical.
- **Status:** JOB-006 can be treated as resolved.

### 9. Project docs and TODO contain stale status
- `docs/product_spec.md` still says Reed + Adzuna are not wired, cover-letter tests are missing, and tailoring validation is a stub.
- `PROJECT_TODO.md` still lists JOB-005 as missing cover-letter tests, despite `tests/test_cover_letter.py` existing.
- **Gap:** Status docs need cleanup before they can be trusted as current-state references.

### 10. Other viewer files have similar canon/link issues
- **Resolved 2026-05-20:** `viewer/openclaw_status_v2.html` is no longer present in the Job Seeking Tool repo; `viewer/openclaw_status.html` is the retained status dashboard file.
- **Variant group:** `viewer/social_post.html`, `viewer/social_post_comprehensive.html`, and `viewer/social_post_x.html` all exist. No project doc identifies a canonical retained version.
- **Broken local links:** `viewer/openclaw_status.html` links to missing local viewer pages in this repo: `kanban.html`, `multi_llm_chat.html`, `openclaw_optimization_designs.html`, `system_kanban.html`, and `swarm_panel.html`.
- **Resolved 2026-05-20:** `viewer/memory_infra_proof_dashboard.html` is no longer present in the Job Seeking Tool repo; the retained copy lives in the main OpenClaw workspace root.
- **Resolved 2026-05-20:** No literal `src/ui.py` exists in the Job Seeking Tool repo, and stale `viewer/ui.py` was removed. The active UI remains `src/job_hunt_ui.py`.
- **Status:** Remaining items in this section are static scan findings that need separate canon decisions before removal.

## Updated From Previous Gap Analysis

The following 2026-05-12 gaps are no longer accurate as originally stated:

- Reed ingestion is no longer completely unwired: Reed-only `run_reed_evaluation_flow()` exists.
- `validate_tailored_cv()` is no longer a simple `True` stub.
- `docs/data_contract.md` and `docs/tailoring_spec.md` now exist.
- Cover-letter tests now exist, though workflow integration remains missing.

## Recommended Next Order

1. Resolve JOB-009: choose the canonical URL ingestion implementation and either disable unsafe URL prefill or bring it up to `url-ingestion-design.md`.
2. Update stale status docs: `docs/product_spec.md`, `PROJECT_TODO.md`, and `viewer/kanban_data.json`.
3. Implement source quality gating in the Reed evaluation path or explicitly downgrade it from the API design.
4. Add UI/orchestrator actions for tailored CV and cover-letter generation.
