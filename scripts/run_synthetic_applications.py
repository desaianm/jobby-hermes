#!/usr/bin/env python3
"""Fictional-only materials and loopback native form scenario. No import side effects."""
import argparse
import copy
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import selectors
import re
import signal
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
LEGACY_BASE = Path('/home/adcan288/tmp/jobby-role-tests-20261104')
# Additional task-owned root; the legacy output root remains accepted unchanged.
BASE = Path('/home/adcan288/tmp/jobby-question-benchmark-20261105')
NATIVE_BASE = Path('/home/adcan288/tmp/jobby-hackathon-20261106')
IDS = ['ai-engineer', 'backend-engineer', 'ml-platform-engineer', 'fde', 'senior-stretch']
HOST = 'https://applications.example.test'


def validate_case_id(case_id):
    if case_id not in IDS and not re.fullmatch(r'benchmark-(?:00[1-9]|0[1-9][0-9]|100)', case_id):
        raise ValueError('Invalid controlled fixture case ID')


def benchmark_matrix(manifest, count=100):
    from personal_jobby.greenhouse import verified_forms
    matrix = json.loads((REPO / 'tests/fixtures/benchmark-ai-agent.json').read_text())
    template = matrix.pop('role_template')
    roles = []
    for index, (form, data) in enumerate(verified_forms(manifest, count), 1):
        role = copy.deepcopy(template)
        case_id = f'benchmark-{index:03d}'
        validate_case_id(case_id)
        # Public descriptions are read-only untrusted evidence, never candidate truth or targets.
        # Benchmark identity is explicitly non-human; the five-role compatibility fixture is separate.
        role.update(id=case_id, url=HOST + '/jobs/' + case_id,
                    title=f'AI Engineer (FICTIONAL standard fixture {index:03d})',
                    source_input=dict(posting_key=form['posting_key'], board=form['board'], job_id=form['job_id'],
                        internal_job_id=form['internal_job_id'], title=form['title'], source=form['source'],
                        untrusted_read_only=True, qualifications='Unassessed; no public qualification claims imported'),
                    public_form_coverage=dict(mode='Maintained standard fixture; no public form replay',
                        replayed_public_fields=0, matched_groups=[],
                        held_groups=[dict(fingerprint=q['fingerprint'], kind=q['context']['kind'],
                            label=q['label'], reason='No fixture-approved production field mapping; held as read-only metadata')
                            for q in form['questions']], gaps=form['coverage']['gaps']))
        role['public_questions'] = form['questions']
        roles.append(role)
    matrix['roles'] = roles
    matrix['benchmark'] = dict(source_manifest=str(manifest), selected_distinct_postings=len(roles),
        controlled_fixture_cases=len(roles), public_form_replayed_fields=0,
        public_form_mapped_fields=0,
        note='One fictional standard fixture case per distinct public posting. Public questions all held. '
             'Controlled completion is independent of public-form answer coverage. No production form completion claim.')
    return matrix


def validate_url(url, matrix):
    if url not in [HOST + '/jobs/' + r['id'] for r in matrix['roles']]:
        raise ValueError('Only exact fictional fixture URLs are accepted')


def validate_matrix(matrix):
    if [r['id'] for r in matrix['roles']] != IDS:
        raise ValueError('Exactly five stable distinct role IDs required')
    if matrix['candidate']['name'] != 'Rowan Example — FICTIONAL TEST CANDIDATE':
        raise ValueError('Fictional identity required')
    for role in matrix['roles']:
        validate_url(role['url'], matrix)
        if not role['supported_fact_ids'] or not role['gaps']:
            raise ValueError('Explicit support and gaps required')
    return matrix


def load_matrix():
    return validate_matrix(json.loads((REPO / 'tests/fixtures/synthetic-role-matrix.json').read_text()))


def fresh_output(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or not any(root in path.parents for root in (BASE, LEGACY_BASE, NATIVE_BASE)):
        raise ValueError('Output must be a fresh absolute child of the owned temporary root')
    from personal_jobby import private_fs as fs
    fs.check(path)
    fd = fs.directory(path.parent)
    try:
        os.mkdir(path.name, 0o700, dir_fd=fd)  # Atomic refusal of existing outputs, including symlinks.
    finally:
        os.close(fd)
    return path


def source_documents(output, matrix):
    from personal_jobby.documents import pdf, docx, qa
    content = [('name', matrix['candidate']['name']),
               ('contact', [(matrix['candidate']['contact'], '')])]
    for section, rows in matrix['source_sections']:
        content.append(('section', section))
        content.extend(('body', row) for row in rows)
    pdf(output / 'fictional-source.pdf', content)
    docx(output / 'fictional-source.docx', content)
    qa(output / 'fictional-source.pdf', output / 'fictional-source.png')
    (output / 'source-fixture.json').write_text(json.dumps(matrix, indent=2))


class RegisteredTools:
    """Actual bundled registration handlers, recording context only (not installed loader)."""
    def __init__(self):
        self.tools = {}
        spec = importlib.util.spec_from_file_location('synthetic_jobby_plugin', REPO / '__init__.py',
                                                    submodule_search_locations=[str(REPO)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.register(self)

    def register_tool(self, **kwargs):
        self.tools[kwargs['name']] = kwargs['handler']

    def register_skill(self, *args, **kwargs):
        pass

    def call(self, action, **args):
        result = json.loads(self.tools['jobby_' + action](args))
        if not result.get('ok'):
            raise RuntimeError('Registered plugin action failed: ' + action)
        return result


class NativeTools:
    """Installed PluginManager discovery and the real scoped registry, without stand-ins."""
    def __init__(self, home):
        from hermes_constants import get_hermes_home
        from hermes_cli.plugins import PluginManager
        from tools.registry import registry
        if get_hermes_home() != home:
            raise ValueError('Native context home mismatch')
        self.manager = PluginManager()
        self.manager.discover_and_load()
        self.registry = registry
        self.loaded = [p for p in self.manager.list_plugins() if p['name'] == 'jobby']
        if (len(self.loaded) != 1 or not self.loaded[0]['enabled'] or self.loaded[0]['error']
                or self.loaded[0]['source'] != 'user' or self.loaded[0]['tools'] != 7):
            raise RuntimeError('Installed discovery failed: ' + json.dumps(self.loaded))
        for action in ('initialize', 'intake', 'overview', 'prepare', 'review', 'attempt', 'discover'):
            if registry.get_entry('jobby_' + action, scope=self.manager.scope_key) is None:
                raise RuntimeError('Installed tool missing: ' + action)

    def raw(self, action, args):
        value = self.registry.dispatch('jobby_' + action, args, scope=self.manager.scope_key)
        return json.loads(value) if isinstance(value, str) else value

    def call(self, action, **args):
        value = self.raw(action, args)
        if not value.get('ok'):
            raise RuntimeError('Native action failed: ' + action + ': ' + json.dumps(value))
        return value


def native_launch(args):
    """Copy the directory plugin, then cold-start the supplied installed engine runtime."""
    import shutil
    if not args.runtime_python or not args.hermes_source:
        raise ValueError('Native qualification requires --runtime-python and --hermes-source')
    for path in (args.runtime_python, args.hermes_source):
        if not path.is_absolute() or '..' in path.parts or not path.exists():
            raise ValueError('Runtime and SDK source must be existing absolute paths')
    if (args.hermes_source / 'hermes_cli/plugins.py').is_file() is False:
        raise ValueError('SDK source must contain hermes_cli/plugins.py')
    if args.source_manifest or args.controlled_agent_answers or not args.prepare_only:
        raise ValueError('Native qualification requires --prepare-only and no benchmark inputs')
    if NATIVE_BASE not in args.output.parents:
        raise ValueError('Native output must be inside the current owned evidence root')
    output = fresh_output(args.output)
    for name in ('user', 'tmp', 'empty-bundled', 'home-a', 'home-b'):
        (output / name).mkdir(mode=0o700)
    # A directory installation, not Git/catalog/PM installation. Copy only required public files.
    for profile in ('home-a', 'home-b'):
        installed = output / profile / 'plugins/jobby'
        installed.mkdir(parents=True, mode=0o700)
        for name in ('__init__.py', 'plugin.py', 'plugin.yaml', 'tool-schemas.json',
                     'skills/assisted-application/SKILL.md', 'scripts/run_synthetic_applications.py',
                     'tests/fixtures/synthetic-role-matrix.json'):
            target = installed / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / name, target)
    (output / 'native-child.pending').write_text('fictional-only installed qualification\n')
    child = output / 'home-a/plugins/jobby/scripts/run_synthetic_applications.py'
    env = dict(PATH=os.defpath, HOME=str(output / 'user'), HERMES_HOME=str(output / 'home-a'),
               TMPDIR=str(output / 'tmp'), PYTHONDONTWRITEBYTECODE='1', PYTHON_DOTENV_DISABLED='1',
               HERMES_BUNDLED_PLUGINS=str(output / 'empty-bundled'))
    command = [str(args.runtime_python), '-I', '-B', str(child), '--native-child', '--prepare-only',
               '--output', str(output), '--hermes-source', str(args.hermes_source)]
    (output / 'invocation.json').write_text(json.dumps(dict(command=command, environment=env), indent=2))
    with (output / 'native-stdout.json').open('w') as stdout, (output / 'native-stderr.log').open('w') as stderr:
        try:
            completed = subprocess.run(command, cwd=output, env=env, stdout=stdout, stderr=stderr, timeout=90)
        except subprocess.TimeoutExpired:
            return 1, dict(ok=False, blocker='Native child exceeded 90 seconds; inspect native-stderr.log', output=str(output))
    try:
        result = json.loads((output / 'native-stdout.json').read_text())
    except (ValueError, OSError):
        return 1, dict(ok=False, blocker='Native child did not return whole JSON; inspect native logs', output=str(output))
    if completed.returncode != 0 or not isinstance(result, dict) or result.get('ok') is not True:
        return completed.returncode or 1, dict(ok=False, child_exit=completed.returncode,
            blocker=result.get('blocker', 'Native runtime failed; inspect native logs') if isinstance(result, dict)
                    else 'Native child returned an invalid result object; inspect native logs', output=str(output))
    return completed.returncode, result


def native_child(args):
    """One bounded local journey, plus explicitly synthetic safety characterization."""
    output = args.output
    if not output.is_absolute() or '..' in output.parts or NATIVE_BASE not in output.parents:
        raise ValueError('Native child output is outside the owned evidence root')
    from personal_jobby import private_fs as fs
    fs.check(output)
    fs.read_text(output / 'native-child.pending')
    (output / 'native-child.pending').unlink()  # No replay into an existing desk.
    # -I excludes checkout/PYTHONPATH. Add SDK source only, never the engine checkout.
    sys.path.insert(0, str(args.hermes_source))
    import personal_jobby
    engine = Path(personal_jobby.__file__).resolve()
    if not engine.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError('Engine must be installed in the explicitly supplied runtime')
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_cli.config import config_command
    from personal_jobby.store import Store, now
    from argparse import Namespace
    report = dict(provenance='Fictional installed directory-plugin qualification. No browser, employer requests or receipts. '
                  'Guard-job approvals and uncertain events are synthetic, never human visual QA.',
                  installation='copied directory plugin; preinstalled engine runtime; no Git/catalog/PM install claim',
                  engine=str(engine), runtime=sys.executable, sdk_source=str(args.hermes_source),
                  checkpoints={}, dispatches=[], readbacks=[], post_count=0, receipts=0)
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    tools_by_home = []

    def check(label, condition):
        if not condition:
            raise RuntimeError('Native qualification assertion failed: ' + label)
        report['checkpoints'][label] = True

    def readback(label, selected, workspace):
        # Only the fixed read-only invocation returned by the native owner is admitted.
        handoff = selected['operator_handoff']
        check(label + '_binding', handoff['environment'] == {'JOBBY_ROOT': str(workspace)}
              and handoff['argv'] == [sys.executable, '-I', '-B', '-m', 'personal_jobby',
                                     'show', str(selected['job']['id'])]
              and handoff['purpose'] == 'snapshot_readback_only')
        env = dict(PATH=os.defpath, HOME=str(output / 'user'), TMPDIR=str(output / 'tmp'),
                   PYTHON_DOTENV_DISABLED='1', **handoff['environment'])
        completed = subprocess.run(handoff['argv'], cwd=output, env=env,
                                   capture_output=True, text=True, timeout=15)
        record = dict(label=label, exit_code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)
        report['readbacks'].append(record)
        check(label + '_exit', completed.returncode == 0)
        value = json.loads(completed.stdout)  # ENTIRE stdout, never a last-line fallback.
        check(label + '_agreement', value == {key: selected[key] for key in
              ('job', 'events', 'materials', 'current_artifact_directory')})
        record['result'] = value
        return value

    try:
        matrix = load_matrix()
        source_documents(output, matrix)
        for profile in ('home-a', 'home-b'):
            token = set_hermes_home_override(output / profile)
            try:
                # Exact `hermes config set` command handler; no launcher bootstrap/PM repair.
                config_command(Namespace(config_command='set', key='plugins.enabled', value='["jobby"]', force=False))
                tools_by_home.append(NativeTools(output / profile))
            finally:
                reset_hermes_home_override(token)
        tools, other = tools_by_home
        report['loaded'] = tools.loaded
        token = set_hermes_home_override(output / 'home-a')
        try:
            def call(action, **kwargs):
                value = tools.call(action, **kwargs)
                report['dispatches'].append(dict(action=action, result=value))
                return value
            def rejected(label, action, arguments):
                value = tools.raw(action, arguments)
                report['dispatches'].append(dict(action=action, synthetic_negative=label, result=value))
                check(label, value.get('ok') is False or bool(value.get('error')))
            empty = call('overview')
            check('empty_initialize_guidance', empty['jobs'] == [] and empty['next_action'] == 'initialize_resume')
            call('initialize', pdf_path=str(output / 'fictional-source.pdf'))
            check('imported_posting_guidance', call('overview')['next_action'] == 'intake_posting')
            role = matrix['roles'][0]
            posting = dict(title=role['title'], company='Fable Systems (FICTIONAL)', job_url=role['url'],
                           location='Berlin (FICTIONAL)', description=role['description'],
                           salary=dict(lower=50000.0, upper=60000.0, currency='EUR', verified=True))
            selected = call('intake', posting=posting, mode='direct')
            job_id = selected['job']['id']
            check('outside_discovery_policy', bool(selected['downstream_blockers']) and selected['mode'] == 'direct'
                  and selected['submission_available'] is False)
            check('duplicate_intake', call('intake', posting=posting, mode='direct')['job']['id'] == job_id
                  and len(call('overview')['jobs']) == 1)
            draft = call('prepare', job_id=job_id)
            store = Store(output / 'home-a/plugin-data/jobby/workspace')
            report['truth'] = verify_truth(store, job_id, role)
            readback('profile_a_draft', draft, store.root)
            check('pending_visual_review', draft['materials']['qa_state'] == 'pending_visual_review'
                  and draft['next_action'] == 'review_exact_generation' and draft['job']['attempts'] == [])
            rejected('wrong_id_type', 'prepare', {'job_id': True})
            rejected('unknown_job', 'overview', {'job_id': 99999})
            rejected('unknown_argument', 'overview', {'unexpected': 'synthetic'})
            rejected('malformed_arguments', 'overview', [])
            rejected('unknown_tool', 'not_a_tool', {})
            rejected('stale_review_token', 'review', dict(job_id=job_id, review_token='0'*64,
                     reviewer='Synthetic guard', note='No human QA'))
            second_token = set_hermes_home_override(output / 'home-b')
            try:
                b = other.call('overview')
                check('profile_b_empty', b['jobs'] == [] and b['source_status'] == 'not_initialized')
                b_selected = other.call('intake', posting={**posting, 'company': 'Distinct Fictional Profile B'}, mode='direct')
                b_selected = other.call('overview', job_id=b_selected['job']['id'])
                readback('profile_b_selected', b_selected, output / 'home-b/plugin-data/jobby/workspace')
                check('profile_b_distinct', b_selected['job']['id'] == job_id
                      and b_selected['job']['company'] != draft['job']['company']
                      and b_selected['materials'] is None)
                # Inspect the old binding without executing/reusing it after a scope switch.
                check('old_a_payload_not_repointed', draft['operator_handoff']['environment']
                      == {'JOBBY_ROOT': str(store.root)}
                      and draft['operator_handoff']['environment'] != b_selected['operator_handoff']['environment'])
            finally:
                reset_hermes_home_override(second_token)
            restored = call('overview', job_id=job_id)
            check('profile_a_restored', restored['materials'] == draft['materials']
                  and restored['operator_handoff'] == draft['operator_handoff'])
            readback('profile_a_restored', restored, store.root)
            # Separate guard job leaves the observable selected journey unapproved.
            guard_posting = {**posting, 'job_url': matrix['roles'][1]['url']}
            guard_id = call('intake', posting=guard_posting, mode='direct')['job']['id']
            guard = call('prepare', job_id=guard_id)
            old = guard['materials']
            regenerated = call('prepare', job_id=guard_id)
            rejected('obsolete_generation_token', 'review', dict(job_id=guard_id, review_token=old['review_token'],
                     reviewer='Synthetic guard', note='No human QA'))
            meta = regenerated['materials']
            folder = Path(regenerated['current_artifact_directory'])
            artifact = folder / 'resume.pdf'
            original = artifact.read_bytes()
            artifact.write_bytes(original + b'\nsynthetic corruption\n')
            rejected('changed_artifact', 'review', dict(job_id=guard_id, review_token=meta['review_token'],
                     reviewer='Synthetic guard', note='No human QA'))
            artifact.write_bytes(original)
            call('review', job_id=guard_id, review_token=meta['review_token'], reviewer='Synthetic guard only',
                 note='Simulated guard fixture review; NOT human visual QA')
            captured = call('attempt', job_id=guard_id, generation_id=meta['generation_id'],
                            review_token=meta['review_token'], application_url=guard_posting['job_url'],
                            resume=dict(filename='resume.pdf', sha256=meta['artifact_hashes']['resume.pdf']), cover_letter=None)
            attempt_id = captured['job']['attempts'][0]['id']
            with store.connect() as connection:
                connection.execute('INSERT INTO application_attempt_events(attempt_id,at,kind,data) VALUES(?,?,?,?)',
                                   (attempt_id, now(), 'uncertain', json.dumps(dict(reason='Synthetic hold; no browser action'))))
                store.event(connection, guard_id, 'synthetic_hold_fixture', dict(status='uncertain'))
            held = call('overview', job_id=guard_id)
            check('uncertain_hold', held['next_action'] == 'hold_existing_application')
            readback('uncertain_readback', held, store.root)
            before = store.get(guard_id), store.events(guard_id)
            rejected('uncertain_prepare_held', 'prepare', dict(job_id=guard_id))
            check('uncertain_hold_unchanged', (store.get(guard_id), store.events(guard_id)) == before)
            source = output / 'fictional-source.pdf'
            original_source = source.read_bytes()
            source.write_bytes(original_source + b'\nsynthetic source mutation\n')
            stale = call('overview', job_id=job_id)
            check('changed_source_stale', stale['materials']['qa_state'] == 'stale')
            readback('stale_readback', stale, store.root)
            rejected('changed_source_prepare', 'prepare', dict(job_id=job_id))
            source.write_bytes(original_source)
            final = call('prepare', job_id=job_id)
            check('final_pending_visual_review', final['materials']['qa_state'] == 'pending_visual_review'
                  and final['job']['attempts'] == [])
            report['truth'] = verify_truth(store, job_id, role)
            readback('final_current_generation', final, store.root)
            report['selected_job_id'] = job_id
            report['final'] = final
            check('no_receipts', all(not any(e['kind'] == 'receipt' for e in store.events(j['id'])) for j in store.jobs()))
        finally:
            reset_hermes_home_override(token)
    except Exception as error:
        report['blocker'] = type(error).__name__ + ': ' + str(error)
        return 1, dict(ok=False, report=str(output / 'report.json'), blocker=report['blocker'])
    finally:
        for tools in tools_by_home:
            tools.manager.unload()
        (output / 'report.json').write_text(json.dumps(report, indent=2))
    return 0, dict(ok=True, native_dispatch=True, browser_executed=False, report=str(output / 'report.json'))


def verify_truth(store, job_id, role):
    import fitz
    from docx import Document
    folder = store.artifact_dir(job_id)
    evidence = json.loads((folder / 'evidence.json').read_text())
    facts = {f['id']: f for f in store.profile()['facts']}
    included = {e['fact_id']: e for e in evidence['evidence'] if e['included']}
    texts = []
    for filename in ('resume.pdf', 'cover_letter.pdf'):
        with fitz.open(folder / filename) as document:
            texts.append(' '.join(p.get_text() for p in document))
    for filename in ('resume.docx', 'cover_letter.docx'):
        texts.append(' '.join(p.text for p in Document(folder / filename).paragraphs))
    normalized = [' '.join(t.split()) for t in texts]
    for fid, entry in included.items():
        if entry['original_text'] != facts[fid]['text'] or entry['source_excerpt'] != facts[fid]['excerpt']:
            raise ValueError('Generation evidence lost source provenance: ' + fid)
        expected = ' '.join(entry['text'].split())
        if not all(expected in text for text in (normalized[0], normalized[2])):
            raise ValueError('Included evidence missing from resume PDF/DOCX: ' + fid)
    for fid in role['supported_fact_ids']:
        if fid not in included or included[fid]['original_text'] != facts[fid]['text']:
            raise ValueError('Expected source fact missing from generation evidence: ' + fid)
        expected = ' '.join(included[fid]['text'].split())
        if not all(expected in text for text in (normalized[0], normalized[2])):
            raise ValueError('Expected fact missing from resume PDF/DOCX: ' + fid)
    for gap in role['gaps']:
        if any(gap['claim'].casefold() in text.casefold() for text in normalized):
            raise ValueError('Unsupported claim appeared in final documents')
    return dict(supported_fact_ids=role['supported_fact_ids'], gaps=role['gaps'],
                evidence=str(folder / 'evidence.json'), truth_checked=True)


def reserve_once(output, role_id, attempt_id):
    from personal_jobby import private_fs as fs
    validate_case_id(role_id)
    # Durable no-retry intent exists BEFORE the only browser click, including interruption.
    fs.create_bytes(output / (role_id + '.submit-intent.json'), json.dumps(dict(
        role_id=role_id, attempt_id=attempt_id, synthetic_only=True, retry_allowed=False)).encode())


def reconcile(store, row, event):
    from personal_jobby.audit import add_screenshot, record_receipt, historical_bytes
    from personal_jobby.store import now
    if (event.get('outcome') != 'confirmation_observed' or event.get('post_count') != 1
            or event.get('resume_sha256') != row['manifest']['resume']['sha256']
            or event.get('attempt_id') != row['attempt_id']
            or event.get('role_id') != row['id']
            or event.get('text') != 'synthetic test only — no real employer application'):
        raise ValueError('No verified synthetic acknowledgment')
    if 'controlled_answers' in row:
        expected = row['controlled_answers']['fields']
        if event.get('submitted_safe_fields') != expected or event.get('rendered_safe_fields') != expected:
            raise ValueError('No verified controlled answer receipt proof')
        row['public_form_coverage']['replayed_public_fields'] = len(expected)
        with store.connect() as connection:
            store.event(connection, row['job_id'], 'controlled_fixture_answer_receipt', dict(
                attempt_id=row['attempt_id'], submitted_safe_fields=event['submitted_safe_fields'],
                rendered_safe_fields=event['rendered_safe_fields'], multipart_sha256=event['multipart_sha256']))
    add_screenshot(store, row['attempt_id'], event['confirmation_screenshot'], 'employer_confirmation',
                   'Simulated fixture review; automated capture, not human acceptance', True)
    record_receipt(store, row['job_id'], event['text'], now(), row['url'], row['attempt_id'])
    payload, _ = historical_bytes(store, row['job_id'], row['attempt_id'], 'documents', 'resume.pdf')
    if hashlib.sha256(payload).hexdigest() != event['resume_sha256']:
        raise ValueError('Archive mismatch')
    row.update(outcome='mock_acknowledged', post_count=1, browser=event,
               archive_sha256=hashlib.sha256(payload).hexdigest())


def browser_role(output, row, store, node, playwright):
    from personal_jobby.audit import add_screenshot
    validate_case_id(row['id'])
    config = output / (row['id'] + '.browser-input.json')
    # No public employer URL, name, description or raw question enters the submit child.
    config.write_text(json.dumps({k: row[k] for k in ('id', 'url', 'attempt_id', 'manifest', 'identity', 'gaps',
        'resume_path', 'output_directory', 'controlled_answers') if k in row}))
    # Chrome's Unix socket paths must stay short even for deeply nested evidence outputs.
    # Exclusive 0700 ownership lasts until the child and its process group have ended.
    with tempfile.TemporaryDirectory(prefix='b-', dir=BASE) as browser_tmp, \
            (output / (row['id'] + '.browser-stderr.txt')).open('w') as errors:
        env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': browser_tmp,
               'JOBBY_PLAYWRIGHT_MODULE': playwright, 'TMPDIR': browser_tmp}
        process = subprocess.Popen([node, str(REPO / 'browser/synthetic-applications.mjs'), str(config)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                                   text=True, env=env, start_new_session=True)
        try:
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                if not selector.select(45):
                    raise TimeoutError('Browser fixture timeout; no retry')
                line = process.stdout.readline()
                if not line:
                    raise RuntimeError('Browser stopped; see preserved browser-stderr.txt')
                event = json.loads(line)
                if event['stage'] == 'filled':
                    add_screenshot(store, row['attempt_id'], event['screenshot'], 'filled_form',
                                   'Simulated fixture review; automated capture, not human acceptance', True)
                    reserve_once(output, row['id'], row['attempt_id'])
                    row['stages'].append('durable_no_retry_intent')
                    # A lost click response must remain unknown, never be reported as zero sends.
                    row['post_count'] = None
                    row['outcome'] = 'submit_permitted_outcome_uncertain'
                    process.stdin.write('submit-once\n')
                    process.stdin.flush()
                elif event['stage'] == 'result':
                    if process.wait(timeout=15) != 0:
                        raise RuntimeError('Browser failed after result')
                    reconcile(store, row, event)
                    row['stages'].extend(['native_multipart_post', 'mock_acknowledgment', 'audit_reconciled'])
                    return
                elif event['stage'] == 'transport_ready':
                    row['mock_transport'] = event['transport']
                elif event['stage'] == 'post_observed':
                    row['post_count'] = event['post_count']
                    row['stages'].append('native_post_observed')
                    row['outcome'] = 'post_observed_confirmation_pending'
        finally:
            selector.close()
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            # Also reap browser descendants if a timeout killed Node before its finally block.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.stdin.close()
            process.stdout.close()


def write_report(output, report):
    if 'benchmark' in report:
        report['benchmark']['public_form_replayed_fields'] = sum(
            r['public_form_coverage']['replayed_public_fields'] for r in report['roles'] if r['outcome'] == 'mock_acknowledged')
    if 'metrics' in report:
        report['metrics'].update(elapsed_seconds=round((datetime.now(timezone.utc) - datetime.fromisoformat(report['started_at'])).total_seconds(), 3),
            controlled_cases=len(report['roles']), mock_acknowledged=sum(r['outcome'] == 'mock_acknowledged' for r in report['roles']),
            observed_posts=sum(r['post_count'] or 0 for r in report['roles']),
            uncertain_post_counts=sum(r['post_count'] is None for r in report['roles']))
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    lines = ['# Synthetic applications', '', report['provenance'], '',
             'Source PDF: ' + str(output / 'fictional-source.pdf'),
             'Source DOCX: ' + str(output / 'fictional-source.docx'), '',
             '| Role ID | Stages | POSTs | Outcome | Generated documents | Gaps |',
             '| --- | --- | --- | --- | --- | --- |']
    for row in report['roles']:
        documents = ', '.join(f'[{name}]({path})' for name, path in row.get('generated_documents', {}).items())
        lines.append('| ' + ' | '.join([row['id'], ', '.join(row['stages']),
                     str(row['post_count']), row['outcome'], documents or 'none',
                     ', '.join(g['id'] for g in row['gaps'])]) + ' |')
    if report.get('blocker'):
        lines.extend(['', 'Blocker: ' + report['blocker']])
    (output / 'RESULTS.md').write_text('\n'.join(lines) + '\n')


def run(args):
    controlled = getattr(args, 'controlled_agent_answers', False)
    if controlled and not getattr(args, 'source_manifest', None):
        raise ValueError('Controlled agent answers require a public source manifest')
    matrix = (benchmark_matrix(args.source_manifest, args.case_limit)
              if getattr(args, 'source_manifest', None) else load_matrix())
    output = fresh_output(args.output)
    os.environ['JOBBY_ROOT'] = str(output / 'unused-cli-root')
    os.environ['HERMES_HOME'] = str(output / 'hermes-profile')
    sys.path.insert(0, str(args.hermes_source))
    from plugins.plugin_storage import plugin_data_dir
    from personal_jobby.store import Store
    from personal_jobby import private_fs as fs
    expected = output / 'hermes-profile/plugin-data/jobby'
    actual = plugin_data_dir('jobby')
    if actual != expected:
        raise ValueError('Hermes storage escaped synthetic profile')
    store = Store(actual / 'workspace')
    report = dict(provenance='Synthetic test only; fictional candidate and mock employers. '
                  'Recording registration context with actual Hermes plugin_data_dir; no installed-loader acceptance. '
                  'All QA is simulated fixture review, not human acceptance. No hiring probability or real submission authority. '
                  'Canonical reserved URLs map explicitly to an owned ephemeral loopback HTTP fixture; '
                  'this is not real employer origin or whole-browser OS egress acceptance.',
                  roles=[dict(id=r['id'], url=r['url'], gaps=r['gaps'], stages=[], post_count=0,
                              outcome='not_executed') for r in matrix['roles']])
    if 'benchmark' in matrix:
        report['benchmark'] = matrix['benchmark']
        for role, row in zip(matrix['roles'], report['roles']):
            row.update(source_input=role['source_input'], public_form_coverage=role['public_form_coverage'])
    report['started_at'] = datetime.now(timezone.utc).isoformat()
    report['metrics'] = dict(actual_model_calls=0, deterministic_answer_hits=0, source_http_requests_in_submit_child=0)
    cache = dict(schema_version=1, approvals=[])
    if controlled:
        report['metrics'].update(first_time_synthetic_approvals=0, existing_cache_hits=0, unknown_group_occurrences=0)
    write_report(output, report)
    try:
        source_documents(output, matrix)
        report['source_hashes'] = {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                                   for name in ('fictional-source.pdf', 'fictional-source.docx', 'source-fixture.json')}
        tools = RegisteredTools()
        tools.call('initialize', pdf_path=str(output / 'fictional-source.pdf'))
        store.save_answers(matrix['candidate']['answers'])
        if 'benchmark' in matrix:
            facts = store.profile()['facts']
            support = []
            for text in matrix['supported_source_texts']:
                matches = [f['id'] for f in facts if f['text'] == text]
                if len(matches) != 1:
                    raise ValueError('AI fixture support must resolve to exactly one imported fact')
                support.extend(matches)
            for role in matrix['roles']:
                role['supported_fact_ids'] = support[:]
        for role, row in zip(matrix['roles'], report['roles']):
            result = tools.call('intake', mode='direct', posting=dict(title=role['title'],
                company='Fable Systems (FICTIONAL)', requisition='FICTIONAL-' + role['id'],
                job_url=role['url'], location='Example City (fictional)', description=role['description']))
            job_id = result['job']['id']
            prepared = tools.call('prepare', job_id=job_id)
            meta = prepared['materials']
            row.update(verify_truth(store, job_id, role))
            if controlled:
                from personal_jobby.question_inventory import digest
                from personal_jobby.question_answers import controlled_fixture_batch
                # Use current native material bindings, authoritative imported profile and
                # fixture bytes/settings. Job differs per case; question context scopes it.
                material_scope = {k: meta['fingerprints'][k] for k in ('candidate', 'sources', 'settings')}
                scopes = dict(candidate_fingerprint=digest(dict(profile=store.profile(), settings=store.settings(),
                    identity=matrix['candidate'], materials=material_scope)),
                    source_fingerprint=digest(dict(source_hashes=report['source_hashes'], sources=material_scope['sources'])))
                answers = controlled_fixture_batch(role['public_questions'], cache, identity=matrix['candidate'], **scopes)
                fs.write_text(output / 'controlled-answer-cache.json', json.dumps(cache, indent=2))
                fs.write_text(output / (role['id'] + '.answers.json'), json.dumps(answers, indent=2))
                row['controlled_answers'] = dict(policy=answers['policy'], fields=answers['fields'], **scopes)
                row['answer_scope_materials'] = material_scope
                row['answer_metrics'] = answers['metrics']
                matched = {f['fingerprint'] for f in answers['fields']}
                coverage = row['public_form_coverage']
                coverage.update(mode='Controlled non-human fixture policy; first_name/last_name/email only',
                    mapped_public_fields=len(matched), replayed_public_fields=0, matched_groups=answers['fields'],
                    held_groups=[dict(fingerprint=q['fingerprint'], kind=q['context']['kind'], label=q['label'],
                        required=q['required'], status='needs_review', reason='Outside controlled safe mapping; no honest phone or automatic sensitive answers')
                        for q in role['public_questions'] if q['fingerprint'] not in matched])
                report['benchmark']['public_form_mapped_fields'] += len(matched)
                report['benchmark']['note'] = ('Limited safe public identity/contact mapping under controlled-nonhuman-fixture-v1. '
                    'Every other source group held. Controlled completion is independent of production-form completeness.')
                report['metrics']['deterministic_answer_hits'] += answers['metrics']['deterministic_hits']
                for key in ('first_time_synthetic_approvals', 'existing_cache_hits'):
                    report['metrics'][key] += answers['metrics'][key]
                report['metrics']['unknown_group_occurrences'] += len(coverage['held_groups'])
            tools.call('review', job_id=job_id, review_token=meta['review_token'],
                       reviewer='Synthetic automated fixture',
                       note='Simulated fixture review; PDF text/font/margins checked; DOCX content checked. Not human acceptance or visual approval.')
            manifest = dict(generation_id=meta['generation_id'], review_token=meta['review_token'],
                application_url=role['url'], resume=dict(filename='resume.pdf',
                sha256=meta['artifact_hashes']['resume.pdf']), cover_letter=None)
            result = tools.call('attempt', job_id=job_id, **manifest)
            attempt = result['job']['attempts'][-1]
            row.update(job_id=job_id, manifest=manifest, attempt_id=attempt['id'],
                artifact_directory=str(store.artifact_dir(job_id)),
                generated_documents={name: str(store.artifact_dir(job_id) / name) for name in
                    ('resume.pdf', 'resume.docx', 'cover_letter.pdf', 'cover_letter.docx')},
                resume_path=str(store.root / 'applications' / attempt['id'] / 'documents/resume.pdf'),
                output_directory=str(output), identity=matrix['candidate'],
                source_hashes=report['source_hashes'], artifact_hashes=meta['artifact_hashes'],
                stages=['source_imported', 'generated', 'truth_checked', 'simulated_fixture_review', 'attempt_captured'],
                outcome='prepared_browser_not_executed')
            if controlled:
                binding = dict(attempt_id=attempt['id'], controlled_answers=row['controlled_answers'],
                    generation_id=meta['generation_id'], resume_sha256=manifest['resume']['sha256'])
                fs.create_bytes(output / (role['id'] + '.controlled-answer-binding.json'), json.dumps(binding).encode())
                with store.connect() as connection:
                    store.event(connection, job_id, 'controlled_fixture_answer_binding', binding)
            write_report(output, report)
        write_report(output, report)
        if not args.prepare_only:
            for row in report['roles']:
                row['stages'].append('browser_launch_attempted')
                row['outcome'] = 'browser_incomplete'
                browser_role(output, row, store, args.node, args.playwright_module)
                write_report(output, report)
    except Exception as error:
        report['blocker'] = type(error).__name__ + ': ' + str(error)
        write_report(output, report)
        return 1, dict(ok=False, report=str(output / 'report.json'), blocker=report['blocker'])
    write_report(output, report)
    return 0, dict(ok=True, browser_executed=not args.prepare_only, report=str(output / 'report.json'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--hermes-source', type=Path, help='Hermes SDK checkout (required explicitly for native qualification)')
    parser.add_argument('--playwright-module', default=os.environ.get('JOBBY_PLAYWRIGHT_MODULE',
                        '/home/adcan288/hermes-secure-browser/control/node_modules/playwright-core/index.mjs'))
    parser.add_argument('--node', default='/home/adcan288/.local/bin/node')
    parser.add_argument('--prepare-only', action='store_true', help='Generate and audit documents; explicitly no browser results')
    parser.add_argument('--native-installed', action='store_true', help='Opt-in installed PluginManager/registry journey; requires --prepare-only')
    parser.add_argument('--runtime-python', type=Path, help='Explicit read/execute-only runtime with Jobby and Hermes SDK dependencies installed')
    parser.add_argument('--native-child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--source-manifest', type=Path, help='Hash-verified public collection manifest; maps distinct source IDs to fictional standard cases')
    parser.add_argument('--controlled-agent-answers', action='store_true',
        help='Explicit synthetic non-human fixture approval policy for exact first_name/last_name/email only; no human approval or real send authority')
    parser.add_argument('--case-limit', type=int, default=100, help='Benchmark count 1..100 (default 100); small smoke only in worker')
    args = parser.parse_args()
    if not args.native_child and not args.native_installed and args.hermes_source is None:
        args.hermes_source = Path('/home/adcan288/.hermes/hermes-agent')
    if not args.native_child:
        sys.path.insert(0, str(REPO))
    # Bootstrap/backend chatter is diagnostic; stdout is exactly one result document.
    try:
        with redirect_stdout(sys.stderr):
            code, result = native_child(args) if args.native_child else native_launch(args) if args.native_installed else run(args)
    except Exception as error:
        code, result = 1, dict(ok=False, blocker=type(error).__name__ + ': ' + str(error))
    print(json.dumps(result))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
