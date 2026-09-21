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

def _identity_fields(job: dict) -> tuple[str, str, str, str, str, str]:
    """Extract (external_id, title_norm, company_norm, location_norm, url,
    description) from a job dict.

    Centralises the identity/duplicate logic so it works for BOTH the
    pipeline's ``NormalizedJob`` schema (``external_id``/``location_normalized``/
    ``apply_url``/``description``) AND the UI search-result dict schema used by
    ``ui_handlers.handle_source_search`` (``source_job_id``/``location``/``url``/
    ``description_raw``). Callers elsewhere (e.g. Slice B "seen" tracking in
    ``ui_handlers``) reuse this instead of reimplementing the key."""
    eid = str(job.get("external_id") or job.get("source_job_id") or "")
    title_norm = (job.get("title") or "").lower().strip()
    company_norm = (job.get("company") or "").lower().strip()
    loc_norm = (job.get("location_normalized") or job.get("location") or "").lower().strip()
    url = job.get("apply_url") or job.get("url") or ""
    description = job.get("description") or job.get("description_raw") or job.get("description_preview") or ""
    return eid, title_norm, company_norm, loc_norm, url, description


def is_duplicate_job(job: dict, existing: dict) -> bool:
    """True if `job` and `existing` identify the same posting per Section 6:
    same (title, company, normalised location) AND (same apply URL OR >=80%
    description similarity). Reused by dedup within a batch and by Slice B's
    cross-page "already shown" check in ui_handlers."""
    _, title_norm, comp_norm, loc_norm, url, description = _identity_fields(job)
    _, e_title, e_comp, e_loc, e_url, e_desc = _identity_fields(existing)
    if not (title_norm == e_title and comp_norm == e_comp and loc_norm == e_loc):
        return False
    if url and url == e_url:
        return True
    return compute_description_similarity(description, e_desc) >= 0.80


def deduplicate_jobs(jobs: List[NormalizedJob]) -> List[NormalizedJob]:
    """
    Deduplicates jobs across and within sources based on Section 6.

    Works on the full ``NormalizedJob`` schema (used by the CLI orchestrator)
    and on the leaner UI search-result dict schema (used by
    ``ui_handlers.handle_source_search``) — fields that only exist on one
    schema are simply skipped via ``dict.get``/``"key" in dict`` guards so
    behaviour for the full schema is unchanged.
    """
    # 1. Within-source deduplication (using external_id)
    source_buckets: dict[str, dict[str, dict]] = {}
    for job in jobs:
        src = job.get("source", "")
        eid, _, _, _, _, description = _identity_fields(job)
        bucket = source_buckets.setdefault(src, {})

        existing_in_bucket = bucket.get(eid)
        if existing_in_bucket is None:
            bucket[eid] = job
        else:
            _, _, _, _, _, existing_description = _identity_fields(existing_in_bucket)
            # Keep the one with the longer description if ID collisions occur
            if len(description) > len(existing_description):
                bucket[eid] = job

    # Flatten to a single list of unique-per-source jobs
    unique_per_source = []
    for src_jobs in source_buckets.values():
        unique_per_source.extend(src_jobs.values())

    # 2. Cross-source deduplication
    final_jobs = []

    for job in unique_per_source:
        eid, _, _, _, _, description = _identity_fields(job)
        is_duplicate = False
        duplicate_index = -1

        for i, existing in enumerate(final_jobs):
            if is_duplicate_job(job, existing):
                is_duplicate = True
                duplicate_index = i
                break

        if is_duplicate:
            # Multi-source resolution (Section 6.2)
            existing = final_jobs[duplicate_index]
            _, _, _, _, _, existing_description = _identity_fields(existing)

            # Keep richer description
            if len(description) > len(existing_description) and "description" in existing:
                existing["description"] = job.get("description", description)
                if isinstance(existing.get("source_quality"), dict):
                    existing["source_quality"]["description_length"] = len(description)

            # Set source to multi_source
            existing["source"] = "multi_source"

            # Merge external IDs - store as pipe-separated string (only when
            # this schema tracks external_id at all)
            if "external_id" in existing:
                existing_ids = existing["external_id"].split("|") if "|" in existing["external_id"] else [existing["external_id"]]
                if eid not in existing_ids:
                    existing_ids.append(eid)
                existing["external_id"] = "|".join(existing_ids)

            # Merge quality score (max)
            if isinstance(existing.get("source_quality"), dict) and isinstance(job.get("source_quality"), dict):
                existing["source_quality"]["quality_score"] = max(
                    existing["source_quality"]["quality_score"],
                    job["source_quality"]["quality_score"],
                )

            # Prefer non-null fields (NormalizedJob-only fields; no-op if the
            # schema doesn't carry them)
            for field in ["salary_min", "salary_max", "salary_text", "posted_date"]:
                if field in existing and existing.get(field) is None and job.get(field) is not None:
                    existing[field] = job[field]
        else:
            final_jobs.append(job)

    return final_jobs
