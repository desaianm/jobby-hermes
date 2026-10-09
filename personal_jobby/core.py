import math
import re
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, ConfigDict, field_validator

DEFAULTS = dict(minimum=120000, target_terms=['AI Engineer','LLM','AI Agent','Applied AI','Machine Learning','ML Engineer','AI Platform','MLOps'], locations=['Toronto/GTA hybrid','Canada remote'], blacklist=[], criteria_confirmed=False, submission_desired=True, provenance='PROVISIONAL user example; annual CAD base; Toronto/GTA hybrid and Canada remote')


def exact_evidence(value):
    from personal_jobby.privacy import sanitize_text
    if sanitize_text(value)!=value or '[private credential]' in value or '[private phone]' in value:
        raise ValueError('Exact public evidence must be free of private data; supply a clean source excerpt')
    return value

class Salary(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    raw: str = Field(default='', max_length=2000)
    source_url: str = Field(default='', max_length=2000)
    origin: str = Field(default='unknown', pattern='^(employer|aggregator|estimate|unknown)$')
    currency: str | None = Field(default=None, max_length=8)
    unit: str | None = Field(default=None, max_length=30)
    kind: str | None = Field(default=None, max_length=30)
    lower: float | None = Field(default=None, ge=0)
    upper: float | None = Field(default=None, ge=0)
    verified: bool = False
    _exact_raw = field_validator('raw')(exact_evidence)
    @field_validator('source_url')
    @classmethod
    def url(cls,v):
        return public_url(v) if v else v


def public_url(v):
    import ipaddress
    p=urlsplit(v)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password: raise ValueError('Public HTTP(S) URL required')
    if p.hostname.lower() in ('localhost',) or '.' not in p.hostname: raise ValueError('Public URL required')
    try:
        if not ipaddress.ip_address(p.hostname).is_global: raise ValueError('Public URL required')
    except ValueError as e:
        if str(e)=='Public URL required': raise
    return v

class Job(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1,max_length=250)
    company: str = Field(min_length=1,max_length=250)
    requisition: str = Field(default='',max_length=250)
    location: str = Field(default='',max_length=500)
    job_url: str = Field(max_length=2000)
    description: str = Field(min_length=1,max_length=60000)
    employment_type: str = Field(default='unknown', pattern='^(unknown|permanent_full_time|contract|temporary|part_time)$')
    employment_evidence: str = Field(default='',max_length=2000)
    arrangement: str = Field(default='unknown', pattern='^(unknown|hybrid|remote|onsite)$')
    arrangement_evidence: str = Field(default='', max_length=2000)
    qualifications_reviewed: bool = False
    qualification_review_note: str = Field(default='',max_length=2000)
    original_source: dict = Field(default_factory=dict)
    salary: Salary = Field(default_factory=Salary)
    _exact_fit = field_validator('arrangement_evidence','employment_evidence')(exact_evidence)
    @field_validator('original_source')
    @classmethod
    def source_bounds(cls,v):
        import json
        if len(json.dumps(v))>65000: raise ValueError('Source snapshot too large')
        return v
    @field_validator('job_url')
    @classmethod
    def url(cls,v): return public_url(v)

class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    employment_policy: str = Field(default='permanent_full_time_only',pattern='^permanent_full_time_only$')
    minimum: float = Field(ge=0,le=10000000,allow_inf_nan=False)
    target_terms: list[str] = Field(min_length=1,max_length=30)
    locations: list[str] = Field(min_length=1,max_length=30)
    blacklist: list[str] = Field(max_length=100)
    criteria_confirmed: bool = False
    submission_desired: bool = True
    @field_validator('target_terms','locations','blacklist')
    @classmethod
    def bounded(cls,v):
        if any(not x.strip() or len(x)>200 for x in v): raise ValueError('Terms must be 1–200 characters')
        return v



def _structured_base_bounds(raw):
    """Accept only an exact baseSalary excerpt, never search arbitrary JSON."""
    import json
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate evidence key')
            result[key] = value
        return result
    obj = json.loads(raw, object_pairs_hook=unique,
                     parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite evidence')))
    if not isinstance(obj, dict): raise ValueError('Salary object required')
    if 'baseSalary' in obj:
        if set(obj) - {'baseSalary', '@type', '@context'}: raise ValueError('Mixed evidence')
        if '@type' in obj and obj['@type'] != 'JobPosting': raise ValueError('JobPosting required')
        if '@context' in obj and obj['@context'] not in ('https://schema.org', 'http://schema.org'): raise ValueError('Invalid context')
        obj = obj['baseSalary']
    # The existing employer/verified/kind=base gate supplies base context for a bare excerpt.
    if not isinstance(obj, dict) or set(obj) != {'@type', 'currency', 'value'} or obj['@type'] != 'MonetaryAmount' or obj['currency'] != 'CAD':
        raise ValueError('Exact CAD MonetaryAmount required')
    value = obj['value']
    if not isinstance(value, dict) or value.get('@type') != 'QuantitativeValue' or value.get('unitText') != 'YEAR': raise ValueError('Annual quantity required')
    if set(value) == {'@type', 'unitText', 'minValue', 'maxValue'}:
        low, high = value['minValue'], value['maxValue']
    elif set(value) == {'@type', 'unitText', 'value'}:
        low = high = value['value']
    else: raise ValueError('Exact range or fixed quantity required')
    if any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in (low, high)) or low > high: raise ValueError('Invalid bounds')
    return low, high


def salary_decision(s,floor):
    low,high=s.get('lower'),s.get('upper')
    if any(x is not None and (not math.isfinite(x) or x<0) for x in (low,high)): return 'needs_review','Non-finite or invalid salary'
    if (not s.get('raw') or s.get('origin')!='employer' or not s.get('verified',False) or not s.get('source_url') or s.get('currency')!='CAD' or s.get('unit')!='annual' or s.get('kind')!='base'): return 'needs_review','Verify exact employer-posted CAD annual base salary'
    try: public_url(s['source_url'])
    except ValueError: return 'needs_review','Public employer salary evidence URL required'
    structured_raw = s['raw'].lstrip()
    prefix = 'JobPosting.baseSalary:'
    labelled = structured_raw.startswith(prefix) and structured_raw[len(prefix):len(prefix)+1].isspace()
    if labelled:
        structured_raw = structured_raw[len(prefix):].lstrip()
    if labelled or structured_raw.startswith(('{', '[')):
        try: source_low, source_high = _structured_base_bounds(structured_raw)
        except (ValueError, TypeError, OverflowError): return 'needs_review','Exact structured CAD YEAR baseSalary evidence required'
        if low != source_low or (high != source_high and not (source_low == source_high and high is None)):
            return 'needs_review','Entered bounds do not match structured baseSalary'
    else:
        raw=s['raw'].lower()
        if re.search(r'\b(?:monthly|weekly|biweekly|daily|hourly)\b|(?:\bper\s+|/\s*)(?:month|week|day|hour|mo|wk|hr)\b',raw): return 'needs_review','Nonannual salary period conflicts with annual metadata'
        if not re.search(r'\bcad\b|c\$|canadian dollars',raw) or re.search(r'\busd\b|estimate|total compensation|\btc\b|hourly|per hour',raw): return 'needs_review','Raw salary must explicitly support CAD base; estimates/TC/hourly held'
        if re.search(r'up to|at most|maximum|bonus|on.target|us\$',raw): return 'needs_review','Upper-only or mixed compensation excerpt requires review'
        number=r'(\d[\d,]*(?:\.\d+)?)\s*(k)?'
        tokens=list(re.finditer(number,raw))
        if len(tokens) not in (1,2): return 'needs_review','Ambiguous salary excerpt; provide exact base range only'
        def amount(match,inherit=False): return float(match[1].replace(',',''))*(1000 if match[2] or inherit else 1)
        if len(tokens)==2:
            between=raw[tokens[0].end():tokens[1].start()]
            if not re.fullmatch(r'\s*(?:[–—-]|to)\s*(?:(?:cad|c\$|\$)\s*)?',between): return 'needs_review','Salary range separator ambiguous'
            source_low=amount(tokens[0],bool(tokens[1][2] and not tokens[0][2]));source_high=amount(tokens[1])
            if low!=source_low or high!=source_high: return 'needs_review','Entered lower/upper bounds do not match complete ordered raw range'
        elif low!=amount(tokens[0]) or high not in (None,low): return 'needs_review','Entered bounds do not match fixed posted salary'
    if low is None or (high is not None and high<low): return 'needs_review','Missing or invalid lower bound'
    if high is not None and high<floor: return 'excluded','Entire base range below floor'
    if low<floor: return ('excluded','Explicit base salary below floor') if high is None else ('needs_review','Range overlaps floor')
    return 'eligible','Verified employer CAD annual base lower bound meets floor'


GTA = {'toronto','north york','scarborough','etobicoke','east york','york region','mississauga','brampton','markham','vaughan','richmond hill','oakville','burlington','milton','halton hills','ajax','pickering','whitby','oshawa','clarington','uxbridge','scugog','brock','aurora','newmarket','east gwillimbury','georgina','king','caledon','greater toronto area','gta'}


def location_fit(job,settings):
    loc=job.get('location','').lower(); arrangement=job.get('arrangement','unknown')
    evidence=job.get('arrangement_evidence','').strip().lower()
    listing=(loc+' '+job['description'].lower())
    if not loc or not evidence or evidence not in listing: return False
    policies=[p.lower() for p in settings['locations']]
    if arrangement in ('hybrid','remote'):
        mode=re.escape(arrangement)
        if re.search(r'\b(?:not|no|non)[ -]+(?:a\s+)?'+mode+r'\b|\b'+mode+r'\b[^.;\n]{0,60}\b(?:not|never)\s+(?:available|allowed|offered|permitted|supported)\b|\b(?:on[ -]?site|in[ -]?office)\s+only\b',listing): return False
    if arrangement=='hybrid' and re.search(r'\bhybrid\b',evidence):
        in_gta=any(re.search(r'(?<!\w)'+re.escape(t)+r'(?!\w)',loc) for t in GTA)
        return in_gta and 'toronto/gta hybrid' in policies
    if arrangement=='remote' and re.search(r'\bremote\b',evidence):
        return bool(re.search(r'\bcanada\b|\bcanadian\b',loc+' '+evidence)) and not re.search(r'usa only|us only|united states only',evidence) and 'canada remote' in policies
    return False


def experience_years(profile):
    from datetime import datetime, timezone
    current=datetime.now(timezone.utc); intervals=[]
    for f in profile.get('facts',[]):
        if f.get('section')!='EXPERIENCE': continue
        m=re.fullmatch(r'([A-Za-z]{3} \d{4}) [–-] ([A-Za-z]{3} \d{4}|Present)',f.get('date',''))
        if not m: continue
        start=datetime.strptime(m[1],'%b %Y'); end=current if m[2]=='Present' else datetime.strptime(m[2],'%b %Y')
        intervals.append((start.year*12+start.month,end.year*12+end.month))
    merged=[]
    for start,end in sorted(set(intervals)):
        if merged and start<=merged[-1][1]: merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else: merged.append((start,end))
    return sum(max(0,b-a) for a,b in merged)/12


def qualification_gaps(job,profile):
    text=job['description'].lower(); gaps=[]
    # Conservative: experience mentions are held unless explicitly preferred.
    for sentence in re.split(r'\n|;|\.(?=\s|$)',text):
        if re.search(r'preferred|nice to have|asset|bonus',sentence) and not re.search(r'required|must|minimum',sentence): continue
        for m in re.finditer(r'(\d{1,2})(?:\s*[–-]\s*\d{1,2})?\s*\+?\s*years?\b',sentence):
            required=int(m[1]); available=experience_years(profile or {})
            if re.search(r'\b(?:of|with|in)\s+\w+|years?\s*[’\']?\s+\w+\s+experience',sentence[m.end():]) or re.search(r'\d+\s+years?\s+of\b',sentence): gaps.append('Required skill-specific duration needs dated source-grounded review; total tenure is insufficient')
            if available<required: gaps.append(f'Required {required} years; source-dated employment demonstrates approximately {available:.1f} years; review requirement')
    evidence=' '.join(f['text']+' '+f.get('group','') for f in (profile or {}).get('facts',[])).lower()
    required_section=False
    for sentence in re.split(r'\n|;|\.(?=\s|$)',text):
        if re.search(r'preferred|nice to have|bonus',sentence) and not re.search(r'required|must|minimum',sentence): continue
        if re.search(r'required|requirements|qualifications|must have',sentence): required_section=True
        if not required_section: continue
        for pattern,label in [(r'ph\.?d|doctorate','PhD'),(r"master[’']?s|msc|m\.sc",'masters'),(r'certif(?:ication|ied)','certification')]:
            if re.search(pattern,sentence) and not re.search(pattern,evidence): gaps.append('Required qualification not demonstrated: '+label)
        for skill in ('c++','rust','scala','swift','kotlin','reinforcement learning','bert','qwen','security clearance','french'):
            if skill in sentence and skill not in evidence: gaps.append('Required qualification not demonstrated: '+skill)
    return list(dict.fromkeys(gaps))


def normalize_employer(name):
    name=re.sub(r'[^a-z0-9 ]',' ',name.casefold())
    return re.sub(r'(?:\s+(?:inc|incorporated|corp|corporation|ltd|limited|llc|co))+\s*$','',re.sub(r'\s+',' ',name).strip()).strip()


def assess(job,settings,profile=None):
    state,reason=salary_decision(job['salary'],settings['minimum']); reasons=[reason]; reviews=[]
    if not any(re.search(r'(?<!\w)'+re.escape(t.lower())+r'(?!\w)',job['title'].lower()) for t in settings['target_terms']): reviews.append('Role fit unconfirmed')
    if not location_fit(job,settings): reviews.append('Location/arrangement unconfirmed: require evidenced GTA hybrid or Canada remote; onsite held')
    reviews.extend(qualification_gaps(job,profile))
    if re.search(r'requir(?:ed|ements)|qualifications|must have',job['description'],re.I) and (not job.get('qualifications_reviewed') or not job.get('qualification_review_note','').strip()): reviews.append('Required qualifications need explicit source-grounded human review')
    if reviews and state!='excluded': state='needs_review'
    employment=job.get('employment_type','unknown')
    employment_evidence=job.get('employment_evidence','').strip().lower()
    if employment in ('contract','temporary','part_time'):
        state='excluded';reasons.append('Excluded: permanent full-time only')
    elif re.search(r'\b(?:not|no|non)[ -]+(?:(?:a|an|the)\s+)?(?:permanent|full[ -]time)\b|\b(?:permanent|full[ -]time)\b[^.;\n]{0,60}\b(?:not|never)\s+(?:available|allowed|offered|permitted|supported)\b|\b(?:contract|temporary|fixed.term|part.time)\s+(?:role|position|employment|job)|(?:role|position|employment|job)\s+(?:is\s+)?(?:a\s+)?(?:contract|temporary)',job['description']+'\n'+job['location'],re.I):
        if state!='excluded': state='needs_review'
        reviews.append('Negated or contradictory permanent full-time evidence')
    elif employment!='permanent_full_time' or not employment_evidence or employment_evidence not in job['description'].lower()+' '+job['location'].lower() or not re.search(r'permanent',employment_evidence) or not re.search(r'full[ -]time',employment_evidence):
        if state!='excluded': state='needs_review'
        reviews.append('Permanent full-time employment evidence required')
    reasons.extend(reviews)
    employer=normalize_employer(job['company'])
    current={normalize_employer(f.get('employer') or f.get('group','').split('|')[0]) for f in (profile or {}).get('facts',[]) if f.get('section')=='EXPERIENCE' and re.search(r'\bPresent\b',f.get('date',''),re.I)}
    if employer in current: state='excluded';reasons.append('Excluded current employer from dated candidate facts')
    if employer in {normalize_employer(t) for t in settings['blacklist']}: state='excluded';reasons.append('Blacklisted employer')
    return state,reasons


def select_facts(profile,job):
    words=set(re.findall(r'[a-z0-9]+',job['title'].lower()+' '+job['description'].lower()))
    scored=[]
    for f in profile['facts']:
        overlap=words & set(re.findall(r'[a-z0-9]+',f['text'].lower()))-{'the','a','and','for','in','of','to','with','built','using'}
        scored.append((len(overlap),f['id']))
    ids=[i for _,i in sorted(scored,key=lambda x:(-x[0],x[1]))]
    from personal_jobby.wording import tailor
    tailoring=[tailor(f,job['title']+' '+job['description']) for f in profile['facts']]
    return dict(mode='truthful deterministic',selection_mode='source facts with bounded equivalent wording',tailoring=tailoring,selected_fact_ids=ids,evidence=[dict(fact_id=i,classification='demonstrated' if n else 'adjacent',source=next(f['source'] for f in profile['facts'] if f['id']==i)) for n,i in scored],gaps=sorted(words & {'bert','qwen','reinforcement','certification','gpt-4'}))
