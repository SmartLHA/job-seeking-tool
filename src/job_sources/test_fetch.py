import os
from src.job_sources.reed_client import fetch_reed_jobs
from src.job_sources.adzuna_client import fetch_adzuna_jobs
from src.job_sources.normalize import normalize_reed, normalize_adzuna
from src.job_sources.dedup import deduplicate_jobs

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv():
        return False

def main():
    load_dotenv()
    
    keyword = "Business Analyst"
    location = "London"
    
    print(f"Searching for '{keyword}' in '{location}'...")
    
    # 1. Fetch
    print("Fetching from Reed...")
    raw_reed = fetch_reed_jobs(keyword, location)
    print(f"Fetched {len(raw_reed)} raw jobs from Reed.")
    
    print("Fetching from Adzuna...")
    raw_adzuna = fetch_adzuna_jobs(keyword, location)
    print(f"Fetched {len(raw_adzuna)} raw jobs from Adzuna.")
    
    # 2. Normalize
    print("Normalizing jobs...")
    norm_reed = [normalize_reed(j) for j in raw_reed]
    norm_adzuna = [normalize_adzuna(j) for j in raw_adzuna]
    
    print(f"Normalized {len(norm_reed)} Reed jobs.")
    print(f"Normalized {len(norm_adzuna)} Adzuna jobs.")
    
    # 3. Deduplicate
    print("Deduplicating...")
    all_jobs = norm_reed + norm_adzuna
    final_jobs = deduplicate_jobs(all_jobs)
    
    print(f"Final unique job count: {len(final_jobs)}")
    print("-" * 80)
    print(f"{'Title':<40} | {'Company':<20} | {'Loc':<10} | {'Src':<10} | {'Score':<5}")
    print("-" * 80)
    
    # Sort by quality score for the top 5
    sorted_jobs = sorted(final_jobs, key=lambda x: x["source_quality"]["quality_score"], reverse=True)
    
    for job in sorted_jobs[:5]:
        title = job["title"][:37] + "..." if len(job["title"]) > 37 else job["title"]
        company = job["company"][:17] + "..." if len(job["company"]) > 17 else job["company"]
        loc = job["location_normalized"][:10]
        src = job["source"]
        score = job["source_quality"]["quality_score"]
        print(f"{title:<40} | {company:<20} | {loc:<10} | {src:<10} | {score:<5}")

if __name__ == "__main__":
    main()
