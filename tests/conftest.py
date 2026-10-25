"""Never allow the advisory checker to contact Ollama from pytest."""
import pytest
from browser_support import browser_required, fail_required_skip


def pytest_configure(config):
    config.addinivalue_line("markers", "required_browser: browser coverage mandatory in required mode")
    if browser_required():
        # Runs before application test-module imports. Required browser CI uses
        # synthetic fixtures and never loads a checkout/home dotenv file.
        import dotenv
        dotenv.load_dotenv = lambda *args, **kwargs: False
        dotenv.find_dotenv = lambda *args, **kwargs: ""
        dotenv.dotenv_values = lambda *args, **kwargs: {}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    result = yield
    fail_required_skip(item, result.get_result())


@pytest.fixture(autouse=True)
def browser_fake_providers_only(request, monkeypatch):
    if request.node.get_closest_marker("required_browser") is None:
        return
    import os
    import requests

    for key in list(os.environ):
        if key.endswith(("_API_KEY", "_APP_KEY")) or key in {"ADZUNA_APP_ID", "ANTHROPIC_AUTH_TOKEN"}:
            monkeypatch.delenv(key, raising=False)

    def blocked(*args, **kwargs):
        raise AssertionError("Browser fixture forbids real provider transport; supply a synthetic fake.")

    if request.node.path.name in {"test_ui.py", "test_bulk_paste.py"}:
        from src import job_hunt_llm
        monkeypatch.setattr(job_hunt_llm, "_call_gemini_reasoning", blocked)
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)


@pytest.fixture(autouse=True)
def explain_check_post_systemone_fence(monkeypatch):
    from src import job_hunt_explain_check

    def blocked(*args, **kwargs):
        raise AssertionError('pytest Ollama transport fence: no socket connection permitted')

    monkeypatch.setattr(job_hunt_explain_check, '_post_systemone', blocked)
