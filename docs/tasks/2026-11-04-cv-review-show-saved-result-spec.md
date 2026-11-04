<!-- STATUS: DRAFT r2 2026-11-04 (r1 checked by a verifier: 0 BLOCKER, 3 MAJOR, 6 MINOR,
fixed in r2), awaiting Mike's approval. Nothing is built before he
says "Yes, build it" (or similar). -->

# AI CV review: show the saved result again after a page reload — design spec

Parent spec: `docs/tasks/2026-10-26-ai-cv-blind-review-spec.md` (C3a record, C3b
approve/revise, C3c page UI). Branch: `feat/cv-blind-review-2026-10-26` (PR #3).
Code line numbers are as of commit 8ef56f6.

## Why
Mike asked for this on 2026-11-04. He answered "Should the page keep showing the last
review result after a reload?" with "Yes, design it".

Today the review result appears only once, in the browser, right after the POST to
`/job/<id>/ai-review-cv`. A reload loses it, although the record and the rewrite stay on
disk. On the first real-job trial (reed-57517499, 2026-11-04) Mike could not see the 9
flagged sentences again without spending another cloud run.

## Facts (from the code at 8ef56f6)
- The result panel is drawn only by `aiRender(d, notice)` in the inline script
  `_AI_CV_SCRIPT` (`src/ui_render.py:183-234`). Its only input is the POST success JSON.
- Every server value goes in through `textContent` (`aiEl`, `src/ui_render.py:48-54`).
  `tests/test_ai_cv_consent.py:359` asserts that the script has no `innerHTML`.
- The POST success JSON (`src/ui_handlers.py:1804-1816`) has these fields:
  `ok, reviewed_cv, changes, saved_path, model_used, review{verdict, l0_findings, items,
  reviewer_model}, generation_id, rewrite_sha256, revise_round, approval`.
- On disk there are two files. The path is built at `src/job_hunt_cv_review.py:98-102`, the
  md header at `src/ui_handlers.py:1783`, and both writes happen at
  `src/ui_handlers.py:1787-1797`:
  - `<output_dir>/<job_id>_ai_reviewed.review.json`, the record: verdict, items,
    l0_findings, generation_id, revise_round, writer_model, reviewer_model, approval,
    binding, created_at.
  - `<output_dir>/<job_id>_ai_reviewed.md`, the rewrite, with an HTML-comment header line.
- `changes` ("Changes made") is not saved anywhere.
- `read_review_record(output_dir, job_id)` (`src/job_hunt_cv_review.py:203-212`) returns
  None for a symlink, bad JSON or a record that fails validation.
- `_ai_cv_binding_current` (`src/ui_handlers.py:1696-1705`) is True only when the record's
  binding equals a fresh `compute_binding` of the current profile, master CV and rewrite.
- `render_job` (`src/ui_handlers.py:557-602`) does not read the record today. `ui_render.py`
  does no file I/O (`src/ui_render.py:1-7`), so the handler must read the record and pass a
  ready value in `JobPageViewModel` (`src/ui_render.py:1263`).
- Approve needs `{generation_id, rewrite_sha256}` and no consent
  (`src/ui_handlers.py:1708-1746`).
- Revise needs a fresh tick of the consent box and the current `consent_scope`
  (`src/ui_handlers.py:1648-1656`). The checkbox is already on the page
  (`src/ui_render.py:2262`).

## Behaviour
- S1. When the job page is rendered, the handler reads the record with
  `read_review_record`. If the record is valid and the rewrite file can be read, the
  handler checks `_ai_cv_binding_current`.
- S2. **Current record.** The handler builds a dict `d` in the POST success shape:
  - `reviewed_cv` = `canonical_cv_body` of the md file;
  - `changes` = `[]`;
  - `saved_path` = the md file name;
  - `model_used` = `record["writer_model"]`;
  - `review` = `{verdict, l0_findings, items, reviewer_model}` from the record;
  - `generation_id`, `revise_round` and `approval` from the record;
  - `rewrite_sha256` = `record["binding"]["rewrite_sha256"]`;
  - one extra field, `created_at`, from the record.
  The renderer embeds `d` in a `<script type="application/json" id="ai-cv-saved">` element.
  Encoding: `json.dumps(d)`, then every `<`, `>` and `&` in the JSON text is replaced by
  the JSON unicode escape for that character. The escape is a backslash, the letter u,
  and then the four hex digits 003c, 003e or 0026. No data can then close the script
  element. On page load the inline script parses that element and calls `aiRender(d, notice)`.
  The notice is "Last AI review: <created_at>":
  - `created_at` is the record's UTC ISO string, which the browser converts to local
    time, shown to the minute;
  - it is shown in the normal text colour, not the error colour that `ai-cv-notice` uses
    today (`src/ui_render.py:203`).
- S2a. Both pages that render the job page get the value: `render_job`
  (`src/ui_handlers.py:557-602`) and `render_result` (`src/ui_handlers.py:1350-1355`, the
  page after an evaluation or Re-evaluate). Build it in one helper and call it from both,
  or from the shared view-model builder.
- S2b. Order of checks in the helper. The whole helper runs inside a broad try/except,
  and any exception gives S4.
  1. Read the record with `read_review_record`; None gives S4.
  2. Read the md file. It is missing, a symlink, or unreadable: S4.
  3. Load the profile and the master CV. Either fails to load, or the master CV is
     missing or unreadable: S4. The review cannot be judged, and the AI Review CV button
     would fail on the same inputs.
  4. Compare the binding, as `_ai_cv_binding_current` does. Not equal: S3. Equal: S2.
- S3. **Stale record** (binding not current, for example the CV or profile changed after
  the review): no panel. The result area shows one line instead: "An earlier AI review of
  this job no longer matches your CV or profile. Click AI Review CV to review again."
- S4. **No record, an invalid record, a missing or unreadable md file, or any error while
  reading:** the page renders exactly as today, with no panel, no notice and no exception
  (log at debug level only).
- S5. Page load is read-only. It makes no cloud call, does not need consent and writes no
  file.
- S6. The buttons on a reloaded panel follow the existing rules unchanged:
  - Approve shows when the verdict is not PASS and the record is not approved. It works
    without consent.
  - Revise shows when the verdict is BLOCKED or NEEDS_EDIT and `revise_round` is 0. It
    still needs the consent box ticked, as today.
  - After Approve or Revise the panel updates as it does now.
- S7. "Changes made" is not shown after a reload, because it is not saved. The rest of the
  panel is the same as right after a run.

## Not in scope
- Saving `changes` in the record. That would need a record schema change and a validator
  change (`_valid_review_record`, `src/job_hunt_cv_review.py:129-200`).
- Showing a stale review read-only (alternative to S3; see the open question).
- Showing reviews on History or Board pages; a "re-review only" action.

## Builder and chunks
Small change: about 3 source files (`src/ui_handlers.py`, `src/ui_render.py`, maybe
`src/job_hunt_cv_review.py` for a read helper) plus tests. Builder: the `implementer`
agent (sonnet), one chunk. A fresh verifier runs after the build, then the full suite.

Test work, part of the same chunk. AC1, AC1a and AC5 need the node page-script harness
in `tests/test_ai_cv_consent.py` extended:
- The fake DOM resolves only the ids it defines (`getElementById: id => ids[id] || null`,
  about :202-300). It needs an `ai-cv-saved` element whose `textContent` holds the
  embedded JSON.
- `_run_page_js` (:343-357) renders `_job_html()` from the `_vm()` factory in
  `tests/test_cover_letter_form.py`. That factory needs a way to pass the new view-model
  field.
- The harness picks scripts with `re.findall(r"<script>(.*?)</script>")`, so the JSON
  element is not run as a script. It still needs a hook to inject the JSON text.

## Acceptance criteria
- AC1 Current NEEDS_EDIT record. The rendered job page contains `#ai-cv-saved`. Under the
  node page-script harness (`_run_page_js`, `tests/test_ai_cv_consent.py:343`) the panel
  shows:
  - the NEEDS_EDIT badge;
  - every non-SUPPORTED item with its reason;
  - flagged lines marked in the rewrite;
  - the Approve and Revise buttons;
  - the "Last AI review:" notice.
- AC2 Approved record: the Approved badge shows and there is no Approve button.
  `revise_round` 1: there is no Revise button.
- AC3 Stale record (the master CV changed after the record was written): there is no
  `#ai-cv-saved` and no panel, and the S3 line is shown.
- AC1a S7: the reloaded panel has no "Changes made" list. The notice element is not
  styled with the error colour.
- AC2a The page rendered by `render_result` with a current record also contains
  `#ai-cv-saved` (S2a).
- AC4 Each of these renders the page with no panel and no S3 line, and raises no
  exception:
  - no record; invalid JSON; a record that fails validation; a symlinked record;
  - a missing md file; a symlinked md file;
  - a profile that fails to load; a missing or unreadable master CV;
  - a helper that raises an unexpected exception (monkeypatched).
- AC5 Injection. A record whose item text, reason, L0 detail and rewrite contain
  `</script><script>alert(1)</script>` and `<img src=x onerror=alert(1)>` produces page
  HTML in which the data never appears as a raw `</script` or `<img`. The panel shows the
  text literally, as text. The existing no-`innerHTML` test still passes.
- AC6 Rendering a page with a current record calls no writer, reviewer, Codex or network
  function (each is monkeypatched to fail the test if called). The record and md file
  bytes and mtimes are unchanged afterwards.
- AC7 Approve from the reloaded panel: posting the embedded `generation_id` and
  `rewrite_sha256` to `/approve` returns 200. After that, `load_latest_tailored_cv` returns
  the AI rewrite.
- AC8 `tests/test_ai_cv_consent.py`, `tests/test_cv_review_routes.py` and
  `tests/test_cv_review_record.py` pass. The full suite shows the same 46 baseline
  failures and 0 new.
- AC9 Live view, which needs no consent because no cloud call is made: reloading
  `/job/reed-57517499` on Mike's running server shows the NEEDS_EDIT panel with 9 flagged
  items and the "Last AI review:" notice. The server must be restarted to load the new
  code; Mike says when.

## Open question for Mike
- Q1 Stale record:
  - (A, recommended) hide it and show the one-line S3 message;
  - (B) show the old result read-only, with a warning and no buttons.
