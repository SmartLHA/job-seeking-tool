import os
import requests
import json
import logging
import hashlib
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_adzuna_jobs(keyword: str, location: str, max_results: int = 50, *, skip: int = 0) -> List[Dict[str, Any]]:
    """
    Fetch jobs from Adzuna API based on keyword and location.

    Adzuna paginates by *page number* in the URL path (1-indexed), not by an
    offset. ``skip`` is the running result offset from the UI's ``resultsSkip``
    cursor; convert it to a page so "More jobs" returns the next page instead of
    repeating page 1. Each page holds ``max_results`` rows, so
    ``page = skip // max_results + 1`` (e.g. skip=10, take=10 -> page 2).
    """
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")

    if not app_id or not app_key:
        logger.error("ADZUNA_APP_ID or ADZUNA_APP_KEY not found in environment variables.")
        return []

    # Adzuna search endpoint: /v1/api/jobs/{country}/search/{page}
    # Ref: https://developer.adzuna.com/overview and /docs/search
    # (The previous /1/data/gb/jobs path with a "max_results" param was not a
    #  valid Adzuna endpoint and always returned nothing.)
    country = "gb"
    per_page = max(1, int(max_results))
    page = (max(0, int(skip)) // per_page) + 1
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": max_results,
        "what": keyword,
        "where": location,
        "content-type": "application/json",
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

# ── Salary histogram (Feature B, 2026-09-22) ─────────────────────────────────
# Advisory market context only. Docs: https://developer.adzuna.com/docs/histogram
# Terms: personal research use; show "Source: Adzuna"; do not redistribute.
# SECURITY: the request URL/params carry app_key. Never log or return them; error
# text below is built only from fixed strings, exception class names and status codes.

HISTOGRAM_URL = "https://api.adzuna.com/v1/api/jobs/gb/histogram"
DEFAULT_SALARY_CACHE_DIR = Path("data/state/cache/adzuna_salary")
SALARY_CACHE_TTL_SECONDS = 24 * 3600
DAILY_CALL_LIMIT = 200  # Adzuna cap is 250/day; keep headroom
_BUDGET_FILE = "budget.json"
_budget_lock = threading.Lock()


@dataclass(frozen=True)
class SalaryHistogramResult:
    status: str  # "ok" | "no_data" | "error" | "unavailable"
    what: str = ""
    buckets: List[Tuple[int, int]] = field(default_factory=list)
    total: int = 0
    fetched_at: str = ""
    error: Optional[str] = None
    cached: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "what": self.what,
            "buckets": [[lo, n] for lo, n in self.buckets],
            "total": self.total,
            "fetched_at": self.fetched_at,
            "error": self.error,
            "cached": self.cached,
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _norm_what(what: str) -> str:
    return " ".join((what or "").lower().split())


def _cache_path(cache_dir: Path, what: str, location: Optional[str]) -> Path:
    key = json.dumps([_norm_what(what), _norm_what(location or "")])
    return Path(cache_dir) / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")


def _read_cache(path: Path, now: datetime) -> Optional[SalaryHistogramResult]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(d["fetched_at"])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if (now - fetched).total_seconds() >= SALARY_CACHE_TTL_SECONDS:
            return None
        if d["status"] not in ("ok", "no_data"):
            return None
        return SalaryHistogramResult(
            status=d["status"], what=str(d.get("what", "")),
            buckets=[(int(a), int(b)) for a, b in d.get("buckets", [])],
            total=int(d.get("total", 0)), fetched_at=d["fetched_at"], cached=True,
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cache(path: Path, result: SalaryHistogramResult) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = result.to_dict()
        payload.pop("cached", None)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        logger.warning("Could not write Adzuna salary cache.")


def _take_budget(cache_dir: Path, now: datetime) -> Optional[str]:
    """Count one HTTP call against today's budget. None = allowed, else the refusal reason (fail closed)."""
    path = Path(cache_dir) / _BUDGET_FILE
    today = now.strftime("%Y-%m-%d")
    with _budget_lock:
        count = 0
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            if d.get("date") == today:
                count = int(d.get("count", 0))
        except (OSError, ValueError, TypeError, AttributeError):
            count = 0
        if count >= DAILY_CALL_LIMIT:
            return "daily Adzuna budget reached"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"date": today, "count": count + 1}), encoding="utf-8")
        except OSError:
            # Fail closed: without a persisted counter the daily budget cannot be enforced.
            logger.warning("Could not persist Adzuna daily call counter; refusing the call.")
            return "budget tracking unavailable"
        return None


def _parse_histogram(data: Any) -> Optional[List[Tuple[int, int]]]:
    """Return sorted (lower_bound, count) pairs, or None when the payload is malformed."""
    if not isinstance(data, dict) or not isinstance(data.get("histogram"), dict):
        return None
    buckets: List[Tuple[int, int]] = []
    try:
        for k, v in data["histogram"].items():
            buckets.append((int(float(k)), int(v)))
    except (TypeError, ValueError):
        return None
    return sorted(buckets)


def fetch_adzuna_salary_histogram(
    what: str,
    *,
    location: Optional[str] = None,
    cache_dir: Optional[Path] = None,
    now: Optional[Callable[[], datetime]] = None,
) -> SalaryHistogramResult:
    """Fetch the Adzuna UK salary histogram for a job title (24h file cache, daily budget)."""
    clock = now or _utc_now
    cache = Path(cache_dir) if cache_dir is not None else DEFAULT_SALARY_CACHE_DIR
    what_n = _norm_what(what)
    stamp = clock()
    if not what_n:
        return SalaryHistogramResult("error", what_n, error="Empty job title query", fetched_at=stamp.isoformat())

    cpath = _cache_path(cache, what_n, location)
    hit = _read_cache(cpath, stamp)
    if hit is not None:
        return hit

    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        return SalaryHistogramResult("unavailable", what_n, fetched_at=stamp.isoformat(),
                                     error="Adzuna credentials are not configured")

    refusal = _take_budget(cache, stamp)
    if refusal:
        return SalaryHistogramResult("error", what_n, fetched_at=stamp.isoformat(), error=refusal)

    params: Dict[str, Any] = {
        "app_id": app_id, "app_key": app_key, "what": what_n,
        "content-type": "application/json",
    }
    if location:
        params["location0"] = "UK"
        params["location1"] = location

    def _err(msg: str) -> SalaryHistogramResult:
        return SalaryHistogramResult("error", what_n, fetched_at=stamp.isoformat(), error=msg)

    try:
        response = requests.get(HISTOGRAM_URL, params=params, timeout=10)
    except requests.exceptions.Timeout:
        logger.warning("Adzuna histogram request failed: Timeout")
        return _err("Adzuna request timed out")
    except requests.exceptions.RequestException as exc:
        logger.warning("Adzuna histogram request failed: %s", type(exc).__name__)
        return _err(f"Adzuna request failed ({type(exc).__name__})")

    code = response.status_code
    if code == 429:
        logger.warning("Adzuna histogram rate limited (429)")
        return _err("Adzuna rate limit reached (429)")
    if code != 200:
        logger.warning("Adzuna histogram HTTP status %s", code)
        return _err(f"Adzuna returned HTTP {code}")
    try:
        data = response.json()
    except ValueError:
        logger.warning("Adzuna histogram response was not valid JSON")
        return _err("Adzuna returned an unreadable response")
    buckets = _parse_histogram(data)
    if buckets is None:
        logger.warning("Adzuna histogram response had an unexpected shape")
        return _err("Adzuna returned an unexpected response")

    total = sum(n for _, n in buckets)
    result = SalaryHistogramResult(
        "ok" if total > 0 else "no_data", what_n, buckets if total > 0 else [], total, stamp.isoformat(),
    )
    _write_cache(cpath, result)
    return result


if __name__ == "__main__":
    # Basic smoke test
    import dotenv
    dotenv.load_dotenv()
    jobs = fetch_adzuna_jobs("Business Analyst", "London")
    print(f"Fetched {len(jobs)} jobs from Adzuna.")
