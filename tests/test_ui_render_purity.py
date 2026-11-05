"""ui_render stays pure (2026-10-19): no src.job_hunt_* imports anywhere in the
module, and the ui_utils display copies match the domain originals."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.job_hunt_salary_benchmark import _POSITION_LABELS, market_badge_text
from src.job_hunt_scoring_presets import PRESET_LABELS
from src.ui_utils import MARKET_POSITION_LABELS, SCORING_PRESET_LABELS, market_badge_display


def test_ui_render_has_no_domain_imports_anywhere() -> None:
    tree = ast.parse(Path("src/ui_render.py").read_text(encoding="utf-8"))
    imported = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
    imported += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [m for m in imported if m.startswith("src.job_hunt_")], imported


def test_preset_labels_copy_matches_domain() -> None:
    assert SCORING_PRESET_LABELS == PRESET_LABELS


def test_market_position_labels_copy_matches_domain() -> None:
    assert MARKET_POSITION_LABELS == _POSITION_LABELS


@pytest.mark.parametrize("snapshot", [
    None, {}, {"position": "unknown"}, {"position": "bottom"},
    {"position": "bottom", "sample_total": 100, "histogram_date": "2026-09-20T10:00:00+00:00"},
    {"position": "typical", "sample_total": 0, "histogram_date": ""},
    {"position": "top", "sample_total": None, "histogram_date": None},
    {"position": "top", "sample_total": 31, "histogram_date": "2026-10-01"},
])
def test_market_badge_display_matches_domain(snapshot) -> None:
    assert market_badge_display(snapshot) == market_badge_text(snapshot)
