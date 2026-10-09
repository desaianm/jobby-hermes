"""Verified audit regressions; synthetic state only, no discovery or submissions."""
from datetime import datetime, timezone
import json

import pytest

from personal_jobby.audit import add_screenshot
from personal_jobby.daily import Daily
from personal_jobby.store import Store
from test_jobby_daily import ready_attempt


@pytest.mark.parametrize('artifact', ['resume', 'filled_form', 'employer_confirmation'])
@pytest.mark.parametrize('damage', ['corrupt', 'delete'])
def test_disabled_pilot_receipt_requires_intact_archives(tmp_path, artifact, damage):
    daily = Daily(Store(tmp_path))
    job, attempt, image = ready_attempt(daily)
    confirmation = add_screenshot(daily.store, attempt['id'], image,
                                  'employer_confirmation', 'Synthetic reviewed confirmation', True)
    archive = tmp_path / 'applications' / attempt['id']
    if artifact == 'resume':
        target = archive / 'documents' / 'resume.pdf'
    else:
        shot = confirmation if artifact == 'employer_confirmation' else daily.store.get(job['id'])['attempts'][0]['screenshots'][0]
        target = archive / 'screenshots' / shot['filename']
    if damage == 'delete':
        target.unlink()
    else:
        target.write_bytes(b'Synthetic corrupt archive')
    with pytest.raises((ValueError, OSError)):
        daily.store.receipt(job['id'], text='Synthetic confirmation',
                            timestamp=datetime.now(timezone.utc).isoformat(), attempt_id=attempt['id'])
    assert daily.store.get(job['id'])['status'] != 'applied'


@pytest.mark.parametrize('changed', ['job', 'profile'])
def test_generation_rejects_changes_after_render_snapshot(tmp_path, monkeypatch, changed):
    from personal_jobby.documents import prepare
    from test_personal_jobby import document_workspace
    store, job = document_workspace(tmp_path)
    method = 'get' if changed == 'job' else 'public_profile'
    read = getattr(store, method)
    fired = False

    def concurrent_read(*args):
        nonlocal fired
        snapshot = read(*args)
        if not fired:
            fired = True
            if changed == 'job':
                posting = store.job_snapshot(job['id'])
                posting['title'] = 'ML Engineer'
                with store.connect() as connection:
                    connection.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(posting), job['id']))
            else:
                profile = store.profile()
                profile['facts'][0]['text'] = 'Built synthetic replacement services.'
                (tmp_path / 'candidate.json').write_text(json.dumps(profile))
        return snapshot

    monkeypatch.setattr(store, method, concurrent_read)
    with pytest.raises(ValueError, match='Inputs changed'):
        prepare(store, job['id'])
    assert store.materials(job['id'])['qa_state'] == 'generation_in_progress'


def test_source_change_during_fingerprint_capture_cannot_publish(tmp_path, monkeypatch):
    import hashlib
    from personal_jobby import private_fs as fs
    from personal_jobby.documents import prepare
    from test_personal_jobby import document_workspace
    store, job = document_workspace(tmp_path)
    source = tmp_path / 'synthetic-authoritative.txt'
    source.write_bytes(b'Synthetic original source')
    profile = store.profile()
    profile['source_hashes'] = {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}
    (tmp_path / 'candidate.json').write_text(json.dumps(profile))
    read = fs.read_bytes
    changed = False

    def concurrent_source_read(path, **kwargs):
        nonlocal changed
        data = read(path, **kwargs)
        if path == str(source) and not changed:
            changed = True
            source.write_bytes(b'Synthetic replacement source')
        return data

    monkeypatch.setattr(fs, 'read_bytes', concurrent_source_read)
    with pytest.raises(ValueError, match='Inputs changed'):
        prepare(store, job['id'])
    assert store.materials(job['id'])['qa_state'] == 'generation_in_progress'


@pytest.mark.parametrize('text', [
    'Not remote in Canada.', 'No remote work in Canada.',
    'Remote in Canada. This role is onsite only.',
    'Remote in Canada. Remote work is not available.',
])
def test_negated_or_contradictory_remote_source_is_held(tmp_path, text):
    from test_personal_jobby import verified_job
    posting = verified_job()
    posting.update(location='Canada', arrangement='remote', arrangement_evidence=text,
                   description=text + ' Permanent full-time.')
    assert Store(tmp_path).add(posting)['eligibility'] == 'needs_review'


@pytest.mark.parametrize('period', ['monthly', 'weekly', 'per month', 'per week', '/month', '/week'])
def test_nonannual_salary_source_cannot_use_annual_metadata(tmp_path, period):
    from test_personal_jobby import verified_job
    posting = verified_job()
    raw = 'CAD 120000 base salary ' + period
    posting['salary'].update(raw=raw)
    store = Store(tmp_path)
    job = store.add(posting)
    assert job['eligibility'] == 'needs_review'
    assert store.job_snapshot(job['id'])['salary']['raw'] == raw
    with pytest.raises(ValueError, match='annual CAD base'):
        Daily(store).verify_job(job['id'], {'salary': posting['salary'], 'operator_note': 'Synthetic conflicting period'})


@pytest.mark.parametrize('text', [
    'Not a permanent full-time role.', 'Not a full-time permanent position.',
    'Permanent full-time employment is not offered.',
])
def test_negated_permanent_full_time_source_is_held(tmp_path, text):
    from test_personal_jobby import verified_job
    posting = verified_job()
    posting.update(employment_evidence=text, description='Hybrid in Toronto. ' + text)
    assert Store(tmp_path).add(posting)['eligibility'] == 'needs_review'


def test_employment_negation_in_location_is_held():
    from personal_jobby.core import Job, assess
    from test_personal_jobby import confirmed_settings, verified_job
    posting = verified_job()
    posting.update(location='Toronto. Not a permanent full-time role.',
                   description='Hybrid in Toronto.',
                   employment_evidence='Not a permanent full-time role.')
    job = Job(**posting).model_dump()
    state, reasons = assess(job, confirmed_settings(), {})
    assert state == 'needs_review'
    assert 'Negated or contradictory permanent full-time evidence' in reasons
    assert job['location'] == posting['location']
    assert job['employment_evidence'] == posting['employment_evidence']


@pytest.mark.parametrize('field', ['password', 'api_key', 'accessToken', 'client_secret', 'Authorization', 'cookie', 'private_key'])
def test_posting_secret_fields_are_omitted_from_storage_and_output(tmp_path, field):
    from personal_jobby.cli_operations import show
    from test_personal_jobby import verified_job
    posting = verified_job()
    posting['original_source'] = {'nested': [{field: 'synthetic-confidential-value', 'jobId': '1000000001'}]}
    store = Store(tmp_path)
    job = store.add(posting)
    assert 'synthetic-confidential-value' not in json.dumps(show(store, job['id']))
    assert store.job_snapshot(job['id'])['original_source']['nested'] == [{'jobId': '1000000001'}]
    assert job['salary']['raw'] == posting['salary']['raw']


@pytest.mark.parametrize('credential', [
    'Bearer synthetic-bearer-value', 'password=synthetic-password-value',
    'api_key: synthetic-api-value', 'sk-synthetic-key-value',
    'ghp_syntheticCredentialValue',
    'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmaXh0dXJlIn0.syntheticSignature',
])
def test_shared_credential_text_filter_covers_postings_and_receipts(tmp_path, credential):
    from personal_jobby.cli_operations import show
    from test_personal_jobby import verified_job
    posting = verified_job()
    posting['description'] += ' ' + credential
    posting['original_source'] = {'note': credential}
    store = Store(tmp_path)
    job = store.add(posting)
    result = store.receipt(job['id'], text='Synthetic confirmation ' + credential,
                           timestamp=datetime.now(timezone.utc).isoformat())
    for record in (store.job_snapshot(job['id']), show(store, job['id']), result):
        assert credential not in json.dumps(record)
        assert '[private credential]' in json.dumps(record)


@pytest.mark.parametrize('suffix', [
    '?token=synthetic-nonnumeric-value', '?access_token=synthetic-nonnumeric-value',
    '?api%5Fkey=synthetic-nonnumeric-value', '#password=synthetic-nonnumeric-value',
    '?X-Amz-Signature=synthetic-nonnumeric-value',
    '?other=sk-synthetic-nonnumeric-value',
])
def test_sensitive_url_components_filtered_without_losing_posting_id(tmp_path, suffix):
    from personal_jobby.cli_operations import show
    from test_personal_jobby import verified_job
    posting = verified_job()
    public = 'https://job-boards.greenhouse.io/fixture/jobs/1000000001'
    posting['job_url'] = public + suffix
    store = Store(tmp_path)
    job = store.add(posting)
    result = store.receipt(job['id'], text='Synthetic confirmation', url=public + suffix,
                           timestamp=datetime.now(timezone.utc).isoformat())
    for record in (store.job_snapshot(job['id']), show(store, job['id']), result):
        serialized = json.dumps(record)
        assert 'synthetic-nonnumeric-value' not in serialized
        assert public in serialized
        assert '[private credential]' in serialized


def test_filtered_posting_source_is_explicitly_marked_without_retaining_raw_secrets(tmp_path):
    from personal_jobby.artifacts import digest
    from test_personal_jobby import verified_job
    posting = verified_job()
    posting['original_source'] = {'password': 'synthetic-input-secret', 'jobId': '1000000001'}
    posting['description'] += ' password=synthetic-input-secret'
    store = Store(tmp_path)
    job = store.add(posting)
    provenance = store.job_snapshot(job['id'])['original_source']['privacy_filtration']
    assert provenance['input_sha256'] == digest(posting)
    assert provenance['raw_retained'] is False
    assert provenance['snapshot'] == 'filtered; not exact source evidence'
    assert 'synthetic-input-secret' not in json.dumps(store.job_snapshot(job['id']))


@pytest.mark.parametrize('boundary,field', [
    ('add', 'salary'), ('add', 'arrangement_evidence'), ('add', 'employment_evidence'),
    ('verify', 'salary'), ('fit', 'arrangement_evidence'), ('fit', 'employment_evidence'),
])
def test_credential_contaminated_exact_evidence_is_rejected(tmp_path, boundary, field):
    from test_personal_jobby import verified_job
    posting = verified_job()
    store = Store(tmp_path)
    job = store.add(posting) if boundary != 'add' else None
    if field == 'salary':
        posting['salary']['raw'] += ' token=synthetic-evidence-secret'
    else:
        posting[field] += ' token=synthetic-evidence-secret'
        posting['description'] += ' ' + posting[field]
    with pytest.raises(ValueError):
        if boundary == 'add':
            store.add(posting)
        elif boundary == 'verify':
            Daily(store).verify_job(job['id'], {'salary': posting['salary'], 'operator_note': 'Synthetic contaminated proof'})
        else:
            from personal_jobby.cli_operations import fit
            path = tmp_path / 'fit.json'
            path.write_text(json.dumps({key: posting[key] for key in (
                'arrangement', 'arrangement_evidence', 'employment_type', 'employment_evidence')}))
            fit(store, job['id'], path)
    if boundary == 'add':
        assert store.jobs() == []
    else:
        assert 'synthetic-evidence-secret' not in json.dumps(store.job_snapshot(job['id']))


@pytest.mark.parametrize('relative', ['.', 'synthetic-relative-state'])
def test_cli_rejects_relative_root_before_creating_state(tmp_path, relative):
    import os
    from pathlib import Path
    import subprocess
    launcher = Path(__file__).resolve().parents[1] / 'personal_jobby' / 'bin' / 'jobby'
    process = subprocess.run([str(launcher), 'status', '--brief'], cwd=tmp_path,
                             env={**os.environ, 'JOBBY_ROOT': relative}, capture_output=True, text=True)
    assert process.returncode == 1
    assert process.stdout == ''
    assert 'input values withheld' in process.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('context', ['field', 'ats_query'])
def test_identifier_exemption_does_not_preserve_credential_shapes(context):
    from personal_jobby.privacy import sanitize
    credential = 'ghp_syntheticCredentialValue'
    value = ({'posting_id': credential} if context == 'field' else
             {'url': 'https://ca.indeed.com/viewjob?jk=' + credential})
    result = json.dumps(sanitize(value))
    assert credential not in result
    assert '[private credential]' in result


def test_url_filter_retains_fragment_structure_and_is_idempotent():
    from personal_jobby.privacy import sanitize_text
    public = 'https://job-boards.greenhouse.io/fixture/jobs/1000000001'
    raw = public + '?token=synthetic-token&gh_jid=1000000001#password=synthetic-password'
    expected = public + '?token=[private credential]&gh_jid=1000000001#password=[private credential]'
    assert sanitize_text(raw) == expected
    assert sanitize_text(expected) == expected


@pytest.mark.parametrize('public,fragment,expected_fragment', [
    ('https://example.com/confirmation',
     '/ghp_syntheticCredentialExample1234567890?view=summary',
     '/[private credential]?view=summary'),
    ('https://example.com/confirmation',
     'ghp_syntheticCredentialExample1234567890=summary',
     '[private credential]=summary'),
    ('https://example.com/confirmation',
     'view=summary&ghp_syntheticCredentialExample1234567890',
     'view=summary&[private credential]'),
    ('https://job-boards.greenhouse.io/fixture/jobs/1000000001?gh_jid=1000000001',
     '/ghp_syntheticCredentialExample1234567890?view=summary&gh_jid=1000000001&password=synthetic-password',
     '/[private credential]?view=summary&gh_jid=1000000001&password=[private credential]'),
])
def test_fragment_credentials_outside_values_are_filtered(public, fragment, expected_fragment):
    from personal_jobby.core import public_url
    from personal_jobby.privacy import sanitize, sanitize_text
    raw = public + '#' + fragment
    expected = public + '#' + expected_fragment
    assert public_url(raw) == raw
    assert sanitize_text(raw) == expected
    assert sanitize_text(expected) == expected
    record = {'confirmation': [raw]}
    filtered = {'confirmation': [expected]}
    assert sanitize(record) == filtered
    assert sanitize(filtered) == filtered
