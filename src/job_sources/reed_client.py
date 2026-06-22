import os
import requests
import json
import logging
from datetime import datetime
from typing import List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

def _ensure_env_loaded() -> None:
    """Load .env from project root if REED_API_KEY is not already in environment."""
    if os.getenv("REED_API_KEY"):
        return
    # Try python-dotenv first
    try:
        from dotenv import load_dotenv
        load_dotenv()
        if os.getenv("REED_API_KEY"):
            return
    except ImportError:
        pass
    # Inline fallback: parse .env manually (no dependencies)
    import pathlib
    for candidate in [
        pathlib.Path(__file__).parent.parent.parent / ".env",  # <project_root>/.env
        pathlib.Path.cwd() / ".env",
    ]:
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            break


def fetch_reed_jobs(keyword: str, location: str, max_results: int = 50, *, skip: int = 0, save_raw: bool = True) -> List[Dict[str, Any]]:
    """
    Fetch jobs from Reed API based on keyword and location.
    Pass skip>0 to page through results (Reed API: resultsToSkip parameter).
    """
    _ensure_env_loaded()
    api_key = os.getenv("REED_API_KEY")
    if not api_key:
        logger.error("REED_API_KEY not found in environment variables.")
        return []

    url = "https://www.reed.co.uk/api/1.0/search"
    # Reed API uses HTTP Basic Auth: api_key as username, empty password
    params = {
        "keywords": keyword,
        "locationName": location,
        "resultsToTake": max_results,
        "resultsToSkip": skip,  # Reed API param is resultsToSkip (not resultsSkip); wrong name made paging return page 0 every time
        "distanceFromLocation": 25,  # miles; Reed API param is distanceFromLocation (not distance)
    }

    try:
        response = requests.get(url, params=params, auth=(api_key, ""), timeout=10)
        
        # Store raw response when explicitly allowed. App-native search is read-only.
        if save_raw:
            save_raw_response(response.text, "reed")
        
        if response.status_code == 429:
            logger.warning("Reed API rate limit exceeded (429). Returning empty list.")
            return []
        
        response.raise_for_status()
        data = response.json()

        # Reed API returns {"results": [...], "totalResults": N}
        if isinstance(data, dict):
            return data.get("results", [])
        # Fallback: older callers that somehow got a plain list
        if isinstance(data, list):
            return data
        return []

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error occurred while fetching from Reed: {e}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error occurred while fetching from Reed: {e}")
        return []
    except json.JSONDecodeError:
        logger.error("Failed to decode JSON response from Reed.")
        return []

def fetch_reed_job_detail(job_id: str) -> Dict[str, Any] | None:
    """Fetch the full detail for a single Reed job by its numeric job ID.

    Returns the raw API dict on success, or None on any failure.
    The detail endpoint returns a richer ``jobDescription`` HTML field than
    the search endpoint — use this to get the full description for skill extraction.
    """
    _ensure_env_loaded()
    api_key = os.getenv("REED_API_KEY")
    if not api_key:
        logger.error("REED_API_KEY not found; cannot fetch job detail.")
        return None
    url = f"https://www.reed.co.uk/api/1.0/jobs/{job_id}"
    try:
        response = requests.get(url, auth=(api_key, ""), timeout=10)
        if response.status_code == 404:
            logger.warning("Reed job detail not found for id=%s", job_id)
            return None
        if response.status_code == 429:
            logger.warning("Reed rate limit hit fetching job detail id=%s", job_id)
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        logger.warning("Failed to fetch Reed job detail id=%s: %s", job_id, exc)
        return None
    except json.JSONDecodeError:
        logger.warning("Bad JSON from Reed job detail id=%s", job_id)
        return None


def save_raw_response(content: str, source: str):
    """
    Saves the raw API response to a timestamped JSON file.
    """
    try:
        raw_dir = Path(f"data/raw/{source}")
        raw_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"raw_{timestamp}.json"
        filepath = raw_dir / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            # Try to parse and re-save as pretty JSON if possible
            try:
                json_data = json.loads(content)
                json.dump(json_data, f, indent=2)
            except json.JSONDecodeError:
                f.write(content)
                
    except Exception as e:
        logger.warning(f"Failed to save raw response for {source}: {e}")

if __name__ == "__main__":
    # Basic smoke test
    import dotenv
    dotenv.load_dotenv()
    jobs = fetch_reed_jobs("Business Analyst", "London")
    print(f"Fetched {len(jobs)} jobs from Reed.")
