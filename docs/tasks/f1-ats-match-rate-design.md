# F1 Design — Per-job ATS Match Rate + keyword gap

<!-- STATUS -->
> **Implementation status:** ✅ Implemented v1 2026-06-19 — 337 tests green (incl. 17 keyword-match unit tests). Decisioning unchanged (advisory only).
> **Author:** Claude (PO/eng) · **Date:** 2026-06-19
> **Market rationale:** `docs/product-feature-research-2026-06.md` (F1, top pick)
> **Key new module:** `src/job_hunt_keyword_match.py`
> **Key functions:** `compute_keyword_match()`; hook in `evaluate_reviewed_job()`
> **Routes:** none for v1 (data rides the existing job page); `POST /job/{id}/ats-recheck` in v2
> **Decisioning:** v1 is **display/advisory only** — must NOT change Apply/Review/Skip
> **Reviewer:** Mic — approved direction with pre-build edits (incorporated 2026-06-19)
<!-- /STATUS -->

## Problem & rationale

ATS keyword alignment matters because recruiters **commonly use ATS filters and
keyword search**, so poorly formatted or keyword-mismatched CVs can be ranked
lower, missed, or filtered out ([jobscan-keywords]). A per-job **match rate** is
among the most-cited résumé-optimisation features in the market (Jobscan's core).

> **Stat caution (reviewer):** the widely-repeated "~75% of résumés are
> auto-rejected by ATS" claim is **contested** — it traces to a defunct vendor with
> no published methodology and lacks strong empirical support ([davron],
> [coversentry]). This design deliberately **does not** rely on it. The feature's
> value rests on the uncontested point above: keyword alignment affects
> ranking/visibility, and the tool can show users *which* keywords they're missing.

This product **does not have it.** What it has today is `score_cv()` in
`job_hunt_ats_scorer.py`, which produces a 0–100 **ATS-friendliness** score from
four sub-metrics — `keyword_density` (0–25), `format_score`, `section_presence`,
`length_score`. Two problems:

1. The keyword signal is **buried** inside a blended "overall" number and never
   shown as a match rate.
2. `_score_keyword_density` is **naive** (`kw.lower() in cv_lower` substring, no
   word boundaries, no required/preferred split, **no missing-keyword list**) —
   so it can't tell the user *which* keywords to add.

> **Important distinction (avoid conflation).** `ats_score` = "will an ATS parse
> this CV cleanly?" (format/length/sections + crude density). The new
> **keyword match rate** = "how well does this CV cover *this job's* keywords?".
> They answer different questions and **both stay**; F1 adds the second, it does
> not replace the first.

## Goals / non-goals

**Goals**
- A per-job **keyword match rate (0–100)** with a **present / missing** keyword
  breakdown, split into **required** vs **preferred**.
- Surfaced on the job detail page next to the existing scores; deterministic;
  computed locally (no LLM, no network).
- **Actively discourage keyword-stuffing** (the feature's main failure mode).

**Non-goals (v1)**
- No LLM keyword extraction; v1 keywords come from the job's already-extracted
  `required_skills` / `preferred_skills` (high signal, already in the model).
- No auto-rewrite of the CV to insert keywords (that's the Tailor feature, and
  auto-stuffing is harmful — see Risks).
- No scraping of full JD prose for keywords in v1 (noisy; see "Future").

## Domain design

### New module: `src/job_hunt_keyword_match.py`

```python
@dataclass(frozen=True)
class KeywordMatchResult:
    match_rate: int | None          # 0–100 overall; None when there are no keywords to match
    required_matched: list[str]
    required_missing: list[str]
    preferred_matched: list[str]
    preferred_missing: list[str]
    overused: list[str]             # keywords repeated > _STUFFING_THRESHOLD times (anti-stuffing signal)

def compute_keyword_match(
    cv_text: str | None,
    required_skills: list[str],
    preferred_skills: list[str],
) -> KeywordMatchResult: ...
```

### Matching algorithm (specified precisely)

1. **Inputs:** `cv_text` (the candidate's master CV text), the job's
   `required_skills` and `preferred_skills` (already normalised, deduped lists on
   `JobPosting`).
2. **Normalisation:** lowercase + collapse internal whitespace — the *same*
   convention as `job_hunt_scoring._normalize_text` (keep them consistent; see the
   "why a new matcher" note below).
3. **Presence test (per keyword) — edge-aware boundaries.** Plain `\b`/`(?<!\w)`
   boundaries misbehave for tech keywords containing punctuation (`C#`, `C++`,
   `.NET`, `Node.js`, `CI/CD`). `\w` only covers `[A-Za-z0-9_]`, so a trailing
   `(?!\w)` after `C#` (where `#` is already a non-word char) is a no-op, and a
   leading boundary before `.NET` can wrongly fire. **Spec:** apply a boundary
   *only on edges where the keyword's edge character is alphanumeric*:
   - left boundary `(?<![A-Za-z0-9])` only if `kw[0]` is alphanumeric;
   - right boundary `(?![A-Za-z0-9])` only if `kw[-1]` is alphanumeric;
   - the keyword body is `re.escape(kw)`; match on the normalised (casefolded,
     whitespace-collapsed) CV text, case-insensitive.

   This makes `"R"` match standalone `R` but not `React`; `"BA"` not match
   `database`; while `"C#"`, `"C++"`, `".NET"`, `"Node.js"`, `"CI/CD"`,
   `"Power BI"`, `"SQL"`, `"NoSQL"` all match as whole tokens. **These exact
   keywords are mandatory test cases** (see Tests).
4. **Canonical key & dedupe.** Two keywords are "the same" iff their
   **casefold + whitespace-collapsed** forms are equal. Dedupe each list on this
   key (preserve first-seen display casing). **Required wins:** if a keyword
   appears in both required and preferred, it is counted **once, as required**, and
   suppressed from the preferred lists — so totals never double-count.
5. **Rate:** `match_rate = round(100 * total_present / total_keywords)` over the
   deduped required ∪ preferred set. **Null contract:** if there are **zero**
   keywords, return `match_rate=None` (render "N/A") — **never 100** (the current
   `_score_keyword_density` returns full marks for "no keywords", which would give
   false confidence here).
6. **Required vs preferred** reported separately so the UI can stress required
   gaps (the ones that actually gate ATS pass-through).
7. **Overuse / anti-stuffing:** any keyword whose whole-word count in the CV
   exceeds `_STUFFING_THRESHOLD = 4` is flagged in `overused` (mirrors the ATS red
   flag "repeating the same phrase >3–4×" [theinterviewguys]).

> **Why a new matcher and not `_match_skills`?** `_match_skills(candidate_skills,
> job_skills)` matches a job skill against the candidate's **structured skill list**
> by set membership. F1 matches a keyword against the candidate's **free-text CV**
> by word-boundary search. Different inputs, different semantics — forcing reuse
> would distort one of them. They **share the `_normalize_text` convention** to
> stay consistent; the new module re-implements the one-line normaliser (or
> imports it) but not the matching.

## Data model changes (blast radius — touch all of these or load breaks)

Adding fields to `JobAnalysis` follows the same discipline as the
`CandidateProfile` rule: update **every** serialisation site.

| # | File | Change |
|---|---|---|
| 1 | `src/job_hunt_models.py` | Add to `JobAnalysis`: `keyword_match_rate: int \| None = None`, `keywords_required_missing: list[str] = field(default_factory=list)`, `keywords_preferred_missing: list[str] = field(default_factory=list)`, **`keywords_overused: list[str] = field(default_factory=list)`** (Comment #1 — the job page is rebuilt from stored `JobAnalysis` via `_build_job_page_vm`, so the stuffing warning is **lost unless persisted**; recomputing would need the CV, which isn't in scope at render). *Matched* lists stay derivable (job skills − missing) so only the missing lists + rate + overused are persisted. Extend `__post_init__` to validate `0 ≤ keyword_match_rate ≤ 100` when not None. |
| 2 | `src/job_hunt_storage.py` `job_analysis_to_dict` (L133) | serialise the 4 new fields |
| 3 | `src/job_hunt_storage.py` `job_analysis_from_dict` (L138) | read them back: `keyword_match_rate=_optional_int(...)`, the missing-lists and `keywords_overused` via `_string_list(...)` (reuse the existing validators) |
| 4 | `src/job_hunt_index.py` | **v1: NO change** (Comment #7). The value lives in the analysis JSON; the board doesn't sort by it yet, and a new column widens the schema/rebuild surface (`INSERT OR REPLACE` resets unlisted columns, and `_upsert_job_to_index` (QW-7) would need updating). Add a `keyword_match_rate` column **only in v2** if/when the board needs to sort/filter by it. |

### Hook point — `evaluate_reviewed_job()` (`src/job_hunt_evaluation.py`)

The ATS keyword data is computed **exactly where `ats_score` already is** — same
inputs in scope, deterministic, cached in the analysis:

```python
ats_score = None
keyword_match = compute_keyword_match(None, [], [])   # empty/None default
if profile.master_cv_text:
    job_keywords = list(job.required_skills) + list(job.preferred_skills)
    ats_score = score_cv(profile.master_cv_text, job_keywords)["overall"]   # unchanged
    keyword_match = compute_keyword_match(            # NEW
        profile.master_cv_text, list(job.required_skills), list(job.preferred_skills),
    )
# → carry match_rate + the two missing lists + keywords_overused onto the JobAnalysis
```

**Advisory only (Comment #6).** `keyword_match_rate` is **display-only in v1** and must NOT feed `decide_application()` — Apply/Review/Skip stays driven solely by score/blockers/risks (`job_hunt_evaluation.py`). Revisit only with real usage evidence.

**Null contract:** no master CV → `keyword_match_rate=None`, missing lists `[]`
(identical to how `ats_score` is `None`), so the UI shows "N/A — add your CV".

## UI (job detail page) — reuse the verdict area, don't add a big new card (Comment #5)

The job page already shows match score, confidence and **ATS readiness** in the
verdict card (`render_job_page` ~L688). Do **not** add another large repeated card.
Instead:

- Add a compact **"Keyword match — NN%"** (or "N/A") metric **beside the existing
  "ATS readiness"** in the verdict card, with a one-line tooltip distinguishing the
  two ("ATS readiness = will it parse; Keyword match = does it cover this job's
  keywords").
- Put the **required/preferred keyword chips** (present = green, **missing =
  amber**) **below the score breakdown / above the current Gaps section**, so it
  reads as part of the existing gap narrative rather than a competing panel.
- **Stuffing warning** (only when `keywords_overused` is non-empty): inline note —
  *"Some keywords repeat a lot. ATS flag stuffing (white text, keyword banks,
  repeating a phrase >3–4×). Weave missing keywords into real achievements
  instead."*
- Link the missing **required** keywords to the existing **Tailor CV** flow (it
  already promotes gap skills).

VM additions on `JobPageViewModel` / `_build_job_page_vm`: `keyword_match_rate`,
`keywords_required_missing`, `keywords_preferred_missing`, `keywords_overused`
(read straight from the stored `JobAnalysis`); the *matched* lists are rebuilt in
`_build_job_page_vm` as `job.required_skills − required_missing` (using the same
casefold canonical key) so `render_job_page` stays pure data-in/string-out.

## Tests

- **`tests/test_keyword_match.py`** (new): word-boundary correctness (`"R"` does
  **not** match `"React"`; `"stakeholder management"` matches as a phrase),
  required/preferred split, rate maths, **null contract** (no keywords →
  `None`, not 100; no CV → `None`), and overuse detection (`> 4` → flagged).
- **`tests/test_storage.py`**: round-trip `job_analysis_to_dict`/`from_dict` with
  the 4 new fields populated and absent (back-compat for old records → defaults).
- **`tests/test_evaluation.py`**: `evaluate_reviewed_job` populates
  `keyword_match_rate` when a master CV is present and leaves it `None` otherwise.
- **`tests/test_ui.py`**: the job page renders the match-rate panel + the missing
  chips (assert substrings), and shows the stuffing warning when overuse is seeded.

## Documentation updates (Comment #4 — fields must not live only in code)
- **`docs/data_contract.md`** — add the 4 new `JobAnalysis` fields to the documented shape.
- **`docs/product_spec.md`** — note the ATS keyword-match feature in scope.
- **`PROJECT_LOG.md` / `PROJECT_TODO.md` / `INDEX.md` / `function_list_v4.md`** — per the usual update-project-docs pass; bump the job-page `_PAGE_UPDATED["job"]` timestamp since `render_job_page` changes.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Encourages keyword-stuffing** (the core failure mode — ATS now penalise it) | The panel's copy steers to *natural integration*; `overused` detection warns; v1 deliberately does **not** auto-insert keywords |
| False positives/negatives from naive substring | Word-boundary regex on normalised text; phrases matched whole |
| Synonyms/abbreviations missed ("JS" vs "JavaScript", "PM" vs "Project Manager") | Out of scope v1; **Future**: a small alias map (`{"js":"javascript", …}`) — flagged, not built |
| "No keywords" giving false 100% | Explicit `None`/"N/A" null contract (≠ current `_score_keyword_density` behaviour) |
| Match rate diverges from `ats_score` and confuses users | Distinct labels + a one-line "what's the difference" tooltip; the two are presented as separate metrics |
| Match computed on master CV, not the tailored one | v1 documents this; **v2** adds `POST /job/{id}/ats-recheck` to re-score against the saved tailored CV |

## Phasing

- **Phase 1 (v1):** `job_hunt_keyword_match.py` + tests → `JobAnalysis` fields +
  serialisation → hook in `evaluate_reviewed_job` → job-page panel + warning.
  Deterministic, no new routes, no LLM. Effort: **M**.
- **Phase 2 (v2):** "re-check against tailored CV" action (`POST
  /job/{id}/ats-recheck`) so the rate reflects the tailored CV; optional alias map;
  optional index column for board sorting.

## Sources
- [jobscan-keywords] [Jobscan — top resume keywords / recruiters use ATS filters & search; tools show missing keywords](https://www.jobscan.co/blog/top-resume-keywords-boost-resume/)
- [jobscan] [Jobscan — AI job search tools (keyword-gap / ATS-compatibility as a core feature)](https://www.jobscan.co/blog/ai-job-search-tools/)
- [theinterviewguys] [The Interview Guys — ATS keyword-stuffing red flags](https://blog.theinterviewguys.com/ats-resume-optimization/)
- [davron] [DAVRON — the "75% ATS rejection" stat lacks empirical support](https://www.davron.net/ats-systems-explained-75-percent-resumes-rejected/)
- [coversentry] [CoverSentry — the viral 75% ATS-rejection figure traced to a defunct vendor](https://www.coversentry.com/ats-statistics)
- Product research: `docs/product-feature-research-2026-06.md`
