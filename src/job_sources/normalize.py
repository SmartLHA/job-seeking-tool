import re
import html
from typing import TypedDict, Optional, List, Dict, Any
from datetime import datetime

class SourceQuality(TypedDict):
    has_full_description: bool
    has_salary: bool
    has_company: bool
    has_apply_url: bool
    description_length: int
    quality_score: int

class NormalizedJob(TypedDict):
    source: str
    external_id: str
    title: str
    company: str
    location: str
    location_normalized: str
    remote_type: str # onsite | hybrid | remote | unknown
    salary_min: Optional[float]
    salary_max: Optional[float]
    salary_text: Optional[str]
    salary_currency: Optional[str]
    salary_is_annual: Optional[bool]
    contract_type: str # permanent | contract | temporary | unknown
    job_type: str # full_time | part_time | unknown
    description: str
    original_url: Optional[str]
    apply_url: str
    posted_date: Optional[str]
    expiry_date: Optional[str]
    source_quality: SourceQuality

# Location Alias Table (Section 6.4)
LOCATION_ALIASES = {
    "greater london": "london",
    "london, city of london": "london",
    "london (central)": "london",
    "england": "united kingdom",
    "scotland": "united kingdom",
    "wales": "united kingdom",
    "uk": "united kingdom",
    "united kingdom": "united kingdom",
    "remote": "remote",
    "work from home": "remote"
}

def strip_html(html_content: str) -> str:
    """
    Strips HTML tags from a string.
    Preserves paragraphs as double newlines.
    """
    if not html_content:
        return ""
    
    # Replace <br> and <p> with newlines to maintain structure
    content = re.sub(r'<(br|p|div)[^>]*>', '\n', html_content, flags=re.IGNORECASE)
    # Remove all other tags
    content = re.sub(r'<[^>]+>', '', content)
    # Decode HTML entities
    content = html.unescape(content)
    # Normalize whitespace: remove excess spaces but keep double newlines
    content = re.sub(r' +', ' ', content)
    content = re.sub(r'\n\s*\n+', '\n\n', content).strip()
    
    return content

def normalize_location(loc: str) -> str:
    """
    Normalizes location strings per Section 6.4.
    """
    if not loc:
        return "unknown"
    
    # 1. Lowercase + strip
    norm = loc.lower().strip()
    
    # 2. Alias table check
    if norm in LOCATION_ALIASES:
        return LOCATION_ALIASES[norm]
    
    # 3. Strip common country suffixes (e.g., "london uk" -> "london")
    # Remove trailing " uk", " united kingdom", " england"
    norm = re.sub(r'\s+(uk|united kingdom|england)$', '', norm)
    
    # Check alias again after suffix strip
    if norm in LOCATION_ALIASES:
        return LOCATION_ALIASES[norm]
        
    return norm

def derive_remote_type(title: str, location: str) -> str:
    """
    Derives remote_type based on keywords in title or location.
    """
    t = (title or "").lower()
    l = (location or "").lower()
    
    remote_keywords = ["remote", "work from home", "wfh", "fully remote", "home-based", "anywhere"]
    hybrid_keywords = ["hybrid"]
    
    # Title overrides location
    for kw in remote_keywords:
        if kw in t:
            return "remote"
    for kw in hybrid_keywords:
        if kw in t:
            return "hybrid"
            
    # Check location
    for kw in remote_keywords:
        if kw in l:
            return "remote"
    for kw in hybrid_keywords:
        if kw in l:
            return "hybrid"
            
    # Fallback: if location is explicitly "remote" via normalize_location, it should be handled by normalize_location
    # but we check here for safety
    if "remote" in l:
        return "remote"
        
    return "unknown"

def calculate_quality_score(job: NormalizedJob) -> int:
    """
    Computes quality_score based on Section 5.1.
    """
    score = 0
    desc = job.get("description", "")
    
    # Description >= 200 chars
    if desc and len(desc) >= 200:
        score += 30
    
    # Company exists
    if job.get("company"):
        score += 20
        
    # Salary exists (min or max)
    if job.get("salary_min") is not None or job.get("salary_max") is not None:
        score += 15
        
    # Location exists
    if job.get("location"):
        score += 15
        
    # Apply URL exists
    if job.get("apply_url"):
        score += 10
        
    # Contract/Job type defined
    if job.get("contract_type") != "unknown" or job.get("job_type") != "unknown":
        score += 10
        
    return score

def normalize_reed(job: Dict[str, Any]) -> NormalizedJob:
    """
    Maps Reed API response to NormalizedJob schema (Section 4.1).
    """
    title = job.get("jobTitle", "")
    location = job.get("locationName", "")
    
    # Handle Reed contract mapping
    raw_contract = job.get("contractType", "unknown").lower()
    contract_map = {
        "permanent": "permanent",
        "contract": "contract",
        "temporary": "temporary"
    }
    contract_type = contract_map.get(raw_contract, "unknown")
    
    # Handle Reed job type (boolean fields)
    if job.get("fullTime") is True:
        job_type = "full_time"
    elif job.get("partTime") is True:
        job_type = "part_time"
    else:
        job_type = "unknown"
        
    normalized = {
        "source": "reed",
        "external_id": str(job.get("jobId", "")),
        "title": title,
        "company": job.get("employerName", ""),
        "location": location,
        "location_normalized": normalize_location(location),
        "remote_type": derive_remote_type(title, location),
        "salary_min": job.get("minimumSalary"),
        "salary_max": job.get("maximumSalary"),
        "salary_text": None,
        "salary_currency": "GBP",
        "salary_is_annual": True,
        "contract_type": contract_type,
        "job_type": job_type,
        "description": strip_html(job.get("jobDescription", "")),
        "original_url": job.get("jobUrl"),
        "apply_url": job.get("jobUrl", ""),
        "posted_date": job.get("datePosted"),
        "expiry_date": None,
        "source_quality": {} # To be filled by calculate_quality_score
    }
    
    # Calculate and attach quality score
    score = calculate_quality_score(normalized)
    normalized["source_quality"] = {
        "has_full_description": len(normalized["description"]) >= 200,
        "has_salary": normalized["salary_min"] is not None or normalized["salary_max"] is not None,
        "has_company": bool(normalized["company"]),
        "has_apply_url": bool(normalized["apply_url"]),
        "description_length": len(normalized["description"]),
        "quality_score": score
    }
    
    return normalized

def normalize_adzuna(job: Dict[str, Any]) -> NormalizedJob:
    """
    Maps Adzuna API response to NormalizedJob schema (Section 4.2).
    """
    title = job.get("title", "")
    # Adzuna nested location/company
    loc_data = job.get("location", {})
    comp_data = job.get("company", {})
    location = loc_data.get("display_name", "")
    company = comp_data.get("display_name", "")
    
    # Salary Logic (Section 4.5)
    s_min = job.get("salary_min")
    s_max = job.get("salary_max")
    
    # salary_is_annual logic
    contract_time = job.get("contract_time", "").lower()
    if contract_time in ["daily", "hourly", "part_time"]:
        salary_is_annual = False
    elif contract_time in ["permanent", "contract"]:
        salary_is_annual = True
    else:
        salary_is_annual = True # Default
        
    # salary_text
    salary_text = None
    if job.get("salary_is_flexible"):
        salary_text = "Flexible"
    # Note: In a real API we'd extract the display string if available
    
    # Contract mapping
    raw_contract = job.get("contract_type", "unknown").lower()
    contract_map = {
        "permanent": "permanent",
        "contract": "contract",
        "temporary": "temporary"
    }
    contract_type = contract_map.get(raw_contract, "unknown")
    
    # Job type mapping
    if job.get("part_time") is True:
        job_type = "part_time"
    else:
        job_type = "full_time" if job.get("contract_type") == "permanent" else "unknown"
        
    normalized = {
        "source": "adzuna",
        "external_id": str(job.get("id", "")),
        "title": title,
        "company": company,
        "location": location,
        "location_normalized": normalize_location(location),
        "remote_type": derive_remote_type(title, location),
        "salary_min": s_min,
        "salary_max": s_max,
        "salary_text": salary_text,
        "salary_currency": "GBP",
        "salary_is_annual": salary_is_annual,
        "contract_type": contract_type,
        "job_type": job_type,
        "description": strip_html(job.get("description", "")),
        "original_url": job.get("canonical_url"),
        "apply_url": job.get("redirect_url", ""),
        "posted_date": job.get("date_posted"),
        "expiry_date": None,
        "source_quality": {}
    }
    
    score = calculate_quality_score(normalized)
    normalized["source_quality"] = {
        "has_full_description": len(normalized["description"]) >= 200,
        "has_salary": normalized["salary_min"] is not None or normalized["salary_max"] is not None,
        "has_company": bool(normalized["company"]),
        "has_apply_url": bool(normalized["apply_url"]),
        "description_length": len(normalized["description"]),
        "quality_score": score
    }
    
    return normalized
