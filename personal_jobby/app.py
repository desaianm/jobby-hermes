import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from fastapi.exceptions import RequestValidationError
from personal_jobby.core import Job, Settings, Salary, exact_evidence
from personal_jobby.store import Store, ROOT, private_write, now
from personal_jobby.documents import prepare, NAMES
from personal_jobby.search import discover
from personal_jobby import private_fs as fs

STATIC=Path(__file__).parent/'static'
HOSTS={'localhost','127.0.0.1'}
if os.environ.get('JOBBY_TRUSTED_HOST'): HOSTS.add(os.environ['JOBBY_TRUSTED_HOST'])

class Status(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status:str=Field(max_length=30)
class Receipt(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text:str=Field(default='',max_length=10000)
    url:str=Field(default='',max_length=2000)
    timestamp:str=Field(max_length=100)
    attempt_id:str|None=Field(default=None,pattern='^[a-f0-9]{32}$')
class Search(BaseModel):
    model_config=ConfigDict(extra='forbid')
    term:str=Field(min_length=1,max_length=200)
    limit:int=Field(default=10,ge=1,le=25)
class Answers(BaseModel):
    model_config=ConfigDict(extra='forbid')
    work_eligibility:str=Field(default='',max_length=2000)
class Fit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    arrangement:str=Field(pattern='^(unknown|hybrid|remote|onsite)$')
    arrangement_evidence:str=Field(default='',max_length=2000)
    employment_type:str=Field(pattern='^(unknown|permanent_full_time|contract|temporary|part_time)$')
    employment_evidence:str=Field(default='',max_length=2000)
    qualifications_reviewed:bool=False
    qualification_review_note:str=Field(default='',max_length=2000)
    _exact_fit = field_validator('arrangement_evidence','employment_evidence')(exact_evidence)
class Phone(BaseModel):
    model_config=ConfigDict(extra='forbid')
    phone:SecretStr=Field(default=SecretStr(''),max_length=40)
    clear:bool=False
class Approval(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reviewer:str=Field(min_length=1,max_length=250)
    note:str=Field(min_length=1,max_length=2000)
    review_token:str=Field(pattern='^[a-f0-9]{64}$')


class Security:
    def __init__(self,app): self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http': return await self.app(scope,receive,send)
        headers=dict(scope['headers']); host=headers.get(b'host',b'').decode()
        try:
            parsed=urlsplit('//'+host)
            valid=parsed.hostname in HOSTS and parsed.username is None and parsed.password is None and parsed.port in (None,8090,9888,80,443)
        except ValueError: valid=False
        rejection=None
        if not valid: rejection=(400,'Host rejected')
        elif scope['method'] not in ('GET','HEAD','OPTIONS'):
            origin=headers.get(b'origin',b'').decode()
            if origin and origin not in ('http://'+host,'https://'+host): rejection=(403,'Foreign Origin rejected')
            elif headers.get(b'content-type',b'').split(b';')[0]!=b'application/json': rejection=(415,'JSON required')
            else:
                chunks=[]; total=0
                while True:
                    message=await receive()
                    if message['type']=='http.disconnect': return
                    chunk=message.get('body',b''); total+=len(chunk); chunks.append(chunk)
                    if total>100000: rejection=(413,'Request too large'); break
                    if not message.get('more_body',False): break
                sent=False
                original_receive=receive
                async def replay():
                    nonlocal sent
                    if not sent:
                        sent=True
                        return {'type':'http.request','body':b''.join(chunks),'more_body':False}
                    return await original_receive()
                receive=replay
        async def secure_send(message):
            if message['type']=='http.response.start':
                extra={'content-security-policy':"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",'cache-control':'no-store','x-robots-tag':'noindex, nofollow','x-content-type-options':'nosniff','referrer-policy':'no-referrer'}
                message['headers']=message.get('headers',[])+[(k.encode(),v.encode()) for k,v in extra.items()]
            await send(message)
        if rejection:
            return await JSONResponse({'detail':rejection[1]},rejection[0])(scope,receive,secure_send)
        await self.app(scope,receive,secure_send)


def create_app(root=ROOT):
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None); store=Store(root); app.state.store=store
    app.add_middleware(Security)
    @app.exception_handler(RequestValidationError)
    async def validation(request,e): return JSONResponse({'detail':'Invalid request fields or JSON; values withheld'},422)
    @app.exception_handler(ValueError)
    async def bad(request,e): return JSONResponse({'detail':'Request cannot be completed; check fields, evidence, or private file safety'},422)
    @app.exception_handler(KeyError)
    async def missing(request,e): return JSONResponse({'detail':'Job not found'},404)
    @app.get('/')
    def index(): return FileResponse(STATIC/'index.html')
    @app.get('/static/{name}')
    def static(name:str):
        if name not in {'app.js','style.css','system-flow.html','system-flow.css'}: raise HTTPException(404)
        return FileResponse(STATIC/name)
    @app.get('/api/daily')
    def daily():
        from personal_jobby.daily import Daily
        return store.redact(Daily(store).status())
    @app.get('/api/state')
    def state():
        p=store.profile()
        from personal_jobby.daily import Daily
        control=Daily(store).status()
        return dict(executor_type=control['executor_type'],executor_enabled=control['executor_enabled'],executor_note=control['capability'],profile=store.public_profile(),phone_present=bool(p.get('answers',{}).get('phone')),settings=store.settings(),jobs=store.redact(store.jobs()),missing_answers=[k for k in ('work_eligibility',) if not p.get('answers',{}).get(k)],submission_adapter='external Hermes cron agent' if control['policy']['cron_job_id'] else 'unavailable',submission_active=control['submission_active'])
    @app.put('/api/settings')
    def settings(data:Settings): return store.save_settings(data.model_dump())
    @app.put('/api/profile/answers')
    def answers(data:Answers):
        store.save_answers(data.model_dump()); return {'saved':True}
    @app.put('/api/profile/phone')
    def phone(data:Phone): return store.save_phone(data.phone.get_secret_value(),data.clear)
    @app.post('/api/jobs')
    def add(data:Job): return store.redact(store.add(data.model_dump()))
    @app.get('/api/jobs/{id}')
    def get(id:int): return store.redact(dict(job=store.get(id),events=store.events(id)))
    @app.put('/api/jobs/{id}/salary')
    def salary(id:int,data:Salary):
        j=store.get(id); j['salary']=store.redact(data.model_dump())
        from personal_jobby.core import assess
        state,_=assess(j,store.settings(),store.profile())
        with store.connect() as c:
            original={k:j[k] for k in Job.model_fields}; c.execute('UPDATE jobs SET data=?,updated=? WHERE id=?',(json.dumps(original),now(),id))
            if j['status'] in ('discovered','needs_review','eligible'): c.execute('UPDATE jobs SET status=? WHERE id=?',(state,id))
            store.event(c,id,'salary_verification',data.model_dump())
        return store.redact(store.get(id))
    @app.put('/api/jobs/{id}/fit')
    def fit(id:int,data:Fit):
        j=store.get(id);j.update(store.redact(data.model_dump()))
        from personal_jobby.core import assess
        eligibility,_=assess(j,store.settings(),store.profile())
        with store.connect() as c:
            c.execute('UPDATE jobs SET data=?,updated=? WHERE id=?',(json.dumps({k:j[k] for k in Job.model_fields}),now(),id))
            if j['status'] in ('discovered','needs_review','eligible'): c.execute('UPDATE jobs SET status=? WHERE id=?',(eligibility,id))
            store.event(c,id,'fit_verification',data.model_dump())
        return store.redact(store.get(id))
    @app.patch('/api/jobs/{id}/status')
    def status(id:int,data:Status): return store.redact(store.transition(id,data.status))
    @app.post('/api/jobs/{id}/receipt')
    def receipt(id:int,data:Receipt): return store.redact(store.receipt(id,**data.model_dump()))
    @app.post('/api/jobs/{id}/prepare')
    def materials(id:int): return prepare(store,id)
    @app.post('/api/jobs/{id}/visual-approval')
    def approve(id:int,data:Approval):
        store.get(id)
        from personal_jobby.artifacts import approve
        try: return approve(store,id,data.review_token,dict(reviewer=data.reviewer,note=data.note))
        except ValueError: raise HTTPException(409,'Reviewed version changed or unavailable; regenerate and review') from None
    @app.get('/api/jobs/{id}/artifacts/{name}')
    def artifact(id:int,name:str):
        store.get(id)
        if name not in NAMES: raise HTTPException(404)
        meta=store.materials(id)
        try: folder=store.artifact_dir(id);fs.check(folder/name)
        except ValueError: raise HTTPException(404) from None
        except FileNotFoundError: raise HTTPException(404) from None
        if not meta or meta.get('qa_state') not in ('pending_visual_review','visual_approved'): raise HTTPException(409,'Documents stale, unavailable or generation in progress')
        try: data=fs.read_bytes(folder/name)
        except (ValueError,FileNotFoundError): raise HTTPException(404) from None
        from fastapi.responses import Response
        from mimetypes import guess_type
        return Response(data,media_type=guess_type(name)[0] or 'application/octet-stream',headers={'Content-Disposition':'attachment; filename="'+name+'"'})
    @app.get('/api/jobs/{id}/attempts/{attempt_id}/{kind}/{name}')
    def historical(id:int,attempt_id:str,kind:str,name:str):
        from personal_jobby.audit import historical_bytes
        from fastapi.responses import Response
        from mimetypes import guess_type
        try: data,filename=historical_bytes(store,id,attempt_id,kind,name)
        except (KeyError,ValueError,OSError): raise HTTPException(404,'Historical artifact unavailable or integrity check failed') from None
        return Response(data,media_type=guess_type(filename)[0] or 'application/octet-stream',headers={'Content-Disposition':'attachment; filename="'+filename+'"'})
    @app.post('/api/search')
    def search(data:Search):
        try: return discover(store,data.term,data.limit)
        except Exception as e: raise HTTPException(502,'Search failed or source blocked. No results fabricated; try later or add a posting manually.') from e
    return app
