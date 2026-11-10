"""Validated local workflow over the existing Jobby engine; no browser authority."""
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from personal_jobby.core import Job

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class Initialize(Input):
    pdf_path: str = Field(min_length=1, max_length=2000)
    replace: bool = False

class Intake(Input):
    posting: Job
    mode: Literal['direct', 'discovery']

class Overview(Input):
    job_id: int | None = Field(default=None, ge=1)

class Selected(Input):
    job_id: int = Field(ge=1)

from personal_jobby.search import SearchPreferences

class Discover(Input):
    operation: Literal['inspect', 'confirm', 'search']
    source_token: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')
    queries: list[str] | None = Field(default=None, min_length=1, max_length=3)
    preferences: SearchPreferences | None = None

class Review(Selected):
    review_token: str = Field(pattern='^[a-f0-9]{64}$')
    reviewer: str = Field(min_length=1, max_length=250)
    note: str = Field(min_length=1, max_length=2000)

class Attachment(Input):
    filename: Literal['resume.pdf', 'resume.docx', 'cover_letter.pdf', 'cover_letter.docx']
    sha256: str = Field(pattern='^[a-f0-9]{64}$')

class Attempt(Selected):
    generation_id: str = Field(pattern='^[a-f0-9]{32}$')
    review_token: str = Field(pattern='^[a-f0-9]{64}$')
    application_url: str = Field(min_length=1, max_length=2000)
    resume: Attachment
    cover_letter: Attachment | None

MODELS = dict(initialize=Initialize, intake=Intake, overview=Overview, discover=Discover,
              prepare=Selected, review=Review, attempt=Attempt)


def _next_action(job, source_present):
    meta = job['materials']
    locked = job['status'] in ('applied', 'submission_pending', 'archived', 'rejected', 'offer', 'interview') or any(a['status'] in ('submit_started', 'uncertain', 'applied') for a in job['attempts'])
    if locked:
        return 'hold_existing_application'
    if not source_present:
        return 'initialize_resume'
    if not meta or meta['qa_state'] in ('stale', 'invalidated', 'generation_in_progress'):
        return 'prepare_materials'
    if meta['qa_state'] != 'visual_approved':
        return 'review_exact_generation'
    if not any(a['status'] in ('draft', 'filled_reviewed', 'confirmation_observed')
               and a.get('generation_id') == meta['generation_id']
               and (a.get('approval') or {}).get('review_token') == meta['review_token']
               for a in job['attempts']):
        return 'capture_attachment_manifest'
    return 'external_browser_pending'


def desk_overview(store):
    imported = bool(store.profile()['facts'])
    jobs = [dict(id=j['id'], title=j['title'], company=j['company'], status=j['status'],
                 next_action=_next_action(j, imported)) for j in store.jobs()]
    action = 'initialize_resume' if not imported else 'select_posting' if jobs else 'intake_posting'
    guidance = {
        'initialize_resume': ('jobby_initialize', 'Provide an absolute path to your authoritative text PDF resume.'),
        'intake_posting': ('jobby_intake', 'Provide a captured posting and choose direct or discovery mode.'),
        'select_posting': ('jobby_overview', 'Choose a job ID from jobs to inspect its materials and exact next action.'),
    }
    tool, instruction = guidance[action]
    return dict(ok=True, jobs=jobs,
                discovery=dict(tool='jobby_discover', operation='inspect', instruction='Inspect source-backed proposals; confirm supported search preferences and up to three suggested queries once, then search. No application authority.'),
                source_status='imported' if imported else 'not_initialized',
                next_action=action, onboarding=dict(tool=tool, instruction=instruction),
                submission_available=False,
                scope='Selected posting materials only; external submission is not authorized')


def overview(store, job):
    from personal_jobby.cli_operations import show
    result = show(store, job['id'])
    modes = [json.loads(e['data'])['mode'] for e in store.events(job['id']) if e['kind'] == 'assistance_selected']
    mode = modes[-1] if modes else 'discovery'
    action = _next_action(job, bool(store.profile()['facts']))
    selected = dict(ok=True, **result, mode=mode, next_action=action, submission_available=False,
                scope='Selected posting materials only; external submission is not authorized',
                downstream_blockers=job['blockers'],
                missing_answers=['work_eligibility'] if not store.profile().get('answers', {}).get('work_eligibility') else [])
    # Native-only operator context. The HTTP desk curates its own allowlisted fields.
    import sys
    from pathlib import Path
    handoff = dict(
        purpose='snapshot_readback_only',
        environment={'JOBBY_ROOT': str(store.root)},
        argv=[sys.executable, '-I', '-B', '-m', 'personal_jobby', 'show', str(job['id'])],
        authority='Read-only snapshot/readback only; never review, fill or submit authority. No automation or daily lease.',
        refresh='Bound to this workspace snapshot. Fetch a fresh native overview after profile, source or generation changes; never repoint or reuse an old handoff.')
    # Filtering a path would produce a different executable target: withhold it.
    if (Path(sys.executable).is_absolute() and Path(sys.executable).is_file()
            and store.redact(handoff) == handoff):
        selected['operator_handoff'] = handoff
    return selected


def dispatch(action, args):
    # All failures, including SDK/dependency failures, pass through this boundary.
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            if not isinstance(args, dict) or len(json.dumps(args).encode()) > 150000:
                raise ValueError('Invalid bounded input')
            data = MODELS[action].model_validate(args, strict=True)
            from plugins.plugin_storage import plugin_data_dir
            from personal_jobby.store import Store
            store = Store(plugin_data_dir('jobby') / 'workspace')
            if action == 'discover':
                from personal_jobby import search
                if data.operation == 'inspect':
                    if data.model_fields_set != {'operation'}: raise ValueError('Inspect takes no options')
                    result = search.setup(store)
                elif data.operation == 'confirm':
                    if data.preferences is None: raise ValueError('Explicit preferences required')
                    result = search.confirm(store, data.source_token, data.queries, data.preferences.model_dump())
                else:
                    if data.model_fields_set != {'operation'}: raise ValueError('Search uses confirmed options only')
                    result = search.run(store)
            elif action == 'initialize':
                from pathlib import Path
                from personal_jobby.import_profile import initialize
                from personal_jobby import private_fs as fs
                path = Path(data.pdf_path)
                if not path.is_absolute() or '..' in path.parts or path.suffix.lower() != '.pdf': raise ValueError('Invalid source path')
                fs.read_bytes(path, max_bytes=8*1024*1024)
                result = dict(ok=True, **initialize(store, path, replace=data.replace))
            elif action == 'intake':
                job = store.add(data.posting.model_dump())
                with store.connect() as connection:
                    store.event(connection, job['id'], 'assistance_selected', dict(mode=data.mode, scope='materials_only'))
                result = overview(store, store.get(job['id']))
            elif action == 'overview':
                result = overview(store, store.get(data.job_id)) if data.job_id else desk_overview(store)
            else:
                job = store.get(data.job_id)
                if _next_action(job, bool(store.profile()['facts'])) == 'hold_existing_application': raise ValueError('Existing application hold')
                if action == 'prepare':
                    from personal_jobby.documents import prepare
                    prepare(store, data.job_id)
                elif action == 'review':
                    from personal_jobby.artifacts import approve
                    approve(store, data.job_id, data.review_token, dict(reviewer=data.reviewer, note=data.note))
                elif action == 'attempt':
                    from personal_jobby.audit import create_attempt
                    manifest = data.model_dump(exclude={'job_id'})
                    manifest['operator'] = 'hermes'
                    create_attempt(store, data.job_id, manifest)
                result = overview(store, store.get(data.job_id))
            return store.redact(result)
    except Exception:
        return dict(ok=False, error='jobby_operation_failed', message='Check input schema, source PDF, selected job and current generation. Local operation failed; no submission was performed.')


class ArtifactRead(Selected):
    generation_id: str = Field(pattern='^[a-f0-9]{32}$')
    review_token: str = Field(pattern='^[a-f0-9]{64}$')
    filename: Literal['resume.pdf', 'resume.docx', 'cover_letter.pdf', 'cover_letter.docx',
                      'preview.png', 'cover_preview.png', 'evidence.json']


def read_artifact(args):
    """Exact current-generation bytes only, including pending review documents."""
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            import base64
            import hashlib
            from plugins.plugin_storage import plugin_data_dir
            from personal_jobby.store import Store
            from personal_jobby import artifacts, private_fs as fs
            if not isinstance(args, dict) or len(json.dumps(args).encode()) > 16000:
                raise ValueError('Invalid bounded input')
            data = ArtifactRead.model_validate(args, strict=True)
            store = Store(plugin_data_dir('jobby') / 'workspace')
            with fs.lock(store.root / ('generation-' + str(data.job_id) + '.lock')):
                meta = artifacts.load(store, data.job_id)
                if (not meta or meta.get('qa_state') not in ('pending_visual_review', 'visual_approved')
                        or meta.get('generation_id') != data.generation_id
                        or meta.get('review_token') != data.review_token):
                    raise ValueError('Stale generation')
                raw = fs.read_bytes(artifacts.artifact_dir(store, data.job_id) / data.filename,
                                    max_bytes=8 * 1024 * 1024)
                if hashlib.sha256(raw).hexdigest() != meta['artifact_hashes'].get(data.filename):
                    raise ValueError('Artifact changed')
                if artifacts.load(store, data.job_id) != meta:
                    raise ValueError('Inputs changed')
                common = dict(ok=True, filename=data.filename, generation_id=data.generation_id,
                              review_token=data.review_token, sha256=meta['artifact_hashes'][data.filename])
                if data.filename == 'evidence.json':
                    return dict(**common, evidence=store.redact(json.loads(raw)))
                mime = 'image/png' if data.filename.endswith('.png') else 'application/pdf' if data.filename.endswith('.pdf') else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                return dict(**common, content_type=mime, base64=base64.b64encode(raw).decode('ascii'))
    except Exception:
        return dict(ok=False, error='jobby_artifact_unavailable', message='Current documents unavailable. Refresh the selected posting; regenerate if inputs or documents changed. No review was recorded.')
