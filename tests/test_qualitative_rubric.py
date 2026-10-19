"""Slice 3 (2026-10-19): qualitative rubric defines every 1-5 level (no anchors)."""
from __future__ import annotations

import pytest

from src.job_hunt_profile import candidate_profile_from_dict
from src.job_hunt_qualitative import DIMENSIONS, RUBRICS, build_qualitative_prompt


def _prompt() -> str:
    profile = candidate_profile_from_dict({"candidate_id": "c1", "skills": ["sql"],
                                           "target_roles": ["Business Analyst"], "locations": ["London"]})
    return build_qualitative_prompt("We need a Business Analyst with SQL.", profile)


def test_rubric_covers_every_dimension() -> None:
    assert set(RUBRICS) == set(DIMENSIONS)


@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_every_level_has_its_own_descriptor(dimension: str) -> None:
    levels = RUBRICS[dimension]
    assert sorted(levels) == [1, 2, 3, 4, 5]
    texts = [levels[i].strip() for i in range(1, 6)]
    assert all(texts) and len(set(texts)) == 5


@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_prompt_lists_all_five_levels(dimension: str) -> None:
    prompt = _prompt()
    for level in range(1, 6):
        assert f"  {level} = {RUBRICS[dimension][level]}" in prompt


def test_prompt_has_no_old_anchor_only_rubric() -> None:
    prompt = _prompt()
    assert "3 = unclear or partial match, 5 = strong" not in prompt
    assert "do not interpolate between levels" in prompt


@pytest.mark.parametrize("dimension", ["culture_signals", "red_flags"])
def test_level_two_means_an_evidenced_concern(dimension: str) -> None:
    # derive_grade caps the grade at score <= 2, so level 2 must be a real concern.
    text = RUBRICS[dimension][2].lower()
    assert "concern" in text or "warning" in text
