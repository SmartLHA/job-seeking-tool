# Feature C: Export application package (zip) — 2026-09-22

<!-- STATUS -->
> **2026-10-04 repair status: ⚠️ Implemented; independent verification partial/pending.** ZIP uses the active profile identity for both CV and letter; missing/legacy letters are missing components, not guessed.
> **Repair functions:** `build_package`, `load_cover_letter`, `load_latest_tailored_cv`. **Routes:** `GET /job/{id}/export.zip`.
> **Verification:** Producer synthetic checks are recorded in [the audit evidence](audit-remediation-2026-10-04.md); live provider/browser/real-data behavior is not certified. Issue 16 remains pending.
<!-- /STATUS -->

Mike approved building (2026-09-22, "do 2-4"). Origin: PROJECT_CONTEXT.md ~143 (packaging/export), PROJECT_TODO.md F4.

## Verified facts
- Tailored CV: `save_tailored_cv` writes output/tailored_cvs/{job_id}.md (first line header `<!-- profile_id: X -->`); AI-reviewed CV is {job_id}_ai_reviewed.md; `load_latest_tailored_cv(job_id, *, expected_profile_id=None, policy)` (src/job_hunt_tailoring.py ~40-85) prefers the AI-reviewed file, strips the header, returns None if none, raises EmptyTailoredCVError / ValueError (bad id); has allow-list regex `^[A-Za-z0-9._-]+$` (~:27) and a resolved-parent check.
- Cover letter: `save_cover_letter(job_id, letter, profile_id)` stores plain text at `output/cover_letters/{profile_id}/{job_id}.txt`; `load_cover_letter(job_id, base_dir=None, *, profile_id=None)` requires the matching profile and safely returns missing for legacy/unmatched letters.
- `job_hunt_export.render_analysis_md` produces package analysis markdown; `UIResponder.send_bytes` serves the ZIP. Export loads profile-specific components and reports missing ones.
- Setup uses `requirements-dev.txt`, including pypdf and python-docx for CV text extraction. ZIP export packages existing markdown/text components; it does not create PDF/DOCX application documents.
- output/tailored_cvs, output/cover_letters, data/state/raw_inputs are gitignored and personal.

State-loader ID/path validation is outside the permitted repair range and remains **UNVERIFIED** in this review; independent runtime enforcement is not established.

## Smallest useful flow
On the job detail page add a "Download package" button (near Tailor/AI-review/Cover letter, ui_render.py ~1460-1480) linking to `GET /job/{id}/export.zip`. The zip (stdlib zipfile, in memory) contains fixed entry names only:
- `README.txt` / manifest: job title, company, generated date, list of files included and files MISSING (e.g. "cover_letter.txt: not generated yet") — a missing part must give a partial bundle, never an error (error only if the job itself does not exist);
- `cv.md` (latest tailored/AI-reviewed CV via load_latest_tailored_cv with expected_profile_id = current profile id; if profile mismatch, treat as missing and say so in the manifest);
- `cover_letter.txt` (`load_cover_letter(job_id, profile_id=current_profile_id)` uses the shared save/load directory and requires the active profile identity; missing, unmatched or legacy letters are reported as missing, with no legacy fallback);
- `analysis.md` (hand-built markdown from the JobAnalysis + qualitative assessment: decision, score, grade, matched/missing required skills, blockers, risk flags, qualitative summary if present; text escaped only where markdown needs it; no raw_inputs);
- `job.json` (the reviewed job JSON: title, company, location, salary, description text, source URL).
Never include: .env, profile personal fields, raw_inputs, other jobs. Download filename: `application-package-<safe-slug>.zip`, slug from job_id after validation (never from raw title/company); `Content-Disposition: attachment; filename="..."` with only [A-Za-z0-9._-]; header injection impossible.

## Requirements
1. `UIResponder.send_bytes(status, data, content_type, headers=None)` (or send_file) in src/ui_routes.py, with tests (src/ui_routes.py test style: tests/test_ui_routes_uncovered.py).
2. New module `src/job_hunt_export.py`: pure function `build_package(job_id, profile, ...) -> (bytes, manifest)`; validate job_id with the allow-list regex first; all file access under expected base dirs; deterministic entry names; unit-testable with tmp dirs.
3. Route `GET /job/{id}/export.zip` + handler in src/ui_handlers.py: 400 bad id, 404 unknown job, 200 zip otherwise. It must work for Skip/Apply/Review jobs alike (no gating; Tailor's gating does not apply to a read-only export).
4. UI button in ui_render.py (plain link with download attribute is enough); keep ui_render.py free of giant `+` string chains.

## Acceptance criteria
- tests/test_export_bundle.py: zip contents for full / CV-only / nothing-generated cases (manifest lists missing files, zipfile.testzip() is None); traversal ids (`../x`, `a/b`, empty, very long) rejected with 400 and no file access (assert via monkeypatched loaders not called); profile-mismatch CV treated as missing; secrets never in the zip (create a fake .env and raw_inputs file, assert absent); Content-Disposition safe; cover-letter save/load round trip from a tmp cwd; route status codes; job page contains the button.
- Manually open one generated zip in the test with zipfile and check analysis.md text against a fixture analysis.
- Existing tests pass: `venv/bin/python -m pytest tests/ -q` 0 failed; py310 flake8 gate `--select=E9,F63,F7,F82` -> 0.
- Docs: INDEX.md (files, tests, Feature Map), PROJECT_TODO.md F4 done with date, docs/function_list.md, PROJECT_CONTEXT.md packaging note, docs/user_flow.md.
Rules: backup edited files first; no commit; no pip install; do not touch ~/.openclaw or port 8765.
