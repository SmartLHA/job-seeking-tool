"""Synthetic CV reviewer smoke check; cloud use requires explicit consent."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.job_hunt_cv_review import (run_layer0, run_blind_review, select_review_items,
                                    link_and_clear, overall_verdict, item_statuses, build_review_source)
from src.job_hunt_models import CandidateProfile, Skill

WARNING = 'Fifteen cases are a smoke check, not proof of reliability.'
CLASSES = ('SUPPORTED', 'EXAGGERATED', 'UNSUPPORTED', 'UNCHECKED')


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


def run(cases, *, dry_run, out_dir, transport=None):
    rows, pairs, item_rows = [], [], []
    for case in cases:
        evidence, context = build_source(case)
        findings = run_layer0(case['original_cv'], evidence, context, case['rewrite'],
                              case['job_skills'], [])
        expected_l0 = {(f['rule'], f['severity']) for f in case['labels']['expected_l0']}
        actual_l0 = {(f.rule, f.severity) for f in findings}
        mismatch = expected_l0 != actual_l0
        if dry_run:
            actual = 'BLOCKED' if any(f.severity == 'BLOCKER' for f in findings) else 'needs Layer 1'
            expected = 'BLOCKED' if any(s == 'BLOCKER' for r, s in expected_l0) else 'needs Layer 1'
        else:
            review = run_blind_review(case['original_cv'], evidence, context, case['job_skills'],
                                      {'reviewed_cv': case['rewrite']}, 'synthetic-writer', transport=transport)
            actual = overall_verdict(link_and_clear(findings, review['items']), item_statuses(review['items']))
            expected = case['labels']['expected_overall']
            by_text = {i['text']: i['verdict'] for i in review['items']}
            for label in case['labels']['expected_items']:
                status = by_text.get(label['statement'], 'UNCHECKED')
                pairs.append((label['expected'], status))
                item_rows.append((case['id'], label['statement'], label['expected'], status))
        mismatch |= actual != expected
        rows.append(dict(id=case['id'], expected_overall=case['labels']['expected_overall'], expected=expected, actual=actual, mismatch=mismatch,
                         expected_l0=sorted(expected_l0), actual_l0=sorted(actual_l0)))
    lines = ['# CV review eval', '', WARNING, '',
             'Mode: ' + ('dry-run; Layer 0 only; no network' if dry_run else 'cloud consent; Layer 1'),
             f"Cases including variants: {len(rows)}; matches: {sum(not r['mismatch'] for r in rows)}; mismatches: {sum(r['mismatch'] for r in rows)}", '',
             '| Case | Expected | Actual | L0 expected | L0 actual | Match |', '|---|---|---|---|---|---|']
    for r in rows:
        lines.append(f"| {r['id']} | {r['expected']} | {r['actual']} | {r['expected_l0']} | {r['actual_l0']} | {not r['mismatch']} |")
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--use-cloud', action='store_true')
    parser.add_argument('--cases', type=Path, default=ROOT / 'tests/fixtures/cv_review_eval')
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'archive/cv-review-eval')
    args = parser.parse_args(argv)
    rows, report = run(load_cases(args.cases), dry_run=args.dry_run, out_dir=args.out_dir)
    print(WARNING)
    for row in rows:
        print(f"{row['id']}: expected overall={row['expected_overall']}; expected gate={row['expected']}; actual={row['actual']}; expected L0={row['expected_l0']}; actual L0={row['actual_l0']}; mismatch={row['mismatch']}")
    print(f"cases: {len(rows)}; mismatches: {sum(r['mismatch'] for r in rows)}")
    print(f'report: {report}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
