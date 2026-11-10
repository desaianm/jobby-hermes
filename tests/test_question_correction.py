"""Bounded regressions at public observation, cache, native and receiver seams."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest
from personal_jobby import question_inventory as inventory
from personal_jobby.question_answers import lookup_batch

ROOT = Path(__file__).resolve().parents[1]


def public_job():
    return json.loads((ROOT / 'tests/fixtures/greenhouse-public-shape.json').read_text())


def runner_module():
    spec = importlib.util.spec_from_file_location('correction_runner', ROOT / 'scripts/run_synthetic_applications.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request_for(question):
    return dict(schema_version=1, candidate_fingerprint='a' * 64, source_fingerprint='b' * 64,
        questions=[question], cache=dict(schema_version=1, approvals=[dict(schema_version=1,
            fingerprint=question['fingerprint'], candidate_fingerprint='a' * 64, source_fingerprint='b' * 64,
            approved=True, approved_kind='identity', approved_by='Controlled fixture test', value='AI Agent')]))


def test_real_nested_compliance_and_returned_null_keep_primary_form_and_exact_context():
    data = public_job()
    form = inventory.observe('fixture', data, {})
    compliance = [q for q in form['questions'] if q['context']['kind'] == 'compliance']
    assert [q['label'] for q in compliance] == ['Gender', 'Veteran status']
    assert compliance[0]['fields'][0]['values'] == [{'label': 'Decline', 'value': 0}, {'label': 'Self describe', 'value': 'other'}]
    assert compliance[0]['context']['group_context'] == dict(section_index=0, type='eeoc', description='&lt;p&gt;Voluntary disclosure&lt;/p&gt;')
    changed = copy.deepcopy(data)
    changed['compliance'][0]['description'] = 'Different disclosure'
    assert inventory.observe('fixture', changed, {})['questions'][-2]['fingerprint'] != compliance[0]['fingerprint']
    data.update(compliance=None, location_questions=None, data_compliance=None)
    form = inventory.observe('fixture', data, {})
    assert len(form['questions']) == 6
    assert form['coverage']['group_status']['compliance'] == 'returned_null_coverage_unknown'
    assert any('returned null' in gap for gap in form['coverage']['gaps'])
    for primary in (None, [], {}, [None]):
        with pytest.raises(ValueError):
            inventory.observe('fixture', {**data, 'questions': primary}, {})


def test_null_empty_description_identity_matches_but_nonempty_context_holds():
    data = public_job()
    data['compliance'] = []
    first = inventory.observe('fixture', data, {})['questions'][0]
    assert lookup_batch(request_for(first))['results'][0]['status'] == 'approved'
    for description in ('', ' ', '<p>Use a legal human identity</p>'):
        changed = copy.deepcopy(data)
        changed['questions'][0]['description'] = description
        q = inventory.observe('fixture', changed, {})['questions'][0]
        assert q['raw']['description'] == description
        assert q['fingerprint'] != first['fingerprint']
        result = lookup_batch(request_for(q))['results'][0]
        assert result['status'] == ('approved' if description == '' else 'needs_review')


def test_canonical_phone_matching_scoped_approval_stays_held_and_queued():
    question = next(q for q in inventory.observe('fixture', public_job(), {})['questions']
                    if q['label'] == 'Phone')
    assert question['raw'] == dict(description=None, label='Phone', required=False,
        fields=[dict(name='phone', type='input_text', values=[])])
    request = request_for(question)
    request['cache']['approvals'][0].update(approved_kind='contact', value='+15550100123')
    original = copy.deepcopy(request)

    result = lookup_batch(request)

    assert result['results'][0]['status'] == 'needs_review'
    assert result['results'] == [dict(fingerprint=question['fingerprint'], status='needs_review',
        reason='unsupported_or_sensitive_prompt')]
    assert len(result['review_queue']) == 1
    held = result['review_queue'][0]
    assert held['status'] == 'needs_review' and held['reason'] == 'unsupported_or_sensitive_prompt'
    assert held['question'] == question and held['fingerprint'] == question['fingerprint']
    assert held['candidate_fingerprint'] == request['candidate_fingerprint']
    assert held['source_fingerprint'] == request['source_fingerprint']
    assert held['occurrences'] == 1 and 'value' not in held
    assert result['metrics']['deterministic_hits'] == 0
    assert result['metrics']['deterministic_misses'] == 1
    assert result['metrics']['ai_orchestration_needed'] == 1
    assert request == original


@pytest.mark.parametrize('title,expected', [
    ('AI Engineer', True), ('AI Infrastructure System Engineer Bangalore', True),
    ('AI Automation Engineer', True), ('ML Platform Engineer', True), ('Research Scientist', True),
    ('Research Engineer, Inference', True), ('Machine Learning Researcher', True),
    ('Account Executive, AI Native', False), ('AI Advisory Principal', False),
    ('Account Director, Enterprise AI', False), ('Director, GTM Systems & AI Transformation', False),
    ('AI Tutor, Applied Math - Temporary', False), ('Finance Research Analyst', False),
    ('AI Sales Engineer', False), ('Software Engineer', False), ('AI Recruiter', False),
])
def test_conservative_technical_title(title, expected):
    assert inventory.technical_title(title) is expected


def test_discovery_and_saved_verification_share_title_predicate(tmp_path):
    from personal_jobby.greenhouse import collect, verified_forms
    titles = ['Account Executive, AI Native', 'Research Scientist', 'AI Tutor', 'ML Engineer']

    class Source:
        requests = received_bytes = 0

        def get(self, board, job_id=None):
            self.requests += 1
            jobs = [{**public_job(), 'id': i, 'title': title} for i, title in enumerate(titles, 1)]
            return json.dumps(dict(jobs=jobs, meta={'total': 4}) if job_id is None else jobs[job_id - 1]).encode()

    out = tmp_path / 'titles'
    result = collect(out, ['fixture'], target=2, client=Source())
    assert result['valid_distinct_forms'] == 2
    assert [f['job_id'] for f, _ in verified_forms(out / 'manifest.json', 2)] == [2, 4]
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['title_filter'] == inventory.AI_TITLE.pattern
    assert manifest['technical_role_filter'] == inventory.TECHNICAL_ROLE.pattern
    # Even hash-valid old broad-filter collections must be held at the import seam.
    import hashlib
    row = manifest['forms'][0]
    path = out / row['source']['raw_path']
    data = json.loads(path.read_bytes())
    data['title'] = titles[0]
    path.write_text(json.dumps(data))
    row['source']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='title'):
        verified_forms(out / 'manifest.json', 2)


def collect_two(tmp_path, *, mutate_second=None):
    from personal_jobby.greenhouse import collect

    class Source:
        requests = received_bytes = 0

        def get(self, board, job_id=None):
            self.requests += 1
            jobs = [{**public_job(), 'id': 101}, {**public_job(), 'id': 102}]
            if mutate_second:
                mutate_second(jobs[1])
            return json.dumps(dict(jobs=jobs, meta={'total': 2}) if job_id is None else jobs[job_id - 101]).encode()

    out = tmp_path / 'public'
    collect(out, ['fixture'], target=2, client=Source())
    return out / 'manifest.json'


def test_benchmark_uses_disclosed_nonhuman_fixture_with_imported_support_and_no_human_history(tmp_path):
    import subprocess
    import fitz
    from docx import Document
    runner = runner_module()
    manifest = collect_two(tmp_path)
    matrix = runner.benchmark_matrix(manifest, 2)
    assert matrix['candidate']['name'] == 'AI Agent — NON-HUMAN SYNTHETIC FIXTURE'
    assert matrix['candidate']['email'] == 'agent@example.test'
    assert matrix['candidate']['answers'] == {}
    assert not {'location', 'phone'} & set(matrix['candidate'])
    output = tmp_path / 'identity-prepared'
    result = subprocess.run([str(ROOT / '.venv/bin/python'), str(ROOT / 'scripts/run_synthetic_applications.py'),
        '--source-manifest', str(manifest), '--case-limit', '2', '--prepare-only', '--output', str(output)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['browser_executed'] is False
    report = json.loads((output / 'report.json').read_text())
    profile = json.loads((output / 'hermes-profile/plugin-data/jobby/workspace/candidate.json').read_text())
    assert not any(f['section'] in ('EXPERIENCE', 'EDUCATION') for f in profile['facts'])
    texts = [(output / 'source-fixture.json').read_text()]
    for pdf in [output / 'fictional-source.pdf'] + [Path(r['artifact_directory']) / n for r in report['roles'] for n in ('resume.pdf', 'cover_letter.pdf')]:
        with fitz.open(pdf) as doc:
            texts.append(' '.join(p.get_text() for p in doc))
    for docx in [output / 'fictional-source.docx'] + [Path(r['artifact_directory']) / n for r in report['roles'] for n in ('resume.docx', 'cover_letter.docx')]:
        texts.append(' '.join(p.text for p in Document(docx).paragraphs))
    for text in texts:
        assert 'AI Agent' in text
        assert not any(term in text for term in ('Rowan', 'B.Sc.', 'Example Institute', 'Paper Lantern', 'Jan 2024', 'RAG'))
    for row in report['roles']:
        assert row['truth_checked'] and row['supported_fact_ids']
        assert all(fid in {f['id'] for f in profile['facts']} for fid in row['supported_fact_ids'])
        assert row['post_count'] == 0


def test_controlled_fixture_cache_reuses_only_exact_safe_identity_and_scopes(tmp_path):
    from personal_jobby.question_answers import controlled_fixture_batch
    runner = runner_module()
    identity = runner.benchmark_matrix(collect_two(tmp_path), 2)['candidate']
    questions = inventory.observe('fixture', public_job(), {})['questions']
    scopes = dict(candidate_fingerprint=inventory.digest(identity), source_fingerprint=inventory.digest(public_job()))
    cache = dict(schema_version=1, approvals=[])
    first = controlled_fixture_batch(questions, cache, identity=identity, **scopes)
    assert first['metrics']['first_time_synthetic_approvals'] == 3
    assert first['metrics']['existing_cache_hits'] == 0
    assert first['metrics']['deterministic_hits'] == 3
    assert {f['name']: f['value'] for f in first['fields']} == {
        'first_name': 'AI', 'last_name': 'Agent (NON-HUMAN SYNTHETIC FIXTURE)', 'email': 'agent@example.test'}
    assert all(q['status'] == 'needs_review' for q in first['review_queue'])
    assert len(first['review_queue']) == 5
    second = controlled_fixture_batch(questions, cache, identity=identity, **scopes)
    assert second['metrics']['first_time_synthetic_approvals'] == 0
    assert second['metrics']['existing_cache_hits'] == 3
    for key in ('company_name', 'location'):
        data = public_job()
        data[key] = 'Changed context'
        changed = controlled_fixture_batch(inventory.observe('fixture', data, {})['questions'], cache, identity=identity, **scopes)
        assert changed['metrics']['existing_cache_hits'] == 0
        assert changed['metrics']['first_time_synthetic_approvals'] == 3
    drift = controlled_fixture_batch(questions, cache, identity=identity,
        **{**scopes, 'source_fingerprint': inventory.digest('changed source')})
    assert drift['metrics']['existing_cache_hits'] == 0 and drift['metrics']['first_time_synthetic_approvals'] == 3
    data = public_job()
    data['questions'][0]['fields'][0]['values'] = [{'label': 'AI', 'value': 'AI'}]
    changed = controlled_fixture_batch(inventory.observe('fixture', data, {})['questions'], cache, identity=identity, **scopes)
    assert 'first_name' not in {f['name'] for f in changed['fields']}
    tampered = copy.deepcopy(cache)
    tampered['approvals'][0]['value'] = 'Fabricated Human'
    with pytest.raises(ValueError, match='value'):
        controlled_fixture_batch(questions, tampered, identity=identity, **scopes)


@pytest.fixture
def controlled_prepared(tmp_path):
    import subprocess
    manifest = collect_two(tmp_path)
    output = tmp_path / 'controlled-prepared'
    result = subprocess.run([str(ROOT / '.venv/bin/python'), str(ROOT / 'scripts/run_synthetic_applications.py'),
        '--source-manifest', str(manifest), '--controlled-agent-answers', '--case-limit', '2',
        '--prepare-only', '--output', str(output)], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['browser_executed'] is False
    return output, json.loads((output / 'report.json').read_text())


def test_native_two_case_preparation_binds_actual_lookup_values_and_current_material_scope(controlled_prepared):
    from personal_jobby.artifacts import bindings
    from personal_jobby.store import Store
    output, report = controlled_prepared
    store = Store(output / 'hermes-profile/plugin-data/jobby/workspace')
    first, second = report['roles']
    assert first['answer_metrics']['first_time_synthetic_approvals'] == 3
    assert first['answer_metrics']['existing_cache_hits'] == 0
    assert second['answer_metrics']['first_time_synthetic_approvals'] == 0
    assert second['answer_metrics']['existing_cache_hits'] == 3
    assert report['metrics']['deterministic_answer_hits'] == 6
    assert report['metrics']['existing_cache_hits'] == 3
    assert report['benchmark']['public_form_mapped_fields'] == 6
    assert report['benchmark']['public_form_replayed_fields'] == 0
    assert len({r['attempt_id'] for r in report['roles']}) == 2
    cache = json.loads((output / 'controlled-answer-cache.json').read_text())
    assert len(cache['approvals']) == 3
    for row in report['roles']:
        coverage = row['public_form_coverage']
        assert coverage['mapped_public_fields'] == 3
        assert coverage['replayed_public_fields'] == 0
        assert len(coverage['held_groups']) == 5
        assert {g['fingerprint'] for g in coverage['matched_groups']} == {f['fingerprint'] for f in row['controlled_answers']['fields']}
        current = bindings(store, row['job_id'])
        assert row['answer_scope_materials'] == {k: current[k] for k in ('candidate', 'sources', 'settings')}
        assert all(a['candidate_fingerprint'] == row['controlled_answers']['candidate_fingerprint'] for a in cache['approvals'])
        proof = json.loads((output / (row['id'] + '.controlled-answer-binding.json')).read_text())
        assert proof['attempt_id'] == row['attempt_id'] and proof['controlled_answers'] == row['controlled_answers']
        assert row['post_count'] == 0
    assert (output / 'controlled-answer-cache.json').stat().st_mode & 0o777 == 0o600
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in output.glob('*.json'))


def test_controlled_fields_reach_native_multipart_validator_and_reject_tamper(controlled_prepared):
    import subprocess
    output, _ = controlled_prepared
    result = subprocess.run(['/home/adcan288/.local/bin/node', '--input-type=module', '-e', r'''
      import assert from 'node:assert/strict';
      import {readFile} from 'node:fs/promises';
      import {renderFixture,validateMultipart} from './browser/synthetic-applications.mjs';
      const report=JSON.parse(await readFile(process.argv[1]+'/report.json','utf8'));
      for(const row of report.roles) {
        const html=renderFixture(row);
        assert.ok(html.includes('AI Agent'));
        assert.ok(!html.includes('Rowan') && !html.includes('eligibility') && !html.includes('Fictional location'));
        for(const field of row.controlled_answers.fields) {
          assert.ok(html.includes(`name="${field.name}"`));
          assert.ok(html.includes(field.fingerprint));
        }
        assert.ok(!html.includes('Why this role?') && !html.includes('Public shape fixture'));
        for(const mode of ['valid','value','extra','duplicate','hash','config-value','config-label']) {
          const config=structuredClone(row), data=new FormData();
          for(const [key,value] of Object.entries({attempt_id:row.attempt_id,
            gaps:row.gaps.map(g=>`Not supported: ${g.claim}`).join('; '),private_fixture:'fictional-preserved'})) data.set(key,value);
          for(const field of row.controlled_answers.fields) data.set(field.name,field.value);
          if(mode==='value') data.set('first_name','Fabricated human');
          if(mode==='extra') data.set('phone','5551234567');
          if(mode==='duplicate') data.append('email','agent@example.test');
          if(mode==='config-value') config.controlled_answers.fields[0].value='Fabricated human';
          if(mode==='config-label') config.controlled_answers.fields[0].label='<img src=x onerror=alert(1)>';
          data.set('resume',new Blob([mode==='hash'?Buffer.from('wrong'):await readFile(row.resume_path)]),'resume.pdf');
          const encoded=new Request('http://fixture.test',{method:'POST',body:data});
          const parsed=await new Request('http://fixture.test',{method:'POST',headers:encoded.headers,body:await encoded.arrayBuffer()}).formData();
          if(mode==='valid') {
            const proof=await validateMultipart(config,parsed,0);
            assert.equal(proof.resume_sha256,row.manifest.resume.sha256);
            assert.deepEqual(proof.submitted_safe_fields,row.controlled_answers.fields);
            await assert.rejects(()=>validateMultipart(config,parsed,1));
          } else await assert.rejects(()=>validateMultipart(config,parsed,0));
        }
      }
    ''', str(output)], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_controlled_native_http_receiver_archives_actual_safe_fields(controlled_prepared):
    """Real HTTP check; retain literal listener restrictions without skipping them."""
    import subprocess
    output, _ = controlled_prepared
    result = subprocess.run(['/home/adcan288/.local/bin/node', '--input-type=module', '-e', r'''
      import assert from 'node:assert/strict';
      import {readFile} from 'node:fs/promises';
      import {createHash} from 'node:crypto';
      import {startFixture} from './browser/synthetic-applications.mjs';
      const report=JSON.parse(await readFile(process.argv[1]+'/report.json','utf8'));
      for(const row of report.roles) {
        const fixture=await startFixture(row);
        try {
          const form=await fetch(fixture.origin+'/jobs/'+row.id);
          assert.equal(form.status,200);
          const html=await form.text();
          for(const f of row.controlled_answers.fields) assert.ok(html.includes(f.fingerprint));
          const data=new FormData();
          data.set('attempt_id',row.attempt_id);data.set('private_fixture','fictional-preserved');
          data.set('gaps',row.gaps.map(g=>`Not supported: ${g.claim}`).join('; '));
          for(const f of row.controlled_answers.fields) data.set(f.name,f.value);
          data.set('resume',new Blob([await readFile(row.resume_path)]),'resume.pdf');
          const response=await fetch(fixture.origin+'/submit/'+row.id,{method:'POST',body:data});
          assert.equal(response.status,200);assert.ok((await response.text()).includes('synthetic test only'));
          assert.deepEqual(fixture.captured.submitted_safe_fields,row.controlled_answers.fields);
          const actual=await readFile(fixture.captured.multipart_path);
          assert.equal(createHash('sha256').update(actual).digest('hex'),fixture.captured.multipart_sha256);
          const parsed=await new Request(fixture.origin,{method:'POST',headers:{'content-type':fixture.captured.content_type},body:actual}).formData();
          for(const f of row.controlled_answers.fields) assert.equal(parsed.get(f.name),f.value);
          assert.equal((await fetch(fixture.origin+'/submit/'+row.id,{method:'POST',body:data})).status,400);
          assert.equal(fixture.postCount,1);
        } finally {await fixture.close()}
      }
    ''', str(output)], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_controlled_receipt_rejects_missing_or_changed_actual_field_proof(controlled_prepared):
    from personal_jobby.store import Store
    output, report = controlled_prepared
    row = report['roles'][0]
    store = Store(output / 'hermes-profile/plugin-data/jobby/workspace')
    event = dict(outcome='confirmation_observed', post_count=1,
        resume_sha256=row['manifest']['resume']['sha256'], attempt_id=row['attempt_id'], role_id=row['id'],
        text='synthetic test only — no real employer application',
        rendered_safe_fields=row['controlled_answers']['fields'])
    runner = runner_module()
    for fields in (None, [], [{**f, 'value': 'tampered'} for f in row['controlled_answers']['fields']]):
        with pytest.raises(ValueError, match='answer receipt proof'):
            runner.reconcile(store, row, {**event, 'submitted_safe_fields': fields})
    assert row['public_form_coverage']['replayed_public_fields'] == 0
