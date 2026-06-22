# LT-01 Design — Split `job_hunt_ui.py` into Layers

<!-- STATUS -->
> **Implementation status:** ✅ Implemented 2026-06-19 — 291 tests green
> **Divergences from spec:** `raw_input_payload_from_form` kept in `ui_handlers` (Reed-coupled, not pure); `render_select_options` + nonce helpers placed in `ui_utils` rather than `ui_render` (to break the reed↔ui circular import); `render_page`/page renderers take `model_label: str` instead of the whole `config`; QW-7 `_upsert_job_to_index` consolidation and Step 7 re-export cleanup deferred.
> **Key files:** `ui_state.py`, `ui_utils.py`, `ui_render.py` (view-models `JobPageViewModel`/`ProfilePageViewModel`/`ReviewQueueViewModel`), `ui_handlers.py` (standalone `handle_*`/`render_*` fns), `ui_routes.py` (`UIRequest`/`UIResponder`/`_parse_request`/`_build_handler`/`main`), `job_sources/reed_source.py`; `job_hunt_ui.py` → 48-line shell.
> **Routes:** all routes (unchanged); new `GET /sources` handler `handle_sources`.
<!-- /STATUS -->

**Date:** 2026-06-18 (v2 — reviewer findings addressed)
**Author:** Code review + Mic
**Prerequisite:** MT-1 (Reed source extraction) should be done first — it removes ~650 lines before the split and makes the split cleaner.

**Review findings addressed (v2):**
- F1 (High): Thin-shell re-export contract specified — all 9 symbols currently imported from `src.job_hunt_ui` must be re-exported from the shell during migration
- F2 (High): `render_page()` LLM dependency — `model_label: str` passed as render data from handler/config; `ui_render.py` never imports domain modules
- F3 (High): `select_handler` contract change made explicit — updated from `(form)` to `(form, config)` with migration note
- F4 (Medium): Source registration in `ui_routes.py` explicitly modelled as startup side effects, not a dependency inversion
- F5 (Medium): Duplicate upsert cleanup (`_upsert_job_to_index`) moved to Step 5 (during handler extraction), not Step 7
- F6 (Medium): View-model dicts specified for `render_profile_page`, `render_job_page`, and `render_review_queue_page`
- F7 (Medium): `/sources` route added to handler table and dispatch
- F8 (High): `source_registry.py` contract updated — `render_results` signature changed from 3 to 4 args (`more_url=None`)
- F9 (High): `UIRequest` dataclass introduced alongside `UIResponder` — closes the input/body-parsing boundary so handlers are fully testable without a live HTTP object

---

## Problem

`src/job_hunt_ui.py` is 4,729 lines. It contains five distinct concerns with no boundaries between them:

| Concern | Lines (approx) | Example |
|---|---|---|
| HTTP routing (dispatch) | ~200 | `do_GET`, `do_POST`, path regex |
| Request handlers (load/validate/save/respond) | ~900 | `_handle_evaluate`, `_handle_tailor` |
| HTML rendering | ~2,500 | `render_job_page`, `render_reed_search_results` |
| Reed-specific logic | ~650 | `render_reed_search_results`, `normalize_reed_search_params` |
| Utilities + constants | ~480 | `escape`, `format_salary_range`, `_PAGE_UPDATED` |

**Why this matters now:** the user plans to add Adzuna, LinkedIn, and possibly more job sources. Each new source will add ~300–500 lines of rendering and normalisation logic. Without a split, the file will reach 6,000–7,000 lines within two new sources. The current structure also makes every handler and renderer untestable without a live HTTP server.

---

## Design Goals

1. **Each layer testable in isolation** — handlers can be tested by passing a mock `UIRequest` + `UIResponder`; render functions take only data and return strings.
2. **One file per source** — each job source lives entirely in `src/job_sources/{source}_source.py`. Adding Adzuna means creating one file, not editing `ui_handlers.py`.
3. **No circular imports** — dependency graph flows in one direction only: routes → handlers → render → utils.
4. **Backward-compatible entry point** — `python3 src/job_hunt_ui.py` continues to work.
5. **Incremental migration** — layers can be extracted one at a time; the server stays runnable at each step.

---

## Target File Structure

```
src/
├── job_hunt_ui.py          ← thin shell; re-exports for backward compat; entry point
├── ui_state.py             ← constants, UIServerConfig, _PAGE_UPDATED, global dicts
├── ui_utils.py             ← escape, format helpers, form field extractors
├── ui_render.py            ← all HTML render functions (pure: data in, string out)
├── ui_handlers.py          ← all request handler functions (load/validate/save/respond)
├── ui_routes.py            ← HTTP server class, do_GET/do_POST dispatch, UIRequest, UIResponder
└── job_sources/
    ├── source_registry.py  ← updated: render_results now 4-arg contract
    ├── reed_source.py      ← NEW: all Reed rendering, normalisation, registration (MT-1)
    ├── adzuna_source.py    ← future: same pattern
    └── linkedin_source.py  ← future: same pattern
```

**Import direction (strict — no upward imports):**

```
ui_routes.py
    ↓ imports
ui_handlers.py
    ↓ imports
ui_render.py
    ↓ imports
ui_utils.py   ←── ui_state.py (both are leaves; no inter-dependency)
```

Domain modules (`job_hunt_storage`, `job_hunt_orchestrator`, etc.) are imported by `ui_handlers.py` only — never by `ui_render.py` or lower.

**Source registration — startup side effects only:**

`ui_routes.py` imports each source module (`reed_source`, `adzuna_source`, etc.) at the top level for their side effect: calling `register(JobSource(...))` at module import time. These are not runtime dependencies — `ui_routes.py` does not call functions on the source modules directly. The `source_registry` is the runtime interface. This is intentional and is NOT a violation of the dependency rule.

```python
# ui_routes.py — top of file
from src.job_sources import reed_source as _reed  # noqa: F401 — registration side effect
# Adding Adzuna = one line here, nothing else
```

---

## Layer Specifications

### `ui_state.py` — Constants and shared state

No imports from any other `ui_*.py` file. Imported by all other layers.

**Contains:**
```python
_PAGE_UPDATED: dict[str, str]       # per-page timestamps
_HOME_TABS: set[str]                # valid sidebar tab keys
_SELECT_NONCES: dict[str, float]    # nonce store (or remove — see QW-7 / MT-7)
_SELECT_FORM_FIELD_LIMITS: dict[str, int]
_ALLOWED_WORK_MODES: set[str]
_ALLOWED_EMPLOYMENT_TYPES: set[str]
_REED_SOURCE_SNAPSHOT_MAX_BYTES: int
_REED_SOURCE_SNAPSHOT_VERSION: str
_MAX_CV_SIZE_BYTES: int
_ALLOWED_CV_EXTENSIONS: set[str]
_ALLOWED_CV_MIMETYPES: set[str]

@dataclass(frozen=True, slots=True)
class UIServerConfig:
    model_label: str   # e.g. "gemini-2.0-flash" — passed to render layer, not imported there
    ...
```

---

### `ui_utils.py` — Pure helper functions

Imports only stdlib and `ui_state`. No domain module imports.

**Contains:**

| Function | Purpose |
|---|---|
| `escape(v)` | HTML-escape any value, None → "" |
| `format_salary_range(min, max)` | `£50,000 – £70,000` display string |
| `squash_whitespace(s)` | collapse multi-spaces/newlines |
| `normalize_optional_int_text(s, lo, hi)` | clamp string to int range |
| `default_form_values()` | blank evaluate form dict |
| `stringify_form_value(v)` | flatten list or scalar to string |
| `split_lines_or_commas(s)` | skills text → list |
| `required_text(form, key)` | extract required field, raise ValueError if absent |
| `optional_text(form, key)` | extract optional field, return None if blank |
| `optional_float(form, key)` | extract optional float |
| `optional_int(form, key)` | extract optional int |
| `reviewed_job_payload_from_form(form)` | build typed dict from evaluate form |
| `raw_input_payload_from_form(form, payload)` | build raw_input dict |
| `job_id_from_request_path(path, query)` | parse /job?job_id= or /job/{id} |

---

### `ui_render.py` — Pure HTML rendering

Imports `ui_utils`, `ui_state`, stdlib only. **No domain module imports. No network calls. No file I/O.** Every function takes data as arguments and returns a string.

This is the key constraint: if a render function currently loads data itself (e.g. calls `load_candidate_profile`) or imports domain modules (e.g. `src.job_hunt_llm._model`), that load/import is moved to the handler and the data is passed in.

**The `model_label` case:** `render_page()` currently imports `src.job_hunt_llm._model` to display the model name in the footer. In the split, `model_label: str` is a field on `UIServerConfig` (set at startup). Handlers pass `config` to `render_page`; `render_page` reads `config.model_label`. No domain import needed.

#### View-model contracts

Render functions for complex pages accept typed view-model dicts, not raw domain objects. This decouples `ui_render.py` from domain model shape even without importing domain modules.

**`JobPageViewModel`** (passed to `render_job_page`):
```python
@dataclass(frozen=True)
class JobPageViewModel:
    job_id: str
    title: str
    company: str
    location: str
    work_mode: str
    employment_type: str
    salary_display: str | None
    url: str | None
    description_raw: str | None
    match_score: int | None
    decision: str | None
    user_decision: str | None
    fit_summary: str | None         # from LLM analysis
    risk_summary: str | None        # from LLM analysis
    action_items: list[str]
    required_skills_matched: list[str]
    required_skills_missing: list[str]
    optional_skills_matched: list[str]
    outcome_status: str | None
    tailoring_ready: bool
    flash: str | None
    embed: bool
    model_label: str
```

**`ProfilePageViewModel`** (passed to `render_profile_page`):
```python
@dataclass(frozen=True)
class ProfilePageViewModel:
    profile_id: str
    name: str
    target_roles: list[str]
    skills: list[str]
    required_skills: list[str]
    location: str | None
    work_mode_preference: str | None
    salary_min: int | None
    salary_max: int | None
    master_cv_text: str | None
    master_cv_ref: str | None
    saved_searches: list[dict]      # populated by handler from saved_searches module
    flash: str | None
    model_label: str
```

**`ReviewQueueViewModel`** (passed to `render_review_queue_page`):
```python
@dataclass(frozen=True)
class ReviewQueueViewModel:
    jobs: list[dict]    # lightweight: job_id, title, company, match_score, decision
    active_job: JobPageViewModel | None
    model_label: str
```

Handlers build these view models from domain objects before calling the render function. Render functions never call `.skills`, `.master_cv_text` etc. directly on a `CandidateProfile` — they read from the view model only.

**Render function table:**

| Function | Signature (simplified) | Purpose |
|---|---|---|
| `render_page(body, sidebar, *, tab, config)` | `str` | Wraps body in full HTML shell with CSS + global JS |
| `_render_sidebar(active_tab, config)` | `str` | Left nav sidebar |
| `render_home_page(tabs_html, sidebar_html, *, config)` | `str` | Assembles home page |
| `_render_search_jobs_tab(forms_html, results_html)` | `str` | Search Jobs tab panel |
| `_render_add_job_tab(prefill_values)` | `str` | Add Job tab panel |
| `_render_add_job_form_fields(values)` | `str` | Form fields within Add Job |
| `_render_profile_tab_section()` | `str` | Profile placeholder tab |
| `render_input_form(values)` | `str` | Evaluate tab form |
| `render_history_table(rows)` | `str` | History tab table |
| `render_job_page(vm: JobPageViewModel)` | `str` | Full job detail page |
| `render_review_queue_page(vm: ReviewQueueViewModel)` | `str` | Two-panel review queue |
| `render_profile_page(vm: ProfilePageViewModel)` | `str` | My Profile page |
| `render_sources_page(sources: list[dict], *, config)` | `str` | Source status page |
| `render_simple_list(title, items)` | `str` | Titled `<ul>` |
| `render_detail_item(label, value)` | `str` | Label + value div |
| `render_select_options(options, selected)` | `str` | `<option>` elements |

> **Source-specific render functions** (Reed cards, Reed search results, Reed select form) move to `src/job_sources/reed_source.py` as part of MT-1. `ui_render.py` does not import from any source module. Sources register themselves into the render pipeline via `source_registry`.

---

### `ui_handlers.py` — Request handler functions

Imports `ui_render`, `ui_utils`, `ui_state`, and all domain modules (`job_hunt_storage`, `job_hunt_orchestrator`, etc.). **Does not import `ui_routes`.**

Each handler is a standalone function. It receives a `UIRequest` and a `UIResponder` (see next section) rather than `self`. This makes every handler independently testable without a live HTTP server.

**Handler function signature pattern:**

```python
def handle_evaluate(
    req: UIRequest,
    config: UIServerConfig,
    responder: UIResponder,
) -> None:
    form = req.form        # pre-parsed by routes layer; no BaseHTTPRequestHandler needed
    job = reviewed_job_payload_from_form(form)
    result = run_local_evaluation_flow_from_payload(job, config.state_root)
    vm = _build_job_page_vm(result, flash="Evaluated", config=config)
    html = render_job_page(vm)
    responder.send_html(html)
```

**Contains (all current `_handle_*` and load-level `_render_*`):**

| Handler | Route | Notes |
|---|---|---|
| `handle_home(req, config, responder)` | `GET /` | Loads profile + history; calls render |
| `handle_source_search(req, config, responder)` | `GET /search/{src}` | Calls source search; builds more_url |
| `handle_search_reed_more(req, config, responder)` | `GET /search/reed/more` | AJAX next page of Reed cards |
| `handle_source_select(req, config, responder)` | `POST /select/{src}` | Source select → prefill values → re-render home |
| `handle_evaluate(req, config, responder)` | `POST /evaluate` | Run evaluation, render result |
| `handle_job_submit(req, config, responder)` | `POST /job-submit` | Validate + evaluate + redirect |
| `handle_prefill(req, config, responder)` | `POST /prefill` | Parse text/URL, return JSON |
| `handle_job(req, config, responder)` | `GET /job/{id}` | Load + render job detail |
| `handle_job_explain(req, config, responder)` | `GET /job/{id}/explain` | LLM explain, return JSON |
| `handle_decision_override(req, config, responder)` | `POST /job/{id}/decision` | Update user_decision, return JSON |
| `handle_add_gap_skills(req, config, responder)` | `POST /job/{id}/add-gap-skills` | Append gap skills to profile |
| `handle_ai_review_cv(req, config, responder)` | `POST /job/{id}/ai-review-cv` | LLM CV review, return JSON |
| `handle_outcome(req, config, responder)` | `POST /outcome` | Create/update outcome |
| `handle_batch_evaluate(req, config, responder)` | `POST /jobs/batch-evaluate` | Batch evaluate up to 20 jobs |
| `handle_review_queue(req, config, responder)` | `GET /review-queue` | Load + render review queue |
| `handle_jobs_save(req, config, responder)` | `POST /jobs/save` | Save job without evaluate |
| `handle_get_jobs(req, config, responder)` | `GET /jobs` | Return JSON jobs list |
| `handle_get_board(req, config, responder)` | `GET /board` | Return JSON kanban board |
| `handle_get_board_view(req, config, responder)` | `GET /board/view` | Render board HTML page |
| `handle_profile(req, config, responder)` | `GET /profile` | Load + render profile page |
| `handle_save_profile(req, config, responder)` | `POST /profile/save` | Save profile, redirect |
| `handle_parse_cv(req, config, responder)` | `POST /profile/parse-cv` | Parse CV file upload |
| `handle_tailor(req, config, responder)` | `POST /tailor` | Full tailor pipeline |
| `handle_cover_letter(req, config, responder)` | `POST /cover-letter` | Generate cover letter |
| `handle_sources(req, config, responder)` | `GET /sources` | List registered sources + status |

**Shared handler utilities (stay in `ui_handlers.py`):**

```python
def _upsert_job_to_index(job_id: str, config: UIServerConfig) -> None:
    """Single canonical upsert — replaces 5× copy-pasted blocks. Added in Step 5."""
    ...

def _load_recent_job_history(config: UIServerConfig) -> list[dict]: ...
def _allowed_profile_dir(profile_id: str, config: UIServerConfig) -> Path | None: ...
def _normalize_home_tab(raw: str) -> str: ...
def _build_job_page_vm(result, *, flash, config) -> JobPageViewModel: ...
def _build_profile_page_vm(profile, *, flash, config) -> ProfilePageViewModel: ...
def _build_review_queue_vm(jobs, active_job, *, config) -> ReviewQueueViewModel: ...
```

---

### `UIRequest` and `UIResponder` — Full handler testability boundary

The key to testable handlers is a boundary on *both* sides: `UIRequest` for input, `UIResponder` for output. Without `UIRequest`, handlers still reach into `BaseHTTPRequestHandler` for body parsing and headers, which requires a live HTTP socket.

```python
@dataclass(frozen=True)
class UIRequest:
    """Pre-parsed request passed to every handler. Built by ui_routes from BaseHTTPRequestHandler."""
    method: str                       # "GET" or "POST"
    path: str                         # raw path, e.g. "/job/abc-123"
    query: dict[str, str]             # parsed query string
    form: dict[str, str]              # parsed form body (application/x-www-form-urlencoded)
    json_body: Any                    # parsed JSON body, or None
    raw_body: bytes                   # raw bytes for multipart/binary (e.g. CV uploads)
    headers: dict[str, str]           # lowercased header names
    content_type: str                 # e.g. "multipart/form-data; boundary=..."
```

`ui_routes.py` constructs `UIRequest` from `BaseHTTPRequestHandler` before calling any handler. The handler never sees `self` (the raw HTTP object).

```python
@dataclass
class UIResponder:
    """Thin wrapper around an HTTP request handler for sending responses."""
    _handler: BaseHTTPRequestHandler

    def send_html(self, html: str, status: int = 200) -> None: ...
    def send_json(self, data: Any, status: int = 200) -> None: ...
    def redirect(self, url: str) -> None: ...
```

**In tests — both sides mocked, no socket required:**

```python
class MockResponder:
    def __init__(self):
        self.html_sent = None
        self.json_sent = None
        self.redirect_url = None
    def send_html(self, html, status=200): self.html_sent = html
    def send_json(self, data, status=200): self.json_sent = data
    def redirect(self, url): self.redirect_url = url

def test_handle_evaluate_bad_form():
    req = UIRequest(method="POST", path="/evaluate", query={}, form={},
                    json_body=None, raw_body=b"", headers={}, content_type="")
    responder = MockResponder()
    handle_evaluate(req, config=test_config, responder=responder)
    assert responder.json_sent["ok"] is False

def test_handle_parse_cv_reads_raw_body():
    req = UIRequest(method="POST", path="/profile/parse-cv", query={}, form={},
                    json_body=None, raw_body=b"%PDF-1.4...",
                    headers={"content-type": "application/pdf"}, content_type="application/pdf")
    responder = MockResponder()
    handle_parse_cv(req, config=test_config, responder=responder)
    assert responder.redirect_url == "/profile"
```

---

### `ui_routes.py` — HTTP server and dispatch

Imports `ui_handlers`, `ui_state`, `ui_utils`, stdlib, and source modules (startup registration only).

**Contains:**

```python
def _build_handler(config: UIServerConfig) -> type:
    """Returns a JobSeekingUIHandler class bound to config."""
    class JobSeekingUIHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            req = _parse_request(self)
            self._dispatch(req)

        def do_POST(self):
            req = _parse_request(self)
            self._dispatch(req)

        def _dispatch(self, req: UIRequest) -> None:
            responder = UIResponder(self)
            # Pure routing — no logic, just path matching and handler calls
            ...
        def log_message(self, *_): pass
    return JobSeekingUIHandler

def _parse_request(handler: BaseHTTPRequestHandler) -> UIRequest:
    """Build UIRequest from BaseHTTPRequestHandler. All body parsing happens here."""
    ...

def main() -> None: ...
def build_parser() -> argparse.ArgumentParser: ...
```

The dispatch method is purely routing — it parses path/query, builds `UIRequest`, instantiates `UIResponder(self)`, and calls the appropriate `ui_handlers.*` function. Zero business logic.

---

### `src/job_sources/source_registry.py` — Updated contract

`source_registry.py` is **not unchanged**. The `render_results` field must be updated to a 4-argument contract (`more_url=None` was added in the Reed pagination fix):

```python
@dataclass(frozen=True, slots=True)
class JobSource:
    source_id: str
    display_name: str
    is_available: Callable[[], bool]
    normalize_search_params: Callable[[dict[str, str]], dict[str, str]]
    search_handler: Callable[[dict[str, str]], list[dict[str, Any]]]
    select_handler: Callable[[dict[str, str], UIServerConfig], dict[str, str]]
    #                                         ^^^^^^^^^^^^^^^^^
    #                         CHANGED: was (form) -> dict; now (form, config) -> dict
    #                         Migration: existing call sites pass config explicitly;
    #                         or use functools.partial at registration to inject config
    render_search_form: Callable[[dict, bool], str]
    render_results: Callable[[list, str | None, str | None, str | None], str]
    #                                                        ^^^^^^^^^^^^
    #                         CHANGED: was 3-arg; now 4-arg (more_url=None added)
    #                         All registered sources must implement the 4-arg signature
```

**`select_handler` contract change migration note:**
The current `JobSource.select_handler` is `(form) -> dict`. The new contract is `(form, config) -> dict`. During MT-1, `reed_source.py`'s `select_handler` is written with the new signature. The registry type annotation is updated. Any future source must follow the 4-arg `render_results` and 2-arg `select_handler` contracts from day one.

---

### `src/job_hunt_ui.py` — Thin shell (entry point + backward-compat re-exports)

After the split, this file becomes a ~40-line shell. It re-exports all symbols that current tests or importers use from `src.job_hunt_ui`, so no test file needs to change until Step 6 is complete:

```python
"""
Job Seeking Tool — UI entry point.
Run: python3 src/job_hunt_ui.py [--host] [--port] [--profile] [--state-root]

The real implementation is split across:
  ui_state.py    — constants and configuration
  ui_utils.py    — shared helpers and form utilities
  ui_render.py   — HTML rendering functions
  ui_handlers.py — request handler logic
  ui_routes.py   — HTTP server and route dispatch
"""
from src.ui_routes import main, _build_handler
from src.ui_state import UIServerConfig
from src.ui_utils import (
    default_form_values,
    format_salary_range,
    job_id_from_request_path,
    raw_input_payload_from_form,
    reviewed_job_payload_from_form,
    split_lines_or_commas,
)
from src.ui_handlers import _load_recent_job_history as load_recent_job_history

__all__ = [
    "main",
    "_build_handler",
    "UIServerConfig",
    "default_form_values",
    "format_salary_range",
    "job_id_from_request_path",
    "load_recent_job_history",
    "raw_input_payload_from_form",
    "reviewed_job_payload_from_form",
    "split_lines_or_commas",
]

if __name__ == "__main__":
    main()
```

**After the split is stable** (all tests passing, team familiar with the new layout), these re-exports are removed one by one as tests and importers are updated to import from the correct new modules. This is a separate cleanup pass, not part of LT-1.

---

### `src/job_sources/reed_source.py` — Reed source module (MT-1)

This is extracted as part of MT-1, and is a prerequisite for the LT-1 split because it removes ~650 lines from `job_hunt_ui.py` before the main split begins.

**Contains everything Reed-specific:**

```python
# Rendering
def render_search_form(values: dict, enabled: bool) -> str: ...
def render_results(results, error, nonce, more_url=None) -> str: ...   # 4-arg contract
def _render_cards_fragment(results, *, skip=0, nonce=None) -> str: ...
def render_select_form(result: dict, nonce: str, form_id: str) -> str: ...

# Normalisation + validation
def normalize_search_params(params: dict) -> dict: ...
def default_search_values() -> dict: ...
def search_handler(search_values: dict) -> list[dict]: ...
def select_handler(form: dict, config: UIServerConfig) -> dict: ...    # 2-arg contract

# Snapshot helpers
def build_source_snapshot(job: dict) -> dict: ...
def serialize_source_snapshot(snapshot: dict) -> str: ...
def validate_source_snapshot_json(s: str) -> dict: ...
def truncate_description(s: str, max_chars=500) -> str: ...
def filter_notes(result: dict, search_values: dict) -> str: ...

# Reed salary helpers
def format_salary_display(min_val, max_val) -> str: ...
def normalize_salary_value(v) -> str: ...
def parse_salary_number(v) -> int | None: ...
def normalize_source_job_id(v) -> str | None: ...
def validate_salary_text(v: str) -> bool: ...

# Registration (called at module import — startup side effect)
def _register() -> None:
    register(JobSource(
        source_id="reed",
        display_name="Reed",
        is_available=_is_available,
        normalize_search_params=normalize_search_params,
        search_handler=search_handler,
        select_handler=select_handler,
        render_search_form=render_search_form,
        render_results=render_results,   # 4-arg
    ))

_register()
```

**How a new source (e.g. Adzuna) follows the same pattern:**

```python
# src/job_sources/adzuna_source.py
def render_results(results, error, nonce, more_url=None): ...   # 4-arg required
def select_handler(form, config): ...                           # 2-arg required
...

def _register():
    register(JobSource(source_id="adzuna", ...))

_register()
```

Adding Adzuna to the app = one import line in `ui_routes.py`:
```python
from src.job_sources import adzuna_source as _adzuna_src  # noqa: F401 — registration
```
No other file changes needed.

---

## Migration Strategy — Incremental, Always Runnable

Do not do this as a single PR. The order below keeps the server runnable after every step:

### Step 1 — Extract Reed source (MT-1, prerequisite)
Move all Reed-specific code to `src/job_sources/reed_source.py`.
Update `source_registry.py` with new 4-arg `render_results` and 2-arg `select_handler` contracts.
Leave stubs/imports in `job_hunt_ui.py` pointing at the new location.
**Target: −650 lines from ui.py. Server stays runnable.**

### Step 2 — Extract `ui_state.py`
Move all module-level constants and `UIServerConfig` to `ui_state.py`.
Add `model_label: str` field to `UIServerConfig`.
Update all references in `job_hunt_ui.py` to import from `ui_state`.
**Target: −120 lines. Server stays runnable.**

### Step 3 — Extract `ui_utils.py`
Move all pure utility functions (escape, form helpers, format functions) to `ui_utils.py`.
**Target: −200 lines. Server stays runnable.**

### Step 4 — Extract `ui_render.py`
Move all `render_*` and `_render_*` HTML functions to `ui_render.py`.
Add `JobPageViewModel`, `ProfilePageViewModel`, `ReviewQueueViewModel` dataclasses.
For each render function that currently loads data or imports domain modules:
- Move the data load to the caller (handler)
- Add the data as an explicit parameter or view-model field
- Verify no domain import remains in `ui_render.py` after the move

The `model_label` fix: replace `src.job_hunt_llm._model` import with `config.model_label`.
**Target: −2,200 lines. Server stays runnable.**

### Step 5 — Extract `ui_handlers.py` + introduce `UIRequest` + `UIResponder`
Introduce `UIRequest` dataclass and `_parse_request()` in `ui_routes.py`.
Convert all `_handle_*` methods to standalone functions accepting `(req, config, responder)`.
Create `UIResponder` dataclass.
**In this same step:** implement `_upsert_job_to_index()` and replace all 5 copy-pasted upsert blocks — this is the safest moment because all 5 blocks move together.
Add `handle_sources()` handler for `GET /sources`.
Update `do_GET`/`do_POST` to call `_parse_request(self)` then dispatch to standalone functions.
**Target: −900 lines from the class. Server stays runnable.**

### Step 6 — Extract `ui_routes.py`
Move `_build_handler`, `_parse_request`, `JobSeekingUIHandler`, `UIRequest`, `UIResponder`, `main`, `build_parser` to `ui_routes.py`.
Reduce `job_hunt_ui.py` to the ~40-line shell with re-exports.
Verify all tests pass without modification (re-exports ensure backward compat).
**Target: Server runs via `python3 src/job_hunt_ui.py` as before.**

### Step 7 (cleanup, separate PR) — Remove backward-compat re-exports
Update all test files and importers to import from the correct new module.
Remove re-exports from the shell one by one as each test/importer is updated.
Reduce shell to ~20 lines (just `main` import and `if __name__ == "__main__"`).

---

## Line Count Projection

| File | Estimated lines | Notes |
|---|---|---|
| `job_hunt_ui.py` | ~40 | Shell + re-exports |
| `ui_state.py` | ~120 | Constants + UIServerConfig |
| `ui_utils.py` | ~200 | Pure helpers |
| `ui_render.py` | ~2,200 | All HTML generation |
| `ui_handlers.py` | ~900 | All request logic |
| `ui_routes.py` | ~200 | HTTP class + dispatch + UIRequest + UIResponder |
| `job_sources/reed_source.py` | ~650 | Reed-specific (from MT-1) |
| `source_registry.py` | ~90 | Updated 4-arg/2-arg contracts |
| **Total** | **~4,400** | Same code, organised |

`ui_render.py` will still be the largest file, but it will be a single-concern file: every line in it is HTML generation. If it grows beyond ~3,000 lines, it can be split further by feature area (`ui_render_job.py`, `ui_render_profile.py`, etc.).

---

## Test Coverage Additions (after split)

```python
# ui_render tests — pure string assertions, no server
def test_render_job_page_shows_decision_chip():
    vm = JobPageViewModel(decision="Apply", ...)
    html = render_job_page(vm)
    assert 'Apply' in html

# handler tests — UIRequest + MockResponder, no server
def test_handle_batch_evaluate_caps_at_20():
    req = UIRequest(method="POST", path="/jobs/batch-evaluate",
                    json_body={"jobs": [fake_job()] * 25}, ...)
    responder = MockResponder()
    handle_batch_evaluate(req, config=test_config, responder=responder)
    assert responder.json_sent["evaluated"] == 20

def test_handle_parse_cv_rejects_oversized_file():
    req = UIRequest(method="POST", path="/profile/parse-cv",
                    raw_body=b"x" * 6_000_000,
                    content_type="application/pdf", ...)
    responder = MockResponder()
    handle_parse_cv(req, config=test_config, responder=responder)
    assert "too large" in responder.json_sent.get("error", "")

# source tests — completely isolated
def test_reed_render_cards_fragment_offsets_ids():
    html = render_cards_fragment(results=[fake_result()], skip=10, nonce="x")
    assert 'id="jrc-10"' in html

# routes test — verify source registration is idempotent
def test_source_registration_side_effect():
    from src.job_sources import reed_source  # noqa
    from src.job_sources.source_registry import get_source
    assert get_source("reed") is not None
```

---

## Risks

| Risk | Mitigation |
|---|---|
| `render_job_page` is 1,200 lines — moving it may expose hidden side effects | Add snapshot test (assert html contains key strings) before and after; read function carefully for any hidden loads |
| Some render functions currently load data — easy to miss when splitting | Grep for domain imports inside `ui_render.py` after Step 4; the no-domain-import rule makes violations immediately visible |
| Backward-compat re-exports in shell may mask broken imports | Run the full test suite after Step 6 with re-exports in place; then remove re-exports one by one in Step 7, confirming tests still pass at each removal |
| `select_handler` signature change breaks any source that passes only `form` | MT-1 updates the contract and all existing call sites in one PR; new sources follow the 2-arg pattern from day one |
| Step 4 (render extraction) is the biggest step | Do it last of all the render functions; test the server manually on each key page after |
| `UIRequest.raw_body` for CV upload is large (up to 5 MB) | `_parse_request()` reads `raw_body` only if `Content-Type` is multipart or application/octet-stream; other requests get `raw_body=b""` |
