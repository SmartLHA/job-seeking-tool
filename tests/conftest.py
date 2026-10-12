"""Never allow the advisory checker to contact Ollama from pytest."""
import pytest


@pytest.fixture(autouse=True)
def explain_check_post_systemone_fence(monkeypatch):
    from src import job_hunt_explain_check

    def blocked(*args, **kwargs):
        raise AssertionError('pytest Ollama transport fence: no socket connection permitted')

    monkeypatch.setattr(job_hunt_explain_check, '_post_systemone', blocked)
