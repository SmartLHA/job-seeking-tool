import sys
from pathlib import Path


POC_DIR = Path(__file__).resolve().parents[1]
if str(POC_DIR) not in sys.path:
    sys.path.insert(0, str(POC_DIR))

for module_name in (
    "content_extractor",
    "domain_policy",
    "extraction_profiles",
    "extraction_quality",
    "link_extractor",
    "markdown_exporter",
    "report_writer",
    "research_summary",
    "run_live_extraction",
    "run_preflight",
    "text_cleanup",
):
    sys.modules.pop(module_name, None)
