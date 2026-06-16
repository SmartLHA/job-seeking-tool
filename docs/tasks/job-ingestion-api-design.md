# Job Ingestion API Design
**Status:** Draft v2 — updated after Helpo review; pending re-confirmation
**Date:** 2026-04-28
**Supersedes:** Generic URL/manual-only ingestion described in `data_contract.md` (JobPosting contract fields remain valid; this adds API sourcing layer)

---

## 1. Official MVP Job Sources

### 1.1 Primary: Reed (`reed.co.uk`)
- **API:** `https://www.reed.co.uk/api/developer/v1/`
- **Auth:** `REED_API_KEY` (Reed account required; free tier available)
- **Strengths:** UK-specific, full job metadata including salary, contract type, location
- **Coverage:** Broad UK coverage; listings include recruiter info
- **Rate limit note:** Free tier has per-key limits; design must handle 429 gracefully
- **Docs:** https://www.reed.co.uk/developers

### 1.2 Secondary: Adzuna (`adzuna.com`)
- **API:** `https://api.adzuna.com/overview`
- **Auth:** `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` (free registration)
- **Strengths:** Aggregates across multiple UK job boards; good for breadth
- **Coverage:** Aggregated from many sources; descriptions vary in completeness
- **Docs:** https://developer.adzuna.com/overview

### 1.3 Future Optional Sources (NOT in MVP scope)
- DevITjobs UK — tech-focused
- Findwork — aggregated
- Jooble — aggregated
- These may be added after MVP is validated

### 1.4 Explicit MVP Exclusions
- **LinkedIn scraping** — not permitted at MVP; user may paste job text manually
- **Indeed scraping** — not permitted at MVP; user may paste job text manually
- **Generic web scraping** — not in scope; URL ingestion via paste is out-of-scope for API design (see `job_hunt_paste_fetch.py` for existing URL fetch if ever re-enabled)

---

## 2. Job Fetcher Agent — Updated Design

### 2.1 Responsibilities
1. Fetch jobs from Reed API by keyword + location
2. Fetch jobs from Adzuna API by keyword + location
3. Accept manual job input as fallback
4. Normalize all source outputs into the internal NormalizedJob schema (Section 3)
5. Deduplicate jobs across sources
6. Attach source metadata and source quality score

### 2.2 API Fetching Design

**Reed API endpoint pattern:**
```
GET https://www.reed.co.uk/api/1.0/search?keywords={kw}&location={loc}&distance={r}&resultsToTake={n}
```

**Adzuna API endpoint pattern:**
```
GET https://api.adzuna.com/1/data/gb/jobs?app_id={APP_ID}&app_key={APP_KEY}&what={kw}&where={loc}&distance={r}&max_results={n}
```

**Fetch strategy per run:**
- Fire Reed and Adzuna requests in parallel
- If one source fails, log error and continue with the other; do not abort run
- Respect per-source rate limits; back off on 429
- Cap each source at `MAX_JOBS_PER_SOURCE_PER_RUN` (configurable)

**MVP pagination scope:** MVP is strictly limited to **a single API call per source per run** (max 50 jobs). Multi-page/pagination fetching is out of scope for MVP. Rationale: keeps the MVP simple, 50 jobs is sufficient for a focused daily run, and pagination adds complexity (cursor management, deduplication across pages) that can be added in v1.1 if needed.

**Manual fallback:**
- User may paste job text or JSON at any time
- Manual jobs bypass quality gating (treated as trusted user input)

### 2.3 Normalization
Each raw API response is normalized into NormalizedJob schema (Section 3).
Field mapping per source is defined in Section 4.

### 2.4 Deduplication
See Section 6 for full deduplication rules.

### 2.5 Source Quality Scoring
See Section 5 for quality_score rules.
Jobs with `quality_score < 40` are flagged and may be excluded from automated analysis unless manually enriched.

---

## 3. NormalizedJob Schema

```json
{
  "source": "reed | adzuna | manual",
  "external_id": "string",
  "title": "string",
  "company": "string",
  "location": "string",
  "location_normalized": "string",
  "remote_type": "onsite | hybrid | remote | unknown",
  "salary_min": "number | null",
  "salary_max": "number | null",
  "salary_text": "string | null",
  "salary_currency": "GBP | null",
  "salary_is_annual": true,
  "contract_type": "permanent | contract | temporary | unknown",
  "job_type": "full_time | part_time | unknown",
  "description": "string",
  "original_url": "string | null",
  "apply_url": "string",
  "posted_date": "string | null",
  "expiry_date": "string | null",
  "source_quality": {
    "has_full_description": true,
    "has_salary": true,
    "has_company": true,
    "has_apply_url": true,
    "description_length": 0,
    "quality_score": 0
  }
}
```

**Field notes:**
- `external_id`: raw ID from source API (reed: integer job ID; adzuna: adzuna ID string)
- `location`: original raw location string from API
- `location_normalized`: location string passed through `normalize_location()` — see Section 6.4 for strategy
- `remote_type`: derived via `derive_remote_type()` — see Section 4.4 for keyword rules
- `salary_min` / `salary_max`: annual GBP; null if not provided or not parseable; parsed per Section 4.5
- `salary_text`: original salary display string from source (e.g. "£50,000 - £70,000", "Up to £60k", "Competitive", "Negotiable")
- `salary_currency`: ISO 4217 currency code; for UK job sources default `"GBP"`
- `salary_is_annual`: `true` for Reed (always annual); `true` for Adzuna unless source explicitly marks as daily/hourly; `null` if unknown
- `posted_date`: ISO-8601 datetime string with timezone (`2026-04-28T09:00:00Z`); time portion defaulted to `00:00:00Z` if source only provides date
- `original_url`: URL to the raw job listing page on the source site; may differ from `apply_url`; `null` if not available
- `description`: cleaned plain text (HTML stripped per Section 4.6); never null (empty string if unavailable)
- `apply_url`: URL that submits the job application; may be an affiliate/redirect link

---

## 4. Source Field Mapping

### 4.1 Reed API → NormalizedJob

| NormalizedJob field | Reed API field | Notes |
|--------------------|----------------|-------|
| source | `"reed"` (constant) | |
| external_id | `jobId` (integer) | |
| title | `jobTitle` | |
| company | `employerName` | |
| location | `locationName` | |
| location_normalized | `locationName` → normalize_location() | see Section 6.4 |
| remote_type | derived via `derive_remote_type()` | see Section 4.4 |
| salary_min | `minimumSalary` | annual GBP; null if absent |
| salary_max | `maximumSalary` | annual GBP; null if absent |
| salary_text | null | Reed provides numeric range only |
| salary_currency | `"GBP"` | Reed always returns GBP |
| salary_is_annual | `true` | Reed always states annual salary |
| contract_type | `contractType` → mapped | permanent/contract/temporary/unknown |
| job_type | `fullTime`/`partTime` boolean | full_time/part_time/unknown |
| description | `jobDescription` | HTML stripped per Section 4.6 |
| original_url | `jobUrl` | same as apply_url for Reed |
| apply_url | `jobUrl` | |
| posted_date | `datePosted` → ISO-8601 datetime | |
| expiry_date | null | |

### 4.2 Adzuna API → NormalizedJob

| NormalizedJob field | Adzuna API field | Notes |
|--------------------|-------------------|-------|
| source | `"adzuna"` (constant) | |
| external_id | `id` (string) | |
| title | `title` | |
| company | `company.display_name` | |
| location | `location.display_name` | |
| location_normalized | `location.display_name` → normalize_location() | see Section 6.4 |
| remote_type | derived via `derive_remote_type()` | see Section 4.4 |
| salary_min | `salary_min` | GBP; null if absent |
| salary_max | `salary_max` | GBP; null if absent |
| salary_text | `salary_is_flexible` ? "Flexible" : null | or original salary_display string |
| salary_currency | `"GBP"` | default for country=gb |
| salary_is_annual | `contract_time` field: daily/hourly/part_time → false; otherwise true | null if cannot determine |
| contract_type | `contract_type` → mapped | |
| job_type | `part_time` boolean | full_time/part_time/unknown |
| description | `description` | HTML stripped per Section 4.6 |
| original_url | derived from `canonical_url` or `adref` if present | else null |
| apply_url | `redirect_url` | may be affiliate/redirect |
| posted_date | `date_posted` → ISO-8601 datetime | time portion defaulted |
| expiry_date | null | not reliably available |

### 4.3 Manual → NormalizedJob

### 4.3 Manual → NormalizedJob
- `source` = `"manual"`
- All fields from user input; missing fields null
- `source_quality` computed same as API sources
- Manual jobs are always accepted (user is trusted source)

### 4.4 `remote_type` Derivation Rules

`remote_type` is derived from the job `title` and `location` strings (case-insensitive).
The check proceeds in order; first matching rule wins:

| remote_type | Trigger keywords in title OR location |
|-------------|---------------------------------------|
| `remote` | `"remote"`, `"work from home"`, `"wfh"`, `"fully remote"`, `"home-based"`, `"anywhere"` |
| `hybrid` | `"hybrid"` |
| `onsite` | explicit city/region name without remote qualifiers (fallback) |
| `unknown` | no match found, or keyword is ambiguous (e.g. "flexible" alone) |

**Rules:**
- If title contains a remote keyword, it overrides location (a "Remote London" job is `remote`, not `onsite`)
- If only location contains a keyword (e.g. "Work from Home Resourcer"), derive from location
- **"flexible" is ambiguous** — can refer to hours, location, or salary; it is NOT a trigger for any `remote_type` value and always yields `unknown`
- `remote_type` may be `unknown` even when other fields are rich; this is acceptable

### 4.5 Salary Parsing Rules

**Reed:** `minimumSalary` and `maximumSalary` are always annual GBP integers — no parsing needed.

**Adzuna:** `salary_min` and `salary_max` may be null. When present:
- Values are assumed GBP for `country=gb`
- `salary_is_annual` defaults to `true`
- Set `salary_is_annual = false` only if `contract_time` field (Adzuna specific) is one of: `"daily"`, `"hourly"`, `"part_time"`
- If `contract_time` is absent or is `"permanent"`/`"contract"`, keep `salary_is_annual = true`

**Handling edge cases:**
| Input pattern | salary_text | salary_min | salary_max | Notes |
|---------------|-------------|-----------|-----------|-------|
| "Up to £60,000" | "Up to £60,000" | null | 60000 | max only |
| "£40k - £50k" | "£40k - £50k" | 40000 | 50000 | strip "k" |
| "Competitive" | "Competitive" | null | null | no numeric extraction |
| "Negotiable" | "Negotiable" | null | null | no numeric extraction |
| "£300/day" | "£300/day" | 300 | null | note daily rate; salary_is_annual=false |
| "£25/hour" | "£25/hour" | 25 | null | note hourly rate; salary_is_annual=false |
| "£60,000 - £80,000 per annum" | "£60,000 - £80,000 per annum" | 60000 | 80000 | annual confirmed |
| "Range: £55-65k" | "Range: £55-65k" | 55000 | 65000 | extract numeric range |

**Normalization:**
- Strip `£`, `k`, `,`, spaces before parsing
- Convert "per annum", "per year" → annual
- Convert "per day" / "per hour" → note in `salary_text`; `salary_is_annual=false`

### 4.6 HTML Description Stripping

Strip all HTML tags using a standard library (e.g. `html.parser`, `bleach.clean`).

**Preserve:**
- All plain text content
- URLs in `href` attributes → converted to inline links `[text](url)` if the link text is meaningful

**Remove:**
- All HTML tags (`<div>`, `<p>`, `<li>`, `<br>`, etc.)
- Inline styles, classes, IDs
- Images and their `alt` text (unless the alt text is the only content in that block)
- Video embeds and iframes
- JavaScript and `<script>` blocks
- CSS blocks

**Result:** Clean plain text with paragraph breaks preserved (double newline between blocks).

---

## 5. Source Quality Rules

### 5.1 Quality Score Calculation

`quality_score` is computed as the sum of the following components:

| Condition | Points |
|-----------|--------|
| description exists AND `len(description) >= 200` chars | +30 |
| company exists and non-empty | +20 |
| salary_min OR salary_max exists | +15 |
| location exists and non-empty | +15 |
| apply_url exists and is a valid URL | +10 |
| contract_type != unknown OR job_type != unknown | +10 |
| **Maximum possible** | **100** |

### 5.2 Quality Score Thresholds

| quality_score range | Eligibility |
|--------------------|-------------|
| >= 70 | **Eligible** for automated analysis and CV tailoring |
| 40–69 | **Restricted**: analysis allowed; decision must be `Review`; do not `Apply` automatically |
| < 40 | **Excluded**: skip from automated run; flag for manual enrichment |

### 5.3 Quality Gating in Decision Engine
See Section 7 for Decision Engine integration.

---

## 6. Deduplication Rules

### 6.1 Deduplication Key
A job is considered a duplicate if ALL of the following are true:
1. Normalized title matches (case-insensitive, stripped)
2. Normalized company matches (case-insensitive, stripped)
3. `location_normalized` matches (case-insensitive, after normalization)
4. AND either:
   - `apply_url` is identical, OR
   - description similarity score >= 0.80 (Jaccard on word tokens, after stopword removal)

**Note:** Similarity threshold reduced from 0.85 to 0.80 to catch minor rephrasing while avoiding false positives.

### 6.2 Multi-Source Duplicate Resolution
If the same job appears in both Reed and Adzuna:
- Keep the record with the richer `description` (higher `description_length`)
- Retain both `source` references (set `source` to `"multi_source"`)
- Merge `source_quality`: take the maximum `quality_score` across both
- Prefer salary/location fields that are more complete (non-null)
- Attach both original `external_id` values as `["reed:<id>", "adzuna:<id>"]`

### 6.3 Within-Source Deduplication
- Reed may return the same job ID in paginated results — use `external_id` as primary key
- Adzuna may return the same job ID across searches — use `external_id` as primary key
- Deduplicate within each source before merging across sources

### 6.4 Location Normalization Strategy

Before location matching, run `normalize_location()`:

1. **Lowercase + strip**: `" Greater London, UK "` → `"greater london uk"`
2. **Alias table** (MVP hardcoded map, extendable):
   | Raw | Normalized |
   |-----|-----------|
   | `"greater london"` | `"london"` |
   | `"london, city of london"` | `"london"` |
   | `"london (central)"` | `"london"` |
   | `"england"` | `"united kingdom"` |
   | `"scotland"` | `"united kingdom"` |
   | `"wales"` | `"united kingdom"` |
   | `"uk"` | `"united kingdom"` |
   | `"united kingdom"` | `"united kingdom"` |
   | `" remote "` | `"remote"` |
   | `"work from home"` | `"remote"` |
3. **Strip common suffixes**: `"london uk"` → `"london"` (remove country suffixes for city names)
4. **Remote special case**: any normalized location matching `"remote"` is treated as `remote_type="remote"` regardless of keywords in title

**Unknown value tracking:** High frequency of `unknown` in `remote_type` should be logged and metric-tracked (see Section 8.5) to identify when derivation rules need updating.

### 6.5 Unknown Value Tracking

Log and count occurrences of `unknown` values per field per run:
- `remote_type = unknown`
- `contract_type = unknown`
- `job_type = unknown`
- `salary_min = null` AND `salary_max = null`

**Threshold:** If any field has `unknown` rate > 50% across a run, emit a warning metric. This signals that:
- API field mapping may have drifted (schema change)
- Derivation rules need new keywords
- A data quality report should flag this to the user

---

## 7. Decision Engine — Updated Logic

### 7.1 Match Score Thresholds (Existing, Unchanged)
| match_score | Decision |
|-------------|----------|
| >= 80 | `apply` |
| 65–79 | `review` |
| < 65 | `skip` |

### 7.2 New: Source Quality Gating

The following rules override the match-score-based decision:

**Rule A: High match, low quality → force Review**
- If `match_score >= 80` AND `source_quality.quality_score < 70`:
  → Override: decision must be `review`, not `apply`
  → Reason: "High match but insufficient source quality; manual verification required"

**Rule B: Missing description**
- If `description` is empty or `len(description) < 100`:
  → Decision must be `review` or `skip`, never `apply`
  → Reason: "Insufficient description to verify claims"

**Rule C: Apply-gated on quality**
- Tailored CV and cover letter generation is only triggered for:
  - `decision = apply` AND `source_quality.quality_score >= 70`
  - `decision = review` AND user manually selects for tailoring

**Rule D: Explicit rejection**
- Jobs with `quality_score < 40` are excluded before reaching Decision Engine
- They appear in output as `skipped_low_quality: true`

### 7.3 Combined Decision Logic (Pseudocode)

```
function decide(job, match_score):
    if job.source_quality.quality_score < 40:
        return decision="skip", reason="low_source_quality", skipped_low_quality=true

    if len(job.description) < 100:
        if match_score >= 65:
            return decision="review", reason="insufficient_description"
        else:
            return decision="skip", reason="insufficient_description"

    base = match_score_to_decision(match_score)  # apply/review/skip per thresholds

    if base == "apply" and job.source_quality.quality_score < 70:
        return decision="review", reason="source_quality_overrides_apply"

    return decision=base, reason=match_reason
```

---

## 8. Configuration Requirements

### 8.1 Required Environment Variables (stored in `.env`, excluded from git)

```bash
REED_API_KEY=          # Reed API key from reed.co.uk/developers
ADZUNA_APP_ID=         # Adzuna app ID from developer.adzuna.com
ADZUNA_APP_KEY=        # Adzuna app key
```

### 8.2 Config File (`config.json` or `config.yaml`, in repo)

```yaml
job_sources:
  default_country: "gb"           # ISO 3166-1 alpha-2
  default_location: "London"      # user-configurable
  search_keywords:
    - "Business Analyst"
    - "Product Owner"
    - "Data Analyst"
  max_jobs_per_source_per_run: 50
  min_source_quality_score: 40    # jobs below this are flagged but not excluded from report
  apply_quality_threshold: 70     # quality_score must be >= 70 for automated Apply
```

### 8.3 Security Rules
- API keys stored in `.env` only; `.env` in `.gitignore`
- Keys never logged, never in prompts, never in reports
- Raw API responses stored locally for debugging (`/data/raw/reed/`, `/data/raw/adzuna/`)
- Analysis uses only normalized schema

### 8.4 Raw Data Retention Policy
- `/data/raw/reed/` and `/data/raw/adzuna/` store raw JSON responses per run (timestamped)
- Retention: **7 days** for raw data (auto-cleaned by Cache Layer Cleanup cron job)
- Access: same machine only; not synced to cloud; not accessible via UI
- Files are gzip-compressed to reduce disk usage

### 8.5 API Schema Drift Strategy
- Each run logs the API response schema fingerprint (keys present, types)
- On schema change detection (new required field missing, unexpected field type), emit a warning: `"[SCHEMA DRIFT] Reed API field 'newField' not found"`
- Mapping code should have default values for unmapped fields (never raise on missing field)
- Version the field mapping per source: `reed_map_v1`, `adzuna_map_v1`; bump version on breaking change
- A schema drift event triggers a non-blocking warning in the daily report

---

## 9. Orchestration Flow

```
Load config (keywords, location, thresholds)
         ↓
  Fetch Reed jobs (parallel)
         ↓
  Fetch Adzuna jobs (parallel)
         ↓
 Normalize Reed → NormalizedJob[]
 Normalize Adzuna → NormalizedJob[]
         ↓
 Deduplicate across sources
         ↓
 Calculate source_quality for each job
         ↓
 Filter: exclude quality_score < 40 (log, do not fail)
         ↓
 For each eligible job:
   Run Job Analyzer → match_score, score_breakdown
         ↓
   Decision Engine (match_score + quality gating)
         ↓
 For each Apply decision (quality_score >= 70):
   Generate Tailored CV
   Generate Cover Letter
 For each Review decision:
   Flag for manual shortlist; do not auto-generate
         ↓
 Save daily report (JSON + human-readable summary)
```

**Note:** Reed API failure does NOT stop the run; Adzuna continues. Reverse also true. Manual input always available as fallback.

---

## 10. Test Cases

### 10.1 Reed Job Normalization
- Given a valid Reed API JSON response → NormalizedJob matches all field mappings in Section 4.1
- Reed job with null salary → salary_min=null, salary_max=null
- Reed job with full-time=true, part-time=false → job_type="full_time"

### 10.2 Adzuna Job Normalization
- Given a valid Adzuna API JSON response → NormalizedJob matches all field mappings in Section 4.2
- Adzuna job with no salary data → salary_min=null, salary_max=null, salary_text=null
- Adzuna job with flexible salary → salary_text="Flexible"

### 10.3 Missing Salary Handling
- Reed returns null salary → quality_score gets +0 for salary; does not fail
- Ad with partial salary (only min) → quality_score gets +10 (not +15, since both not present)

### 10.4 Short Description Handling
- Job with description length = 50 chars → quality_score: description component = 0 (threshold 200)
- Job with description length = 0 → Decision Engine: must be review or skip per Rule B

### 10.5 Duplicate Job from Both Sources
- Same job posted on both Reed and Adzuna → normalized to single record with source="multi_source"
- Both external_ids preserved
- Description from richer source kept
- quality_score is maximum across both sources

### 10.6 High Match Score, Low Source Quality
- job.match_score = 85, quality_score = 55 → decision must be "review"
- job.match_score = 85, quality_score = 72 → decision = "apply"

### 10.7 API Failure from One Source
- Reed returns 429 → continue with Adzuna; log warning; do not fail run
- Both Reed and Adzuna fail → return error to UI with partial/manual fallback option
- Reed returns empty array → continue with Adzuna results

### 10.8 Quality Score Boundary Cases
- All fields complete → quality_score = 100 → fully eligible
- Only description and company → quality_score = 50 → restricted (review only for apply)
- Only title and apply_url → quality_score = 10 → excluded (< 40)

### 10.9 remote_type Derivation
- Title="Senior Analyst - Remote", location="London" → remote_type="remote"
- Title="Business Analyst", location="Remote" → remote_type="remote"
- Title="Project Manager - Hybrid", location="Glasgow" → remote_type="hybrid"
- Title="Data Engineer", location="Birmingham" (no keywords) → remote_type="unknown"
- Title="Scrum Master - Flexible Working", location="Manchester" → remote_type="unknown" (flexible alone is ambiguous)

### 10.10 Salary Parsing Edge Cases
- "Up to £60k" → salary_min=null, salary_max=60000, salary_text="Up to £60k"
- "Competitive" → salary_min=null, salary_max=null, salary_text="Competitive"
- "£300/day" → salary_min=300, salary_max=null, salary_text="£300/day", salary_is_annual=false
- "£45-55k" → salary_min=45000, salary_max=55000

### 10.11 Location Normalization
- "Greater London" + "London" → normalized to same value → deduplicated correctly
- "London, UK" and "London" → after stripping country suffix → both normalize to "london"

### 10.12 Duplicate Job Both Sources, Richer Description
- Same job on Reed (description 300 chars) and Adzuna (description 800 chars)
- → keep Adzuna record; source="multi_source"; both external_ids preserved

---

## 11. Scoring Consistency Check

**Current scoring in data_contract.md:**
- `match_score` max = 100 (sum of breakdown components)
- Breakdown components: skills_score, experience_score, location_score, salary_score, domain_score, work_mode_score

**Consistency issues found:** None currently. The scoring breakdown totals to 100 when all components are at maximum. Each component is scored independently and summed.

**This design adds:** `quality_score` as a separate orthogonal signal (0–100), distinct from `match_score`. They are NOT combined numerically. `quality_score` gates whether the match_score result is acted upon, not added to it.

**Decision matrix:**

| | match_score < 65 | match_score 65–79 | match_score >= 80 |
|--|--|--|--|
| **quality >= 70** | skip | review | apply |
| **quality 40–69** | skip | review | **review** (overridden) |
| **quality < 40** | skip | skip | skip |

---

## 12. Relationship to Existing Data Contract

The NormalizedJob schema in this document coexists with the JobPosting contract in `data_contract.md`:
- `data_contract.md` JobPosting defines the internal job record used in analysis/tailoring
- This design defines the ingestion normalization layer that feeds JobPosting
- Both schemas should be kept aligned; any field added to NormalizedJob should map to JobPosting

---

## 13. Open Questions

- [x] Multi-page fetching — **resolved**: MVP limited to single-page (50 jobs/source); pagination out of scope for v1
- [x] Location normalization — **resolved**: alias table + suffix stripping (Section 6.4)
- [x] Description similarity threshold — **resolved**: lowered to 0.80 per Helpo feedback (Section 6.1)
- [x] Salary parsing edge cases — **resolved**: explicit rules for "up to £X", "negotiable", daily/hourly (Section 4.5)
- [ ] Reed free tier rate limits — confirm requests-per-day limit; implement 429 backoff
- [ ] Adzuna free tier — confirm max results per call (assume 50 for MVP)
