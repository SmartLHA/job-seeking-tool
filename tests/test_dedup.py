import pytest
from src.job_sources.dedup import deduplicate_jobs, compute_description_similarity

def create_mock_job(source="reed", external_id="1", title="BA", company="CompA", location="london", description="Short desc", apply_url=None, salary_min=40000, salary_max=50000, salary_text=None, salary_currency="GBP", salary_is_annual=True, contract_type="permanent", job_type="full_time", posted_date="2026-01-01", original_url=None, remote_type="unknown", expiry_date=None, quality_score=50):
    if apply_url is None:
        apply_url = f"http://{company.lower().replace(' ', '')}.com/{external_id}"
    return {
        "source": source,
        "external_id": external_id,
        "title": title,
        "company": company,
        "location": "London",
        "location_normalized": location,
        "remote_type": remote_type,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_text": salary_text,
        "salary_currency": salary_currency,
        "salary_is_annual": salary_is_annual,
        "contract_type": contract_type,
        "job_type": job_type,
        "description": description,
        "original_url": original_url,
        "apply_url": apply_url,
        "posted_date": posted_date,
        "expiry_date": expiry_date,
        "source_quality": {"quality_score": quality_score, "description_length": len(description)}
    }

def test_within_source_deduplication():
    # Same source, same ID, different descriptions
    job1 = create_mock_job(external_id="1", description="Short description")
    job2 = create_mock_job(external_id="1", description="A much longer and richer description for the same job")
    
    jobs = [job1, job2]
    deduped = deduplicate_jobs(jobs)
    
    assert len(deduped) == 1
    assert deduped[0]["description"] == "A much longer and richer description for the same job"

def test_cross_source_dedup_by_url():
    # Different source, same identity, same URL
    job_reed = create_mock_job(source="reed", external_id="r1", apply_url="http://shared.com/job")
    job_adz = create_mock_job(source="adzuna", external_id="a1", apply_url="http://shared.com/job")
    
    jobs = [job_reed, job_adz]
    deduped = deduplicate_jobs(jobs)
    
    assert len(deduped) == 1
    assert deduped[0]["source"] == "multi_source"
    assert "r1" in deduped[0]["external_id"]
    assert "a1" in deduped[0]["external_id"]

def test_cross_source_dedup_by_similarity():
    # Different source, same identity, different URL, high similarity
    desc1 = "Professional Business Analyst role at TechCorp. Requires SQL, Python and agile experience. 5 years experience."
    desc2 = "Professional Business Analyst role at TechCorp. Requires SQL, Python and agile experience. 5 years experience needed."
    
    job_reed = create_mock_job(source="reed", external_id="r1", description=desc1, apply_url="url_r")
    job_adz = create_mock_job(source="adzuna", external_id="a1", description=desc2, apply_url="url_a")
    
    jobs = [job_reed, job_adz]
    deduped = deduplicate_jobs(jobs)
    
    assert len(deduped) == 1
    assert deduped[0]["source"] == "multi_source"

def test_no_dedup_different_identity():
    # Different company — apply_url must be unique per company to avoid false deduplication
    job1 = create_mock_job(company="CompA", external_id="ext1", apply_url="http://compa-job1.com")
    job2 = create_mock_job(company="CompB", external_id="ext2", apply_url="http://compb-job2.com")
    
    jobs = [job1, job2]
    deduped = deduplicate_jobs(jobs)
    assert len(deduped) == 2

def test_no_dedup_low_similarity():
    # Same identity, but completely different descriptions and URLs
    desc1 = "Experienced BA for finance project."
    desc2 = "Junior BA for retail project."
    
    job_reed = create_mock_job(source="reed", external_id="r1", description=desc1, apply_url="url_r")
    job_adz = create_mock_job(source="adzuna", external_id="a1", description=desc2, apply_url="url_a")
    
    jobs = [job_reed, job_adz]
    deduped = deduplicate_jobs(jobs)
    assert len(deduped) == 2

def test_multi_source_resolution():
    # Test merging logic
    job_reed = create_mock_job(
        source="reed", 
        external_id="r1", 
        description="Short", 
        salary_min=40000,
        salary_max=None,
        posted_date=None
    )
    job_adz = create_mock_job(
        source="adzuna", 
        external_id="a1", 
        description="Longer description that should win", 
        salary_min=None,
        salary_max=50000,
        posted_date="2026-04-01"
    )
    # Force identity match
    job_reed["title"] = job_adz["title"]
    job_reed["company"] = job_adz["company"]
    job_reed["location_normalized"] = job_adz["location_normalized"]
    job_reed["apply_url"] = job_adz["apply_url"] = "same_url"
    
    jobs = [job_reed, job_adz]
    deduped = deduplicate_jobs(jobs)
    
    res = deduped[0]
    assert res["source"] == "multi_source"
    assert res["description"] == "Longer description that should win"
    assert res["salary_min"] == 40000
    assert res["salary_max"] == 50000
    assert res["posted_date"] == "2026-04-01"
    assert "r1" in res["external_id"] and "a1" in res["external_id"]

def test_compute_description_similarity():
    # Exact match
    assert compute_description_similarity("The quick brown fox", "The quick brown fox") == 1.0
    # No match
    assert compute_description_similarity("Apple", "Banana") == 0.0
    # Partial match
    # "quick brown fox" vs "quick brown dog"
    # tokens: {quick, brown, fox} vs {quick, brown, dog}
    # inter: {quick, brown} (2), union: {quick, brown, fox, dog} (4) -> 0.5
    s1 = "The quick brown fox"
    s2 = "The quick brown dog"
    assert compute_description_similarity(s1, s2) == 0.5
    # Empty
    assert compute_description_similarity("", "") == 1.0
    assert compute_description_similarity("something", "") == 0.0
