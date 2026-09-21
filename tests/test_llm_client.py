"""Tests for the Gemini client hardening (timeout fall-through + max_output_tokens
cap that stops Gemini-3 indefinite hangs)."""
from __future__ import annotations

import requests

import src.job_hunt_llm as L


class _OKResp:
    status_code = 200
    ok = True

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": '{"fit":"good","risk":"low","action":"apply"}'}]}}]}


def test_reasoning_falls_through_on_timeout(monkeypatch):
    """A timeout on the thinking models must fall through to the no-thinking
    fallback (which succeeds), instead of aborting the whole explanation."""
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    calls = []

    def fake_post(url, params=None, json=None, timeout=None):
        calls.append(json["generationConfig"])
        if len(calls) < 3:                       # primary + fallback1 time out
            raise requests.exceptions.Timeout()
        return _OKResp()                          # fallback2 (no thinking) responds

    monkeypatch.setattr(L.requests, "post", fake_post)
    raw, err, model, all_rl = L._call_gemini_reasoning("prompt")
    assert raw is not None                        # got a result via fall-through
    assert len(calls) == 3                        # tried all three models
    assert model == L._ANALYSIS_FALLBACK_2
    assert all_rl is False                        # a timeout is NOT "all rate limited"


def test_every_request_caps_output_tokens(monkeypatch):
    """Gemini 3 hangs without max_output_tokens — every call must set it."""
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    seen = []

    def fake_post(url, params=None, json=None, timeout=None):
        seen.append(json["generationConfig"])
        return _OKResp()

    monkeypatch.setattr(L.requests, "post", fake_post)
    L._call_gemini_reasoning("p")                 # reasoning path
    L._call_gemini("p")                           # skill-extraction path
    assert seen and all("maxOutputTokens" in gc for gc in seen)


def test_timeout_not_misread_as_rate_limited(monkeypatch):
    """All models timing out must NOT raise RateLimited (it's not a 429)."""
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    monkeypatch.setattr(L.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.Timeout()))

    class O:
        skills = []; years_experience = 5; salary_floor_gbp = 50000
        remote_preference = "remote"; target_roles = ["BA"]; industries = ["finance"]
        job_title = "BA"; company = "Co"; location = "London"
        salary_min_gbp = 50000; salary_max_gbp = 60000
        required_skills = ["python"]; preferred_skills = []
        description_raw = "d"; match_score = 80; decision = "apply"
        blockers = []; strengths = []; missing_required_skills = []; missing_preferred_skills = []

    res, err = L.explain_job_match_with_llm(O(), O(), O(), raise_on_rate_limit=True)
    assert res is None and "timed out" in (err or "")   # returned, not raised
