import sys
from pathlib import Path


POC_DIR = Path(__file__).resolve().parents[1]
if str(POC_DIR) not in sys.path:
    sys.path.insert(0, str(POC_DIR))

for module_name in (
    "browser_enrichment_agent",
    "domain_policy",
    "report_writer",
    "run_poc",
    "source_quality",
):
    sys.modules.pop(module_name, None)
