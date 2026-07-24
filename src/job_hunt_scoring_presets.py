"""Named scoring-weight presets (Slice C, 2026-07-21 search/score/filter
plan: docs/tasks/2026-07-21-search-score-filter-plan.md).

Locked decision (Mike, 2026-07-21): three fixed presets only — Balanced
(today's default weights, unchanged), Salary-focused, Skills-focused. No
free-form 7-number editor in v1. The chosen preset persists across restart
via an atomic JSON write (temp file + os.replace); a missing or corrupt file
falls back to Balanced without crashing the app. Each preset's
``ScoringWeights`` still goes through the existing sum-to-100 validation in
``ScoringWeights.__post_init__`` — a broken preset definition fails loudly at
import time rather than silently miscoring every job.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from src.job_hunt_config import DEFAULT_SCORING_POLICY, ScoringPolicy, ScoringWeights

PRESET_BALANCED = "balanced"
PRESET_SALARY_FOCUSED = "salary_focused"
PRESET_SKILLS_FOCUSED = "skills_focused"

DEFAULT_PRESET = PRESET_BALANCED

# Each preset's ScoringWeights must sum to 100 (enforced by
# ScoringWeights.__post_init__ at import time).
PRESET_WEIGHTS: dict[str, ScoringWeights] = {
    # Unchanged from today's DEFAULT_SCORING_POLICY.weights so nothing
    # changes for Mike until he explicitly switches presets.
    PRESET_BALANCED: ScoringWeights(),
    PRESET_SALARY_FOCUSED: ScoringWeights(
        skills_required=25.0,
        skills_preferred=5.0,
        experience=15.0,
        location=10.0,
        salary=25.0,
        domain=10.0,
        work_mode=10.0,
    ),
    PRESET_SKILLS_FOCUSED: ScoringWeights(
        skills_required=45.0,
        skills_preferred=10.0,
        experience=15.0,
        location=10.0,
        salary=5.0,
        domain=5.0,
        work_mode=10.0,
    ),
}

PRESET_LABELS: dict[str, str] = {
    PRESET_BALANCED: "Balanced",
    PRESET_SALARY_FOCUSED: "Salary-focused",
    PRESET_SKILLS_FOCUSED: "Skills-focused",
}

_LOCK = threading.Lock()
_FILENAME = "scoring_preset.json"


def _preset_file(state_root: str | Path) -> Path:
    return Path(state_root) / _FILENAME


def load_preset_name(*, state_root: str | Path) -> str:
    """Return the persisted preset name.

    Falls back to Balanced (without raising) when the file is missing,
    unreadable/corrupt JSON, or names a preset that no longer exists."""
    path = _preset_file(state_root)
    if not path.exists():
        return DEFAULT_PRESET
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        name = data.get("preset") if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return DEFAULT_PRESET
    if not isinstance(name, str) or name not in PRESET_WEIGHTS:
        return DEFAULT_PRESET
    return name


def save_preset_name(name: str, *, state_root: str | Path) -> None:
    """Persist the chosen preset via atomic write: write to a temp file in
    the same directory, fsync, then os.replace over the real path — so a
    crash mid-write never leaves a half-written/corrupt preset file."""
    if name not in PRESET_WEIGHTS:
        raise ValueError(f"Unknown scoring preset: {name!r}")
    path = _preset_file(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with _LOCK:
        try:
            encoded = json.dumps({"preset": name}, ensure_ascii=False, indent=2).encode("utf-8")
            with open(tmp_path, "wb") as fh:
                fh.write(encoded)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass


def get_active_scoring_policy(*, state_root: str | Path) -> ScoringPolicy:
    """Return the ScoringPolicy for the currently persisted preset.

    Only the weights vary by preset; confidence thresholds and credit ratios
    stay at DEFAULT_SCORING_POLICY's values regardless of preset."""
    name = load_preset_name(state_root=state_root)
    weights = PRESET_WEIGHTS[name]
    return ScoringPolicy(
        weights=weights,
        confidence=DEFAULT_SCORING_POLICY.confidence,
        partial_experience_credit_ratio=DEFAULT_SCORING_POLICY.partial_experience_credit_ratio,
        work_mode_unknown_ratio=DEFAULT_SCORING_POLICY.work_mode_unknown_ratio,
        domain_unknown_ratio=DEFAULT_SCORING_POLICY.domain_unknown_ratio,
    )
