"""Immutable generations and approval fingerprints; publish by one atomic pointer write."""
import hashlib
import json
import re
import uuid
from personal_jobby import private_fs as fs
from personal_jobby.core import Job, Settings
from personal_jobby.store import now


def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def bindings(store,id,*,profile=None,job=None,settings=None):
    snapshot=profile is not None
    profile=store.public_profile() if profile is None else profile
    job=store.job_snapshot(id) if job is None else {k:job[k] for k in Job.model_fields}
    settings=store.settings() if settings is None else settings
    candidate={k:profile.get(k) for k in ('name','contact','links','facts','source_hashes')}
    sources={}
    for path,expected in profile.get('source_hashes',{}).items():
        if path.startswith('/') and not snapshot:
            try: sources[path]=hashlib.sha256(fs.read_bytes(path)).hexdigest()
            except (OSError,ValueError): sources[path]='unavailable'
        else: sources[path]=expected  # Snapshots bind their exact imported source hashes.
    return dict(candidate=digest(candidate),sources=digest(sources),settings=digest(Settings.model_validate({k:v for k,v in settings.items() if k in Settings.model_fields}).model_dump()),job=digest(store.redact(job)))


def base(store,id):
    path=store.root/'artifacts'/str(id)
    fs.check(path.parent);fs.check(path)
    return path


def artifact_dir(store,id):
    folder=base(store,id);pointer=json.loads(fs.read_text(folder/'current.json'))
    generation=pointer.get('generation_id','')
    if not re.fullmatch('[a-f0-9]{32}',generation): raise ValueError('Invalid material generation')
    result=folder/'generations'/generation;fs.check(result)
    return result


def load(store,id):
    try:
        folder=base(store,id);pointer=json.loads(fs.read_text(folder/'current.json'))
        if pointer.get('qa_state')=='generation_in_progress': return pointer
        target=artifact_dir(store,id);meta=json.loads(fs.read_text(target/'metadata.json'))
        if meta.get('generation_id')!=pointer.get('generation_id'): raise ValueError('Generation mismatch')
        expected=bindings(store,id)
        fresh=meta.get('fingerprints')==expected
        for name,value in meta.get('artifact_hashes',{}).items():
            from personal_jobby.documents import NAMES
            if name not in NAMES or name=='metadata.json': raise ValueError('Invalid artifact name')
            if hashlib.sha256(fs.read_bytes(target/name)).hexdigest()!=value: fresh=False
        if meta.get('review_token')!=digest({'generation_id':meta.get('generation_id'),'fingerprints':meta.get('fingerprints'),'artifact_hashes':meta.get('artifact_hashes')}): fresh=False
        if not fresh: return {**meta,'qa_state':'stale','reason':'Documents source changed or candidate/settings/job/artifact changed; regenerate and review'}
        return meta
    except FileNotFoundError: return None
    except (ValueError,OSError,json.JSONDecodeError): return {'qa_state':'invalidated','reason':'Unsafe or invalid material path; regenerate'}


def begin(store,id,*,profile=None,job=None,settings=None):
    folder=base(store,id);fs.mkdir(folder)
    generation=uuid.uuid4().hex
    # Revoke the previous approval/downloads before any rendering operation.
    fs.write_text(folder/'current.json',json.dumps(dict(generation_id=generation,qa_state='generation_in_progress',created=now())))
    with store.connect() as c: store.event(c,id,'generation_started',{'generation_id':generation})
    profile=store.public_profile() if profile is None else profile
    for path,expected in profile.get('source_hashes',{}).items():
        if path.startswith('/') and hashlib.sha256(fs.read_bytes(path)).hexdigest()!=expected: raise ValueError('Authoritative source changed; reimport before generation')
    stage=folder/('.staging-'+generation);fs.mkdir(stage)
    initial=bindings(store,id,profile=profile,job=job,settings=settings)
    if bindings(store,id)!=initial: raise ValueError('Inputs changed during generation; retry')
    return stage,generation,initial


def publish(store,id,stage,generation,meta,initial):
    if bindings(store,id)!=initial: raise ValueError('Inputs changed during generation; retry')
    meta.update(generation_id=generation,fingerprints=initial)
    meta['review_token']=digest({'generation_id':generation,'fingerprints':initial,'artifact_hashes':meta['artifact_hashes']})
    fs.write_text(stage/'metadata.json',json.dumps(meta,indent=2))
    target=base(store,id)/'generations'/generation;fs.mkdir(target.parent);fs.check_tree(stage);fs.move(stage,target)
    fs.write_text(base(store,id)/'current.json',json.dumps(dict(generation_id=generation,qa_state='published')))
    return meta


def approve(store,id,token,review):
    with fs.lock(store.root/('generation-'+str(id)+'.lock')):
        meta=load(store,id)
        if not meta or meta.get('qa_state') not in ('pending_visual_review','visual_approved') or meta.get('review_token')!=token: raise ValueError('Reviewed material version no longer current')
        meta.update(qa_state='visual_approved',visual_approval={**store.redact(review),'at':now(),'review_token':token,'fingerprints':meta['fingerprints'],'artifact_hashes':meta['artifact_hashes']})
        fs.write_text(artifact_dir(store,id)/'metadata.json',json.dumps(meta,indent=2))
        with store.connect() as c: store.event(c,id,'visual_approval',meta['visual_approval'])
        return meta
