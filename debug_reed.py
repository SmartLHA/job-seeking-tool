"""
Run this directly to diagnose Reed API issues:
  python3 debug_reed.py
"""
import os, sys, json, pathlib

# ── Load .env ──────────────────────────────────────────────────────────────────
env_path = pathlib.Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    print(f"✓ Loaded .env from {env_path}")
else:
    print("✗ No .env file found")

api_key = os.environ.get("REED_API_KEY", "")
print(f"  REED_API_KEY present: {bool(api_key)} ({api_key[:8]}...)" if api_key else "  REED_API_KEY: NOT SET")

# ── Raw HTTP request (no app code) ────────────────────────────────────────────
print("\n── Raw API call ──")
try:
    import requests
    url = "https://www.reed.co.uk/api/1.0/search"
    params = {"keywords": "Business Analyst", "location": "London", "resultsToTake": 3}
    resp = requests.get(url, params=params, auth=(api_key, ""), timeout=15)
    print(f"  HTTP status: {resp.status_code}")
    print(f"  Content-Type: {resp.headers.get('Content-Type','')}")
    try:
        data = resp.json()
        print(f"  Response type: {type(data).__name__}")
        if isinstance(data, dict):
            print(f"  Keys: {list(data.keys())}")
            results = data.get("results", [])
            print(f"  totalResults: {data.get('totalResults')}")
            print(f"  results count: {len(results)}")
            if results:
                j = results[0]
                print(f"  First job: {j.get('jobTitle')} @ {j.get('employerName')}")
        elif isinstance(data, list):
            print(f"  List length: {len(data)}")
        else:
            print(f"  Raw: {str(data)[:300]}")
    except Exception as e:
        print(f"  JSON parse error: {e}")
        print(f"  Raw text: {resp.text[:500]}")
except Exception as e:
    print(f"  Request failed: {type(e).__name__}: {e}")

# ── Via app code ───────────────────────────────────────────────────────────────
print("\n── Via fetch_reed_jobs() ──")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
try:
    from src.job_sources.reed_client import fetch_reed_jobs
    jobs = fetch_reed_jobs("Business Analyst", "London", max_results=3, save_raw=False)
    print(f"  Returned: {len(jobs)} jobs")
    if jobs:
        print(f"  First job keys: {list(jobs[0].keys())[:6]}")
        print(f"  First job title: {jobs[0].get('jobTitle')}")
    else:
        print("  No jobs returned — check errors above")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")
