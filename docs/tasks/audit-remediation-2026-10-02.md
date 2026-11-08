# Sequential audit remediation

<!-- STATUS -->
Implementation status: ⚠️ 2026-10-02 — all six chunks implemented sequentially. Producer focused suites: 181 passed. Independent fresh-context verification pending. No routes changed. Storage helpers: `_validated_record_id`, `_contained_path`, `_write_json`; URL helpers: `_NoRedirectHandler`, `_fetch_robots_lines`, `_RobotsCache.is_allowed`.
<!-- /STATUS -->

Fix each acceptance point independently; do not access personal data or live services.

1. Storage IDs: reject slash, backslash, NUL and exact dot/double-dot after trimming; preserve ordinary Unicode, spaces and punctuation. Both state and qualitative paths must remain inside their intended directories, including existing symlink escapes. Save, load and archive operations must use the guarded paths. Regression tests use temporary synthetic state only.
2. Redirects: disable automatic following and validate each destination before requesting it, with a finite redirect limit and regression coverage for rejected destinations.
3. Robots caching: cache rules by origin, evaluate permission for each requested path; allowed-first and denied-first sequences must retain different path permissions.
4. Robots timeout: explicitly bound robots network reads and preserve existing fail-closed behavior; mock network calls to verify the timeout and failure handling.
5. JSON persistence: serialize before writing, use a temporary sibling and atomic replacement, clean up on failure, preserve the previous valid JSON on write/replace failure. Multi-file saves remain separately atomic, without a transaction guarantee.
6. Date-sensitive tests: replace accidental dependence on expired fixed dates with deterministic clock control or dates relative to the tested reference. Preserve deadline boundary assertions.

Validation runs in a disposable source/test copy with no personal data or credentials. No commit, push or external service request is part of this remediation.

## Validation and limits

- Validation copy contains only source and tests, with synthetic temporary state. Focused command: `python3 -m pytest tests/test_storage.py tests/test_storage_path_security.py tests/test_storage_atomic.py tests/test_qualitative.py tests/test_parsing.py tests/test_parsing_redirect_security.py tests/test_parsing_robots_security.py tests/test_market_position_route.py -q`: **181 passed in 0.52s** (project venv, credential-free environment).
- Existing tests adapted: robots failure mocks the explicit fetch helper; salary-cache tests share a fixed clock, advancing that clock in the refresh test. Added TTL-minus-one, exact-TTL and TTL-plus-one assertions.
- Multi-file pipeline persistence remains nontransactional; each JSON replacement is atomic independently. No filesystem race-proof guarantee, directory-fsync crash-durability guarantee, hard DNS timeout, pinned DNS, or strict slow-drip wall-clock cutoff is claimed.
- Required independent verification remains UNVERIFIED because the current verifier isolation/approval gate cannot be satisfied. Live providers and visual UX were not exercised.

- Authoritative broadened run: `env -i PATH=/usr/bin:/bin:/opt/homebrew/bin TMPDIR=/private/tmp PYTHONDONTWRITEBYTECODE=1 <project>/venv/bin/python -m pytest tests -q -p no:cacheprovider --tb=short` in the sanitized copy: **1194 passed, 8 skipped, 101 failed in 10.85s**. All 101 failure blocks are sandbox `PermissionError` from socket-based integration; these paths remain UNVERIFIED. The copy also includes the four viewer Python modules needed for imports and tracked `restart.sh`/`start.command`; it contains no original data, viewer JSON, credentials or environment files.
- An initial system-Python run was superseded after restoring the missing test-harness scripts and using the existing project venv. No dependencies were installed.
- Original audit persistence scope is only partly addressed: interrupted individual JSON writes are protected, while partial completion of a multi-file pipeline is still possible.
