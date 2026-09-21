"""Start scripts must use the project venv interpreter (never system python3)."""
import os
import shutil
import subprocess
import sys
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ["restart.sh", "start.command"]


def test_scripts_use_venv_python_not_system():
    for name in SCRIPTS:
        text = (ROOT / name).read_text()
        assert 'exec "$PY" -m src.job_hunt_ui' in text
        assert "exec python3" not in text


def test_dry_run_prints_venv_interpreter(tmp_path):
    """Self-contained: a tmp copy of each script with tmp/venv/bin/python -> sys.executable."""
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    fake_py = venv_bin / "python"
    fake_py.symlink_to(sys.executable)
    for name in SCRIPTS:
        shutil.copy(ROOT / name, tmp_path / name)
        r = subprocess.run(["bash", str(tmp_path / name)], capture_output=True, text=True,
                           env={**os.environ, "DRY_RUN": "1"})
        assert r.returncode == 0, r.stderr
        assert f"Interpreter: {fake_py}" in r.stdout.splitlines()
        assert "Python 3" in r.stdout


def test_missing_venv_fails_clearly(tmp_path):
    for name in SCRIPTS:
        shutil.copy(ROOT / name, tmp_path / name)
        r = subprocess.run(["bash", str(tmp_path / name)], capture_output=True, text=True,
                           env={**os.environ, "DRY_RUN": "1"})
        assert r.returncode == 1
        assert "venv" in r.stderr and "not found" in r.stderr


def test_hidden_list_load_keeps_typed_filter():
    """C (2026-09-20): the async hidden-jobs fetch must re-apply the filter text the user
    already typed instead of resetting to an empty filter (was a real race)."""
    src = (ROOT / "src" / "job_sources" / "_multiselect.py").read_text()
    assert 'window._jst_hidden_jobs=d.jobs;jstFilterHidden(input?input.value:"");' in src
    assert 'window._jst_hidden_jobs=d.jobs;jstFilterHidden("");' not in src
