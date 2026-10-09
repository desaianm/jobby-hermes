"""Native operations use only isolated, source-backed local fixtures."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from personal_jobby import __main__ as cli
from personal_jobby.documents import prepare
from personal_jobby.import_profile import initialize
from personal_jobby.store import Store
from test_personal_jobby import updated_fixture, verified_job, confirmed_settings


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    source = tmp_path / 'source.pdf'
    updated_fixture(source)
    store = Store(tmp_path / 'private')
    initialize(store, source)
    store.save_settings(confirmed_settings())
    job = verified_job()
    job['original_source'] = {'description': job['description']}
    store.add(job)
    monkeypatch.setattr(cli, 'Store', lambda: store)
    return store


def run(monkeypatch, capsys, *args, fails=False):
    monkeypatch.setattr(sys, 'argv', ['jobby', *map(str, args)])
    if fails:
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 1
        output = capsys.readouterr()
        assert not output.out
        assert 'input values withheld' in output.err
        return output.err
    cli.main()
    return json.loads(capsys.readouterr().out)


def evidence(tmp_path, value):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(value))
    return path


def test_profile_private_phone_omitted(workspace, monkeypatch, capsys):
    workspace.save_phone('+1 416 555 0199')
    workspace.save_answers({'work_eligibility': 'Canada'})
    result = run(monkeypatch, capsys, 'profile')
    assert result['phone_present']
    assert 'phone' not in result['profile']['answers']
    assert result['profile']['facts'] and result['profile']['source_hashes']
    assert result['profile']['answers']['work_eligibility'] == 'Canada'
    assert '416' not in json.dumps(result)


def test_show_current_and_stale(workspace, monkeypatch, capsys):
    assert run(monkeypatch, capsys, 'show', 1)['current_artifact_directory'] is None
    meta = prepare(workspace, 1)
    flat = workspace.root / 'artifacts' / '1' / 'metadata.json'
    flat.write_text('{"qa_state":"visual_approved"}')
    result = run(monkeypatch, capsys, 'show', 1)
    assert result['materials']['review_token'] == meta['review_token']
    assert result['current_artifact_directory'] == str(workspace.artifact_dir(1))
    assert '/generations/' in result['current_artifact_directory']
    assert result['events']
    settings = workspace.settings(); settings['minimum'] += 1; workspace.save_settings(settings)
    assert run(monkeypatch, capsys, 'show', 1)['materials']['qa_state'] == 'stale'


def test_fit_validation_and_terminal_preservation(workspace, tmp_path, monkeypatch, capsys):
    meta = prepare(workspace, 1)
    original = workspace.job_snapshot(1)['original_source']
    workspace.transition(1, 'archived')
    value = dict(arrangement='onsite', employment_type='contract', employment_evidence='Permanent full-time')
    path = evidence(tmp_path, {**value, 'unknown': 'secret-value'})
    assert 'secret-value' not in run(monkeypatch, capsys, 'fit', 1, '--evidence', path, fails=True)
    assert workspace.materials(1)['review_token'] == meta['review_token']
    path = evidence(tmp_path, value)
    result = run(monkeypatch, capsys, 'fit', 1, '--evidence', path)
    assert result['status'] == 'archived'
    assert result['original_source'] == original
    assert result['materials']['qa_state'] == 'stale'
    assert workspace.events(1)[-1]['kind'] == 'fit_verification'


def test_approval_exact_current_fixture(workspace, tmp_path, monkeypatch, capsys):
    old = prepare(workspace, 1)
    current = prepare(workspace, 1)
    path = evidence(tmp_path, dict(reviewer='Fixture operator', note='Reviewed actual fixture PDF, DOCX and preview', review_token=old['review_token']))
    run(monkeypatch, capsys, 'approve', 1, '--review', path, fails=True)
    value = json.loads(path.read_text()); value['review_token'] = current['review_token']; path.write_text(json.dumps(value))
    result = run(monkeypatch, capsys, 'approve', 1, '--review', path)
    assert result['qa_state'] == 'visual_approved'
    assert result['visual_approval']['reviewer'] == 'Fixture operator'


def test_private_inputs_bounded_no_symlinks(workspace, tmp_path, monkeypatch, capsys):
    target = evidence(tmp_path, {'arrangement': 'remote', 'employment_type': 'unknown'})
    link = tmp_path / 'link.json'; link.symlink_to(target)
    run(monkeypatch, capsys, 'fit', 1, '--evidence', link, fails=True)
    target.write_bytes(b' ' * 16001)
    run(monkeypatch, capsys, 'approve', 1, '--review', target, fails=True)
    run(monkeypatch, capsys, 'show', 999, fails=True)


def test_subprocess_no_http_or_app_start(tmp_path):
    root = tmp_path / 'private'
    script = '''import sys, socket
from personal_jobby.store import Store
import personal_jobby.__main__ as cli
from contextlib import redirect_stdout
with redirect_stdout(sys.stderr):
 import personal_jobby.app as app
app.create_app=lambda *a,**k: (_ for _ in ()).throw(AssertionError('app started'))
socket.socket=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network'))
store=Store(sys.argv[1])
cli.Store=lambda: store
sys.argv=['jobby','profile']
cli.main()
'''
    result = subprocess.run([sys.executable, '-c', script, str(root)], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['phone_present'] is False


def test_environment_overrides_keep_workspace_private_and_policy_disabled(tmp_path):
    import os
    root = tmp_path / 'private'
    script = '''import sys
from pathlib import Path
from fastapi.testclient import TestClient
from personal_jobby.store import Store
from personal_jobby.daily import Daily
from personal_jobby.app import create_app
store = Store()
assert store.root == Path(sys.argv[1])
daily = Daily(store)
assert daily.policy()['authorization_source'] == 'synthetic-policy-label'
assert daily.status()['executor_enabled'] is False
assert daily.status()['submission_active'] is False
with TestClient(create_app(), base_url='https://desk.example.test') as client:
 assert client.get('/').status_code == 200
 assert client.get('/', headers={'host': 'other.example.test'}).status_code == 400
 assert client.post('/api/jobs', json={}, headers={'origin': 'https://other.example.test'}).status_code == 403
daily.configure(enabled=False)
from personal_jobby import private_fs as fs
import json
policy = daily.policy()
policy['authorization_source'] = 'different-synthetic-label'
fs.write_text(daily.policy_path, json.dumps(policy))
try: daily.policy()
except ValueError: pass
else: raise AssertionError('Mismatched policy provenance must fail closed')
print('private defaults and exact host/provenance guards passed')
'''
    result = subprocess.run([sys.executable, '-c', script, str(root)],
                            capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, 'JOBBY_ROOT': str(root),
                                 'JOBBY_TRUSTED_HOST': 'desk.example.test',
                                 'JOBBY_AUTHORIZATION_SOURCE': 'synthetic-policy-label'})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith('private defaults and exact host/provenance guards passed')


def test_fit_requires_qualification_note_and_grounded_location(workspace, tmp_path, monkeypatch, capsys):
    job = verified_job()
    job.update(job_url='https://example.com/jobs/2', requisition='2')
    job['description'] += ' Required qualifications: Python.'
    workspace.add(job)
    value = dict(arrangement='hybrid', arrangement_evidence='Hybrid in Toronto',
                 employment_type='permanent_full_time', employment_evidence='Permanent full-time',
                 qualifications_reviewed=True)
    path = evidence(tmp_path, value)
    assert run(monkeypatch, capsys, 'fit', 2, '--evidence', path)['eligibility'] == 'needs_review'
    value['qualification_review_note'] = 'Reviewed required Python against source Technical Skills: Python, FastAPI, PostgreSQL.'
    path = evidence(tmp_path, value)
    assert run(monkeypatch, capsys, 'fit', 2, '--evidence', path)['eligibility'] == 'eligible'
    value['arrangement_evidence'] = 'Invented unsupported location'
    path = evidence(tmp_path, value)
    assert run(monkeypatch, capsys, 'fit', 2, '--evidence', path)['eligibility'] == 'needs_review'


@pytest.mark.parametrize('args', [
    ('init', '--pdf', 'private-input'), ('status', '--brief'),
    ('add', 'private-input'), ('search', 'private-input'), ('show', '5'),
    ('profile',), ('fit', '5', '--evidence', 'private-input'),
    ('approve', '5', '--review', 'private-input'), ('prepare', '5'),
    ('receipt', '5', '--timestamp', 'private-input'),
    ('attempt', '5', '--manifest', 'private-input'),
    ('screenshot', 'private-input', 'private.png', '--kind', 'filled_form',
     '--qa-note', 'private-input'), ('daily', 'status'),
])
def test_noisy_failure_shared_boundary(monkeypatch, capsys, args):
    def noisy_store():
        print('warning: private-input secret-token +1 416 555 0199')
        raise ValueError('private-input secret-token +1 416 555 0199')
    monkeypatch.setattr(cli, 'Store', noisy_store)
    error = run(monkeypatch, capsys, *args, fails=True)
    assert 'private-input' not in error
    assert 'secret-token' not in error
    assert '416' not in error
    assert 'ValueError' in error


@pytest.mark.parametrize('args', [('show', '1'), ('status', '--brief'), ('profile',)])
def test_noisy_operation_emits_one_sanitized_document(workspace, monkeypatch, capsys, args):
    workspace.save_phone('+1 416 555 0199')
    original = workspace.profile
    def noisy_profile():
        print('warning: The fitz API is deprecated; secret-token')
        return original()
    monkeypatch.setattr(workspace, 'profile', noisy_profile)
    original_redact = workspace.redact
    def noisy_redact(value):
        print('warning: private sanitizer output')
        return original_redact(value)
    monkeypatch.setattr(workspace, 'redact', noisy_redact)
    monkeypatch.setattr(sys, 'argv', ['jobby', *args])
    cli.main()
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert isinstance(result, dict)
    assert output.out == json.dumps(result, indent=2) + '\n'
    assert output.err == ''
    assert 'secret-token' not in output.out
    assert '+1 416 555 0199' not in output.out


def test_noisy_operation_exception_withholds_private_output(workspace, monkeypatch, capsys):
    from personal_jobby import cli_operations
    def noisy_show(store, job_id):
        print('warning: secret-token +1 416 555 0199')
        raise ValueError('secret-token +1 416 555 0199')
    monkeypatch.setattr(cli_operations, 'show', noisy_show)
    error = run(monkeypatch, capsys, 'show', 1, fails=True)
    assert 'secret-token' not in error
    assert '416' not in error


@pytest.mark.parametrize('args, code', [(('--help',), 0), (('show',), 2)])
def test_argparse_output_unchanged(monkeypatch, capsys, args, code):
    def unexpected_store():
        raise AssertionError('argument parsing must finish before backend operations')
    monkeypatch.setattr(cli, 'Store', unexpected_store)
    monkeypatch.setattr(sys, 'argv', ['jobby', *args])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == code
    output = capsys.readouterr()
    assert 'usage:' in (output.out if code == 0 else output.err)
    assert (output.err if code == 0 else output.out) == ''
