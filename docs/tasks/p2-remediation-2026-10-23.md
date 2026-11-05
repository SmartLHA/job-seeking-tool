# Remaining P2 remediation — 2026-10-23

<!-- STATUS -->
> **Current status — 2026-10-25:** P2-01–P2-12 code/test checkpoints committed; P2-13 documentation reconciled in this checkpoint. All thirteen implementation slices are recorded in the final ledger below. Overall qualification remains **PARTIAL**.
> **Evidence:** final current unit regression 645 passed/75 deselected; earlier P2-12 owned-loopback HTTP/browser 86 passed including 15 required Chromium cases. Earlier clean HEAD+P2-12 projection 106 passed repeats 86 + 20 helpers, not an additive total. Seven expected preflight denials/zero unexpected Python fence events per final runner; owned loopback ports closed.
> **Limits:** advisory review is distinct from producer evidence; generic skill instructions in raw reviewer startup prevent strict Gate 3 certification despite read-only/never. Remote CI, actual Python 3.10 runtime, native browser OS egress isolation, live providers and production/migration remain UNVERIFIED. All five P1 designs remain approval-pending.
> **History:** dated authorization/recovery notes below retain their original state; this current header and final ledger supersede old pending-slice statements. This session-authored plan is tracked with explicit parent authorization; unrelated untracked documents remain excluded.
<!-- /STATUS -->

User authorization: handle all other P2 from the whole-project audit. The five P1 designs remain approval-pending and are excluded.

## Working contract

Fix one issue at a time with synthetic regression tests and checkpoints. Preserve all pre-existing dirty work; never stage whole dirty files or use reset/stash. No real profiles, CVs, .env, providers, applications, production servers, or process signals. No sandbox/security configuration changes. New artifacts go in existing subdirectories. Record changed paths and test results below. Full completion requires qualifying fresh-context verification; otherwise report PARTIAL.

## P2-01 — Adzuna search exception logging

Problem: ordinary search logs raw requests exceptions that can include the app key in a URL.

Scope: src/job_sources/adzuna_client.py and tests/test_reed_adzuna_clients.py only.

Acceptance:
- HTTP errors log a fixed message plus safe numeric HTTP status when available; connection/request errors log a fixed message plus exception class only.
- Neither log output nor propagated error text includes the key, query URL, or raw exception message.
- Existing empty-result/failure behavior and successful search behavior stay compatible.
- Regressions use synthetic HTTPError and RequestException containing a fake key in a URL, capture logs, and cover both branches.
- Run relevant tests in a refreshed disposable copy with synthetic home/dotenv and network/process/private-path fences. Retain actual output and exact command. Do not run the old audit source copy as current evidence.

Checkpoint: producer tests 32 passed; commit 1dd70d1; independent verification pending.

## Remaining inventory

Inventory confirmed 13 items, listed below.

## P2-02 — CV upload transport allowance

Scope: src/ui_routes.py, tests/test_ui_security.py, related CV tests only if required. A required one-line src/ui_handlers.py correction uses HTTPStatus.REQUEST_ENTITY_TOO_LARGE so oversize files return 413 rather than an AttributeError/500.

Preserve the documented 5 MiB file limit. Select an upload request cap of 5 MiB plus 64 KiB bounded multipart overhead only for exact /profile/parse-cv multipart POST; retain 1 MiB elsewhere. Reuse existing body/header/security validation order. Do not implement pending P1 source-origin design.

Acceptance:
- Dispatcher-level synthetic multipart requests containing valid 2 MiB and exactly 5 MiB files reach parse handler.
- A file of 5 MiB + 1 byte is rejected by the existing file validator.
- Upload body allowance + 1 byte is rejected before body read; ordinary POST 1 MiB + 1 byte stays rejected.
- Non-multipart and similar paths do not obtain upload allowance; malformed Content-Length and existing Host/Origin failures remain pre-read rejects.
- Tests run only in refreshed fenced disposable copy; original failing dispatcher path exercised, not merely direct handler calls.

Checkpoint: producer tests 85 passed with zero pytest fence events; commit 2fd3a86; independent verification pending.

## Full confirmed inventory and order

13 current source-backed items. IDs here are local remediation IDs, not historical Phase-2 IDs. P2-01 Adzuna is implemented with producer tests (32 passed), checkpoint 1dd70d1; independent verification remains pending. P2-02 upload allowance is next. The following slices are sequential; finish and report each before beginning the next. For all slices capture baseline snapshots and a baseline-to-current patch, use refreshed isolated synthetic test copies, and retain logs/fence summary. No P1 design work is authorized by these slices.

## P2-03 — Profile-aware tailored CV fallback

Scope: src/job_hunt_tailoring.py; tests/test_f1_recheck.py, tests/test_export_bundle.py.

Acceptance: For each ordered AI/ordinary candidate, validate expected profile before accepting. A mismatched AI candidate must not hide a matching ordinary CV. Matching AI stays preferred. Mismatched/headerless candidates cannot cross profiles; existing no-expected-profile behavior remains compatible. Cover A AI+B ordinary, matching AI, no matching candidate, empty candidate, export ZIP synthetic contents. No real files/provider calls.

## P2-04 — ATS profile identity

Scope: src/ui_handlers.py handle_recheck_ats and tests/test_f1_recheck.py.

Acceptance: load/validate active profile identity and pass expected_profile_id before reading/scoring tailored CV. Only matching CV contributes. If no matching CV exists, existing 422 response is retained without modifying stored six-field keyword group/baseline. Exercise actual handler with two synthetic profile identities and assert chosen text plus no-write failure. Preserve existing master/baseline behavior. Do not implement D1 locking.

## P2-05 — CV output containment

Scope: ordinary tailor save in src/job_hunt_tailoring.py; AI-review, master upload/autosave, explicit profile-save writers in src/ui_handlers.py; narrow shared persistence helper if justified; related tests.

Acceptance: all four CV persistence paths reject destination-file and nested-directory symlinks that could overwrite an external synthetic sentinel. Reject before changing profile reference if CV persistence fails. Valid saves remain compatible. Do not simply resolve a symlink and write its target. Respect existing configured-root symlink semantics: canonicalize an explicitly configured root, then restrict descendants and reject output leaf/intermediate symlinks; report any intentional compatibility change before applying. Avoid TOCTOU by safe directory/file opening or atomic replace with validated directories; no writes through attacker-controlled symlinks. Synthetic fixtures only, including nested symlink and ordinary paths. Reuse current storage safety patterns where appropriate; preserve pre-existing dirty storage/parsing hunks.

## P2-06 — Review Queue job IDs as DOM data

Scope: Review Queue component in src/ui_render.py and relevant rendering/browser tests only. P1 Tailor-result DOM is excluded.

Acceptance: remove job-ID interpolation into executable inline JS. Use data attributes/safe DOM properties and delegated handlers; quote/backslash/Unicode/inert markup IDs select the exact original ID and create correctly encoded iframe URL, with no injected nodes or executed handler. Keep keyboard/click selection and queue layout. Include actual browser/DOM event regression, not only string absence assertions. If local browser dependencies unavailable, retain explicit UNVERIFIED browser criterion while completing code and CI infrastructure; never silently skip required CI coverage.

## P2-07 — Digest metadata persistence recovery

Scope: digest ingestion in src/job_hunt_scheduler.py, narrow src/job_hunt_index.py helper if needed, tests/test_digest_pipeline.py and tests/test_index.py.

Acceptance: metadata/initial queue persistence failure after authoritative job save is retryable on next identical source/search run. Retain job rather than duplicate, repair missing stage once, respect import/queue caps, never reset completed/processing queue status. Prefer an atomic short index/meta/initial queue transaction or explicit resumable stage. Inject independent metadata and queue failures, rerun, assert authoritative record retained and SQL metadata+queue converged. No provider call and no pending P1 D1 rebuild/global locks/B1 budget changes.

## P2-08 — LinkedIn digest detail enrichment

Scope: LinkedIn digest source adapter and src/job_hunt_scheduler.py, tests/test_linkedin_source.py and tests/test_digest_pipeline.py.

Acceptance: normal LinkedIn card with empty description receives bounded lazy detail enrichment before deterministic digest scoring. Use existing source enrichment rules, at most existing per-run job/import allowance, no invented description. Blocked/failed/empty details are explicitly skipped with diagnosable reason; Reed/Adzuna unchanged. Synthetic source/detail mocks; zero real network. Avoid enriching every card before caps/dedupe.

## P2-09 — Pagination response retry

Scope: src/job_sources/search_state.py, relevant src/ui_handlers.py search handler and source call sites; tests/test_search_dedup.py, test_multi_keyword_search.py, test_multiselect_shared.py.

Acceptance: identical source+search identity+cursor retries return the same visible page and successor cursor after simulated lost response; subsequent pages deduplicate normally; concurrent identical requests agree. Preserve excluded/hidden jobs, search reset, multi-keyword cursor behavior. Use bounded page replay cache or equivalent commit/replay protocol, with search-scoped identity, safe eviction and locking; no global cross-profile replay. Exercise real handler response-loss path with fake source; no socket required. Do not advance durable cursor merely because response send was attempted.

## P2-10 — Qualitative claim recovery and ownership

Scope: qualitative claims in src/job_hunt_index.py, src/job_hunt_qualitative.py, eval-queue worker in src/job_hunt_scheduler.py, focused tests/test_eval_queue.py and test_qualitative*.py.

Acceptance: use lease timestamp+unique owner token for qualitative running rows. Active claim is not stealable (including force); expired claim can be recovered/reclaimed for queued and on-demand calls. Old owner cannot finish, release, persist results or change replacement queue state. Coordinate queue+qualitative recovery so a stale pair does not permanently block a new worker; all success/error/finally paths carry ownership predicates. Cover crash after both claims, fake clock expiry, reclaim then old completion/release, new completion, active force refusal, on-demand recovery. Preserve budget/date semantics and do not implement pending P1 B1 digest token/reservation changes. Schema additions backward-compatible and documented; no real providers.

## P2-11 — Preserve AI result group on deterministic rescore

Scope: deterministic reevaluation in src/job_hunt_scheduler.py, related tests/test_digest_reeval.py and tests/test_reevaluation_user_state.py.

Acceptance: retain the complete existing llm_* result group when deterministic rescore replaces computed fields, consistent with unchanged done state and existing already-handled queue policy. Preserve all manual decision/note fields. Seed full AI result group and done state, rescore above threshold, verify result retained+done and no provider call; also exercise existing threshold/requeue transitions. Document that retained AI text may reflect earlier deterministic inputs; explicit future invalidation policy is out of scope. Do not implement D1 locking.

## P2-12 — Required browser coverage in CI

Scope: requirements-dev.txt, .github/workflows/python-app.yml, existing browser test skip sites in tests/test_ui.py and tests/test_bulk_paste.py, narrow shared test helper if needed.

Acceptance: CI installs Playwright dependency and Chromium runtime with needed system dependencies, explicitly runs required browser tests using synthetic data/fake providers, and fails if required browser/package missing or selected browser tests skip. Local optional tests may retain clear skip behavior unless required-browser mode enabled; CI must enable required mode. No real external providers or profiles. Test missing dependency/browser failure paths and run actual browser tests locally if already available, otherwise mark actual browser/CI execution UNVERIFIED. Do not fetch/install paid dependencies or modify global/browser user profiles. Static YAML correctness alone does not prove remote CI passed.

## P2-13 — Current documentation reconciliation

Scope: PROJECT_CONTEXT.md, docs/ui_scope.md, docs/docs-update-checklist.md plus narrowly required doc map/log updates under existing docs conventions.

Acceptance: follow current docs/docs-update-checklist.md. Correct saved-search/digest implemented-versus-pending claims, background-versus-manual AI descriptions, _PAGE_UPDATED location, and signatures/routes changed by these P2 slices. Distinguish code/producer tests from independently verified/runtime behavior, preserve dated historical baseline statements, and keep all five P1 explicitly approval-pending. Back up institution/config docs before changes. Fresh read-back and bounded AST/path/signature checks. Preserve existing dirty doc hunks and commit only new P2 changes.

## Verification limitation

Current parent is workspace-write/auto-review: in-process reviewer/verifier cannot satisfy Gate 3. Use existing external read-only/never reviewer with complete verifier contract and bounded source plus disposable-copy verification method; inspect raw prompt/rollout. Generic inherited skill instructions previously prevented strict Gate 3 qualification. Unless current raw evidence proves all requirements, retain PARTIAL, even when producer tests pass. Never alter reviewer security configuration to manufacture qualification.

## Checkpoint ledger

| Slice | Commit | Producer checks | Independent/runtime status |
|---|---|---|---|
| P2-01 | 1dd70d1 | 32 passed; zero pytest fence events | Pending; live provider excluded |
| P2-02 | 2fd3a86 | 85 passed; zero pytest fence events | Pending; no production server |
| P2-03 | 897f269 | 86 passed, 5 live-server tests deselected; zero pytest fence events | Pending; browser/server criteria excluded |
| P2-04 | b3d30b0 | 99 passed, 5 live-server tests deselected; zero pytest fence events | Pending; real handler exercised with synthetic profiles |
| P2-05 | c1c0ddb | 135 passed; zero pytest fence events | Pending; synthetic filesystem symlink/race fixtures |
| P2-06 | b29a716 | 5 actual Chromium cases passed, including click/keyboard/inert markup; zero Python pytest fence events | Pending; native OS egress and remote CI unverified |

A quota interruption occurred after P2-01. Recovery confirmed P2-02 source was untouched before resumed edits. All completed slices above began from HEAD-clean owned paths and retained baseline snapshots plus patches under /private/tmp/job-tool-p2-20261023/. Original twelve dirty files remain outside these commits.

## Advisory review refinements — before P2-07 onward

The existing external read-only reviewer completed an architecture advisory pass. It is not qualifying independent signoff: raw read-only/never context was observed, but generic base skill instructions remain. Full review retained at /private/tmp/job-tool-p2-20261023/architecture-review/answer.txt.

- P2-07: track explicit incomplete-ingestion initialization (or atomically initialize index/meta/initial queue with a policy distinguishing intentional NULL status). Merely rerunning upsert for any indexed job can reset old manual/done state. Preserve original first-seen/unread/manual metadata; repair only the incomplete stage. Inject each boundary failure and intentional non-digest existing job cases.
- P2-09: cache the fully rendered response and successor cursor together with the seen-state transition, under one search-state lock/commit. Key by full active profile, source, search/filter identity and incoming cursor. Avoid caching transient source/render failure. Define bounded replay lifetime and restart behavior explicitly: a cache miss after expiry must not silently consume/deduplicate an unseen page; return a clear restart requirement or reconstruct the same page. Cover concurrency, response loss, render failure, TTL expiry, restart, search reset and hidden-filter changes.
- P2-10: token-check then artifact write is insufficient. Serialize authoritative qualitative result publication with reclaim using the same ownership guard/short SQL transaction or equivalent dedicated cross-process fence. Provider work remains outside locks. An expired worker cannot publish after replacement is claimed, including artifact writes and quota/error/finally paths. Coordinate unequal queue/qualitative leases: active qualitative owner yields retryable waiting, not permanent done; obsolete quota/error paths cannot annotate replacement claims or other batch rows. Cover old publication interleaving with reclaim, mismatched lease expiry, queue recovery while qualitative remains active, and old quota-failure after replacement. This is qualitative-specific ownership, not pending P1 D1 global analysis locking or B1 digest budget fencing.
- P2-11: serial retention contract had no actionable review defect; concurrency and freshness remain limited by pending P1 policy.

Additional review acceptance: P2-07 marker belongs to a specific ingestion/source identity; disabled/capped queue omission is a completed initialization, not perpetually pending. P2-10 legacy running rows without owner/lease need a documented recoverable migration and exact expiry boundaries; actual on-demand caller must propagate ownership. Artifact+SQL failure is not crash-atomic: define fail-closed recovery rather than claiming otherwise. Technical-review raw rollout: /Users/lhaclaw/.codex-harness/reviewer/sessions/2026/10/24/rollout-2026-10-24T10-32-44-01a16d41-5e3d-70d3-92b2-563d5666d041.jsonl (read-only/never, generic skill instructions present).

Original twelve dirty-file SHA-256 fingerprints were captured before P2-07 and retained in /private/tmp/job-tool-p2-20261023/original-dirty-sha256.json. Later source edits require baseline-to-current partial staging and reverse reconstruction for preservation checks.

## Recovery checkpoint — 2026-10-24

An in-process scout hit the usage limit again while checking P2-07 staging. Development stopped under the harness quota rule; no paid-provider/model fallback was requested. P2-01 through P2-06 are committed as listed above. P2-07 producer checks passed (45 passed, 1 legacy server test deselected, zero pytest fence events), but its commit is pending scope/verification checks.

P2-07 staged set: src/job_hunt_index.py, src/job_hunt_scheduler.py, tests/test_digest_pipeline.py, tests/test_index.py; 373 insertions/22 deletions. Never stage the full dirty source files. Original source changes remain unstaged. Clean projection patch: /private/tmp/job-tool-p2-20261023/digest-init/p2-07-stage.patch; original baseline-to-current patch, baseline snapshots and clean projection checks are alongside it. Cached application passed --check. The scoped cached diff has not yet received the requested scout scope check because of quota.

P2-08 is authorized but has not been implemented. P2-09 through P2-13 also remain pending. On resume: inspect current state and the pending checkpoint-verification answer before retrying any write, finish P2-07 checkpoint, then proceed sequentially from P2-08. Five P1 designs remain approval-pending and excluded.

A complete external read-only verifier request for the existing P2-01 through P2-07 checkpoint was dispatched under /private/tmp/job-tool-p2-20261023/checkpoint-verification/. Its result and raw isolation evidence must be inspected; no qualifying verification is claimed merely from dispatch. Raw generic skill-instruction issue previously failed strict Gate 3. Retained producer browser evidence does not prove OS egress or remote CI.

## Resumed checkpoint — 2026-10-24

P2-07 committed as d62ea94 after scope and original-dirty composition checks. HEAD + original index/scheduler delta + staged P2-07 reconstructed actual current bytes; the other ten original dirty files were unchanged. Producer result: 45 passed, 1 legacy server case deselected, zero pytest fence events.

External checkpoint-verification completed with no BLOCKER/MAJOR/MINOR findings in inspected P2-01 through P2-07, including independent in-memory P2-07 SQL rollback/retry/idempotence checks. It did not independently exercise CV filesystem races or Review Queue browser events. Strict Gate 3 remains unmet: raw read-only/never context is confirmed, but generic Using skills instructions remain in reviewer base instructions. Raw rollout: /Users/lhaclaw/.codex-harness/reviewer/sessions/2026/10/24/rollout-2026-10-24T16-55-10-01a16e9f-80d6-79b3-b3d8-b3af197ceab0.jsonl. No qualifying signoff claimed.

User requested continuation. P2-08 implementation now authorized/in progress; P2-09 through P2-13 remain pending. Preserve existing per-saved-search caps for P2-08; do not add an aggregate-cap feature. Five P1 designs remain excluded and approval-pending.

## P2-09 compatibility clarification

Existing partial multi-keyword success is a valid rendered page: failed terms keep their incoming offsets and can retry at the successor cursor. Preserve this behavior. A successfully rendered partial page may be replayed identically, including its unchanged failed-term cursor; this does not cache an all-failed response or advance failed terms. All-failed/source-error/render-error paths must not commit seen state or a failure response. Test both lost-response replay and eventual recovery of the failed keyword on the successor request.

Bind search state/replay to the full configured profile/state namespace, source, normalized query/filter identity and complete cursor vector; include the current hidden-filter fingerprint or invalidate explicitly when it changes. Unknown/expired/evicted state or cursor must yield a clear restart-required result, not silently filter an unseen page against consumed state. The client must show an actionable restart message/link using safe DOM data, while ordinary transient errors retain their current retry URL and selection state. Preserve existing low-level dedup helper semantics; handler replay is a separate atomic preparation contract.

## P2-08 checkpoint

Committed d3e6695. Producer: 115 passed, 1 legacy server case deselected, zero pytest fence events. Stage scope and original-dirty composition checks passed for all four files. Baselines, normalized patch, clean projection and logs: /private/tmp/job-tool-p2-20261023/linkedin-digest/. Real LinkedIn/provider behavior and qualifying independent verification remain UNVERIFIED. P2-09 read/plan started; implementation awaits proposal acknowledgment.

## P2-09 implementation contract approved

Add a high-level initial commit and per-search prepare/replay API alongside unchanged low-level dedup helpers. Initial HTML is fully prepared before state registration/send; More prepares against draft seen state under a per-search lock, then commits JSON-serializable rendered payload, seen state and successor together before response send. Fetch/render/all-failed/serialization errors do not commit. Send failure retains replay.

Identity includes canonical state root, configured profile path and loaded candidate identity, source, normalized noncursor query/take/exclusions, complete scalar/vector cursor and frozen hidden lookup fingerprint. Narrow scope addition approved: optional lookup= on src/job_hunt_not_interested.py.filter_results, default behavior unchanged, to use one frozen lookup through request filtering. Recheck current identity before commitment. Add optional prepare_only on render_home while preserving ordinary callers.

Bounds: one-hour TTL, at most 500 searches after insertion, 8 replay pages/search, 2 MiB replay/search, 32 MiB aggregate replay, 2000 seen jobs/search. Oversized preparation/unknown/expired/evicted cursor produces HTTP409 restart-required with safe actionable client link while retaining current cards/selection. Keep only current successor plus retained replay keys, without unbounded tombstones. Per-search lock may acquire the short registry lock; registry pruning must not wait on a per-search lock.

Replace the old deliberate unissued-cursor jump handler assertion with explicit409 behavior, preserving complete vector execution checks at the lower helper. Required new tests cover render/serialization/send failures, identical concurrent retries, partial-keyword successor recovery, identity mutation during preparation, TTL/cap/page/byte eviction and visible safe restart behavior.

## P2-10 publication and lifecycle contract refinements

Fresh technical advisory: /private/tmp/job-tool-p2-20261023/qualitative-design-review/answer.txt (three HIGH ordering/predicate/transition clarifications and one MED timing clarification; not implementation findings). Incorporate all before code; generic reviewer skill instructions still prevent Gate 3 qualification.

- One short write transaction validates qualitative ownership, owned queue row and cancellation intent, publishes the generation-tagged JSON, completes qualitative SQL and completes owned queue SQL, checking every affected-row result. Cancellation committed first prevents publication; publication committed first preserves completed work. Provider calls stay outside locks. Test cancellation before guard, after JSON replacement and failure between SQL completions. JSON and SQL are not crash-atomic; failed publication is not accepted by readers.
- Retain a durable completed generation separately from cleared running ownership. Actual UI/export readers accept managed artifacts only against matching completed SQL generation; malformed/missing/mismatched metadata or index-read failure fails closed. Legacy compatibility is explicit and cannot bypass a newer managed running/error generation. Test legacy-survives-new-run, index failure and replacement between reads. Rejected content never enters GET backfill.
- Retry/quota/release validates both current live claims and applies qualitative transition, queue transition and any authorized batch annotation in one transaction, returning explicit outcomes. Capture restorable state during acquisition and never restore expired running ownership/token. Test takeover at every transition boundary and quota failure immediately after stale recovery. Unequal leases produce retryable waiting without consuming provider retry budget.
- Active iff now < lease_until; expired iff now >= lease_until. Sample injected aware UTC time after acquiring the ownership guard; expired owner cannot renew. Stale reset must respect renewal. Test guard acquisition crossing expiry, renewal/reset race and repeated waiting. Preserve Pacific quota accounting independently.
- Force archive and GET grade backfill are additional authoritative writers: archive under the same current-owner guard with safe failure cleanup; stale archive cannot move replacement artifact. Backfill rereads current artifact/index under the publication guard or uses equivalent generation predicates, never saving a stale full dict.
- Actual on-demand and queued callers must propagate ownership. Legacy token/lease migration requires quiescing old-version writers during upgrade; no real process signals/deployment are authorized by this code slice. Runtime quiescence remains UNVERIFIED.

## P2-09 checkpoint

Committed 490c94d. Producer: 76 passed, 10 legacy server cases deselected; genuine Chromium retry/restart tests: 3 passed. Both runners report seven expected preflight denials and zero pytest fence events. Seven-file staging/read-back and original-dirty preservation checks passed. Evidence: /private/tmp/job-tool-p2-20261023/search-replay/. A fresh external read-only P2-09 check is running under /private/tmp/job-tool-p2-20261023/search-replay-verification/; no qualifying certification claimed. Add all three test_search_replay_browser.py cases to P2-12 required CI coverage alongside the older seven and Queue five.

P2-10 proposal is being prepared from the corrected ownership/publication contract. No P2-10 source edits yet. P2-11 through P2-13 remain pending.

## P2-10 implementation proposal approved

Use qualitative claim_token, lease_until, latest managed generation and durable completed_generation, plus queue lease_until. Thirty-minute aware-UTC leases, clocks sampled after BEGIN IMMEDIATE. Capture safe previous business state during acquisition, never from an unguarded caller pre-read. Legacy running rows without owner/lease become recoverable unowned state after documented old-writer quiescence. Legacy job-only seed/finish/release APIs cannot alter managed rows.

Pipeline and actual on-demand/queue callers carry the qualitative claim and optional queue owner. Renew both live claims together; unequal leases yield waiting without consuming retry budget. Unified publication completes JSON + qualitative SQL + owned queue SQL under one guard, with rowcount/cancellation checks. Unified nonpublished transitions validate both claims before changing result/queue/batch. Quota annotation touches only authorized pending batch rows, never another running owner. Callers do not separately complete a queue after successful publication.

Strict shared storage reader uses the guarded SQL/artifact snapshot: managed artifact requires well-formed versioned generation metadata, matching completed_generation and status=done. Truly unmanaged legacy artifacts may be accepted only when no managed marker exists and a successful index read shows no row or legacy done. Missing/malformed managed metadata never falls back to legacy; index-read errors reject all content. GET grade backfill rereads accepted current content under guard; archive is owner-guarded and inside caller cleanup handling.

Coherence restriction: quota restoration can return status=done only when the prior managed completed artifact is still present and accepted by the strict reader. If archival, legacy invalidation or a missing/mismatched artifact prevents that, restore unowned retryable pending/error with a visible reason, never done-with-unreadable-result. No new legacy artifact conversion feature. Keep the latest managed marker to prevent legacy bypass after a managed attempt. Expired owner/token is never restored. Cross-store crash atomicity, mixed old-version writers and live runtime behavior are not claimed.

## P2-09 fresh check result

External read-only check completed with BLOCKER/MAJOR/MINOR all NONE. It independently reproduced the old first/retry visible-count failure (1,0), then executed AST-extracted memory checks for identical lost-send replay, four concurrent retries with one fetch, successor dedup, mutation isolation, vector/failed-keyword recovery, exact TTL and cache limits; no blocked external operations/application entrypoint imports. Fourteen UI search-function hashes and the other six P2-09 files matched afterward. Full handler/browser/server execution remained UNVERIFIED by that check, distinct from producer unit/browser evidence.

Raw /Users/lhaclaw/.codex-harness/reviewer/sessions/2026/10/24/rollout-2026-10-24T18-21-02-01a16eee-1f0a-7990-abd4-0481ea8b4155.jsonl confirms read-only/never but retains generic Using skills instructions; strict Gate 3 still unmet. Full report: /private/tmp/job-tool-p2-20261023/search-replay-verification/answer.txt. No P2-09 corrective patch requested. P2-10 implementation has started from its approved corrected contract.

P2-10 grade-backfill coherence: grade backfill also changes JSON and SQL. JSON success followed by SQL-grade failure must not leave an apparently accepted same-generation artifact with inconsistent index grade. Use a new completed publication generation for backfill (or safely restore the old artifact before unlocking) so failure remains fail-closed. Test injected SQL failure after backfill JSON and stale GET after replacement. This extends the existing generation/publication predicate, not a legacy conversion feature.

P2-10 clean-checkpoint acceptance: storage/index/scheduler have pre-existing dirty helpers absent from HEAD. AST compilation alone cannot prove a clean staged checkpoint has no dependency on them. Execute the focused new ownership checks against a disposable HEAD plus P2-10 clean projection, as well as the working-copy tests, without absorbing original hunks. Preserve exact server/browser deselection nodes for P2-12 loopback integration; blocked-socket/timezone baseline failures are not clean passing evidence. Public Pacific IANA reads must be explicit, and date math must not pass via a swallowed local-time fallback.

## P2-11 narrow persistence scope approved

Typed analysis loading drops unknown future keys, so preserving only dataclass fields is insufficient. Add a dedicated raw llm_* group loader and optional preserved_llm_fields argument to storage.save_job_analysis, with default behavior unchanged. Deterministic rescore carries recognized llm fields in the typed result and merges the complete raw group into one serialized atomic JSON write before index/queue projection; no transient two-write erasure or path-helper bypass. Include future keys, nested values and explicit nulls. Preserve manual fields, market snapshot and existing threshold/requeue/CAS policy; no extra provider calls. Focused working-copy and clean HEAD-plus-slice projection tests must pass without dependency on pre-existing dirty helpers. Implementation waits for P2-10 checkpoint.

## P2-10 checkpoint

Committed d5f49e9 as a local producer checkpoint. Final worktree tests: 159 passed, 58 HTTP/browser cases deselected; clean HEAD+slice projection: 41 passed. Both runners report zero pytest fence violations, seven expected preflight denies and explicit public Pacific IANA reads; real summer/winter quota date boundaries passed. Ten-file staged scope matched the clean projection and composed exactly with the original dirty delta. Original three touched dirty files reconstruct exactly; the other nine original dirty files retain their hashes. New staged files were absent at baseline; no pre-existing untracked files absorbed.

Evidence: /private/tmp/job-tool-p2-20261023/qualitative-ownership/ including migration-reader-notes.txt and excluded-http-nodeids.json. The 58 cases must be covered by the dedicated P2-12 loopback integration mode. Live old-writer quiescence, runtime migration, providers and cross-store crash atomicity remain UNVERIFIED. External read-only fresh verification is running under /private/tmp/job-tool-p2-20261023/qualitative-verification/; no qualifying certification claimed. P2-11 implementation now proceeding; P2-12/13 remain pending.

P2-11 clean-HEAD constraint: generic storage atomic-writing improvements belong to original dirty work. The optional preservation save path may use a minimal analysis-specific stdlib tempfile/replace writer without changing default saves or absorbing those original hunks. Reuse a path helper present in clean HEAD, or add a narrowly owned independent analysis helper; clean projection must execute it. Restrict preservation overlay to string keys beginning llm_ so computed/manual fields cannot be overridden. Test replacement failure preserves the prior analysis bytes.

## P2-11 checkpoint

Committed 2458638. Working-copy and clean HEAD+slice projection each report 43 passed, 1 HTTP case deselected; zero pytest fence violations. Full raw llm_* preservation (known/future/nested/null), manual state, done queue, one snapshot and replacement-failure preservation are covered. Three-file scope and original-dirty composition checks passed. Evidence: /private/tmp/job-tool-p2-20261023/reeval-llm-preservation/. The exact excluded node is recorded for P2-12 integration. Retained AI text may reflect earlier deterministic inputs; no provider calls or freshness guarantee added. P2-12 proposal is next; P2-13 remains pending.

## P2-10 fresh verification follow-up required

The completed fresh read-only check found two MAJOR issues against both working source and clean d5f49e9 (no BLOCKER/MINOR): /private/tmp/job-tool-p2-20261023/qualitative-verification/answer.txt. (1) reset_stale_eval_queue_running charged retries for expired queue leases while the same-job qualitative owner remained active; retries=4 could become terminal error. (2) standalone queue finish/retry/release accepted the old queue token after qualitative reclaim, without paired qualitative ownership validation.

Fix only stale reset, standalone transition guard and necessary wrapper plumbing/tests. Preserve retryable pending/waiting without retry charge while a qualitative owner is live; cancellation retains precedence. Reject standalone compatibility transitions for any managed qualitative generation unless paired ownership is proved; legitimate managed worker paths must use owned/transactional APIs. Preserve unmanaged compatibility. Required regressions: staggered leases at retries=4 with no provider work and unchanged retry budget; parameterized finish/retry/release after qualitative reclaim must change neither queue nor qualitative state; cancellation and normal managed/unmanaged workflows still pass. No new schema association is needed if standalone APIs are intentionally unmanaged-only. Working and clean projection focused suites required before checkpoint.

Other independent in-memory P2-10 checks passed, but filesystem/browser/crash behavior remains UNVERIFIED. Raw read-only/never rollout retained generic Using skills instructions, so strict Gate 3 still fails. Two fixes are mandatory before P2-12 implementation.


### Continuation checkpoint: P2-10 follow-up committed

- Commit `01fd28a` contains only the paired-ownership retry recovery correction, standalone managed queue transition fencing, and focused regressions.
- Producer evidence: 165 passed / 58 deselected in the working tree; 73 passed in the clean projection. Both test fence summaries were clean.
- Read-only staged-scope inventory confirmed exact projection bytes and preservation of the original dirty delta. This is scope evidence, not independent functional certification.
- Fresh external read-only follow-up verification is pending. Strict fresh-context qualification remains unproven because prior reviewer raw prompts contained generic skill instructions.
- P2-12 implementation may now proceed from its approved proposal. P2-13 documentation inventory may run read-only in parallel. P1 designs remain excluded.


### P2-13 documentation implementation contract

Implement after the P2-12 code/test checkpoint. Follow `docs/docs-update-checklist.md`; documentation and comments remain English. Preserve the original dirty deltas in INDEX, PROJECT_LOG, PROJECT_TODO and function_list; use clean HEAD staging projections. Back up existing institution/config documents before modifying them. Do not alter unrelated URL-ingestion, Issue 16, P3 or P1 design content.

Acceptance:

1. Correct current-state descriptions in PROJECT_CONTEXT and docs/ui_scope: implemented saved searches/digest and all-source pagination; distinguish manual AI actions from the profile-gated scheduler/worker. Preserve dated baseline/history.
2. Correct the documentation checklist footer lookup to `src/ui_state.py` (`_PAGE_UPDATED`), without fragile approximate line numbers. Refresh the actual footer date only if required by the checklist.
3. Reconcile INDEX and docs/function_list with implemented APIs/modules/tests: CV storage, profile-aware CV fallback, multipart CV limit (5 MiB file plus 64 KiB request overhead) versus ordinary 1 MiB cap; search prepared replay/bindings/atomic state commit/bounded cache/restart; resumable marked digest initialization, bounded LinkedIn details, complete raw llm_* rescore retention; qualitative leases, paired ownership, guarded publication/readers, cancellation, unmanaged-only standalone compatibility, and waiting without retry charge. Preserve the distinction between low-level legacy helpers and the new handler API.
4. Update affected current STATUS headers/supersession notes in F1_v2_recheck_design, backlog-01-daily-digest-design, career-ops-absorption-design, 2026-07-21-search-score-filter-plan, export-bundle-2026-09-22 and cv-tailoring-brief. Preserve their historical design bodies. State retained AI text can reflect older inputs; deployed old writers must be quiesced for ownership migration.
5. Add dated narrow PROJECT_LOG/PROJECT_TODO updates and a final 13-item P2 ledger here. Keep all five P1 designs approval-pending. Record actual P2-12 evidence only after it exists; never sum overlapping test runs into an aggregate claim.
6. Clearly separate committed code, synthetic unit/integration/browser evidence, independent advisory review and UNVERIFIED remote CI/live providers/production behavior. Strict Gate 3 certification remains PARTIAL when raw reviewer startup includes generic skill instructions even with read-only/never.
7. Fresh read-back confirms intended edits; verify referenced paths/functions/commands and run the required documentation AST check using a disposable fenced environment. Do not touch private artifacts, secrets, .env, user profiles or providers. Deliver normalized clean staging patch plus original-dirty reconstruction evidence.

This contract is documentation reconciliation only, not authority for further product or security changes.

## Final P2 implementation ledger — 2026-10-25

Implementation and qualification are separate. P2-01–P2-12 are committed as shown;
P2-13 is this documentation checkpoint. All implementation slices are complete;
strict independent certification remains PARTIAL. The six dated design bodies
remain historical beneath their current supersession headers. Five P1 designs
remain approval-pending; no P1, Issue 16 or P3 work is approved or claimed here.

| Slice | Implemented behavior | Checkpoint | Focused evidence directory under `/private/tmp/job-tool-p2-20261023/` |
|---|---|---|---|
| P2-01 | Adzuna search logging uses fixed/class/status information; key-bearing request exceptions never reach logs. | `1dd70d1` | `adzuna/` |
| P2-02 | Multipart CV transport admits 5 MiB + 64 KiB overhead; file limit 5 MiB, ordinary POST cap 1 MiB, exact oversized-file 413. | `2fd3a86` | `cv-upload/` |
| P2-03 | Profile-aware tailored-CV candidate selection skips mismatched AI candidates and permits matching ordinary fallback. | `897f269` | `profile-fallback/` |
| P2-04 | ATS recheck enforces active profile identity when available. | `b3d30b0` | `ats-identity/` |
| P2-05 | Four CV save paths share canonical-root descriptor writes, reject descendant/leaf symlinks, preserve references and outside files on failure; existing configured-root symlinks resolve as trusted roots. | `c1c0ddb` | `cv-containment/` |
| P2-06 | Review Queue IDs stay data in escaped attributes/static listeners; initial and dynamic iframe paths encode the exact ID. | `b29a716` | `review-queue/` |
| P2-07 | New explicit unfinished ingestion markers resume metadata/queue initialization with stable first-seen/unread/manual state; intentional omissions complete, completed/processing work is retained. Unmarked legacy partial rows are not guessed. | `d62ea94` | `digest-init/` |
| P2-08 | LinkedIn empty-card details are lazy after deduplication and bounded by each saved search's existing import cap; no UI select side effects/JD fabrication. Strict HTTP errors precede short-body/redirect heuristics; explicit blocking statuses and default UI handling are retained. | `d3e6695`, diagnostic follow-up `c3a8739` | `linkedin-digest/`, `linkedin-diagnostic-followup/` |
| P2-09 | Initial HTML renders before binding/seen/successor commit; bound More freezes serialized JSON, successor and seen together; retries replay; expired/evicted/unknown or changed bindings show restart. Valid partial pages keep failed-term cursors; transient preparation failures consume no state. Legacy low-level helper behavior is retained. | `490c94d` | `search-replay/` |
| P2-10 | UTC leases, paired ownership/cancellation guards, accepted completed-generation readers, guarded archive/backfill and coherent quota restoration. Follow-up preserves retries while a qualitative owner remains live and rejects managed standalone queue transitions. Old writers must be quiesced for migration. | `d5f49e9`, follow-up `01fd28a` | `qualitative-ownership/`, `qualitative-followup/` |
| P2-11 | Deterministic re-evaluation retains the entire raw `llm_*` group, including future/nested/null values, through one optional atomic analysis save; human fields/done queue policy retained. AI text may reflect older inputs. | `2458638` | `reeval-llm-preservation/` |
| P2-12 | Shared `required_browser` mode makes missing dependency/launch/selected skip fail; all 15 named cases are marked, browser-only provider fakes and Python 3.10 CI Playwright 1.59/Chromium installation are configured. Ordinary local mode remains optional. Legacy HTTP fixtures use owned Origin and issued cursors. | `de5521f` | `browser-ci/` |
| P2-13 | Current context/UI/API/feature maps/checklist, six historical-spec status headers and dated log/TODO reconciled; source footer unchanged for docs-only work. Original dirty deltas preserved via clean projections. | this documentation checkpoint | `docs-reconciliation/` |

### Final acceptance evidence and limits

- One deduplicated current non-HTTP/non-browser regression: **645 passed, 75 deselected in 6.67s** across 22 files. Exact selected/excluded nodes: `browser-ci/aggregate/selected-nodeids.json` and `excluded-nodeids.json`.
- Earlier P2-12 deferred HTTP/browser union: **86 passed in 69.85s**, including all 15 required Chromium cases. This includes five legacy F1 HTTP cases discovered beyond the initial 81-case manifest. Initial failures and their fixture/harness corrections are retained under `browser-ci/loopback-first81/` and `loopback-first86/`; no assertions were removed or skipped to obtain acceptance.
- Earlier clean HEAD + only P2-12 projection: **106 passed in 68.69s**, repeating 86 HTTP/browser cases plus 20 helper cases. This demonstrates independence from original dirty source and is not an extra coverage total.
- Actual required-mode setup/call/teardown skip canary: expected pytest exit 1, one failure/two errors/zero skipped. Final accepted suites have zero failures/errors/skips. Final runners logged seven expected preflight denials, zero unexpected Python fence events; browser/HTTP runners left no owned ports open. Exact driver children were allowed only in bounded browser mode; no OS-level native browser egress isolation claim.
- LinkedIn diagnostic follow-up `c3a8739`: working and clean HEAD+two-file focused suites each **120 passed, 1 deselected** (1.11s/1.04s). Added 17 in-memory response cases cover short/padded HTTP errors, explicit blocking statuses, successful challenges and default-mode parity. Latest 645 is a working-copy aggregate, not a clean 645 run; earlier 86/106 checks were not repeated for this strict-only diagnostic change. Evidence: `linkedin-diagnostic-followup/commands.txt`, `readback.json`.
- Commands and logs: `browser-ci/commands.txt`, `acceptance-summary.json`, per-run `results.xml`/`run-summary.json` and selected node manifests. Source references and required AST/read-back results for this docs checkpoint live in `docs-reconciliation/`.
- Read-only independent advisory checks are separate. The P2-10 follow-up review reported NONE Blocker/Major/Minor; P2-11/12 final-source advisory likewise reported NONE Blocker/Major/Minor in in-memory/static checks (`final-source-verification/answer.txt`). Actual filesystem/crash/runtime behavior is outside those checks. Final P2-08 diagnostic/P2-13 documentation advisory is pending at this checkpoint. Raw startup retained generic skill instructions despite read-only/never, so strict Gate 3 certification remains **PARTIAL**.
- **UNVERIFIED:** actual remote CI/Python 3.10 execution, live providers, production behavior, deployed old-writer quiescence/migration, crash atomicity across JSON/SQLite, and native browser OS egress isolation. Synthetic request/fence handling is not proof of those properties. No secrets/private profiles/CVs/.env/providers were inspected or used for acceptance.
