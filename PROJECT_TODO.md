# Job Seeking Tool — Project TODO
**Last updated:** 2026-05-07 | **Owner:** SilverHand

---

## 🔴 High Priority

### **[JOB-001]** Tailoring truth validation
**Owner:** Handy | **Status:** Backlog
**Description:** `validate_tailored_cv()` in `job_hunt_tailoring.py` always returns `True` — no actual truthfulness check running. Implement real cross-check: tailored CV claims must match only CandidateProfile fields; reject any invented facts.
**Test:** `python3 -m pytest tests/test_tailoring.py -v`

---

### **[JOB-002]** Orchestrator integration — Reed + Adzuna
**Owner:** Handy | **Status:** Backlog
**Description:** `job_sources/reed_client.py`, `adzuna_client.py`, `normalize.py`, `dedup.py` all exist but NOT wired to `job_hunt_orchestrator.py`. Wire API clients into the workflow. Confirm env var wiring (`REED_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`). Clarify whether `job_hunt_paste_fetch.py` is active or deprecated.
**Tests:** `python3 -m pytest tests/test_job_sources*.py tests/test_ingestion*.py -v`

---

### **[JOB-007]** Create `docs/tasks/url-ingestion-design.md`
**Owner:** Wiser → SilverHand | **Status:** Backlog (Design)
**Description:** MEMORY.md references `docs/tasks/url-ingestion-design.md` but the file does not exist on disk. The existing `job-ingestion-api-design.md` covers API-based ingestion (Reed + Adzuna) but not URL paste/fetch spec. Need to create the design doc covering: 10s budget, 2s parse + 8s network, redirects max 3, allowed sources (indeed, linkedin, reed, glassdoor, cwjobs, cv-library, guardianjobs).
**DEPENDS ON:** Wiser review before build starts

---

## 🟡 Medium Priority

### **[JOB-005]** Cover letter tests
**Owner:** Handy | **Status:** Backlog
**Description:** `job_hunt_cover_letter.py` exists but `tests/test_cover_letter.py` does not exist or is not in the test suite. Spec says all new functions must have tests.
**Test:** `python3 -m pytest tests/test_cover_letter.py -v`

---

### **[JOB-008]** Verify ATS scorer integration
**Owner:** Scout | **Status:** Backlog
**Description:** `src/job_hunt_ats_scorer.py` exists (3676 bytes, Apr 12) with `tests/test_ats_scorer.py`. Verify it is actually wired into the evaluation flow or UI. Confirm whether it's invoked from `job_hunt_evaluation.py`, `job_hunt_ui.py`, or the orchestrator.
**Test:** Run a job through the UI and verify ATS score appears in output

---

### **[JOB-009]** Clarify `job_hunt_paste_fetch.py` status
**Owner:** SilverHand | **Status:** Backlog
**Description:** `job_hunt_paste_fetch.py` + `job_hunt_paste_ui.py` handle URL/text parsing for the UI prefill tab. But `job-ingestion-api-design.md` is the current spec. Need to confirm: is paste_fetch active and canonical, or is it superseded by job_sources pipeline?
**Decision needed from:** Wiser/Mic review

---

### **[JOB-010]** Wiser review `cv-tailoring-brief.md`
**Owner:** Wiser | **Status:** Backlog (Review)
**Description:** `docs/tasks/cv-tailoring-brief.md` created Apr 14 but never went through Wiser review. Needs sign-off before next tailoring work proceeds.
**DEPENDS ON:** Wiser scheduling

---

### **[JOB-011]** `job_sources/` test coverage
**Owner:** Scout | **Status:** Backlog
**Description:** Reed client, Adzuna client, normalize, dedup all exist but no tests in suite for the API pipeline. Need integration tests covering: successful fetch, 429 rate limit handling, empty results, dedup across sources.
**Test:** `python3 -m pytest tests/test_job_sources*.py tests/test_dedup.py tests/test_normalize.py -v`

---

## 🟢 Lower Priority

### **[JOB-006]** Clarify canonical viewer HTML
**Owner:** SilverHand | **Status:** Backlog
**Description:** `viewer/` contains `reed_jobs.html` + v2 + v3 + v4 + `reed_minimal.html` + `reed_debug.html`. No clear statement of which is current canonical UI. Confirm and update `viewer/README.md`.

---

### **[JOB-012]** Full ingestion flow integration tests
**Owner:** Scout | **Status:** Backlog
**Description:** End-to-end test from API fetch → normalize → dedup → scoring → decision → stored analysis. Not written. Needed before any ingestion work is marked complete.

---

## ✅ Completed (from prior audits)

| Item | Description | Done |
|------|-------------|------|
| JOB-003 | PROJECT_LOG.md catch-up (Apr 14–28 gap entry) | ✅ 2026-05-02 |
| JOB-004 | product_spec.md updated (stale scope refs) | ✅ 2026-05-02 |
| 3A | Missing docs: data_contract.md existed, tailoring_spec.md created | ✅ 2026-05-02 |
| 3C | PROJECT_LOG.md gap entry added | ✅ 2026-05-02 |
| 3E | product_spec.md stale scope ✅ | ✅ 2026-05-02 |
| 3F | INDEX.md url-ingestion fix (→ job-ingestion-api-design.md) | ✅ 2026-05-02 |
| — | 180 tests passing | ✅ verified |
| — | job_sources/ clients exist (reed, adzuna, normalize, dedup) | ✅ done |
| — | Cover letter module exists | ✅ done |
| — | ATS scorer module exists | ✅ done |

---

## Kanban Location
`viewer/kanban_data.json` (Job Hunt viewer on port 8765)

## Pipeline Gate
All P0/P1 items require Wiser design review before Handy build starts.
Wiser Protocol: max 2 revisions per review. REJECT → discuss with Mic.