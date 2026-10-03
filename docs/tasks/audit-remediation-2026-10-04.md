# Audit remediation — 2026-10-04

User authorization: fix all findings from the independently reviewed audit, one issue at a time. Preserve existing uncommitted changes. No live provider calls, real application submissions, secrets changes, or changes to unrelated OpenClaw services.

## Execution and verification

Implement the numbered items sequentially. Each item needs focused regression tests before proceeding. Keep synthetic test data and test artifacts in disposable directories; do not load real user data or credentials. Record exact test results below. Existing broad baseline: 1295 passed, 8 skipped, from the preceding audit; this is historical, not validation of these changes. Final verification must use the existing isolated read-only reviewer, raw isolation evidence, and an appropriately bounded disposable test execution. Do not claim live provider/browser behavior without exercising it. Commit only owned changes after inspecting the staged diff; preserve unrelated pre-existing work.

## Acceptance criteria

1. **Manual decisions on reevaluation.** Local and digest reevaluation preserve `user_decision` and `user_decision_note` from the existing analysis while recomputing derived scoring fields. Missing previous analysis still works. Regression tests exercise both entrypoints with synthetic saved decisions and notes.
2. **Viewer file boundary.** Default bind is loopback. Static routes serve only explicitly public assets, reject hidden/config/source/profile/state files and traversal/symlink escapes, while intended public viewer assets still load. Do not modify the separate running OpenClaw viewer.
3. **Shortlist identity.** Cards use stable source/job identities rather than page offsets across all source renderers; cached identity and submitted payload remain consistent across multi-keyword pages, repeats, and selection changes. Execute a DOM/JS regression where feasible.
4. **CV cloud consent.** UI accurately explains local extraction versus cloud processing. Cloud extraction requires explicit user selection/consent; a local-only route remains useful and makes no provider call. Correct misleading global privacy copy. Test default local behavior and explicit cloud behavior with mocks.
5. **Cover-letter profile isolation.** Persist and load letters by both job and profile, update export/callers consistently, and never silently include a legacy or mismatched-profile letter. Preserve existing files; no destructive migration. Test two profiles for the same job and ZIP contents.
6. **Cancellation and retries.** Cancelled batches cannot acquire/requeue work for further LLM calls, including cancellation during an in-flight rate-limited attempt and recovery paths. Existing normal retries continue. Test the combined cancellation-plus-429 path.
7. **CSV text safety.** Untrusted text fields cannot be interpreted as spreadsheet formulas, including relevant leading whitespace/control characters. Preserve legitimate numeric data. Regression tests cover titles, companies, notes and benign text.
8. **Uploaded CV format.** Extracted text is stored with a truthful text format; original PDF/DOCX bytes, if retained, remain separate and valid. Subsequent parse/save/reload paths work. Test PDF/DOCX filename flows using synthetic/mocked extraction.
9. **Profile atomicity.** Profile writes use atomic replacement and preserve the prior valid file on failure. Read-modify-write paths share per-profile synchronization so concurrent updates do not silently overwrite unrelated fields. Test failure and concurrent updates in temporary directories.
10. **Sensitive HTTP actions.** Cloud analysis uses POST with appropriate same-origin validation. Validate Host for relevant local UI routes; do not accept unsafe missing-header cross-origin mutations. Keep legitimate UI requests working. Test request boundaries with synthetic local servers or handler fixtures.
11. **Keyword/cursor consistency.** Initial and subsequent pages use the same per-keyword normalization; long multi-keyword inputs cannot silently change terms or cursor arity. Test all supported sources without network.
12. **Batch partial errors.** Show successes and failures, preserve failed selections and allow retry; do not silently discard errors after partial success. Test mixed success/failure JS behavior.
13. **Batch selection limit.** UI prevents or clearly handles selections beyond the backend limit of 20 before submitting; no silently rejected whole shortlist. Test the 21st selection and normal 20-item submission.
14. **Initial failed keyword.** A failed first request retains a retryable cursor distinct from exhaustion; subsequent pagination can retry it while continuing other terms. Test initial failure plus another term succeeding.
15. **Import dependencies.** Declare required PDF/DOCX import dependencies in the supported installation manifest and update installation documentation consistently. Verify dependency import paths; do not install packages globally.
16. **Daily scheduler semantics.** Pending user preference: persist successful daily state and use bounded failure retries, or the explicitly selected alternative. Test restart and failure behavior; document the actual contract. Do not create unrelated system automations.

## Progress

- Issue 1 committed as `70c53daf820be5300204cef3b43888b5af69d25e`; targeted producer tests: `47 passed`.
- Issue 2 implementation: loopback viewer bind, code-owned public file allowlist, traversal and symlink rejection, canonical public manifest paths, and supported local-server documentation/checker. Files: `viewer/viewer_server.py`, `viewer/documents.json`, `viewer/README.md`, `scripts/check_viewer_docs.py`, `tests/test_viewer_static_boundary.py`. Commit: pending; sandbox denies `.git/index.lock` creation (`Operation not permitted`), so staging/commit could not run.
- Issue 2 producer validation: `venv/bin/python /private/tmp/job-tool-remediation-BxSQqQ/prepare_and_test.py tests/test_viewer_static_boundary.py tests/test_viewer_paste_handlers.py` → `36 passed in 0.49s`; log `/private/tmp/job-tool-remediation-BxSQqQ/issue2-tests.log`, disposable copy `/private/tmp/job-tool-remediation-BxSQqQ/run-mt691mft`. All static requests used synthetic fixtures; no live server, actual sensitive-file request, provider or separate OpenClaw service was exercised.
- Issue 2 independent isolated verification remains pending; no other issue implemented in this chunk.
- Independent review of implementation: pending.
