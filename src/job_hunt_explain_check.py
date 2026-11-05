"""Bounded, local advisory checks of the exact explanation source."""
from __future__ import annotations

import copy
import json
import logging
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid
import urllib.error
import urllib.request

LOGGER = logging.getLogger(__name__)
MODEL = 'nimble:9b-q4_K_M'
QUESTION_VERSION = 'explain-check-v1'
THRESHOLD = .5
ENDPOINT = 'http://127.0.0.1:11434/v1/systemone'
MAX_BYTES = 65536
INSTRUCTIONS = 'Ignore opinions, judgements and recommendations. Is EVERY factual assertion in the STATEMENT TO CHECK (numbers, money, dates, skills, tools, places, work mode, requirements, scores, and what the candidate has or lacks) supported by the SOURCE?'
TRUE_CRITERION = 'Every factual assertion in the statement appears in or follows directly from the SOURCE, or the statement contains only opinions, judgements or recommendations.'
FALSE_CRITERION = 'At least one factual assertion in the statement is not in the SOURCE or contradicts it.'


def split_statements(fit, risk=None, action=None):
    """Split without removing any characters, preserving section concatenation."""
    explanation = fit if isinstance(fit, dict) else {"fit": fit, "risk": risk, "action": action}
    result = []
    eligible = 0
    for section in ('fit', 'risk', 'action'):
        text = str(explanation.get(section) or '')
        boundaries = []
        for match in re.finditer(r'\n+|[.!?]+(?:[ \t]+|$)', text):
            start, end = match.span()
            if text[start] == '.':
                prefix = text[:start + 1]
                if re.search(r'(?:\b(?:e\.g|i\.e|Mr|Mrs|Ms|Dr|Prof|vs|etc)|(?:\b[A-Za-z]\.)+[A-Za-z])\.$', prefix, re.I):
                    continue
            boundaries.append(end)
        if not boundaries or boundaries[-1] != len(text):
            boundaries.append(len(text))
        pieces = []
        pending = ''
        previous = 0
        for end in boundaries:
            piece = text[previous:end]
            previous = end
            if not piece.strip():
                # Whitespace never becomes its own statement: it stays attached
                # to the previous one, or to the next one when none exists yet.
                # A section made only of whitespace has no statements (as for '').
                if pieces:
                    pieces[-1] += piece
                else:
                    pending += piece
                continue
            pieces.append(pending + piece)
            pending = ''
        for index, piece in enumerate(pieces):
            row = {'id': f'{section}-{index}', 'section': section, 'text': piece}
            if section == 'action':
                row['reason'] = 'advice'
            elif eligible >= 10 or len(piece) > 600:
                row['reason'] = 'limit'
            if section != 'action':
                eligible += 1
            result.append(row)
    return result


class TokenStore:
    def __init__(self, clock=time.monotonic, state_root=None):
        self.state_root = state_root
        self.clock = clock
        self.lock = threading.RLock()
        self.entries = {}

    def _expire(self):
        now = self.clock()
        for token, entry in list(self.entries.items()):
            if now - entry['created'] >= 600:
                del self.entries[token]

    def create(self, job_id, source, statements):
        with self.lock:
            self._expire()
            for token, entry in list(self.entries.items()):
                if entry['job_id'] == job_id:
                    del self.entries[token]
            explanation = statements if isinstance(statements, dict) else None
            statements = split_statements(explanation) if explanation is not None else copy.deepcopy(statements)
            sections = explanation or {section: "".join(row["text"] for row in statements if row["section"] == section) for section in ("fit", "risk", "action")}
            if len(source.encode('utf-8')) > 8192:
                for row in statements:
                    if row['section'] != 'action':
                        row['reason'] = 'source_too_large'
            token = uuid.uuid4().hex
            self.entries[token] = {'job_id': job_id, 'source': source,
                                   'statements': statements, 'sections': sections, 'token': token,
                                   'created': self.clock()}
            if self.state_root is not None:
                self.entries[token]['state_root'] = self.state_root
            while len(self.entries) > 20:
                del self.entries[next(iter(self.entries))]
            return token

    def get(self, token, job_id):
        with self.lock:
            self._expire()
            entry = self.entries.get(token)
            return copy.deepcopy(entry) if entry and entry['job_id'] == job_id else None


class ModelUnavailable(Exception):
    pass


class ModelShapeError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelUnavailable('redirect rejected')


def _post_systemone(payload, timeout=90):
    """The sole socket-capable function; tests replace it before any call."""
    body = json.dumps(payload, allow_nan=False).encode('utf-8')
    if len(body) > MAX_BYTES:
        raise ModelShapeError('request too large')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(ENDPOINT, body, {'Content-Type': 'application/json'}, method='POST')
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, OSError) as exc:
        raise ModelUnavailable(str(exc)) from exc
    if len(raw) > MAX_BYTES:
        raise ModelShapeError('reply too large')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ModelShapeError('invalid JSON') from exc


def build_request(source, section_text, statement):
    return {'model': MODEL, 'state': f'SOURCE:\n{source}\n\nSECTION (context only, not evidence):\n{section_text}\n\nSTATEMENT TO CHECK:\n{statement}',
            'questions': {'supported': {'type': 'noul', 'instructions': INSTRUCTIONS,
                          'criteria': {'true': TRUE_CRITERION, 'false': FALSE_CRITERION}}},
            'keep_alive': '30m'}


def parse_response(reply):
    try:
        answer = reply['answers']['supported']
        p = answer['noul']
        if answer['type'] != 'noul' or isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise ModelShapeError('invalid noul answer') from exc
    return p, 'ok' if p >= THRESHOLD else 'could_not_confirm'


def fact_check(source, statement):
    def numbers(text):
        values = set()
        for match in re.finditer(r'(?<!\w)[£$€]?\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)(?!\w)', text):
            value = float(match[1].replace(',', '')) * {'k': 1000, 'm': 1000000, '': 1}[match[2].lower()]
            values.add(value)
        return values
    absent = sorted(numbers(statement) - numbers(source))
    caps = sorted(set(re.findall(r'\b[A-Z]{2,}\b', statement)) - set(re.findall(r'\b[A-Z]{2,}\b', source)))
    return {'unsupported_numbers': absent, 'unsupported_caps': caps}


class ExplainCheckService:
    """One lazy daemon owns calls; deadline never releases call ownership."""
    def __init__(self, store=None, transport=None, clock=time.monotonic):
        self.store = store or TokenStore(clock)
        self.transport = transport
        self.clock = clock
        self.condition = threading.Condition(threading.RLock())
        self.active = None
        self.thread = None
        self.log_lock = threading.Lock()

    def check(self, job_id, token, state_root, deadline_seconds=90):
        entry = self.store.get(token, job_id)
        if entry is None:
            return {'ok': True, 'state': 'stale'}
        with self.condition:
            if self.active is not None:
                return {'ok': True, 'state': 'busy'}
            task = {'job_id': job_id, 'token': token, 'entry': entry, 'root': state_root,
                    'results': {}, 'rows': [], 'late': [], 'returned': False,
                    'finished': False, 'run_id': uuid.uuid4().hex,
                    'deadline': self.clock() + deadline_seconds}
            self.active = task
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._worker, name='explain-check', daemon=True)
                self.thread.start()
            self.condition.notify_all()
            while not task['finished']:
                remaining = task['deadline'] - self.clock()
                if remaining <= 0:
                    break
                self.condition.wait(min(remaining, .1))
            task['returned'] = True
            results = copy.deepcopy(task['results'])
            for row in entry['statements']:
                results.setdefault(row['id'], {'verdict': 'not_checked', 'reason': row.get('reason', 'time')})
            state = 'stale' if task.get('stale') else ('done' if task['finished'] and not any(r.get('reason') in ('time', 'model_error', 'model_unavailable') for r in results.values()) else 'partial')
            self.condition.notify_all()
            return {'ok': True, 'state': state, 'results': results}

    def _worker(self):
        while True:
            with self.condition:
                while self.active is None:
                    self.condition.wait()
                task = self.active
            try:
                self._run(task)
            except Exception:
                LOGGER.exception('Explain check worker failed')
            finally:
                with self.condition:
                    task['finished'] = True
                    self.condition.notify_all()
                    while not task['returned']:
                        self.condition.wait()
                self._log(task)
                with self.condition:
                    self.active = None
                    self.condition.notify_all()

    def _run(self, task):
        unavailable = False
        entry = task['entry']
        for row in entry['statements']:
            with self.condition:
                if task['returned'] or self.clock() >= task['deadline']:
                    break
            if self.store.get(task['token'], task['job_id']) is None:
                task['stale'] = True
                break
            started = self.clock()
            p = None
            reason = row.get('reason')
            verdict = 'not_checked'
            if unavailable and not reason:
                reason = 'model_unavailable'
            if not reason:
                try:
                    payload = build_request(entry['source'], entry['sections'].get(row['section'], ''), row['text'])
                    if len(json.dumps(payload).encode()) > MAX_BYTES:
                        raise ModelShapeError('request too large')
                    reply = (self.transport or _post_systemone)(payload, timeout=max(.001, task['deadline'] - self.clock()))
                    p, verdict = parse_response(reply)
                except (ModelUnavailable, urllib.error.URLError, OSError):
                    unavailable = True
                    reason = 'model_unavailable'
                except Exception:
                    reason = 'model_error'
                    LOGGER.exception('Explain check model error')
            result = {'verdict': verdict}
            if reason:
                result['reason'] = reason
            record = {**row, **result, 'reason': reason, 'p': p, 'fact_check': fact_check(entry['source'], row['text']), 'seconds': self.clock() - started}
            with self.condition:
                if task['returned'] or self.clock() >= task['deadline']:
                    task['late'].append(record)
                    break
                task['results'][row['id']] = result
                task['rows'].append(record)
                self.condition.notify_all()

    def _log(self, task):
        recorded = {row['id'] for row in task['rows']}
        rows = list(task['rows'])
        for row in task['entry']['statements']:
            if row['id'] not in recorded:
                rows.append({**row, 'p': None, 'verdict': 'not_checked',
                             'reason': row.get('reason', 'stale' if task.get('stale') else 'time'),
                             'fact_check': fact_check(task['entry']['source'], row['text']), 'seconds': 0})
        record = {'run_id': task['run_id'], 'job_id': task['job_id'], 'time': time.time(),
                  'model': MODEL, 'model_digest': None, 'QUESTION_VERSION': QUESTION_VERSION,
                  'threshold': THRESHOLD, 'source': task['entry']['source'].encode()[:8192].decode('utf-8', errors='ignore'),
                  'statements': rows, 'discarded_late_results': task['late']}
        try:
            with self.log_lock:
                path = Path(task['root']) / 'logs' / 'explain-check.jsonl'
                path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, 'a', encoding='utf-8') as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(json.dumps(record, allow_nan=False) + '\n')
        except Exception:
            LOGGER.exception('Could not write explain check log')


TOKEN_STORE = TokenStore()
CHECK_SERVICE = ExplainCheckService(TOKEN_STORE)


def create_check(job_id, source, explanation):
    statements = split_statements(explanation)
    # One lock hold (the store lock is re-entrant) so a second explain for the
    # same job cannot supersede this token between create and the snapshot read.
    with TOKEN_STORE.lock:
        token = TOKEN_STORE.create(job_id, source, statements)
        snapshot = TOKEN_STORE.get(token, job_id)['statements']
    return {'check_token': token, 'statements': snapshot}


def check_explanation(job_id, token, state_root, deadline_seconds=90):
    return CHECK_SERVICE.check(job_id, token, state_root, deadline_seconds)


def run_check(token_entry, deadline_seconds=90):
    """Check a current server-side token entry using its configured log root."""
    job_id, token = token_entry["job_id"], token_entry["token"]
    if TOKEN_STORE.get(token, job_id) is None:
        return {"ok": True, "state": "stale"}
    return CHECK_SERVICE.check(job_id, token, token_entry["state_root"], deadline_seconds)
