# Viewer: dangling job_hunt_paste_ui.py reference — 2026-09-20

Problem: viewer/viewer_server.py `_import_ui_module()` (~line 2001) loads `src/job_hunt_paste_ui.py`, deleted on 2026-09-20 (it was already a docstring-only stub at HEAD, so the handlers at ~2018, 2037, 2055 that use it were already broken). Goal: the viewer must no longer reference a missing file, and those three handlers must work against the real current code.

Steps: (1) read the function and the three callers; find which real module now provides the functionality they expect (likely src/job_hunt_ui.py shim -> src/ui_handlers.py / ui_render.py / ui_routes.py); (2) repoint or rewrite the loader and callers to that real module; (3) if a handler's functionality no longer exists anywhere, make it return a clear HTTP error message instead of crashing, and report that in STATUS.

AC: grep -rn "job_hunt_paste_ui" viewer/ src/ tests/ returns nothing; each of the three viewer handlers is exercised (via existing viewer tests or a new small test in tests/) and returns a non-crashing response; `python3 -m pytest tests/ -q` tally is not worse than baseline 10 failed / 1029 passed / 1 skipped (10 = bs4/dotenv missing). Back up every edited file into backups/ (timestamped). Do not commit. Do not touch swarm/session_guard/shared_bus.
