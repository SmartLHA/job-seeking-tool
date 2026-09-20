"""F1 (audit 2026-09-20): cover-letter form options must match what the generator accepts."""

from __future__ import annotations

import json
import re
from http import HTTPStatus
from types import SimpleNamespace

import pytest

from src import ui_handlers
from src.job_hunt_cover_letter import _VALID_LENGTHS, _VALID_TONES
from src.ui_render import JobPageViewModel, render_job_page
from tests.test_cover_letter import build_analysis, build_job, build_profile


def _vm() -> JobPageViewModel:
    values = {}
    import dataclasses

    for f in dataclasses.fields(JobPageViewModel):
        t = str(f.type)
        if t.startswith("list"):
            values[f.name] = []
        elif t.startswith("bool"):
            values[f.name] = False
        elif t.startswith("str") and "None" not in t:
            values[f.name] = ""
        else:
            values[f.name] = None
    values.update(
        job_id="job-001", job_title="BA", company="Example Co", has_analysis=True,
        match_score=85.0, confidence="high", decision="apply", effective_decision="apply",
        flash_kind="info", model_label="m", source_type="copied_text",
    )
    return JobPageViewModel(**values)


def _select_options(html: str, name: str) -> tuple[list[str], list[str]]:
    m = re.search(rf'<select name="{name}".*?</select>', html, re.S)
    assert m, f"select {name} not rendered"
    opts = re.findall(r'<option value="([^"]+)"( selected)?', m.group(0))
    return [v for v, _ in opts], [v for v, sel in opts if sel]


def test_form_options_equal_valid_sets() -> None:
    html = render_job_page(_vm())
    tones, tone_sel = _select_options(html, "tone")
    lengths, length_sel = _select_options(html, "length")
    assert set(tones) == _VALID_TONES and len(tones) == len(_VALID_TONES)
    assert set(lengths) == _VALID_LENGTHS and len(lengths) == len(_VALID_LENGTHS)
    assert tone_sel == ["professional"]
    assert length_sel == ["standard"]
    assert 'fd.get("length")||"standard"' in html
    assert 'fd.get("tone")||"professional"' in html


class _Resp:
    def __init__(self) -> None:
        self.json_sent = None
        self.last_status = HTTPStatus.OK

    def send_json(self, payload, status=HTTPStatus.OK) -> None:
        self.json_sent = payload
        self.last_status = status


def _tones_lengths_from_form() -> list[tuple[str, str]]:
    html = render_job_page(_vm())
    tones, _ = _select_options(html, "tone")
    lengths, _ = _select_options(html, "length")
    return [(t, l) for t in tones for l in lengths]


@pytest.mark.parametrize("tone,length", _tones_lengths_from_form())
def test_every_form_value_accepted_by_handler(tone, length, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ui_handlers, "load_job_analysis", lambda *a, **k: build_analysis())
    monkeypatch.setattr(ui_handlers, "load_reviewed_job", lambda *a, **k: build_job())
    monkeypatch.setattr(ui_handlers, "load_candidate_profile", lambda *a, **k: build_profile(master_cv_text="CV text"))
    body = json.dumps({"job_id": "job-001", "why_company_text": "Great culture.", "tone": tone, "length": length})
    req = SimpleNamespace(raw_body=body.encode())
    config = SimpleNamespace(state_root=tmp_path, profile_path=tmp_path / "p.json")
    resp = _Resp()
    ui_handlers.handle_cover_letter(req, config, resp)
    assert resp.last_status == HTTPStatus.OK, resp.json_sent
    assert "letter" in resp.json_sent
