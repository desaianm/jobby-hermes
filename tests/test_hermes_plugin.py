"""Public dispatch seam; invented data and SDK boundary stand-ins only."""
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class Context:
    def __init__(self): self.tools = {}; self.skills = {}
    def register_tool(self, **kw): self.tools[kw['name']] = kw
    def register_skill(self, name, path, description=''): self.skills[name] = path

def load():
    spec = importlib.util.spec_from_file_location('jobby_plugin', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    ctx = Context()
    module.register(ctx)
    return ctx

def call(ctx, name, **args):
    return json.loads(ctx.tools[name]['handler'](args))

def test_registration_is_lazy(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBBY_ROOT', str(tmp_path / 'forbidden'))
    before = dict(os.environ)
    ctx = load()
    assert set(ctx.tools) == {'jobby_initialize', 'jobby_intake', 'jobby_overview', 'jobby_prepare', 'jobby_review', 'jobby_attempt', 'jobby_discover'}
    assert not list(tmp_path.iterdir())
    assert dict(os.environ) == before

import sys
import types
import pytest

@pytest.fixture
def desk(tmp_path, monkeypatch):
    active = [tmp_path / 'profile-a']
    sdk = types.ModuleType('plugins.plugin_storage')
    sdk.plugin_data_dir = lambda name: active[0] / 'plugin-data' / name
    monkeypatch.setitem(sys.modules, 'plugins.plugin_storage', sdk)
    monkeypatch.setenv('JOBBY_ROOT', str(tmp_path / 'forbidden'))
    return load(), active

POSTING = dict(title='Engineer', company='Synthetic Example', job_url='https://example.org/jobs/1',
               description='Build Python services', location='Berlin')

def test_intake_direct_is_selected_local_and_profile_scoped(desk):
    ctx, active = desk
    result = call(ctx, 'jobby_intake', posting=POSTING, mode='direct')
    assert result['ok'] and result['job']['id'] == 1
    assert result['next_action'] == 'initialize_resume'
    assert result['mode'] == 'direct' and result['submission_available'] is False
    assert call(ctx, 'jobby_intake', posting=POSTING, mode='direct')['job']['id'] == 1
    active[0] = active[0].parent / 'profile-b'
    assert call(ctx, 'jobby_overview')['jobs'] == []
    active[0] = active[0].parent / 'profile-a'
    assert len(call(ctx, 'jobby_overview')['jobs']) == 1
    assert not (active[0].parent / 'forbidden').exists()


def test_desk_list_loads_fresh_jobs_without_discarded_dossiers(desk):
    from contextlib import ExitStack
    from unittest.mock import patch
    from personal_jobby import cli_operations
    from personal_jobby.store import Store
    ctx, _ = desk
    assert call(ctx, 'jobby_intake', posting=POSTING, mode='direct')['ok']
    assert call(ctx, 'jobby_intake', posting={**POSTING, 'job_url': 'https://example.org/jobs/2'},
                mode='discovery')['ok']
    # Call through to real owners: list still validates each job and its materials.
    with ExitStack() as stack:
        spies = {name: stack.enter_context(patch.object(Store, name, autospec=True,
                                                       side_effect=getattr(Store, name)))
                 for name in ('jobs', 'get', 'materials', 'events')}
        show = stack.enter_context(patch.object(cli_operations, 'show', wraps=cli_operations.show))
        result = call(ctx, 'jobby_overview')
    assert result['ok'] and result['next_action'] == 'initialize_resume'
    assert [job['next_action'] for job in result['jobs']] == ['initialize_resume'] * 2
    assert {**{name: spy.call_count for name, spy in spies.items()}, 'show': show.call_count} == {
        'jobs': 1, 'get': 2, 'materials': 2, 'events': 0, 'show': 0}


def test_mutation_hold_loads_fresh_job_without_discarded_dossier(desk):
    from contextlib import ExitStack
    from unittest.mock import patch
    from personal_jobby import cli_operations
    from personal_jobby.store import Store
    ctx, active = desk
    assert call(ctx, 'jobby_intake', posting=POSTING, mode='direct')['ok']
    store = Store(active[0] / 'plugin-data/jobby/workspace')
    store.transition(1, 'archived')
    before = store.get(1), store.events(1)
    with ExitStack() as stack:
        spies = {name: stack.enter_context(patch.object(Store, name, autospec=True,
                                                       side_effect=getattr(Store, name)))
                 for name in ('get', 'materials', 'events')}
        show = stack.enter_context(patch.object(cli_operations, 'show', wraps=cli_operations.show))
        result = call(ctx, 'jobby_prepare', job_id=1)
    assert result['ok'] is False and result['error'] == 'jobby_operation_failed'
    assert (store.get(1), store.events(1)) == before
    assert {**{name: spy.call_count for name, spy in spies.items()}, 'show': show.call_count} == {
        'get': 1, 'materials': 1, 'events': 0, 'show': 0}


def test_real_materials_review_and_attempt(desk, tmp_path):
    from test_personal_jobby import updated_fixture
    from docx import Document
    import fitz
    ctx, _ = desk
    pdf = tmp_path / 'synthetic-source.pdf'
    updated_fixture(pdf)
    assert call(ctx, 'jobby_initialize', pdf_path=str(pdf))['ok']
    call(ctx, 'jobby_intake', posting=POSTING, mode='direct')
    draft = call(ctx, 'jobby_prepare', job_id=1)
    assert draft['next_action'] == 'review_exact_generation'
    folder = Path(draft['current_artifact_directory'])
    with fitz.open(folder / 'resume.pdf') as doc:
        assert 'Fixture Candidate' in doc[0].get_text()
    assert Document(folder / 'resume.docx').paragraphs
    meta = draft['materials']
    assert not call(ctx, 'jobby_review', job_id=1, review_token='0'*64, reviewer='Synthetic test', note='Simulated review')['ok']
    reviewed = call(ctx, 'jobby_review', job_id=1, review_token=meta['review_token'], reviewer='Synthetic test', note='Simulated fixture review, not real visual QA')
    assert reviewed['next_action'] == 'capture_attachment_manifest'
    manifest = dict(job_id=1, generation_id=meta['generation_id'], review_token=meta['review_token'], application_url=POSTING['job_url'], resume=dict(filename='resume.pdf', sha256=meta['artifact_hashes']['resume.pdf']), cover_letter=None)
    assert not call(ctx, 'jobby_attempt', **{**manifest, 'generation_id':'0'*32})['ok']
    attempt = call(ctx, 'jobby_attempt', **manifest)
    assert attempt['next_action'] == 'external_browser_pending'
    assert attempt['job']['attempts'][0]['operator'] == 'hermes'
    assert attempt['job']['status'] != 'applied'
    assert attempt['job']['attempts'][0]['status'] == 'draft'
    (folder / 'resume.pdf').write_bytes(b'changed synthetic bytes')
    assert not call(ctx, 'jobby_attempt', **manifest)['ok']

@pytest.mark.parametrize('name,args', [
    ('jobby_prepare', {'job_id':'../private-input'}),
    ('jobby_overview', {'extra':'private-input'}),
    ('jobby_initialize', {'pdf_path':'../private-input.pdf'}),
    ('jobby_intake', {'posting':{**POSTING, 'extra':'private-input'}, 'mode':'direct'}),
    ('jobby_prepare', {'job_id':True}),
])
def test_malformed_inputs_are_redacted(desk, name, args, capsys):
    ctx, _ = desk
    result = call(ctx, name, **args)
    assert result['ok'] is False
    assert 'private-input' not in json.dumps(result)
    assert capsys.readouterr().out == ''

def test_registered_schemas_bound_arguments():
    ctx = load()
    assert ctx.tools['jobby_intake']['schema']['parameters']['additionalProperties'] is False
    assert ctx.tools['jobby_attempt']['schema']['parameters']['required'] == ['job_id','generation_id','review_token','application_url','resume','cover_letter']

def test_sdk_failure_is_redacted(desk, monkeypatch, capsys):
    ctx, _ = desk
    def broken(name):
        print('private-sdk-input')
        raise RuntimeError('private-sdk-input')
    monkeypatch.setattr(sys.modules['plugins.plugin_storage'], 'plugin_data_dir', broken)
    result = call(ctx, 'jobby_overview')
    assert result['ok'] is False
    assert 'private-sdk-input' not in json.dumps(result) + capsys.readouterr().out

def test_registration_schema_matches_validators():
    ctx=load()
    from jobby_plugin.plugin import MODELS
    for name,model in MODELS.items():
        assert ctx.tools['jobby_'+name]['schema']['parameters'] == model.model_json_schema()

def test_direct_mode_does_not_change_discovery_policy(desk):
    ctx, _ = desk
    first=call(ctx,'jobby_intake',posting=POSTING,mode='direct')
    assert first['next_action']=='initialize_resume'
    assert first['downstream_blockers']
    other=call(ctx,'jobby_intake',posting={**POSTING,'job_url':'https://example.org/jobs/2'},mode='discovery')
    assert other['mode']=='discovery'
    assert call(ctx,'jobby_overview',job_id=1)['mode']=='direct'
    assert call(ctx,'jobby_overview',job_id=1)['job']['eligibility']!='eligible'


def test_operator_skill_is_registered():
    ctx=load()
    assert ctx.skills['assisted-application'].is_file()


@pytest.fixture
def reviewed_desk(desk, tmp_path):
    """Actual engine artifacts; all source/review claims are synthetic fixtures."""
    from test_personal_jobby import updated_fixture
    ctx, active = desk
    pdf = tmp_path / 'synthetic-source.pdf'
    updated_fixture(pdf)
    assert call(ctx, 'jobby_initialize', pdf_path=str(pdf))['ok']
    assert call(ctx, 'jobby_intake', posting=POSTING, mode='direct')['ok']
    return ctx, active


def prepare_review_fixture(ctx):
    draft = call(ctx, 'jobby_prepare', job_id=1)
    assert draft['ok']
    meta = draft['materials']
    reviewed = call(ctx, 'jobby_review', job_id=1,
                    review_token=meta['review_token'], reviewer='Synthetic fixture',
                    note='Simulated fixture review only; no real visual QA')
    assert reviewed['ok']
    return reviewed


def capture_fixture_attempt(ctx, meta):
    result = call(ctx, 'jobby_attempt', job_id=1,
                  generation_id=meta['generation_id'], review_token=meta['review_token'],
                  application_url=POSTING['job_url'],
                  resume=dict(filename='resume.pdf', sha256=meta['artifact_hashes']['resume.pdf']),
                  cover_letter=None)
    assert result['ok']
    return result


@pytest.mark.parametrize('state', ['stale', 'invalidated', 'generation_in_progress'])
def test_overviews_keep_real_material_freshness_checks(reviewed_desk, state):
    from personal_jobby import artifacts
    from personal_jobby.store import Store
    ctx, active = reviewed_desk
    reviewed = prepare_review_fixture(ctx)
    store = Store(active[0] / 'plugin-data/jobby/workspace')
    if state == 'stale':
        (Path(reviewed['current_artifact_directory']) / 'resume.pdf').write_bytes(b'changed synthetic document')
    elif state == 'invalidated':
        (artifacts.base(store, 1) / 'current.json').write_text('invalid synthetic JSON')
    else:
        artifacts.begin(store, 1)
    selected = call(ctx, 'jobby_overview', job_id=1)
    assert selected['ok'] and selected['materials']['qa_state'] == state
    assert selected['operator_handoff']['argv'][-2:] == ['show', '1']
    assert 'source or generation changes' in selected['operator_handoff']['refresh']
    assert selected['next_action'] == 'prepare_materials'
    assert call(ctx, 'jobby_overview')['jobs'][0]['next_action'] == 'prepare_materials'


@pytest.mark.parametrize('status,approval,expected', [
    ('filled_reviewed', {'review_token': 'b' * 64}, 'external_browser_pending'),
    ('confirmation_observed', {'review_token': 'b' * 64}, 'external_browser_pending'),
    ('draft', {'review_token': 'c' * 64}, 'capture_attachment_manifest'),
    ('draft', None, 'capture_attachment_manifest'),
    ('applied', None, 'hold_existing_application'),
])
def test_next_action_preserves_attempt_status_and_review_token_matching(desk, status, approval, expected):
    from jobby_plugin.plugin import _next_action
    job = dict(status='materials_ready',
               materials=dict(qa_state='visual_approved', generation_id='a' * 32, review_token='b' * 64),
               attempts=[dict(status=status, generation_id='a' * 32, approval=approval)])
    assert _next_action(job, True) == expected
    if status == 'applied':
        assert _next_action(job, False) == 'hold_existing_application'


def test_overview_requires_manifest_for_current_generation(reviewed_desk):
    ctx, active = reviewed_desk
    first = prepare_review_fixture(ctx)
    captured = capture_fixture_attempt(ctx, first['materials'])
    assert captured['next_action'] == 'external_browser_pending'
    old_attempt = captured['job']['attempts'][0]
    old_folder = active[0] / 'plugin-data/jobby/workspace/applications' / old_attempt['id']
    old_bytes = {p.relative_to(old_folder): p.read_bytes() for p in old_folder.rglob('*') if p.is_file()}
    second = prepare_review_fixture(ctx)
    assert second['materials']['generation_id'] != first['materials']['generation_id']
    assert second['job']['attempts'] == [old_attempt]
    observed = call(ctx, 'jobby_overview', job_id=1)
    assert call(ctx, 'jobby_overview', job_id=1) == observed
    assert observed['job'] == second['job']
    assert 'never repoint or reuse an old handoff' in observed['operator_handoff']['refresh']
    assert observed['operator_handoff']['purpose'] == 'snapshot_readback_only'
    assert observed['next_action'] == 'capture_attachment_manifest'
    assert second['next_action'] == 'capture_attachment_manifest'
    current = capture_fixture_attempt(ctx, second['materials'])
    assert current['next_action'] == 'external_browser_pending'
    assert len(current['job']['attempts']) == 2
    assert next(a for a in current['job']['attempts'] if a['id'] == old_attempt['id']) == old_attempt
    assert {p.relative_to(old_folder): p.read_bytes() for p in old_folder.rglob('*') if p.is_file()} == old_bytes
    new_attempt = next(a for a in current['job']['attempts'] if a['id'] != old_attempt['id'])
    assert new_attempt['generation_id'] == second['materials']['generation_id']


@pytest.mark.parametrize('hold', ['applied', 'submission_pending', 'submit_started', 'uncertain', 'archived', 'rejected', 'offer', 'interview'])
def test_overview_preserves_existing_application_holds(reviewed_desk, hold):
    from personal_jobby.store import Store, now
    ctx, active = reviewed_desk
    reviewed = prepare_review_fixture(ctx)
    captured = capture_fixture_attempt(ctx, reviewed['materials'])
    store = Store(active[0] / 'plugin-data/jobby/workspace')
    # Deliberate synthetic store state/events, never a fabricated employer receipt.
    with store.connect() as connection:
        if hold in ('submit_started', 'uncertain'):
            connection.execute('INSERT INTO application_attempt_events(attempt_id,at,kind,data) VALUES(?,?,?,?)',
                               (captured['job']['attempts'][0]['id'], now(), hold,
                                json.dumps({'reason': 'Synthetic hold fixture; no browser action'})))
        else:
            connection.execute('UPDATE jobs SET status=? WHERE id=1', (hold,))
        store.event(connection, 1, 'synthetic_hold_fixture', {'status': hold})
    before = store.get(1), store.events(1)
    for _ in range(2):
        result = call(ctx, 'jobby_overview', job_id=1)
        assert result['ok'] and result['next_action'] == 'hold_existing_application'
        assert result['operator_handoff']['argv'][-2:] == ['show', '1']
        assert 'never review, fill or submit authority' in result['operator_handoff']['authority']
        assert call(ctx, 'jobby_overview')['jobs'][0]['next_action'] == 'hold_existing_application'
        assert (store.get(1), store.events(1)) == before
    assert not call(ctx, 'jobby_prepare', job_id=1)['ok']
    assert (store.get(1), store.events(1)) == before


@pytest.mark.parametrize('nested', [
    {'qualifications_reviewed': 'false'},
    {'salary': {'verified': 'true'}},
])
def test_intake_rejects_coerced_nested_booleans(desk, nested):
    ctx, _ = desk
    assert call(ctx, 'jobby_intake', posting={**POSTING, **nested}, mode='direct')['ok'] is False
    assert call(ctx, 'jobby_overview')['jobs'] == []


def test_intake_accepts_typed_nested_booleans(desk):
    ctx, _ = desk
    result = call(ctx, 'jobby_intake', posting={**POSTING, 'qualifications_reviewed': False,
                  'salary': {'verified': True}}, mode='direct')
    assert result['ok']
    assert result['job']['qualifications_reviewed'] is False
    assert result['job']['salary']['verified'] is True


def test_empty_overview_guides_source_initialization_without_profile_answers(desk):
    ctx, _ = desk
    result = call(ctx, 'jobby_overview')
    assert result['ok'] and result['jobs'] == []
    assert result['source_status'] == 'not_initialized'
    assert result['next_action'] == 'initialize_resume'
    assert result['onboarding']['tool'] == 'jobby_initialize'
    assert 'absolute' in result['onboarding']['instruction']
    assert result['submission_available'] is False
    assert 'answers' not in result and 'profile' not in result


def test_initialized_empty_overview_guides_posting_intake_without_answers(desk, tmp_path):
    from test_personal_jobby import updated_fixture
    ctx, _ = desk
    source = tmp_path / 'fictional-onboarding.pdf'
    updated_fixture(source)
    assert call(ctx, 'jobby_initialize', pdf_path=str(source))['ok']
    result = call(ctx, 'jobby_overview')
    assert result['jobs'] == [] and result['source_status'] == 'imported'
    assert result['next_action'] == 'intake_posting'
    assert result['onboarding']['tool'] == 'jobby_intake'
    assert 'posting' in result['onboarding']['instruction']
    assert 'answers' not in result and 'profile' not in result


def test_overview_with_source_and_jobs_guides_selection_and_hides_answers(desk, tmp_path):
    from test_personal_jobby import updated_fixture
    from personal_jobby.store import Store
    ctx, active = desk
    source = tmp_path / 'fictional-selection.pdf'
    updated_fixture(source)
    call(ctx, 'jobby_initialize', pdf_path=str(source))
    call(ctx, 'jobby_intake', posting=POSTING, mode='direct')
    Store(active[0] / 'plugin-data/jobby/workspace').save_answers({'work_eligibility':'synthetic-private-answer'})
    result = call(ctx, 'jobby_overview')
    assert result['next_action'] == 'select_posting'
    assert result['onboarding']['tool'] == 'jobby_overview'
    assert result['jobs'][0]['next_action'] == 'prepare_materials'
    assert 'synthetic-private-answer' not in json.dumps(result)
    # Resolve the active SDK profile anew on every list and selected call.
    profile_a = active[0]
    active[0] = profile_a.parent / 'profile-b'
    assert call(ctx, 'jobby_intake', posting=POSTING, mode='discovery')['ok']
    for profile, action, mode, missing in (
        (profile_a, 'prepare_materials', 'direct', []),
        (active[0], 'initialize_resume', 'discovery', ['work_eligibility']),
        (profile_a, 'prepare_materials', 'direct', []),
    ):
        active[0] = profile
        assert call(ctx, 'jobby_overview')['jobs'][0]['next_action'] == action
        selected = call(ctx, 'jobby_overview', job_id=1)
        assert selected['next_action'] == action and selected['mode'] == mode
        assert selected['missing_answers'] == missing
        assert any(event['kind'] == 'assistance_selected' for event in selected['events'])

SEARCH_PREFS = dict(country='Canada', location='Ottawa, ON', remote=False,
                    hours_old=48, per_query=3, total=5, order='lexical')


@pytest.mark.parametrize('location', ['Berlin, Germany', 'Ottawa, ON 416-555-0199',
                                     'bearer synthetic-example-secret'], ids=['conflicting-country', 'phone', 'credential'])
def test_search_location_rejection_preserves_confirmation_and_blocks_tampering(desk, tmp_path, monkeypatch, location):
    from test_personal_jobby import updated_fixture
    from personal_jobby.store import Store
    import jobspy
    ctx, active = desk
    pdf = tmp_path / 'synthetic-source.pdf'
    updated_fixture(pdf)
    assert call(ctx, 'jobby_initialize', pdf_path=str(pdf))['ok']
    setup = call(ctx, 'jobby_discover', operation='inspect')
    body = dict(operation='confirm', source_token=setup['source_token'], queries=['Python'], preferences=SEARCH_PREFS)
    good = call(ctx, 'jobby_discover', **body)
    rejected = call(ctx, 'jobby_discover', **{**body, 'preferences': {**SEARCH_PREFS, 'location': location}})
    assert rejected['ok'] is False
    assert location not in json.dumps(rejected)
    assert call(ctx, 'jobby_discover', operation='inspect')['preferences'] == good['preferences']
    store = Store(active[0] / 'plugin-data/jobby/workspace')
    # Bypass normal save sanitation to model corrupted/on-disk untrusted setup.
    with store.connect() as connection:
        settings = json.loads(connection.execute('SELECT data FROM settings').fetchone()[0])
        settings['discovery']['preferences']['location'] = location
        connection.execute('UPDATE settings SET data=?', (json.dumps(settings),))
    calls = []
    monkeypatch.setattr(jobspy, 'scrape_jobs', lambda **kw: calls.append(kw))
    inspected = call(ctx, 'jobby_discover', operation='inspect')
    searched = call(ctx, 'jobby_discover', operation='search')
    assert inspected['confirmed'] is False and inspected['preferences'] is None
    assert searched['ok'] is False and calls == []
    assert location not in json.dumps([inspected, searched])


@pytest.mark.parametrize('location,canonical', [('Ottawa, ON', 'Ottawa, ON, Canada'),
    (' london, on, canada ', 'London, ON, Canada'), ('Canada', 'Canada'),
    ('Nunavut, Canada', 'NU, Canada')])
def test_search_location_is_canonical_for_both_providers(tmp_path, monkeypatch, location, canonical):
    import jobspy
    import pandas as pd
    from personal_jobby.search import SearchPreferences, discover
    from personal_jobby.store import Store
    assert SearchPreferences(**{**SEARCH_PREFS, 'location': location}).location == canonical
    calls = []
    monkeypatch.setattr(jobspy, 'scrape_jobs', lambda **kw: calls.append(kw) or pd.DataFrame())
    discover(Store(tmp_path), 'Python', 1, location=location)
    assert calls[0]['location'] == canonical
    assert calls[0]['site_name'] == ['indeed', 'linkedin']
    assert calls[0]['country_indeed'] == 'Canada'


def test_search_adapter_rejects_private_or_unsupported_location_before_provider(tmp_path, monkeypatch):
    import jobspy
    import pandas as pd
    from personal_jobby.search import discover
    from personal_jobby.store import Store
    calls = []
    monkeypatch.setattr(jobspy, 'scrape_jobs', lambda **kw: calls.append(kw) or pd.DataFrame())
    for location in ['Berlin, Germany', 'Ottawa, ON 416-555-0199', 'bearer synthetic-example-secret']:
        with pytest.raises(ValueError) as error:
            discover(Store(tmp_path), 'Python', 1, location=location)
        assert location not in str(error.value)
    assert calls == []


@pytest.mark.parametrize('role,bullets,skills,expected,excluded', [
    ('Accountant', ['Partnered with a Product Manager to improve invoicing.'], 'Tools: SQL',
     {'Accountant', 'SQL'}, {'Product Manager'}),
    ('Accountant', ['No experience with Python or Docker.', 'Have not used Kubernetes.',
                    'SQL was never used.'], 'Tools: PostgreSQL',
     {'Accountant', 'PostgreSQL'}, {'Python', 'Docker', 'Kubernetes', 'SQL'}),
    ('Software Engineer', ['Built retrieval-augmented generation (RAG) services in C++.',
                           'No experience with Python.', 'Built Python services.'], 'Tools: C#, .NET',
     {'Software Engineer', 'RAG', 'C++', 'C#', '.NET', 'Python'}, {'Product Manager'}),
], ids=['collaborator-role', 'negated-skills', 'positive-role-equivalents-and-separate-fact'])
def test_imported_discovery_queries_require_owned_role_and_affirmative_skill_evidence(
        desk, tmp_path, role, bullets, skills, expected, excluded):
    from reportlab.pdfgen import canvas
    from personal_jobby.store import Store
    ctx, active = desk
    pdf = tmp_path / 'synthetic-grounding.pdf'
    rows = ['Fixture Candidate', 'fixture@example.test', 'Experience', 'Fictional Co',
            'Ottawa', role, 'Apr 2026 - Present', *['• ' + b for b in bullets],
            'Selected Projects', 'Sample: Prepared reports.', 'Technical Skills', skills,
            'Education', 'Example University | Degree | Apr 2024']
    document = canvas.Canvas(str(pdf))
    for index, text in enumerate(rows): document.drawString(54, 780 - 18 * index, text)
    document.save()
    assert call(ctx, 'jobby_initialize', pdf_path=str(pdf))['ok']
    result = call(ctx, 'jobby_discover', operation='inspect')
    assert result['ok']
    terms = {p['term'] for p in result['proposals']}
    assert excluded.isdisjoint(terms)
    assert expected <= terms
    facts = {f['id']: f for f in Store(active[0] / 'plugin-data/jobby/workspace').profile()['facts']}
    for proposal in result['proposals']:
        for evidence in proposal['evidence']:
            fact = facts[evidence['fact_id']]
            assert evidence['excerpt'] == fact['excerpt'][:500]
            assert evidence['role'] == fact.get('role', '')
            if proposal['term'] == 'Python': assert fact['text'] == 'Built Python services.'
    for term in excluded:
        assert not call(ctx, 'jobby_discover', operation='confirm', source_token=result['source_token'],
                        queries=[term], preferences=SEARCH_PREFS)['ok']


@pytest.mark.parametrize('failure', ['body', 'exception', 'propagated-exception'])
def test_preimported_linkedin_diagnostics_are_private_and_logging_is_restored(desk, tmp_path, monkeypatch, failure):
    import io
    import logging
    import jobspy
    from jobspy.util import RequestsRotating, log_handler
    from test_personal_jobby import updated_fixture
    ctx, _ = desk
    pdf = tmp_path / 'synthetic-source.pdf'
    updated_fixture(pdf)
    assert call(ctx, 'jobby_initialize', pdf_path=str(pdf))['ok']
    setup = call(ctx, 'jobby_discover', operation='inspect')
    assert call(ctx, 'jobby_discover', operation='confirm', source_token=setup['source_token'],
                queries=['Python'], preferences=SEARCH_PREFS)['ok']
    marker = 'synthetic-raw-provider-response'
    captured = {name: io.StringIO() for name in ('provider', 'root', 'factory')}
    provider_log = logging.getLogger('jobspy')
    provider_handler = logging.StreamHandler(captured['provider'])
    root_handler = logging.StreamHandler(captured['root'])
    provider_log.addHandler(provider_handler)
    logging.root.addHandler(root_handler)
    monkeypatch.setattr(log_handler, 'stream', captured['factory'])
    handler_filters = tuple(log_handler.filters)
    root_filters = tuple(root_handler.filters)
    provider_handler_filters = tuple(provider_handler.filters)
    existing_filter = logging.Filter()
    provider_log.addFilter(existing_filter)
    unrelated = logging.getLogger('jobby-test-unrelated')
    unrelated_output = io.StringIO()
    unrelated_handler = logging.StreamHandler(unrelated_output)
    unrelated.addHandler(unrelated_handler)
    snapshots = {logger: (logger.level, tuple(logger.handlers), tuple(logger.filters), logger.propagate)
                 for logger in list(logging.root.manager.loggerDict.values())
                 if isinstance(logger, logging.Logger) and
                 (logger.name == 'jobspy' or logger.name.startswith('jobspy.') or logger.name.startswith('JobSpy:'))}
    # RequestsRotating.request is the real provider request boundary for both sites.
    # A missing stub would fail before any network is attempted.
    def request(self, method, url, **kwargs):
        unrelated.error('unrelated-positive-control')
        if failure == 'body' and 'indeed.com' in url:
            return types.SimpleNamespace(status_code=200, json=lambda: {'errors': [marker]})
        raise RuntimeError(marker)
    monkeypatch.setattr(RequestsRotating, 'request', request)
    if failure == 'propagated-exception':
        actual_factory = jobspy.scrape_jobs
        def provider(**options):
            actual_factory(**options)
            try: raise RuntimeError(marker)
            except RuntimeError:
                logging.getLogger('jobspy.linkedin').exception(marker)
                raise
        monkeypatch.setattr(jobspy, 'scrape_jobs', provider)
    try:
        result = call(ctx, 'jobby_discover', operation='search')
        assert result['ok']
        assert marker not in ''.join(out.getvalue() for out in captured.values()) + json.dumps(result)
        assert 'unrelated-positive-control' in unrelated_output.getvalue()
        assert 'unrelated-positive-control' in captured['root'].getvalue()
        assert result['last_run']['outcome'] == ('failed' if failure == 'propagated-exception' else 'empty')
        if failure == 'propagated-exception': assert result['last_run']['errors'][0]['code'] == 'source_failed'
        for logger, state in snapshots.items():
            assert (logger.level, tuple(logger.handlers), tuple(logger.filters), logger.propagate) == state
        assert tuple(log_handler.filters) == handler_filters
        assert tuple(root_handler.filters) == root_filters
        assert tuple(provider_handler.filters) == provider_handler_filters
        provider_log.error('restored-positive-control')
        assert 'restored-positive-control' in captured['provider'].getvalue()
    finally:
        provider_log.removeFilter(existing_filter)
        provider_log.removeHandler(provider_handler)
        logging.root.removeHandler(root_handler)
        unrelated.removeHandler(unrelated_handler)
        for logger, state in snapshots.items(): logger.setLevel(state[0])


def test_jobspy_factory_attaches_precreated_handler_inside_diagnostic_scope(tmp_path, monkeypatch):
    import io
    import logging
    from jobspy.util import RequestsRotating, log_handler
    from personal_jobby.search import discover
    from personal_jobby.store import Store
    marker = 'synthetic-factory-handler-private'
    captured = io.StringIO()
    provider = logging.getLogger('jobspy')
    original_filters = tuple(log_handler.filters)
    monkeypatch.setattr(logging.root, 'handlers', [])
    monkeypatch.setattr(provider, 'handlers', [])
    monkeypatch.setattr(log_handler, 'stream', captured)
    attached = []
    def request(self, method, url, **kwargs):
        attached.append(log_handler in provider.handlers)
        raise RuntimeError(marker)
    monkeypatch.setattr(RequestsRotating, 'request', request)
    result = discover(Store(tmp_path), 'Python', 1)
    assert result['jobs'] == [] and attached and all(attached)
    assert marker not in captured.getvalue()
    assert tuple(provider.handlers) == () and tuple(log_handler.filters) == original_filters


@pytest.mark.parametrize('mode', ['nested', 'overlapping'])
def test_provider_diagnostic_scope_survives_nested_and_overlapping_calls(tmp_path, monkeypatch, mode):
    import io
    import logging
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import jobspy
    import pandas as pd
    from jobspy.util import log_handler
    from personal_jobby.search import discover
    from personal_jobby.store import Store
    captured = io.StringIO()
    log = logging.getLogger('jobspy')
    handler = logging.StreamHandler(captured)
    log.addHandler(handler)
    legacy = logging.getLogger('JobSpy:LinkedIn')
    legacy_handler = logging.StreamHandler(captured)
    legacy.addHandler(legacy_handler)
    state = (log.level, tuple(log.handlers), tuple(log.filters), log.propagate, tuple(handler.filters), tuple(log_handler.filters))
    legacy_state = (legacy.level, tuple(legacy.handlers), tuple(legacy.filters), legacy.propagate)
    entered = threading.Event(); release = threading.Event(); second_started = threading.Event()
    store = Store(tmp_path / 'synthetic')
    def provider(**options):
        log.error('synthetic-private-before')
        legacy.error('synthetic-private-before')
        if options['search_term'] == 'Python':
            if mode == 'nested': discover(store, 'SQL', 1)
            else:
                entered.set()
                assert release.wait(5)
        log.error('synthetic-private-after')
        legacy.error('synthetic-private-after')
        return pd.DataFrame()
    monkeypatch.setattr(jobspy, 'scrape_jobs', provider)
    try:
        if mode == 'nested': discover(store, 'Python', 1)
        else:
            def second():
                second_started.set()
                return discover(store, 'SQL', 1)
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(discover, store, 'Python', 1)
                try:
                    assert entered.wait(5)
                    other = executor.submit(second)
                    assert second_started.wait(5)
                finally: release.set()
                first.result(timeout=5); other.result(timeout=5)
        assert 'synthetic-private' not in captured.getvalue()
        assert (log.level, tuple(log.handlers), tuple(log.filters), log.propagate, tuple(handler.filters), tuple(log_handler.filters)) == state
        assert (legacy.level, tuple(legacy.handlers), tuple(legacy.filters), legacy.propagate) == legacy_state
        log.error('restored-positive-control')
        assert 'restored-positive-control' in captured.getvalue()
    finally:
        log.removeHandler(handler)
        legacy.removeHandler(legacy_handler)


def test_resume_search_setup_requires_explicit_preferences_and_grounded_terms(desk, tmp_path):
    from test_personal_jobby import updated_fixture
    ctx, active = desk
    empty = call(ctx, 'jobby_discover', operation='inspect')
    assert empty['ok'] and empty['proposals'] == [] and empty['preferences'] is None
    assert 'source' in empty['warnings'][0].lower()
    pdf = tmp_path / 'synthetic-source.pdf'
    updated_fixture(pdf)
    assert call(ctx, 'jobby_initialize', pdf_path=str(pdf))['ok']
    setup = call(ctx, 'jobby_discover', operation='inspect')
    assert call(ctx, 'jobby_overview')['discovery']['tool'] == 'jobby_discover'
    terms = [p['term'] for p in setup['proposals']]
    assert 'AI Engineer' in terms and 'Python' in terms
    assert 'LLM' not in terms and 'Senior Engineer' not in terms
    assert all(p['evidence'][0]['fact_id'] and p['evidence'][0]['excerpt'] for p in setup['proposals'])
    assert setup['preferences'] is None and not setup['confirmed']
    assert not call(ctx, 'jobby_discover', operation='search')['ok']
    body = dict(operation='confirm', source_token=setup['source_token'], queries=['Python'], preferences=SEARCH_PREFS)
    confirmed = call(ctx, 'jobby_discover', **body)
    assert confirmed['ok'] and confirmed['confirmed'] and confirmed['queries'] == ['Python']
    assert confirmed['preferences'] == {**SEARCH_PREFS, 'location': 'Ottawa, ON, Canada'}
    assert call(ctx, 'jobby_discover', operation='inspect')['confirmed']
    assert not call(ctx, 'jobby_discover', **{**body, 'queries': ['Fixture Candidate']})['ok']
    for change in ({'country': 'Atlantis'}, {'location': ''}, {'remote': None}, {'hours_old': 0}, {'total': 26}, {'per_query': 11}):
        assert not call(ctx, 'jobby_discover', **{**body, 'preferences': {**SEARCH_PREFS, **change}})['ok']
    active[0] = active[0].parent / 'other-profile'
    assert call(ctx, 'jobby_discover', operation='inspect')['preferences'] is None
    active[0] = active[0].parent / 'profile-a'
    pdf.write_bytes(b'changed synthetic source')
    assert not call(ctx, 'jobby_discover', operation='inspect')['confirmed']
    assert not call(ctx, 'jobby_discover', operation='search')['ok']


def test_native_bounded_search_persists_explainable_shortlist_and_prepares(desk, tmp_path, monkeypatch):
    from test_personal_jobby import updated_fixture
    import pandas as pd
    import jobspy
    ctx, _ = desk
    pdf = tmp_path / 'synthetic-source.pdf'
    updated_fixture(pdf)
    call(ctx, 'jobby_initialize', pdf_path=str(pdf))
    setup = call(ctx, 'jobby_discover', operation='inspect')
    assert call(ctx, 'jobby_discover', operation='confirm', source_token=setup['source_token'],
                queries=['Python', 'AI Engineer'], preferences=SEARCH_PREFS)['ok']
    calls = []
    def provider(**options):
        calls.append(options)
        return pd.DataFrame([
            dict(title='Python Engineer', company='Fictional One', location='Ottawa',
                 job_url='https://jobs.example.test/python', description='Build Python FastAPI services',
                 job_url_direct='https://employer.example.test/jobs/42', date_posted='2026-11-06', id='in-42'),
            dict(title='Python Engineer', company='Fictional One', location='Ottawa',
                 job_url='https://employer.example.test/jobs/42', description='Duplicate listing', date_posted='2026-11-06'),
            dict(title='Registered Nurse', company='Fictional Hospital', location='Ottawa',
                 job_url='https://jobs.example.test/nurse', description='Clinical nursing licensure and bedside care', date_posted=None),
            dict(title='Must not ingest', company='Beyond bound', job_url='https://jobs.example.test/overflow', description='Python'),
        ])
    monkeypatch.setattr(jobspy, 'scrape_jobs', provider)
    found = call(ctx, 'jobby_discover', operation='search')
    assert found['ok'], found
    assert [c['results_wanted'] for c in calls] == [3, 2]
    assert all(c['country_indeed'] == 'Canada' and c['location'] == 'Ottawa, ON, Canada' and c['is_remote'] is False for c in calls)
    assert {c['search_term'] for c in calls} == {'Python', 'AI Engineer'}
    assert not any(value in json.dumps(calls) for value in ['Fixture Candidate', 'fixture@example.com', 'Current Co', '48.6'])
    assert len(found['shortlist']) == 2
    match, negative = found['shortlist']
    assert match['title'] == 'Python Engineer' and match['posted_date'] == '2026-11-06'
    assert 'python' in match['matching_terms'] and match['evidence'][0]['excerpt']
    assert negative['matching_terms'] == [] and negative['posted_date'] is None
    assert negative['unknowns'] and 'lexical' in found['ranking_method'].lower()
    assert all(j['status'] not in ('eligible', 'applied', 'submission_pending') for j in found['shortlist'])
    assert call(ctx, 'jobby_discover', operation='inspect')['shortlist'] == found['shortlist']
    assert len(call(ctx, 'jobby_overview')['jobs']) == 2
    again = call(ctx, 'jobby_discover', operation='search')
    assert [j['id'] for j in again['shortlist']] == [j['id'] for j in found['shortlist']]
    prepared = call(ctx, 'jobby_prepare', job_id=match['id'])
    assert prepared['ok'] and prepared['materials']['qa_state'] == 'pending_visual_review'
    assert prepared['job']['attempts'] == [] and not prepared['submission_available']


def test_search_partial_failures_dates_and_requisition_dedupe_are_truthful(desk, tmp_path, monkeypatch, capsys):
    from test_personal_jobby import updated_fixture
    import pandas as pd
    import jobspy
    ctx, _ = desk
    pdf = tmp_path / 'synthetic-source.pdf'
    updated_fixture(pdf)
    call(ctx, 'jobby_initialize', pdf_path=str(pdf))
    setup = call(ctx, 'jobby_discover', operation='inspect')
    prefs = {**SEARCH_PREFS, 'per_query': 10, 'total': 25, 'order': 'newest'}
    def confirm(order):
        return call(ctx, 'jobby_discover', operation='confirm', source_token=setup['source_token'],
                    queries=['Python', 'AI Engineer'], preferences={**prefs, 'order': order})
    assert confirm('newest')['ok']
    def provider(**options):
        if options['search_term'] == 'AI Engineer':
            raise RuntimeError('sensitive-provider-body-with-candidate-data')
        return pd.DataFrame([
            dict(title='Older Python', company='Fictional', requisition='42', job_url='https://jobs.example.test/old', description='Python', date_posted='2026-10-01'),
            dict(title='Duplicate requisition', company='Fictional', requisition='42', job_url='https://jobs.example.test/alias', description='Python', date_posted='2026-11-07'),
            dict(title='New Python', company='Fictional', job_url='https://jobs.example.test/new', description='Python FastAPI', date_posted='2026-11-06'),
            dict(title='Unknown Python', company='Fictional', job_url='https://jobs.example.test/unknown', description='Python', date_posted='bad date'),
            dict(title='Invalid URL', company='Fictional', job_url='file:///sensitive-provider-body', description='Python'),
        ])
    monkeypatch.setattr(jobspy, 'scrape_jobs', provider)
    found = call(ctx, 'jobby_discover', operation='search')
    assert found['ok'], found
    assert [j['title'] for j in found['shortlist']] == ['New Python', 'Older Python', 'Unknown Python']
    assert found['last_run']['outcome'] == 'partial'
    assert {e['code'] for e in found['last_run']['errors']} == {'source_failed', 'listing_invalid'}
    assert 'sensitive-provider-body' not in json.dumps(found) + capsys.readouterr().out
    assert call(ctx, 'jobby_discover', operation='inspect')['last_run'] == found['last_run']
    assert confirm('oldest')['ok']
    assert [j['title'] for j in call(ctx, 'jobby_discover', operation='inspect')['shortlist']] == ['Older Python', 'New Python', 'Unknown Python']
    monkeypatch.setitem(sys.modules, 'jobspy', None)
    missing = call(ctx, 'jobby_discover', operation='search')
    assert missing['ok'] and missing['last_run']['outcome'] == 'failed'
    assert all(e['code'] == 'dependency_missing' for e in missing['last_run']['errors'])
    monkeypatch.setitem(sys.modules, 'jobspy', types.SimpleNamespace(scrape_jobs=lambda **kw: pd.DataFrame()))
    empty = call(ctx, 'jobby_discover', operation='search')
    assert empty['ok'] and empty['last_run']['outcome'] == 'empty'
    assert len(empty['shortlist']) == 3

def test_real_scoped_registry_discovers_search_and_prepares(tmp_path):
    """Real Hermes loader/registry in an available owned runtime, checkout engine."""
    import subprocess
    import shutil
    sdk = Path(os.environ.get('JOBBY_HERMES_SOURCE', '/home/adcan288/.hermes/hermes-agent'))
    runtime = Path(os.environ.get('JOBBY_NATIVE_PYTHON', '/home/adcan288/tmp/jobby-hackathon-20261107/native-runtime/bin/python'))
    if not sdk.is_dir() or not runtime.is_file():
        pytest.skip('Owned full Hermes runtime and SDK source required')
    home = tmp_path / 'native-home'
    installed = home / 'plugins/jobby'
    installed.mkdir(parents=True)
    for name in ('__init__.py', 'plugin.py', 'plugin.yaml', 'tool-schemas.json', 'skills/assisted-application/SKILL.md'):
        path = installed / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, path)
    (home / 'config.yaml').write_text('plugins:\n  enabled:\n    - jobby\n')
    bundled = tmp_path / 'empty-bundled'
    bundled.mkdir()
    script = '''import sys, json
from pathlib import Path
from contextlib import redirect_stdout
with redirect_stdout(sys.stderr):
 sys.path[:0]=sys.argv[1:3]
 from scripts.run_synthetic_applications import NativeTools, source_documents, load_matrix
 root=Path(sys.argv[3]); home=root/'native-home'
 source_documents(root,load_matrix())
 native=NativeTools(home)
 selected=native.call('intake',posting=dict(title='Readback Engineer',company='Fictional Readback',job_url='https://jobs.example.test/readback',description='Python'),mode='direct')
 selected=native.call('overview',job_id=selected['job']['id'])
 handoff=selected['operator_handoff']
 assert handoff['argv']==[sys.executable,'-I','-B','-m','personal_jobby','show',str(selected['job']['id'])]
 assert handoff['environment']=={'JOBBY_ROOT':str(home/'plugin-data/jobby/workspace')}
 assert handoff['purpose']=='snapshot_readback_only'
 native.call('initialize',pdf_path=str(root/'fictional-source.pdf'))
 prepared=native.call('prepare',job_id=selected['job']['id'])
 import subprocess, os
 handoff=prepared['operator_handoff']
 child=subprocess.run(handoff['argv'],env=dict(PATH=os.defpath,HOME=str(root),TMPDIR=os.environ['TMPDIR'],PYTHON_DOTENV_DISABLED='1',**handoff['environment']),cwd=root,capture_output=True,text=True,timeout=15)
 assert child.returncode==0,child.stderr
 readback=json.loads(child.stdout)
 assert readback=={key:prepared[key] for key in ('job','events','materials','current_artifact_directory')}
 assert readback['materials']['qa_state']=='pending_visual_review'
 assert readback['materials']['generation_id'] and readback['materials']['artifact_hashes']
 assert readback['job']['attempts']==[]
 # Installed JobSpy supplies metadata; the provider boundary supplies a source-shaped frame without network.
 class Row(dict):
  @property
  def index(self): return self.keys()
 class Frame:
  def head(self,limit): return self
  def iterrows(self):
   yield 0,Row(title='Python Engineer',company='Fictional Native',location='Ottawa',job_url='https://jobs.example.test/native-discovery',description='Python FastAPI PostgreSQL services',date_posted='2026-11-06')
 import jobspy
 jobspy.scrape_jobs=lambda **kw:Frame()
 setup=native.call('discover',operation='inspect')
 native.call('discover',operation='confirm',source_token=setup['source_token'],queries=['Python'],preferences=json.loads(sys.argv[4]))
 found=native.call('discover',operation='search')
 assert found['shortlist'][0]['evidence']
 draft=native.call('prepare',job_id=found['shortlist'][0]['id'])
 assert draft['materials']['qa_state']=='pending_visual_review'
 assert draft['job']['attempts']==[]
 result=dict(installation='Copied directory plugin, checkout engine, real Hermes scoped registry; no fresh wheel/catalog/PM claim',shortlist=found['shortlist'],last_run=found['last_run'],qa_state=draft['materials']['qa_state'],generation_id=draft['materials']['generation_id'],submission_available=draft['submission_available'])
 (root/'native-discovery-result.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
'''
    env = {**os.environ, 'HERMES_HOME': str(home), 'HERMES_BUNDLED_PLUGINS': str(bundled),
           'HERMES_ENABLE_PROJECT_PLUGINS': '0', 'PYTHON_DOTENV_DISABLED': '1',
           'HOME': str(tmp_path), 'TMPDIR': str(tmp_path)}
    result = subprocess.run([str(runtime), '-I', '-B', '-c', script, str(ROOT), str(sdk), str(tmp_path), json.dumps(SEARCH_PREFS)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['qa_state'] == 'pending_visual_review'


def test_operator_readback_is_bound_to_each_profile_without_global_root_changes(desk):
    from personal_jobby import store as store_module
    ctx, active = desk
    original_env = dict(os.environ)
    original_default = store_module.ROOT
    profile_a = active[0]
    call(ctx, 'jobby_intake', posting=POSTING, mode='direct')
    a = call(ctx, 'jobby_overview', job_id=1)
    old = json.loads(json.dumps(a['operator_handoff']))
    active[0] = profile_a.parent / 'profile-b'
    other_posting = {**POSTING, 'company': 'Distinct Synthetic B', 'job_url': 'https://example.org/jobs/b'}
    call(ctx, 'jobby_intake', posting=other_posting, mode='direct')
    b = call(ctx, 'jobby_overview', job_id=1)
    assert b['job']['company'] == 'Distinct Synthetic B'
    assert b['operator_handoff']['environment'] == {'JOBBY_ROOT': str(active[0] / 'plugin-data/jobby/workspace')}
    assert old == a['operator_handoff']
    assert old['environment'] != b['operator_handoff']['environment']
    assert 'fresh native overview' in old['refresh']
    active[0] = profile_a
    assert call(ctx, 'jobby_overview', job_id=1)['operator_handoff'] == old
    assert 'operator_handoff' not in call(ctx, 'jobby_overview')
    assert dict(os.environ) == original_env and store_module.ROOT == original_default
    assert not Path(os.environ['JOBBY_ROOT']).exists()


def test_operator_readback_omits_private_answers_and_review_tokens(reviewed_desk):
    from personal_jobby.store import Store
    ctx, active = reviewed_desk
    store = Store(active[0] / 'plugin-data/jobby/workspace')
    store.save_answers({'work_eligibility': 'synthetic-private-legal-answer'})
    store.save_phone('+1 416 555 0199')
    selected = call(ctx, 'jobby_prepare', job_id=1)
    handoff = selected['operator_handoff']
    text = json.dumps(handoff)
    assert selected['materials']['review_token'] not in text
    assert 'synthetic-private-legal-answer' not in text and '416' not in text
    assert set(handoff['environment']) == {'JOBBY_ROOT'}
    assert handoff['argv'] == [sys.executable, '-I', '-B', '-m', 'personal_jobby', 'show', '1']
    assert 'command' not in handoff and 'answers' not in handoff
    for extra in ({'environment': {'JOBBY_ROOT': '/arbitrary'}}, {'argv': ['arbitrary']}):
        assert call(ctx, 'jobby_overview', job_id=1, **extra)['ok'] is False


@pytest.mark.parametrize('target', ['workspace', 'interpreter'])
def test_operator_readback_withholds_paths_requiring_privacy_filtration(desk, tmp_path, monkeypatch, target):
    ctx, active = desk
    if target == 'workspace':
        active[0] = active[0].parent / 'profile-4165550199'
    else:
        executable = tmp_path / 'token=synthetic-private-runtime'
        executable.touch()
        monkeypatch.setattr(sys, 'executable', str(executable))
    assert call(ctx, 'jobby_intake', posting=POSTING, mode='direct')['ok']
    selected = call(ctx, 'jobby_overview', job_id=1)
    assert selected['ok'] and selected['next_action'] == 'initialize_resume'
    assert 'operator_handoff' not in selected
    assert '4165550199' not in json.dumps(selected)
    assert 'synthetic-private-runtime' not in json.dumps(selected)


def test_operator_readback_preserves_exact_workspace_with_spaces_and_shell_metacharacters(desk):
    ctx, active = desk
    active[0] = active[0].parent / "profile space ' ; $(unused)"
    selected = call(ctx, 'jobby_intake', posting=POSTING, mode='direct')
    assert selected['operator_handoff']['environment'] == {'JOBBY_ROOT': str(active[0] / 'plugin-data/jobby/workspace')}
    assert isinstance(selected['operator_handoff']['argv'], list)


@pytest.mark.parametrize('country,location,code,qualified', [
    ('Germany', 'Berlin', 'DE', 'Berlin, Germany'),
    ('United States', 'New York, NY', 'US', 'New York, NY, USA'),
    ('United Kingdom', 'London', 'GB', 'London, UK'),
    ('India', 'मुंबई, Maharashtra', 'IN', 'मुंबई, Maharashtra, India'),
    ('Canada', 'Ottawa, ON', 'CA', 'Ottawa, ON, Canada'),
])
def test_international_adapter_reaches_real_jobspy_request_boundary(tmp_path, monkeypatch, country, location, code, qualified):
    from personal_jobby.search import discover
    from personal_jobby.store import Store
    from jobspy.util import RequestsRotating
    requests = []
    class Response:
        status_code = 200
        text = ""
        def json(self):
            return {"data": {"jobSearch": {"results": [], "pageInfo": {"nextCursor": None}}}}
    def request(session, method, url, **options):
        requests.append((method, url, {**options, "headers": dict(session.headers)}))
        return Response()
    monkeypatch.setattr(RequestsRotating, "request", request)
    # Real scrape_jobs/Indeed/LinkedIn run; only outgoing HTTP is stubbed.
    result = discover(Store(tmp_path), "Python", 1, country=country, location=location)
    assert result["jobs"] == []
    indeed = next(options for method, url, options in requests if "apis.indeed.com" in url)
    linkedin = next(options for method, url, options in requests if "linkedin.com" in url)
    assert indeed["headers"]["indeed-co"] == code
    assert qualified in indeed["json"]["query"]
    assert linkedin["params"]["location"] == qualified


@pytest.mark.parametrize('country,location', [
    ('Germany\n', 'Berlin'), ('Germany\t', 'Berlin'), ('Germany\x00', 'Berlin'),
    ('Atlantis', 'Example'), ('fixture@example.test', 'Berlin'),
    ('Germany', 'fixture@example.test'), ('Germany', '+49 30 12345678'),
    ('Germany', 'Berlin\nMitte'), ('Germany', 'Berlin\u200b'),
    ('Germany', 'https://example.test'), ('Germany', 'example.test'),
    ('Germany', 'token=synthetic-secret'), ('Germany', 'bearer synthetic-secret'),
    ('Germany', 'I built Python services'), ('Germany', 'Managed a team of developers'),
    ('Germany', 'Berlin, Canada'), ('Germany', 'A'*121),
    ('Germany', 'a b c d e f'), ('Germany', '1234567'),
    ('Germany', 123), (123, 'Berlin'),
])
def test_international_private_or_unsupported_inputs_never_reach_transport(tmp_path, monkeypatch, country, location):
    from personal_jobby.search import discover
    from personal_jobby.store import Store
    from jobspy.util import RequestsRotating
    requests = []
    monkeypatch.setattr(RequestsRotating, 'request', lambda *args, **kwargs: requests.append(True))
    with pytest.raises(ValueError):
        discover(Store(tmp_path), 'Python', 1, country=country, location=location)
    assert requests == []


def test_native_international_setup_persists_exact_choices_and_retires_with_source_or_profile(desk, tmp_path, monkeypatch):
    from test_personal_jobby import updated_fixture
    from jobspy.util import RequestsRotating
    ctx, active = desk
    pdf = tmp_path / 'synthetic-source.pdf'
    updated_fixture(pdf)
    call(ctx, 'jobby_initialize', pdf_path=str(pdf))
    current = call(ctx, 'jobby_discover', operation='inspect')
    assert {'USA', 'UK', 'Germany', 'India', 'Canada'} <= set(current['supported_countries'])
    requests = []
    class Response:
        status_code = 200
        text = ''
        def json(self):
            return {'data': {'jobSearch': {'results': [], 'pageInfo': {'nextCursor': None}}}}
    def request(session, method, url, **options):
        requests.append((dict(session.headers), options))
        return Response()
    monkeypatch.setattr(RequestsRotating, 'request', request)
    for country, location, code in [('USA', 'Boston, MA, USA', 'US'), ('UK', 'London, UK', 'GB'),
                                    ('Germany', 'München, Germany', 'DE'), ('India', 'Delhi, India', 'IN'),
                                    ('Canada', 'Ottawa, ON, Canada', 'CA')]:
        prefs = {**SEARCH_PREFS, 'country': country, 'location': location, 'total': 1, 'per_query': 1}
        confirmed = call(ctx, 'jobby_discover', operation='confirm', source_token=current['source_token'], queries=['Python'], preferences=prefs)
        assert confirmed['ok'] and confirmed['confirmed'] and confirmed['preferences'] == prefs
        assert call(load(), 'jobby_discover', operation='inspect')['preferences'] == prefs
        requests.clear()
        found = call(ctx, 'jobby_discover', operation='search')
        assert found['ok'] and found['last_run']['outcome'] == 'empty'
        assert any(headers.get('indeed-co') == code and location in options['json']['query'] for headers, options in requests if 'json' in options)
        assert any(options.get('params', {}).get('location') == location for headers, options in requests)
    active[0] = active[0].parent / 'profile-b'
    assert not call(ctx, 'jobby_discover', operation='inspect')['confirmed']
    active[0] = active[0].parent / 'profile-a'
    pdf.write_bytes(b'changed synthetic source')
    requests.clear()
    assert not call(ctx, 'jobby_discover', operation='inspect')['confirmed']
    assert not call(ctx, 'jobby_discover', operation='search')['ok']
    assert requests == []


def test_enum_country_without_selected_adapter_mapping_is_not_advertised_or_sent(desk, tmp_path, monkeypatch):
    from jobspy.indeed.constant import country_codes
    from jobspy.model import Country
    from jobspy.util import RequestsRotating
    from personal_jobby.search import discover
    from personal_jobby.store import Store
    monkeypatch.delitem(country_codes, Country.AUSTRALIA)
    ctx, _ = desk
    assert 'Australia' not in call(ctx, 'jobby_discover', operation='inspect')['supported_countries']
    requests = []
    monkeypatch.setattr(RequestsRotating, 'request', lambda *args, **kwargs: requests.append(True))
    with pytest.raises(ValueError): discover(Store(tmp_path), 'Python', 1, country='Australia', location='Sydney')
    assert requests == []
