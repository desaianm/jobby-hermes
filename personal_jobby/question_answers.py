"""Explicit local approvals for narrow identity/contact questions. No model integration."""
import re
import time
from personal_jobby.question_inventory import SCHEMA, normalize, signature

HEX = re.compile(r'[0-9a-f]{64}\Z')
# A deliberately small safe surface. Other prompts stay held even if a cache file claims approval.
SAFE = {'first_name': ('first name', 'identity'), 'last_name': ('last name', 'identity'),
        'email': ('email', 'contact')}
CONTROLLED_POLICY = 'controlled-nonhuman-fixture-v1'


def safe_kind(q):
    fields, raw = q.get('fields'), q.get('raw', {})
    if (q.get('context', {}).get('kind') != 'questions' or q.get('group_rule') != 'at_least_one_field'
            or not isinstance(q.get('label'), str) or not isinstance(fields, list) or len(fields) != 1
            or not isinstance(raw, dict) or set(raw) - {'label', 'required', 'fields', 'description'}
            or raw.get('description') not in (None, '')
            or not {'label', 'required', 'fields'} <= set(raw) or raw['fields'] != fields
            or raw['label'] != q['label'] or raw['required'] != q['required']):
        return None
    field = fields[0]
    known = SAFE.get(field.get('name'))
    if (not known or normalize(q['label']) != known[0] or field.get('type') != 'input_text'
            or set(field) - {'name', 'type', 'values'} or field.get('values', []) != []):
        return None
    return known[1]


def lookup_batch(request):
    started = time.monotonic()
    if not isinstance(request, dict) or request.get('schema_version') != SCHEMA:
        raise ValueError('Unsupported answer request schema')
    for key in ('candidate_fingerprint', 'source_fingerprint'):
        if not isinstance(request.get(key), str) or not HEX.fullmatch(request[key]):
            raise ValueError('Explicit candidate/source SHA-256 fingerprints required')
    questions, cache = request.get('questions'), request.get('cache', {})
    if not isinstance(questions, list) or not 1 <= len(questions) <= 5000 or not isinstance(cache, dict):
        raise ValueError('Invalid bounded answer batch')
    approvals = cache.get('approvals', [])
    if not isinstance(approvals, list) or len(approvals) > 5000 or any(not isinstance(a, dict) for a in approvals):
        raise ValueError('Invalid bounded approvals')
    index = {}
    for a in approvals:
        if isinstance(a.get('fingerprint'), str):
            index.setdefault(a['fingerprint'], []).append(a)
    results, queue, hits = [], {}, 0
    for q in questions:
        if not isinstance(q, dict) or q.get('fingerprint') != signature(q):
            raise ValueError('Question signature mismatch')
        fp, kind = q['fingerprint'], safe_kind(q)
        reason = 'unapproved_or_stale_scope'
        matching = []
        if not kind:
            reason = 'unsupported_or_sensitive_prompt'
        elif cache.get('schema_version') != SCHEMA:
            reason = 'stale_cache_schema'
        else:
            matching = [a for a in index.get(fp, []) if a.get('schema_version') == SCHEMA
                        and a.get('candidate_fingerprint') == request['candidate_fingerprint']
                        and a.get('source_fingerprint') == request['source_fingerprint']
                        and a.get('approved') is True and a.get('approved_kind') == kind
                        and isinstance(a.get('approved_by'), str) and 1 <= len(a['approved_by'].strip()) <= 250
                        and isinstance(a.get('value'), str) and 1 <= len(a['value']) <= 500]
        if len(matching) == 1:
            hits += 1
            results.append(dict(fingerprint=fp, status='approved', value=matching[0]['value']))
        else:
            if len(matching) > 1:
                reason = 'ambiguous_approval'
            results.append(dict(fingerprint=fp, status='needs_review', reason=reason))
            entry = queue.setdefault(fp, dict(fingerprint=fp, status='needs_review', reason=reason, question=q,
                candidate_fingerprint=request['candidate_fingerprint'], source_fingerprint=request['source_fingerprint'], occurrences=0,
                resolution='Explicit scoped approval for safe identity/contact only; other prompts remain held for individual review'))
            entry['occurrences'] += 1
    return dict(schema_version=SCHEMA, results=results, review_queue=list(queue.values()), metrics=dict(
        deterministic_hits=hits, deterministic_misses=len(questions) - hits, ai_orchestration_needed=len(queue),
        actual_model_calls=0, http_requests=0, elapsed_seconds=round(time.monotonic() - started, 6)))


def controlled_fixture_batch(questions, cache, *, identity, candidate_fingerprint, source_fingerprint):
    """Explicit synthetic policy, callable only by the optional controlled runner.

    Cache is owned by one fresh run. No human approval or employer send authority.
    All answers still pass through the same exact-signature batch lookup.
    """
    if (identity.get('name') != 'AI Agent — NON-HUMAN SYNTHETIC FIXTURE'
            or identity.get('first_name') != 'AI'
            or identity.get('last_name') != 'Agent (NON-HUMAN SYNTHETIC FIXTURE)'
            or identity.get('email') != 'agent@example.test' or identity.get('answers') != {}):
        raise ValueError('Controlled non-human fixture identity required')
    values = {key: identity[key] for key in ('first_name', 'last_name', 'email')}
    request = dict(schema_version=SCHEMA, questions=questions, cache=cache,
                   candidate_fingerprint=candidate_fingerprint, source_fingerprint=source_fingerprint)
    before = lookup_batch(request)
    eligible = [q for q in questions if safe_kind(q) and q['fields'][0]['name'] in values]
    # Multiple source groups for the same control are ambiguous; render none of them.
    counts = {name: sum(q['fields'][0]['name'] == name for q in eligible) for name in values}
    eligible = [q for q in eligible if counts[q['fields'][0]['name']] == 1]
    allowed = {q['fingerprint'] for q in eligible}
    created = existing = 0
    for q, result in zip(questions, before['results']):
        if q['fingerprint'] not in allowed:
            continue
        value = values[q['fields'][0]['name']]
        if result['status'] == 'approved':
            if result['value'] != value:
                raise ValueError('Controlled approved value differs from authoritative fixture')
            existing += 1
        elif result['reason'] == 'unapproved_or_stale_scope':
            cache['approvals'].append(dict(schema_version=SCHEMA, fingerprint=q['fingerprint'],
                candidate_fingerprint=candidate_fingerprint, source_fingerprint=source_fingerprint,
                approved=True, approved_by=CONTROLLED_POLICY, approved_kind=safe_kind(q), value=value))
            created += 1
    result = lookup_batch(request)
    fields = []
    for q, answer in zip(questions, result['results']):
        if q['fingerprint'] in allowed and answer['status'] == 'approved':
            name = q['fields'][0]['name']
            fields.append(dict(fingerprint=q['fingerprint'], name=name, source_type='input_text',
                type='email' if name == 'email' else 'text', label=SAFE[name][0].title(),
                required=q['required'], value=answer['value']))
        elif answer['status'] == 'approved':
            # This owned cache must never contain a phone or other out-of-policy approval.
            raise ValueError('Out-of-policy controlled approval')
    result.update(fields=fields, policy=CONTROLLED_POLICY)
    result['metrics'].update(first_time_synthetic_approvals=created, existing_cache_hits=existing)
    return result
