from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from src.orchestrator import LocalEvaluationRunResult, run_local_evaluation_flow
from src.profile import ProfileValidationError
from src.reviewed_input import ReviewedInputValidationError
from src.storage import StorageError
from src.outcomes import OutcomeValidationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one lightweight local reviewed-job evaluation flow.",
    )
    parser.add_argument("--profile", required=True, help="Path to candidate profile JSON")
    parser.add_argument("--reviewed-job", required=True, help="Path to reviewed job JSON")
    parser.add_argument(
        "--state-root",
        default="data/state",
        help="Directory for local raw/reviewed/analysis state (default: data/state)",
    )
    parser.add_argument(
        "--report-dir",
        default="output/reports",
        help="Directory for JSON/CSV report exports (default: output/reports)",
    )
    parser.add_argument(
        "--raw-input",
        help="Optional raw input JSON file to store separately for auditability",
    )
    parser.add_argument(
        "--raw-input-id",
        help="Optional identifier for stored raw input (defaults to the reviewed job id)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = run_local_evaluation_flow(
            profile_path=args.profile,
            reviewed_job_path=args.reviewed_job,
            state_root=args.state_root,
            report_dir=args.report_dir,
            raw_input_path=args.raw_input,
            raw_input_id=args.raw_input_id,
        )
    except FileNotFoundError as exc:  # pragma: no cover - exercised via CLI-style tests
        print(f"File not found: {exc.filename or exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc.filename or 'input'}: {exc.msg} at line {exc.lineno}, column {exc.colno}", file=sys.stderr)
        return 1
    except ProfileValidationError as exc:
        print(f"Profile validation error: {exc}", file=sys.stderr)
        return 1
    except ReviewedInputValidationError as exc:
        print(f"Reviewed job validation error: {exc}", file=sys.stderr)
        return 1
    except StorageError as exc:
        print(f"Storage error: {exc}", file=sys.stderr)
        return 1
    except OutcomeValidationError as exc:
        print(f"Outcome validation error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - exercised via CLI-style tests
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_summary(result)
    return 0


def _print_summary(result: LocalEvaluationRunResult) -> None:
    print("Local evaluation completed")
    print(f"Job: {result.reviewed_job.job_title} @ {result.reviewed_job.company}")
    print(f"Decision: {result.analysis.decision}")
    print(f"Match score: {result.analysis.match_score}")
    print(f"Confidence: {result.analysis.confidence}")
    print(f"Reviewed job saved: {result.reviewed_job_path}")
    print(f"Analysis saved: {result.analysis_path}")
    print(f"JSON report: {result.report_json_path}")
    print(f"CSV report: {result.report_csv_path}")
    if result.raw_input_path is not None:
        print(f"Raw input saved: {result.raw_input_path}")
    if result.master_cv_path is not None:
        print(f"Master CV checked: {Path(result.master_cv_path)}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
