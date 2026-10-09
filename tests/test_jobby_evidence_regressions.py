import json
from copy import deepcopy

import pytest

from personal_jobby.core import Salary, public_url, salary_decision
from personal_jobby.privacy import sanitize, sanitize_text


def evidence(raw, **changes):
    return dict(raw=raw, origin='employer', verified=True, currency='CAD',
                unit='annual', kind='base', lower=120000, upper=150000,
                source_url='https://jobs.ashbyhq.com/fixture/12345678-abcd-1234-abcd-123456789abc',
                **changes)


def base_salary():
    return {'@type': 'MonetaryAmount', 'currency': 'CAD', 'value': {
        '@type': 'QuantitativeValue', 'minValue': 120000, 'maxValue': 150000,
        'unitText': 'YEAR'}}


def test_exact_structured_employer_base_salary_preserves_raw():
    raw = json.dumps(base_salary())
    salary = Salary(**evidence(raw)).model_dump()
    assert salary_decision(salary, 120000)[0] == 'eligible'
    assert salary['raw'] == raw


def test_public_numeric_job_url_survives_sanitizing():
    url = 'https://job-boards.greenhouse.io/fixture/jobs/1000000001'
    assert sanitize({'source_url': url})['source_url'] == public_url(url)


@pytest.mark.parametrize('wrapper', ['bare', 'baseSalary', 'JobPosting'])
@pytest.mark.parametrize('fixed', [False, True])
def test_structured_range_and_fixed_contract(wrapper, fixed):
    obj = base_salary()
    if fixed:
        obj['value'] = {'@type': 'QuantitativeValue', 'value': 120000, 'unitText': 'YEAR'}
    if wrapper == 'baseSalary': obj = {'baseSalary': obj}
    if wrapper == 'JobPosting': obj = {'@context': 'https://schema.org', '@type': 'JobPosting', 'baseSalary': obj}
    raw = json.dumps(obj, separators=(',', ':'))
    salary = evidence(raw)
    if fixed: salary['upper'] = None
    assert salary_decision(salary, 120000)[0] == 'eligible'
    assert Salary(**salary).raw == raw


@pytest.mark.parametrize('change', [
    {'origin': 'aggregator'}, {'verified': False}, {'source_url': ''},
    {'source_url': 'http://127.0.0.1/jobs/1'}, {'currency': 'USD'},
    {'unit': 'monthly'}, {'kind': 'TC'}, {'kind': 'bonus'},
    {'lower': 125000}, {'upper': 160000}, {'lower': None},
])
def test_structured_source_and_entered_bounds_must_match(change):
    salary = evidence(json.dumps(base_salary()))
    salary.update(change)
    assert salary_decision(salary, 120000)[0] == 'needs_review'


@pytest.mark.parametrize('case', [
    'missing_currency', 'missing_unit', 'month', 'hour', 'usd', 'tc', 'bonus',
    'list', 'nested', 'extra_number', 'negative', 'nan', 'infinity', 'upper_only',
    'reversed', 'mixed_fixed', 'string_number', 'bool_number', 'wrong_type',
    'duplicate', 'arbitrary_wrapper', 'malformed',
])
def test_ambiguous_or_invalid_structured_salary_is_held(case):
    obj = deepcopy(base_salary())
    val = obj['value']
    if case == 'missing_currency': del obj['currency']
    elif case == 'missing_unit': del val['unitText']
    elif case in ('month', 'hour'): val['unitText'] = case.upper()
    elif case == 'usd': obj['currency'] = 'USD'
    elif case in ('tc', 'bonus'): obj['name'] = case
    elif case == 'list': obj = [obj]
    elif case == 'nested': obj = {'unrelated': obj, 'number': 120000}
    elif case == 'extra_number': val['unrelated'] = 120000
    elif case == 'negative': val['minValue'] = -1
    elif case == 'nan': val['minValue'] = float('nan')
    elif case == 'infinity': val['maxValue'] = float('inf')
    elif case == 'upper_only': del val['minValue']
    elif case == 'reversed': val.update(minValue=150000, maxValue=120000)
    elif case == 'mixed_fixed': val['value'] = 120000
    elif case == 'string_number': val['minValue'] = '120000'
    elif case == 'bool_number': val['minValue'] = True
    elif case == 'wrong_type': obj['@type'] = 'PriceSpecification'
    elif case == 'arbitrary_wrapper': obj = {'@type': 'Offer', 'baseSalary': obj}
    raw = json.dumps(obj)
    if case == 'duplicate': raw = raw.replace('"currency": "CAD"', '"currency": "USD", "currency": "CAD"')
    if case == 'malformed': raw = raw[:-1]
    assert salary_decision(evidence(raw), 120000)[0] == 'needs_review'


@pytest.mark.parametrize('low,high,floor,result', [
    (100000, 150000, 120000, 'needs_review'),
    (90000, 100000, 120000, 'excluded'),
    (120000, 150000, 120000, 'eligible'),
    (120000, 150000, 160000, 'excluded'),
])
def test_structured_salary_preserves_floor_policy(low, high, floor, result):
    obj = base_salary()
    obj['value'].update(minValue=low, maxValue=high)
    salary = evidence(json.dumps(obj))
    salary.update(lower=low, upper=high)
    assert salary_decision(salary, floor)[0] == result


@pytest.mark.parametrize('url', [
    'https://job-boards.greenhouse.io/fixture/jobs/1000000001?gh_jid=1000000001&gh_jid=1000000002&utm_source=test%20source',
    'https://boards.greenhouse.io/fixture/jobs/1000000001/',
    'https://jobs.ashbyhq.com/fixture/12345678-abcd-1234-abcd-123456789abc?utm_source=test',
    'https://jobs.lever.co/fixture/12345678-abcd-1234-abcd-123456789abc',
    'https://ca.indeed.com/viewjob?jk=1000000001&jk=1000000002',
    'https://fixture.taleo.net/careersection/external/jobdetail.ftl?job=1000000001&job=1000000002',
    'https://fixture.wd1.myworkdayjobs.com/en-US/Careers/job/Toronto/Engineer_R1000000001',
])
def test_validated_ats_identifiers_and_raw_url_are_lossless(url):
    assert sanitize_text(url) == url
    assert public_url(sanitize_text(url)) == url
    assert sanitize({'event': {'url': url}, 'artifact': [url]}) == {'event': {'url': url}, 'artifact': [url]}


@pytest.mark.parametrize('phone', [
    '4165550199', '+14165550199', '416-555-0199', '(416) 555-0199',
    '+1 416 555 0199', '416.555.0199', '416\t555\t0199',
])
def test_free_text_phone_variants_remain_masked(phone):
    result = sanitize_text('Call ' + phone)
    assert '[private phone]' in result
    assert not any(character.isdigit() for character in result)
    result = sanitize({'phone': phone, 'phone_history': [phone], 'note': phone})
    assert set(result) == {'note'}
    assert '[private phone]' in result['note']
    assert not any(character.isdigit() for character in result['note'])


@pytest.mark.parametrize('key', ['phone', 'tel', 'contact', 'mobile', 'other'])
@pytest.mark.parametrize('value', ['4165550199', '%2B1%20416%20555%200199', '%34%31%36%35%35%35%30%31%39%39', '416%2D555%2D0199'])
def test_contact_query_values_are_masked_even_on_job_urls(key, value):
    url = f'https://job-boards.greenhouse.io/fixture/jobs/1000000001?{key}={value}&gh_jid=1000000001'
    assert sanitize_text(url) == f'https://job-boards.greenhouse.io/fixture/jobs/1000000001?{key}=[private phone]&gh_jid=1000000001'


@pytest.mark.parametrize('url', [
    'https://example.com/jobs/4165550199',
    'https://job-boards.greenhouse.io/fixture/contact/4165550199',
    'https://job-boards.greenhouse.io/fixture/jobs/%34%31%36%35%35%35%30%31%39%39',
    'https://job-boards.greenhouse.io/fixture/jobs/416-555-0199',
    'https://job-boards.greenhouse.io.evil.example/fixture/jobs/4165550199',
    'https://4165550199@job-boards.greenhouse.io/fixture/jobs/4165550199',
    'https://%34%31%36%35%35%35%30%31%39%39@job-boards.greenhouse.io/fixture/jobs/4165550199',
    'https://ca.indeed.com/viewjob?jk=416-555-0199',
])
def test_untrusted_and_malformed_identifiers_and_userinfo_are_masked(url):
    result = sanitize_text(url)
    assert '[private phone]' in result
    assert '4165550199' not in result
    assert '416-555-0199' not in result
    assert '%34%31%36' not in result


@pytest.mark.parametrize('field', ['requisition', 'job_id', 'jobID', 'jobId', 'posting_id'])
def test_semantic_identifier_fields_are_bounded(field):
    assert sanitize({field: '1000000001'}) == {field: '1000000001'}
    assert sanitize({field: 'Call 416-555-0199'}) == {field: 'Call [private phone]'}
    assert sanitize({field: '416-555-0199'}) == {field: '[private phone]'}
    assert sanitize({'note': '1000000001'}) == {'note': '[private phone]'}


def test_temp_store_lookup_and_daily_verify_preserve_exact_evidence(tmp_path):
    from personal_jobby.store import Store
    from personal_jobby.daily import Daily
    store = Store(tmp_path)
    url = 'https://job-boards.greenhouse.io/fixture/jobs/1000000001?gh_jid=1000000001&gh_jid=1000000002'
    job = dict(title='AI Engineer', company='Synthetic Fixture', job_url=url,
               requisition='1000000001', location='Toronto', description='Synthetic test only. Python.',
               original_source={'job_url_direct': url})
    first = store.add(job)
    assert first['job_url'] == url
    assert first['requisition'] == '1000000001'
    assert store.add(job)['id'] == first['id']
    raw = 'JobPosting.baseSalary: {"@type":"MonetaryAmount","currency":"CAD","value":{"@type":"QuantitativeValue","minValue":120000,"maxValue":150000,"unitText":"YEAR"}}'
    salary = evidence(raw)
    assert salary_decision(salary, 120000)[0] == 'eligible'
    salary['source_url'] = url
    result = Daily(store).verify_job(first['id'], {
        'salary': salary, 'operator_note': 'Synthetic structured baseSalary fixture; no fetch.'})
    assert result['salary']['raw'] == raw
    assert result['salary']['source_url'] == url
    saved = store.job_snapshot(first['id'])
    assert saved['original_source']['employer_salary_verification']['salary']['raw'] == raw
    # Salary evidence must not bypass other eligibility checks.
    assert result['eligibility'] == 'needs_review'


def test_public_ats_host_case_preserves_original_string():
    url = 'HTTPS://JOB-BOARDS.GREENHOUSE.IO/fixture/jobs/1000000001?gh_jid=1000000001'
    assert public_url(url) == url
    assert sanitize_text(url) == url


@pytest.mark.parametrize('prefix,tail', [
    ('jobPosting.baseSalary: ', ''),
    ('JobPosting.basesalary: ', ''),
    ('JobPosting.totalCompensation: ', ''),
    ('Unknown.baseSalary: ', ''),
    ('junk JobPosting.baseSalary: ', ''),
    ('JobPosting.baseSalary:', ''),
    ('JobPosting.baseSalary: ', ' junk'),
    ('JobPosting.baseSalary: ', '{}'),
    ('JobPosting.baseSalary: ', ','),
])
def test_labelled_salary_rejects_unknown_prefixes_and_json_tails(prefix, tail):
    raw = prefix + json.dumps(base_salary()) + tail
    assert salary_decision(evidence(raw), 120000)[0] == 'needs_review'


@pytest.mark.parametrize('change', [
    {'origin': 'aggregator'}, {'verified': False}, {'source_url': ''},
    {'source_url': 'http://127.0.0.1/jobs/1'}, {'currency': 'USD'},
    {'unit': 'monthly'}, {'kind': 'TC'}, {'lower': 125000}, {'upper': 160000},
])
def test_labelled_salary_preserves_source_validation(change):
    salary = evidence('JobPosting.baseSalary: ' + json.dumps(base_salary()))
    salary.update(change)
    assert salary_decision(salary, 120000)[0] == 'needs_review'


@pytest.mark.parametrize('case', ['malformed', 'prose', 'unit', 'currency', 'bounds'])
def test_labelled_salary_preserves_strict_payload_validation(case):
    obj = base_salary()
    if case == 'unit': obj['value']['unitText'] = 'MONTH'
    elif case == 'currency': obj['currency'] = 'USD'
    elif case == 'bounds': obj['value']['maxValue'] = 100000
    raw = json.dumps(obj)
    if case == 'malformed': raw = raw[:-1]
    if case == 'prose': raw = 'CAD 120000 - 150000 annual base'
    assert salary_decision(evidence('JobPosting.baseSalary: \t' + raw), 120000)[0] == 'needs_review'
