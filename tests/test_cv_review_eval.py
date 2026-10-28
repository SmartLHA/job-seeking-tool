"""Offline synthetic reviewer eval contracts; never call the provider."""
import json
from pathlib import Path
import pytest
from scripts import cv_review_eval as ev
from src import job_hunt_llm

CASES = Path(__file__).parent / 'fixtures/cv_review_eval'


@pytest.fixture(autouse=True)
def no_cloud(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('Unexpected cloud transport')
    monkeypatch.setattr(job_hunt_llm, '_call_gemini_model', blocked)


def test_schema_and_selected_labels():
    assert len(list(CASES.glob('*.json'))) == 15
    for case in ev.load_cases(CASES):
        assert {'id', 'description', 'original_cv', 'rewrite', 'profile', 'job_skills', 'labels'} <= case.keys()
        assert set(case['profile']) == {'years_experience', 'skills', 'target_roles', 'industries'}
        assert case['labels']['expected_overall'] in {'PASS', 'NEEDS_EDIT', 'BLOCKED'}
        labels = case['labels']['expected_items']
        assert all(x['expected'] in ev.CLASSES[:3] for x in labels)
        selected = [i['text'] for i in ev.select_review_items(case['original_cv'], case['rewrite'])]
        assert selected == [x['statement'] for x in labels], case['id']


def test_dry_report_no_transport(tmp_path):
    def forbidden(prompt):
        pytest.fail('Dry run invoked transport')
    rows, report = ev.run(ev.load_cases(CASES), dry_run=True, out_dir=tmp_path, transport=forbidden)
    assert not [r for r in rows if r['mismatch']]
    text = report.read_text()
    assert ev.WARNING in text
    assert 'Statement |' not in text


def test_handmade_metrics():
    m = ev.metrics([('SUPPORTED', 'EXAGGERATED'), ('EXAGGERATED', 'UNSUPPORTED'),
                    ('UNSUPPORTED', 'UNCHECKED'), ('SUPPORTED', 'SUPPORTED')])
    assert (m['recall'], m['precision'], m['unchecked_rate']) == ('0.500', '0.500', '0.250')
    assert m['confusion']['UNSUPPORTED', 'UNCHECKED'] == 1
    empty = ev.metrics([])
    assert (empty['recall'], empty['precision'], empty['unchecked_rate']) == ('n/a', 'n/a', 'n/a')
    assert ev.metrics([('SUPPORTED', 'SUPPORTED')])['precision'] == 'n/a'


def test_fake_live_report(tmp_path):
    case = next(c for c in ev.load_cases(CASES) if c['id'] == 'clean-rephrase')
    def fake(prompt):
        return json.dumps({'results': [{'id': 's-0', 'verdict': 'SUPPORTED',
                         'evidence_quote': 'Helped teams document business needs.', 'reason': 'faithful'}]})
    rows, report = ev.run([case], dry_run=False, out_dir=tmp_path, transport=fake)
    assert rows[0]['actual'] == 'PASS'
    text = report.read_text()
    assert 'Item recall: n/a; precision: n/a; UNCHECKED rate: 0.000' in text
    assert '| SUPPORTED | 1 | 0 | 0 | 0 |' in text
    assert case['labels']['expected_items'][0]['statement'] in text
    assert case['original_cv'] not in text


def test_mode_required():
    with pytest.raises(SystemExit) as exc:
        ev.main([])
    assert exc.value.code != 0


def test_source_separates_preferences():
    case = ev.load_cases(CASES)[0]
    evidence, context = ev.build_source(case)
    assert 'Years experience: 5' in evidence
    assert 'Profile skills:' in evidence
    assert 'Programme Director' not in evidence
    assert 'Target roles (preference, not experience): Programme Director' in context


def test_no_contact_patterns():
    import re
    email = re.compile(r'[A-Za-z0-9_.+-]+\x40[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
    phone = re.compile(r'(?<!\d)(?:\+\d[\d ()-]{8,}\d|0\d[\d ()-]{8,}\d)(?!\d)')
    for file in [*CASES.glob('*.json'), Path(__file__)]:
        text = file.read_text()
        assert not email.search(text), file.name
        assert not phone.search(text), file.name
