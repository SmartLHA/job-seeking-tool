<!-- STATUS: built and independently verified 2026-10-13 (commits a144d36, 10cf099, 85c6e21, 33e9f4e, 125f1a0); approved 2026-10-12 (Mike: "approve") -->
# Explain check — local "could not confirm" labels on Gemini's job explanation (spec, 2026-10-12)

## Goal
On the job page, after "Run Analysis" shows Gemini's Fit / Risk / Action text as today,
check each Fit and Risk statement with the local Nimble model (Ollama on this Mac) and
show an advisory label on any statement whose factual assertions it could not confirm
from the exact information Gemini was given. Nothing is hidden; no score, grade or
decision changes; every check is also logged locally. Manual "Run Analysis" path only.
Design review: Codex 3 rounds + Gemini pre-check and final comment (design notes in the
session; this spec is the build contract).

## Background facts (path:line as of 2026-10-12)
- Prompt: `_EXPLAIN_PROMPT` src/job_hunt_llm.py:244-280; `explain_job_match_with_llm(profile, job, analysis, *, raise_on_rate_limit=False)` :367-373; fields built :393-423 (`description_raw[:1500]` at :401); call `_call_gemini_reasoning(prompt)` :425; parse :438-444 -> {"fit","risk","action","model_used"}.
- Manual route: `POST /job/{id}/explain` src/ui_routes.py:370-373 -> `handle_job_explain` src/ui_handlers.py:675-700 (loads job/analysis/profile :682-696, returns `{"ok": True, **explanation}` :700, saves nothing).
- Page: AI block src/ui_render.py:1729-1816; JS fills `#ai-fit/#ai-risk/#ai-action` with textContent :1791-1793; badge :1795-1797; Re-run re-enabled :1806.
- Host/origin checks for POST routes: tests/test_ui_security.py:207-290 (`assert_called_once_with(profile, job, analysis)` at :290 must keep passing).
- JS execution tests exist: tests/test_ui_small_issues_d.py:102 (follow that pattern).
- Nimble API (verified 2026-10-10..12): `POST http://127.0.0.1:11434/v1/systemone`, body `{"model":"nimble:9b-q4_K_M","state":<text>,"questions":{<name>:{"type":"noul","instructions":...,"criteria":{"true":...,"false":...}}},"keep_alive":"30m"}`; reply `{"answers":{<name>:{"type":"noul","noul":<0..1>}},"usage":{"input_tokens":...}}`; unknown model -> HTTP 404 JSON error. Warm ~5 s per statement, cold first call ~17 s. 8,192-token limit per question prompt.

## Hard constraints
- Do NOT edit files another session is changing: src/job_hunt_index.py, src/job_hunt_scheduler.py, src/job_hunt_storage.py, src/job_hunt_parsing.py, INDEX.md, PROJECT_LOG.md, PROJECT_TODO.md, docs/function_list.md, tests/test_digest_scheduler.py, tests/test_parsing.py, tests/test_market_position_route.py. If the build needs any of them, STOP and report.
- The Gemini prompt text must stay byte-identical; `explain_job_match_with_llm` signature unchanged.
- No new Python packages. Loopback-only Ollama client (fixed URL, no proxies, no redirects, request <= 64 KiB, reply size cap).
- pytest never reaches Ollama: an autouse fence in a new tests/conftest.py patches the new module's transport; a test proves an unfenced call is blocked before connecting.
- Never open any .env file. Nothing new at project root. No change to saved analyses, scores, grades, decisions, or the D6 worker.

## Behaviour
1. Exact binding. Add a pure `build_explain_fields(profile, job, analysis) -> dict` in src/job_hunt_llm.py that returns the exact `.format` fields; the prompt is `_EXPLAIN_PROMPT.format(**fields)`. Add `explain_source_text(fields) -> str` = the prompt's data part (everything the template fills, as the labelled text block Gemini sees, without the fixed instruction lines). `handle_job_explain` builds `fields` from the SAME in-memory profile/job/analysis it passes to `explain_job_match_with_llm` (call the builder in the handler; do not change the explain function's signature).
2. Statements. After Gemini returns, split fit / risk / action into a server-generated list `[{"id":"fit-0","section":"fit","text":...}, ...]` (sentence split robust to decimals like 2.5, abbreviations like e.g./i.e./U.K., and newlines). Keep all text; only the first 10 Fit/Risk statements of at most 600 chars are eligible; others are shown and marked `not_checked: limit`. Action statements are `not_checked: advice`.
3. Token store (in memory, thread-safe): `{token: {job_id, source, statements, created}}`, max 20 entries (evict oldest), 10-minute expiry; a new explain for the same job invalidates that job's older tokens. If the source exceeds 8 KB (UTF-8 bytes), statements are `not_checked: source_too_large`.
4. Explain response adds `check_token` and `statements` (ids + section + text). Never send the source to the browser.
5. Check route `POST /job/{id}/explain-check`, JSON body `{"check_token": ...}` only, same host/origin checks as other POST routes. Token must exist, be current, and belong to that job id; else respond `{"ok": true, "state": "stale"}` and do no work.
6. Nimble question (frozen, `QUESTION_VERSION = "explain-check-v1"`), one noul per eligible statement, threshold 0.5:
   - state = "SOURCE:\n<source>\n\nSECTION (context only, not evidence):\n<the whole section text>\n\nSTATEMENT TO CHECK:\n<statement>"
   - instructions: "Ignore opinions, judgements and recommendations. Is EVERY factual assertion in the STATEMENT TO CHECK (numbers, money, dates, skills, tools, places, work mode, requirements, scores, and what the candidate has or lacks) supported by the SOURCE?"
   - criteria true: "Every factual assertion in the statement appears in or follows directly from the SOURCE, or the statement contains only opinions, judgements or recommendations."
   - criteria false: "At least one factual assertion in the statement is not in the SOURCE or contradicts it."
   - p >= 0.5 -> `ok`; p < 0.5 -> `could_not_confirm`. A non-finite or out-of-range p, or a missing field, is a shape error -> `not_checked: model_error`.
7. Diagnostic fact check (logged only, never a label): numbers and money normalised (£50k = £50,000 = 50000; commas ignored) and ALL-CAPS tokens (2+ letters) that do not appear in the source; record them per statement.
8. Worker and bounds: one background worker thread owns all Ollama calls and the single "active check" lock, held until the current call actually returns (never abandoned while running). The route waits for results up to an overall 90 s deadline, then returns what is finished; unfinished statements are `not_checked: time`; results arriving after the route returned are discarded (logged). The worker re-checks the token between statements and stops if it became stale. If the worker is busy with another check, the route returns `{"ok": true, "state": "busy"}`. Ollama unreachable -> remaining statements `not_checked: model_unavailable`.
9. Response: `{"ok": true, "state": "done"|"partial"|"busy"|"stale", "results": {<statement id>: {"verdict": "ok"|"could_not_confirm"|"not_checked", "reason": ...}}}`.
10. Page JS: render the statement list with textContent (no innerHTML for model text), one element per statement id; show "Checking against the information Gemini was given (local model)..." while pending; label for `could_not_confirm`: "⚠ Local check could not confirm this from the information given to Gemini - may be wrong"; `not_checked` shows "not checked (<reason>)" in muted text; footer "Local check, advisory only. No label does not mean verified."; `busy` shows a "Check again" button that re-posts the same token; clicking Run Analysis again clears all labels; any response whose token is not the current one is ignored; a failed check never hides the explanation.
11. Log: append one JSON line per check to `config.state_root / "logs" / "explain-check.jsonl"` (create dir if needed; file mode 0600), under the lock: run_id, job_id, time, model name, model digest if cheaply available (else null), QUESTION_VERSION, threshold, source (<= 8 KB), per statement: id, section, text, p, verdict, reason, fact-check findings, seconds; plus discarded late results. Write failures go to the app logger and never break the response.

## Build chunks (commit after each passing chunk; orchestrator commits)
- C1: `build_explain_fields` + `explain_source_text` refactor; prompt byte-identical fixture test (compare old vs new prompt for 2-3 representative profiles/jobs/analyses including None salary/years).
- C2: src/job_hunt_explain_check.py (splitter, token store, Nimble client, worker, fact-check diagnostic, logger) + tests/test_explain_check.py + tests/conftest.py fence.
- C3: handler/route changes + route tests (host/origin, 404, stale token incl. wrong job, busy then retry, limits, source too large, Ollama down, partial at deadline using a fake slow transport and a short deadline).
- C4: page JS + labels + JS tests (label mapping by id, rerun clears labels, stale response ignored, network failure keeps explanation, busy shows Check again, HTML-like text stays literal).

## Acceptance criteria
1. Prompt byte-identical test passes; tests/test_ui_security.py passes unchanged.
2. tests/test_explain_check.py covers: splitting (decimals, abbreviations, newlines, >10 and >600 limits); token store (expiry, supersede, wrong job, unknown, max 20); Nimble parse (ok, below threshold, non-finite, out-of-range, missing field, 404); worker (busy, stale between statements, deadline with blocked transport -> partial, late result discarded, lock held until call returns then retry succeeds); fact-check diagnostic (£50k vs £50,000, ALL-CAPS); log (fields present, 0600, write failure tolerated).
3. Route and JS tests listed in C3/C4 pass.
4. The fence test passes (unfenced call blocked).
5. `venv/bin/python -m pytest tests -q -p no:cacheprovider`: no new failures versus the pre-build baseline (record the baseline first; known sandbox socket failures excluded only if identical before and after).
6. No file in the hard-constraint list changed by this build.

## Live trial (after C4, log-only, by the orchestrator)
Run the final pipeline (not the page) on the 15 saved explanations plus new written cases (opinion-only, recommendation, pronoun and cross-sentence, has/lacks, attribution), labelled before the run; report to Mike. Stop condition: if Nimble flags most correct statements, report before relying on the labels.
