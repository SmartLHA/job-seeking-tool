"""Slice C (2026-07-21 search/score/filter plan): named scoring-weight
presets, persisted via atomic JSON write; corrupt/missing file falls back to
Balanced; switching preset changes the ScoringPolicy used for scoring."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.job_hunt_config import ScoringWeights
from src.job_hunt_scoring_presets import (
    DEFAULT_PRESET,
    PRESET_BALANCED,
    PRESET_SALARY_FOCUSED,
    PRESET_SKILLS_FOCUSED,
    PRESET_WEIGHTS,
    get_active_scoring_policy,
    load_preset_name,
    save_preset_name,
)


def test_all_presets_sum_to_100():
    # ScoringWeights.__post_init__ already enforces this at construction time
    # (module import would have failed otherwise) — assert it explicitly too.
    for name, weights in PRESET_WEIGHTS.items():
        assert abs(weights.total() - 100.0) < 0.01, f"{name} does not sum to 100"


def test_missing_file_falls_back_to_balanced(tmp_path: Path):
    assert load_preset_name(state_root=tmp_path) == PRESET_BALANCED == DEFAULT_PRESET


def test_corrupt_file_falls_back_to_balanced(tmp_path: Path):
    (tmp_path / "scoring_preset.json").write_text("{not valid json", encoding="utf-8")
    assert load_preset_name(state_root=tmp_path) == PRESET_BALANCED


def test_unknown_preset_name_in_file_falls_back_to_balanced(tmp_path: Path):
    (tmp_path / "scoring_preset.json").write_text('{"preset": "made_up"}', encoding="utf-8")
    assert load_preset_name(state_root=tmp_path) == PRESET_BALANCED


def test_save_then_load_round_trips(tmp_path: Path):
    save_preset_name(PRESET_SALARY_FOCUSED, state_root=tmp_path)
    assert load_preset_name(state_root=tmp_path) == PRESET_SALARY_FOCUSED


def test_save_uses_atomic_write_temp_file_not_left_behind(tmp_path: Path):
    save_preset_name(PRESET_SKILLS_FOCUSED, state_root=tmp_path)
    assert (tmp_path / "scoring_preset.json").exists()
    assert not (tmp_path / "scoring_preset.json.tmp").exists()


def test_persists_across_reload_simulating_restart(tmp_path: Path):
    save_preset_name(PRESET_SKILLS_FOCUSED, state_root=tmp_path)
    # Simulate a fresh process: load again from disk only.
    assert load_preset_name(state_root=tmp_path) == PRESET_SKILLS_FOCUSED
    policy = get_active_scoring_policy(state_root=tmp_path)
    assert policy.weights == PRESET_WEIGHTS[PRESET_SKILLS_FOCUSED]


def test_save_unknown_preset_name_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        save_preset_name("not_a_real_preset", state_root=tmp_path)


def test_switching_preset_changes_active_scoring_policy_weights(tmp_path: Path):
    balanced_policy = get_active_scoring_policy(state_root=tmp_path)
    assert balanced_policy.weights == ScoringWeights()

    save_preset_name(PRESET_SALARY_FOCUSED, state_root=tmp_path)
    salary_policy = get_active_scoring_policy(state_root=tmp_path)
    assert salary_policy.weights.salary > balanced_policy.weights.salary
    assert salary_policy.weights != balanced_policy.weights
