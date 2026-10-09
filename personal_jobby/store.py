import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from personal_jobby.core import DEFAULTS, Job, assess
from personal_jobby import private_fs as fs
from threading import RLock

ROOT=Path(os.environ.get('JOBBY_ROOT', str(Path.home()/'.local/share/jobby-personal')))
STATUSES={'discovered','needs_review','eligible','materials_ready','submission_pending','applied','interview','rejected','offer','archived'}

def canonical_url(url):
    """Comparison key only: retain original URLs and meaningful job query parameters."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    from personal_jobby.core import public_url
    public_url(url)
    parts=urlsplit(url)
    query=[(k,v) for k,v in parse_qsl(parts.query,keep_blank_values=True) if not (k.lower().startswith('utm_') or k.lower() in {'gh_src','lever-source','source','src'})]
    return urlunsplit((parts.scheme.lower(),parts.netloc.lower(),parts.path.rstrip('/'),urlencode(sorted(query,key=lambda pair:pair[0])),''))


def now(): return datetime.now(timezone.utc).isoformat()
def private_write(path,data): fs.write_text(path,data)

class Store:
    def __init__(self,root=ROOT):
        if not Path(root).is_absolute(): raise ValueError('JOBBY_ROOT must be an absolute private path')
        self.root=fs.absolute(root); fs.mkdir(self.root);self.lock=RLock()
        os.umask(0o077)
        self.db=self.root/'workspace.sqlite'
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, url TEXT UNIQUE, reqkey TEXT UNIQUE, data TEXT, status TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS application_attempts(id TEXT PRIMARY KEY,job_id INTEGER NOT NULL,created TEXT NOT NULL,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS application_attempt_events(id INTEGER PRIMARY KEY,attempt_id TEXT NOT NULL,at TEXT NOT NULL,kind TEXT NOT NULL,data TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS immutable_attempt_update BEFORE UPDATE ON application_attempts BEGIN SELECT RAISE(ABORT,'append only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_attempt_delete BEFORE DELETE ON application_attempts BEGIN SELECT RAISE(ABORT,'append only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_attempt_event_update BEFORE UPDATE ON application_attempt_events BEGIN SELECT RAISE(ABORT,'append only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_attempt_event_delete BEFORE DELETE ON application_attempt_events BEGIN SELECT RAISE(ABORT,'append only'); END;
CREATE TABLE IF NOT EXISTS job_aliases(url TEXT PRIMARY KEY,job_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, job_id INTEGER, at TEXT, kind TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT);
CREATE TRIGGER IF NOT EXISTS immutable_events_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_events_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append only'); END;''')
            from personal_jobby.daily import SCHEMA
            c.executescript(SCHEMA)
            c.execute('INSERT OR IGNORE INTO settings VALUES(1,?)',(json.dumps(DEFAULTS),))
            for row in c.execute('SELECT url,job_id FROM job_aliases').fetchall():
                c.execute('INSERT OR IGNORE INTO job_aliases VALUES(?,?)',(canonical_url(row['url']),row['job_id']))
            for row in c.execute('SELECT id,data FROM jobs').fetchall():
                for alias in self.aliases(json.loads(row['data'])): c.execute('INSERT OR IGNORE INTO job_aliases VALUES(?,?)',(alias,row['id']))
        fs.chmod(self.db)
    def connect(self):
        for p in (self.db,Path(str(self.db)+'-wal'),Path(str(self.db)+'-shm'),Path(str(self.db)+'-journal')): fs.check(p)
        c=sqlite3.connect(self.db,timeout=10); c.row_factory=sqlite3.Row
        c.execute('PRAGMA busy_timeout=10000'); c.execute('PRAGMA journal_mode=WAL'); return c
    def settings(self):
        with self.connect() as c: return json.loads(c.execute('SELECT data FROM settings').fetchone()[0])
    def save_settings(self,data):
        data={**self.redact(data),'defaults_provenance':DEFAULTS['provenance'],'provenance':'User-confirmed settings '+now() if data['criteria_confirmed'] else DEFAULTS['provenance']}
        with self.connect() as c: c.execute('UPDATE settings SET data=?',(json.dumps(data),))
        return data
    def profile(self):
        p=self.root/'candidate.json'
        return json.loads(fs.read_text(p)) if p.exists() else dict(facts=[],answers={},name='',contact='')
    def redact(self,data):
        from personal_jobby.privacy import sanitize
        return sanitize(data)
    def public_profile(self):
        return self.redact(self.profile())
    def save_answers(self,data):
        with self.lock,self.profile_lock():
            p=self.profile();p['answers']={**p.get('answers',{}),**self.redact(data)}
            private_write(self.root/'candidate.json',json.dumps(p,indent=2))
    def save_phone(self,phone='',clear=False):
        with self.lock,self.profile_lock():
            return self._save_phone(phone,clear)
    def _save_phone(self,phone,clear):
        if clear:
            p=self.profile();p.setdefault('answers',{})['phone']='';private_write(self.root/'candidate.json',json.dumps(p,indent=2))
        elif phone.strip():
            import re
            if not re.fullmatch(r'[+0-9() .-]{7,40}',phone) or len(re.sub(r'\D','',phone))<7: raise ValueError('Phone format invalid')
            p=self.profile();p.setdefault('answers',{})['phone']=phone.strip();private_write(self.root/'candidate.json',json.dumps(p,indent=2))
        return {'phone_present':bool(self.profile().get('answers',{}).get('phone'))}
    def event(self,c,id,kind,data):
        data=self.redact(data)
        c.execute('INSERT INTO events(job_id,at,kind,data) VALUES(?,?,?,?)',(id,now(),kind,json.dumps(data)))
    def aliases(self,data):
        from personal_jobby.core import public_url
        urls=[data['job_url'],data.get('original_source',{}).get('job_url_direct','')]
        result=[]
        for url in urls:
            if not isinstance(url,str) or not url: continue
            try: public_url(url)
            except ValueError: continue
            result.extend([url.split('#')[0].rstrip('/'),canonical_url(url)])
        return result
    def add(self,data):
        Job.model_validate(data)  # Validate exact evidence before privacy filtration.
        filtered=self.redact(data)
        if filtered!=data:
            from personal_jobby.artifacts import digest
            filtered['original_source']={**filtered.get('original_source',{}),'privacy_filtration':dict(input_sha256=digest(data),raw_retained=False,snapshot='filtered; not exact source evidence')}
        data=Job.model_validate(filtered).model_dump(); url=data['job_url'].split('#')[0].rstrip('/'); req=(data['company'].casefold()+':'+data['requisition'].casefold()) if data['requisition'] else None
        state,_=assess(data,self.settings(),self.profile())
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            for alias in self.aliases(data):
                existing=c.execute('SELECT job_id FROM job_aliases WHERE url=?',(alias,)).fetchone()
                if existing:
                    for added in self.aliases(data): c.execute('INSERT OR IGNORE INTO job_aliases VALUES(?,?)',(added,existing[0]))
                    if data!=self.job_snapshot(existing[0]): self.event(c,existing[0],'source_alias_observed',data)
                    return self.get(existing[0])
            row=c.execute('SELECT id FROM jobs WHERE url=? OR reqkey=?',(url,req)).fetchone()
            if row:
                for added in self.aliases(data): c.execute('INSERT OR IGNORE INTO job_aliases VALUES(?,?)',(added,row[0]))
                if data!=self.job_snapshot(row[0]): self.event(c,row[0],'source_alias_observed',data)
                return self.get(row[0])
            cur=c.execute('INSERT INTO jobs(url,reqkey,data,status,created,updated) VALUES(?,?,?,?,?,?)',(url,req,json.dumps(data),state,now(),now())); id=cur.lastrowid
            for alias in self.aliases(data): c.execute('INSERT OR IGNORE INTO job_aliases VALUES(?,?)',(alias,id))
            self.event(c,id,'discovered',data)
        return self.get(id)
    def job_snapshot(self,id):
        with self.connect() as c: row=c.execute('SELECT data FROM jobs WHERE id=?',(id,)).fetchone()
        if not row: raise KeyError('Job not found')
        return Job.model_validate(json.loads(row[0])).model_dump()
    def artifact_dir(self,id):
        from personal_jobby.artifacts import artifact_dir
        return artifact_dir(self,id)
    def materials(self,id):
        from personal_jobby.artifacts import load
        return load(self,id)
    def profile_lock(self): return fs.lock(self.root/'answers.lock')
    def get(self,id):
        with self.connect() as c: r=c.execute('SELECT * FROM jobs WHERE id=?',(id,)).fetchone()
        if not r: raise KeyError('Job not found')
        d={**json.loads(r['data']),**{k:r[k] for k in ('id','status','created','updated')}}
        from personal_jobby.audit import list_attempts
        d['attempts']=list_attempts(self,id)
        d['submitted_at']=next((a['submitted_at'] for a in reversed(d['attempts']) if a.get('submitted_at')),None)
        d['materials']=self.materials(id)
        d['eligibility'],d['explanation']=assess(d,self.settings(),self.profile()); d['blockers']=self.blockers(d)
        return d
    def jobs(self):
        with self.connect() as c: ids=[r[0] for r in c.execute('SELECT id FROM jobs ORDER BY id DESC')]
        return [self.get(i) for i in ids]
    def blockers(self,j):
        from personal_jobby.daily import Daily
        p=self.profile(); s=self.settings();policy=Daily(self).policy()
        b=[]
        if not policy['cron_job_id']: b.append('Browser submission adapter unavailable; daily pilot not configured')
        elif not policy['enabled']: b.append('External Hermes cron pilot disabled')
        if not s['submission_desired']: b.append('Submission intent disabled (kill switch)')
        if j['status']=='submission_pending': b.append('Submission pending or uncertain; never automatically retry')
        if not s['criteria_confirmed']: b.append('Provisional search criteria unconfirmed')
        for k in ('work_eligibility',):
            if not p.get('answers',{}).get(k): b.append('Candidate answer missing: '+k)
        if j['eligibility']!='eligible': b.extend(j['explanation'])
        meta=j.get('materials')
        if not meta: b.append('Documents not prepared')
        elif meta.get('qa_state') in ('stale','invalidated'): b.append(meta.get('reason','Documents source changed; regenerate'))
        elif meta.get('qa_state')!='visual_approved': b.append('Documents pending external visual review')
        return b
    def transition(self,id,status):
        if status not in STATUSES or status=='applied': raise ValueError('Applied requires receipt; invalid status')
        j=self.get(id)
        if status in ('eligible','materials_ready','submission_pending'): raise ValueError('Computed states cannot be assigned manually')
        with self.connect() as c:
            c.execute('UPDATE jobs SET status=?,updated=? WHERE id=?',(status,now(),id)); self.event(c,id,'status',{'status':status})
        return self.get(id)
    def receipt(self,id,text='',timestamp='',url='',attempt_id=None):
        from personal_jobby.audit import record_receipt
        return record_receipt(self,id,text,timestamp,url,attempt_id)
    def events(self,id):
        self.get(id)
        with self.connect() as c: return [dict(r) for r in c.execute('SELECT * FROM events WHERE job_id=? ORDER BY id',(id,))]
