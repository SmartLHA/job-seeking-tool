# Issue 16: durable daily digest attempts, manual retries

## Approved behavior

The user selected option A on 2026-10-12: persist daily success and retry failures only manually. A scheduled attempt must also survive restart so a failed or interrupted run does not cause another automatic attempt that day. Existing per-search Run now remains available and does not certify success of the entire daily batch.

## Scope

Implement a small daily-run ledger in the existing state-root SQLite index. Use an atomic local-date claim committed before any pipeline/provider work. Store outcome, result and error; retain successful and unsuccessful attempts across scheduler instances. No new automatic retry, provider calls during development, production service startup, secrets or security-setting changes. Preserve unrelated dirty files and earlier user documentation edits.

Own scheduler/index implementation, focused scheduler/index tests, this task and the relevant audit/status documentation. Keep changes minimal; no general scheduling framework or UI redesign.

## Acceptance criteria

1. A successful daily run is persisted and a new scheduler using the same state root does not rerun it on the same local date.
2. Exceptions, results containing errors, and interrupted claimed runs also suppress automatic same-day retries across restart; useful partial results and error details remain available.
3. The next local day permits one new scheduled attempt. Disabled and pre-schedule checks retain their existing behavior. Next-run status moves to tomorrow after a claimed attempt.
4. Two scheduler instances racing for the same date can claim at most once using SQLite transaction/uniqueness semantics. The claim is durable before pipeline execution.
5. Persistence read/claim errors produce zero pipeline/provider calls and a truthful status error. Outcome-write failure retains the durable claim; it does not enable a retry or falsely claim durable success.
6. Status preserves existing last_run_date semantics (attempted date), exposes durable outcome/success information, and restores appropriate result/error after restart. A returned result with nonempty errors is not labelled successful. A stale running claim is described as interrupted/unfinished and requiring manual retry.
7. Existing per-search POST Run now continues to bypass the daily guard, including after failure. A manual run neither clears a daily attempt nor converts the batch to success.
8. Focused tests exercise actual scheduler and actual SQLite with synthetic temporary state: successful/failed/interrupted restarts, next-day execution, competing claims, persistence failures, partial results and manual-run compatibility. No network or real profile/data/home reads.
9. Update relevant audit and user-facing scheduler documentation accurately. Preserve existing user hunks; back up existing documents before modifying. Fresh read-back, local links and appropriate syntax checks pass. Report execution evidence separately from unverified production/provider behavior.
10. Independently verify the final change through the existing external Codex read-only reviewer/verifier with raw fresh-context/read-only/never evidence. Do not self-certify completion.

## Verification limits

Do not start the real scheduler or call external providers. Development checks use a disposable synthetic copy or memory-only harness. Production startup, real provider behavior and unrelated earlier end-to-end gaps remain unverified.

## Status

Implementation and independent verification pending.
