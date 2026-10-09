"""Generic importer for a sectioned text PDF. The PDF is the sole resume authority."""
import hashlib
import json
import re
from pathlib import Path
import fitz
from personal_jobby.store import private_write, now
from personal_jobby import private_fs as fs

DATE = r'[A-Za-z]{3} \d{4} [–-] (?:[A-Za-z]{3} \d{4}|Present)'
HEADINGS = {'experience':'EXPERIENCE','selected projects':'PROJECTS','projects':'PROJECTS','technical skills':'TECHNICAL SKILLS','education':'EDUCATION'}


def extract(pdf_path):
    pdf_path=fs.absolute(pdf_path)
    with fitz.open(stream=fs.read_bytes(pdf_path),filetype="pdf") as document:
        text='\n'.join(p.get_text() for p in document)
        pages=[{'lines':[(line['bbox'],' '.join(span['text'] for span in line['spans'])) for block in page.get_text('dict')['blocks'] for line in block.get('lines',[])],'links':page.get_links()} for page in document]
    rows=[r.strip() for r in text.splitlines() if r.strip()]
    if len(rows)<3: raise ValueError('PDF has no usable text')
    name=rows[0]
    # Phone is deliberately not imported from a PDF. Only secure direct entry saves it.
    parts=[p.strip() for p in rows[1].split('|')]
    contact=' | '.join(p for p in parts if not re.search(r'\d[\d ()+.-]{6,}\d',p))
    links=[]
    for part in parts:
        if re.search(r'(?:github|linkedin)\.com/',part,re.I):
            url=part if part.startswith(('http://','https://')) else 'https://'+part
            links.append(dict(label='GitHub' if 'github.com' in part.lower() else 'LinkedIn',url=url))
    sections={};section=None
    for row in rows[2:]:
        if row.lower() in HEADINGS: section=HEADINGS[row.lower()];sections[section]=[]
        elif section: sections[section].append(row)
    if not all(k in sections for k in ('EXPERIENCE','PROJECTS','TECHNICAL SKILLS','EDUCATION')): raise ValueError('Expected resume section headings missing')
    facts=[]
    def add(section,group,date,body,excerpt,**extra):
        facts.append(dict(id=section.lower().replace(' ','-')+'-'+str(len(facts)+1),section=section,group=group,date=date,text=body,source=str(pdf_path),excerpt=excerpt,**extra))
    exp=sections['EXPERIENCE'];i=0
    while i<len(exp):
        if i+3>=len(exp) or not re.fullmatch(DATE,exp[i+3]): raise ValueError('Unsupported employment heading layout')
        employer,location,role,date=exp[i:i+4];i+=4;bullets=[]
        while i<len(exp):
            if i+3<len(exp) and re.fullmatch(DATE,exp[i+3]): break
            line=exp[i];i+=1
            if line.startswith('•'): bullets.append([line.removeprefix('•').strip()])
            elif bullets: bullets[-1].append(line)
            else: raise ValueError('Employment evidence must be a bullet')
        for bullet in bullets: add('EXPERIENCE',employer+' | '+role,date,' '.join(bullet),'\n'.join(bullet),employer=employer,role=role,location=location)
    projects=[]
    for line in sections['PROJECTS']:
        if ':' in line and not line.startswith('•'): projects.append([line])
        elif projects: projects[-1].append(line)
        else: raise ValueError('Unsupported project layout')
    def associated_link(title,next_title):
        anchors=[(page,rect) for page in pages for rect,line in page['lines'] if line.strip().startswith(title+':')]
        if len(anchors)!=1: return ''
        page,rect=anchors[0];stop=min((r[1] for r,line in page['lines'] if r[1]>rect[1] and (line.strip().lower() in HEADINGS or (next_title and line.strip().startswith(next_title+':')))),default=100000)
        uris={link.get('uri','') for link in page['links'] if rect[1]-3<=link['from'].y0<stop and 'github.com/' in link.get('uri','')}
        return next(iter(uris)) if len(uris)==1 else ''
    for i,project in enumerate(projects):
        joined=' '.join(project);title,body=joined.split(':',1)
        add('PROJECTS',title,'',body.strip(),'\n'.join(project),link=associated_link(title,projects[i+1][0].split(':',1)[0] if i+1<len(projects) else None))
    skills=[]
    for line in sections['TECHNICAL SKILLS']:
        if ':' in line: skills.append([line])
        elif skills: skills[-1].append(line)
        else: raise ValueError('Unsupported skill layout')
    for skill in skills:
        label,body=' '.join(skill).split(':',1);add('TECHNICAL SKILLS',label,'',body.strip(),'\n'.join(skill))
    for line in sections['EDUCATION']:
        values=[s.strip() for s in line.split('|')]
        if len(values)!=3: raise ValueError('Unsupported education layout')
        add('EDUCATION',values[0],values[2],values[1],line)
    return dict(name=name,contact=contact,links=links,answers={'phone':'','work_eligibility':''},facts=facts,source_hashes={str(pdf_path):hashlib.sha256(fs.read_bytes(pdf_path)).hexdigest()},imported_at=now())


def initialize(store,pdf,replace=False):
    with store.profile_lock(): return _initialize(store,pdf,replace)

def _initialize(store,pdf,replace=False):
    profile=extract(pdf);path=store.root/'candidate.json';backup=False
    if path.exists():
        if not replace: raise ValueError('Candidate exists; use explicit --replace migration')
        old=store.profile();profile['answers']=old.get('answers',{});profile['answer_provenance']=old.get('answer_provenance',{})
        folder=store.root/'backups';fs.mkdir(folder)
        private_write(folder/('candidate-'+now().replace(':','-')+'.json'),fs.read_text(path));backup=True
    invalidated=0;artifacts=store.root/'artifacts'
    if artifacts.exists():
        # Archive complete old materials privately; remove all live artifact paths.
        folder=store.root/'backups';fs.mkdir(folder)
        invalidated=sum(1 for _ in artifacts.glob('*/metadata.json'))
        fs.check_tree(artifacts);fs.move(artifacts,folder/('artifacts-'+now().replace(':','-')))
    private_write(path,json.dumps(profile,indent=2))
    with store.connect() as c:
        for row in c.execute('SELECT id,status FROM jobs').fetchall():
            if row['status']=='materials_ready': c.execute("UPDATE jobs SET status='needs_review',updated=? WHERE id=?",(now(),row['id']))
            store.event(c,row['id'],'candidate_source_migrated',dict(source_hashes=profile['source_hashes'],materials_invalidated=True))
    return dict(fact_count=len(profile['facts']),source_hashes=profile['source_hashes'],backup_created=backup,materials_invalidated=invalidated,phone_present=bool(profile.get('answers',{}).get('phone')))
