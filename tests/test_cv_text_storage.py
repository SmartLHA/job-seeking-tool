"""New extracted CV saves use truthful text paths; legacy references are retained."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import job_hunt_llm, ui_handlers
from src.job_hunt_profile import candidate_profile_from_dict, load_candidate_profile, load_master_cv, save_candidate_profile


@pytest.fixture
def profile_store(tmp_path, monkeypatch):
    root = tmp_path / 'profiles'
    directory = root / 'synthetic'
    directory.mkdir(parents=True)
    startup = tmp_path / 'synthetic.json'
    legacy = directory / 'docs' / 'master_cv.pdf'
    legacy.parent.mkdir()
    legacy.write_text('Legacy extracted text with SQL.', encoding='utf-8')
    profile = candidate_profile_from_dict({'candidate_id': 'synthetic', 'master_cv_text': load_master_cv(legacy), 'master_cv_ref': str(legacy)})
    save_candidate_profile(profile, directory / 'candidate_profile.json')
    save_candidate_profile(profile, startup)
    monkeypatch.setattr(ui_handlers, '_DATA_ROOT', root)
    provider = Mock(side_effect=AssertionError('No cloud provider allowed'))
    monkeypatch.setattr(job_hunt_llm, 'extract_cv_skills_with_llm', provider)
    config = SimpleNamespace(profile_path=startup, state_root=tmp_path / 'state')
    return config, directory, legacy, provider


@pytest.mark.parametrize('extension', ['pdf', 'docx'])
def test_upload_autosave_save_and_reload_plain_text_for_both_formats(profile_store, monkeypatch, extension):
    config, directory, legacy, provider = profile_store
    old_bytes = legacy.read_bytes()
    extracted = f'Synthetic extracted {extension} CV: SQL and Python.'
    filename = f'original-name.{extension}'
    content = b'%PDF-synthetic' if extension == 'pdf' else b'synthetic-docx'
    form = {'cv_file': {'filename': filename, 'content': content}, 'profile_id': {'content': b'synthetic'}}
    monkeypatch.setattr(ui_handlers, 'parse_multipart_form', lambda req: form)
    extractor = Mock(return_value=extracted)
    monkeypatch.setattr(ui_handlers, 'parse_cv_file', extractor)
    response = SimpleNamespace(send_json=Mock())
    ui_handlers.handle_parse_cv(SimpleNamespace(headers={'Content-Type': 'multipart/form-data'}), config, response)
    data = response.send_json.call_args.args[0]
    assert data['ok'] and data['auto_saved'] and data['filename'] == filename
    assert data['master_cv_text'] == extracted and data['skill_extraction_warning'] is None
    assert 'SQL' in data['suggested_skills']
    extractor.assert_called_once()
    assert extractor.call_args.args[0].suffix == '.' + extension
    assert not extractor.call_args.args[0].exists()
    expected = directory / 'docs' / 'master_cv.txt'
    for path in [directory / 'candidate_profile.json', config.profile_path]:
        saved = load_candidate_profile(path)
        assert Path(saved.master_cv_ref) == expected.resolve()
        assert saved.master_cv_text == extracted and load_master_cv(saved.master_cv_ref) == extracted
    # Save Profile receives the original filename as UI metadata but stores text.
    edited = extracted + ' Edited after upload.'
    request = SimpleNamespace(form={'profile_id': 'synthetic', 'master_cv_text': edited, '_cv_filename': filename})
    saved_response = SimpleNamespace(send_json=Mock(), redirect=Mock())
    ui_handlers.handle_save_profile(request, config, saved_response)
    saved_response.send_json.assert_not_called()
    saved_response.redirect.assert_called_once()
    for path in [directory / 'candidate_profile.json', config.profile_path]:
        saved = load_candidate_profile(path)
        assert Path(saved.master_cv_ref) == expected.resolve()
        assert saved.master_cv_text == edited and load_master_cv(saved.master_cv_ref) == edited
    assert legacy.read_bytes() == old_bytes and load_master_cv(legacy) == old_bytes.decode()
    if extension == 'docx':
        assert not (directory / 'docs' / 'master_cv.docx').exists()
    provider.assert_not_called()


@pytest.mark.parametrize('extension', ['pdf', 'docx'])
@pytest.mark.parametrize('omitted', [True, False])
def test_save_without_new_text_preserves_legacy_reference_and_bytes(profile_store, extension, omitted):
    config, directory, old_legacy, provider = profile_store
    legacy = directory / 'docs' / f'old-reference.{extension}'
    old_bytes = b'Legacy UTF-8 extracted text, readable regardless of suffix.'
    legacy.write_bytes(old_bytes)
    profile = candidate_profile_from_dict({'candidate_id': 'synthetic', 'master_cv_text': old_bytes.decode(), 'master_cv_ref': str(legacy)})
    for path in [directory / 'candidate_profile.json', config.profile_path]:
        save_candidate_profile(profile, path)
    form = {'profile_id': 'synthetic', 'name': 'Updated name', '_cv_filename': f'original.{extension}'}
    if not omitted:
        form['master_cv_text'] = ''
    response = SimpleNamespace(send_json=Mock(), redirect=Mock())
    ui_handlers.handle_save_profile(SimpleNamespace(form=form), config, response)
    response.send_json.assert_not_called()
    response.redirect.assert_called_once()
    for path in [directory / 'candidate_profile.json', config.profile_path]:
        saved = load_candidate_profile(path)
        assert saved.master_cv_ref == str(legacy) and saved.master_cv_text == old_bytes.decode()
        assert load_master_cv(saved.master_cv_ref) == old_bytes.decode()
    assert legacy.read_bytes() == old_bytes
    assert not (directory / 'docs' / 'master_cv.txt').exists()
    assert old_legacy.exists()
    provider.assert_not_called()


@pytest.mark.parametrize('extension', ['pdf', 'docx'])
def test_explicit_save_without_upload_stores_text_and_preserves_legacy(profile_store, extension):
    config, directory, legacy, provider = profile_store
    old_bytes = legacy.read_bytes()
    text = 'New explicitly saved synthetic text with SQL.'
    response = SimpleNamespace(send_json=Mock(), redirect=Mock())
    ui_handlers.handle_save_profile(SimpleNamespace(form={'profile_id': 'synthetic', 'master_cv_text': text, '_cv_filename': f'input.{extension}'}), config, response)
    response.redirect.assert_called_once()
    saved = load_candidate_profile(directory / 'candidate_profile.json')
    assert Path(saved.master_cv_ref) == (directory / 'docs' / 'master_cv.txt').resolve()
    assert load_master_cv(saved.master_cv_ref) == text
    assert legacy.read_bytes() == old_bytes
    provider.assert_not_called()
