"""Source-preserving lexical emphasis through selection and real document artifacts."""
import importlib.util
import json
from pathlib import Path

import fitz
import pytest
from docx import Document

from personal_jobby.core import select_facts
from personal_jobby.documents import lines, prepare
from personal_jobby.import_profile import extract, initialize
from personal_jobby.store import Store
from personal_jobby.store import private_write

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'role_emphasis_scenario', ROOT / 'scripts/run_synthetic_applications.py')
scenario = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenario)


@pytest.fixture(scope='module')
def fictional_source(tmp_path_factory):
    output = tmp_path_factory.mktemp('fictional-source')
    matrix = scenario.load_matrix()
    scenario.source_documents(output, matrix)
    return extract(output / 'fictional-source.pdf'), matrix


def test_ai_emphasis_prefers_rag_evals_to_mock_boilerplate(fictional_source):
    profile, matrix = fictional_source
    selection = select_facts(profile, matrix['roles'][0])
    ranked = selection['selected_fact_ids']
    assert ranked.index('experience-2') < ranked.index('experience-1')


def fact(fid, text, section='EXPERIENCE', group='Fictional role', date='', **extra):
    return dict(id=fid, text=text, section=section, group=group, date=date,
                source='fictional-source.pdf', excerpt=text, **extra)


@pytest.mark.parametrize('description', ['Unrelated xenobiology', 'Python'])
def test_equal_or_absent_overlap_keeps_source_order(description):
    profile = dict(facts=[fact('z-10', 'Python services.'), fact('a-2', 'Python clients.')])
    result = select_facts(profile, dict(title='Vacancy', description=description))
    assert result['selected_fact_ids'] == ['z-10', 'a-2']


@pytest.mark.parametrize(('term', 'other'), [
    ('C++', 'C'), ('C#', 'C++'), ('.NET', 'net'), ('CI/CD', 'CI and CD'),
])
def test_punctuation_sensitive_terms_match_exactly(term, other):
    profile = dict(facts=[fact('first', f'Used {other}.'), fact('second', f'Used {term}.')])
    result = select_facts(profile, dict(title='Vacancy', description=f'Required: {term}.'))
    assert result['selected_fact_ids'] == ['second', 'first']


def test_ai_project_emphasis_reaches_document_groups(fictional_source):
    profile, matrix = fictional_source
    ranked = select_facts(profile, matrix['roles'][0])['selected_fact_ids']
    lookup = {f['id']: f for f in profile['facts']}
    content = lines(profile, [lookup[fid] for fid in ranked])
    projects = [value[0] for kind, value in content
                if kind == 'heading' and value[0] in ('Sandbox Connector', 'Evaluation Notebook')]
    assert projects == ['Evaluation Notebook', 'Sandbox Connector']


def test_evidence_explains_lexical_emphasis_without_proving_qualifications(fictional_source):
    profile, matrix = fictional_source
    result = select_facts(profile, matrix['roles'][0])
    evidence = {e['fact_id']: e for e in result['evidence']}
    assert evidence['experience-2'].get('matched_terms') == ['evals', 'rag']
    assert evidence['experience-1']['matched_terms'] == ['python']
    assert evidence['experience-2']['lexical_score'] == 2
    assert evidence['experience-1']['lexical_score'] == 1
    assert evidence['experience-2']['classification'] == 'demonstrated'
    assert result['ranking']['tie_break'] == 'source order'
    assert 'not skill verification' in result['ranking']['scope']
    assert 'hiring probability' in result['ranking']['scope']


@pytest.fixture(scope='module')
def generated(tmp_path_factory, fictional_source):
    profile, matrix = fictional_source
    store = Store(tmp_path_factory.mktemp('generated'))
    initialize(store, profile['facts'][0]['source'])
    rows = {}
    for role in matrix['roles']:
        job = store.add(dict(title=role['title'], description=role['description'],
                             company='Fable Systems (FICTIONAL)', job_url=role['url']))
        meta = prepare(store, job['id'])
        rows[role['id']] = (store.artifact_dir(job['id']), meta, job['id'])
    return store, matrix, rows


def test_cover_has_concise_truthful_closing_in_both_formats(generated):
    _, _, rows = generated
    for folder, _, _ in rows.values():
        paragraphs = [p.text for p in Document(folder / 'cover_letter.docx').paragraphs]
        assert paragraphs[-3] == 'Thank you for considering my application.'
        with fitz.open(folder / 'cover_letter.pdf') as pdf:
            assert 'Thank you for considering my application.' in pdf[0].get_text()


def test_reviewed_equivalence_can_emphasize_a_complete_numeric_source_fact():
    original = 'Implemented retrieval-augmented generation across 12 documents with 3.5-second latency.'
    profile = dict(facts=[fact('first', 'Docker packaging.'), fact('second', original)])
    posting = dict(title='Vacancy', description='Required: RAG. PyTorch training and 10 years required.')
    result = select_facts(profile, posting)
    assert result['selected_fact_ids'] == ['second', 'first']
    supported = result['tailoring'][1]
    assert supported['original'] == original
    assert supported['rendered'] == 'Implemented RAG across 12 documents with 3.5-second latency.'
    assert supported['substitutions'] == [dict(
        before='retrieval-augmented generation', after='RAG',
        reason='Reviewed identical terminology: retrieval-augmented generation / RAG')]
    assert profile['facts'][1]['text'] == original
    assert 'PyTorch' not in supported['rendered'] and '10 years' not in supported['rendered']


def test_generic_posting_prose_cannot_outweigh_a_supported_role_term():
    boilerplate = ('Experience working in our team. This role offers an opportunity '
                   'for the right candidate at our company.')
    profile = dict(facts=[fact('first', boilerplate), fact('second', 'Implemented RAG retrieval.')])
    result = select_facts(profile, dict(title='Vacancy', description=(
        'Join our team. This role offers an opportunity for the right candidate '
        'with experience. Required: RAG.')))
    assert result['selected_fact_ids'] == ['second', 'first']
    assert result['evidence'][0]['matched_terms'] == []
    assert result['evidence'][0]['classification'] == 'adjacent'


def test_repeated_boilerplate_and_unknown_terms_do_not_change_emphasis(fictional_source):
    profile, matrix = fictional_source
    posting = matrix['roles'][0]
    original = select_facts(profile, posting)
    noisy = {**posting, 'description': posting['description'] + (
        ' FICTIONAL MOCK EMPLOYER ONLY. Required source qualifications for the candidate. '
        'Python RAG evals. Unobtainium flibbertigibbet.') * 30}
    result = select_facts(profile, noisy)
    assert result['selected_fact_ids'] == original['selected_fact_ids']
    assert result['evidence'] == original['evidence']
    assert result['tailoring'] == original['tailoring']


def normalized(text):
    return ' '.join(text.split())


@pytest.mark.parametrize('text', [
    'This is an openly disclosed AI-agent workflow test.',
    'The workflow reports only source-backed observations.',
    'Built Python services.',
    'I built Python services.',
    "I've inspected 12 public pages.",
    'We inspected public pages and report only observed outcomes.',
    'Inspected public pages; the workflow reports only observed outcomes.',
    'API checks retained 12 source excerpts.',
])
def test_cover_preserves_source_fact_person_tense_and_capitalization(tmp_path, text):
    store = Store(tmp_path)
    original = fact('experience', text)
    profile = dict(name='Fictional Fixture', contact='fixture@example.test',
                   facts=[original], answers={})
    private_write(store.root / 'candidate.json', json.dumps(profile))
    job = store.add(dict(title='Archivist', description='Xenobiology.',
                         company='Fictional Archive', job_url='https://archive.example.test/job'))
    meta = prepare(store, job['id'])
    folder = store.artifact_dir(job['id'])
    # A complete source fact is evidence, not a fragment to recast as "I ...".
    for name in ('resume', 'cover_letter'):
        paragraphs = [p.text for p in Document(folder / (name + '.docx')).paragraphs]
        assert '• ' + text in paragraphs
        with fitz.open(folder / (name + '.pdf')) as pdf:
            assert len(pdf) == 1
            assert normalized('• ' + text) in normalized(pdf[0].get_text())
    evidence = json.loads((folder / 'evidence.json').read_text())['evidence'][0]
    assert evidence['original_text'] == evidence['text'] == evidence['source_excerpt'] == text
    assert evidence['source'] == original['source']
    assert store.profile()['facts'] == [original]
    assert meta['qa_state'] == 'pending_visual_review'
    assert not store.get(job['id'])['attempts']


def test_real_formats_show_role_emphasis_and_preserve_all_fixture_facts(generated):
    store, matrix, rows = generated
    source = {f['id']: f for f in store.profile()['facts']}
    texts = {}
    for role in matrix['roles']:
        folder, meta, job_id = rows[role['id']]
        evidence = json.loads((folder / 'evidence.json').read_text())
        assert set(evidence['ranked_fact_ids']) == set(source)
        assert set(evidence['selected_fact_ids']) == set(source)
        assert len(evidence['evidence']) == len(source)
        for name in ('resume', 'cover_letter'):
            with fitz.open(folder / (name + '.pdf')) as pdf:
                assert len(pdf) == 1
                pdf_text = normalized(pdf[0].get_text())
            doc = Document(folder / (name + '.docx'))
            docx_text = normalized(' '.join(p.text for p in doc.paragraphs))
            assert pdf_text == docx_text
            assert doc.styles['Normal'].font.name == 'Times New Roman'
            assert doc.styles['Normal'].font.size.pt == 10
            section = doc.sections[0]
            assert all(m.inches == .75 for m in (
                section.top_margin, section.bottom_margin, section.left_margin, section.right_margin))
            for term in ('PyTorch', 'Kafka', 'Kubernetes', 'Rust', '10 years', 'team of 12'):
                assert term not in pdf_text
            if name == 'resume':
                texts[role['id']] = pdf_text
                for entry in evidence['evidence']:
                    original = source[entry['fact_id']]
                    assert entry['included']
                    assert entry['original_text'] == entry['text'] == original['text']
                    assert entry['source_excerpt'] == original['excerpt']
                    assert entry['source'] == original['source']
                    assert normalized(original['text']) in pdf_text
                assert pdf_text.index('Fable Systems (FICTIONAL)') < pdf_text.index('Paper Lantern Labs (FICTIONAL)')
        assert meta['qa_state'] == store.materials(job_id)['qa_state'] == 'pending_visual_review'
        assert meta['source_hashes'] == store.profile()['source_hashes']
        assert not store.get(job_id)['attempts']
    ai = texts['ai-engineer']
    backend = texts['backend-engineer']
    fde = texts['fde']
    rag = normalized(source['experience-2']['text'])
    services = normalized(source['experience-1']['text'])
    assert ai.index(rag) < ai.index(services)
    assert backend.index(services) < backend.index(rag)
    assert fde.index(services) < fde.index(rag)
    assert ai.index('Evaluation Notebook') < ai.index('Sandbox Connector')
    assert fde.index('Sandbox Connector') < fde.index('Evaluation Notebook')
    assert ai != backend and ai != fde


def test_employment_chronology_and_project_dates_links_stay_bound():
    facts = [
        fact('current-1', 'Docker packaging.', group='Current', date='2024 - Present'),
        fact('current-2', 'RAG evals.', group='Current', date='2024 - Present'),
        fact('prior', 'RAG evals Python.', group='Prior', date='2022 - 2023'),
        fact('connector', 'MCP server.', 'PROJECTS', 'Connector', '2021',
             link='https://github.com/example/fictional-connector'),
        fact('evaluation', 'RAG evals.', 'PROJECTS', 'Evaluation', '2020',
             link='https://github.com/example/fictional-evaluation'),
    ]
    profile = dict(name='Fictional Fixture', contact='', facts=facts)
    ranked = select_facts(profile, dict(title='Vacancy', description='RAG evals Python'))['selected_fact_ids']
    assert ranked[0] == 'prior'
    lookup = {f['id']: f for f in facts}
    content = lines(profile, [lookup[fid] for fid in ranked])
    assert [v for k, v in content if k == 'heading'] == [
        ('Current', '2024 - Present'), ('Prior', '2022 - 2023'),
        ('Evaluation', '2020'), ('Connector', '2021')]
    start = content.index(('section', 'EXPERIENCE')) + 1
    assert content[start:start + 3] == [
        ('heading', ('Current', '2024 - Present')), ('body', '• RAG evals.'), ('body', '• Docker packaging.')]
    start = content.index(('section', 'PROJECTS')) + 1
    assert content[start:] == [
        ('heading', ('Evaluation', '2020')), ('body', '• RAG evals.'),
        ('contact', [('GitHub', 'https://github.com/example/fictional-evaluation')]),
        ('heading', ('Connector', '2021')), ('body', '• MCP server.'),
        ('contact', [('GitHub', 'https://github.com/example/fictional-connector')])]


@pytest.mark.parametrize('description', ['Xenobiology', 'MCP'])
def test_project_group_ties_keep_source_order(description):
    facts = [fact('z', 'MCP fixture.', 'PROJECTS', 'First'),
             fact('a', 'MCP fixture.', 'PROJECTS', 'Second')]
    profile = dict(name='Fictional Fixture', contact='', facts=facts)
    ranked = select_facts(profile, dict(title='Vacancy', description=description))['selected_fact_ids']
    lookup = {f['id']: f for f in facts}
    assert [v for k, v in lines(profile, [lookup[fid] for fid in ranked]) if k == 'heading'] == [
        ('First', ''), ('Second', '')]


def test_no_overlap_retains_every_employment_role_under_page_pressure(tmp_path):
    store = Store(tmp_path)
    facts = [fact('education', 'Synthetic degree.', 'EDUCATION', 'Fictional Institute'),
             fact('skills', 'Python, Docker', 'TECHNICAL SKILLS', 'Tools')]
    for group, date in [('Newest', '2024 - Present'), ('Middle', '2022 - 2023'), ('Oldest', '2020 - 2021')]:
        for i in range(6):
            facts.append(fact(f'{group}-{i}', ('Documented sandbox releases with rollback notes, '
                'structured error logging and repeatable fixture tests. ') * 3, group=group, date=date))
    private_write(store.root / 'candidate.json', json.dumps(dict(
        name='Fictional Fixture', contact='fixture@example.test', facts=facts, answers={})))
    job = store.add(dict(title='Archivist', description='Xenobiology.',
                         company='Fictional Archive', job_url='https://archive.example.test/job'))
    meta = prepare(store, job['id'])
    chosen = meta['selected_fact_ids']
    assert {'education', 'skills', 'Newest-0', 'Middle-0', 'Oldest-0'} <= set(chosen)
    assert len(chosen) < len(facts)
    with fitz.open(store.artifact_dir(job['id']) / 'resume.pdf') as pdf:
        assert len(pdf) == 1
        text = normalized(pdf[0].get_text())
    assert text.index('Newest') < text.index('Middle') < text.index('Oldest')
    assert 'Synthetic degree.' in text and 'Python, Docker' in text
    ledger = json.loads((store.artifact_dir(job['id']) / 'evidence.json').read_text())
    assert set(ledger['ranked_fact_ids']) == {f['id'] for f in facts}
    for entry, original in zip(ledger['evidence'], facts):
        assert entry['fact_id'] == original['id']
        assert entry['original_text'] == original['text']
        assert entry['source_excerpt'] == original['excerpt']
        assert entry['included'] == (original['id'] in chosen)
        assert entry['lexical_score'] == 0 and entry['classification'] == 'adjacent'
    assert meta['qa_state'] == 'pending_visual_review'


def test_separate_dated_stints_in_same_role_are_each_mandatory(tmp_path):
    store = Store(tmp_path)
    group = 'Fictional Company | Engineer'
    facts = [fact(f'current-{i}', f'Built Python fixture component {i}.',
                  group=group, date='Jan 2024 - Present') for i in range(14)]
    facts.append(fact('prior', 'Documented sandbox releases.', group=group, date='Jan 2020 - Dec 2021'))
    private_write(store.root / 'candidate.json', json.dumps(dict(
        name='Fictional Fixture', contact='fixture@example.test', facts=facts, answers={})))
    job = store.add(dict(title='Python', description='Python.', company='Fictional Company',
                         job_url='https://stints.example.test/job'))
    meta = prepare(store, job['id'])
    assert {'current-0', 'prior'} <= set(meta['selected_fact_ids'])
    with fitz.open(store.artifact_dir(job['id']) / 'resume.pdf') as pdf:
        text = normalized(pdf[0].get_text())
    assert text.index('Jan 2024 - Present') < text.index('Jan 2020 - Dec 2021')
