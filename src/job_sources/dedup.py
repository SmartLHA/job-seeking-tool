from typing import List, Set
from .normalize import NormalizedJob

# Simple English stopword list for similarity check
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when", "at", "from", "by", "for", "with", "about", "against", "between", "into", "through", "during", "before", "after", "above", "below", "to", "of", "in", "on", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "having", "do", "does", "did", "doing", "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your", "yours", "yourself", "yourselves", "he", "him", "his", "himself", "she", "her", "hers", "herself", "it", "its", "itself", "they", "them", "their", "theirs", "themselves", "what", "which", "who", "whom", "this", "that", "these", "those", "am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "having", "do", "does", "did", "doing"
}

def tokenize(text: str) -> Set[str]:
    """
    Converts text to a set of lowercased alphanumeric tokens, removing stopwords.
    """
    if not text:
        return set()
    # Lowercase and split by non-alphanumeric characters
    tokens = re.findall(r'\w+', text.lower())
    return {t for t in tokens if t not in STOPWORDS}

import re

def compute_description_similarity(desc1: str, desc2: str) -> float:
    """
    Computes Jaccard similarity between two descriptions based on word tokens.
    """
    set1 = tokenize(desc1)
    set2 = tokenize(desc2)
    
    if not set1 and not set2:
        return 1.0
    if not set1 or not set2:
        return 0.0
        
    intersection = set1.intersection(set2)
    union = set1.union(set2)
    
    return len(intersection) / len(union)

def deduplicate_jobs(jobs: List[NormalizedJob]) -> List[NormalizedJob]:
    """
    Deduplicates jobs across and within sources based on Section 6.
    """
    # 1. Within-source deduplication (using external_id)
    source_buckets = {}
    for job in jobs:
        src = job["source"]
        eid = job["external_id"]
        if src not in source_buckets:
            source_buckets[src] = {}
        
        # Keep the one with the longer description if ID collisions occur
        if eid not in source_buckets[src] or len(job["description"]) > len(source_buckets[src][eid]["description"]):
            source_buckets[src][eid] = job
            
    # Flatten to a single list of unique-per-source jobs
    unique_per_source = []
    for src_jobs in source_buckets.values():
        unique_per_source.extend(src_jobs.values())
        
    # 2. Cross-source deduplication
    final_jobs = []
    
    for job in unique_per_source:
        is_duplicate = False
        duplicate_index = -1
        
        # Normalize current job for comparison
        title_norm = job["title"].lower().strip()
        comp_norm = job["company"].lower().strip()
        loc_norm = job["location_normalized"].lower().strip()
        url = job["apply_url"]
        
        for i, existing in enumerate(final_jobs):
            # Check basic identity
            if (title_norm == existing["title"].lower().strip() and
                comp_norm == existing["company"].lower().strip() and
                loc_norm == existing["location_normalized"].lower().strip()):
                
                # Check URLs or description similarity
                if url and url == existing["apply_url"]:
                    is_duplicate = True
                    duplicate_index = i
                    break
                
                similarity = compute_description_similarity(job["description"], existing["description"])
                if similarity >= 0.80:
                    is_duplicate = True
                    duplicate_index = i
                    break
        
        if is_duplicate:
            # Multi-source resolution (Section 6.2)
            existing = final_jobs[duplicate_index]
            
            # Keep richer description
            if len(job["description"]) > len(existing["description"]):
                existing["description"] = job["description"]
                existing["source_quality"]["description_length"] = len(job["description"])
            
            # Set source to multi_source
            existing["source"] = "multi_source"
            
            # Merge external IDs - store as pipe-separated string
            existing_ids = existing["external_id"].split("|") if "|" in existing["external_id"] else [existing["external_id"]]
            new_id = job["external_id"]
            if new_id not in existing_ids:
                existing_ids.append(new_id)
            existing["external_id"] = "|".join(existing_ids)
            
            # Merge quality score (max)
            existing["source_quality"]["quality_score"] = max(
                existing["source_quality"]["quality_score"], 
                job["source_quality"]["quality_score"]
            )
            
            # Prefer non-null fields
            for field in ["salary_min", "salary_max", "salary_text", "posted_date"]:
                if existing[field] is None and job[field] is not None:
                    existing[field] = job[field]
        else:
            final_jobs.append(job)
            
    return final_jobs
