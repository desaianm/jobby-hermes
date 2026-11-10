"""Desktop HTTP seam using real engine/storage and the host's non-package loader."""
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
import os
SDK = Path(os.environ.get('JOBBY_HERMES_SOURCE', '/home/adcan288/.hermes/hermes-agent'))

@pytest.fixture
def desk_api(tmp_path, monkeypatch):
    if not SDK.is_dir():
        pytest.skip('Real Hermes source is required for desktop storage qualification')
    monkeypatch.syspath_prepend(str(SDK))
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'home-a'))
    monkeypatch.setenv('JOBBY_ROOT', str(tmp_path / 'forbidden'))
    spec = importlib.util.spec_from_file_location('hermes_dashboard_plugin_jobby', ROOT / 'dashboard/plugin_api.py')
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router, prefix='/api/plugins/jobby')
    def request(method, path, body=None):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                return await client.request(method, '/api/plugins/jobby' + path, **({'content': body} if isinstance(body, bytes) else {'json': body}))
        return asyncio.run(run())
    return request


def test_real_loader_import_selected_posting_and_generation(desk_api, tmp_path, monkeypatch):
    from scripts.run_synthetic_applications import load_matrix, source_documents
    request = desk_api
    assert request('GET', '/desk').json()['source_status'] == 'not_initialized'
    source_documents(tmp_path, load_matrix())
    result = request('POST', '/initialize', {'pdf_path': str(tmp_path / 'fictional-source.pdf')})
    assert result.json()['ok'], result.text
    posting = dict(company='Fictional Example', title='Engineer', url='https://jobs.example.test/one',
                   location='Berlin', description='Build Python services')
    assert request('POST', '/posting', posting).json()['job']['id'] == 1
    assert request('POST', '/posting', posting).json()['job']['id'] == 1
    draft = request('POST', '/prepare', {'job_id': 1}).json()
    assert draft['ok'] and draft['next_action'] == 'review_exact_generation'
    assert draft['materials']['qa_state'] == 'pending_visual_review'
    assert '"answers":' not in json.dumps(draft)
    assert 'events' not in draft and 'current_artifact_directory' not in draft
    assert 'operator_handoff' not in draft and 'JOBBY_ROOT' not in json.dumps(draft)
    token = {k: draft['materials'][k] for k in ('generation_id', 'review_token')}
    artifact = request('POST', '/artifact', dict(job_id=1, filename='resume.pdf', **token)).json()
    import base64
    assert base64.b64decode(artifact['base64']).startswith(b'%PDF-')
    assert request('GET', '/desk/1').json()['materials']['qa_state'] == 'pending_visual_review'
    assert request('POST', '/artifact', dict(job_id=1, filename='evidence.json', **token)).json()['evidence']['evidence']
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'home-b'))
    assert request('GET', '/desk').json()['jobs'] == []
    assert not request('POST', '/artifact', dict(job_id=1, filename='resume.pdf', **token)).json()['ok']
    assert not (tmp_path / 'forbidden').exists()


def test_posting_requires_readable_nonblank_identity(desk_api):
    posting = dict(company=' ', title='Engineer', url='https://jobs.example.test/one', location='', description='Python')
    assert desk_api('POST', '/posting', posting).json()['ok'] is False
    assert desk_api('GET', '/desk').json()['jobs'] == []

@pytest.mark.parametrize('path,value', [
    ('/initialize', {'pdf_path': '../sensitive-input.pdf'}),
    ('/initialize', {'pdf_path': '/sensitive-input.pdf', 'replace': 'yes'}),
    ('/initialize', {'pdf_path': '/sensitive-input.pdf', 'extra': True}),
    ('/posting', {'company': 'sensitive-input'}),
    ('/posting', {'company': 'Example', 'title': 'Engineer', 'url': 'file:///sensitive-input', 'location': '', 'description': 'Work'}),
    ('/prepare', {'job_id': True}),
    ('/prepare', {'job_id': '1'}),
    ('/prepare', {'job_id': 1, 'extra': 'sensitive-input'}),
    ('/prepare', {'job_id': -1}),
    ('/prepare', {'job_id': 999}),
    ('/prepare', {'job_id': 1, 'extra': 'sensitive-input' * 20000}),
    ('/artifact', {'job_id': 1, 'filename': '../../sensitive-input'}),
    ('/artifact', {'job_id': 1, 'filename': 'metadata.json', 'generation_id': 'a'*32, 'review_token': 'a'*64}),
])
def test_bounded_http_inputs_never_echo_private_values(desk_api, path, value, capsys):
    response = desk_api('POST', path, value)
    assert response.status_code == 200 and response.json()['ok'] is False
    assert 'sensitive-input' not in response.text + capsys.readouterr().out

@pytest.mark.parametrize('path', ['/submit', '/review', '/attempt', '/dispatch', '/artifact/resume.pdf'])
def test_desk_does_not_expose_general_tools_or_paths(desk_api, path):
    assert desk_api('POST', path, {}).status_code == 404


def test_exact_artifacts_reject_old_generation_source_changes_and_tampering(desk_api, tmp_path):
    from scripts.run_synthetic_applications import load_matrix, source_documents
    from plugins.plugin_storage import plugin_data_dir
    from personal_jobby.store import Store
    source_documents(tmp_path, load_matrix())
    source = tmp_path / 'fictional-source.pdf'
    assert desk_api('POST', '/initialize', {'pdf_path': str(source)}).json()['ok']
    posting = dict(company='Fictional Example', title='Engineer', url='https://jobs.example.test/two', location='', description='Python services')
    desk_api('POST', '/posting', posting)
    first = desk_api('POST', '/prepare', {'job_id': 1}).json()['materials']
    def binding(meta, name='resume.pdf'):
        return dict(job_id=1, filename=name, generation_id=meta['generation_id'], review_token=meta['review_token'])
    for filename in ('resume.pdf', 'cover_letter.pdf', 'resume.docx', 'cover_letter.docx', 'preview.png', 'cover_preview.png'):
        assert desk_api('POST', '/artifact', binding(first, filename)).json()['ok']
    second = desk_api('POST', '/prepare', {'job_id': 1}).json()['materials']
    assert not desk_api('POST', '/artifact', binding(first)).json()['ok']
    assert not desk_api('POST', '/artifact', {**binding(second), 'review_token': '0'*64}).json()['ok']
    store = Store(plugin_data_dir('jobby') / 'workspace')
    folder = store.artifact_dir(1)
    (folder / 'resume.pdf').write_bytes(b'changed synthetic attachment')
    assert not desk_api('POST', '/artifact', binding(second, 'cover_letter.pdf')).json()['ok']
    third = desk_api('POST', '/prepare', {'job_id': 1}).json()['materials']
    source.write_bytes(b'changed source')
    assert not desk_api('POST', '/artifact', binding(third)).json()['ok']
    assert desk_api('GET', '/desk/1').json()['materials']['qa_state'] == 'stale'
    assert not desk_api('POST', '/prepare', {'job_id': 1}).json()['ok']


def test_no_phone_legal_answers_or_event_notes_in_dossier(desk_api, tmp_path):
    from plugins.plugin_storage import plugin_data_dir
    from personal_jobby.store import Store
    store = Store(plugin_data_dir('jobby') / 'workspace')
    profile = store.profile()
    profile['answers'] = {'phone': '+1 416 555 0199', 'work_eligibility': 'sensitive-legal-answer'}
    store.save_answers({'work_eligibility': 'sensitive-legal-answer'})
    store.save_phone('+1 416 555 0199')
    result = desk_api('POST', '/posting', dict(company='Fictional Example', title='Engineer', url='https://jobs.example.test/privacy', location='', description='Python')).json()
    assert 'sensitive-legal-answer' not in json.dumps(result)
    assert '416' not in json.dumps(result)
    assert 'events' not in result and 'answers' not in result
    native = sys.modules['hermes_dashboard_plugin_jobby'].adapter().dispatch('overview', {'job_id': 1})
    assert native['operator_handoff']['environment'] == {'JOBBY_ROOT': str(store.root)}
    for response in (result, desk_api('GET', '/desk/1').json(), desk_api('GET', '/desk').json()):
        payload = json.dumps(response)
        assert 'operator_handoff' not in response and 'JOBBY_ROOT' not in payload
        assert str(store.root) not in payload and sys.executable not in payload


def test_backend_failure_is_recoverable_and_silent(desk_api, monkeypatch, capsys):
    from plugins import plugin_storage
    def unavailable(name):
        print('sensitive-runtime-path')
        raise RuntimeError('sensitive-runtime-path')
    with monkeypatch.context() as patch:
        patch.setattr(plugin_storage, 'plugin_data_dir', unavailable)
        result = desk_api('GET', '/desk').json()
        assert result['ok'] is False
        assert 'sensitive-runtime-path' not in json.dumps(result) + capsys.readouterr().out
    assert desk_api('GET', '/desk').json()['ok']


def test_context_local_profile_switch_uses_real_sdk(desk_api, tmp_path):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    a = set_hermes_home_override(tmp_path / 'context-a')
    try:
        desk_api('POST', '/posting', dict(company='Fictional Example', title='Engineer', url='https://jobs.example.test/context', location='', description='Python'))
        b = set_hermes_home_override(tmp_path / 'context-b')
        try:
            assert desk_api('GET', '/desk').json()['jobs'] == []
        finally:
            reset_hermes_home_override(b)
        assert len(desk_api('GET', '/desk').json()['jobs']) == 1
    finally:
        reset_hermes_home_override(a)


def test_existing_application_hold_and_unknown_answer_guidance_are_preserved(desk_api):
    from plugins.plugin_storage import plugin_data_dir
    from personal_jobby.store import Store
    result = desk_api('POST', '/posting', dict(company='Fictional Example', title='Engineer', url='https://jobs.example.test/hold', location='', description='Python')).json()
    assert result['missing_answers'] == ['work_eligibility']
    assert result['downstream_blockers']
    store = Store(plugin_data_dir('jobby') / 'workspace')
    # Synthetic external application state, never an employer request.
    with store.connect() as connection:
        connection.execute('UPDATE jobs SET status=? WHERE id=?', ('submission_pending', 1))
    assert desk_api('GET', '/desk/1').json()['next_action'] == 'hold_existing_application'
    assert not desk_api('POST', '/prepare', {'job_id': 1}).json()['ok']


def test_binary_reader_refuses_symlink_and_bounded_request(desk_api, tmp_path):
    from scripts.run_synthetic_applications import source_documents, load_matrix
    from plugins.plugin_storage import plugin_data_dir
    from personal_jobby.store import Store
    source_documents(tmp_path, load_matrix())
    desk_api('POST', '/initialize', {'pdf_path': str(tmp_path / 'fictional-source.pdf')})
    desk_api('POST', '/posting', dict(company='Fictional Example', title='Engineer', url='https://jobs.example.test/symlink', location='', description='Python'))
    meta = desk_api('POST', '/prepare', {'job_id': 1}).json()['materials']
    folder = Store(plugin_data_dir('jobby') / 'workspace').artifact_dir(1)
    pdf = folder / 'resume.pdf'
    pdf.unlink()
    pdf.symlink_to(tmp_path / 'fictional-source.pdf')
    binding = dict(job_id=1, filename='resume.pdf', generation_id=meta['generation_id'], review_token=meta['review_token'])
    assert not desk_api('POST', '/artifact', binding).json()['ok']
    assert not desk_api('POST', '/artifact', {**binding, 'extra': 'x'*16000}).json()['ok']

@pytest.mark.parametrize('raw', [b'{"job_id":', b'[]', b'null', b'{"secret":"sensitive-input"}', b'x'*150001])
def test_malformed_and_oversized_json_is_sanitized(desk_api, raw, capsys):
    response = desk_api('POST', '/prepare', raw)
    assert response.json()['ok'] is False
    assert 'sensitive-input' not in response.text + capsys.readouterr().out


def test_http_resume_discovery_shortlist_prepare_and_profile_isolation(desk_api, tmp_path, monkeypatch):
    from scripts.run_synthetic_applications import source_documents, load_matrix
    import pandas as pd
    import jobspy
    request = desk_api
    source_documents(tmp_path, load_matrix())
    assert request('POST', '/initialize', {'pdf_path': str(tmp_path / 'fictional-source.pdf')}).json()['ok']
    setup = request('GET', '/discovery').json()
    assert setup['ok'] and setup['proposals'] and not setup['confirmed']
    assert 'source' not in setup['proposals'][0]['evidence'][0]
    term = setup['proposals'][0]['term']
    prefs = dict(country='Canada', location='Ottawa, ON', remote=True, hours_old=72, per_query=2, total=2, order='lexical')
    assert request('POST', '/discovery', dict(operation='confirm', source_token=setup['source_token'], queries=[term], preferences=prefs)).json()['confirmed']
    monkeypatch.setattr(jobspy, 'scrape_jobs', lambda **kw: pd.DataFrame([
        dict(title='Python Engineer', company='Fictional Discovery', location='Ottawa', job_url='https://jobs.example.test/desk-search', description='Build Python FastAPI services', date_posted='2026-11-06')]))
    found = request('POST', '/discovery', dict(operation='search')).json()
    assert found['ok'] and found['shortlist'][0]['evidence']
    assert found['last_run']['outcome'] == 'completed'
    assert not any(k in found for k in ('answers', 'events', 'current_artifact_directory'))
    job_id = found['shortlist'][0]['id']
    assert request('GET', f'/desk/{job_id}').json()['next_action'] == 'prepare_materials'
    draft = request('POST', '/prepare', dict(job_id=job_id)).json()
    assert draft['materials']['qa_state'] == 'pending_visual_review'
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'home-b'))
    other = request('GET', '/discovery').json()
    assert other['shortlist'] == [] and other['preferences'] is None and not other['confirmed']
