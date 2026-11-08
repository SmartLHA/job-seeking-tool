import json
import os
import stat
from unittest.mock import patch

import pytest
from src import job_hunt_storage as storage


@pytest.mark.parametrize('failure', ['serialize', 'write', 'fsync', 'replace'])
def test_failed_save_preserves_old_json_and_cleans_temp(tmp_path, failure):
    path = storage.save_raw_input({'old': 'synthetic'}, 'record', tmp_path)
    before = path.read_bytes()
    if failure == 'serialize':
        with pytest.raises(TypeError):
            storage.save_raw_input({'bad': object()}, 'record', tmp_path)
    elif failure == 'write':
        make_temp = storage.tempfile.NamedTemporaryFile
        def failing_temp(*args, **kwargs):
            stream = make_temp(*args, **kwargs)
            original_write = stream.write
            def partial_write(text):
                original_write(text[:1])
                raise OSError('injected failure')
            stream.write = partial_write
            return stream
        with patch.object(storage.tempfile, 'NamedTemporaryFile', side_effect=failing_temp):
            with pytest.raises(OSError, match='injected failure'):
                storage.save_raw_input({'new': 'synthetic'}, 'record', tmp_path)
    else:
        with patch.object(storage.os, failure, side_effect=OSError('injected failure')):
            with pytest.raises(OSError, match='injected failure'):
                storage.save_raw_input({'new': 'synthetic'}, 'record', tmp_path)
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


def test_replace_uses_complete_unique_sibling_and_retains_permissions(tmp_path):
    path = storage.save_raw_input({'old': True}, 'record', tmp_path)
    path.chmod(0o640)
    replace = os.replace
    def inspect_replace(source, destination):
        assert source.parent == destination.parent
        assert source != destination
        assert json.loads(source.read_text()) == {'new': '香港'}
        assert json.loads(destination.read_text()) == {'old': True}
        replace(source, destination)
    with patch.object(storage.os, 'replace', side_effect=inspect_replace) as replacement:
        storage.save_raw_input({'new': '香港'}, 'record', tmp_path)
    replacement.assert_called_once()
    assert storage.load_raw_input('record', tmp_path) == {'new': '香港'}
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert list(path.parent.iterdir()) == [path]
