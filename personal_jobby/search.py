import math
from personal_jobby.core import public_url

def discover(store,term,limit=10,*,location='Toronto, ON, Canada',remote=None,hours_old=72):
    if not term.strip() or len(term)>200 or not 1<=limit<=25: raise ValueError('Search requires term and limit 1–25')
    if not isinstance(location,str) or not location.strip() or len(location)>500 or type(hours_old) is not int or not 1<=hours_old<=8760 or (remote is not None and type(remote) is not bool): raise ValueError('Invalid bounded search options')
    from jobspy import scrape_jobs
    options=dict(site_name=['indeed','linkedin'],search_term=term,location=location,country_indeed='Canada',results_wanted=limit,hours_old=hours_old)
    if remote is not None: options['is_remote']=remote
    frame=scrape_jobs(**options)
    def value(row,key):
        v=row.get(key)
        return '' if v is None or (isinstance(v,float) and math.isnan(v)) else str(v)
    results=[]; errors=[]
    for _,row in frame.head(limit).iterrows():
        try:
            url=value(row,'job_url'); public_url(url)
            salary_raw=' | '.join(value(row,k) for k in ('currency','min_amount','max_amount','interval','salary_source'))
            data=dict(title=value(row,'title'),company=value(row,'company'),job_url=url,location=value(row,'location'),description=value(row,'description') or 'Description not supplied by source; review original listing.',original_source={str(k):value(row,k) for k in row.index},salary=dict(raw=salary_raw,source_url=url,origin='aggregator',verified=False))
            results.append(store.add(data))
        except ValueError as e: errors.append('Listing validation failed; source values withheld')
    return dict(jobs=results,errors=errors,message='Aggregator salaries require manual employer verification. No salary estimates confer eligibility.')
