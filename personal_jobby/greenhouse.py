"""Bounded, key-free public Greenhouse GET adapter. No submission capability."""
from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import ssl
import time

from personal_jobby import private_fs as fs
from personal_jobby.question_inventory import (AI_TITLE, TECHNICAL_ROLE, NONTECHNICAL_ROLE, SCHEMA,
    aggregate, normalize, observe, source_url, technical_title)

MAX_JSON = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024


def utc():
    return datetime.now(timezone.utc).isoformat()


def decode(raw):
    if len(raw) > MAX_JSON:
        raise ValueError('JSON exceeds 16 MiB')
    return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def load(path, cap=MAX_JSON):
    return decode(fs.read_bytes(path, cap))


def save(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    if len(text.encode()) > MAX_JSON:
        raise ValueError('Aggregate JSON exceeds 16 MiB')
    fs.write_text(path, text)


def fresh_output(path):
    path = Path(path)
    root = Path.home() / 'tmp'
    if not path.is_absolute() or '..' in path.parts or root not in path.parents:
        raise ValueError(f'Output must be a fresh absolute child of {root}')
    fs.check(path)
    fd = fs.directory(path.parent, create=True)
    try:
        os.mkdir(path.name, 0o700, dir_fd=fd)
    finally:
        os.close(fd)
    return path


@contextmanager
def request_deadline(seconds):
    # This Linux CLI is sequential. SIGALRM also bounds DNS/connect/headers, where
    # a socket timeout alone does not bound the resolver. Never borrow another timer.
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise ValueError('Public GET requires an unshared main-thread deadline')
    previous = signal.getsignal(signal.SIGALRM)

    def expired(*_):
        raise TimeoutError('Public GET deadline reached')

    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class PublicGreenhouse:
    """Only generated GET paths; stdlib TLS, no proxies, cookies, auth or redirects."""
    def __init__(self, *, pace=0.3, timeout=10, request_cap=250, elapsed_cap=900):
        if not 0.25 <= pace <= 10 or not 1 <= timeout <= 20 or not 1 <= request_cap <= 250 or not 1 <= elapsed_cap <= 900:
            raise ValueError('Invalid public request bounds')
        self.pace, self.timeout, self.request_cap, self.elapsed_cap = pace, timeout, request_cap, elapsed_cap
        self.requests = self.received_bytes = 0
        self.started = time.monotonic()
        self.last = None

    def get(self, board, job_id=None):
        url = source_url(board, job_id)
        if self.requests >= self.request_cap or time.monotonic() - self.started >= self.elapsed_cap or self.received_bytes >= MAX_TOTAL:
            raise ValueError('Public request/elapsed/aggregate byte cap reached')
        if self.last is not None:
            time.sleep(max(0, self.pace - (time.monotonic() - self.last)))
        remaining = self.elapsed_cap - (time.monotonic() - self.started)
        if remaining <= 0:
            raise ValueError('Public elapsed cap reached')
        cap = min(8 * 1024 * 1024 if job_id is None else 2 * 1024 * 1024, MAX_TOTAL - self.received_bytes)
        connection = http.client.HTTPSConnection('boards-api.greenhouse.io', timeout=min(self.timeout, remaining), context=ssl.create_default_context())
        self.requests += 1
        self.last = time.monotonic()
        with request_deadline(min(self.timeout, remaining)):
            return self._receive(connection, url, cap)

    def _receive(self, connection, url, cap):
        try:
            connection.request('GET', url.removeprefix('https://boards-api.greenhouse.io'), headers={
                'Accept': 'application/json', 'Accept-Encoding': 'identity', 'User-Agent': 'Jobby-public-question-inventory/1'})
            response = connection.getresponse()
            # No redirect is followed, including redirects to this origin.
            if response.status != 200:
                raise ValueError(f'Public GET HTTP {response.status}; redirects not followed')
            if response.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValueError('Compressed public response refused')
            length = response.getheader('Content-Length')
            if length is not None and (not length.isdigit() or int(length) > cap):
                raise ValueError('Public response size cap exceeded')
            chunks, size = [], 0
            while True:
                if time.monotonic() - self.started >= self.elapsed_cap or time.monotonic() - self.last >= self.timeout:
                    raise TimeoutError('Public GET wall time cap reached')
                chunk = response.read1(min(65536, cap + 1 - size))
                if not chunk:
                    break
                self.received_bytes += len(chunk)
                size += len(chunk)
                if size > cap:
                    raise ValueError('Public response size cap exceeded')
                chunks.append(chunk)
            return b''.join(chunks)
        finally:
            connection.close()


def collect(output, boards, *, target=100, per_board_cap=25, client=None):
    if type(target) is not int or not 1 <= target <= 100 or type(per_board_cap) is not int or not 1 <= per_board_cap <= 100:
        raise ValueError('Target and per-board cap must be 1..100')
    if not 1 <= len(boards) <= 12 or len(set(boards)) != len(boards):
        raise ValueError('Provide 1..12 explicit distinct board slugs')
    for board in boards:
        source_url(board)
    output = fresh_output(output)
    fs.mkdir(output / 'raw')
    client = client or PublicGreenhouse()
    started = time.monotonic()
    forms, queues, failures, seen = [], {}, [], set()
    manifest = dict(schema_version=SCHEMA, ats_scope='Greenhouse-only', started_at=utc(), status='collecting',
                    boards=boards, target=target, per_board_cap=per_board_cap,
                    sampling='Round-robin across configured boards; AI cue AND technical role, excluding nontechnical titles; source ordering within board',
                    title_filter=AI_TITLE.pattern, technical_role_filter=TECHNICAL_ROLE.pattern,
                    excluded_role_filter=NONTECHNICAL_ROLE.pattern,
                    per_board_counts={b: 0 for b in boards}, failures=failures,
                    coverage_gaps=['Static public metadata only; no hosted/conditional/widget completeness',
                                   'No candidate answers collected; unknown country not inferred'])

    def snapshot():
        questions = aggregate(forms)
        labels = {}
        for q in questions:
            key = normalize(q['label']) if isinstance(q['label'], str) else '<metadata>'
            entry = labels.setdefault(key, dict(normalized_label=key, variants=[], posting_keys=set()))
            entry['variants'].extend(v for v in q['label_variants'] if v not in entry['variants'])
            entry['posting_keys'].update(r['posting_key'] for r in q['source_refs'])
        manifest.update(updated_at=utc(), elapsed_seconds=round(time.monotonic() - started, 3),
                        valid_distinct_forms=len(forms), shortfall=max(0, target - len(forms)),
                        distinct_internal_jobs=len({(f['board'], f['internal_job_id']) for f in forms if f['internal_job_id'] is not None}),
                        null_internal_job_ids=sum(f['internal_job_id'] is None for f in forms),
                        distinct_title_families=len({(f['board'], normalize(f['title'])) for f in forms}),
                        exact_scoped_question_signatures=len(questions),
                        observed_label_repetition=[dict(normalized_label=e['normalized_label'], variants=e['variants'],
                            distinct_posting_count=len(e['posting_keys'])) for e in labels.values()],
                        http_requests=client.requests, received_bytes=client.received_bytes,
                        http_request_count_semantics='Attempted GETs including DNS/connect failures; wire sends not measured',
                        actual_model_calls=0, approved_answer_reuses=0,
                        forms=[{k: v for k, v in f.items() if k != 'questions'} for f in forms])
        save(output / 'questions.json', questions)  # Always a JSON ARRAY.
        save(output / 'manifest.json', manifest)

    sequence = 0

    def fetch(board, job_id=None):
        nonlocal sequence
        sequence += 1
        ref = dict(url=source_url(board, job_id), started_at=utc(), sequence=sequence)

        def event(stage, **kwargs):
            # Append and fsync before/after every attempt; raw source survives parse failure.
            with fs.parent(output / 'responses.jsonl') as (fd, name):
                opened = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                with os.fdopen(opened, 'w', encoding='utf-8') as log:
                    log.write(json.dumps(dict(stage=stage, **ref, **kwargs), ensure_ascii=False) + '\n')
                    log.flush()
                    os.fsync(log.fileno())

        event('request_started')
        try:
            raw = client.get(board, job_id)
            ref.update(collected_at=utc(), sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), raw_path=f'raw/{sequence:04d}.response')
            fs.create_bytes(output / ref['raw_path'], raw)
            event('response_saved')
            return decode(raw), ref
        except Exception as error:
            event('request_failed', error=type(error).__name__ + ': ' + str(error))
            raise

    snapshot()
    try:
        for board in boards:
            try:
                data, _ = fetch(board)
                if not isinstance(data, dict) or not isinstance(data.get('jobs'), list) or len(data['jobs']) > 10000:
                    raise ValueError('Malformed/oversized public jobs array')
                if not isinstance(data.get('meta'), dict) or data['meta'].get('total') != len(data['jobs']):
                    raise ValueError('Public list total mismatch; refusing silent truncation')
                queue = []
                for row in data['jobs']:
                    if not isinstance(row, dict):
                        raise ValueError('Malformed public listing')
                    if row.get('id') is None:
                        raise ValueError('Missing public listing ID')
                    source_url(board, row['id'])
                    if not isinstance(row.get('title'), str):
                        raise ValueError('Missing listing title')
                    key = (board, row['id'])
                    if key not in seen and technical_title(row['title']):
                        seen.add(key)
                        queue.append(row['id'])
                queues[board] = queue
                manifest.setdefault('discovered', {})[board] = dict(public_list_count=len(data['jobs']), distinct_ai_posting_ids=len(queue))
            except Exception as error:
                failures.append(dict(board=board, stage='list', error=type(error).__name__ + ': ' + str(error)))
            snapshot()
        while len(forms) < target and any(queues.values()) and sequence < 250:
            for board in boards:
                queue = queues.get(board, [])
                if len(forms) >= target or sequence >= 250:
                    break
                if manifest['per_board_counts'][board] >= per_board_cap:
                    queue.clear()
                if not queue:
                    continue
                job_id = queue.pop(0)
                try:
                    data, ref = fetch(board, job_id)
                    if not isinstance(data, dict) or data.get('id') != job_id:
                        raise ValueError('Public job ID mismatch')
                    if not technical_title(data.get('title', '')):
                        raise ValueError('Detail title no longer matches AI filter')
                    form = observe(board, data, ref)
                    # Check aggregate sizes before adding a form to the valid denominator.
                    encoded = json.dumps(aggregate(forms + [form]), ensure_ascii=False, indent=2, allow_nan=False).encode()
                    if len(encoded) > MAX_JSON // 2:
                        raise ValueError('Aggregate inventory size cap reached')
                    forms.append(form)
                    manifest['per_board_counts'][board] += 1
                except Exception as error:
                    failures.append(dict(board=board, job_id=job_id, stage='questions', error=type(error).__name__ + ': ' + str(error)))
                snapshot()
        manifest['status'] = 'complete' if len(forms) == target else 'shortfall'
        if sequence >= 250 and len(forms) < target:
            failures.append(dict(stage='collection', error='Request attempt cap 250 reached; no retry'))
    except BaseException:
        manifest['status'] = 'interrupted'
        raise
    finally:
        snapshot()
    return dict(ok=manifest['status'] == 'complete', manifest=str(output / 'manifest.json'),
                questions=str(output / 'questions.json'), valid_distinct_forms=len(forms),
                shortfall=manifest['shortfall'], http_requests=client.requests, actual_model_calls=0)


def verified_forms(path, count=100):
    """Revalidate stored source bytes before using them as read-only benchmark inputs."""
    manifest = load(path)
    if manifest.get('schema_version') != SCHEMA or type(count) is not int or not 1 <= count <= 100 or len(manifest.get('forms', [])) < count:
        raise ValueError('Insufficient distinct source forms or unsupported manifest')
    selected, seen, total = [], set(), 0
    for row in manifest['forms'][:count]:
        board, job_id, ref = row['board'], row['job_id'], row['source']
        if job_id is None or ref['url'] != source_url(board, job_id) or (board, job_id) in seen:
            raise ValueError('Duplicate or mismatched source reference')
        if not isinstance(ref.get('raw_path'), str) or not re.fullmatch(r'raw/[0-9]{4}\.response', ref['raw_path']):
            raise ValueError('Unsafe source raw path')
        raw = fs.read_bytes(Path(path).parent / ref['raw_path'], 2 * 1024 * 1024)
        total += len(raw)
        if total > MAX_TOTAL or hashlib.sha256(raw).hexdigest() != ref['sha256']:
            raise ValueError('Source hash/aggregate size mismatch')
        data = decode(raw)
        form = observe(board, data, ref)
        if data['id'] != job_id or not technical_title(data['title']):
            raise ValueError('Source ID/title mismatch')
        seen.add((board, job_id))
        selected.append((form, data))
    return selected


def add_parser(sub):
    output_help = f'Fresh absolute child of {Path.home() / "tmp"}'
    parser = sub.add_parser('questions', help='Greenhouse-only public inventory and explicit local answer lookup; no submissions or models')
    actions = parser.add_subparsers(dest='question_action', required=True)
    collect_parser = actions.add_parser('collect', help='Bounded public GETs; fresh incremental output, honest shortfall')
    collect_parser.add_argument('--board', action='append', required=True, help='Explicit public board slug; repeat for round-robin sampling')
    collect_parser.add_argument('--target', type=int, default=100)
    collect_parser.add_argument('--per-board-cap', type=int, default=25)
    collect_parser.add_argument('--pace', type=float, default=0.3, help='Minimum seconds between requests, 0.25..10')
    collect_parser.add_argument('--output', type=Path, required=True, help=output_help)
    lookup_parser = actions.add_parser('lookup', help='Local batch lookup; unknowns queued together; never calls a provider')
    lookup_parser.add_argument('--input', type=Path, required=True, help='Private JSON request with explicit scoped approvals; max 16 MiB')
    lookup_parser.add_argument('--output', type=Path, required=True, help=output_help + '; stdout contains counts/paths only')


def dispatch(args):
    if args.question_action == 'collect':
        return collect(args.output, args.board, target=args.target, per_board_cap=args.per_board_cap, client=PublicGreenhouse(pace=args.pace))
    from personal_jobby.question_answers import lookup_batch
    result = lookup_batch(load(args.input))
    output = fresh_output(args.output)
    save(output / 'answers.json', result)
    save(output / 'review-queue.json', result['review_queue'])
    return dict(ok=True, answers=str(output / 'answers.json'), review_queue=str(output / 'review-queue.json'), metrics=result['metrics'])
