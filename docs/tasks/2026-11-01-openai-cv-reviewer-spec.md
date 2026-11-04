# OpenAI CV reviewer through the local Codex CLI — design spec

Status: ENABLED 2026-11-04 (Mike: "Yes, enable it"), enable commit 40cc011; steps 1-4 passed: (1) Mike read the OpenAI pages live and accepted the points, "All pass, go step 2"; (2) `~/.codex-cv-reviewer` created and logged in; (3) self-check 4 of 4 PASS on codex-cli 0.166.0; (4) eval 19 of 19 cases, recall 1.000, precision 0.833, UNCHECKED 0, 3 of 8 clean statements flagged.
Earlier status: r6 2026-11-02, APPROVED by Mike 2026-11-02 ("Yes, build it"). BUILT 2026-11-02/03 in four commits:
af5c746 (chunk A, Codex CLI adapter), 4c7e6ce (chunk B, provider-aware chain, eval option, self-check),
9d12c38 (chunk C, consent scope), 5819a92 (fix, test pins and bounded drain). It was NOT ENABLED until the
"Live check, then enable" steps 1-5 passed, each with Mike's consent on the day; REVIEWER_MODELS is now
('gpt-6-luna', 'gemini-3.5-flash') since 40cc011.
Docs (O-12) recorded 2026-11-03 after the build; updated again 2026-11-04 after the live check and the enable.
Parent spec: docs/tasks/2026-10-26-ai-cv-blind-review-spec.md (blind reviewer; "## Fix 4" reviewer chain).
Parent-spec line numbers cited below (D3 :78-81, Providers :144-146, :172, S0, S2) are as of commit 0e56f5c;
the notes added to the parent spec on 2026-11-03 shifted later lines by up to 27 (it grew from 1160 to 1187 lines).
Evidence folder (local, untracked): archive/cv-review/openai-reviewer-2026-11-01/ ("EV" below).
Review history: r1 reviewed by Codex 2026-11-01, VERDICT NOT READY (EV/spec-codex-review-r1.md);
r2 reviewed by Codex, BUILD WITH FIXES, one HIGH (EV/spec-codex-review-r2.md); r3 reviewed by
Codex, BUILD WITH FIXES, one HIGH (EV/spec-codex-review-r3.md). r4 folds in all r3 points but
was NOT reviewed again: the design-council limit of three Codex rounds was reached
(see "## Review points").

## Decisions (Mike, 2026-11-01)
- Role: "OpenAI 主審 (Recommended)". OpenAI reviews every AI CV rewrite; the Gemini
  reviewer chain from Fix 4 becomes the fallback.
- Model: "只用 gpt-6-luna".
- Access: "try to  use existing CLI connection" (Mike's words, spacing as typed), then,
  after the r1 review and the paid-API comparison, "Keep Codex CLI". The app calls the local
  Codex CLI signed in with Mike's ChatGPT account. No OpenAI API key, no prepaid credit.
  Note for approval: the design needs Mike to sign in once more, into a separate Codex home
  for the app (O-2); the existing logins are not reused.
- The writer is unchanged (Gemini chain, src/job_hunt_llm.py:25-27).

## Why
- Parent spec D3 (:78-81) waived the rule "reviewer must be a different family from the
  writer" because only Gemini was free. An OpenAI reviewer restores that rule.
- It reduces the alias risk in Fix 4 "Limits kept" (the risk remains whenever the Gemini
  fallback answers): Google lists gemini-3.6-flash as the
  recommended replacement for the writer's gemini-3-flash-preview and already routes the
  reviewer's gemini-3.5-flash to gemini-3.6-flash (deprecations page, read 2026-11-01,
  last updated 2026-10-22).

## Facts (codex-cli 0.166.0, ChatGPT login; each probe n=1, 2026-11-01; files in EV/probes/)
All probes except "no login" ran with CODEX_HOME=~/.codex-harness/reviewer (the harness
reviewer home, which has its own config.toml, AGENTS.md, plugins and skills), NOT with an
O-2-shaped home. Whether the results hold in the O-2 home is UNVERIFIED until the self-check
(O-9) runs there (live check step 3). Timings and exit codes below are from the session
transcript; the event and answer files are in EV/probes/.
- P1 `codex exec -m gpt-6-luna --output-schema <file>` on a trivial prompt returned
  schema-valid JSON in 3 s (prompt.txt, answer-gpt-6-luna.txt, events-gpt-6-luna.jsonl).
- P2 With 9 features off, the shell tool was gone (events2.jsonl).
- P3 With the same 9 features off, the model still had and USED web search (`web__run`,
  two `web_search` events), plus image_gen, view_image, goal tools, apply_patch and MCP
  resource tools (answer3.txt, events3.jsonl). The 9 flags are NOT enough.
- P4 With the 15 features in O-1 off and `-c web_search="disabled"`, the model reported only
  apply_patch, clock__curr_time, two MCP listing tools and read_mcp_resource; the events had no
  web_search, command or file item; a canary file outside `-C` was not read (token absent
  from events); no file was created in `-C` (answer4.txt, events4.jsonl). The tool list is
  the model's own report; the event types are the stronger evidence. The two MCP calls in
  P4 returned `{"resources":[]}` and `{"resourceTemplates":[]}` (events4.jsonl lines 7-8).
- `-c 'mcp_servers={}'` is accepted by codex 0.166.0 (`codex debug prompt-input`, exit 0; a
  non-table value is rejected with "expected a map"), so the MCP server list can be forced
  empty on every call.
- P3 and P4 ran under `env -i` with only PATH="/usr/bin:/bin:/opt/homebrew/bin", CODEX_HOME
  and TMPDIR (no HOME): login worked. `/opt/homebrew/bin/codex` is a symlink to a node script
  (`#!/usr/bin/env node`), and node is only in /opt/homebrew/bin, so the child PATH must
  contain node's directory (O-1).
- P4's answer cites "the reviewer instructions": the Codex home's AGENTS.md was loaded even
  with `--ignore-user-config`. So the Codex home must hold an empty AGENTS.md (O-2).
- Failure events: no login → exit 1, several `{"type":"error","message":"Reconnecting... n/5
  (unexpected status 401 Unauthorized ..."}`, then `turn.failed` with "401 Unauthorized"
  (events-nologin.jsonl, 16 s). Unknown model → exit 1, `turn.failed` "The '<model>' model
  is not supported when using Codex with a ChatGPT account." (events-badmodel.jsonl, 2 s).
  Usage limit → an error event and `turn.failed` "You've hit your usage limit ..."
  (events-usage-limit-2026-10-31.jsonl; exit code not recorded).
- With `--ephemeral`, a grep of the Codex home after P3/P4 found no copy of the prompt text.
- `-s read-only` is not a read boundary (~/.claude/protocols/codex.md rule 3, n=1,
  2026-09-15); the tools being off, not the sandbox, is what stops file reads. The
  read-only sandbox rejected an apply_patch write in P3 (events3.jsonl:6); P4 made no write
  attempt, so the sandbox block under the final flag set is untested.
- The reviewer receives the full original CV, the rewrite, target roles, industries, job
  skills and review items (prompt sections src/job_hunt_cv_review.py:579-611; target roles
  and industries are added in `build_review_source`, :74-81). The rewrite and job skills
  derive from web job ads: untrusted input.
- Mike's ChatGPT plan is probably Plus (UNVERIFIED: the 2026-10-31 usage-limit message said
  "Upgrade to Pro"); the Plus figures below assume it.
- Codex usage limits are shared with Mike's development use (hit 2026-10-26 and
  2026-10-31). OpenAI's estimate for Plus: Luna 350-3,000 messages per 5 hours, "Weekly
  limits may also apply" (learn.chatgpt.com/docs/pricing, EV/codex-cli-research.md).
- Privacy and terms (EV/codex-cli-research.md, checked by EV/codex-cli-research-verifier.md:
  the learn.chatgpt.com claims pass; help.openai.com and openai.com returned 403, so the
  training and terms points below are search SNIPPETs, UNVERIFIED):
  - Plus content "may" be used for training unless "Improve the model for everyone" is off;
    that toggle is said to cover Codex tasks. No retention period found for Codex CLI.
  - Docs list "`codex exec`, and scriptable workflows" for Plus, but also say "API keys are
    the right default for automation" and a ChatGPT session may expire (re-login).
  - Third-party copies of the Europe Terms (which cover the UK) ban "Automatically or
    programmatically extracting data or Output". Whether a personal script calling the
    official `codex` binary falls under it is UNVERIFIED.

## Behaviour (one build commit, then a small enable commit)
- O-1 New module src/job_hunt_codex.py, `call_codex_reviewer(prompt, model, schema, *,
  timeout=180)` returning the 4-tuple of `job_hunt_llm._call_gemini_model`:
  `(text, error, should_try_fallback, failure_kind)`. It never raises: any exception inside
  becomes `server_error`.
  - One child process started by `_run`, which wraps `subprocess.Popen` (so the process
    group can be killed) with an argument list (never `shell=True`), prompt on stdin, a
    `timeout`, captured output and `start_new_session=True`, inside a
    new `tempfile.TemporaryDirectory()` holding the schema file, the answer file and an
    empty working dir. On timeout the whole process group is killed (`os.killpg`), because
    the node launcher spawns a native child that a plain kill may leave running
    (UNVERIFIED). The launcher is a module-level function `_run` so tests can replace it;
    both the version check and the exec go through it.
  - Exact arguments: `<codex_bin> exec -s read-only -C <empty dir> --skip-git-repo-check
    --ephemeral --ignore-user-config` + `--disable <f>` for each f in `DISABLED_FEATURES` =
    (shell_tool, unified_exec, browser_use, browser_use_external, computer_use,
    in_app_browser, apps, plugins, memories, goals, image_generation, multi_agent,
    view_image, skill_search, skill_mcp_dependency_install) + `-c web_search="disabled"
    -c mcp_servers={} -m <model> -c model_reasoning_effort="low" --output-schema
    <schema file> --json -o <answer file> -`.
  - Shared builders: `resolve_codex()` (binary and node, below), `build_env(...)` and
    `build_exec_args(...)` (the exec argument list above). O-1 and the self-check (O-9) use
    all three, so their exec invocations are identical; the version check (O-3) and the
    self-check's `codex debug prompt-input` use the same binary and environment.
  - `check_codex_ready(*, allow_untested_version=False)` runs the O-2 home check and the O-3
    version check and returns `None` or a failure_kind. O-1 always calls it with the
    default; only the self-check passes `allow_untested_version=True` (a test greps the
    source for other callers).
  - Never present: `--dangerously-bypass-approvals-and-sandbox`, `--approve-for-me`,
    `--dangerously-bypass-hook-trust`, `workspace-write`, `danger-full-access`,
    `--add-dir`, `--worktree`, `--enable`.
  - Child environment is an allowlist, not a copy: `PATH` = "<dir of codex_bin>:<dir of
    node>:/usr/bin:/bin" (duplicates removed), `CODEX_HOME` (O-2), `TMPDIR` (from
    os.environ, else the temp dir). Nothing else.
  - `resolve_codex()`: `codex_bin` = env `CODEX_BIN` if set, else `shutil.which('codex')`,
    used as found (a symlink is NOT resolved for launching; `os.path.realpath` is used only
    for the self-check's printout). `node` = `shutil.which('node')`. If either is missing
    → `not_found`, no launch.
- O-2 Codex home: `CODEX_HOME` = env `CV_REVIEW_CODEX_HOME` if set, else
  `~/.codex-cv-reviewer`. It holds Mike's login (one-time
  `CODEX_HOME=~/.codex-cv-reviewer codex login`, done by Mike), an empty AGENTS.md and no
  config.toml; Codex also writes its own state files there (sqlite files, installation_id,
  seen in the no-login probe). Before each call `check_codex_ready` checks the home exists
  and is not group- or world-writable, AGENTS.md exists and is empty, and no config.toml
  exists; otherwise `server_error` with no call. Whether an empty AGENTS.md removes the
  instruction block is UNVERIFIED until O-9 check 1 runs in this home.
- O-3 Version binding: `TESTED_CODEX_VERSIONS = ('0.166.0',)`. Before each call O-1 runs
  `<codex_bin> --version` (local, no network: UNVERIFIED) with the O-1 environment and
  `timeout=10`; a launch error → `not_found`; a timeout or a version not in the tuple →
  `server_error`; no model call in any of these cases. After any Codex upgrade, reviews fall
  back to Gemini until `scripts/codex_reviewer_selfcheck.py` (O-9) passes on the new
  version and a one-line commit adds it to the tuple. Only the self-check may skip the
  version check, through an explicit keyword `allow_untested_version=True`; nothing else
  passes it (test).
- O-4 Outcome, decided in this order from the exit code, the `--json` events and the
  answer file (the same launch-error rule applies to the version check in O-3):
  1. launch error (`FileNotFoundError`, `PermissionError`, `OSError`) → `not_found`.
  2. `subprocess.TimeoutExpired` → `timeout`.
  3. SUCCESS only if ALL hold: exit code 0; every stdout line that starts with `{` parses
     as JSON; there is at least one `turn.started`, every `turn.started` is followed by a
     `turn.completed` before the next `turn.started`, and the LAST turn event in the
     stream is `turn.completed`; no `turn.failed` event; the answer file exists and is
     non-empty. Then the answer text is returned and parsed as today
     (bad JSON → `bad_json`, stops the chain).
  4. Otherwise a failure, classified by the `turn.failed` message, or if there is none by
     the last `error` event that does not start with "Reconnecting" ("Reconnecting n/5"
     events are retry notices and never decide the outcome on their own):
     - contains "usage limit" → `rate_limited`;
     - contains "401 Unauthorized", "Not logged in" or "not supported when using Codex
       with a ChatGPT account" → `not_found`;
     - anything else, including malformed JSONL, a non-zero exit with no failure event, or
       success events with a missing answer file → `server_error`.
  Fall-through as Fix 4 F4-3: `rate_limited`, `server_error`, `not_found` move to the next
  model; `timeout` stops the chain. Latency with the generation lock held
  (src/ui_handlers.py:1650-1680): a fall-through failure can itself arrive late, so the
  worst case is the 10 s version check plus up to 180 s per model in the chain (about
  370 s with codex + gemini-3.5-flash, about 550 s if gemini-3.8-flash is also enabled).
  These are estimates from the timeouts, not measurements, and not hard bounds: the Gemini
  180 s applies per phase (parent spec Fix 4 F4-3).
- O-5 Provider-aware chain in `run_blind_review`: a model id starting with `gpt-` is called
  through O-1, any other through `_call_gemini_model`. The Google key check moves from
  before the chain (src/job_hunt_cv_review.py:668-670) to just before each Gemini call: a
  Gemini model with no key gives failure `no_key` and the chain moves on. A Gemini-only
  chain with no key therefore still ends UNCHECKED `no_key` with no call (as today); a
  pinned `gpt-6-luna` eval needs no Google key. Writer-model skip, `reviewer_model`
  recording and the fall-through warning stay as Fix 4 (F4-2, F4-5, F4-7).
- O-6 Constants: `EVAL_REVIEWER_MODELS` gains `'gpt-6-luna'`. `REVIEWER_MODELS` is NOT
  changed in the build commit. The enable commit, only after every step of "Live check,
  then enable" passes, sets `REVIEWER_MODELS = ('gpt-6-luna', 'gemini-3.5-flash')`, plus
  `'gemini-3.8-flash'` last if it has passed its own Fix 4 check.
- O-7 Output schema written by O-1: `{"results": [{"id": string, "verdict": one of
  SUPPORTED|EXAGGERATED|UNSUPPORTED, "evidence_quote": string or null, "reason": string}]}`,
  every property required, `additionalProperties: false` (strict structured-output rules).
  The schema cannot express "null only for UNSUPPORTED"; the code validator
  `_validated_results` (src/job_hunt_cv_review.py:614-630) stays the authority and keeps its
  current all-or-nothing behaviour. Prompt text and `REVIEW_PROMPT_VERSION` unchanged;
  grounding downgrade (:717-734) still runs.
- O-8 Consent bound to the provider set:
  - `consent_scope()` = "gemini+openai" if any model in `REVIEWER_MODELS` starts with `gpt-`,
    else "gemini".
  - The page renders the scope next to the checkbox and the JS sends it as
    `consent_scope` with `use_cloud` on rewrite and revise. The server compares it with the
    current scope; a missing value counts as "gemini" (pages rendered before this change).
    A mismatch makes no LLM call and returns 409. When the request carried a
    `consent_scope`, the body is `{"error": "consent_stale"}` and the new JS shows "The AI
    services used for this check have changed. Reload the page and tick the box again."
    When it carried none (an old page, whose `aiErrorText` at src/ui_render.py:62-72 prints
    unknown codes as "<action> failed: <code>"), the `error` value is the readable sentence
    "AI services changed - reload the page", so the old page shows a usable message.
  - Order: the existing 403 `consent_required` check (no `use_cloud`) runs first, then the
    409 scope check; existing 403 tests keep their result under either scope.
  - Text when the scope is "gemini+openai": label (src/ui_render.py:2257) "Send my CV to
    Google Gemini and OpenAI for this rewrite and its check"; error text (:63) and sidebar
    (:3533) name both companies; progress text (:249) "Reviewing your CV against this job".
    With scope "gemini" all text stays as today.
  - The eval keeps its own `--use-cloud` flag; its report header names the provider.
- O-9 `scripts/codex_reviewer_selfcheck.py` (run by a human or Claude after a Codex upgrade,
  with consent; uses Codex quota, no CV). It calls `check_codex_ready(
  allow_untested_version=True)`, then uses `resolve_codex()`, `build_env(...)` and
  `build_exec_args(...)` with the app's Codex home, and PASSES only if ALL hold:
  1. Instructions: `codex debug prompt-input` run with the same home, features and
     overrides shows no AGENTS.md instruction block with any content (local, no network).
  2. Probe call: a canary prompt based on probes/prompt3.txt, changed so that item 5 tells
     the model to call `list_mcp_resources` and `list_mcp_resource_templates` (this wording
     has not been run yet), with a fresh random canary file outside `-C`, ends as SUCCESS
     under O-4, and the answer is valid against its schema.
  3. Events: the canary token appears nowhere in events or answer; there is no
     `web_search`, command or file-change item. MCP items are correlated by item id: every
     `item.started` `mcp_tool_call` must have an `item.completed` with the same id. The
     probe prompt tells the model to call both listing tools, and BOTH
     `list_mcp_resources` and `list_mcp_resource_templates` must appear as completed
     items with `error` null, whose result text parses as JSON equal to
     `{"resources": []}` and `{"resourceTemplates": []}` respectively. Any other MCP tool,
     a missing, errored or unfinished listing call, or a non-empty list → FAIL.
  4. No file appears in `-C`.
  The script prints the version, the codex path, the exact arguments and environment names
  used, and PASS/FAIL per check; it never edits code.
- O-10 Logging: a fall-through logs model and failure_kind only; never the prompt, CV,
  answer, events or stderr.
- O-11 Eval (scripts/cv_review_eval.py): `--reviewer-model gpt-6-luna` accepted; start-up
  check for a `gpt-` model = codex binary found + tested version + Codex home valid, not the
  Google key. Pacing and retry stay as today. `--dry-run` makes no subprocess call.
- O-12 Docs after the build and after the live check: INDEX.md, docs/function_list.md,
  PROJECT_LOG.md, PROJECT_TODO.md (our lines only, Fix 4 F4-12 method), README.md :50-56
  (Codex CLI requirement and privacy note), the parent spec's Providers line :144-146 and D3
  :78-81, which this decision supersedes. Also review, and change only where now wrong:
  docs/product_spec.md:32, docs/user_flow.md:75, the comments at src/job_hunt_cv_review.py
  :502-505 and :633-639 and src/ui_handlers.py:1587 and :1643-1644, and the parent spec's
  :172, S0 :222-235, S2 :318 and :362-373, and Q-C (list in EV/code-map.md).

## Tests (all offline; no codex, Gemini or network call)
- Fence: an autouse fixture in tests/conftest.py replaces `job_hunt_codex._run` with a
  recorder that refuses the call; at teardown the fixture calls `pytest.fail()` if any call
  was recorded (an exception raised inside would be swallowed into `server_error` by O-1
  or by `run_blind_review`, src/job_hunt_cv_review.py:708-711). Both launches (the version
  check and the exec) go through `_run`. Adapter tests opt in to a fake. A test drives
  `run_blind_review` with a `gpt-` model, asserts the fence recorded the attempt, then
  clears the recorder before teardown so this one deliberate trip does not fail it.
- Fixtures: the probe event and answer files used by the tests are copied into
  tests/fixtures/codex_reviewer/ (the EV folder is local and untracked). They hold thread,
  request and cf-ray ids only, no secrets and no CV.
- `check_codex_ready`: only the self-check passes `allow_untested_version=True` (source grep);
  `shutil.which('codex')` or `shutil.which('node')` returning None → `not_found`;
  a group-writable home → `server_error`.
- Command line: every O-1 argument present; every `DISABLED_FEATURES` entry; the web_search
  override; none of the banned flags; prompt sent on the child's stdin (`communicate(input=...)`), never in argv; `shell` not set.
- Environment: exactly PATH, CODEX_HOME, TMPDIR; no `*_API_KEY`, `*_TOKEN`, ADZUNA or HOME.
  PATH starts with the directory of `codex_bin` as found (not its realpath) and contains the
  directory of `node` (regression test for the r4 BLOCKER, using a fake symlinked codex and
  a fake node in a temp dir).
- Home check (O-2): each failing case → `server_error`, no model call. Version check (O-3):
  launch error → `not_found`; timeout or untested version → `server_error`; no model call.
- Outcome (O-4), using the probe event files as fixtures: success; no login; unknown model;
  usage limit; "Reconnecting" lines followed by success (must succeed); turn.completed but
  missing answer; non-zero exit with a non-empty answer (must fail); malformed JSONL;
  TimeoutExpired; FileNotFoundError; an exception inside the adapter (→ `server_error`, no
  raise). Turn order, each with exit 0 and a non-empty answer, all must FAIL:
  `started → completed → started`; two `started` in a row; `turn.failed` present.
- Version check: `--version` timeout (10 s) → `server_error`, no model call.
- Self-check (O-9) logic on recorded or synthetic events, each failing alone: a non-SUCCESS
  run or a schema-invalid answer (check 2); a command or file-change item; an MCP call to
  any other tool (check 3).
- Self-check (O-9) logic on recorded events: the P4 events pass; the P3 events fail
  (web_search); a trace missing either listing call, with an errored or unfinished
  listing, with a non-empty list, containing the canary token, or with a file in `-C`
  fails; a prompt-input render with a non-empty AGENTS.md block fails check 1.
- Chain: codex `rate_limited` → Gemini called and used, `reviewer_model` is Gemini; codex
  `timeout` → Gemini not called; codex success → `reviewer_model` `gpt-6-luna`; Gemini model
  with no key skipped, Gemini-only chain with no key → `no_key` and no call.
- Replies: mixed valid and invalid items, missing and duplicate ids, null quote on SUPPORTED,
  grounding downgrade after a codex reply.
- Record: `reviewer_model` `'gpt-6-luna'` validates and loads.
- Consent: scope "gemini" text unchanged; scope "gemini+openai" text; stale scope → 409 with
  no LLM call on rewrite AND revise; missing scope with a Gemini-only chain → accepted;
  missing scope with an OpenAI chain → 409 with the readable sentence. The page script is
  exercised for both scopes and both actions in the same way the existing consent tests
  exercise it, and the OLD script (as at HEAD before this build) is exercised against the
  scope-less 409 to show it prints the readable sentence.
- Tests that assume a Gemini reviewer get a setup-only pin to a Gemini-only model tuple in
  the build commit, so the enable commit does not break them: at least
  tests/test_cv_review_blind.py:132-150 and :309-321, tests/test_cv_review_eval.py:182-194.
  The builder finds the full list by running the suite once with `REVIEWER_MODELS` patched
  in memory to the enable value (as Fix 4's builder did) and pins each failing test the same
  way; any change beyond a setup-only pin comes back to Mike. Expected to include every
  server-side test that posts `use_cloud` without `consent_scope` (it would get 409 under
  the OpenAI scope): tests/test_cv_review_record.py:240, tests/test_cv_output_containment.py:124,
  tests/test_cv_review_routes.py:130, :144, :155, :194, :204, :212, :353, :388, :417-430, :424,
  tests/test_ui_handlers_uncovered.py:743, tests/test_ai_cv_consent.py:92, :125, :133, :145.
- Existing consent tests (tests/test_ai_cv_consent.py:25, :190, :196-197, :521) get a
  setup-only patch pinning a Gemini-only `REVIEWER_MODELS`, so the enable commit does not
  break them.
- Assertion changes in the build commit, because the script now sends `consent_scope`:
  the request-body assertions at tests/test_ai_cv_consent.py:249, :261, :274, :473, :489
  (approved with this spec). The builder re-checks this list; any other existing assertion
  change comes back to Mike first.
- Eval: `--reviewer-model gpt-6-luna` accepted with no Google key; dry-run makes no
  subprocess call.
- Assertion changes (approved with this spec): tests/test_cv_review_fallback.py:302 (new
  `EVAL_REVIEWER_MODELS`) in the build commit; :303 (`REVIEWER_MODELS[0]`) in the enable commit.

## Acceptance (build commit)
- Full suite: the same 46 known failures as archive/cv-review/baseline-failures-2026-10-26.txt,
  zero new; all new tests pass; the codex fence never trips.
- Dry-run eval: 19 rows, L0 actual equals expected; `--dry-run --reviewer-model gpt-6-luna`
  makes no subprocess call.
- `REVIEWER_MODELS` unchanged; no codex, Gemini or network call during build or verification.
- Simulated enable: the full suite run with `REVIEWER_MODELS` patched in memory to
  `('gpt-6-luna', 'gemini-3.5-flash')` meets the same 46-failure bar, with the codex fence
  never tripping.
- The 13 pre-existing uncommitted files untouched except the four doc files, where only our
  lines are staged.

## Live check, then enable (each step needs Mike's consent on the day)
1. Privacy and terms, by Mike in a browser (our fetches were blocked):
   - "Improve the model for everyone" is OFF in ChatGPT data controls;
   - the separate Codex setting "Include environments" is checked and set as Mike wants
     (whether it applies to the local CLI is UNVERIFIED);
   - Mike accepts that OpenAI's server-side retention for Codex CLI requests is not
     published (`--ephemeral` only stops local session files);
   - Mike reads the Europe Terms of Use section on automated or programmatic use.
   If he is not satisfied with any of these, stop: nothing is enabled (the paid API route
   in EV/research.md remains the alternative).
2. Claude creates `~/.codex-cv-reviewer` (mode 700) with an empty AGENTS.md; Mike logs in
   once with `CODEX_HOME=~/.codex-cv-reviewer codex login`; Claude then checks that no
   config.toml was created.
3. `scripts/codex_reviewer_selfcheck.py` passes on the installed version.
4. One eval run `--use-cloud --reviewer-model gpt-6-luna` on the main folder: 19 Codex calls,
   synthetic fixtures only. Pass rule as Fix 4 step 3 (all 19 ran; no expected BLOCKED or
   NEEDS_EDIT case came back PASS; UNCHECKED 0; item recall at least 0.8; no more than half
   of the clean statements flagged). Record time per call. An early stop is INCONCLUSIVE.
5. On pass: the enable commit (O-6, fallback.py:303), the full suite again, docs (O-12).

## Limits and risks
- Training: Plus content may be used for training unless Mike turns it off (step 1).
- Terms: the scripted personal use of a ChatGPT-login Codex is UNVERIFIED against the
  Europe Terms (step 1). OpenAI's own docs prefer API keys for automation.
- Shared quota: CV reviews use the same Codex limit as development; when it is used up,
  reviews fall back to the free Gemini reviewers (the old same-vendor setup).
- Session expiry: a ChatGPT login may expire; reviews then fall back to Gemini
  (`not_found`) until Mike logs in again.
- Codex changes: every upgrade sends reviews to Gemini until the self-check passes (O-3,
  O-9). The self-check cannot prove that no tool exists; it tests the known exits (file read,
  web, write, MCP).
- Prompt injection: the reviewer reads text derived from web job ads. Defences: tools off
  and web search off (P4), read-only sandbox, allowlisted env, empty working dir, output
  schema, the existing nonce fences, code-side validation.
- Real-size latency is not measured; the eval measures it.

## Review points
### r5 re-check (verifier report in the session, 2026-11-02): 0 BLOCKER, 0 MAJOR, 6 MINOR, fixed in r6
- N1 stale builder names in O-9; N2 Tests vs O-3 launch-error kind; N3 three parent refs
  off by one; N4 `subprocess.run` cannot kill a process group (now `Popen` in `_run`);
  N5 PATH regression test; N6 self-check test gaps. Also: 403-before-409 order (O-8) and the
  home-creation step (live check step 2).

### r4 read-back (EV/spec-r4-readback-verifier.md): 1 BLOCKER, 1 MAJOR, 15 MINOR, fixed in r5
- BLOCKER child PATH could not start the node-based codex → O-1 PATH includes node's dir;
  codex launched as found, not via realpath.
- MAJOR probes ran in the harness reviewer home, not an O-2 home → stated in Facts, marked
  UNVERIFIED, proven only by the self-check in the O-2 home (live check step 3).
- MINOR fixed: parent spec line refs; prompt-source cite; MCP tool count; apply_patch
  evidence (P3); self-check prompt names both listing tools; shared builders and
  `check_codex_ready`; launch-error kinds; which() None; fence deliberate-trip test;
  fixtures copied to tests/fixtures; per-phase timeout and process-group kill; expected pin
  list; extra O-12 review list; Plus plan UNVERIFIED; "reduces" not "removes"; exact quote;
  second login stated; "small enable commit".

### r3 (EV/spec-codex-review-r3.md) and where r4 answers them (not re-reviewed)
- HIGH MCP listings could be absent → O-9 check 3 requires both listing calls, completed,
  error-free and empty; anything else fails.
- MED started events have null results → correlation by item id, completed results only.
- MED Gemini-specific tests break at enable → setup-only pins, found by a simulated-enable
  suite run; acceptance item added.
- MED version check had no timeout; latency understated → 10 s timeout; honest worst case.
- LOW turn-order regressions untested → three turn-order tests added.
- LOW byte-exact MCP strings → parsed JSON comparison; model tool list dropped.
- O-8 legacy script → regression test added.

### r2 (EV/spec-codex-review-r2.md) and where r3 answers them
- HIGH MCP resources not proven empty → `-c mcp_servers={}` on every call (O-1); O-9 check 3
  requires the listing results to be exactly empty; O-9 check 1 inspects loaded instructions.
- MED request-body assertions break in the build → listed and approved under Tests.
- MED old pages cannot show `consent_stale` → readable error sentence for scope-less
  requests (O-8).
- MED unfinished final turn accepted → O-4 step 3 turn-order rule.
- MED fence swallowed by `except` → teardown `pytest.fail()`; both launches through `_run`.
- MED upgrade recovery → shared builders; only the self-check may skip the version check.
- MED "Include environments" and retention → live check step 1.
- LOW model-reported tool list → printed only, does not decide PASS.

### r1 (EV/spec-codex-review-r1.md) and where r2 answered them
- HIGH tools not shown off → P3/P4 probes, 15 features + web_search off, O-9 self-check.
- HIGH once-per-process guard → O-3 version check before every call; O-9 per version.
- MED env blacklist → O-1 allowlist (P3/P4 ran with it).
- HIGH O-3 overlap → O-4 ordered outcome rules with event fixtures from real failures.
- MED unexpected exceptions stop the chain → O-1 never raises.
- MED eval key gate → O-5 key check per Gemini call.
- MED stale consent → O-8 consent scope and 409.
- MED enable-time assertions → consent tests pinned to Gemini-only; fallback.py:303 listed.
- HIGH real Codex calls from tests → conftest fence.
- MED schema vs validator → O-7 states it; reply tests added.
- MED privacy not a prerequisite → live check step 1.
- Q5.1 dedicated home → O-2 with checks; Q5.2 timeout stops → O-4.
