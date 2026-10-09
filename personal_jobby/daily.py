"""Durable deterministic controls for an external Hermes cron agent. Never clicks forms."""
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from personal_jobby import private_fs as fs

TORONTO=ZoneInfo('America/Toronto')
# Provenance label only; operators must obtain actual authorization externally.
AUTHORIZATION=os.environ.get('JOBBY_AUTHORIZATION_SOURCE', 'operator-managed policy; confirm authorization externally')
OUTCOMES={'discovered','verified','queued','blocked','excluded','failed','submitted','uncertain'}
SCHEMA='''
CREATE TABLE IF NOT EXISTS daily_runs(id TEXT PRIMARY KEY, owner TEXT NOT NULL, day TEXT NOT NULL, started TEXT NOT NULL, lease_expires TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily_events(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL,at TEXT NOT NULL,job_id INTEGER,attempt_id TEXT,kind TEXT NOT NULL,reason TEXT NOT NULL,source_url TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily_reservations(attempt_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,job_id INTEGER NOT NULL,day TEXT NOT NULL,at TEXT NOT NULL,data TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS immutable_daily_events_update BEFORE UPDATE ON daily_events BEGIN SELECT RAISE(ABORT,'append only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_daily_events_delete BEFORE DELETE ON daily_events BEGIN SELECT RAISE(ABORT,'append only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_daily_reservations_update BEFORE UPDATE ON daily_reservations BEGIN SELECT RAISE(ABORT,'append only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_daily_reservations_delete BEFORE DELETE ON daily_reservations BEGIN SELECT RAISE(ABORT,'append only'); END;
'''


class Daily:
    def __init__(self,store,clock=None):
        self.store=store
        self.clock=clock or (lambda: datetime.now(timezone.utc))
        self.policy_path=store.root/'daily-policy.json'

    def now(self):
        value=self.clock()
        if value.tzinfo is None: raise ValueError('Aware clock required')
        return value.astimezone(timezone.utc)

    def policy(self):
        try: data=json.loads(fs.read_bytes(self.policy_path,max_bytes=4096))
        except FileNotFoundError: data={}
        return self.validate_policy({**dict(enabled=False,cron_job_id=None,schedule=None,timezone='America/Toronto',max_submissions_per_day=10,authorization_source=AUTHORIZATION),**data})

    @staticmethod
    def validate_policy(data):
        if set(data)!= {'enabled','cron_job_id','schedule','timezone','max_submissions_per_day','authorization_source'}: raise ValueError('Invalid policy fields')
        if type(data['enabled']) is not bool or type(data['max_submissions_per_day']) is not int or not 1<=data['max_submissions_per_day']<=25: raise ValueError('Invalid policy bounds')
        if data['timezone']!='America/Toronto' or data['authorization_source']!=AUTHORIZATION: raise ValueError('Invalid policy provenance')
        for key in ('cron_job_id','schedule'):
            if data[key] is not None and (not isinstance(data[key],str) or not data[key].strip() or len(data[key])>200 or re.search(r'[\r\n\x00]',data[key])): raise ValueError('Invalid external executor configuration')
        if data['enabled'] and (not data['cron_job_id'] or not data['schedule']): raise ValueError('Configured external cron ID and schedule required')
        return data

    def configure(self,**changes):
        with fs.lock(self.store.root/'daily-policy.lock'):
            data=self.validate_policy({**self.policy(),**changes})
            fs.write_text(self.policy_path,json.dumps(self.store.redact(data),indent=2))
        return data

    def status(self):
        policy=self.policy();settings=self.store.settings()
        holds=[]
        if not policy['enabled']: holds.append('Daily pilot disabled')
        if not settings['criteria_confirmed']: holds.append('Current criteria unconfirmed')
        if not settings['submission_desired']: holds.append('Submission intent disabled (kill switch)')
        with self.store.connect() as c:
            reservations=self.reservation_states(c)
        summary=self.summary()
        return dict(confirmed_today=sum(r['state']=='confirmed' and r['day']==summary['day'] for r in reservations),latest_run=summary['run'],latest_outcomes=summary,uncertain_count=sum(r['state']=='uncertain' for r in reservations),pending_count=sum(r['state']=='submit_started' for r in reservations),unresolved_submissions=[r for r in reservations if r['state']!='confirmed'],policy=policy,executor_type='hermes_cron_agent',executor_enabled=policy['enabled'],submission_permitted=not holds,submission_active=not holds and summary['lease_active'],holds=holds,capability='External Hermes agent executes browser actions; API and CLI never click forms. Schedule is parent-reported configuration, not verified runtime health.')

    def text(self,value,limit=500,required=True):
        if not isinstance(value,str) or len(value)>limit or (required and not value.strip()) or re.search(r'[\x00-\x08\x0b-\x1f]',value): raise ValueError('Short redacted text required')
        return self.store.redact(value)

    def emit(self,c,run_id,kind,reason='',job_id=None,attempt_id=None,source_url=''):
        c.execute('INSERT INTO daily_events(run_id,at,job_id,attempt_id,kind,reason,source_url) VALUES(?,?,?,?,?,?,?)',(run_id,self.now().isoformat(),job_id,attempt_id,kind,reason,source_url))

    def live(self,c,run_id):
        from personal_jobby.audit import validate_id
        validate_id(run_id)
        row=c.execute('SELECT * FROM daily_runs WHERE id=?',(run_id,)).fetchone()
        if not row or row['status']!='running' or datetime.fromisoformat(row['lease_expires'])<=self.now(): raise ValueError('Live run lease required')
        return row

    def start(self,owner):
        owner=self.text(owner,100)
        with fs.lock(self.store.root/'daily-policy.lock'),self.store.connect() as c:
            if not self.policy()['enabled']: raise ValueError('Daily pilot disabled')
            c.execute('BEGIN IMMEDIATE')
            for run in c.execute("SELECT * FROM daily_runs WHERE status='running'").fetchall():
                if datetime.fromisoformat(run['lease_expires'])>self.now(): raise ValueError('Global daily lease already held')
                c.execute("UPDATE daily_runs SET status='interrupted' WHERE id=?",(run['id'],))
                self.emit(c,run['id'],'run_interrupted','Expired lease recovered; unresolved submissions remain locked')
                self.mark_unresolved(c,run['id'],'Lease interrupted after reservation; outcome uncertain')
            id=uuid.uuid4().hex;at=self.now();expires=at+timedelta(minutes=30);day=at.astimezone(TORONTO).date().isoformat()
            c.execute('INSERT INTO daily_runs VALUES(?,?,?,?,?,?)',(id,owner,day,at.isoformat(),expires.isoformat(),'running'))
            self.emit(c,id,'run_started')
        return dict(run_id=id,owner=owner,day=day,lease_expires_at=expires.isoformat(),ownership='Opaque run ID owns the lease; not dependent on a CLI process PID')

    def heartbeat(self,run_id):
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');self.live(c,run_id)
            expires=(self.now()+timedelta(minutes=30)).isoformat()
            c.execute('UPDATE daily_runs SET lease_expires=? WHERE id=?',(expires,run_id));self.emit(c,run_id,'heartbeat')
        return dict(run_id=run_id,lease_expires_at=expires)

    def finish(self,run_id,status,note=''):
        if status not in {'completed','partial','blocked','failed'}: raise ValueError('Invalid terminal run status')
        note=self.text(note,required=False)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');self.live(c,run_id)
            c.execute('UPDATE daily_runs SET status=? WHERE id=?',(status,run_id))
            self.mark_unresolved(c,run_id,'Run ended without a confirmed receipt; outcome uncertain')
            self.emit(c,run_id,'run_finished',note)
        return self.summary(run_id)

    def note(self,run_id,job_id,outcome,reason,source_url=''):
        from personal_jobby.core import public_url
        if outcome not in OUTCOMES: raise ValueError('Invalid outcome')
        reason=self.text(reason)
        if source_url:
            if len(source_url)>2000: raise ValueError('Public URL too long')
            public_url(source_url);source_url=self.text(source_url,2000)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');self.live(c,run_id)
            if not c.execute('SELECT 1 FROM jobs WHERE id=?',(job_id,)).fetchone(): raise KeyError('Job not found')
            if outcome=='submitted' and not c.execute("SELECT 1 FROM events WHERE job_id=? AND kind='receipt'",(job_id,)).fetchone(): raise ValueError('Actual guarded receipt required; notes cannot invent submissions')
            self.emit(c,run_id,outcome,reason,job_id=job_id,source_url=source_url)
        return self.summary(run_id)

    def summary(self,run_id=None):
        if run_id:
            from personal_jobby.audit import validate_id
            validate_id(run_id)
        with self.store.connect() as c:
            run=c.execute('SELECT * FROM daily_runs WHERE id=?',(run_id,)).fetchone() if run_id else c.execute('SELECT * FROM daily_runs ORDER BY started DESC,rowid DESC LIMIT 1').fetchone()
            if run_id and not run: raise KeyError('Run not found')
            events=[dict(r) for r in c.execute('SELECT * FROM daily_events WHERE run_id=? ORDER BY id',(run['id'],))] if run else []
            counts={k:sum(e['kind']==k for e in events) for k in sorted(OUTCOMES)}
            # Submitted note claims never contribute to submitted totals.
            counts['submitted']=c.execute("SELECT COUNT(*) FROM daily_reservations r WHERE r.run_id=? AND EXISTS(SELECT 1 FROM application_attempt_events e WHERE e.attempt_id=r.attempt_id AND e.kind='receipt')",(run['id'],)).fetchone()[0] if run else 0
            day=self.now().astimezone(TORONTO).date().isoformat()
            used=c.execute('SELECT COUNT(*) FROM daily_reservations WHERE day=?',(day,)).fetchone()[0]
            reservations=self.reservation_states(c,run['id']) if run else []
            counts['uncertain']=sum(r['state']=='uncertain' for r in reservations)
        return self.store.redact(dict(run=dict(run) if run else None,lease_active=bool(run and run['status']=='running' and datetime.fromisoformat(run['lease_expires'])>self.now()),counts=counts,events=events,reservations=reservations,day=day,attempted_submissions_today=used))

    def posting_keys(self,c,job_id):
        """Resolve historical URL aliases transitively, retaining requisition identities."""
        from personal_jobby.store import canonical_url
        from personal_jobby.core import normalize_employer
        by_job={}
        for row in c.execute('SELECT id,data FROM jobs'):
            data=json.loads(row['data']);keys={'url:'+canonical_url(u) for u in self.store.aliases(data)}
            if data.get('requisition'): keys.add('req:'+normalize_employer(data['company'])+':'+data['requisition'].strip().casefold())
            by_job[row['id']]=keys
        for row in c.execute('SELECT url,job_id FROM job_aliases'):
            by_job.setdefault(row['job_id'],set()).add('url:'+canonical_url(row['url']))
        keys=set(by_job.get(job_id,()));ids={job_id}
        changed=True
        while changed:
            changed=False
            for id,aliases in by_job.items():
                if keys & aliases and id not in ids:
                    keys.update(aliases);ids.add(id);changed=True
        return keys,ids

    def begin_submit(self,run_id,attempt_id,*,phone_required=None):
        from personal_jobby.audit import attempt_record,historical_bytes
        from personal_jobby.artifacts import bindings
        if type(phone_required) is not bool: raise ValueError('Explicit actual form phone requirement required')
        attempt=attempt_record(self.store,attempt_id);job_id=attempt['job_id']
        # File locks protect the profile, configuration, and generation; SQLite serializes
        # settings/job edits and global budget reservations across independent CLI processes.
        with fs.lock(self.store.root/'daily-policy.lock'),self.store.profile_lock(),fs.lock(self.store.root/('generation-'+str(job_id)+'.lock')),self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');self.live(c,run_id)
            policy=self.policy();settings=self.store.settings();profile=self.store.profile()
            if not policy['enabled'] or not settings['criteria_confirmed'] or not settings['submission_desired']: raise ValueError('Pilot and current submission criteria/intent required')
            if not profile.get('answers',{}).get('work_eligibility','').strip(): raise ValueError('Confirmed work eligibility answer required')
            if phone_required and not profile.get('answers',{}).get('phone','').strip(): raise ValueError('Actual form requires saved phone')
            job=self.store.get(job_id)
            if job['eligibility']!='eligible': raise ValueError('Current posting eligibility must be eligible')
            keys,ids=self.posting_keys(c,job_id)
            for id in ids:
                row=c.execute('SELECT status FROM jobs WHERE id=?',(id,)).fetchone()
                if row['status'] in {'applied','interview','offer','rejected','submission_pending','archived'} or c.execute("SELECT 1 FROM events WHERE job_id=? AND kind='receipt'",(id,)).fetchone(): raise ValueError('Posting already applied, held or archived')
            for row in c.execute('SELECT job_id,data FROM daily_reservations'):
                if row['job_id'] in ids or keys & set(json.loads(row['data'])['posting_keys']): raise ValueError('Underlying posting has prior reservation; no automatic retry')
            meta=self.store.materials(job_id)
            if attempt['operator']!='hermes' or not meta or meta.get('qa_state')!='visual_approved' or meta.get('generation_id')!=attempt['generation_id'] or meta.get('fingerprints')!=bindings(self.store,job_id): raise ValueError('Current visually approved attempt generation required')
            approval=attempt.get('approval') or {}
            if any(approval.get(k)!=meta.get(k) for k in ('review_token','fingerprints','artifact_hashes')): raise ValueError('Attempt approval no longer matches exact version')
            if attempt['posting_snapshot']!=self.store.job_snapshot(job_id) or 'resume' not in attempt['documents']: raise ValueError('Exact current posting and resume manifest required')
            for doc in attempt['documents'].values():
                if meta['artifact_hashes'].get(doc['filename'])!=doc['sha256']: raise ValueError('Document changed')
                historical_bytes(self.store,job_id,attempt_id,'documents',doc['filename'])
            shots=[s for s in attempt['screenshots'] if s['kind']=='filled_form' and s['generation_id']==attempt['generation_id'] and s.get('phone_redacted_before_capture') and s.get('qa_note','').strip()]
            if not shots or attempt.get('submitted_at') or any(s['kind']=='employer_confirmation' for s in attempt['screenshots']): raise ValueError('Actual reviewed filled-form screenshot before submission required')
            for shot in shots: historical_bytes(self.store,job_id,attempt_id,'screenshots',shot['id'])
            day=self.now().astimezone(TORONTO).date().isoformat()
            used=c.execute('SELECT COUNT(*) FROM daily_reservations WHERE day=?',(day,)).fetchone()[0]
            if used>=policy['max_submissions_per_day']: raise ValueError('Toronto daily attempted-submission cap reached')
            data=dict(state='submit_started',generation_id=attempt['generation_id'],documents=attempt['documents'],cover_letter_used=attempt['cover_letter_used'],fingerprints=meta['fingerprints'],review_token=meta['review_token'],posting_keys=sorted(keys),phone_required=phone_required)
            c.execute('INSERT INTO daily_reservations VALUES(?,?,?,?,?,?)',(attempt_id,run_id,job_id,day,self.now().isoformat(),json.dumps(data)))
            self.emit(c,run_id,'submit_started','Reserved before external click; confirmation not yet recorded',job_id,attempt_id,job['job_url'])
            c.execute('INSERT INTO application_attempt_events(attempt_id,at,kind,data) VALUES(?,?,?,?)',(attempt_id,self.now().isoformat(),'submit_started',json.dumps(dict(run_id=run_id,day=day,generation_id=attempt['generation_id']))))
            c.execute("UPDATE jobs SET status='submission_pending',updated=? WHERE id=?",(self.now().isoformat(),job_id))
            self.store.event(c,job_id,'submit_started',dict(run_id=run_id,attempt_id=attempt_id,generation_id=attempt['generation_id']))
        return dict(run_id=run_id,attempt_id=attempt_id,state='submit_started',day=day,attempted_submissions_today=used+1,cover_letter_used=attempt['cover_letter_used'],instruction='Reservation persisted. External operator must submit once or mark uncertain; CLI never clicks.')

    def reservation_states(self,c,run_id=None):
        query='''SELECT r.*, d.status AS run_status,d.lease_expires FROM daily_reservations r JOIN daily_runs d ON d.id=r.run_id'''
        rows=c.execute(query+(' WHERE r.run_id=?' if run_id else '')+' ORDER BY r.at,r.attempt_id',(run_id,) if run_id else ()).fetchall()
        result=[]
        for row in rows:
            receipt=c.execute("SELECT data FROM application_attempt_events WHERE attempt_id=? AND kind='receipt'",(row['attempt_id'],)).fetchone()
            explicit=c.execute("SELECT reason FROM daily_events WHERE attempt_id=? AND kind='uncertain' ORDER BY id DESC LIMIT 1",(row['attempt_id'],)).fetchone()
            state='confirmed' if receipt else ('uncertain' if explicit or row['run_status']!='running' or datetime.fromisoformat(row['lease_expires'])<=self.now() else 'submit_started')
            job=json.loads(c.execute('SELECT data FROM jobs WHERE id=?',(row['job_id'],)).fetchone()[0])
            result.append(dict(run_id=row['run_id'],attempt_id=row['attempt_id'],job_id=row['job_id'],day=row['day'],reserved_at=row['at'],state=state,source_url=job['job_url'],reason=explicit[0] if explicit and not receipt else '',submitted_at=json.loads(receipt[0])['timestamp'] if receipt else None))
        return result

    def mark_unresolved(self,c,run_id,reason):
        for row in self.reservation_states(c,run_id):
            if row['state']=='confirmed' or c.execute("SELECT 1 FROM daily_events WHERE attempt_id=? AND kind='uncertain'",(row['attempt_id'],)).fetchone(): continue
            self.emit(c,run_id,'uncertain',reason,row['job_id'],row['attempt_id'],row['source_url'])
            c.execute('INSERT INTO application_attempt_events(attempt_id,at,kind,data) VALUES(?,?,?,?)',(row['attempt_id'],self.now().isoformat(),'uncertain',json.dumps(dict(run_id=run_id,reason=reason))))
            self.store.event(c,row['job_id'],'uncertain',dict(attempt_id=row['attempt_id'],reason=reason))

    def uncertain(self,run_id,attempt_id,reason):
        reason=self.text(reason)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');self.live(c,run_id)
            row=c.execute('SELECT * FROM daily_reservations WHERE attempt_id=? AND run_id=?',(attempt_id,run_id)).fetchone()
            if not row or c.execute("SELECT 1 FROM application_attempt_events WHERE attempt_id=? AND kind='receipt'",(attempt_id,)).fetchone(): raise ValueError('Unresolved reservation belonging to run required')
            self.emit(c,run_id,'uncertain',reason,row['job_id'],attempt_id)
            c.execute('INSERT INTO application_attempt_events(attempt_id,at,kind,data) VALUES(?,?,?,?)',(attempt_id,self.now().isoformat(),'uncertain',json.dumps(dict(run_id=run_id,reason=reason))))
            self.store.event(c,row['job_id'],'uncertain',dict(attempt_id=attempt_id,reason=reason))
        return self.summary(run_id)

    def resolve_receipt(self,c,job_id,attempt,receipt):
        """Called inside the existing guarded receipt transaction; never releases a lock."""
        from personal_jobby.audit import historical_bytes
        row=c.execute('SELECT * FROM daily_reservations WHERE attempt_id=?',(attempt['id'],)).fetchone()
        keys,ids=self.posting_keys(c,job_id)
        other=[r for r in c.execute('SELECT * FROM daily_reservations') if r['job_id'] in ids or keys & set(json.loads(r['data'])['posting_keys'])]
        if any(r['attempt_id']!=attempt['id'] for r in other): raise ValueError('Receipt must resolve the exact reserved attempt')
        # Captured evidence must remain intact even outside the daily pilot.
        for doc in attempt['documents'].values(): historical_bytes(self.store,job_id,attempt['id'],'documents',doc['filename'])
        for shot in attempt['screenshots']: historical_bytes(self.store,job_id,attempt['id'],'screenshots',shot['id'])
        if not row:
            if self.policy()['enabled'] and attempt['operator']=='hermes': raise ValueError('Enabled Hermes pilot requires pre-click reservation')
            return
        if row['job_id']!=job_id: raise ValueError('Reserved posting mismatch')
        data=json.loads(row['data'])
        if data['generation_id']!=attempt['generation_id'] or data['documents']!=attempt['documents']: raise ValueError('Receipt version mismatch')
        if datetime.fromisoformat(receipt['timestamp'])<datetime.fromisoformat(row['at']): raise ValueError('Receipt predates reservation')
        started=next((i for i,e in enumerate(attempt['timeline']) if e['kind']=='submit_started'),None)
        if started is None or not any(e['kind']=='screenshot' and e['data']['kind']=='employer_confirmation' for e in attempt['timeline'][started+1:]): raise ValueError('Actual reviewed confirmation after reservation required')
        self.emit(c,row['run_id'],'receipt_confirmed','Guarded actual receipt recorded',job_id,attempt['id'],receipt['url'])


    def verify_job(self,job_id,proof):
        """Persist externally observed employer salary proof; performs no HTTP requests."""
        from personal_jobby.core import Job,Salary,salary_decision,assess
        if not isinstance(proof,dict) or set(proof)!={'salary','operator_note'}: raise ValueError('Salary and source-grounded operator note only')
        salary=Salary.model_validate(proof['salary']).model_dump()
        note=self.text(proof['operator_note'],2000)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            job=self.store.job_snapshot(job_id);settings=self.store.settings()
            if salary_decision(salary,settings['minimum'])[0]=='needs_review': raise ValueError('Exact verified employer annual CAD base proof required')
            job['salary']=salary
            job['original_source']={**job['original_source'],'employer_salary_verification':dict(salary=salary,operator_note=note,observed_at=self.now().isoformat(),provenance='External operator public employer source observation; no local fetch')}
            job=Job.model_validate(self.store.redact(job)).model_dump()
            c.execute('UPDATE jobs SET data=?,updated=? WHERE id=?',(json.dumps(job),self.now().isoformat(),job_id))
            state=assess(job,settings,self.store.profile())[0]
            c.execute("UPDATE jobs SET status=? WHERE id=? AND status IN ('discovered','needs_review','eligible')",(state,job_id))
            self.store.event(c,job_id,'salary_verification',job['original_source']['employer_salary_verification'])
        return self.store.get(job_id)


def add_parser(sub):
    parser=sub.add_parser('daily',help='Durable guards for an external Hermes cron agent; never submits')
    actions=parser.add_subparsers(dest='daily_command',required=True)
    verify=actions.add_parser('verify-job',help='Record external employer salary proof from a local JSON file; no URL fetch')
    verify.add_argument('job_id',type=int);verify.add_argument('--evidence',required=True,help='Private JSON with salary object and source-grounded operator_note')
    actions.add_parser('status',help='Safe policy, executor configuration, counts and holds')
    configure=actions.add_parser('configure',help='Parent-reported external cron configuration; default disabled')
    configure.add_argument('--enabled',choices=['true','false'],required=True)
    configure.add_argument('--cron-job-id',help='Actual externally configured Hermes job ID; required when enabling')
    configure.add_argument('--schedule',help='External cron schedule string; required when enabling')
    configure.add_argument('--timezone',choices=['America/Toronto'])
    configure.add_argument('--max-submissions-per-day',type=int,help='Attempted submissions, including uncertain (1–25; initial 10)')
    start=actions.add_parser('start',help='Acquire one durable global 30-minute lease; requires enabled pilot')
    start.add_argument('--owner',required=True,help='Opaque owner label; never use credentials or candidate information')
    heartbeat=actions.add_parser('heartbeat',help='Renew the live run ID lease; no parent PID dependence');heartbeat.add_argument('run_id')
    finish=actions.add_parser('finish',help='Close a live run; unresolved reservations stay uncertain');finish.add_argument('run_id');finish.add_argument('--status',choices=['completed','partial','blocked','failed'],required=True);finish.add_argument('--note',default='')
    note=actions.add_parser('note',help='Append a short safe posting outcome; submitted claims require a receipt');note.add_argument('run_id');note.add_argument('--job-id',type=int,required=True);note.add_argument('--outcome',choices=sorted(OUTCOMES),required=True);note.add_argument('--reason',required=True);note.add_argument('--source-url',default='')
    summary=actions.add_parser('summary',help='Ledger-derived safe counts and chronological events');summary.add_argument('run_id',nargs='?')
    begin=actions.add_parser('begin-submit',help='Mandatory durable reservation BEFORE one external browser submit click');begin.add_argument('run_id');begin.add_argument('attempt_id')
    phones=begin.add_mutually_exclusive_group(required=True)
    phones.add_argument('--phone-required',dest='phone_required',action='store_true')
    phones.add_argument('--phone-not-required',dest='phone_required',action='store_false')
    uncertain=actions.add_parser('uncertain',help='After click without confirmation: keep posting locked, never retry');uncertain.add_argument('run_id');uncertain.add_argument('attempt_id');uncertain.add_argument('--reason',required=True)


def dispatch(store,args):
    daily=Daily(store);command=args.daily_command
    if command=='configure':
        changes={k:getattr(args,k) for k in ('cron_job_id','schedule','timezone','max_submissions_per_day') if getattr(args,k) is not None}
        return daily.configure(enabled=args.enabled=='true',**changes)
    if command=='verify-job': return daily.verify_job(args.job_id,json.loads(fs.read_bytes(args.evidence,max_bytes=16000)))
    if command=='status': return daily.status()
    if command=='start': return daily.start(args.owner)
    if command=='heartbeat': return daily.heartbeat(args.run_id)
    if command=='finish': return daily.finish(args.run_id,args.status,args.note)
    if command=='note': return daily.note(args.run_id,args.job_id,args.outcome,args.reason,args.source_url)
    if command=='summary': return daily.summary(args.run_id)
    if command=='begin-submit': return daily.begin_submit(args.run_id,args.attempt_id,phone_required=args.phone_required)
    if command=='uncertain': return daily.uncertain(args.run_id,args.attempt_id,args.reason)
    raise ValueError('Unknown daily action')
