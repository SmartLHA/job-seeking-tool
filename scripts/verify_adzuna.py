"""Live Adzuna check — run on your own machine (the sandbox can't reach the API).

    python3 scripts/verify_adzuna.py

Loads .env, calls the real Adzuna search, and prints what came back.
Exits non-zero if the keys are wrong or no jobs are returned.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _load_env() -> str:
    """Load .env via python-dotenv if present, else parse it manually so this
    works with a bare system python3 (no venv / no python-dotenv)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
        return "python-dotenv"
    except ImportError:
        pass
    env_path = os.path.join(ROOT, ".env")
    if not os.path.exists(env_path):
        return "no .env file found"
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    return "manual .env parse"


print(f"env loaded via: {_load_env()}")

from src.job_sources.adzuna_client import fetch_adzuna_jobs  # noqa: E402
from src.job_sources.adzuna_source import adzuna_job_to_ui_result  # noqa: E402
from src.job_sources.adzuna_source import normalize_adzuna_search_params  # noqa: E402

app_id = os.getenv("ADZUNA_APP_ID")
app_key = os.getenv("ADZUNA_APP_KEY")
if not app_id or not app_key:
    print("FAIL: ADZUNA_APP_ID / ADZUNA_APP_KEY not found in .env")
    raise SystemExit(1)
print(f"keys loaded: app_id={app_id[:3]}*** app_key=***{app_key[-3:]}")

jobs = fetch_adzuna_jobs("Business Analyst", "London", max_results=5)
print(f"raw jobs returned: {len(jobs)}")
if not jobs:
    print("FAIL: 0 jobs — check the keys are active, or the daily quota.")
    raise SystemExit(1)

# Run them through the adapter to prove the full normalise path works too.
search_values = normalize_adzuna_search_params({})
for j in jobs[:3]:
    ui = adzuna_job_to_ui_result(j, search_values)
    print(f"  - {ui['title']} | {ui['company']} | {ui['location']} | {ui['salary_display']}")

print("OK: Adzuna is wired and returning live jobs.")
