# F1 v2 — ATS keyword-match "re-check" action (design, rev 3 — real Codex review folded in)

<!-- STATUS -->
> **Implementation status:** ✅ Implemented 2026-06-22 — 408 passed / 1 skipped (+25 tests).
> **Divergences from spec:** `_parse_profile_id` regex corrected to not exclude `-`
> (rev 3 draft truncated ids like `cand-001`). Otherwise as designed.
> **Key functions:** `load_latest_tailored_cv()`, `EmptyTailoredCVError`,
> `handle_ats_recheck()`, `render_keyword_match_panel()`, `_keyword_match_vm_fields()`;
> `JobAnalysis.keyword_match_baseline_rate` / `keyword_match_source`.
> **Routes:** `POST /job/{id}/ats-recheck`.
> **Tests:** `tests/test_f1_recheck.py`.
<!-- /STATUS -->

_Date: 2026-06-22 · Project: job_hunt · Status: IMPLEMENTED (rev 3 design, Codex-reviewed)_

> **Rev 3 change log:** ran the `design-council` skill with a **real, live Codex
> independent review** (read-only MCP, verified against actual source). Codex
> raised 3 high-severity issues that change the design: (H1) AJAX vs reload panel
> can show **different matched lists** — must render through the same view-model
> path; (H2) `job_analysis_from_dict` **enumerates fields**, so the two new fields
> must be read explicitly or they silently reset on load; (H3) an **empty tailored
> file** computes `None` and overwrites a good score — needs its own 422. Medium
> items (real storage fn names + 404/422 contract, read-modify-write races,
> fail-closed `profile_id`) and low items are folded into the sections below. Full
> critique verbatim in §Codex independent review.

## Goal
Close the F1 feedback loop: today the keyword-match panel is computed once at
evaluation against the **master CV** and never moves. v2 adds a **re-check**
action that recomputes the match against the **latest saved tailored CV** and
shows the improvement as `was X% → now Y% (tailored CV)`.

## Confirmed product decisions (rev 2 — conflict resolved)
1. **CV source — tailored only, no master fallback.** Prefer
   `{job_id}_ai_reviewed.md`, else `{job_id}.md`. If neither exists → **422**
   `"No tailored CV saved yet — tailor your CV first."` We do **not** silently
   re-score the master CV: the button says "re-check against tailored CV" and a
   no-change result would confuse the user.
2. **Display:** keep the master-CV baseline; panel shows `was X% → now Y% (tailored CV)`.
3. **Trigger:** button on the panel; AJAX `POST /job/{id}/ats-recheck`; replace the
   panel in place via **`outerHTML`** (server returns the full wrapper — see §AJAX).

### `keyword_match_rate` semantics (confirmed, MVP-simple)
- After re-check, `keyword_match_rate` is **overwritten** with the tailored score.
  The top verdict card (`ui_render.py:755`) reads the same field, so it **will**
  show the latest tailored score after reload. This is intended for MVP.
- `keyword_match_baseline_rate` holds the **master-CV** score (the "before").
- A full re-evaluation **resets** `keyword_match_source="master"` and recaptures
  `keyword_match_baseline_rate` from the new master score.
- (Rejected for MVP: a separate `keyword_match_tailored_rate` field that leaves the
  verdict card on the master score. Revisit only if we decide the card must not move.)

## Current state (verified on disk)
- `compute_keyword_match(cv_text, required_skills, preferred_skills) -> KeywordMatchResult`
  in `src/job_hunt_keyword_match.py`. Fields: `match_rate` (int|None),
  `required_matched/missing`, `preferred_matched/missing`, `overused`.
  Null contract: `match_rate=None` when no keywords OR no CV text. Required wins
  over preferred (dedupe across lists).
- Called once in `src/job_hunt_evaluation.py:80` using `profile.master_cv_text`.
- Persisted on `JobAnalysis` (`src/job_hunt_models.py:211–214`): `keyword_match_rate`
  + **missing** lists + `overused`. Matched lists re-derived for display in
  `_keyword_match_vm_fields` (`src/ui_handlers.py:1396`).
- Panel rendered inline in `render_job_page` (`src/ui_render.py:687–725`).
- Tailored CVs: `save_tailored_cv` → `output/tailored_cvs/{job_id}.md`
  (header `<!-- profile_id: X -->`); AI-review → `{job_id}_ai_reviewed.md`
  (header `<!-- ai_reviewed: true | model: M | profile_id: X -->`).
  `DEFAULT_TAILORING_POLICY.output_dir = Path("output/tailored_cvs")` (cwd-relative).
- No tailored-CV loader and no `/ats-recheck` route exist yet.

## Changes by file (blast radius: 8 files)

### 1. `src/job_hunt_models.py` — JobAnalysis (+2 fields)
```python
keyword_match_baseline_rate: int | None = None  # master-CV rate at eval time (the "before")
keyword_match_source: str = "master"            # "master" | "tailored"
```
`__post_init__`: validate `keyword_match_baseline_rate` 0–100 when not None.
Defaults matter: old analyses on disk lack these keys.

### 2. `src/job_hunt_storage.py` — serialization
- `job_analysis_to_dict` uses `asdict()` (verified, line 135) → auto-includes new
  fields. No change on the write side.
- **(H2 — load-side gap is mandatory, not optional.)** `job_analysis_from_dict`
  (verified line 154) **explicitly enumerates every field** — it does NOT splat. So
  the two new fields are **silently dropped on every load** unless added by hand,
  which would reset baseline→None / source→"master" on every reload and defeat the
  whole feature. Add inside the `JobAnalysis(...)` call (after line 175):
  `keyword_match_baseline_rate=_optional_int(payload.get("keyword_match_baseline_rate"), "keyword_match_baseline_rate")`
  and `keyword_match_source=payload.get("keyword_match_source") or "master"`.
  Old-record contract: missing keys → baseline None, source "master". Covered by
  `test_old_analysis_without_new_keys_loads_with_defaults`.

### 3. `src/job_hunt_evaluation.py` — capture baseline at eval
At the `JobAnalysis(...)` build (~line 99): add
`keyword_match_baseline_rate=keyword_match.match_rate, keyword_match_source="master"`.
(Full re-evaluation therefore resets both, per decision.)

### 4. `src/job_hunt_tailoring.py` — new hardened loader
```python
import re as _re
_SAFE_JOB_ID = _re.compile(r"^[A-Za-z0-9._-]+$")

def load_latest_tailored_cv(job_id: str, *, expected_profile_id: str | None = None,
                            policy: TailoringPolicy = DEFAULT_TAILORING_POLICY) -> str | None:
    """Most-tailored saved CV text for a job (AI-reviewed preferred, then tailor
    output), with the single leading HTML-comment metadata line stripped.
    Returns None when no tailored file exists.

    Path safety: job_id must match a strict allow-list (no '/', no '..'); the
    resolved file must stay inside policy.output_dir. Raises ValueError on a
    malformed job_id so the caller can 400/404 rather than touch the filesystem.
    TODO(multi-profile): when expected_profile_id is given, parse 'profile_id:'
    from the header and return None on mismatch.
    """
    if not isinstance(job_id, str) or not _SAFE_JOB_ID.match(job_id) or job_id in (".", ".."):
        raise ValueError("invalid job_id")  # rev3: reject "."/".." explicitly (the regex alone allows them)
    base = policy.output_dir.resolve()
    for name in (f"{job_id}_ai_reviewed.md", f"{job_id}.md"):
        path = (base / name).resolve()
        # defence in depth: resolved path must remain within base
        if base not in path.parents:
            continue
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        first = lines[0].strip() if lines else ""
        if first.startswith("<!--") and first.endswith("-->"):
            body = "".join(lines[1:])           # remove ONLY the first metadata line
        else:
            body = "".join(lines)               # no header → return full text
        if expected_profile_id is not None:
            hdr_pid = _parse_profile_id(first)            # None if absent/garbled
            if hdr_pid != expected_profile_id:            # rev3: FAIL-CLOSED — absent/garbled also fails
                return None
        body = body.strip()
        if not body:                                     # rev3 (H3): file exists but is empty/comment-only
            raise EmptyTailoredCVError("tailored CV is empty")
        return body
    return None
```
`_parse_profile_id(header_line)` greps `profile_id:\s*([^\s|>-]+)` from the comment.

**Rev 3 loader changes (from Codex review):**
- **(H3) Empty/comment-only file:** if a tailored file exists but its body is empty
  after header-stripping, raise `EmptyTailoredCVError` (caller → 422
  `"Tailored CV is empty — re-tailor your CV."`). Without this, `compute_keyword_match`
  returns `None` and the handler would overwrite a valid score with `None`, flipping
  both the panel and the verdict card to N/A. `None` (no file) and "empty file" are
  now distinct outcomes.
- **profile_id fail-closed:** when `expected_profile_id` is given, an absent or
  unparsable header now also returns `None` (was: absent header passed). Avoids
  scoring against a stale/other-profile CV. MVP passes `None` (single profile), so
  this path is dormant but correct when multi-profile lands.
- **`.`/`..` rejected** in the id guard (see above) for clarity + future-proofing;
  resolved-path containment remains the real security boundary.

### 5. `src/ui_render.py` — extract panel (full wrapper) + button + delta
- New `render_keyword_match_panel(*, job_id, baseline, source, keyword_match_rate,
  keywords_required_matched, keywords_required_missing, keywords_preferred_matched,
  keywords_preferred_missing, keywords_overused) -> str` that returns the card
  **including** the wrapper `<div id="kw-panel-body"> … </div>`. The keyword fields
  are exactly the dict `_keyword_match_vm_fields` already returns, so the handler can
  `**vm`-splat it (rev3 H1) — one rendering path for both AJAX and reload.
- `render_job_page` calls it with the same vm fields (no first-render behaviour
  change; today the panel is built by `_card(...)` with **no id** — the new wrapper
  adds `id="kw-panel-body"`).
- Inside the panel:
  - **Delta line** when `source == "tailored"` and `baseline is not None` and
    `keyword_match_rate is not None`: `was {baseline}% → now {rate}% (tailored CV)`
    (green when `rate > baseline`).
  - **No-baseline state (rev3 low #8):** if `source == "tailored"` but `baseline is
    None` (master CV was absent at eval, so there is no honest "before"), show
    `now {rate}% (tailored CV)` with **no delta** — do not fabricate a baseline from
    the first tailored score. Delta also suppressed when `rate is None`.
  - Button `Re-check against tailored CV`.

### 6. `src/ui_render.py` — JobPageViewModel (+2 fields)
`keyword_match_baseline_rate: int | None`, `keyword_match_source: str`.
`_keyword_match_vm_fields` returns them; the no-analysis branch in
`_build_job_page_vm` sets baseline None / source "master".

### 7. `src/ui_handlers.py` — `handle_ats_recheck(req, config, responder, job_id)`
Real storage fn names verified: **`load_job_analysis(job_id, config.state_root)`**
and **`save_job_analysis(analysis, config.state_root)`** (rev 2 wrote `load_analysis`
/`save_analysis`, which do **not** exist — corrected). Status codes follow the
sibling `handle_ai_review_cv` convention (**missing analysis / missing job → 404**;
422 is reserved for "analysis exists but recheck can't proceed").

```
# --- per-job mutation lock (rev3, see M-races) ---
with _job_analysis_lock(job_id):
    try: tailored = load_latest_tailored_cv(job_id, expected_profile_id=<profile id or None>)
    except ValueError:                 -> 404   (malformed id)
    except EmptyTailoredCVError:        -> 422  "Tailored CV is empty — re-tailor your CV."   # rev3 H3
    try: reviewed_job = load_reviewed_job(job_id, config.state_root)
    except FileNotFoundError:           -> 404
    try: analysis = load_job_analysis(job_id, config.state_root)
    except FileNotFoundError:           -> 404  "Evaluate this job first"   # rev3: 404 (was 422), matches siblings
    if tailored is None:                -> 422  "No tailored CV saved yet — tailor your CV first"
    km = compute_keyword_match(tailored, reviewed_job.required_skills, reviewed_job.preferred_skills)
    baseline = analysis.keyword_match_baseline_rate
               if analysis.keyword_match_baseline_rate is not None
               else analysis.keyword_match_rate            # seed baseline on first recheck
    updated = dataclasses.replace(analysis,
        keyword_match_rate=km.match_rate,
        keywords_required_missing=km.required_missing,
        keywords_preferred_missing=km.preferred_missing,
        keywords_overused=km.overused,
        keyword_match_baseline_rate=baseline,
        keyword_match_source="tailored")
    save_job_analysis(updated, config.state_root)          # atomic write (tmp + os.replace)
# render via the SAME derived view-model path used on reload (rev3 H1):
vm = _keyword_match_vm_fields(reviewed_job, updated)
panel_html = render_keyword_match_panel(job_id=job_id, baseline=baseline, source="tailored", **vm)
send_json({"ok": True, "rate": km.match_rate, "baseline": baseline, "panel_html": panel_html})
```

**(H1 — single source of truth for matched lists.)** Codex's top issue: rev 2 fed
`km.required_matched`/`km.preferred_matched` straight into the panel, but a normal
page **reload** rebuilds matched lists in `_keyword_match_vm_fields` (verified
line 1396) as `(job skills − stored missing)` with `_kw_canon` canonicalization and
required-wins dedupe. Those two derivations can diverge (casing, aliases, a skill
listed as both required & preferred), so the user could see one set of chips right
after clicking and a *different* set after refresh. Fix: the handler renders the
AJAX panel by calling `_keyword_match_vm_fields(reviewed_job, updated)` on the
**saved** analysis — identical code path to reload. `render_keyword_match_panel`
therefore takes the vm dict, not raw `km` matched lists.

**(M — read-modify-write races.)** load→replace→save is not atomic. A double-click,
two tabs, or a recheck racing a full re-evaluation can clobber fields — worst case a
recheck writing `source="tailored"` *after* a fresh eval reset it to `"master"`. MVP
mitigation: a process-local per-job lock (`_job_analysis_lock(job_id)`, e.g. a
`defaultdict(threading.Lock)`) around the load→save, plus atomic file replace
(write tmp + `os.replace`) in `save_job_analysis` if not already atomic. Cross-process
locking is out of scope for the single-user local tool.

### 8. `src/ui_routes.py` — route
Add alongside the other `^/job/([^/]+)/…$` POST handlers:
`re.match(r"^/job/([^/]+)/ats-recheck$", parsed.path)` → `handle_ats_recheck(...)`.

### Also: bump `_PAGE_UPDATED["job"]` in `src/ui_state.py`.

## AJAX contract (no duplicate-div risk)
- **Server returns the full wrapper** `<div id="kw-panel-body">…</div>` in `panel_html`.
- **Frontend replaces with `outerHTML`:**
  `document.getElementById('kw-panel-body').outerHTML = data.panel_html;`
  Never `innerHTML` with a wrapped payload (would nest a second `kw-panel-body`).
- On non-OK: render `data.error` inline near the button; leave the panel untouched.
- **Convention note (rev3 low #9):** every existing AJAX handler in `ui_render.py`
  swaps via `resultDiv.innerHTML = html` into a dedicated result `<div>`. This
  `outerHTML`-on-wrapper approach is a deliberate, isolated divergence (it keeps the
  panel self-replacing without a separate result div). Accepted; the
  single-`kw-panel-body` invariant is locked by
  `test_recheck_response_panel_has_single_kw_panel_body`. If we'd rather not diverge,
  the alternative is: server returns inner body only, frontend does
  `innerHTML` into a stable empty `<div id="kw-panel-body">` — revisit only if the
  divergence bites.

## Edge / null contracts
- No tailored CV file → 422, panel unchanged, inline message (no master fallback).
- **Tailored file exists but empty/comment-only → 422 "Tailored CV is empty"**
  (rev3 H3); analysis is **not** mutated, so a good master score is never clobbered.
- Malformed `job_id` (path traversal, `/`, `..`, `.`) → loader raises ValueError → 404.
- `match_rate is None` because the **job lists no keywords** → panel shows N/A; delta
  suppressed. (Distinct from the empty-CV case above, which is a 422.)
- Old analysis JSON without new keys → baseline None, source "master"; first
  re-check seeds baseline from the stored master rate.
- Master CV absent at eval (rate None, baseline None) → after recheck, show
  `now Y%` with no delta; never fabricate a baseline (rev3 low #8).
- Tailored file with no/garbled header → strip only a first line that is a full
  `<!-- … -->` comment; otherwise return full text untouched.
- `expected_profile_id` given + header absent/garbled/mismatched → loader returns
  None (fail-closed) → 422 (rev3). Dormant in single-profile MVP (passes None).

## Tests (`tests/test_ui.py`, `tests/test_storage.py`, `tests/test_tailoring.py`)
Render/flow:
- `test_recheck_improves_rate_against_tailored_cv` — eval (low master rate) → write
  tailored CV containing the missing keywords → POST recheck → `rate > baseline`,
  `ok`, persisted analysis updated, source "tailored".
- `test_recheck_prefers_ai_reviewed_over_tailor_output` — both files present, the
  ai_reviewed content drives the score.
- `test_recheck_without_tailored_cv_returns_422_and_panel_unchanged`.
- `test_recheck_unknown_job_404`.
- `test_recheck_no_keywords_returns_na_and_suppresses_delta`.
- `test_recheck_response_panel_has_single_kw_panel_body` — `panel_html.count('id="kw-panel-body"') == 1`.
- `test_verdict_card_shows_tailored_rate_after_recheck_reload` — GET /job after
  recheck; verdict-card "Keyword match" metric reflects the tailored rate.
- **`test_recheck_panel_matches_reload_panel` (rev3 H1)** — chips in the AJAX
  `panel_html` are byte-identical to the panel after a fresh GET /job, incl. a case
  where a skill differs only by casing/alias and a skill that is both required &
  preferred (exercises `_kw_canon` + required-wins).
- **`test_recheck_empty_tailored_cv_returns_422_and_does_not_mutate` (rev3 H3)** —
  empty/comment-only tailored file → 422, stored analysis rate unchanged.
- **`test_recheck_unevaluated_job_returns_404`** — missing analysis → 404 (sibling
  contract), not 422.
- **`test_recheck_no_master_baseline_shows_now_only`** — eval with no master CV
  (baseline None) → recheck renders `now Y%` with no delta.
Loader/serialization:
- `test_loader_blocks_path_traversal_in_job_id` — `../etc/passwd` style raises ValueError.
- `test_loader_strips_only_first_metadata_comment_line`.
- `test_loader_returns_none_when_no_tailored_file`.
- `test_loader_rejects_profile_id_mismatch_when_expected_given`.
- `test_analysis_roundtrip_preserves_baseline_and_source`.
- `test_old_analysis_without_new_keys_loads_with_defaults`.
- **`test_loader_rejects_dot_and_dotdot_job_id`** — `"."` / `".."` raise ValueError.
- **`test_loader_profile_id_fail_closed`** — absent/garbled header fails when
  `expected_profile_id` is given.
- **`test_concurrent_recheck_serialized`** (if lock added) — two overlapping rechecks
  don't interleave a partial write; a recheck cannot resurrect `source="tailored"`
  after a re-eval reset it (lock + last-writer well-defined).

## Risks (residual, post-Codex-review)
- Verdict card and panel share `keyword_match_rate`; overwrite changes both — accepted
  for MVP, covered by `test_verdict_card_shows_tailored_rate_after_recheck_reload`.
- `output_dir` is cwd-relative; tests run from repo root (existing tests assume this).
- Multi-profile: header `profile_id` validation is wired as optional
  (`expected_profile_id`), now **fail-closed** when supplied; single-profile MVP passes None.
- Concurrency mitigated by a **process-local** per-job lock only — correct for the
  single-user local tool; not safe across multiple processes (out of scope).
- AJAX swap diverges from the `innerHTML` house convention (deliberate; see §AJAX).

## Blast radius (rev 3)
Still ~8 source files. Net-new helpers introduced by the review: `EmptyTailoredCVError`
(in `job_hunt_tailoring.py`) and `_job_analysis_lock` (in `ui_handlers.py`, or a small
shared module). `save_job_analysis` may need an atomic-write tweak if it isn't already.

---

## Codex independent review (rev 3, verbatim)
_Source: live `codex` local MCP, read-only sandbox, run 2026-06-22 via the
`design-council` skill. Verified against the actual source. Advisory — folded into
the sections above; the human is the approval authority._

> **1. High — AJAX and reload can disagree** (D5 vs `_keyword_match_vm_fields`)
> D5 renders `km.required_matched`/`km.preferred_matched` directly, while reload
> derives matches from stored missing lists using `_kw_canon` and "required wins"
> dedup. Differences in casing, aliases/canonicalization, duplicate skills, or a
> preferred skill also listed as required can produce different lists. Fix: use one
> rendering/view-model path for both — after saving the missing lists, render via
> `_keyword_match_vm_fields(reviewed_job, updated_analysis)`. Do not render direct
> `km.*_matched` lists.
>
> **2. High — load-side persistence gap** (D3; `job_analysis_from_dict`)
> `asdict()` only solves serialization. Because `job_analysis_from_dict` explicitly
> enumerates fields, it must explicitly read `keyword_match_baseline_rate` and
> `keyword_match_source` with backward-compatible defaults, or every reload silently
> restores `baseline=None`/`source="master"`.
>
> **3. High — empty tailored CV corrupts a valid displayed result** (D1, D4, D5)
> D1 only distinguishes absent files. An existing empty/whitespace tailored file
> reaches `compute_keyword_match`, returns `None`, and overwrites a valid master
> score; the verdict becomes N/A. Fix: reject empty/whitespace tailored content with
> 422 before computation and do not save. Error: "Tailored CV is empty."
>
> **4. Medium — handler naming/status mismatch** (D5)
> Literal `load_analysis`/`save_analysis` will fail if those functions don't exist.
> 422-vs-404 is not cosmetic: it creates inconsistent behavior with sibling
> endpoints. Fix: use the real storage functions (`load_job_analysis`, the save
> counterpart). Match sibling behavior (404 for missing analysis); reserve 422 for
> "analysis exists but recheck cannot proceed" (unevaluated, missing/empty tailored
> CV, profile mismatch).
>
> **5. Medium — read/modify/write can lose updates** (D5, D7)
> Two tabs, a double-click, or a re-evaluation racing a recheck can overwrite fields.
> Worst case: recheck saving `source="tailored"` after a fresh evaluation reset it to
> `"master"`. Fix (MVP): serialize mutations per job with a process-local lock and
> atomic file replacement on save.
>
> **6. Medium — profile validation underspecified** (D4)
> "Optional profile_id match" is ambiguous. Fix: when `expected_profile_id` is
> provided, fail closed — metadata must be present and match exactly, else 422. If
> legacy untagged files must work, make that an explicit compatibility rule.
>
> **7. Low — `..` doesn't bypass containment here, but the validation is misleading**
> (D4) Given `{job_id}.md` filename construction + `resolve()` containment, `".."` is
> harmless. Fix: reject `"."`/`".."` for clarity; don't rely on the regex as the
> security boundary — keep resolved-path containment.
>
> **8. Low — permanently `None` baseline is a product-state gap** (D2, D6)
> If the initial master eval had no score, a tailored score has no meaningful "was
> X%". Fix: explicit "no baseline available" state — show "Now Y%", keep
> `baseline=None`. A full re-eval can establish a baseline. Don't substitute the
> first tailored score as baseline (false provenance).
>
> **9. Low — some mechanics overbuilt, but the state model is justified** (D2–D4, D6)
> `baseline_rate`/`source` are justified (overwriting otherwise loses provenance).
> The custom `outerHTML` path is unnecessary divergence from the existing AJAX
> convention, and the panel currently lacks the required ID. Fix: add a stable panel
> container and follow `innerHTML`, or have the server render only the panel body.
> Keep the two provenance fields; avoid history/audit tables for this MVP.
>
> **10. Low — missing tests:** AJAX/reload parity (canonicalization, duplicates,
> req/pref overlap); new fields surviving save/load + old JSON defaults; empty &
> comment-only files → 422 without mutation; profile metadata absent/malformed/
> match/mismatch; `.`/`..` job IDs + path containment; re-eval resetting
> baseline/source; concurrent recheck vs evaluation; DOM contract (panel ID exists,
> error leaves panel unchanged).
>
> **Single most important change:** render the recheck response through the same
> derived keyword-panel view model used after reload; otherwise users can see
> different match lists before and after refreshing.

### Disposition of Codex items
- **Accepted & folded:** H1, H2, H3, M4 (names + 404), M5 (lock + atomic), M6
  (fail-closed), low #7, #8, #9 (panel ID; outerHTML kept with invariant test), #10.
- **Kept as-is (deliberate):** `outerHTML` swap (isolated, invariant-tested) rather
  than refactoring to the `innerHTML` convention; shared-field overwrite of
  `keyword_match_rate` (MVP, provenance preserved via baseline/source).
- **No conflicts** between Claude's plan and Codex requiring a human tie-break — the
  three high items are pure correctness fixes.
