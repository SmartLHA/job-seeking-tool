"""CV persistence uses synthetic roots and never writes through symlinks."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import job_hunt_cv_storage, job_hunt_llm, ui_handlers
from src.job_hunt_config import TailoringPolicy
from src.job_hunt_cv_storage import write_cv_text
from src.job_hunt_profile import candidate_profile_from_dict, save_candidate_profile
from src.job_hunt_tailoring import save_tailored_cv


@pytest.fixture
def profile_env(tmp_path, monkeypatch):
    root = tmp_path / "profiles"
    directory = root / "synthetic"
    (directory / "docs").mkdir(parents=True)
    legacy = directory / "docs" / "previous.txt"
    legacy.write_text("Previous synthetic CV", encoding="utf-8")
    profile = candidate_profile_from_dict({
        "candidate_id": "synthetic", "master_cv_text": "Previous synthetic CV", "master_cv_ref": str(legacy),
    })
    config = SimpleNamespace(profile_path=tmp_path / "startup.json", state_root=tmp_path / "state")
    canonical = directory / "candidate_profile.json"
    save_candidate_profile(profile, canonical)
    save_candidate_profile(profile, config.profile_path)
    monkeypatch.setattr(ui_handlers, "_DATA_ROOT", root)
    monkeypatch.setattr(ui_handlers, "_ALLOWED_PROFILE_ROOTS", [])
    provider = Mock(side_effect=AssertionError("No external provider allowed"))
    monkeypatch.setattr(job_hunt_llm, "extract_cv_skills_with_llm", provider)
    return config, directory, {p: p.read_bytes() for p in (canonical, config.profile_path)}, provider


@pytest.mark.parametrize("writer", ["upload", "explicit"])
@pytest.mark.parametrize("symlink_kind", ["leaf", "nested", "inward"])
def test_master_cv_writers_reject_symlinks_without_profile_changes(
    profile_env, tmp_path, monkeypatch, writer, symlink_kind
):
    config, directory, before, provider = profile_env
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "master_cv.txt"
    sentinel.write_text("Outside sentinel", encoding="utf-8")
    if symlink_kind == "nested":
        (directory / "docs" / "previous.txt").unlink()
        (directory / "docs").rmdir()
        (directory / "docs").symlink_to(outside, target_is_directory=True)
    else:
        target = sentinel
        if symlink_kind == "inward":
            target = directory / "docs" / "previous.txt"
        (directory / "docs" / "master_cv.txt").symlink_to(target)
    responder = SimpleNamespace(send_json=Mock(), redirect=Mock())
    if writer == "upload":
        monkeypatch.setattr(ui_handlers, "parse_multipart_form", lambda req: {
            "cv_file": {"filename": "synthetic.txt", "content": b"New synthetic SQL CV"},
            "profile_id": {"content": b"synthetic"},
        })
        monkeypatch.setattr(ui_handlers, "parse_cv_file", lambda path: "New synthetic SQL CV")
        ui_handlers.handle_parse_cv(SimpleNamespace(headers={"Content-Type": "multipart/form-data"}), config, responder)
        response = responder.send_json.call_args.args[0]
        assert response["ok"] is True and response["auto_saved"] is False
        assert response["auto_save_error"]
    else:
        ui_handlers.handle_save_profile(SimpleNamespace(form={
            "profile_id": "synthetic", "master_cv_text": "New synthetic SQL CV", "name": "Unsaved name",
        }), config, responder)
        assert responder.send_json.call_args.kwargs["status"] == 400
        responder.redirect.assert_not_called()
    assert sentinel.read_text() == "Outside sentinel"
    for path, content in before.items():
        assert path.read_bytes() == content
    if symlink_kind != "nested":
        assert (directory / "docs" / "previous.txt").read_text() == "Previous synthetic CV"
    provider.assert_not_called()


@pytest.mark.parametrize("kind", ["leaf", "directory"])
def test_ordinary_tailor_rejects_output_symlinks(tmp_path, kind):
    output = tmp_path / "tailored"
    output.mkdir()
    sentinel = tmp_path / "outside.md"
    sentinel.write_text("Outside sentinel", encoding="utf-8")
    destination = output / "job-1.md"
    if kind == "leaf":
        destination.symlink_to(sentinel)
    else:
        destination.mkdir()

    with pytest.raises((OSError, ValueError)):
        save_tailored_cv("job-1", "New synthetic CV", "synthetic", TailoringPolicy(output_dir=output))

    assert sentinel.read_text() == "Outside sentinel"
    assert not list(output.glob(".*.tmp"))


@pytest.mark.parametrize("symlink_leaf", [False, True])
@pytest.mark.parametrize("configured_alias", [False, True])
def test_ai_review_rejects_symlink_save_but_keeps_result(tmp_path, monkeypatch, symlink_leaf, configured_alias):
    from src import job_hunt_cv_review
    monkeypatch.setattr(job_hunt_cv_review, 'REVIEWER_MODELS', ('gemini-3.5-flash',))
    output = tmp_path / "tailored"
    output.mkdir()
    if configured_alias:
        alias = tmp_path / "configured-output"
        alias.symlink_to(output, target_is_directory=True)
        output = alias
    sentinel = tmp_path / "outside.md"
    sentinel.write_text("Outside sentinel", encoding="utf-8")
    destination = output / "job-1_ai_reviewed.md"
    if symlink_leaf:
        destination.symlink_to(sentinel)
    monkeypatch.setattr(ui_handlers, "DEFAULT_TAILORING_POLICY", TailoringPolicy(output_dir=output))
    monkeypatch.setattr(ui_handlers, "load_job_analysis", lambda *args: SimpleNamespace(decision="apply", user_decision=None))
    monkeypatch.setattr(ui_handlers, "load_reviewed_job", lambda *args: SimpleNamespace(job_id="job-1"))
    monkeypatch.setattr(ui_handlers, "load_candidate_profile", lambda *args: SimpleNamespace(
        candidate_id="synthetic", master_cv_text="Synthetic master SQL CV",
    ))
    provider = Mock(return_value=({"reviewed_cv": "Reviewed synthetic SQL CV", "changes": []}, None, "synthetic-model"))
    monkeypatch.setattr(job_hunt_llm, "ai_rewrite_cv", provider)
    monkeypatch.setattr("src.job_hunt_cv_review.run_blind_review", lambda *a, **k: {"items": [], "reviewer_model": "synthetic-reviewer", "prompt_version": "cv-blind-review-v0"})
    responder = SimpleNamespace(send_json=Mock())

    ui_handlers.handle_ai_review_cv(SimpleNamespace(json_body={"use_cloud": True}), SimpleNamespace(profile_path=tmp_path / "profile.json", state_root=tmp_path), responder, "job-1")

    response = responder.send_json.call_args.args[0]
    assert response["ok"] is True and response["reviewed_cv"] == "Reviewed synthetic SQL CV"
    assert response["saved_path"] == (None if symlink_leaf else destination.name)
    assert sentinel.read_text() == "Outside sentinel"
    if not symlink_leaf:
        assert "profile_id: synthetic" in destination.read_text()
    provider.assert_called_once()


def test_configured_root_symlink_remains_supported(tmp_path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    alias = tmp_path / "configured-root"
    alias.symlink_to(canonical, target_is_directory=True)

    saved = save_tailored_cv("job-1", "Synthetic CV", "synthetic", TailoringPolicy(output_dir=alias))

    assert saved == alias / "job-1.md"
    assert "Synthetic CV" in (canonical / "job-1.md").read_text()
    nested = write_cv_text(alias, "profile/docs/master_cv.txt", "Synthetic master CV")
    assert nested == alias / "profile/docs/master_cv.txt"
    assert (canonical / "profile/docs/master_cv.txt").read_text() == "Synthetic master CV"


@pytest.mark.parametrize("writer", ["upload", "explicit"])
def test_master_cv_writers_allow_configured_root_alias(profile_env, tmp_path, monkeypatch, writer):
    config, directory, _, provider = profile_env
    alias = tmp_path / "configured-profiles"
    alias.symlink_to(directory.parent, target_is_directory=True)
    monkeypatch.setattr(ui_handlers, "_DATA_ROOT", alias)
    responder = SimpleNamespace(send_json=Mock(), redirect=Mock())
    if writer == "upload":
        monkeypatch.setattr(ui_handlers, "parse_multipart_form", lambda req: {
            "cv_file": {"filename": "synthetic.txt", "content": b"Synthetic SQL CV"},
            "profile_id": {"content": b"synthetic"},
        })
        monkeypatch.setattr(ui_handlers, "parse_cv_file", lambda path: "Synthetic SQL CV")
        ui_handlers.handle_parse_cv(SimpleNamespace(headers={"Content-Type": "multipart/form-data"}), config, responder)
        assert responder.send_json.call_args.args[0]["auto_saved"] is True
    else:
        ui_handlers.handle_save_profile(SimpleNamespace(form={
            "profile_id": "synthetic", "master_cv_text": "Synthetic SQL CV",
        }), config, responder)
        responder.redirect.assert_called_once()
    assert (directory / "docs/master_cv.txt").read_text() == "Synthetic SQL CV"
    provider.assert_not_called()


def test_writer_refuses_leaf_symlink_inserted_before_replace(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    sentinel = tmp_path / "outside.txt"
    sentinel.write_text("Outside sentinel", encoding="utf-8")
    real_fsync = job_hunt_cv_storage.os.fsync

    def insert_symlink(fd):
        real_fsync(fd)
        (root / "cv.txt").symlink_to(sentinel)

    monkeypatch.setattr(job_hunt_cv_storage.os, "fsync", insert_symlink)
    with pytest.raises(ValueError, match="regular file"):
        write_cv_text(root, "cv.txt", "New CV")
    assert sentinel.read_text() == "Outside sentinel"
    assert not list(root.glob(".*.tmp"))


def test_writer_rejects_intermediate_symlink_inserted_during_walk(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "profile").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "master_cv.txt"
    sentinel.write_text("Outside sentinel", encoding="utf-8")
    real_open = job_hunt_cv_storage.os.open

    def swap_directory(path, flags, *args, **kwargs):
        if path == "profile":
            (root / "profile").rmdir()
            (root / "profile").symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(job_hunt_cv_storage.os, "open", swap_directory)
    with pytest.raises(OSError):
        write_cv_text(root, "profile/master_cv.txt", "New CV")
    assert sentinel.read_text() == "Outside sentinel"


def test_writer_cleans_failed_atomic_replace_and_preserves_old_file(tmp_path, monkeypatch):
    destination = tmp_path / "cv.txt"
    destination.write_text("Original CV", encoding="utf-8")
    monkeypatch.setattr(job_hunt_cv_storage.os, "replace", Mock(side_effect=OSError("Synthetic replace failure")))

    with pytest.raises(OSError, match="Synthetic replace failure"):
        write_cv_text(tmp_path, "cv.txt", "New CV")

    assert destination.read_text() == "Original CV"
    assert not list(tmp_path.glob(".*.tmp"))
