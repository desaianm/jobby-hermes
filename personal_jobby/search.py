import math
import hashlib
import json
import re
import logging
import threading
import sys
import unicodedata
from contextlib import contextmanager
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, ValidationInfo
from personal_jobby.core import public_url
from personal_jobby.privacy import sanitize_text


_PROVIDER_LOCK = threading.RLock()


@contextmanager
def _provider_diagnostics():
    """Suppress JobSpy's raw diagnostics before its independent handlers see them.

    Current JobSpy creates child loggers in workers and configures a precreated
    handler during scrape_jobs. Filter handlers too: ancestor logger filters do
    not see propagated records. Serialize calls so nested and worker output stays
    covered until the factory has returned.
    """
    with _PROVIDER_LOCK:
        provider = logging.getLogger('jobspy')
        loggers = [provider] + [logger for logger in list(logging.root.manager.loggerDict.values())
                                if isinstance(logger, logging.Logger) and logger is not provider
                                and (logger.name.startswith('jobspy.') or logger.name.startswith('JobSpy:'))]
        states = [(logger, logger.level, tuple(logger.handlers), logger.propagate) for logger in loggers]
        handlers = list(logging.root.handlers)
        for logger in loggers:
            handlers.extend(logger.handlers)
        # JobSpy 1.4.1 may add this existing handler only after the guard starts.
        util = sys.modules.get('jobspy.util')
        if util is not None and isinstance(getattr(util, 'log_handler', None), logging.Handler):
            handlers.append(util.log_handler)
        handlers = list(dict.fromkeys(handlers))
        def allow(record):
            return not (record.name == 'jobspy' or record.name.startswith('jobspy.')
                        or record.name.startswith('JobSpy:'))
        try:
            for logger in loggers: logger.addFilter(allow)
            for handler in handlers: handler.addFilter(allow)
            yield
        finally:
            for handler in handlers: handler.removeFilter(allow)
            for logger, level, original_handlers, propagate in states:
                logger.removeFilter(allow)
                logger.handlers[:] = original_handlers
                logger.setLevel(level)
                logger.propagate = propagate


# Preserve normalization of earlier Canadian inputs; this is not a geocoder.
PROVINCES = dict(AB='Alberta', BC='British Columbia', MB='Manitoba', NB='New Brunswick',
                NL='Newfoundland and Labrador', NS='Nova Scotia', NT='Northwest Territories',
                NU='Nunavut', ON='Ontario', PE='Prince Edward Island', QC='Quebec',
                SK='Saskatchewan', YT='Yukon')
SEARCH_CITIES = (('Ottawa', 'ON'), ('Toronto', 'ON'), ('London', 'ON'),
                 ('Vancouver', 'BC'), ('Montreal', 'QC'))


def supported_countries():
    """Indeed requires a mapped country; LinkedIn uses the qualified location."""
    from jobspy.model import Country
    from jobspy.indeed.constant import country_codes
    return sorted(country.value.upper() if country.value in ('usa', 'uk') else country.value.title()
                  for country in Country if country in country_codes)


class SearchLocation(BaseModel):
    """Bounded public place names, separate from residence or legal eligibility."""
    model_config = ConfigDict(extra='forbid', strict=True, hide_input_in_errors=True)
    country: str = Field(min_length=1, max_length=80, description='Provider-supported country; inspect supported_countries for canonical choices. JobSpy aliases are accepted.')
    location: str = Field(min_length=1, max_length=120)

    @field_validator('country')
    @classmethod
    def country_name(cls, value):
        from jobspy.model import Country
        from jobspy.indeed.constant import country_codes
        if sanitize_text(value) != value or any(unicodedata.category(c).startswith('C') for c in value):
            raise ValueError('Provider-supported search country required')
        try:
            country = Country(value)
            if country not in country_codes: raise ValueError
        except ValueError:
            raise ValueError('Provider-supported search country required') from None
        return country.value.upper() if country.value in ('usa', 'uk') else country.value.title()

    @field_validator('location')
    @classmethod
    def place(cls, value, info: ValidationInfo):
        country = info.data.get('country')
        invalid = 'Bounded public city/region search location required'
        if not country or sanitize_text(value) != value or any(unicodedata.category(c).startswith('C') for c in value):
            raise ValueError(invalid)
        key = ', '.join(part.strip().casefold() for part in value.strip().split(','))
        supported = {'canada': 'Canada'}
        for code, name in PROVINCES.items():
            for province in (code, name):
                supported[f'{province.casefold()}, canada'] = f'{code}, Canada'
        for city, code in SEARCH_CITIES:
            for province in (code, PROVINCES[code]):
                for suffix in ('', ', canada'):
                    supported[f'{city.casefold()}, {province.casefold()}{suffix}'] = f'{city}, {code}, Canada'
        if country == 'Canada' and key in supported: return supported[key]
        # No digits, addresses, URLs, contact/credential syntax or free-form prose.
        # Letters/marks support international names; punctuation is name-only.
        if any(not (unicodedata.category(c)[0] in 'LM' or c in " ,.'’-‐‑") for c in value):
            raise ValueError(invalid)
        parts = [part.strip() for part in value.strip().split(',')]
        if not 1 <= len(parts) <= 3 or any(not part or len(part.split()) > 5 for part in parts):
            raise ValueError(invalid)
        for word in ' '.join(parts).split():
            if not any(c.isalpha() for c in word) or ('.' in word and not re.fullmatch(r'[^.]{1,3}\.', word)):
                raise ValueError(invalid)
        if re.search(r'\b(?:I|my|me|we|our|resume|CV|email|phone|password|passwd|passphrase|token|secret|credential|bearer|authorization|cookie|contact|built|developed|managed|led|worked|experience|years|engineer|skills|Python|JavaScript)\b', value, re.I):
            raise ValueError(invalid)
        from jobspy.model import Country
        # Normalize a country suffix/alias and reject an explicit conflicting one.
        try: suffix = Country(parts[-1])
        except ValueError: suffix = None
        if suffix is not None:
            if suffix != Country(country): raise ValueError(invalid)
            parts.pop()
        elif len(parts) == 3:
            raise ValueError(invalid)
        normalized = ', '.join(parts + [country])
        if len(normalized) > 120: raise ValueError(invalid)
        return normalized


class SearchPreferences(SearchLocation):
    """Provider options, separate from eligibility and submission settings."""
    remote: bool
    hours_old: int = Field(ge=1, le=720)
    per_query: int = Field(ge=1, le=10)
    total: int = Field(ge=1, le=25)
    order: Literal['lexical', 'newest', 'oldest']


# Controlled public vocabulary: resume sentences, employers and contact values
# can never become provider queries. Unsupported source vocabulary stays weak.
ROLE_TERMS = (
    'Software Engineer', 'Backend Engineer', 'Frontend Engineer', 'Full Stack Engineer',
    'AI Engineer', 'Machine Learning Engineer', 'Data Engineer', 'Data Analyst',
    'DevOps Engineer', 'Platform Engineer', 'Product Designer', 'Product Manager',
    'Business Analyst', 'Accountant', 'Registered Nurse',
)
SKILL_TERMS = (
    'Python', 'JavaScript', 'TypeScript', 'Java', 'C++', 'C#', '.NET', 'SQL',
    'PostgreSQL', 'React', 'FastAPI', 'Docker', 'Kubernetes', 'AWS', 'GCP',
    'Machine Learning', 'MLOps', 'RAG', 'LLM', 'LLMs', 'MCP', 'CI/CD',
)
QUERY_TERMS = ROLE_TERMS + SKILL_TERMS

# Conservatively withhold the whole skill fact on explicit uncertainty/negation.
# A separate affirmative fact may still support the term. This is lexical, not NLP.
UNSUPPORTED_CLAIM = re.compile(
    r"\b(?:no|not|never|without|lack(?:s|ed|ing)?|unfamiliar|unknown|unsure)\b"
    r"|\b\w+n['’]t\b", re.I)


def proposals(profile):
    from personal_jobby.wording import tailor, pattern
    result = []
    for term in QUERY_TERMS:
        evidence = []
        for fact in profile['facts']:
            if term in ROLE_TERMS:
                # An exact imported occupation, never a collaborator in a bullet.
                supported = bool(re.fullmatch(pattern(term), fact.get('role', '').strip(), re.I))
            else:
                text = tailor(fact, term)['rendered']
                supported = not UNSUPPORTED_CLAIM.search(text) and bool(re.search(pattern(term), text, re.I))
            if supported:
                evidence.append(dict(fact_id=fact['id'], excerpt=fact['excerpt'][:500],
                                     role=fact.get('role', '')))
        if evidence:
            result.append(dict(term=term, evidence=evidence[:3]))
        if len(result) == 8: break
    return result


def source_token(profile):
    from personal_jobby import private_fs as fs
    hashes = profile.get('source_hashes', {})
    if not profile['facts'] or not hashes: return None
    try:
        if any(hashlib.sha256(fs.read_bytes(path, max_bytes=8*1024*1024)).hexdigest() != digest
               for path, digest in hashes.items()): return None
    except (OSError, ValueError): return None
    return hashlib.sha256(json.dumps(dict(facts=profile['facts'], hashes=hashes), sort_keys=True).encode()).hexdigest()


def setup(store):
    profile = store.profile()
    token = source_token(profile)
    suggested = proposals(profile) if token else []
    saved = store.settings().get('discovery') or {}
    try:
        preferences = SearchPreferences.model_validate(saved.get('preferences'), strict=True).model_dump()
        queries = saved.get('queries')
        allowed = {p['term'] for p in suggested}
        if (not isinstance(queries, list) or not 1 <= len(queries) <= 3
                or any(not isinstance(q, str) or q not in allowed for q in queries)
                or len(set(queries)) != len(queries)):
            raise ValueError('Current supported queries required')
    except (ValueError, TypeError):
        preferences = None
        queries = []
    confirmed = bool(token and saved.get('source_token') == token and preferences and queries)
    return dict(ok=True, proposals=suggested, source_token=token,
                confirmed=confirmed, preferences=preferences,
                queries=queries, supported_countries=supported_countries(),
                last_run=store.discovery_result(),
                shortlist=shortlist(store, profile if token else dict(facts=[]), (preferences or {}).get('order', 'lexical')),
                ranking_method='Distinct exact lexical overlap after reviewed terminology equivalences; not semantic fit or hiring probability.',
                warnings=[] if suggested else ['Source evidence is missing, changed or outside the supported query vocabulary; import a usable source or use a selected posting.'],
                scope='Lexical source suggestions only; search preferences are not work authorization or submission consent.',
                submission_available=False)


def confirm(store, token, queries, preferences):
    with store.profile_lock():
        current = setup(store)
        allowed = {p['term'] for p in current['proposals']}
        if not token or token != current['source_token'] or not queries or len(queries) > 3 or len(set(queries)) != len(queries) or not set(queries) <= allowed:
            raise ValueError('Confirm current source-supported queries')
        preferences = SearchPreferences.model_validate(preferences, strict=True).model_dump()
        store.save_discovery(dict(source_token=token, queries=queries, preferences=preferences))
    return setup(store)


def posted_date(job):
    from datetime import date
    raw = job.get('original_source', {}).get('date_posted', '')
    try:
        return date.fromisoformat(raw).isoformat() if isinstance(raw, str) else None
    except ValueError: return None


def shortlist(store, profile, order='lexical'):
    from personal_jobby.core import select_facts, ranking_terms
    facts = {f['id']: f for f in profile['facts']}
    result = []
    for job in store.discovery_jobs():
        selection = select_facts(profile, job)
        terms = sorted({t for e in selection['evidence'] for t in e['matched_terms']})
        evidence = [dict(fact_id=e['fact_id'], matching_terms=e['matched_terms'],
                         excerpt=facts[e['fact_id']]['excerpt'][:500])
                    for e in selection['evidence'] if e['matched_terms']]
        result.append(dict(id=job['id'], title=job['title'], company=job['company'],
                           location=job['location'], job_url=job['job_url'], status=job['status'],
                           posted_date=posted_date(job), matching_terms=terms, evidence=evidence[:6],
                           unmatched_posting_terms=sorted(ranking_terms(job['title']+' '+job['description']) - set(terms))[:20],
                           unknowns=['Lexical overlap does not establish qualifications.',
                                     'Employer salary, arrangement, eligibility and legal authorization require separate verification.']))
    def key(item):
        stable = (item['job_url'], item['company'], item['title'], item['id'])
        if order == 'lexical': return (-len(item['matching_terms']), *stable)
        from datetime import date
        day = date.fromisoformat(item['posted_date']).toordinal() if item['posted_date'] else 0
        return (item['posted_date'] is None, -day if order == 'newest' else day, *stable)
    return sorted(result, key=key)[:100]


def run(store):
    with store.profile_lock(): return _run(store)


def _run(store):
    current = setup(store)
    if not current['confirmed']: raise ValueError('Confirm source and search preferences first')
    saved = store.settings()['discovery']
    preferences = SearchPreferences.model_validate(saved['preferences'], strict=True)
    if not set(saved['queries']) <= {p['term'] for p in current['proposals']}:
        raise ValueError('Source-supported queries required')
    remaining = preferences.total
    queries = []; errors = []; observed = set()
    for term in saved['queries']:
        if remaining <= 0: break
        limit = min(preferences.per_query, remaining)
        try:
            result = discover(store, term, limit, country=preferences.country, location=preferences.location, remote=preferences.remote,
                              hours_old=preferences.hours_old, record_discovery=True)
            observed.update(j['id'] for j in result['jobs'])
            errors.extend(dict(query=term, code='listing_invalid', message='Listing validation failed; source values withheld.') for _ in result['errors'])
            queries.append(dict(term=term, requested=limit, stored=len(result['jobs'])))
        except ImportError:
            errors.append(dict(query=term, code='dependency_missing', message='Optional python-jobspy discovery dependency is unavailable in this runtime. Ask the operator to install the declared discovery extra in an owned environment.'))
        except Exception:
            errors.append(dict(query=term, code='source_failed', message='Search source failed; details withheld. Existing shortlist retained.'))
        remaining -= limit
    outcome = 'partial' if errors and observed else 'failed' if errors else 'completed' if observed else 'empty'
    store.save_discovery_result(dict(outcome=outcome, queries=queries, errors=errors,
                                     unique_jobs_observed=len(observed), requested=preferences.total-remaining))
    return setup(store)

def discover(store,term,limit=10,*,country='Canada',location='Toronto, ON, Canada',remote=None,hours_old=72,record_discovery=False):
    if not term.strip() or len(term)>200 or not 1<=limit<=25: raise ValueError('Search requires term and limit 1–25')
    if not isinstance(location,str) or not location.strip() or len(location)>500 or type(hours_old) is not int or not 1<=hours_old<=8760 or (remote is not None and type(remote) is not bool): raise ValueError('Invalid bounded search options')
    place = SearchLocation(country=country, location=location)
    from jobspy import scrape_jobs
    options=dict(site_name=['indeed','linkedin'],search_term=term,location=place.location,country_indeed=place.country,results_wanted=limit,hours_old=hours_old)
    if remote is not None: options['is_remote']=remote
    with _provider_diagnostics():
        frame=scrape_jobs(**options)
    def value(row,key):
        v=row.get(key)
        return '' if v is None or (isinstance(v,float) and math.isnan(v)) else str(v)
    results=[]; errors=[]
    for _,row in frame.head(limit).iterrows():
        try:
            url=value(row,'job_url'); public_url(url)
            salary_raw=' | '.join(value(row,k) for k in ('currency','min_amount','max_amount','interval','salary_source'))
            data=dict(title=value(row,'title'),company=value(row,'company'),job_url=url,requisition=value(row,'requisition'),location=value(row,'location'),description=value(row,'description') or 'Description not supplied by source; review original listing.',original_source={str(k):value(row,k) for k in row.index},salary=dict(raw=salary_raw,source_url=url,origin='aggregator',verified=False))
            results.append(store.add(data))
            if record_discovery:
                with store.connect() as connection:
                    store.event(connection, results[-1]['id'], 'discovery_observed', dict(query=term))
        except ValueError as e: errors.append('Listing validation failed; source values withheld')
    return dict(jobs=results,errors=errors,message='Aggregator salaries require manual employer verification. No salary estimates confer eligibility.')
