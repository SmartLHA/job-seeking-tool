import os
import requests
import json
import logging
from datetime import datetime
from typing import List, Dict, Any
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_reed_jobs(keyword: str, location: str, max_results: int = 50, *, save_raw: bool = True) -> List[Dict[str, Any]]:
    """
    Fetch jobs from Reed API based on keyword and location.
    """
    api_key = os.getenv("REED_API_KEY")
    if not api_key:
        logger.error("REED_API_KEY not found in environment variables.")
        return []

    url = "https://www.reed.co.uk/api/1.0/search"
    params = {
        "api_key": api_key,
        "keywords": keyword,
        "location": location,
        "resultsToTake": max_results,
        "distance": 25  # Default distance in miles
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        
        # Store raw response when explicitly allowed. App-native search is read-only.
        if save_raw:
            save_raw_response(response.text, "reed")
        
        if response.status_code == 429:
            logger.warning("Reed API rate limit exceeded (429). Returning empty list.")
            return []
        
        response.raise_for_status()
        data = response.json()
        
        # Reed returns a list of jobs directly in the root of the JSON response
        return data if isinstance(data, list) else []

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error occurred while fetching from Reed: {e}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error occurred while fetching from Reed: {e}")
        return []
    except json.JSONDecodeError:
        logger.error("Failed to decode JSON response from Reed.")
        return []

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
