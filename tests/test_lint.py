"""Lint gate — keep pyflakes findings at the known-benign baseline.

Added after the 2026-06-19 post-refactor lint sweep (see
`docs/code-review-2026-06-19.md`). Fails if `pyflakes` reports anything outside the
small allowlist below, so unused imports / dead code / undefined names cannot
silently reaccumulate. Skips cleanly if pyflakes is not installed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# (path-suffix, message-substring) pairs that are intentionally left — see the
# code review's "Resolution" section:
#  - cosmetic f-strings inside multi-line embedded-JS blocks (escaped braces, no
#    real placeholders; render identically to plain strings)
#  - the reed_source registration import in ui_routes (a deliberate import-time
#    side effect; annotated `# noqa: F401`, which pyflakes does not read)
_ALLOWED = (
    ("src/ui_render.py", "f-string is missing placeholders"),
    ("src/ui_routes.py", "imported but unused"),
)


def test_no_unexpected_pyflakes_findings() -> None:
    pytest.importorskip("pyflakes")
    files = [str(p.relative_to(_ROOT)) for p in sorted((_ROOT / "src").rglob("*.py"))]
    proc = subprocess.run(
        [sys.executable, "-m", "pyflakes", *files],
        cwd=_ROOT, capture_output=True, text=True,
    )
    findings = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    unexpected = []
    for line in findings:
        # format: "path:line:col: message"
        parts = line.split(":", 3)
        path = parts[0]
        message = parts[3].strip() if len(parts) >= 4 else line
        if not any(path.endswith(ap) and sub in message for ap, sub in _ALLOWED):
            unexpected.append(line)
    assert not unexpected, (
        "Unexpected pyflakes findings (clean them or add to the allowlist):\n"
        + "\n".join(unexpected)
    )
