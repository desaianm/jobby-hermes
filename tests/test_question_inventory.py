"""Public Greenhouse metadata and explicit local approvals; entirely synthetic sources."""
import copy
import json
import pytest

from personal_jobby import question_inventory as inventory


@pytest.mark.parametrize('accounts', [('account-a', 'account-b'), ('account-b', 'account-a')])
def test_fresh_output_uses_current_home_per_call(tmp_path, monkeypatch, accounts):
    from personal_jobby.greenhouse import fresh_output, save
    previous = None
    for account in accounts:
        home = tmp_path / account
        monkeypatch.setenv('HOME', str(home))
        output = home / 'tmp' / 'nested' / 'inventory'
        assert fresh_output(output) == output
        for directory in (home, home / 'tmp', output.parent, output):
            assert directory.is_dir() and directory.stat().st_mode & 0o777 == 0o700
        save(output / 'synthetic.json', {'synthetic': True})
        assert (output / 'synthetic.json').stat().st_mode & 0o777 == 0o600
        if previous is not None:
            with pytest.raises(ValueError):
                fresh_output(previous / 'fresh')
            assert not (previous / 'fresh').exists()
        previous = output.parent


@pytest.mark.parametrize('account', ['account-a', 'account-b'])
@pytest.mark.parametrize('action', ['collect', 'lookup'])
def test_output_help_and_error_bind_current_home(tmp_path, monkeypatch, capsys, account, action):
    import argparse
    from personal_jobby import greenhouse
    home = tmp_path / account
    monkeypatch.setenv('HOME', str(home))
    parser = argparse.ArgumentParser()
    greenhouse.add_parser(parser.add_subparsers())
    with pytest.raises(SystemExit) as result:
        parser.parse_args(['questions', action, '--help'])
    assert result.value.code == 0
    # argparse may wrap a long scratch path at its hyphens.
    expected_help = 'Fresh absolute child of ' + str(home / 'tmp')
    assert ''.join(expected_help.split()) in ''.join(capsys.readouterr().out.split())
    with pytest.raises(ValueError) as error:
        greenhouse.fresh_output(tmp_path / 'outside')
    assert str(error.value) == 'Output must be a fresh absolute child of ' + str(home / 'tmp')
    assert not home.exists()


@pytest.mark.parametrize('case', [
    'relative', 'root', 'outside', 'prefix-sibling', 'traversal',
    'preexisting-directory', 'preexisting-file', 'leaf-symlink',
    'dangling-symlink', 'ancestor-symlink', 'tmp-symlink', 'home-symlink',
])
def test_fresh_output_retains_private_path_guards(tmp_path, monkeypatch, case):
    from pathlib import Path
    from personal_jobby.greenhouse import fresh_output
    home = tmp_path / 'account'
    root = home / 'tmp'
    root.mkdir(parents=True)
    monkeypatch.setenv('HOME', str(home))
    output = root / 'fresh'
    expected = ValueError
    if case == 'relative':
        output = Path('relative')
    elif case == 'root':
        output = root
    elif case == 'outside':
        output = tmp_path / 'outside'
    elif case == 'prefix-sibling':
        output = home / 'tmp-sibling' / 'fresh'
    elif case == 'traversal':
        output = root / 'nested' / '..' / 'fresh'
    elif case == 'preexisting-directory':
        output.mkdir()
        expected = FileExistsError
    elif case == 'preexisting-file':
        output.write_text('synthetic')
        expected = FileExistsError
    else:
        target = tmp_path / 'target'
        target.mkdir()
        if case == 'home-symlink':
            alias = tmp_path / 'home-alias'
            alias.symlink_to(home, target_is_directory=True)
            monkeypatch.setenv('HOME', str(alias))
            output = alias / 'tmp' / 'fresh'
        elif case == 'tmp-symlink':
            root.rmdir()
            root.symlink_to(target, target_is_directory=True)
        elif case == 'ancestor-symlink':
            (root / 'linked').symlink_to(target, target_is_directory=True)
            output = root / 'linked' / 'fresh'
        else:
            output.symlink_to(target if case == 'leaf-symlink' else target / 'missing')
    with pytest.raises(expected):
        fresh_output(output)
    if case.startswith('preexisting'):
        assert output.is_dir() if case == 'preexisting-directory' else output.read_text() == 'synthetic'
    elif 'symlink' in case:
        assert list(target.iterdir()) == []
    else:
        assert not output.exists() or output == root


def job(job_id=101):
    return dict(id=job_id, internal_job_id=9, title='AI Engineer', company_name='Fictional Board',
                location={'name': 'Canada'}, language='en', content='<p>Untrusted description</p>',
                absolute_url='https://fictional.example.test/jobs/101',
                questions=[dict(label='Resume', required=True, fields=[
                    dict(name='resume', type='input_file'), dict(name='resume_text', type='textarea')]),
                    dict(label='First Name', required=True, fields=[dict(name='first_name', type='input_text')])])


def test_inventory_preserves_alternative_group_and_exact_labels_and_scoped_repetition():
    first = inventory.observe('fixture', job(), {'url': 'source-1', 'sha256': 'a' * 64})
    second_job = job(102)
    second_job['questions'][1]['label'] = '  FIRST\u00a0Name '
    second = inventory.observe('fixture', second_job, {'url': 'source-2', 'sha256': 'b' * 64})
    questions = inventory.aggregate([first, second])
    resume, name = questions
    assert resume['group_rule'] == 'at_least_one_field'
    assert resume['required'] is True and len(resume['fields']) == 2
    assert name['distinct_posting_count'] == 2
    assert name['label_variants'] == ['First Name', '  FIRST\u00a0Name ']
    assert len(name['source_refs']) == 2
    changed = job(103)
    changed['location'] = {'name': 'United States'}
    assert inventory.observe('fixture', changed, {})['questions'][1]['fingerprint'] != name['fingerprint']


def test_collection_is_incremental_deduped_and_balanced_with_honest_shortfall(tmp_path):
    from personal_jobby.greenhouse import collect

    class PublicFixture:
        requests = 0
        received_bytes = 0

        def get(self, board, job_id=None):
            self.requests += 1
            if job_id is None:
                return json.dumps({'jobs': [job(101), job(101), job(102)], 'meta': {'total': 3}}).encode()
            if board == 'other':
                raise OSError('synthetic public source unavailable')
            return json.dumps(job(job_id)).encode()

    out = tmp_path / 'collect'
    result = collect(out, ['fixture', 'other'], target=3, per_board_cap=1, client=PublicFixture())
    manifest = json.loads((out / 'manifest.json').read_text())
    assert result['ok'] is False and manifest['valid_distinct_forms'] == 1
    assert manifest['status'] == 'shortfall' and manifest['shortfall'] == 2
    assert manifest['per_board_counts'] == {'fixture': 1, 'other': 0}
    assert len(manifest['failures']) == 2
    assert manifest['distinct_internal_jobs'] == 1
    assert isinstance(json.loads((out / 'questions.json').read_text()), list)
    assert len((out / 'responses.jsonl').read_text().splitlines()) == 10
    assert len(list((out / 'raw').iterdir())) == 3


def test_explicit_approval_hits_only_exact_safe_candidate_source_scope():
    from personal_jobby.question_answers import lookup_batch
    question = inventory.observe('fixture', job(), {})['questions'][1]
    approval = dict(schema_version=1, fingerprint=question['fingerprint'], candidate_fingerprint='c' * 64,
                    source_fingerprint='d' * 64, approved=True, approved_by='Synthetic reviewer',
                    value='Fictional', approved_kind='identity')
    request = dict(schema_version=1, candidate_fingerprint='c' * 64, source_fingerprint='d' * 64,
                   cache=dict(schema_version=1, approvals=[approval]), questions=[question, copy.deepcopy(question)])
    result = lookup_batch(request)
    assert [r['status'] for r in result['results']] == ['approved', 'approved']
    assert result['metrics']['deterministic_hits'] == 2
    assert result['metrics']['actual_model_calls'] == 0
    assert not result['review_queue']
    for key in ('candidate_fingerprint', 'source_fingerprint'):
        changed = copy.deepcopy(request)
        changed[key] = 'e' * 64
        assert lookup_batch(changed)['results'][0]['status'] == 'needs_review'
    for label in ('First Name?', 'Not First Name', 'Consent to contact', 'Explain your experience'):
        changed = copy.deepcopy(request)
        q = changed['questions'][0]
        q['label'] = q['raw']['label'] = label
        q['fingerprint'] = inventory.signature(q)
        assert lookup_batch(changed)['results'][0]['status'] == 'needs_review'
    ambiguous = copy.deepcopy(request)
    ambiguous['cache']['approvals'].append({**approval, 'value': 'Conflicting Fiction'})
    assert lookup_batch(ambiguous)['results'][0]['reason'] == 'ambiguous_approval'


def test_benchmark_uses_unique_reserved_cases_and_holds_unreplayed_public_questions(tmp_path):
    from personal_jobby.greenhouse import collect
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('benchmark_runner', Path(__file__).resolve().parents[1] / 'scripts/run_synthetic_applications.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    class Source:
        requests = received_bytes = 0

        def get(self, board, job_id=None):
            self.requests += 1
            data = {'jobs': [job(101), job(102)], 'meta': {'total': 2}} if job_id is None else job(job_id)
            return json.dumps(data).encode()

    out = tmp_path / 'source'
    collect(out, ['fixture'], target=2, client=Source())
    matrix = runner.benchmark_matrix(out / 'manifest.json', 2)
    assert [r['id'] for r in matrix['roles']] == ['benchmark-001', 'benchmark-002']
    assert [r['source_input']['posting_key'] for r in matrix['roles']] == ['fixture:101', 'fixture:102']
    for role in matrix['roles']:
        assert role['url'].startswith('https://applications.example.test/jobs/benchmark-')
        assert role['description'].startswith('FICTIONAL MOCK EMPLOYER ONLY.')
        assert role['public_form_coverage']['replayed_public_fields'] == 0
        assert len(role['public_form_coverage']['held_groups']) == 2
        assert role['gaps']
    with pytest.raises(ValueError, match='Insufficient'):
        runner.benchmark_matrix(out / 'manifest.json', 100)
    for bad in ['benchmark-000', 'benchmark-101', 'benchmark-01', 'benchmark-001/../../evil']:
        with pytest.raises(ValueError):
            runner.validate_case_id(bad)


def test_scoped_fingerprints_stop_option_employer_type_punctuation_and_country_drift():
    base = job()
    base['questions'] = [dict(label='<img src=x onerror=alert(1)> Do you agree?', required=True,
                              fields=[dict(name='question_7', type='multi_value_single_select',
                                           values=[dict(value='YES', label='Yes'), dict(value='NO', label='No')])])]
    observed = inventory.observe('fixture', base, {})['questions'][0]
    assert observed['label'] == '<img src=x onerror=alert(1)> Do you agree?'
    assert observed['fields'][0]['values'][0]['value'] == 'YES'
    changes = [dict(company_name='Different Employer'), dict(country='CA'), dict(language='fr')]
    variants = [{**copy.deepcopy(base), **c} for c in changes]
    for mutate in ('label', 'field_type', 'option_value', 'option_label', 'required'):
        changed = copy.deepcopy(base)
        q = changed['questions'][0]
        if mutate == 'label':
            q['label'] = q['label'].replace('agree?', 'not agree?')
        elif mutate == 'field_type':
            q['fields'][0]['type'] = 'multi_value_multi_select'
        elif mutate == 'option_value':
            q['fields'][0]['values'][0]['value'] = 'yes'
        elif mutate == 'option_label':
            q['fields'][0]['values'][0]['label'] = 'No'
        else:
            q['required'] = False
        variants.append(changed)
    assert all(inventory.observe('fixture', v, {})['questions'][0]['fingerprint'] != observed['fingerprint'] for v in variants)


def test_compliance_demographic_consent_and_hidden_location_are_preserved_but_never_cached():
    from personal_jobby.question_answers import lookup_batch
    data = job()
    data.update(location_questions=[dict(label='Latitude', required=True, fields=[dict(name='latitude', type='input_hidden')])],
        compliance=[dict(label='Veteran status', required=False, fields=[dict(name='veteran', type='multi_value_single_select', values=[dict(value=1, label='Decline')])])],
        data_compliance=[dict(type='gdpr', requires_processing_consent=True, requires_retention_consent=True)],
        demographic_questions=dict(header='Fictional inclusion', description='<b>untrusted</b>', questions=[dict(
            id=7, label='Optional demographic', required=False, type='multi_value_single_select',
            answer_options=[dict(id=11, label='Decline', free_form=False)])]),
        ai_disclaimer='<p>Untrusted disclosure</p>')
    observed = inventory.observe('fixture', data, {})
    kinds = {q['context']['kind'] for q in observed['questions']}
    assert kinds == {'questions', 'location_questions', 'compliance', 'data_compliance', 'demographic_questions', 'disclosures'}
    result = lookup_batch(dict(schema_version=1, candidate_fingerprint='c' * 64, source_fingerprint='d' * 64,
        cache={'schema_version': 1, 'approvals': []}, questions=observed['questions']))
    assert all(q['status'] == 'needs_review' for q in result['results'])
    assert result['metrics']['actual_model_calls'] == 0


@pytest.mark.parametrize('bad', [None, {}, {'id': None}, {'id': True}, {'id': -1},
    {**job(), 'questions': None}, {**job(), 'questions': []}, {**job(), 'location_questions': {}},
    {**job(), 'internal_job_id': []}, {**job(), 'compliance': [None]}])
def test_null_or_malformed_forms_never_enter_valid_denominator(bad):
    with pytest.raises((ValueError, TypeError)):
        inventory.observe('fixture', bad, {})


def test_interruption_keeps_raw_response_and_last_valid_inventory(tmp_path):
    from personal_jobby.greenhouse import collect

    class Interrupted:
        requests = received_bytes = 0

        def get(self, board, job_id=None):
            self.requests += 1
            if job_id == 102:
                raise KeyboardInterrupt('synthetic interruption')
            return json.dumps({'jobs': [job(101), job(102)], 'meta': {'total': 2}} if job_id is None else job(job_id)).encode()

    out = tmp_path / 'interrupted'
    with pytest.raises(KeyboardInterrupt):
        collect(out, ['fixture'], target=2, client=Interrupted())
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['status'] == 'interrupted' and manifest['valid_distinct_forms'] == 1
    assert len(json.loads((out / 'questions.json').read_text())) == 2
    assert len(list((out / 'raw').iterdir())) == 2
    assert json.loads((out / 'responses.jsonl').read_text().splitlines()[-1])['stage'] == 'request_started'


def test_public_client_fixed_get_no_redirects_and_size_request_caps(monkeypatch):
    from personal_jobby import greenhouse
    calls = []
    response = {'status': 302, 'headers': {'Location': 'https://forbidden.example.test/submit'}, 'body': b'{}'}

    class Connection:
        def __init__(self, host, **kwargs):
            calls.append(host)

        def request(self, method, path, **kwargs):
            calls.append((method, path, kwargs['headers']))

        def getresponse(self):
            return self

        @property
        def status(self):
            return response['status']

        def getheader(self, key, default=None):
            return response['headers'].get(key, default)

        def read1(self, count):
            body = response['body'][:count]
            response['body'] = response['body'][count:]
            return body

        def close(self):
            pass

    monkeypatch.setattr(greenhouse.http.client, 'HTTPSConnection', Connection)
    client = greenhouse.PublicGreenhouse(request_cap=1)
    with pytest.raises(ValueError, match='HTTP 302'):
        client.get('fixture', 101)
    with pytest.raises(ValueError, match='cap'):
        client.get('fixture', 102)
    assert calls[0] == 'boards-api.greenhouse.io'
    assert calls[1][0:2] == ('GET', '/v1/boards/fixture/jobs/101?questions=true')
    assert not {'Authorization', 'Cookie'} & calls[1][2].keys()
    for board in ('../evil', 'fixture?redirect=x', 'https://evil.test', 'FIXTURE'):
        with pytest.raises(ValueError):
            greenhouse.PublicGreenhouse().get(board, 101)
    for bad_id in ('101/submit', -1, True, 10**20):
        with pytest.raises(ValueError):
            greenhouse.PublicGreenhouse().get('fixture', bad_id)
    response.update(status=200, headers={'Content-Length': str(2 * 1024 * 1024 + 1)})
    with pytest.raises(ValueError, match='size cap'):
        greenhouse.PublicGreenhouse().get('fixture', 101)


def test_public_request_deadline_interrupts_blocked_connect_or_headers(monkeypatch):
    from personal_jobby import greenhouse
    import time

    class BlockedHeaders:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            time.sleep(2)  # Includes DNS/connect/header work, before any read loop.

        def getresponse(self):
            raise AssertionError('Deadline should interrupt the connect/request stage')

        def close(self):
            pass

    monkeypatch.setattr(greenhouse.http.client, 'HTTPSConnection', BlockedHeaders)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match='deadline'):
        greenhouse.PublicGreenhouse(timeout=1).get('fixture', 101)
    assert time.monotonic() - started < 1.8


def test_native_benchmark_bounds_and_origin_paths_remain_exact():
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(['/home/adcan288/.local/bin/node', '--input-type=module', '-e', '''
        import assert from 'node:assert/strict';
        import {routeKind,transportRouteKind,validCaseId} from './browser/synthetic-applications.mjs';
        for(const id of ['benchmark-001','benchmark-100']) {
          const row={id},origin='http://127.0.0.1:12345';
          assert.equal(routeKind(`https://applications.example.test/jobs/${id}`,'GET',row),'form');
          assert.equal(transportRouteKind(origin+`/submit/${id}`,'POST',row,origin),'post');
          for(const url of [`https://evil.test/submit/${id}`,origin+`/submit/${id}?x`,origin+'/submit/benchmark-002'])
            assert.equal(transportRouteKind(url,'POST',row,origin),'abort');
        }
        for(const id of ['benchmark-000','benchmark-101','benchmark-01','benchmark-001/../evil'])
          assert.equal(validCaseId(id),false);
        for(const origin of ['https://evil.test','http://localhost:12345','http://127.0.0.1:99999'])
          assert.equal(transportRouteKind(origin+'/submit/benchmark-001','POST',{id:'benchmark-001'},origin),'abort');
    '''], cwd=root, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_hundred_distinct_inputs_do_not_imply_hundred_job_families_and_hashes_are_checked(tmp_path):
    from personal_jobby.greenhouse import collect, verified_forms

    class Hundred:
        requests = received_bytes = 0

        def get(self, board, job_id=None):
            self.requests += 1
            return json.dumps({'jobs': [job(i) for i in range(1, 101)], 'meta': {'total': 100}}
                              if job_id is None else job(job_id)).encode()

    out = tmp_path / 'hundred'
    result = collect(out, ['fixture'], target=100, per_board_cap=100, client=Hundred())
    assert result['ok'] and result['valid_distinct_forms'] == 100 and result['http_requests'] == 101
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['distinct_internal_jobs'] == 1 and manifest['distinct_title_families'] == 1
    selected = verified_forms(out / 'manifest.json')
    assert len({f['posting_key'] for f, _ in selected}) == 100
    raw = out / manifest['forms'][0]['source']['raw_path']
    raw.write_bytes(b'{}')
    with pytest.raises(ValueError, match='hash'):
        verified_forms(out / 'manifest.json')


def test_aggregate_size_and_input_caps_preserve_shortfall_and_raw_evidence(tmp_path, monkeypatch):
    from personal_jobby import greenhouse

    class LargeForm:
        requests = received_bytes = 0

        def get(self, board, job_id=None):
            self.requests += 1
            data = job()
            if job_id is None:
                return json.dumps(dict(jobs=[data], meta={'total': 1})).encode()
            data['questions'] = [dict(label=str(i) + 'x' * 300, required=True,
                fields=[dict(name='question_' + str(i), type='input_text')]) for i in range(30)]
            return json.dumps(data).encode()

    monkeypatch.setattr(greenhouse, 'MAX_JSON', 16000)
    out = tmp_path / 'oversize'
    result = greenhouse.collect(out, ['fixture'], target=1, client=LargeForm())
    assert not result['ok'] and result['valid_distinct_forms'] == 0
    manifest = json.loads((out / 'manifest.json').read_text())
    assert 'Aggregate inventory size cap' in manifest['failures'][0]['error']
    assert len(list((out / 'raw').iterdir())) == 2
    path = tmp_path / 'large-input.json'
    path.write_text(' ' * 16001)
    with pytest.raises(ValueError, match='size limit|JSON exceeds'):
        greenhouse.load(path)
    with pytest.raises(ValueError, match='Aggregate JSON'):
        greenhouse.save(tmp_path / 'large-output.json', ['x' * 16001])


def test_unknown_essay_legal_and_demographic_approvals_cannot_override_holds():
    from personal_jobby.question_answers import lookup_batch
    data = job()
    data['questions'] = [dict(label=label, required=True, fields=[dict(name='first_name', type=kind)])
        for label, kind in [('I consent to processing', 'input_text'), ('Why this company?', 'textarea'),
                            ('Are you authorized to work here?', 'input_text'), ('Ethnic background', 'input_text')]]
    questions = inventory.observe('fixture', data, {})['questions']
    approvals = [dict(schema_version=1, fingerprint=q['fingerprint'], candidate_fingerprint='c' * 64,
        source_fingerprint='d' * 64, approved=True, approved_by='Synthetic reviewer', value='Never send', approved_kind='identity')
        for q in questions]
    result = lookup_batch(dict(schema_version=1, candidate_fingerprint='c' * 64, source_fingerprint='d' * 64,
        questions=questions, cache=dict(schema_version=1, approvals=approvals)))
    assert result['metrics']['deterministic_hits'] == 0 and len(result['review_queue']) == 4
    assert all(r['reason'] == 'unsupported_or_sensitive_prompt' and 'value' not in r for r in result['results'])


def test_lookup_cli_stdout_is_json_without_answers_or_active_profile_access(tmp_path):
    import os
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    question = inventory.observe('fixture', job(), {})['questions'][1]
    approval = dict(schema_version=1, fingerprint=question['fingerprint'], candidate_fingerprint='c' * 64,
        source_fingerprint='d' * 64, approved=True, approved_by='Synthetic reviewer', approved_kind='identity', value='FictionalPrivateValue')
    request = tmp_path / 'request.json'
    request.write_text(json.dumps(dict(schema_version=1, candidate_fingerprint='c' * 64, source_fingerprint='d' * 64,
        questions=[question], cache=dict(schema_version=1, approvals=[approval]))))
    unused_root = tmp_path / 'must-not-initialize'
    home = tmp_path / 'unused-home'
    output = home / 'tmp' / 'lookup'
    result = subprocess.run([str(root / 'personal_jobby/bin/jobby'), 'questions', 'lookup', '--input', str(request),
        '--output', str(output)], cwd=tmp_path, capture_output=True, text=True, timeout=10,
        env={'PATH': '/usr/bin:/bin', 'JOBBY_ROOT': str(unused_root), 'HOME': str(home)})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['metrics']['deterministic_hits'] == 1
    assert 'FictionalPrivateValue' not in result.stdout + result.stderr
    assert not unused_root.exists()
    assert json.loads((output / 'answers.json').read_text())['results'][0]['value'] == 'FictionalPrivateValue'
    assert output.stat().st_mode & 0o777 == 0o700
    assert (output / 'answers.json').stat().st_mode & 0o777 == 0o600


def test_collection_shortfall_cli_is_nonzero_with_one_json_result(monkeypatch, capsys, tmp_path):
    import sys
    from personal_jobby.__main__ import main
    from personal_jobby import greenhouse
    monkeypatch.setattr(sys, 'argv', ['jobby', 'questions', 'collect', '--board', 'fixture', '--output', str(tmp_path / 'unused')])
    monkeypatch.setattr(greenhouse, 'dispatch', lambda args: dict(ok=False, valid_distinct_forms=0, shortfall=100))
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == dict(ok=False, valid_distinct_forms=0, shortfall=100)
    assert captured.err == ''


def test_two_case_preparation_keeps_unique_native_attempts_and_synthetic_targets(tmp_path):
    from personal_jobby.greenhouse import collect
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]

    class Source:
        requests = received_bytes = 0

        def get(self, board, job_id=None):
            self.requests += 1
            return json.dumps(dict(jobs=[job(101), job(102)], meta={'total': 2}) if job_id is None else job(job_id)).encode()

    source = tmp_path / 'source'
    collect(source, ['fixture'], target=2, client=Source())
    output = tmp_path / 'prepared'
    result = subprocess.run([str(root / '.venv/bin/python'), str(root / 'scripts/run_synthetic_applications.py'),
        '--source-manifest', str(source / 'manifest.json'), '--case-limit', '2', '--prepare-only', '--output', str(output)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env={'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path / 'unused-home'), 'PYTHON_DOTENV_DISABLED': '1'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['browser_executed'] is False
    report = json.loads((output / 'report.json').read_text())
    assert len({r['attempt_id'] for r in report['roles']}) == 2
    assert len({r['manifest']['generation_id'] for r in report['roles']}) == 2
    for row in report['roles']:
        assert row['truth_checked'] and row['post_count'] == 0
        assert row['manifest']['application_url'] == row['url']
        assert row['url'].startswith('https://applications.example.test/jobs/benchmark-')
        assert Path(row['artifact_directory']).is_relative_to(output)
    assert report['metrics']['actual_model_calls'] == 0
    assert report['metrics']['elapsed_seconds'] > 0
