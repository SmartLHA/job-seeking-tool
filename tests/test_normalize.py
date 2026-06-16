import pytest
from src.job_sources.normalize import (
    normalize_location, 
    derive_remote_type, 
    calculate_quality_score, 
    normalize_reed, 
    normalize_adzuna,
    strip_html
)

def test_strip_html():
    html_input = "<p>Hello <b>World</b></p><br>Next line."
    expected = "Hello World\nNext line."
    assert strip_html(html_input) == expected
    
    assert strip_html(None) == ""
    assert strip_html("") == ""

def test_normalize_location():
    # Aliases
    assert normalize_location("Greater London") == "london"
    assert normalize_location("UK") == "united kingdom"
    assert normalize_location("Work from home") == "remote"
    
    # Suffixes
    assert normalize_location("London UK") == "london"
    assert normalize_location("Manchester England") == "manchester"
    
    # Unknown/Empty
    assert normalize_location("") == "unknown"
    assert normalize_location(None) == "unknown"
    assert normalize_location("Unknown City") == "unknown city"

def test_derive_remote_type():
    # Title priority
    assert derive_remote_type("Remote Business Analyst", "London") == "remote"
    assert derive_remote_type("Hybrid Project Manager", "Manchester") == "hybrid"
    
    # Location fallback
    assert derive_remote_type("Business Analyst", "Remote") == "remote"
    assert derive_remote_type("Project Manager", "Hybrid Office") == "hybrid"
    
    # Unknown
    assert derive_remote_type("Developer", "London") == "unknown"
    assert derive_remote_type(None, None) == "unknown"

def test_calculate_quality_score():
    # Base case: minimal data
    job_min = {
        "description": "Too short",
        "company": "",
        "salary_min": None,
        "salary_max": None,
        "location": "",
        "apply_url": "",
        "contract_type": "unknown",
        "job_type": "unknown"
    }
    assert calculate_quality_score(job_min) == 0
    
    # Boundary: description length 200
    job_desc_short = job_min.copy()
    job_desc_short["description"] = "a" * 199
    assert calculate_quality_score(job_desc_short) == 0
    
    job_desc_long = job_min.copy()
    job_desc_long["description"] = "a" * 200
    assert calculate_quality_score(job_desc_long) == 30
    
    # Full case
    job_full = {
        "description": "a" * 200,
        "company": "TechCorp",
        "salary_min": 50000,
        "salary_max": 60000,
        "location": "London",
        "apply_url": "http://apply.com",
        "contract_type": "permanent",
        "job_type": "full_time"
    }
    # 30 (desc) + 20 (comp) + 15 (salary) + 15 (loc) + 10 (url) + 10 (type) = 100
    assert calculate_quality_score(job_full) == 100

def test_normalize_reed():
    reed_data = {
        "jobId": 12345,
        "jobTitle": "Business Analyst",
        "locationName": "London UK",
        "employerName": "Reed Company",
        "contractType": "Permanent",
        "fullTime": True,
        "partTime": False,
        "minimumSalary": 40000,
        "maximumSalary": 50000,
        "jobDescription": "<p>A very long description that exceeds two hundred characters to ensure that the quality score for the description length is correctly calculated as thirty points. This is just filler text to reach the length requirement.</p>",
        "jobUrl": "http://reed.co.uk/job/12345",
        "datePosted": "2026-04-01"
    }
    
    normalized = normalize_reed(reed_data)
    assert normalized["source"] == "reed"
    assert normalized["external_id"] == "12345"
    assert normalized["location_normalized"] == "london"
    assert normalized["remote_type"] == "unknown"
    assert normalized["salary_min"] == 40000
    assert normalized["source_quality"]["quality_score"] >= 80
    assert "Reed Company" in normalized["company"]

def test_normalize_adzuna():
    adzuna_data = {
        "id": "adz_6789",
        "title": "Hybrid Project Manager",
        "location": {"display_name": "Manchester England"},
        "company": {"display_name": "Adzuna Corp"},
        "salary_min": 45000,
        "salary_max": 55000,
        "salary_is_flexible": True,
        "contract_type": "permanent",
        "contract_time": "permanent",
        "part_time": False,
        "description": "A very long description that exceeds two hundred characters to ensure that the quality score for the description length is correctly calculated as thirty points. This is just filler text to reach the length requirement.",
        "canonical_url": "http://adzuna.co.uk/job/6789",
        "redirect_url": "http://apply-adzuna.com/6789",
        "date_posted": "2026-04-02"
    }
    
    normalized = normalize_adzuna(adzuna_data)
    assert normalized["source"] == "adzuna"
    assert normalized["external_id"] == "adz_6789"
    assert normalized["location_normalized"] == "manchester"
    assert normalized["remote_type"] == "hybrid"
    assert normalized["salary_text"] == "Flexible"
    assert normalized["source_quality"]["quality_score"] >= 80
