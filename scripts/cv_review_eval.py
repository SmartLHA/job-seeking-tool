"""Synthetic CV reviewer smoke check; cloud use requires explicit consent."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.job_hunt_cv_review import (run_layer0, run_blind_review, select_review_items,
                                    link_and_clear, overall_verdict, item_statuses, build_review_source)
from src.job_hunt_models import CandidateProfile, Skill
from src import job_hunt_llm

WARNING = 'Fifteen cases are a smoke check, not proof of reliability.'
CLASSES = ('SUPPORTED', 'EXAGGERATED', 'UNSUPPORTED', 'UNCHECKED')
DEFAULT_PACE = 15.0        # seconds between consecutive reviewer calls
DEFAULT_RETRY_WAIT = 65.0  # seconds before the single retry of a 429 or 503
RETRY_DETAILS = ('rate_limited', 'server_error')
EXIT_RATE_LIMITED = 3      # run stopped early on a repeated rate limit


def build_source(case):
    """Use the production evidence/context builder with a typed synthetic profile."""
    p = case['profile']
    profile = CandidateProfile(
        candidate_id=case['id'], years_experience=p['years_experience'],
        skills=[Skill(name=name) for name in p['skills']],
        target_roles=list(p['target_roles']), industries=list(p['industries']))
    return build_review_source(profile, case['original_cv'])


def load_cases(path):
    cases = []
    for file in sorted(Path(path).glob('*.json')):
        case = json.loads(file.read_text())
        cases.append(case)
        cases.extend(case.get('variants', []))
    if not cases:
        raise ValueError('No cases found')
    ids = [c['id'] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate case ids')
    return cases


def metrics(pairs):
    table = Counter(pairs)
    positives = sum(e != 'SUPPORTED' for e, a in pairs)
    flags = sum(a in ('EXAGGERATED', 'UNSUPPORTED') for e, a in pairs)
    true_flags = sum(e != 'SUPPORTED' and a in ('EXAGGERATED', 'UNSUPPORTED') for e, a in pairs)
    ratio = lambda n, d: f'{n / d:.3f}' if d else 'n/a'
    return dict(recall=ratio(true_flags, positives), precision=ratio(true_flags, flags),
                unchecked_rate=ratio(sum(a == 'UNCHECKED' for e, a in pairs), len(pairs)),
                confusion=table, count=len(pairs))


def failure_detail(review):
    """Failure kind the reviewer left on a case's items ('' when the call succeeded)."""
    for item in review['items']:
        if item.get('unchecked_detail'):
            return item['unchecked_detail']
    return ''


def wait(sleep, seconds):
    if seconds > 0:
        sleep(seconds)


def review_case(case, evidence, context, *, transport, retry_wait, sleep):
    """Review one case; retry once after retry_wait on a 429 or 503. Returns (review, detail, stop).

    stop is True only when both attempts were rate_limited (a repeated rate limit).
    """
    def attempt():
        review = run_blind_review(case['original_cv'], evidence, context, case['job_skills'],
                                  {'reviewed_cv': case['rewrite']}, 'synthetic-writer', transport=transport)
        return review, failure_detail(review)
    review, first = attempt()
    if first not in RETRY_DETAILS:
        return review, first, False
    wait(sleep, retry_wait)
    review, detail = attempt()
    return review, detail, first == 'rate_limited' and detail == 'rate_limited'


def not_run_row(case, detail='', actual_l0=None):
    """Report row for a case that was not reviewed; it counts as neither a match nor a mismatch."""
    overall = case['labels']['expected_overall']
    expected_l0 = sorted((f['rule'], f['severity']) for f in case['labels']['expected_l0'])
    return dict(id=case['id'], expected_overall=overall, expected=overall, actual='NOT_RUN', detail=detail,
                mismatch=False, not_run=True, expected_l0=expected_l0, actual_l0=actual_l0)


def stop_summary(rows):
    """One line saying how many cases ran when a repeated rate limit ended the run; '' otherwise."""
    skipped = [r['id'] for r in rows if r['not_run']]
    if not skipped:
        return ''
    return (f"Run stopped: {len(rows) - len(skipped)} of {len(rows)} cases ran; stopped on a repeated "
            f"rate limit (likely the daily quota; which limit is UNVERIFIED). NOT_RUN: {', '.join(skipped)}")


def run(cases, *, dry_run, out_dir, transport=None, pace=DEFAULT_PACE,
        retry_wait=DEFAULT_RETRY_WAIT, sleep=time.sleep):
    rows, pairs, item_rows = [], [], []
    called = False   # a reviewer call was made, so the next one waits `pace` first
    stopped = False  # repeated rate limit: no more reviewer calls, remaining cases are NOT_RUN
    for case in cases:
        if stopped:
            rows.append(not_run_row(case))
            continue
        evidence, context = build_source(case)
        findings = run_layer0(case['original_cv'], evidence, context, case['rewrite'],
                              case['job_skills'], [])
        expected_l0 = {(f['rule'], f['severity']) for f in case['labels']['expected_l0']}
        actual_l0 = {(f.rule, f.severity) for f in findings}
        mismatch = expected_l0 != actual_l0
        detail = ''
        if dry_run:
            actual = 'BLOCKED' if any(f.severity == 'BLOCKER' for f in findings) else 'needs Layer 1'
            expected = 'BLOCKED' if any(s == 'BLOCKER' for r, s in expected_l0) else 'needs Layer 1'
        else:
            if called:
                wait(sleep, pace)
            review, detail, stopped = review_case(case, evidence, context, transport=transport,
                                                  retry_wait=retry_wait, sleep=sleep)
            called = True
            if stopped:
                # Left out of every metric: this case's items are not recorded.
                rows.append(not_run_row(case, detail, sorted(actual_l0)))
                continue
            actual = overall_verdict(link_and_clear(findings, review['items']), item_statuses(review['items']))
            expected = case['labels']['expected_overall']
            by_text = {i['text']: i['verdict'] for i in review['items']}
            for label in case['labels']['expected_items']:
                status = by_text.get(label['statement'], 'UNCHECKED')
                pairs.append((label['expected'], status))
                item_rows.append((case['id'], label['statement'], label['expected'], status))
        mismatch |= actual != expected
        rows.append(dict(id=case['id'], expected_overall=case['labels']['expected_overall'], expected=expected, actual=actual, detail=detail,
                         mismatch=mismatch, not_run=False,
                         expected_l0=sorted(expected_l0), actual_l0=sorted(actual_l0)))
    lines = ['# CV review eval', '', WARNING, '',
             'Mode: ' + ('dry-run; Layer 0 only; no network' if dry_run else 'cloud consent; Layer 1'),
             f"Cases including variants: {len(rows)}; matches: {sum(not r['mismatch'] and not r['not_run'] for r in rows)}; mismatches: {sum(r['mismatch'] for r in rows)}", '']
    if stop_summary(rows):
        lines += [stop_summary(rows), '']
    lines += ['| Case | Expected | Actual | Detail | L0 expected | L0 actual | Match |', '|---|---|---|---|---|---|---|']
    for r in rows:
        l0_actual = 'n/a' if r['actual_l0'] is None else r['actual_l0']
        match = 'n/a' if r['not_run'] else not r['mismatch']
        lines.append(f"| {r['id']} | {r['expected']} | {r['actual']} | {r['detail']} | {r['expected_l0']} | {l0_actual} | {match} |")
    if not dry_run:
        m = metrics(pairs)
        lines += ['', f"Item recall: {m['recall']}; precision: {m['precision']}; UNCHECKED rate: {m['unchecked_rate']}", '',
                  '| Expected / Actual | ' + ' | '.join(CLASSES) + ' |', '|---|' + '---|' * len(CLASSES)]
        for e in CLASSES[:3]:
            lines.append('| ' + e + ' | ' + ' | '.join(str(m['confusion'][e, a]) for a in CLASSES) + ' |')
        lines += ['', '| Case | Statement | Expected | Actual |', '|---|---|---|---|']
        for row in item_rows:
            lines.append('| ' + ' | '.join(str(v).replace('|', '\\|').replace('\n', ' ') for v in row) + ' |')
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc)
    report = out_dir / f"report-{stamp.strftime('%Y-%m-%d-%H%M%S')}.md"
    while report.exists():
        stamp += timedelta(seconds=1)
        report = out_dir / f"report-{stamp.strftime('%Y-%m-%d-%H%M%S')}.md"
    with report.open('x') as handle:
        handle.write('\n'.join(lines) + '\n')
    return rows, report


def seconds(text):
    """argparse type: a finite float >= 0."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f'not a number: {text!r}') from None
    if not (math.isfinite(value) and value >= 0):
        raise argparse.ArgumentTypeError(f'must be a number >= 0, got {text!r}')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--use-cloud', action='store_true')
    parser.add_argument('--cases', type=Path, default=ROOT / 'tests/fixtures/cv_review_eval')
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'archive/cv-review-eval')
    parser.add_argument('--pace', type=seconds, default=DEFAULT_PACE,
                        help='seconds to wait between consecutive reviewer calls (default %(default)s; live runs only)')
    parser.add_argument('--retry-wait', type=seconds, default=DEFAULT_RETRY_WAIT,
                        help='seconds to wait before the one retry of a 429 or 503 (default %(default)s)')
    args = parser.parse_args(argv)
    if args.use_cloud:
        # Same form as src/ui_routes.py main(), with the explicit project path.
        try:
            from dotenv import load_dotenv
            load_dotenv(ROOT / '.env')
        except ImportError:
            pass  # python-dotenv not installed; env vars must be set externally
        if not job_hunt_llm._api_key():
            print('error: no Gemini API key found (set GOOGLE_API_KEY or GEMINI_API_KEY '
                  'in the project .env or the environment); no report written', file=sys.stderr)
            return 2
    rows, report = run(load_cases(args.cases), dry_run=args.dry_run, out_dir=args.out_dir,
                       pace=args.pace, retry_wait=args.retry_wait)
    print(WARNING)
    for row in rows:
        print(f"{row['id']}: expected overall={row['expected_overall']}; expected gate={row['expected']}; actual={row['actual']}; expected L0={row['expected_l0']}; actual L0={row['actual_l0']}; mismatch={row['mismatch']}")
    print(f"cases: {len(rows)}; mismatches: {sum(r['mismatch'] for r in rows)}")
    if stop_summary(rows):
        print(stop_summary(rows))
    print(f'report: {report}')
    return EXIT_RATE_LIMITED if stop_summary(rows) else 0


if __name__ == '__main__':
    raise SystemExit(main())
