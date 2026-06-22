"""Job Seeking Tool — UI entry point (thin shell after the LT-1 split).

Run: ``python3 -m src.job_hunt_ui --profile … [--host] [--port] [--state-root]``

The implementation lives in focused layers (import direction flows downward):

  ui_routes.py    — HTTP server, request dispatch, UIRequest/UIResponder, main
  ui_handlers.py  — request handler functions (load/validate/save/respond)
  ui_render.py    — pure HTML rendering (data in, string out)
  ui_utils.py     — shared pure helpers and form utilities
  ui_state.py     — constants and UIServerConfig
  job_sources/    — one self-contained module per job board (reed_source, …)
"""
from __future__ import annotations

from src.ui_routes import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
