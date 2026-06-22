# Code Review — Job Seeking Tool
**Date:** 2026-06-18 | **Reviewer:** Senior Systems Analyst (AI-assisted)
**Scope:** All files under `src/`

---

## 1. Architecture Issues

### 1.1 `job_hunt_ui.py` is a 4,700-line god module

This is the dominant structural problem. The file contains: the HTTP server class, all route handlers, all HTML rendering functions (~2,000 lines of f-string HTML), CSS (~600 lines embedded in `render_page`), JavaScript (several hundred lines of concatenated Python strings), form parsing utilities, Reed source registration, the nonce system, salary/skill formatting utilities, and the profile page renderer. There is no separation between the HTTP layer, presentation layer, and coordination logic.

Consequence: any UI change requires navigating 4,700 lines of mixed Python/HTML/CSS/JS. `render_job_page` alone is ~1,200 lines. Writing meaningful unit tests means string-matching against massive HTML blobs.

### 1.2 Reed rendering logic does not live in the source module

`source_registry.py` was designed to decouple sources from the UI, but `_render_reed_search_form`, `render_reed_search_results`, `_render_reed_cards_fragment`, `reed_select_form_to_evaluate_values`, `normalize_reed_search_params`, all snapshot logic, and source registration all live in `job_hunt_ui.py`. The abstraction only decouples on paper. A second source would add another 300–500 lines to an already over-full file.

### 1.3 `shared_bus.py` has duplicate definitions and a hardcoded foreign path

`shared_bus.py` has two definitions each of `_conn()` (lines 27 and 257) and `DB_PATH` (lines 12 and 266) — the second pair silently overrides the first at import. `DB_PATH` on line 266 points to `~/.openclaw/workspace/shared_memory.db` — a path on an AI development machine, not this project. This file is dead weight and will crash if any swarm function is called.

### 1.4 Validation helpers are duplicated across three modules

`_required_string`, `_optional_string`, and `_normalise_string_list` exist independently in `job_hunt_storage.py`, `job_hunt_reviewed_input.py`, and `job_hunt_profile.py`, each with subtly different behaviour (different exception types, different empty-string handling). Three validation layers that can silently drift.

### 1.5 Index upsert block is copy-pasted five times

The `upsert_job` call with its 15-field dict appears near-verbatim in `_render_result`, `_handle_job_submit`, `_handle_outcome`, `_handle_decision_override`, and `_handle_batch_evaluate`. One will eventually diverge.

### 1.6 `evaluate_job_from_raw` is in `__all__` but does not exist

`job_hunt_evaluation.py` line 109 exports `evaluate_job_from_raw`. No such function is defined anywhere. Either a removed feature or an unfulfilled promise.

---

## 2. Code Quality Issues

### 2.1 `_score_required_skills` has a latent Iterable double-consume bug
**File:** `job_hunt_scoring.py` lines 96–97

```python
matched, missing = _match_skills(candidate_skills, required_skills)
required_list = list(required_skills)   # exhausted if caller passed a generator
```

If a one-shot iterator is passed, `required_list` is empty and the function silently returns the "no required skills" branch. Doesn't trigger today because `JobPosting.required_skills` is always a `list`, but the signature promises more.

### 2.2 Required-skills bonus can push dimension above weight cap
**File:** `job_hunt_scoring.py` line 141

```python
return weight + ((matched_count - 1) * bonus_per_extra_match)
```

3 of 3 matches → 35 + (2 × 3.5) = 42 points on a 35-point dimension. The global `min(100)` cap in `score_job` absorbs this but creates a false signal: a candidate can score 100 with only 3 of 5 required skills if the 3 they match also trigger the bonus. The dimension needs its own cap.

### 2.3 ATS scorer penalises well-formatted CVs
**File:** `job_hunt_ats_scorer.py` lines 74–80

`_score_format` returns 0 if the CV has 3 or more ALL-CAPS headings. `EXPERIENCE`, `SKILLS`, `EDUCATION` — standard ATS-friendly CV format per every major CV guide — score 0. A wall of unstructured text scores higher than a properly structured CV. This inverts the scoring signal.

### 2.4 `_read_multipart_form` crashes on `Content-Type` without a boundary
**File:** `job_hunt_ui.py` lines 572–573

```python
_, options = content_type.split(";", 1)
_, boundary = options.strip().split("=", 1)
```

`ValueError` if `Content-Type` is `multipart/form-data` without `;boundary=...`. The outer try/except catches it but surfaces "not enough values to unpack" to the browser.

### 2.5 `reed_client.py` calls `logging.basicConfig` at module level
**File:** `reed_client.py` line 10

Overrides any logging configuration the host process has already set. Modules should use `logging.getLogger(__name__)` and leave `basicConfig` to the entry point.

### 2.6 `_handle_parse_cv` mutates a `slots=True` dataclass directly
**File:** `job_hunt_ui.py` lines 461–462

```python
_profile_obj.master_cv_text = text
_profile_obj.master_cv_ref = str(_cv_path.resolve())
```

`CandidateProfile` uses `slots=True` (not `frozen=True`) so this doesn't raise at runtime, but it bypasses `__post_init__` validation and is inconsistent with `job_hunt_orchestrator.py` which correctly uses `dataclasses.replace()`.

### 2.7 Full CSS + JS is inlined on every response
**File:** `job_hunt_ui.py` `render_page` function

~800 lines of CSS/JS repeated on every page load, no `Cache-Control`, no static file routes. Harmless for local use but complicates testing rendered output and inflates response sizes.

### 2.8 `consume_select_nonce` is permanently disabled
**File:** `job_hunt_ui.py` lines 1905–1909

Always returns `True` regardless of input. The comment explains this was done to avoid dev-reload friction. The entire nonce/TTL infrastructure is therefore misleading dead code — it should either be reinstated or removed entirely.

### 2.9 Dangling orphan string in JS block
**File:** `job_hunt_ui.py` line 2835

```python
'var cvTextarea = document.querySelector("textarea[name=\'master_cv_text']");'
```

A bare string literal inside a JavaScript IIFE — no-op at runtime but confuses the intent. The variable appears to be unused.

### 2.10 `job_hunt_config.py` `__all__` only lists one export
**File:** `job_hunt_config.py` line 106

```python
__all__ = ["ScoringWeights"]
```

The module exports `ScoringPolicy`, `DecisionPolicy`, `DEFAULT_SCORING_POLICY`, `get_enabled_sources`, and more — none listed. The `__all__` is misleading.

---

## 3. Security / Correctness Issues

### 3.1 Profile paths are relative to CWD, not an absolute anchor

`_allowed_profile_dir` constructs `Path("data") / profile_id`. If the server is started from a directory other than the project root, all profile path resolution shifts silently. `Path.resolve()` should be anchored to a known absolute startup location from `UIServerConfig`.

### 3.2 Same CWD issue applies to CV file writes

`_handle_parse_cv` and `_handle_save_profile` write CV files to `data/{profile_id}/docs/master_cv{ext}` — a relative path. Wrong CWD = files written to unexpected locations.

### 3.3 Required-skills-missing gives 0 score, not neutral

When `required_skills == []`, the required-skills dimension scores 0 rather than neutral. This silently penalises jobs with incomplete skill data in the most important dimension — the opposite of what the confidence system is supposed to do (carry uncertainty, not penalise it).

### 3.4 Skill names have no length cap

`POST /job/{id}/add-gap-skills` accepts skill names from JSON body, strips whitespace and deduplicates, then writes directly to the profile. No length limit. XSS is handled by `escape()` at render time, but unbounded strings accumulate in the profile JSON.

### 3.5 `robots.txt` fetch fires before SSRF guard on URL ingestion

In `parse_job_from_url`, `_robots_cache.is_allowed(url)` makes a network request before the SSRF check fires. A crafted hostname could be probed via the robots TTL cache before the SSRF guard has a chance to block it.

---

## 4. Test Coverage Gaps

The domain logic modules are reasonably well covered. Gaps:

| Area | Status |
|---|---|
| `shared_bus.py` | Zero tests — duplicate `_conn`/`DB_PATH` bug would be caught immediately by an import test |
| `POST /jobs/batch-evaluate` | Completely untested |
| `GET /search/reed/more` (pagination) | Completely untested |
| ATS scorer — ALL-CAPS heading format scoring | Test confirms broken behaviour but no regression guard for a fix |
| `_read_multipart_form` crash on missing boundary | Not tested |
| Profile path resolution when CWD ≠ project root | Not tested |
| `evaluate_job_from_raw` | In `__all__`, doesn't exist, not tested |
| `_handle_save_profile` skills parsing (JSON vs comma-split) | Not tested |
| CV auto-save happy path in `_handle_parse_cv` | Not tested |
| `score_job` partial experience credit, location + remote override, bonus-cap interaction | Not individually covered in `test_scoring.py` (7 tests total for a multi-dimensional scorer) |

---

## 5. Improvement Plan

### Quick wins — do these first

| # | What | File(s) | Why |
|---|---|---|---|
| QW-1 | Fix `_score_required_skills` signature to `list[str]`, remove double-iteration | `job_hunt_scoring.py` L91–108 | Silent correctness bug |
| QW-2 | Fix ATS scorer — remove or flip ALL-CAPS penalty | `job_hunt_ats_scorer.py` L74–80 | Inverted scoring signal for most professional CVs |
| QW-3 | Remove `logging.basicConfig` from `reed_client.py` module level | `reed_client.py` L10 | Overrides host logging config |
| QW-4 | Delete or fix `shared_bus.py` | `shared_bus.py` | Duplicate definitions, hardcoded foreign path, dead code |
| QW-5 | Remove `evaluate_job_from_raw` from `__all__` or implement it | `job_hunt_evaluation.py` L109 | Misleading export |
| QW-6 | Fix `job_hunt_config.py` `__all__` | `job_hunt_config.py` L106 | Misleading |
| QW-7 | Extract `upsert_job` into a single `_upsert_job_to_index(job_id)` helper | `job_hunt_ui.py` | 5 copy-pasted blocks that will diverge |
| QW-8 | Add dimension-level cap to `_score_skill_bucket` return value | `job_hunt_scoring.py` L141 | Bonus inflates past dimension weight, hits global cap silently |
| QW-9 | Add length cap (~120 chars) to skill names in `_handle_add_gap_skills` | `job_hunt_ui.py` L~1091 | Unbounded strings in profile JSON |

### Medium-term — bounded design work required

| # | What | File(s) |
|---|---|---|
| MT-1 | Move all Reed rendering/normalisation into `src/job_sources/reed_source.py` | New `reed_source.py`, `job_hunt_ui.py` (~−600 lines) |
| MT-2 | Extract shared validation helpers to `src/job_hunt_validation.py` | New file, 3 existing modules |
| MT-3 | Fix required-skills-missing to score neutral, not 0 | `job_hunt_scoring.py` |
| MT-4 | Guard `_read_multipart_form` against missing `Content-Type` boundary | `job_hunt_ui.py` L572–574 |
| MT-5 | Anchor all profile paths to `UIServerConfig.state_root` (absolute) | `job_hunt_ui.py` L~150–166 |
| MT-6 | Write tests for batch evaluate, pagination endpoint, CV auto-save, skills parsing | `tests/test_ui.py` |
| MT-7 | Either remove nonce infrastructure or re-enable `consume_select_nonce` | `job_hunt_ui.py` L1905–1909 |

### Longer-term — architectural, worth deferring

| # | What | Payoff |
|---|---|---|
| LT-1 | Split `job_hunt_ui.py` into `ui_routes.py` / `ui_handlers.py` / `ui_render.py` | Makes each layer independently testable; currently ~4,700 lines is past the point a new developer can reason about |
| LT-2 | Move CSS and JS to module-level constants or template files | Eliminates Python string-escaping friction; makes CSS/JS editable without touching render functions |
| LT-3 | Add `__post_init__` validator to `ScoringWeights` asserting weights sum to 100 | Misconfigured weights currently hit the global `min(100)` cap silently |

---

## Summary counts

| Category | Count |
|---|---|
| Architecture issues | 6 |
| Code quality issues | 10 |
| Security / correctness issues | 5 |
| Test coverage gaps | 10 areas |
| Quick wins | 9 |
| Medium-term improvements | 7 |
| Longer-term improvements | 3 |

**Most urgent:** QW-2 (ATS scorer inverted signal), QW-4 (dead `shared_bus.py`), QW-7 (5× duplicated upsert block), MT-1 (extract Reed source), MT-5 (relative path anchor).
