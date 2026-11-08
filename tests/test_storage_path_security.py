"""Storage confinement regressions using synthetic temporary state only."""

import pytest

from src import job_hunt_storage as storage
from src.job_hunt_models import JobPosting


@pytest.mark.parametrize('record_id', ['../escape', '/absolute', 'a/b', r'a\b', '\0', '.', ' .. ', '', ' '])
@pytest.mark.parametrize('operation', [
    storage.load_raw_input, storage.load_reviewed_job, storage.load_job_analysis,
    storage.load_application_outcome, storage.load_qualitative_assessment,
    storage.archive_qualitative_assessment,
])
def test_read_and_archive_reject_unsafe_ids(tmp_path, record_id, operation):
    with pytest.raises(storage.StorageError):
        operation(record_id, tmp_path / 'state')


@pytest.mark.parametrize('record_id', ['../escape', 'a/b', r'a\b', '\0', '.', ' .. '])
def test_saves_reject_unsafe_ids(tmp_path, record_id):
    with pytest.raises(storage.StorageError):
        storage.save_raw_input({}, record_id, tmp_path)
    with pytest.raises(storage.StorageError):
        storage.save_qualitative_assessment(record_id, {}, tmp_path)
    job = JobPosting(job_id=record_id, job_title='Example', company='Example', description_raw='Example',
                     source_type='copied_text', source_ref=None, location=None,
                     work_mode=None, employment_type=None)
    with pytest.raises(storage.StorageError):
        storage.save_reviewed_job(job, tmp_path)


@pytest.mark.parametrize('record_id', ['香港 BA', 'Job 123', 'id:one!?', 'some..id', '  trimmed  '])
def test_ordinary_ids_roundtrip(tmp_path, record_id):
    path = storage.save_raw_input({'text': 'synthetic'}, record_id, tmp_path)
    assert path.name == record_id.strip() + '.json'
    assert storage.load_raw_input(record_id, tmp_path) == {'text': 'synthetic'}
    storage.save_qualitative_assessment(record_id, {'score': 1}, tmp_path)
    assert storage.load_qualitative_assessment(record_id, tmp_path) == {'score': 1}
    assert storage.archive_qualitative_assessment(record_id, tmp_path).parent.name == 'archive'


@pytest.mark.parametrize('kind', ['record', 'state', 'qualitative', 'archive'])
def test_existing_symlink_escape_is_rejected(tmp_path, kind):
    root = tmp_path / 'state'
    layout = storage.ensure_storage_layout(root)
    outside = tmp_path / 'outside'
    outside.mkdir()
    target = outside / 'victim.json'
    target.write_text('{"unchanged": true}')
    if kind == 'record':
        (layout.raw_inputs_dir / 'victim.json').symlink_to(target)
        operations = [lambda: storage.save_raw_input({}, 'victim', root),
                      lambda: storage.load_raw_input('victim', root)]
    elif kind == 'state':
        layout.raw_inputs_dir.rmdir()
        layout.raw_inputs_dir.symlink_to(outside, target_is_directory=True)
        operations = [lambda: storage.save_raw_input({}, 'victim', root)]
    else:
        qualitative = layout.analyses_dir / 'qualitative'
        if kind == 'qualitative':
            qualitative.symlink_to(outside, target_is_directory=True)
            operations = [lambda: storage.save_qualitative_assessment('victim', {}, root)]
        else:
            storage.save_qualitative_assessment('victim', {}, root)
            (qualitative / 'archive').symlink_to(outside, target_is_directory=True)
            operations = [lambda: storage.archive_qualitative_assessment('victim', root)]
    for operation in operations:
        with pytest.raises(storage.StorageError):
            operation()
    assert target.read_text() == '{"unchanged": true}'
