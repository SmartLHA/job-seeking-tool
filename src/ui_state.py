"""UI shared state — constants and server configuration.

Leaf module (LT-1 Step 2): imports nothing from other ``ui_*`` modules. It is
imported by all UI layers and by job-source modules. Holds per-page timestamps,
the server-config dataclass, CV-upload limits, home tab keys, select-form field
limits, and the shared select-nonce store.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


# Per-page last-updated timestamps.
# RULE: whenever a page's rendering function is modified, bump its entry to the
# current UTC time (YYYY-MM-DD HH:MM UTC).  Shown in the sidebar footer and on
# the job-detail page footer.
_PAGE_UPDATED: dict[str, str] = {
    # sidebar tab keys  → bump when modifying that tab's render code
    "search":   "2026-06-18 16:00 UTC",   # Find Jobs tab  (render_reed_search_results)
    "evaluate": "2026-06-18 01:00 UTC",   # Evaluate form tab
    "add_job":  "2026-06-18 01:00 UTC",   # Add Job tab
    "history":  "2026-06-18 01:00 UTC",   # History tab
    "board":    "2026-06-18 01:00 UTC",   # Board View page
    "profile":  "2026-06-18 01:00 UTC",   # My Profile page
    # standalone pages (no sidebar)
    "job":      "2026-06-22 18:00 UTC",   # Job detail page (render_job_page) — F1 v2 ATS keyword re-check panel
}


@dataclass(frozen=True, slots=True)
class UIServerConfig:
    profile_path: Path
    state_root: Path
    report_dir: Path
    host: str = "127.0.0.1"
    port: int = 9000
    # Display label for the active LLM, shown in the page footer. Set at startup
    # (LT-1 F2) so the render layer never imports a domain LLM module.
    model_label: str = ""


# CV-upload validation limits
_MAX_CV_SIZE_BYTES = 5 * 1024 * 1024
_ALLOWED_CV_EXTENSIONS = {".txt", ".pdf", ".docx"}
_ALLOWED_CV_MIMETYPES = {
    "text/plain",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Valid sidebar tab keys
_HOME_TABS = {"search", "evaluate", "history", "add_job", "profile"}

# Field limits for the hidden-field POST form submitted by any job-source select form.
# All sources share these field names; the "source" field identifies which source.
_SELECT_FORM_FIELD_LIMITS = {
    "source": 20,
    "source_job_id": 120,
    "title": 180,
    "company": 180,
    "location": 180,
    "work_mode": 40,
    "employment_type": 60,
    "url": 500,
    "description_raw": 501,
    "salary_min_gbp": 20,
    "salary_max_gbp": 20,
}
_ALLOWED_WORK_MODES = {"", "unknown", "remote", "hybrid", "onsite"}
_ALLOWED_EMPLOYMENT_TYPES = {"", "unknown", "permanent", "contract", "temporary", "full_time", "part_time"}
