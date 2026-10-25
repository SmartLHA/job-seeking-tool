# UI Scope

**Current implementation reconciliation: 2026-10-25.** The product UI is the recovered split architecture: `ui_routes`, `ui_handlers`, `ui_render`, `ui_utils`, `ui_state`, and source adapters. `src/job_hunt_ui.py` is only the entry-point shim.

## Current experience

The local-first workflow is:

```text
Search a configured source or add a job → review fields → explicitly evaluate
→ inspect the explainable result → prepare material or record outcome → submit manually
```

Reed, Adzuna, and LinkedIn have implemented adapters in the generic source registry; configured availability and live provider behavior are separate from implementation evidence. Further sources remain unavailable until their complete adapters are implemented and tested.

### Search, review, and batch queue

- Search uses `GET /search/{source}` and `GET /search/{source}/more` for Reed, Adzuna and LinkedIn. Initial HTML must render before binding, successor and seen state commit. More binds profile/state/source/normalized filters/keyword cursors/hidden state and commits serialized JSON, successor and seen records together. Retries replay frozen responses; expired/evicted/unknown or changed-bound searches show an actionable restart. Valid partial keyword pages retain failed-term cursors; unsuccessful preparation does not consume state.
- Result selection uses `POST /select/{source}`, preserves a source snapshot, and fetches full Reed detail when available before extracting skills.
- Users may stage selected results and call `POST /jobs/batch-evaluate` (maximum enforced by the handler), then inspect them through `GET /review-queue`.
- Manual input follows **Add & Evaluate**: paste or URL → `POST /prefill` → review/edit → `POST /job-submit`. The Advanced Review form remains available through `POST /evaluate` for reviewed/amended data; both routes use the same validation, raw-input persistence, and scoring pipeline. URL parsing remains host-allowlisted, robots-aware, SSRF-protected, and fail-closed.
- Parsed values carry field-review provenance. Missing data remains unknown rather than invented.

### Evaluate and job detail

- Job detail is `GET /job/<id>`; `?embed=1` is used by the review queue.
- It shows match score, categorical confidence, source-quality state, ATS readiness, F1 ATS keyword coverage, strengths, gaps, blockers, risk flags, and decision reasoning.
- F1 keyword matching is advisory only. It reports present/missing required and preferred keywords and warns about repeated-keyword stuffing; it does not affect decisions.
- Users can persist an Apply/Review/Skip override through `POST /job/<id>/decision`.
- When `source_ref` is an HTTP(S) advert URL, the page renders **View original posting / Apply**. The product never submits an application itself.
- Optional manual AI actions (including `POST /job/<id>/ai-review-cv`, explanations and qualitative assessment) remain separate from deterministic scoring. Explicit user-requested qualitative batches use the shared worker when a key is available; this is independent of the digest LLM toggle.

### Tailoring, cover letters, profile, and outcomes

- The job page exposes decision-gated Tailor CV and Cover Letter actions, backed by `POST /tailor` and `POST /cover-letter`.
- Tailoring returns summary, promoted evidence, matched keywords, missing keywords, and markdown. Review decisions require manual selection; Skip is blocked.
- Cover letters require `why_company_text`, accept only supported tone/length values, and use grounded optional points.
- Profile editing separates job-search preferences, experience/evidence, CV upload/content, scoring presets, and digest settings. It supports structured skills, master-CV parsing, and explicit save feedback without rendering local CV filesystem paths.
- Multipart `POST /profile/parse-cv` permits a 5 MiB file within a 5 MiB + 64 KiB request; ordinary POSTs retain a 1 MiB cap. All four CV save paths reject symlinks below the canonical configured root and preserve references on failure. Profile-aware candidate loading can skip a mismatched AI CV before ordinary fallback.
- `POST /outcome` enforces the local outcome state machine.

### Saved searches, digest and background work

- Saved-search create/toggle/delete and manual Run now are implemented. The local digest feed, seen state and deterministic re-evaluation are implemented.
- The scheduler follows profile digest settings. Digest AI draining requires the digest LLM toggle and a provider key; explicit qualitative batch work has its own user request/key gate.
- New marked ingestion attempts resume unfinished metadata/queue initialization without resetting completed/processing work; unmarked legacy partial rows are not guessed. LinkedIn details are fetched lazily after deduplication within each saved search's existing cap; empty/blocked details are skipped.
- Re-evaluation retains the complete raw `llm_*` group in one save; retained AI text can describe older inputs. Qualitative ownership uses paired leases/guards and accepted-generation UI/export reads. Waiting on a live owner does not consume retries, and cancellation wins. Old writers must be quiesced for migration; no cross-store crash-atomicity claim.

### Board and tracker

- `GET /board` returns SQLite-backed columns, statistics, cards, and allowed transitions.
- `GET /board/view` renders the board UI; `POST /jobs/save` creates a `not_applied` bookmark.
- The only tracker statuses are `Not Applied`, `Applied`, `Interview`, `Offer`, `Rejected`, and `Withdrawn`. Visual transitions must follow the server-provided allowed transitions.

## Visual and safety rules

- Use the established paper/ink layout, clear decision colours, and compact metadata treatment.
- Keep privacy, local storage, evidence boundaries, and manual submission visible in the UI.
- Never turn categorical confidence into a probability.
- Never treat sample/prototype data as live candidate or job data.
- No auto-apply, credential storage, stealth automation, or mass-application behaviour.

## Backlog

- Gap Coach, deterministic aggregation over stored analyses.
- *(Adzuna and LinkedIn source adapters — shipped & enabled, 2026-06.)*
- DOCX/PDF application-package export.

## Evidence and qualification — 2026-10-25

Committed P2 code has synthetic evidence: **645 passed, 75 deselected** in the final
non-HTTP/non-browser regression after the LinkedIn diagnostic follow-up. Earlier
P2-12 evidence is **86 passed** in the separate owned-loopback
HTTP/browser regression, including all **15 mandatory Chromium cases**. The clean
HEAD + P2-12 projection at that earlier checkpoint passed **106 cases**,
repeating those 86 plus 20 helper
checks; this is dependency evidence, not an additional coverage total or a clean
HEAD run of the latest 645 cases. Follow-up `c3a8739` corrects strict LinkedIn HTTP
error classification before body/redirect heuristics while preserving default UI
behavior; its working and clean focused suites each passed **120 cases, 1 HTTP
case deselected**. Required-mode
setup/call/teardown skip canaries deliberately fail. Each final runner recorded
seven expected fence-preflight denials and zero unexpected Python fence events;
loopback runners left no owned ports open. Native browser OS egress isolation is
UNVERIFIED. Evidence: `/private/tmp/job-tool-p2-20261023/browser-ci/commands.txt`,
`acceptance-summary.json`, and the per-run logs/manifests in that directory.

Independent read-only advisory reviews are separate from producer test evidence.
The P2-10 follow-up advisory reported no Blocker/Major/Minor findings; the P2-11/12 final-source
advisory likewise reported no Blocker/Major/Minor findings (in-memory/static
checks; `/private/tmp/job-tool-p2-20261023/final-source-verification/answer.txt`). Raw reviewer startup still includes generic skill
instructions, so strict Gate 3 certification remains **PARTIAL** despite
read-only/never settings. Remote CI, actual Python 3.10 execution, live providers,
production behavior and deployed-writer migration are **UNVERIFIED**. All five P1
designs remain approval-pending and outside these P2 changes.
