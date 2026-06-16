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

def fetch_adzuna_jobs(keyword: str, location: str, max_results: int = 50) -> List[Dict[str, Any]]:
    """
    Fetch jobs from Adzuna API based on keyword and location.
    """
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    
    if not app_id or not app_key:
        logger.error("ADZUNA_APP_ID or ADZUNA_APP_KEY not found in environment variables.")
        return []

    url = "https://api.adzuna.com/1/data/gb/jobs"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": keyword,
        "where": location,
        "max_results": max_results,
        "distance": 25
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        
        # Store raw response
        save_raw_response(response.text, "adzuna")
        
        if response.status_code == 429:
            logger.warning("Adzuna API rate limit exceeded (429). Returning empty list.")
            return []
        
        response.raise_for_status()
        data = response.json()
        
        # Adzuna puts the jobs in the 'results' key
        return data.get("results", []) if isinstance(data, dict) else []

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error occurred while fetching from Adzuna: {e}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error occurred while fetching from Adzuna: {e}")
        return []
    except json.JSONDecodeError:
        logger.error("Failed to decode JSON response from Adzuna.")
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
    jobs = fetch_adzuna_jobs("Business Analyst", "London")
    print(f"Fetched {len(jobs)} jobs from Adzuna.")
