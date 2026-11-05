"""Atomic profile persistence and process-local merge tests; synthetic data only."""
import json
import os
import stat
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import job_hunt_profile as profile_module, ui_handlers
from src.job_hunt_profile import candidate_profile_from_dict, load_candidate_profile, profile_update_lock, save_candidate_profile


def _profile(**changes):
    payload = dict(candidate_id='synthetic', name='Original', skills=['SQL'], target_roles=['Analyst'],
                   locations=['London'], industries=['Finance'], years_experience=8, salary_floor_gbp=50000,
                   digest_llm_rpm=7)
    payload.update(changes)
    return candidate_profile_from_dict(payload)


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / 'profiles'
    canonical = root / 'synthetic' / 'candidate_profile.json'
    alias = tmp_path / 'active.json'
    save_candidate_profile(_profile(), canonical)
    save_candidate_profile(_profile(), alias)
    monkeypatch.setattr(ui_handlers, '_DATA_ROOT', root)
    monkeypatch.setattr(ui_handlers, 'parse_cv_file', lambda path: 'New synthetic CV with SQL.')
    monkeypatch.setattr('src.job_hunt_llm.extract_cv_skills_with_llm', Mock(side_effect=AssertionError('No provider allowed')))
    monkeypatch.setattr(ui_handlers, 'parse_multipart_form', lambda req: {
        'cv_file': {'filename': 'synthetic.pdf', 'content': b'%PDF-synthetic'},
        'profile_id': {'content': b'synthetic'},
    })
    return SimpleNamespace(profile_path=alias, state_root=tmp_path / 'state'), canonical, alias


def test_atomic_failed_replace_preserves_valid_bytes_and_cleans_unique_temp(tmp_path, monkeypatch):
    path = tmp_path / 'profile.json'
    save_candidate_profile(_profile(), path)
    path.chmod(0o640)
    original = path.read_bytes()
    seen = []
    def failed_replace(source, destination):
        source = type(path)(source)
        assert source != path and source.parent == path.parent
        assert json.loads(source.read_text())['name'] == 'Changed'
        seen.append(source)
        raise OSError('synthetic failed replace')
    monkeypatch.setattr(profile_module.os, 'replace', failed_replace)
    with pytest.raises(OSError, match='synthetic failed replace'):
        save_candidate_profile(_profile(name='Changed'), path)
    assert path.read_bytes() == original and json.loads(path.read_text())['name'] == 'Original'
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert len(seen) == 1 and not seen[0].exists()
    assert list(tmp_path.glob('.profile.json.*.tmp')) == []


def test_serialization_fails_before_filesystem_change(tmp_path, monkeypatch):
    path = tmp_path / 'profile.json'
    save_candidate_profile(_profile(), path)
    original = path.read_bytes()
    monkeypatch.setattr(profile_module, 'candidate_profile_to_dict', lambda p: {'invalid': object()})
    with pytest.raises(TypeError):
        save_candidate_profile(_profile(), path)
    assert path.read_bytes() == original and list(tmp_path.glob('*.tmp')) == []
    new = tmp_path / 'absent' / 'profile.json'
    with pytest.raises(TypeError):
        save_candidate_profile(_profile(), new)
    assert not new.parent.exists()


def test_atomic_success_flushes_and_fsyncs_before_replace_preserving_mode(tmp_path, monkeypatch):
    path = tmp_path / 'profile.json'
    save_candidate_profile(_profile(), path)
    path.chmod(0o640)
    fsync, replace = profile_module.os.fsync, profile_module.os.replace
    order = []
    temporary_paths = []
    def observed_fsync(fd):
        temporary = next(tmp_path.glob('.profile.json.*.tmp'))
        assert json.loads(temporary.read_text())['name'] == 'Changed'
        order.append('fsync')
        return fsync(fd)
    def observed_replace(source, dest):
        assert order[-1] == 'fsync'
        temporary_paths.append(source)
        order.append('replace')
        return replace(source, dest)
    monkeypatch.setattr(profile_module.os, 'fsync', observed_fsync)
    monkeypatch.setattr(profile_module.os, 'replace', observed_replace)
    save_candidate_profile(_profile(name='Changed'), path)
    save_candidate_profile(_profile(name='Changed'), path)
    assert order == ['fsync', 'replace', 'fsync', 'replace']
    assert len(set(temporary_paths)) == 2
    assert load_candidate_profile(path).name == 'Changed'
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert list(tmp_path.glob('.profile.json.*.tmp')) == []


def test_canonical_alias_lock_blocks_competing_operation_and_preserves_symlink(tmp_path):
    canonical = tmp_path / 'profile.json'
    save_candidate_profile(_profile(), canonical)
    alias = tmp_path / 'alias.json'
    alias.symlink_to(canonical)
    attempted, entered, released = threading.Event(), threading.Event(), threading.Event()
    errors = []
    def competing():
        try:
            attempted.set()
            with profile_update_lock(alias):
                entered.set()
                save_candidate_profile(_profile(name='Alias saved'), alias)
            released.set()
        except BaseException as exc:
            errors.append(exc)
    with profile_update_lock(canonical):
        thread = threading.Thread(target=competing)
        thread.start()
        assert attempted.wait(5) and not entered.is_set()
        assert load_candidate_profile(alias).name == 'Original'  # Reentrant alias read.
    assert entered.wait(5) and released.wait(5)
    thread.join(5)
    assert not thread.is_alive() and errors == []
    assert alias.is_symlink() and load_candidate_profile(canonical).name == 'Alias saved'


def test_sorted_multifile_lock_order_avoids_reverse_order_deadlock(tmp_path):
    a, b = tmp_path / 'a.json', tmp_path / 'b.json'
    barrier = threading.Barrier(2)
    entered, release = threading.Event(), threading.Event()
    errors, finished = [], []
    def operation(paths):
        try:
            barrier.wait(timeout=5)
            with profile_update_lock(*paths):
                entered.set()
                assert release.wait(5)
            finished.append(paths)
        except BaseException as exc:
            errors.append(exc)
    threads = [threading.Thread(target=operation, args=(paths,)) for paths in [(a, b), (b, a)]]
    for thread in threads:
        thread.start()
    assert entered.wait(5)
    release.set()
    for thread in threads:
        thread.join(5)
    assert not any(t.is_alive() for t in threads) and errors == [] and len(finished) == 2


def _responder():
    return SimpleNamespace(send_json=Mock(), redirect=Mock())


@pytest.mark.parametrize('skill_operation', ['gap', 'save'])
@pytest.mark.parametrize('first', ['upload', 'skills'])
def test_concurrent_cv_and_skills_merge_under_full_transaction(store, monkeypatch, skill_operation, first):
    config, canonical, alias = store
    paused, resume, attempted = threading.Event(), threading.Event(), threading.Event()
    errors, responses = [], {}
    original_save = ui_handlers.save_candidate_profile
    original_lock = profile_module.profile_update_lock
    paused_once = False
    def paused_save(profile, path):
        nonlocal paused_once
        if threading.current_thread().name == 'first' and not paused_once:
            paused_once = True
            paused.set()
            assert resume.wait(5)
        return original_save(profile, path)
    @contextmanager
    def observed_lock(*paths):
        if threading.current_thread().name == 'second':
            attempted.set()
        with original_lock(*paths):
            yield
    monkeypatch.setattr(ui_handlers, 'save_candidate_profile', paused_save)
    monkeypatch.setattr(ui_handlers, 'profile_update_lock', observed_lock)
    monkeypatch.setattr(profile_module, 'profile_update_lock', observed_lock)
    def upload():
        response = _responder()
        ui_handlers.handle_parse_cv(SimpleNamespace(headers={'Content-Type': 'multipart/form-data'}), config, response)
        assert response.send_json.call_args.args[0]['auto_saved'] is True
        responses['upload'] = response
    def skills():
        response = _responder()
        if skill_operation == 'gap':
            ui_handlers.handle_add_gap_skills(SimpleNamespace(raw_body=b'{"skills":["Python"]}'), config, response, 'synthetic-job')
            assert response.send_json.call_args.args[0]['added'] == ['Python']
        else:
            ui_handlers.handle_save_profile(SimpleNamespace(form={'profile_id': 'synthetic', 'skills': 'SQL, Python'}), config, response)
            response.send_json.assert_not_called()
            response.redirect.assert_called_once()
        responses['skills'] = response
    operations = [upload, skills] if first == 'upload' else [skills, upload]
    def run(operation):
        try:
            operation()
        except BaseException as exc:
            errors.append(exc)
    threads = [threading.Thread(target=run, args=(operation,), name=name) for operation, name in zip(operations, ['first', 'second'])]
    threads[0].start()
    try:
        assert paused.wait(5)
        threads[1].start()
        assert attempted.wait(5)
        assert responses == {}  # Competing update cannot finish before first releases.
    finally:
        resume.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(5)
    assert not any(thread.is_alive() for thread in threads) and errors == []
    for path in [canonical, alias]:
        saved = load_candidate_profile(path)
        assert saved.master_cv_text == 'New synthetic CV with SQL.'
        assert [s.name for s in saved.skills] == ['SQL', 'Python']
        assert saved.name == 'Original' and saved.target_roles == ['Analyst']
        assert saved.locations == ['London'] and saved.digest_llm_rpm == 7
        assert type(path)(saved.master_cv_ref).read_text() == saved.master_cv_text


def test_save_omitted_fields_preserve_latest_and_explicit_empty_clears(store):
    config, canonical, alias = store
    latest = _profile(name='Latest', skills=['SQL', 'Python'], digest_llm_rpm=11)
    for path in [canonical, alias]:
        save_candidate_profile(latest, path)
    response = _responder()
    ui_handlers.handle_save_profile(SimpleNamespace(form={'profile_id': 'synthetic', 'locations': 'Reading'}), config, response)
    assert response.redirect.called
    saved = load_candidate_profile(canonical)
    assert saved.name == 'Latest' and [s.name for s in saved.skills] == ['SQL', 'Python']
    assert saved.digest_llm_rpm == 11 and saved.target_roles == ['Analyst'] and saved.locations == ['Reading']
    response = _responder()
    ui_handlers.handle_save_profile(SimpleNamespace(form={'profile_id': 'synthetic', 'name': '', 'skills_json': '', 'target_roles': '', 'salary_floor_gbp': ''}), config, response)
    assert response.redirect.called
    for path in [canonical, alias]:
        saved = load_candidate_profile(path)
        assert saved.name is None and saved.skills == [] and saved.target_roles == []
        assert saved.salary_floor_gbp is None and saved.locations == ['Reading'] and saved.digest_llm_rpm == 11


def test_cv_only_save_preserves_name_roles_and_unrelated_fields(store):
    config, canonical, alias = store
    for path in [canonical, alias]:
        save_candidate_profile(_profile(name='Keep', target_roles=['Engineer']), path)
    response = _responder()
    ui_handlers.handle_save_profile(SimpleNamespace(form={
        'profile_id': 'synthetic', 'master_cv_text': 'Updated synthetic CV.',
    }), config, response)
    response.redirect.assert_called_once()
    for path in [canonical, alias]:
        saved = load_candidate_profile(path)
        assert saved.name == 'Keep' and saved.target_roles == ['Engineer']
        assert [skill.name for skill in saved.skills] == ['SQL']
        assert saved.master_cv_text == 'Updated synthetic CV.'
        assert type(path)(saved.master_cv_ref).read_text() == saved.master_cv_text
