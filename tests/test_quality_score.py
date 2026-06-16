import pytest
from src.job_sources.normalize import calculate_quality_score

def test_quality_score_boundaries():
    # Base job with no attributes
    job = {
        "description": "",
        "company": "",
        "salary_min": None,
        "salary_max": None,
        "location": "",
        "apply_url": "",
        "contract_type": "unknown",
        "job_type": "unknown"
    }
    
    # No attributes = 0
    assert calculate_quality_score(job) == 0
    
    # Description boundary
    job["description"] = "a" * 199
    assert calculate_quality_score(job) == 0
    job["description"] = "a" * 200
    assert calculate_quality_score(job) == 30
    
    # Company
    job["company"] = "Some Corp"
    assert calculate_quality_score(job) == 30 + 20
    
    # Salary
    job["salary_min"] = 1000
    assert calculate_quality_score(job) == 30 + 20 + 15
    
    # Location
    job["location"] = "London"
    assert calculate_quality_score(job) == 30 + 20 + 15 + 15
    
    # Apply URL
    job["apply_url"] = "http://apply.com"
    assert calculate_quality_score(job) == 30 + 20 + 15 + 15 + 10
    
    # Type (Permanent/FullTime)
    job["contract_type"] = "permanent"
    assert calculate_quality_score(job) == 30 + 20 + 15 + 15 + 10 + 10
    
    # Final score should be 100
    assert calculate_quality_score(job) == 100

def test_quality_score_combinations():
    # Only description and salary
    job = {
        "description": "a" * 200,
        "company": "",
        "salary_min": 100,
        "salary_max": None,
        "location": "",
        "apply_url": "",
        "contract_type": "unknown",
        "job_type": "unknown"
    }
    assert calculate_quality_score(job) == 30 + 15

    # Only company and URL
    job = {
        "description": "short",
        "company": "Corp",
        "salary_min": None,
        "salary_max": None,
        "location": "",
        "apply_url": "url",
        "contract_type": "unknown",
        "job_type": "unknown"
    }
    assert calculate_quality_score(job) == 20 + 10
