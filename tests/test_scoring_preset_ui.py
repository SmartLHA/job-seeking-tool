"""Slice C UI wiring (2026-07-21 search/score/filter plan): POST /scoring-
preset persists the choice and the My Profile page renders/selects it;
switching preset changes the ScoringPolicy used by the evaluation flow."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

from src.ui_state import UIServerConfig
from src.ui_routes import _build_handler
from src.job_hunt_scoring_presets import (
    PRESET_BALANCED,
    PRESET_SALARY_FOCUSED,
    load_preset_name,
)


def _write_profile(tmp_path: Path) -> Path:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "docs").mkdir(parents=True, exist_ok=True)
    (profile_dir / "docs" / "master_cv.md").write_text("# Master CV\n", encoding="utf-8")
    profile_path = profile_dir / "candidate_profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "candidate_id": "cand-001",
                "name": "Mic",
                "target_roles": ["Business Analyst"],
                "locations": ["London"],
                "remote_preference": "remote_friendly",
                "salary_floor_gbp": 50000,
                "right_to_work_uk": True,
                "skills": ["Stakeholder Management", "Process Mapping", "SQL"],
                "years_experience": 5,
                "industries": ["finance"],
                "achievements": ["Improved reporting workflow"],
                "certifications": ["BCS Foundation"],
                "master_cv_ref": "docs/master_cv.md",
            }
        ),
        encoding="utf-8",
    )
    return profile_path


@contextmanager
def _running_ui_server(tmp_path: Path):
    profile_path = _write_profile(tmp_path)
    config = UIServerConfig(
        profile_path=profile_path,
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
        host="127.0.0.1",
        port=0,
    )
    server = ThreadingHTTPServer((config.host, config.port), _build_handler(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", config
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _http_get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _http_post_form(url: str, form: dict[str, str]) -> tuple[int, str]:
    data = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_profile_page_shows_balanced_selected_by_default(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        status, body = _http_get(f"{base_url}/profile?profile_id={config.profile_path.stem}")

    assert status == 200
    assert "Scoring weights" in body
    assert 'value="balanced" selected' in body


def test_post_scoring_preset_persists_and_redirects(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        status, body = _http_post_form(
            f"{base_url}/scoring-preset",
            {"preset": "salary_focused", "profile_id": config.profile_path.stem},
        )
        assert status == 200
        assert "Salary-focused" in body
        assert 'value="salary_focused" selected' in body

    assert load_preset_name(state_root=config.state_root) == PRESET_SALARY_FOCUSED


def test_unknown_preset_name_does_not_crash_or_change_state(tmp_path: Path) -> None:
    with _running_ui_server(tmp_path) as (base_url, config):
        status, body = _http_post_form(
            f"{base_url}/scoring-preset",
            {"preset": "made_up_preset", "profile_id": config.profile_path.stem},
        )
        assert status == 200
        assert "Unknown scoring preset" in body

    assert load_preset_name(state_root=config.state_root) == PRESET_BALANCED
