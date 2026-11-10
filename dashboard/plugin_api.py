"""Bounded local desk API. Host mounts this as a non-package module."""
import importlib.util
import json
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter()
FAILURE = dict(ok=False, error='jobby_operation_failed', message='Local operation unavailable. Check the backend enable switch, source PDF, posting and current generation, then refresh. No submission was performed.')


def adapter():
    # The host loads this file without package context. Load the one owning
    # adapter by its bundled path; never alter sys.path or duplicate dispatch.
    spec = importlib.util.spec_from_file_location('_jobby_desk_adapter', Path(__file__).resolve().parents[1] / 'plugin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def public_desk(result):
    if not result.get('ok'):
        return FAILURE
    keys = ('ok', 'jobs', 'source_status', 'next_action', 'submission_available', 'scope',
            'downstream_blockers', 'missing_answers', 'proposals', 'source_token', 'confirmed',
            'preferences', 'queries', 'supported_countries', 'warnings', 'shortlist',
            'ranking_method', 'last_run')
    data = {k: result[k] for k in keys if k in result}
    if 'job' in result:
        data['job'] = {k: result['job'][k] for k in ('id', 'company', 'title', 'job_url', 'location', 'description', 'status', 'explanation')}
        meta = result.get('materials')
        data['materials'] = {k: meta[k] for k in ('generation_id', 'review_token', 'qa_state', 'created', 'artifact_hashes', 'docx_qa') if k in meta} if meta else None
    return data


async def body(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 150000:
            raise ValueError('Request too large')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Object required')
    return value


def run(action, value):
    try:
        return public_desk(adapter().dispatch(action, value))
    except Exception:
        return FAILURE


@router.get('/desk')
async def desk():
    return run('overview', {})


@router.get('/discovery')
async def discovery():
    return run('discover', dict(operation='inspect'))


@router.post('/discovery')
async def discover(request: Request):
    try:
        return run('discover', await body(request))
    except Exception:
        return FAILURE


@router.get('/desk/{job_id}')
async def selected(job_id: str):
    try:
        if not job_id.isascii() or not job_id.isdecimal() or len(job_id) > 12:
            raise ValueError('Invalid ID')
        return run('overview', dict(job_id=int(job_id)))
    except Exception:
        return FAILURE


@router.post('/initialize')
async def initialize(request: Request):
    try:
        result = adapter().dispatch('initialize', await body(request))
        return run('overview', {}) if result.get('ok') else FAILURE
    except Exception:
        return FAILURE


@router.post('/posting')
async def posting(request: Request):
    try:
        value = await body(request)
        if set(value) != {'company', 'title', 'url', 'location', 'description'}:
            raise ValueError('Posting fields required')
        if any(not isinstance(value[k], str) or not value[k].strip() for k in ('company', 'title', 'url', 'description')):
            raise ValueError('Readable posting required')
        value['job_url'] = value.pop('url')
        return run('intake', dict(posting=value, mode='direct'))
    except Exception:
        return FAILURE


@router.post('/prepare')
async def prepare(request: Request):
    try:
        return run('prepare', await body(request))
    except Exception:
        return FAILURE


@router.post('/artifact')
async def artifact(request: Request):
    try:
        return adapter().read_artifact(await body(request))
    except Exception:
        return FAILURE
