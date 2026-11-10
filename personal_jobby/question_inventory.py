"""Read-only Greenhouse question observations. Source strings are data, never instructions."""
import copy
import hashlib
import json
import re
import unicodedata

SCHEMA = 1
ORIGIN = 'https://boards-api.greenhouse.io'
BOARD = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}\Z')
AI_TITLE = re.compile(r'\b(ai|artificial intelligence|machine learning|ml|llm|research|inference|reinforcement|robotics|computer vision|deep learning)\b', re.I)
TECHNICAL_ROLE = re.compile(r'\b(engineer|engineering|scientist|researcher)\b', re.I)
NONTECHNICAL_ROLE = re.compile(r'\b(sales|advisory|account|gtm|tutor|recruiter|analyst)\b', re.I)


def technical_title(title):
    """Literal conservative engineering/research sample; no company-wide inference."""
    return bool(isinstance(title, str) and AI_TITLE.search(title) and TECHNICAL_ROLE.search(title)
                and not NONTECHNICAL_ROLE.search(title))


def normalize(value):
    return ' '.join(unicodedata.normalize('NFC', value).split()).casefold()


def canonical(value):
    # Identifiers and submitted option values remain exact, including type/case/whitespace.
    if isinstance(value, dict):
        return {k: v if k in ('value', 'name', 'type', 'id') else canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return normalize(value) if isinstance(value, str) else value


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def source_url(board, job_id=None):
    if not isinstance(board, str) or not BOARD.fullmatch(board):
        raise ValueError('Invalid Greenhouse board slug')
    if job_id is not None and (type(job_id) is not int or not 1 <= job_id <= 10**15):
        raise ValueError('Invalid Greenhouse posting ID')
    return f'{ORIGIN}/v1/boards/{board}/jobs' + (f'/{job_id}?questions=true' if job_id is not None else '')


def signature(question):
    return digest(canonical({k: question[k] for k in ('label', 'required', 'fields', 'group_rule', 'context', 'raw')}))


def observe(board, job, ref):
    """Validate a public job form; preserve raw metadata and per-question grouping."""
    if not isinstance(job, dict):
        raise ValueError('Job response must be an object')
    if job.get('id') is None:
        raise ValueError('Missing public posting ID')
    source_url(board, job['id'])
    if job.get('internal_job_id') is not None and (type(job['internal_job_id']) is not int or not 1 <= job['internal_job_id'] <= 10**15):
        raise ValueError('Malformed internal job ID')
    if not isinstance(job.get('title'), str) or not job['title'].strip() or len(job['title']) > 1000:
        raise ValueError('Missing or oversized posting title')
    if not isinstance(job.get('questions'), list) or not job['questions']:
        raise ValueError('Missing nonempty public questions array')
    context = dict(ats='greenhouse', api_version='v1', schema_version=SCHEMA, board=board,
                   company=job.get('company_name'), location=job.get('location'),
                   country=job.get('country'), language=job.get('language'),
                   # Unknown country stays unknown; do not infer it from a city name.
                   country_resolution='source_only_no_inference')
    questions = []

    def add(raw, kind, group_context=None):
        if not isinstance(raw, dict):
            raise ValueError('Question must be an object')
        label = raw.get('label')
        metadata = kind in ('data_compliance', 'disclosures')
        if not metadata and (not isinstance(label, str) or len(label) > 16000 or type(raw.get('required')) is not bool):
            raise ValueError('Question label/requiredness malformed')
        fields = raw.get('fields')
        if kind == 'demographic_questions':
            if not isinstance(raw.get('answer_options'), list) or not isinstance(raw.get('type'), str):
                raise ValueError('Malformed demographic question')
            fields = [dict(name=str(raw.get('id')), type=raw['type'], values=raw['answer_options'])]
        elif metadata:
            fields = []  # Consent flags are metadata, never invented input labels/options.
        if not isinstance(fields, list) or (not metadata and not fields) or len(fields) > 50:
            raise ValueError('Malformed grouped fields')
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get('name'), str) or not isinstance(field.get('type'), str):
                raise ValueError('Malformed field name/type')
            if 'values' in field and (not isinstance(field['values'], list) or len(field['values']) > 1000):
                raise ValueError('Malformed or oversized options')
            for option in field.get('values', []):
                value_key = 'id' if kind == 'demographic_questions' else 'value'
                if (not isinstance(option, dict) or not isinstance(option.get('label'), str)
                        or len(option['label']) > 16000 or type(option.get(value_key)) not in (str, int, bool)):
                    raise ValueError('Malformed option label/value')
        q = dict(label=label, required=raw.get('required'), fields=copy.deepcopy(fields), raw=copy.deepcopy(raw),
                 group_rule='metadata_only' if metadata else 'at_least_one_field',
                 context={**context, 'kind': kind, 'group_context': copy.deepcopy(group_context)})
        q['fingerprint'] = signature(q)
        q['source_refs'] = [{**ref, 'posting_key': f'{board}:{job["id"]}', 'kind': kind, 'index': len(questions)}]
        questions.append(q)

    group_names = ('questions', 'location_questions', 'compliance', 'data_compliance', 'demographic_questions')
    group_status = {key: ('absent_coverage_unknown' if key not in job else
                         'returned_null_coverage_unknown' if job[key] is None else
                         'returned_empty' if job[key] in ([], {}) else 'returned') for key in group_names}
    for key in ('questions', 'location_questions', 'compliance', 'data_compliance'):
        rows = job.get(key, [])
        if rows is None and key != 'questions':
            continue
        if not isinstance(rows, list) or len(rows) > 500:
            raise ValueError('Null/malformed/oversized question group: ' + key)
        for section_index, row in enumerate(rows):
            if key == 'compliance' and isinstance(row, dict) and 'questions' in row:
                if not isinstance(row['questions'], list) or len(row['questions']) > 500:
                    raise ValueError('Malformed nested compliance questions')
                section = {**{k: v for k, v in row.items() if k != 'questions'}, 'section_index': section_index}
                for inner in row['questions']:
                    add(inner, key, section)
            else:
                add(row, key)
    demographic = job.get('demographic_questions')
    if demographic is not None:
        if not isinstance(demographic, dict) or not isinstance(demographic.get('questions'), list) or len(demographic['questions']) > 500:
            raise ValueError('Malformed demographic group')
        for row in demographic['questions']:
            add(row, 'demographic_questions', {k: v for k, v in demographic.items() if k != 'questions'})
    disclosures = {k: job[k] for k in ('include_ai_disclaimer', 'ai_disclaimer', 'ai_opt_out_request_url', 'privacy_policy_url') if k in job}
    if disclosures:
        add(disclosures, 'disclosures')
    if len(questions) > 1000:
        raise ValueError('Too many aggregate questions in form')
    return dict(board=board, job_id=job['id'], posting_key=f'{board}:{job["id"]}',
                internal_job_id=job.get('internal_job_id'), title=job['title'], questions=questions,
                source=ref, coverage=dict(returned_groups=[k for k in group_names if k in job], group_status=group_status,
                gaps=['Greenhouse-only static public metadata; no hosted widgets, conditional browser fields or CAPTCHA inspection',
                      'Absent groups are not evidence that no questions exist; country is not inferred'] +
                     [key + ' returned null; coverage unknown (raw response retained)' for key in group_names if job.get(key, []) is None]))


def aggregate(forms):
    inventory = {}
    for form in forms:
        for q in form['questions']:
            item = inventory.setdefault(q['fingerprint'], {**copy.deepcopy(q), 'source_refs': [], 'label_variants': []})
            if q['label'] not in item['label_variants']:
                item['label_variants'].append(q['label'])
            item['source_refs'].extend(q['source_refs'])
    for item in inventory.values():
        item['distinct_posting_count'] = len({r['posting_key'] for r in item['source_refs']})
    return list(inventory.values())
