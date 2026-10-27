"""Deterministic checks and shared text segmentation for CV blind review."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
import re

from src.job_hunt_ats_scorer import score_cv
from src.text_grounding import normalize_grounding_text


@dataclass
class Finding:
    layer: int
    rule: str
    text: str
    severity: str
    detail: str
    item_id: str | None = None
    cleared_by: str | None = None


_HEADINGS = set(('summary,professional summary,profile,personal profile,career summary,'
    'objective,experience,work experience,professional experience,employment history,'
    'career history,education,qualifications,skills,key skills,technical skills,core skills,'
    'core competencies,competencies,certifications,certificates,training,professional development,'
    'projects,key projects,achievements,key achievements,languages,interests,hobbies,references,'
    'publications,volunteering,volunteer experience,memberships,professional memberships,awards,'
    'contact,contact details').split(','))
_WORDS = dict(zip('two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty'.split(), range(2, 21)))
_BULLET = re.compile(r'^\s*(?:[-*•●▪‣◦]\s*|\d+[.)](?:\s+|$))')


def normalize(text: str) -> str:
    """Normalize text using shared grounding rules."""
    return normalize_grounding_text(text)


def is_bullet(line: str) -> bool:
    """Identify supported bullet markers."""
    return bool(_BULLET.match(line.replace('**', '').replace('__', '')))


def split_statements(text: str) -> list[str]:
    """Split long lines while protecting abbreviations."""
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line.split()) <= 25:
            result.append(line)
            continue
        protected = re.sub(r'\b(?:e\.g\.|i\.e\.|U\.K\.)', lambda m: m[0].replace('.', '\x00'), line, flags=re.I)
        result.extend(part.replace('\x00', '.').strip() for part in re.split(r'(?<=[.!?])\s+', protected) if part.strip())
    return result


def _heading(line: str) -> str | None:
    if is_bullet(line) or not line.strip():
        return None
    markdown = re.match(r'^#{1,6} ', line.lstrip())
    body = line.lstrip()[markdown.end():] if markdown else line.strip()
    key = normalize(body.strip().rstrip(':').replace('&', 'and'))
    return key if markdown or key in _HEADINGS else None


def listed_headings(text: str) -> list[str]:
    """Return recognized headings in document order."""
    return [key for line in text.splitlines() if (key := _heading(line)) is not None]


def is_date_line(line: str) -> bool:
    """Identify short date lines outside bullets and prose."""
    return len(line.split()) <= 15 and not line.rstrip().endswith('.') and not is_bullet(line) and _heading(line) is None and bool(re.search(r'\b(?:19[5-9]\d|20\d\d)\b|[\x27’]\d{2}\b', line))


def _role_candidate(line: str) -> bool:
    return bool(line.strip()) and not is_bullet(line) and _heading(line) is None and len(line.split()) <= 10 and not line.rstrip().endswith('.')


def _role_indices(text: str) -> set[int]:
    lines = text.splitlines()
    indices = set()
    for i, line in enumerate(lines):
        if is_date_line(line):
            indices.add(i)
            collected = blanks = 0
            for j in range(i - 1, -1, -1):
                if not lines[j].strip() and blanks == 0:
                    blanks += 1
                    continue
                if collected == 2 or not _role_candidate(lines[j]):
                    break
                indices.add(j)
                collected += 1
    return indices


def _canonical_role(line: str) -> str:
    line = normalize(line.replace('**', '').replace('__', ''))
    line = re.sub(r'\s*-\s*', '-', line)
    for month in 'january february march april may june july august september october november december'.split():
        short = 'sept?' if month == 'september' else month[:3]
        line = re.sub(r'\b(?:' + short + '|' + month + r')\b', month, line)
    return line


def role_lines(text: str) -> set[str]:
    """Return canonical dated role lines."""
    lines = text.splitlines()
    return {_canonical_role(lines[i]) for i in _role_indices(text)}


def role_adjacent_lines(text: str) -> set[str]:
    """Return canonical candidate lines immediately after dates."""
    lines = text.splitlines()
    return {_canonical_role(lines[i + 1]) for i, line in enumerate(lines[:-1]) if is_date_line(line) and _role_candidate(lines[i + 1]) and not is_date_line(lines[i + 1])}


def _possible(line: str) -> bool:
    words = line.split()
    return bool(words) and len(words) <= 5 and not is_bullet(line) and _heading(line) is None and not re.search(r'[,|;/\d]', line) and not re.search(r'[.!?:;,]$', line.rstrip()) and all(word[0].isupper() for word in words)


def possible_headings(text: str) -> list[str]:
    """Return short title-case headings outside role blocks."""
    roles = _role_indices(text)
    return [normalize(line) for i, line in enumerate(text.splitlines()) if i not in roles and _possible(line)]


def segment_blocks(text: str) -> list[tuple[str, list[str]]]:
    """Group statements under headings and canonical role keys."""
    lines = text.splitlines()
    roles = _role_indices(text)
    result = []
    key, statements = 'header', []
    i = 0
    while i < len(lines):
        line = lines[i]
        if i in roles:
            if statements or key != 'header':
                result.append((key, statements))
            run = []
            while i < len(lines) and (i in roles or (not lines[i].strip() and i + 1 in roles)):
                if i in roles:
                    run.append(_canonical_role(lines[i]))
                i += 1
            key, statements = 'role:' + '\n'.join(run), []
            continue
        heading = _heading(line)
        if heading is not None or _possible(line):
            if statements or key != 'header':
                result.append((key, statements))
            key, statements = heading or normalize(line), []
        else:
            statements.extend(split_statements(line))
        i += 1
    if statements or key != 'header':
        result.append((key, statements))
    return result


def _numbers(text: str, *, source: bool = False) -> set[tuple[str, str, str]]:
    text = normalize('\n'.join(_BULLET.sub('', line) for line in text.splitlines()))
    result = set()
    scales = {'': 1, 'k': 1000, 'thousand': 1000, 'm': 1000000,
              'million': 1000000, 'bn': 1000000000, 'billion': 1000000000}
    pattern = (r'(?<![\w])([£$€]?)\s*(\d+(?:,\d{3})*(?:\.\d+)?)'
               r'(?:\s*(bn|k|m|thousand|million|billion)(?![a-z]))?'
               r'(?:\s*(%|percent\b|per\s+cent\b))?')
    for match in re.finditer(pattern, text):
        currency, number, scale, percent = match.groups()
        value = Decimal(number.replace(',', '')) * scales[scale or '']
        result.add((currency, str(value.normalize()), '%' if percent else ''))
    words = {'one': 1, **_WORDS} if source else _WORDS
    for match in re.finditer(r'\b(' + '|'.join(words) + r')\b', text):
        result.add(('', str(Decimal(words[match[1]]).normalize()), ''))
    return result


def _term_in(term: str, text: str, case_sensitive: bool = False) -> bool:
    return bool(re.search(r'(?<![\w+#.])' + re.escape(term) + r'(?![\w+#])', text, 0 if case_sensitive else re.I))


def run_layer0(original_cv: str, evidence: str, context: str, rewrite: str,
               job_skills: list[str], known_skills: list[str], aliases: dict[str, str] | None = None) -> list[Finding]:
    """Run deterministic checks using evidence and context separately."""
    job_skills = list(job_skills)
    known_skills = list(known_skills)
    findings = []
    def add(rule, text, severity, detail):
        findings.append(Finding(0, rule, text, severity, detail))
    if not rewrite.strip():
        add('L0-empty', '', 'BLOCKER', 'empty rewrite')
        return findings
    for token in sorted(_numbers(rewrite) - _numbers(evidence + '\n' + context, source=True)):
        add('L0-1', ' '.join(token), 'BLOCKER', 'number absent from source')
    if listed_headings(original_cv) != listed_headings(rewrite):
        add('L0-2', '', 'BLOCKER', 'listed headings changed')
    if Counter(possible_headings(original_cv)) != Counter(possible_headings(rewrite)):
        add('L0-2', '', 'MAJOR', 'possible headings changed')
    for line in sorted(role_lines(original_cv) - role_lines(rewrite)):
        add('L0-3', line, 'BLOCKER', 'role line changed or removed')
    for line in sorted(role_lines(rewrite) - role_lines(original_cv)):
        add('L0-3', line, 'BLOCKER', 'new role line')
    if role_adjacent_lines(original_cv) != role_adjacent_lines(rewrite):
        add('L0-3', '', 'MAJOR', 'role-adjacent line changed')
    alias_map = {alias.casefold(): canonical.casefold() for alias, canonical in
                 {'MS Teams': 'Microsoft Teams', **(aliases or {})}.items()}
    groups = []
    for term in sorted({term.casefold() for term in known_skills + job_skills}):
        group = {term}
        for alias, canonical in alias_map.items():
            if term in {alias, canonical}:
                group.update((alias, canonical))
        if group not in groups:
            groups.append(group)
    for statement in split_statements(rewrite):
        for group in groups:
            if any(_term_in(term, statement) for term in group) and not any(_term_in(term, evidence) for term in group):
                add('L0-4', statement, 'MAJOR', 'new skill term: ' + ', '.join(sorted(group)))
    before, after = score_cv(original_cv, job_skills)['overall'], score_cv(rewrite, job_skills)['overall']
    if after < before:
        add('L0-5', '', 'MINOR', f'ATS score dropped from {before} to {after}')
    original_statements = {normalize(s) for s in split_statements(original_cv)}
    for statement in split_statements(rewrite):
        if normalize(statement) in original_statements:
            continue
        for term in ('SUPPORTED', 'UNSUPPORTED', 'EXAGGERATED', 'ignore previous', 'ignore the above', 'system prompt', 'as an ai', 'reviewer', 'verdict', 'numbered item'):
            sensitive = term.isupper()
            pattern = r'(?<!\w)' + re.escape(term) + r'(?!\w)'
            flags = 0 if sensitive else re.I
            if re.search(pattern, statement, flags) and not re.search(pattern, original_cv, flags):
                add('L0-6', statement, 'MAJOR', 'review instruction tripwire: ' + term)
    return findings


def overall_verdict(l0_findings, item_statuses) -> str:
    """Apply verdict precedence to findings and item statuses."""
    l0_findings = [f if isinstance(f, dict) else vars(f) for f in l0_findings]
    statuses = list(item_statuses.values()) if isinstance(item_statuses, dict) else list(item_statuses)
    statuses = [s.get('verdict', s.get('status')) if isinstance(s, dict) else getattr(s, 'verdict', s) for s in statuses]
    if any(f.get('severity') == 'BLOCKER' for f in l0_findings) or 'UNSUPPORTED' in statuses:
        return 'BLOCKED'
    if any(s not in {'SUPPORTED', 'EXAGGERATED', 'UNSUPPORTED'} for s in statuses):
        return 'UNCHECKED'
    if any(f.get('severity') == 'MAJOR' and not f.get('cleared_by') for f in l0_findings) or 'EXAGGERATED' in statuses:
        return 'NEEDS_EDIT'
    return 'PASS'
