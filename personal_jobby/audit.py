"""External-operator application records. These functions never fill or submit forms."""
import hashlib
import json
import re
import struct
import uuid
from datetime import datetime
import fitz
from personal_jobby import private_fs as fs
from personal_jobby.core import public_url
from personal_jobby.store import now

DOCS={'resume.pdf','resume.docx','cover_letter.pdf','cover_letter.docx'}


def validate_id(id):
    if not re.fullmatch('[a-f0-9]{32}',id): raise ValueError('Invalid attempt identifier')
    return id


def list_attempts(store,job_id):
    with store.connect() as c:
        records=c.execute('SELECT * FROM application_attempts WHERE job_id=? ORDER BY created,id',(job_id,)).fetchall();result=[]
        for record in records:
            attempt=json.loads(record['data']);attempt.update(id=record['id'],created=record['created'],job_id=job_id,status='draft',submitted_at=None,screenshots=[],timeline=[])
            for event in c.execute('SELECT * FROM application_attempt_events WHERE attempt_id=? ORDER BY id',(record['id'],)):
                data=json.loads(event['data']);attempt['timeline'].append(dict(at=event['at'],kind=event['kind'],data=data))
                if event['kind']=='screenshot':
                    attempt['screenshots'].append(data);attempt['status']='filled_reviewed' if data['kind']=='filled_form' else 'confirmation_observed'
                if event['kind'] in ('submit_started','uncertain'): attempt['status']=event['kind']
                if event['kind']=='receipt': attempt.update(status='applied',submitted_at=data['timestamp'],receipt=data)
            reservation=c.execute('SELECT d.status,d.lease_expires FROM daily_reservations r JOIN daily_runs d ON d.id=r.run_id WHERE r.attempt_id=?',(record['id'],)).fetchone()
            if reservation and not attempt['submitted_at']:
                uncertain=any(e['kind']=='uncertain' for e in attempt['timeline']) or reservation['status']!='running' or datetime.fromisoformat(reservation['lease_expires'])<=datetime.now().astimezone()
                attempt['status']='uncertain' if uncertain else 'submit_started'
            result.append(store.redact(attempt))
    return result


def attempt_record(store,attempt_id):
    validate_id(attempt_id)
    with store.connect() as c: row=c.execute('SELECT job_id FROM application_attempts WHERE id=?',(attempt_id,)).fetchone()
    if not row: raise KeyError('Attempt not found')
    return next(a for a in list_attempts(store,row[0]) if a['id']==attempt_id)


def create_attempt(store,job_id,manifest):
    with fs.lock(store.root/("generation-"+str(job_id)+".lock")):
        return _create_attempt(store,job_id,manifest)

def _create_attempt(store,job_id,manifest):
    job=store.get(job_id);manifest=store.redact(manifest)
    if manifest.get('operator') not in ('hermes','user_reported'): raise ValueError('Explicit operator required')
    url=public_url(manifest.get('application_url',job['job_url']))
    generation=manifest.get('generation_id');documents={};approval=None
    if generation:
        validate_id(generation);meta=store.materials(job_id)
        if not meta or meta.get('qa_state')!='visual_approved' or meta.get('generation_id')!=generation or meta.get('review_token')!=manifest.get('review_token'): raise ValueError('Explicit currently approved generation required')
        if 'cover_letter' not in manifest: raise ValueError('Explicit cover_letter document or null (not attached) required')
        for role,prefix in (('resume','resume.'),('cover_letter','cover_letter.')):
            entry=manifest.get(role,{})
            if role=='cover_letter' and entry is None: continue
            if not isinstance(entry,dict): raise ValueError('Explicit correct document filename and hash required')
            filename=entry.get('filename','');expected=entry.get('sha256','')
            if filename not in DOCS or not filename.startswith(prefix) or not re.fullmatch('[a-f0-9]{64}',expected): raise ValueError('Explicit correct document filename and hash required')
            payload=fs.read_bytes(store.artifact_dir(job_id)/filename)
            if hashlib.sha256(payload).hexdigest()!=expected or meta['artifact_hashes'].get(filename)!=expected: raise ValueError('Document hash mismatch')
            documents[role]=dict(filename=filename,sha256=expected)
        approval=meta['visual_approval']
    elif manifest['operator']=='hermes': raise ValueError('Hermes-managed attempt requires an approved generation manifest')
    id=uuid.uuid4().hex
    canonical=job.get('original_source',{}).get('job_url_direct') or job['job_url']
    try: public_url(canonical)
    except ValueError: canonical=job['job_url']
    data=dict(operator=manifest['operator'],generation_id=generation,documents_used='explicit manifest' if generation else 'unknown',documents=documents,application_url=url,posting_url=job['job_url'],canonical_url=canonical,requisition=job['requisition'],posting_snapshot=store.job_snapshot(job_id),approval=approval,blockers_at_capture=job['blockers'],screenshot_policy='Phone must be masked/removed in external form BEFORE capture. Only visually reviewed sanitized PNGs accepted locally.')
    data['cover_letter_used']='cover_letter' in documents if generation else None
    if generation and not data['cover_letter_used']: data['documents_used']='explicit manifest (cover letter: none)'
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM events WHERE job_id=? AND kind='receipt'",(job_id,)).fetchone(): raise ValueError('Already submitted; no repeated application attempt')
        if manifest['operator']=='user_reported':
            from personal_jobby.daily import Daily
            keys,ids=Daily(store).posting_keys(c,job_id)
            if any(r['job_id'] in ids or keys & set(json.loads(r['data'])['posting_keys']) for r in c.execute('SELECT job_id,data FROM daily_reservations')): raise ValueError('Receipt must use the exact reserved attempt')
        folder=store.root/'applications'/id;fs.mkdir(folder/'documents')
        for document in documents.values():
            payload=fs.read_bytes(store.artifact_dir(job_id)/document['filename'])
            if hashlib.sha256(payload).hexdigest()!=document['sha256']: raise ValueError('Generation changed during capture')
            fs.create_bytes(folder/'documents'/document['filename'],payload)
        fs.create_bytes(folder/'manifest.json',json.dumps(store.redact(data),indent=2).encode())
        c.execute('INSERT INTO application_attempts VALUES(?,?,?,?)',(id,job_id,now(),json.dumps(store.redact(data))))
    return attempt_record(store,id)


def add_screenshot(store,attempt_id,path,kind,qa_note,phone_redacted=False):
    attempt=attempt_record(store,attempt_id)
    if attempt['status']=='applied': raise ValueError('Submitted audit is immutable')
    if kind not in ('filled_form','employer_confirmation') or not phone_redacted or not qa_note.strip() or len(qa_note)>2000: raise ValueError('Reviewed phone-sanitized screenshot and QA note required')
    payload=fs.read_bytes(path,max_bytes=8*1024*1024)
    if not payload.startswith(b'\x89PNG\r\n\x1a\n') or len(payload)<33 or payload[12:16]!=b'IHDR': raise ValueError('Valid PNG required')
    width,height=struct.unpack('>II',payload[16:24])
    if not 1<=width<=4000 or not 1<=height<=4000 or width*height>16000000: raise ValueError('PNG pixel bounds exceeded')
    offset=8
    while offset<len(payload):
        if offset+12>len(payload): raise ValueError('Invalid PNG chunks')
        size=struct.unpack('>I',payload[offset:offset+4])[0];tag=payload[offset+4:offset+8]
        if size>len(payload)-offset-12: raise ValueError('Invalid PNG chunk length')
        if tag in (b'tEXt',b'iTXt',b'zTXt'): raise ValueError('PNG textual metadata must be removed before ingestion')
        offset+=size+12
    try:
        pixmap=fitz.Pixmap(payload)
        if pixmap.width!=width or pixmap.height!=height: raise ValueError('PNG shape mismatch')
    except Exception: raise ValueError('PNG cannot be decoded') from None
    id=uuid.uuid4().hex;folder=store.root/'applications'/attempt_id/'screenshots';fs.mkdir(folder)
    fs.create_bytes(folder/(id+'.png'),payload)
    data=store.redact(dict(id=id,kind=kind,filename=id+'.png',sha256=hashlib.sha256(payload).hexdigest(),qa_note=qa_note,phone_redacted_before_capture=True,generation_id=attempt['generation_id'],at=now()))
    with store.connect() as c: c.execute('INSERT INTO application_attempt_events(attempt_id,at,kind,data) VALUES(?,?,?,?)',(attempt_id,now(),'screenshot',json.dumps(data)))
    return data


def record_receipt(store,job_id,text,timestamp,url,attempt_id):
    if url: public_url(url)
    if not text.strip() and not url: raise ValueError('Receipt evidence required')
    if len(text)>10000: raise ValueError('Receipt too long')
    time=datetime.fromisoformat(timestamp)
    if time.tzinfo is None: raise ValueError('Timestamp with timezone required')
    if attempt_id is None: attempt=create_attempt(store,job_id,{'operator':'user_reported'})
    else:
        attempt=attempt_record(store,attempt_id)
        if attempt['job_id']!=job_id: raise ValueError('Attempt belongs to another posting')
    if attempt['operator']=='hermes':
        kinds={s['kind'] for s in attempt['screenshots']}
        if not {'filled_form','employer_confirmation'}<=kinds: raise ValueError('Reviewed filled-form and employer confirmation screenshots required')
    receipt=store.redact(dict(text=text,url=url,timestamp=timestamp,attempt_id=attempt['id'],generation_id=attempt['generation_id'],documents_used=attempt['documents_used'],documents=attempt['documents'],action='recording only'))
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM events WHERE job_id=? AND kind='receipt'",(job_id,)).fetchone(): raise ValueError('Receipt already recorded')
        from personal_jobby.daily import Daily
        Daily(store).resolve_receipt(c,job_id,attempt,receipt)
        c.execute('INSERT INTO application_attempt_events(attempt_id,at,kind,data) VALUES(?,?,?,?)',(attempt['id'],now(),'receipt',json.dumps(receipt)))
        store.event(c,job_id,'receipt',receipt);c.execute("UPDATE jobs SET status='applied',updated=? WHERE id=?",(now(),job_id))
    return store.get(job_id)


def historical_bytes(store,job_id,attempt_id,kind,name):
    attempt=attempt_record(store,attempt_id)
    if attempt['job_id']!=job_id: raise KeyError('Attempt belongs to another job')
    if kind=='documents':
        document=next((v for v in attempt['documents'].values() if v['filename']==name),None)
        if not document: raise KeyError('Document not in submitted manifest')
        relative='documents';filename=name;expected=document['sha256']
    elif kind=='screenshots':
        validate_id(name);screenshot=next((s for s in attempt['screenshots'] if s['id']==name),None)
        if not screenshot: raise KeyError('Screenshot not in attempt')
        relative='screenshots';filename=screenshot['filename'];expected=screenshot['sha256']
    else: raise KeyError('Unknown historical artifact')
    data=fs.read_bytes(store.root/'applications'/attempt_id/relative/filename)
    if hashlib.sha256(data).hexdigest()!=expected: raise ValueError('Historical artifact integrity failure')
    return data,filename
