# Function List

**Source-verified after recovery merge: 2026-06-22.** The current implementation is the split UI architecture below. Do not treat the previous monolithic `src/job_hunt_ui.py` description as current.

## UI architecture

| Module | Responsibility |
|---|---|
| `src/job_hunt_ui.py` | 19-line compatibility entry point, importing `main` from `ui_routes`. Run with `python3 -m src.job_hunt_ui --profile …`. |
| `src/ui_state.py` | `UIServerConfig`, UI constants, page timestamps, form/upload limits. |
| `src/ui_utils.py` | Pure sanitising, formatting, form, job-id, and nonce helpers. |
| `src/ui_render.py` | Pure HTML rendering and view models. No domain or persistence imports. |
| `src/ui_handlers.py` | Request handlers, view-model construction, persistence, evaluation, and source orchestration. |
| `src/ui_routes.py` | HTTP request parsing, responder, route dispatch, CLI/server startup. |
| `src/job_sources/source_registry.py` | Generic source registration and lookup. |
| `src/job_sources/reed_source.py` | Reed search/select/render behaviour and source registration. |

The dependency direction is `ui_routes → ui_handlers → ui_render → ui_utils ⇄ ui_state`. Domain modules are used by handlers, not renderers.

## Domain modules

| Module | Responsibility |
|---|---|
| `job_hunt_models.py` | Typed models including structured `Skill`, `JobPosting`, `JobAnalysis`, `TailoredCVResult`, ATS and keyword-match fields, and `effective_decision()`. |
| `job_hunt_scoring.py` | Seven weighted components: required skills 35, preferred skills 5, experience 20, location/salary/domain/work mode 10 each. |
| `job_hunt_evaluation.py` | Composes scoring and decisions; applies source-quality gates; populates ATS readiness and advisory keyword matching. |
| `job_hunt_keyword_match.py` | F1 per-job CV keyword coverage, required/preferred missing lists, edge-aware technical-keyword matching, and anti-stuffing signal. It never changes Apply/Review/Skip. |
| `job_hunt_validation.py` | Shared validation helpers for profile, reviewed input, and storage boundaries. |
| `job_hunt_llm.py` | Optional Gemini-backed skill extraction and structured job explanation. It cannot change deterministic scores or decisions. |
| `job_hunt_tailoring.py` / `job_hunt_cover_letter.py` | Truth-bounded CV tailoring and grounded letter generation. |
| `job_hunt_index.py` / `job_hunt_outcomes.py` | SQLite jobs/board read model and local outcome state machine. |

## Implemented HTTP surface

- Discovery: `GET /search/{source}`, `POST /select/{source}`, `GET /search/reed/more`, `GET /sources`.
- Review/evaluation: `POST /prefill`, `POST /job-submit`, `POST /evaluate`, `GET /job/<id>`, `GET /job/<id>/explain`, `POST /job/<id>/decision`.
- Document and profile actions: `POST /tailor`, `POST /cover-letter`, `POST /job/<id>/add-gap-skills`, `POST /job/<id>/ai-review-cv`, `GET /profile`, `POST /profile/parse-cv`, `POST /profile/save`.
- Board and batch flow: `GET /jobs`, `GET /board`, `GET /board/view`, `POST /jobs/save`, `POST /jobs/batch-evaluate`, `GET /review-queue`.
- Outcomes: `POST /outcome`.

## Important contracts

- Confidence is categorical: `low`, `medium`, or `high`, not a probability.
- The visible score breakdown has six buckets; its skills bucket contains two separately weighted components, so scoring has seven weights in total.
- `source_ref` retains an advert URL where available. Job pages render it as **View original posting / Apply**.
- Tailoring and cover-letter generation are local, decision-gated actions. Neither submits an application.
- Gap Coach, daily digest, broader source coverage, and DOCX/PDF output remain backlog work.
