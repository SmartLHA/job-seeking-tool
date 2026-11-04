"""Show the saved AI CV review again after a page reload (spec 2026-11-04).

Synthetic text only; tmp_path fixtures only. Writer, reviewer, Codex and network
functions are patched to fail the test if they are ever called.
"""
from __future__ import annotations

import json
import os
import re
from types import SimpleNamespace as NS
from unittest.mock import Mock
from uuid import uuid4

import pytest

from src import job_hunt_cv_review as review, job_hunt_llm as llm, ui_handlers as handlers, ui_render
from src.job_hunt_config import TailoringPolicy
from src.job_hunt_tailoring import load_latest_tailored_cv
from tests.test_ai_cv_consent import _job_html, _run_page_js
from tests.test_cover_letter import build_analysis, build_job

JOB_ID = "job-001"
MASTER = "Summary\n- Prepared useful reports."
BODY = "Summary\nRan the weekly planning meeting\nLed a team of ten\nPrepared useful reports"
PAYLOAD = "</script><script>alert(1)</script>"
IMG = "<img src=x onerror=alert(1)>"


def _item(i, text, verdict, reason):
    severity = {"SUPPORTED": None, "EXAGGERATED": "MAJOR", "UNSUPPORTED": "BLOCKER"}[verdict]
    return dict(id=f"s-{i}", block_key="Experience", text=text, removed=[], verdict=verdict,
                evidence_quote=None, reason=reason, severity=severity)


def _record(profile, body, *, items=None, l0=None, revise_round=0, approval=None):
    items = items if items is not None else [
        _item(0, "Ran the weekly planning meeting", "EXAGGERATED", "REASON_ONE"),
        _item(1, "Led a team of ten", "EXAGGERATED", "REASON_TWO"),
        _item(2, "Prepared useful reports", "SUPPORTED", "REASON_OK"),
    ]
    l0 = l0 or []
    evidence, context = review.build_review_source(profile, profile.master_cv_text)
    return dict(
        schema_version=1, generation_id=uuid4().hex,
        verdict=review.overall_verdict(l0, review.item_statuses(items)),
        l0_findings=l0, items=items, reviewer_model="checker", prompt_version=review.REVIEW_PROMPT_VERSION,
        binding=review.compute_binding(profile, profile.master_cv_text, evidence, context, body, JOB_ID),
        writer_model="writer", created_at="2026-11-04T10:15:00+00:00", revise_round=revise_round,
        approval=approval)


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile = NS(candidate_id="synthetic", master_cv_text=MASTER, master_cv_ref=None,
                 years_experience=5, skills=[NS(name="SQL")], target_roles=["Analyst"],
                 industries=["Finance"])
    out = tmp_path / "tailored"
    out.mkdir()
    monkeypatch.setattr(handlers, "DEFAULT_TAILORING_POLICY", TailoringPolicy(output_dir=out))
    monkeypatch.setattr(handlers, "load_candidate_profile", lambda *a: profile)
    forbidden = Mock(side_effect=AssertionError("cloud/network call is forbidden"))
    for mod, names in ((llm, ("ai_rewrite_cv", "_call_gemini_model", "_call_gemini_reasoning")),
                       (review, ("run_blind_review",))):
        for name in names:
            monkeypatch.setattr(mod, name, forbidden)
    env = NS(profile=profile, out=out, md=out / f"{JOB_ID}_ai_reviewed.md",
             config=NS(profile_path=tmp_path / "profile.json", state_root=tmp_path, model_label="m"),
             forbidden=forbidden)
    env.save = lambda rec=None, body=BODY, header="<!-- ai_reviewed: true | model: writer -->\n": (
        env.md.write_text(header + body + "\n"),
        review.write_review_record(out, JOB_ID, rec if rec is not None else _record(profile, body)))
    return env


def _fields(env):
    return handlers._ai_cv_saved_fields(env.config, JOB_ID)


def _page(env, **extra):
    return _job_html(**{**_fields(env), **extra})


def _saved_json(html):
    m = re.search(r'<script type="application/json" id="ai-cv-saved">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


# ---- AC1, AC1a: current NEEDS_EDIT record ----------------------------------------

def test_current_needs_edit_record_panel_after_reload(env, tmp_path):
    env.save()
    html = _page(env)
    d = _saved_json(html)
    assert d["review"]["verdict"] == "NEEDS_EDIT" and d["changes"] == []
    assert d["saved_path"] == f"{JOB_ID}_ai_reviewed.md" and d["model_used"] == "writer"
    assert d["reviewed_cv"] == BODY and d["created_at"] == "2026-11-04T10:15:00+00:00"
    assert 'id="ai-cv-stale"' not in html
    _run_page_js(tmp_path, r"""
  const t = pageText();
  assert(t.includes('NEEDS EDIT — not used until you approve it'));
  assert(t.includes('Ran the weekly planning meeting') && t.includes('REASON_ONE'));
  assert(t.includes('Led a team of ten') && t.includes('REASON_TWO'));
  assert(!t.includes('REASON_OK'), 'SUPPORTED item must not be listed');
  const flagged = all(resultDiv).filter(n => n.className.includes('ai-cv-flagged'));
  assert.strictEqual(flagged.length, 2);
  assert(findButton('Approve this rewrite') && findButton('Revise once with findings'));
  assert(t.includes('Last AI review: '));
  assert.strictEqual(calls.length, 0, 'loading a saved review must not call the server');
  assert.strictEqual(innerHtmlWrites.length, 0);
""", html=html)


def test_reloaded_panel_has_no_changes_list_and_notice_is_not_error_coloured(env, tmp_path):
    env.save()
    _run_page_js(tmp_path, r"""
  assert(!pageText().includes('Changes made'));
  const note = all(resultDiv).find(n => n.className === 'ai-cv-notice');
  assert(note && note.textContent.startsWith('Last AI review: '));
  assert(!note.style.cssText.includes('var(--skip)'));
""", html=_page(env))


# ---- AC2: approved / revised ------------------------------------------------------

def test_approved_record_shows_badge_and_no_approve_button(env, tmp_path):
    rec = _record(env.profile, BODY)
    rec["approval"] = {"approved_at": "t", "generation_id": rec["generation_id"],
                       "rewrite_sha256": rec["binding"]["rewrite_sha256"]}
    env.save(rec)
    _run_page_js(tmp_path, r"""
  assert(pageText().includes('Approved — this rewrite will be used'));
  assert(!findButton('Approve this rewrite'));
""", html=_page(env))


def test_revise_round_one_has_no_revise_button(env, tmp_path):
    env.save(_record(env.profile, BODY, revise_round=1))
    _run_page_js(tmp_path, r"""
  assert(findButton('Approve this rewrite'));
  assert(!findButton('Revise once with findings'));
""", html=_page(env))


# ---- AC3: stale record ------------------------------------------------------------

def test_stale_record_hides_panel_and_shows_one_line(env):
    env.save()
    env.profile.master_cv_text = MASTER + "\n- A new line added after the review."
    fields = _fields(env)
    assert fields == {"ai_cv_saved": None, "ai_cv_stale": True}
    html = _page(env)
    assert 'id="ai-cv-saved"' not in html
    assert "An earlier AI review of this job no longer matches your CV or profile. Click AI Review CV to review again." in html


def test_stale_when_rewrite_changed_after_review(env):
    env.save()
    env.md.write_text("<!-- h -->\nSomething else entirely\n")
    assert _fields(env)["ai_cv_stale"] is True


# ---- AC2a: render_result and render_job both embed it ------------------------------

def _patch_pages(monkeypatch):
    monkeypatch.setattr(handlers, "load_reviewed_job", lambda *a, **k: build_job())
    monkeypatch.setattr(handlers, "load_job_analysis", lambda *a, **k: build_analysis())
    monkeypatch.setattr(handlers, "load_application_outcome", lambda *a, **k: None)
    monkeypatch.setattr(handlers, "_upsert_job_to_index", lambda *a, **k: None)
    monkeypatch.setattr(handlers, "_ensure_qualitative_grade", lambda c, j, an, qa, qi: (None, None, None))
    monkeypatch.setattr(handlers, "_index_db_path", lambda c: c.state_root / "missing.db")


def test_render_result_and_render_job_both_embed_saved_review(env, monkeypatch):
    _patch_pages(monkeypatch)
    env.save()
    sent = []
    responder = NS(send_html=lambda page, **k: sent.append(page), redirect=Mock())
    handlers.render_result(NS(), env.config, responder, NS(reviewed_job=build_job(), analysis=build_analysis()))
    handlers.render_job(NS(path="/job/job-001"), env.config, responder, JOB_ID)
    assert len(sent) == 2
    for page in sent:
        assert 'id="ai-cv-saved"' in page and "ai-cv-btn" in page
        assert _saved_json(page)["review"]["verdict"] == "NEEDS_EDIT"


# ---- AC4: every failure renders the plain page --------------------------------------

def _assert_plain(env):
    assert _fields(env) == {"ai_cv_saved": None, "ai_cv_stale": False}
    html = _page(env)
    assert 'id="ai-cv-saved"' not in html and 'id="ai-cv-stale"' not in html
    assert "no longer matches" not in html


def test_no_record(env):
    _assert_plain(env)


def test_invalid_json_record(env):
    env.save()
    review.review_record_path(env.out, JOB_ID).write_text("{not json")
    _assert_plain(env)


def test_record_failing_validation(env):
    rec = _record(env.profile, BODY)
    rec["verdict"] = "PASS"  # inconsistent with its items
    env.save(rec)
    _assert_plain(env)


def test_symlinked_record(env, tmp_path):
    env.save()
    path = review.review_record_path(env.out, JOB_ID)
    target = tmp_path / "elsewhere.json"
    path.rename(target)
    os.symlink(target, path)
    _assert_plain(env)


def test_missing_md_file(env):
    env.save()
    env.md.unlink()
    _assert_plain(env)


def test_symlinked_md_file(env, tmp_path):
    env.save()
    target = tmp_path / "elsewhere.md"
    env.md.rename(target)
    os.symlink(target, env.md)
    _assert_plain(env)


def test_profile_fails_to_load(env, monkeypatch):
    env.save()
    monkeypatch.setattr(handlers, "load_candidate_profile", Mock(side_effect=ValueError("bad profile")))
    _assert_plain(env)


@pytest.mark.parametrize("how", ["missing", "unreadable"])
def test_master_cv_missing_or_unreadable(env, tmp_path, how):
    env.save()
    env.profile.master_cv_text = None
    env.profile.master_cv_ref = "master.txt"
    if how == "unreadable":
        (tmp_path / "master.txt").write_bytes(b"\xff\xfe\x00bad")
        (tmp_path / "master.txt").chmod(0)
    try:
        _assert_plain(env)
    finally:
        if how == "unreadable":
            (tmp_path / "master.txt").chmod(0o644)


def test_unexpected_exception_in_helper(env, monkeypatch):
    env.save()
    monkeypatch.setattr(review, "read_review_record", Mock(side_effect=RuntimeError("boom")))
    _assert_plain(env)


# ---- AC5: injection ---------------------------------------------------------------

def test_injection_text_is_never_raw_in_page_html(env, tmp_path):
    bad = PAYLOAD + IMG
    body = f"Summary\n{bad}\nPrepared useful reports"
    items = [_item(0, bad, "EXAGGERATED", bad), _item(1, "Prepared useful reports", "SUPPORTED", "ok")]
    l0 = [dict(layer=0, rule="L0-1", text=bad, severity="MAJOR", detail=bad, item_id=None, cleared_by=None)]
    env.save(_record(env.profile, body, items=items, l0=l0), body=body)
    html = _page(env)
    data = re.search(r'<script type="application/json" id="ai-cv-saved">(.*?)</script>', html, re.S).group(1)
    assert "</script" not in data and "<img" not in data and "<" not in data and ">" not in data
    assert html.count("<script>alert(1)") == 0 and "<img src=x" not in html
    _run_page_js(tmp_path, r"""
  const t = pageText();
  assert(t.includes('</script><script>alert(1)</script>'));
  assert(t.includes('<img src=x onerror=alert(1)>'));
  assert.strictEqual(innerHtmlWrites.length, 0);
""", html=html)


def test_script_still_has_no_inner_html():
    assert "innerHTML" not in ui_render._AI_CV_SCRIPT


# ---- AC6: read-only, no cloud call --------------------------------------------------

def test_page_render_calls_nothing_and_changes_no_file(env, monkeypatch):
    _patch_pages(monkeypatch)
    env.save()
    record_path = review.review_record_path(env.out, JOB_ID)
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (record_path, env.md)]
    responder = NS(send_html=Mock(), redirect=Mock())
    handlers.render_job(NS(path="/job/job-001"), env.config, responder, JOB_ID)
    handlers.render_result(NS(), env.config, responder, NS(reviewed_job=build_job(), analysis=build_analysis()))
    assert responder.send_html.call_count == 2
    env.forbidden.assert_not_called()
    assert before == [(p.read_bytes(), p.stat().st_mtime_ns) for p in (record_path, env.md)]
    assert sorted(p.name for p in env.out.iterdir()) == sorted([record_path.name, env.md.name])


# ---- AC7: approve from the reloaded panel --------------------------------------------

def test_approve_with_embedded_ids_returns_200_and_rewrite_becomes_the_cv(env):
    env.save(header="<!-- profile_id: synthetic -->\n")
    d = _saved_json(_page(env))
    sent = NS(send_json=Mock())
    handlers.handle_ai_review_cv_approve(
        NS(json_body={"generation_id": d["generation_id"], "rewrite_sha256": d["rewrite_sha256"]}),
        env.config, sent, JOB_ID)
    args, kw = sent.send_json.call_args
    assert kw.get("status", 200) == 200 and args[0]["ok"] is True
    got = load_latest_tailored_cv(JOB_ID, expected_profile_id="synthetic", profile=env.profile,
                                  base_dir=env.config.profile_path.parent,
                                  policy=TailoringPolicy(output_dir=env.out))
    assert got == BODY
    env.forbidden.assert_not_called()
