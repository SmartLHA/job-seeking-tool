# CI fix: flake8 RecursionError on src/ui_render.py — 2026-09-21

CI (.github/workflows/python-app.yml, Python 3.10, `flake8 . --count --select=E9,F63,F7,F82`) fails: `./src/ui_render.py: "pyflakes[F]" failed during execution due to RecursionError`. It failed on d25394e too, so it predates the audit fixes. Later CI step is `PYTHONPATH=. pytest` (never reached yet). main has also been red since 2026-07-09.

Goal: CI's lint step passes and pytest step passes on Python 3.10, without changing any rendered HTML.

Steps:
1. Reproduce. Try `uv venv --python 3.10 <scratch>/py310` (or any python3.10 you can get); create ALL scratch envs under the scratchpad /private/tmp/claude-502/-Users-lhaclaw-AI-Project-Workspace-job-hunt-Job-Seeking-Tool/9214229d-aa47-4e1a-89fc-044c1efd665f/scratchpad, NOT in the repo, and install flake8, pytest plus requirements-dev.txt there. Run the exact CI flake8 commands. If 3.10 is unobtainable, use the repo venv's python 3.14 with flake8 in a scratch venv and lower sys.setrecursionlimit to reproduce; say which.
2. Find the cause: the deepest AST construct in src/ui_render.py (very long `a + b + c ...` string concat chains, deeply nested expressions). Measure AST depth per file to confirm it is an outlier. Fix by restructuring (e.g. build with "".join([...]) or a list of parts, or split into helper functions) so output is BYTE-IDENTICAL. Prove it: before editing, render a set of pages (home tabs, job detail with a sample job, digest, profile, review queue, board, batch) via the project's own render functions/test helpers into files; after editing, diff = empty.
3. Run the CI commands again (E9,F63,F7,F82 must give 0 and exit 0; whole-repo `flake8 .` must not crash on any file). Also run `PYTHONPATH=. pytest` under Python 3.10 if you got one: fix real 3.10-incompatibilities in src/ (e.g. 3.12-only syntax such as nested same-quote f-strings, `type` statements, PEP 695) minimally; do not weaken or skip tests. If a test fails ONLY because of missing optional infra (e.g. Playwright not installed in CI), report it and do not hack around it.
4. Backup each edited file to backups/ first. Do not commit, do not push. Nothing new at the repo root; scratch stays in scratchpad.
Also report: what else the whole-repo flake8 E9/F63/F7/F82 pass finds.
AC: pasted flake8 output (count 0), byte-identical render diff empty, pytest tally on 3.10 (or on venv 3.14 if 3.10 unobtainable) with 0 failed, `venv/bin/python -m pytest tests/ -q` still 1021 passed / 5 skipped.
