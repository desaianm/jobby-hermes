"""Daily control seam tests: only temporary private workspaces, no live searches."""
import json
from datetime import datetime, timedelta, timezone
import pytest
from personal_jobby.store import Store
from personal_jobby.daily import Daily, AUTHORIZATION


def test_policy_disabled_until_external_cron_configured(tmp_path):
    store=Store(tmp_path)
    daily=Daily(store)
    status=daily.status()
    assert status['policy']['enabled'] is False
    assert status['policy']['cron_job_id'] is None
    assert status['policy']['schedule'] is None
    assert status['executor_enabled'] is False
    assert status['submission_active'] is False
    with pytest.raises(ValueError): daily.configure(enabled=True)
    with pytest.raises(ValueError): daily.configure(enabled=False,max_submissions_per_day=26)
    policy=daily.configure(enabled=True,cron_job_id='test-fixture-cron',schedule='0 9 * * *')
    assert policy['authorization_source']==AUTHORIZATION
    assert daily.status()['executor_enabled'] is True
    assert daily.status()['submission_active'] is False  # criteria still provisional
    assert (tmp_path/'daily-policy.json').stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o777 == 0o700
    daily.configure(enabled=False)
    assert daily.status()['executor_enabled'] is False


def enabled_daily(tmp_path,clock=None):
    d=Daily(Store(tmp_path),clock)
    d.configure(enabled=True,cron_job_id='temp-test-cron',schedule='0 9 * * *')
    return d


def test_one_global_renewable_lease_and_stale_recovery(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    current=[datetime(2026,10,9,2,0,tzinfo=timezone.utc)]
    d=enabled_daily(tmp_path,lambda:current[0])
    def start(owner):
        try: return Daily(Store(tmp_path),lambda:current[0]).start(owner)
        except ValueError: return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(start,['cron-a','cron-b']))
    run=next(r for r in results if r)
    assert len([r for r in results if r])==1
    assert run['day']=='2026-10-08'  # Toronto, not UTC
    current[0]+=timedelta(minutes=20)
    renewed=d.heartbeat(run['run_id'])
    current[0]+=timedelta(minutes=20)
    with pytest.raises(ValueError): d.start('second')
    assert renewed['lease_expires_at']>run['lease_expires_at']
    current[0]+=timedelta(minutes=11)
    next_run=d.start('recovered')
    assert d.summary(run['run_id'])['run']['status']=='interrupted'
    with pytest.raises(ValueError): d.heartbeat(run['run_id'])
    d.note(next_run['run_id'],job_id=d.store.add({'title':'Fixture','company':'Fixture','job_url':'https://example.com/lease','description':'Fixture only'})['id'],outcome='blocked',reason='Login needed +1 416 555 0100',source_url='https://example.com/lease')
    with pytest.raises(ValueError): d.note(next_run['run_id'],job_id=1,outcome='submitted',reason='Claimed')
    summary=d.finish(next_run['run_id'],'blocked','Hold')
    assert summary['counts']['blocked']==1
    assert summary['counts']['submitted']==0
    assert '416 555' not in json.dumps(summary)
    assert summary['events'][-1]['kind']=='run_finished'
    with pytest.raises(ValueError): d.note(next_run['run_id'],job_id=1,outcome='failed',reason='Late')


def test_tracking_aliases_dedupe_archived_roles_but_keep_meaningful_ids(tmp_path):
    store=Store(tmp_path)
    job=dict(title='AI Engineer',company='Fixture',job_url='https://example.com/view?jk=one&utm_campaign=first',description='Fixture',original_source={'job_url_direct':'https://ats.example.com/job?req=123&gh_src=ad'})
    first=store.add(job)
    store.transition(first['id'],'archived')
    second=store.add({**job,'title':'ML Engineer','job_url':'https://example.com/view?utm_medium=social&jk=one','original_source':{'job_url_direct':'https://ats.example.com/job?req=123&source=feed'}})
    assert second['id']==first['id']
    assert store.job_snapshot(first['id'])['job_url']==job['job_url']
    assert store.job_snapshot(first['id'])['original_source']['job_url_direct']==job['original_source']['job_url_direct']
    other=store.add({**job,'job_url':'https://example.com/view?jk=two','original_source':{}})
    assert other['id']!=first['id']
    another=store.add({**job,'job_url':'https://example.com/view?job_id=three&req=456','original_source':{}})
    assert another['id'] not in (first['id'],other['id'])
    assert Store(tmp_path).add({**job,'job_url':'https://ats.example.com/job?src=new&req=123','original_source':{}})['id']==first['id']


def ready_attempt(d,*,suffix='one',approved=True,shot=True,job_changes=None):
    from personal_jobby import private_fs as fs
    from personal_jobby.documents import prepare
    from personal_jobby.artifacts import approve
    from personal_jobby.audit import create_attempt,add_screenshot
    from PIL import Image
    s=d.store
    settings=s.settings();settings.update(criteria_confirmed=True,submission_desired=True);s.save_settings(settings)
    if not (s.root/'candidate.json').exists():
        fs.write_text(s.root/'candidate.json',json.dumps(dict(name='Fixture',contact='Toronto',answers={'work_eligibility':'Authorized in Canada'},facts=[dict(id='f',section='EXPERIENCE',group='Past Employer | AI Engineer',date='Apr 2026 - Present',text='Built Python services.',source='fixture',excerpt='Built Python services.')],source_hashes={'fixture':'v1'})))
    job=dict(title='AI Engineer',company='Fixture',job_url='https://example.com/jobs/'+suffix,requisition=suffix,location='Toronto, ON',description='Hybrid in Toronto. Python RAG. Permanent full-time.',arrangement='hybrid',arrangement_evidence='Hybrid in Toronto',employment_type='permanent_full_time',employment_evidence='Permanent full-time',salary=dict(raw='CAD 120000 annual base salary',origin='employer',currency='CAD',unit='annual',kind='base',lower=120000,verified=True,source_url='https://example.com/jobs/'+suffix))
    job.update(job_changes or {})
    j=s.add(job);meta=prepare(s,j['id'])
    # Manifest capture needs approval; optionally revoke afterwards through real regeneration.
    approve(s,j['id'],meta['review_token'],dict(reviewer='Fixture reviewer',note='Viewed all fixture documents'))
    attempt=create_attempt(s,j['id'],dict(operator='hermes',generation_id=meta['generation_id'],review_token=meta['review_token'],resume=dict(filename='resume.pdf',sha256=meta['artifact_hashes']['resume.pdf']),cover_letter=None))
    image=s.root/'fixture-screen.png';Image.new('RGB',(10,10),'white').save(image)
    fs.chmod(image)
    if shot: add_screenshot(s,attempt['id'],image,'filled_form','Fixture review of exact attached resume, phone omitted',True)
    if not approved: prepare(s,j['id'])
    return j,attempt,image


@pytest.mark.parametrize('failure',['phone_unknown','phone_required','no_screenshot','no_approval','changed_settings','changed_facts','changed_source','changed_pdf','salary_unknown','location_unknown','ft_unknown','work_unknown','kill_switch','pilot_disabled','criteria_unconfirmed'])
def test_submit_preflight_fails_closed_without_budget_cost(tmp_path,failure):
    from personal_jobby import private_fs as fs
    d=enabled_daily(tmp_path)
    changes={}
    if failure=='salary_unknown': changes['salary']={}
    if failure=='location_unknown': changes['arrangement']='unknown'
    if failure=='ft_unknown': changes['employment_type']='unknown'
    j,a,image=ready_attempt(d,approved=failure!='no_approval',shot=failure!='no_screenshot',job_changes=changes)
    run=d.start('temp-fixture')
    phone=False
    if failure=='phone_unknown': phone=None
    if failure=='phone_required': phone=True
    if failure in {'changed_settings','kill_switch','criteria_unconfirmed'}:
        settings=d.store.settings()
        settings.update({'minimum':130000} if failure=='changed_settings' else {('submission_desired' if failure=='kill_switch' else 'criteria_confirmed'):False})
        d.store.save_settings(settings)
    if failure=='changed_facts':
        profile=d.store.profile();profile['facts'][0]['text']='Changed fixture fact';fs.write_text(d.store.root/'candidate.json',json.dumps(profile))
    if failure=='changed_source':
        profile=d.store.profile();profile['source_hashes']['fixture']='v2';fs.write_text(d.store.root/'candidate.json',json.dumps(profile))
    if failure=='changed_pdf': fs.write_text(d.store.artifact_dir(j['id'])/'resume.pdf','corrupt fixture')
    if failure=='work_unknown': d.store.save_answers({'work_eligibility':''})
    if failure=='pilot_disabled': d.configure(enabled=False)
    with pytest.raises(ValueError): d.begin_submit(run['run_id'],a['id'],phone_required=phone)
    assert d.summary()['attempted_submissions_today']==0
    assert d.store.get(j['id'])['status']!='submission_pending'


def test_reserve_before_click_blocks_repeat_and_resume_only_is_exact(tmp_path):
    d=enabled_daily(tmp_path);j,a,image=ready_attempt(d)
    run=d.start('temp-fixture')
    reserved=d.begin_submit(run['run_id'],a['id'],phone_required=False)
    assert reserved['state']=='submit_started'
    assert reserved['cover_letter_used'] is False
    assert d.store.get(j['id'])['status']=='submission_pending'
    assert d.store.get(j['id'])['attempts'][0]['status']=='submit_started'
    with pytest.raises(ValueError): d.begin_submit(run['run_id'],a['id'],phone_required=False)
    assert d.summary()['attempted_submissions_today']==1
    assert d.summary()['counts']['submitted']==0


def test_uncertain_survives_interruption_and_receipt_resolves_once(tmp_path):
    from personal_jobby.audit import add_screenshot,create_attempt
    current=[datetime(2026,10,8,15,tzinfo=timezone.utc)]
    d=enabled_daily(tmp_path,lambda:current[0]);j,a,image=ready_attempt(d)
    run=d.start('fixture-owner');d.begin_submit(run['run_id'],a['id'],phone_required=False)
    with pytest.raises(ValueError): d.store.receipt(j['id'],text='Claimed confirmation',timestamp=current[0].isoformat(),attempt_id=a['id'])
    uncertain=d.uncertain(run['run_id'],a['id'],'Click happened; no receipt +1 416 555 0100')
    assert uncertain['reservations'][0]['state']=='uncertain'
    current[0]+=timedelta(minutes=31)
    next_run=d.start('recovery')
    assert d.summary(run['run_id'])['run']['status']=='interrupted'
    assert d.status()['uncertain_count']==1
    assert d.store.get(j['id'])['attempts'][0]['status']=='uncertain'
    with pytest.raises(ValueError): d.begin_submit(next_run['run_id'],a['id'],phone_required=False)
    with pytest.raises(ValueError): d.store.receipt(j['id'],text='Alternate report cannot release reserved lock',timestamp=current[0].isoformat())
    add_screenshot(d.store,a['id'],image,'employer_confirmation','Fixture confirmation reviewed; phone omitted',True)
    result=d.store.receipt(j['id'],text='Actual fixture employer confirmation',timestamp=current[0].isoformat(),attempt_id=a['id'])
    assert result['status']=='applied'
    assert result['attempts'][0]['generation_id']==a['generation_id']
    assert result['attempts'][0]['cover_letter_used'] is False
    assert result['submitted_at']==current[0].isoformat()
    assert d.summary(run['run_id'])['counts']['submitted']==1
    assert d.status()['uncertain_count']==0
    with pytest.raises(ValueError): d.store.receipt(j['id'],text='Repeated',timestamp=current[0].isoformat(),attempt_id=a['id'])
    d.note(next_run['run_id'],job_id=j['id'],outcome='submitted',reason='Receipt exists')
    assert d.summary(next_run['run_id'])['counts']['submitted']==0
    assert d.summary(run['run_id'])['counts']['submitted']==1


def test_unresolved_reserve_automatically_uncertain_without_operator_note(tmp_path):
    current=[datetime(2026,10,8,15,tzinfo=timezone.utc)]
    d=enabled_daily(tmp_path,lambda:current[0]);j,a,image=ready_attempt(d)
    run=d.start('fixture-owner');d.begin_submit(run['run_id'],a['id'],phone_required=False)
    current[0]+=timedelta(minutes=31)
    assert d.summary(run['run_id'])['reservations'][0]['state']=='uncertain'
    next_run=d.start('recovery')
    assert any(e['kind']=='uncertain' for e in d.summary(run['run_id'])['events'])
    assert d.summary()['attempted_submissions_today']==1
    with pytest.raises(ValueError): d.begin_submit(next_run['run_id'],a['id'],phone_required=False)


def test_daily_budget_persists_same_day_and_buckets_midnight_toronto(tmp_path):
    from personal_jobby.audit import add_screenshot
    current=[datetime(2026,10,9,3,55,tzinfo=timezone.utc)]  # Oct 8, 23:55 Toronto
    d=enabled_daily(tmp_path,lambda:current[0]);d.configure(max_submissions_per_day=1)
    j,a,image=ready_attempt(d);run=d.start('before-midnight')
    d.begin_submit(run['run_id'],a['id'],phone_required=False)
    d.finish(run['run_id'],'partial','No confirmation')
    j2,a2,image2=ready_attempt(d,suffix='two')
    run2=d.start('same-day')
    with pytest.raises(ValueError,match='cap'):d.begin_submit(run2['run_id'],a2['id'],phone_required=False)
    assert d.summary()['attempted_submissions_today']==1
    current[0]+=timedelta(minutes=6)  # Same lease may cross midnight; use reservation time.
    d.begin_submit(run2['run_id'],a2['id'],phone_required=False)
    assert d.summary()['day']=='2026-10-09'
    assert d.summary()['attempted_submissions_today']==1
    assert d.status()['uncertain_count']==1
    add_screenshot(d.store,a2['id'],image2,'employer_confirmation','Reviewed fixture confirmation',True)
    d.store.receipt(j2['id'],text='Fixture confirmed',timestamp=current[0].isoformat(),attempt_id=a2['id'])
    d.finish(run2['run_id'],'completed')
    run3=d.start('same-new-day')
    j3,a3,image3=ready_attempt(d,suffix='three')
    with pytest.raises(ValueError,match='cap'):d.begin_submit(run3['run_id'],a3['id'],phone_required=False)
    assert d.summary(run2['run_id'])['counts']['submitted']==1
    assert d.summary()['attempted_submissions_today']==1


def test_concurrent_reservations_cannot_exceed_cap(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    d=enabled_daily(tmp_path);d.configure(max_submissions_per_day=1)
    j,a,image=ready_attempt(d);j2,a2,image2=ready_attempt(d,suffix='two')
    run=d.start('parallel-fixture')
    def reserve(attempt):
        try: return Daily(Store(tmp_path)).begin_submit(run['run_id'],attempt,phone_required=False)
        except ValueError: return None
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(reserve,[a['id'],a2['id']]))
    assert len([r for r in results if r])==1
    assert d.summary()['attempted_submissions_today']==1


@pytest.mark.parametrize('terminal',['applied','interview','offer','rejected'])
def test_existing_application_states_block_even_an_archived_alias(tmp_path,terminal):
    d=enabled_daily(tmp_path);j,a,image=ready_attempt(d)
    if terminal=='applied':
        # A genuine user-reported prior receipt is independent of the never-clicked draft.
        d.store.receipt(j['id'],text='Fixture prior employer receipt',timestamp=datetime.now(timezone.utc).isoformat())
        d.store.transition(j['id'],'archived')
    else: d.store.transition(j['id'],terminal)
    assert d.store.add({**d.store.job_snapshot(j['id']),'title':'ML Engineer','job_url':j['job_url']+'?utm_source=second'})['id']==j['id']
    run=d.start('alias-fixture')
    with pytest.raises(ValueError): d.begin_submit(run['run_id'],a['id'],phone_required=False)
    assert d.summary()['attempted_submissions_today']==0


def test_reserved_receipt_requires_exact_timestamp_and_intact_confirmation(tmp_path):
    from personal_jobby import private_fs as fs
    from personal_jobby.audit import add_screenshot
    d=enabled_daily(tmp_path);j,a,image=ready_attempt(d)
    run=d.start('fixture');d.begin_submit(run['run_id'],a['id'],phone_required=False)
    confirmation=add_screenshot(d.store,a['id'],image,'employer_confirmation','Reviewed actual fixture confirmation',True)
    with pytest.raises(ValueError):d.store.receipt(j['id'],text='Fixture receipt',timestamp='2020-01-01T00:00:00+00:00',attempt_id=a['id'])
    fs.write_text(d.store.root/'applications'/a['id']/'screenshots'/confirmation['filename'],'corrupt fixture')
    with pytest.raises(ValueError):d.store.receipt(j['id'],text='Fixture receipt',timestamp=datetime.now(timezone.utc).isoformat(),attempt_id=a['id'])
    assert d.summary()['counts']['submitted']==0


def test_readonly_daily_dashboard_is_truthful_and_has_current_security(tmp_path):
    from fastapi.testclient import TestClient
    from personal_jobby.app import create_app
    app=create_app(tmp_path);client=TestClient(app,base_url='http://localhost')
    daily=Daily(app.state.store)
    assert client.get('/api/daily').status_code==200
    initial=client.get('/api/daily').json()
    assert initial['policy']['schedule'] is None
    assert initial['executor_enabled'] is False
    assert initial['latest_run'] is None
    assert client.get('/api/state').json()['submission_active'] is False
    assert client.get('/api/daily',headers={'host':'evil.example'}).status_code==400
    assert client.post('/api/daily',json={},headers={'origin':'https://evil.example'}).status_code==403
    assert client.post('/api/daily',json={}).status_code==405
    daily.configure(enabled=True,cron_job_id='fixture-external-cron',schedule='0 9 * * *')
    j,a,image=ready_attempt(daily)
    state=client.get('/api/state').json()
    assert state['executor_type']=='hermes_cron_agent'
    assert state['executor_enabled'] is True
    assert not any('unavailable' in b.lower() or 'missing: phone' in b.lower() for b in app.state.store.get(j['id'])['blockers'])
    settings=app.state.store.settings();settings['submission_desired']=False;app.state.store.save_settings(settings)
    assert client.get('/api/state').json()['submission_active'] is False
    assert any('intent disabled' in b.lower() for b in app.state.store.get(j['id'])['blockers'])
    html=client.get('/').text;js=client.get('/static/app.js').text
    assert 'id="daily-status"' in html and '/api/daily' in js
    assert 'innerHTML' not in js and 'onclick=' not in html
    assert "script-src 'self'" in client.get('/api/daily').headers['content-security-policy']
    assert client.get('/api/daily').headers['cache-control']=='no-store'


def test_policy_and_ledger_private_paths_reject_symlinks_and_redact(tmp_path):
    from personal_jobby import private_fs as fs
    store=Store(tmp_path/'private');d=Daily(store)
    target=tmp_path/'target';target.write_text('{}')
    (store.root/'daily-policy.json').symlink_to(target)
    with pytest.raises(ValueError): d.policy()
    with pytest.raises(ValueError): d.configure(enabled=False)
    (store.root/'daily-policy.json').unlink()
    (store.root/'daily-policy.lock').unlink(missing_ok=True)
    (store.root/'daily-policy.lock').symlink_to(target)
    with pytest.raises(ValueError):d.configure(enabled=False)
    (store.root/'daily-policy.lock').unlink()
    d.configure(enabled=True,cron_job_id='fixture-id',schedule='0 9 * * *')
    job=store.add(dict(title='Fixture',company='Fixture',job_url='https://example.com/redacted',description='Fixture'))
    run=d.start('test-owner')
    d.note(run['run_id'],job_id=job['id'],outcome='blocked',reason='Phone +1 416 555 0100 token=secret123 password=hidden')
    summary=d.summary()
    assert '416 555' not in json.dumps(summary)
    assert 'secret123' not in json.dumps(summary) and 'hidden' not in json.dumps(summary)
    assert store.db.stat().st_mode & 0o777==0o600
    for path in store.root.glob('*.lock'): assert path.stat().st_mode & 0o777==0o600
    with pytest.raises(ValueError): d.note(run['run_id'],job_id=job['id'],outcome='blocked',reason='x'*501)
    with pytest.raises(ValueError): d.note(run['run_id'],job_id=job['id'],outcome='blocked',reason='Hold',source_url='http://127.0.0.1/private')
    import sqlite3
    with store.connect() as c:
        with pytest.raises(sqlite3.IntegrityError):c.execute("DELETE FROM daily_events")


def test_daily_cli_commands_require_explicit_phone_decision_and_sanitize(tmp_path,monkeypatch,capsys):
    import personal_jobby.__main__ as cli
    monkeypatch.setattr(cli,'Store',lambda:Store(tmp_path))
    def command(*args):
        monkeypatch.setattr('sys.argv',['personal_jobby',*args]);cli.main()
        return json.loads(capsys.readouterr().out)
    assert command('daily','status')['policy']['enabled'] is False
    command('daily','configure','--enabled','true','--cron-job-id','fixture-cron','--schedule','0 9 * * *')
    run=command('daily','start','--owner','fixture-owner')
    d=Daily(Store(tmp_path));j,a,image=ready_attempt(d)
    monkeypatch.setattr('sys.argv',['personal_jobby','daily','begin-submit',run['run_id'],a['id']])
    with pytest.raises(SystemExit) as error:cli.main()
    assert error.value.code!=0
    capsys.readouterr()
    reserved=command('daily','begin-submit',run['run_id'],a['id'],'--phone-not-required')
    assert reserved['state']=='submit_started'
    command('daily','heartbeat',run['run_id'])
    command('daily','uncertain',run['run_id'],a['id'],'--reason','No receipt +1 416 555 0100')
    result=command('daily','summary',run['run_id'])
    assert '416 555' not in json.dumps(result)
    command('daily','finish',run['run_id'],'--status','partial','--note','Login hold')
    assert command('daily','configure','--enabled','false')['enabled'] is False


def test_search_location_remote_age_direct_jobspy_and_original_row(tmp_path,monkeypatch):
    import sys,types
    import pandas as pd
    from personal_jobby.search import discover
    seen=[]
    raw=dict(title='AI Engineer',company='Fixture',job_url='https://example.com/jobs/search?jk=raw&utm_source=keep',job_url_direct='https://ats.example.com/search?job_id=123',description='Fixture raw posting',location='Canada',is_remote=True)
    def scrape(**kwargs):seen.append(kwargs);return pd.DataFrame([raw])
    monkeypatch.setitem(sys.modules,'jobspy',types.SimpleNamespace(scrape_jobs=scrape))
    s=Store(tmp_path)
    result=discover(s,'AI Engineer',25,location='Canada',remote=True,hours_old=72)
    assert seen[0]['location']=='Canada' and seen[0]['is_remote'] is True and seen[0]['hours_old']==72
    assert seen[0]['results_wanted']==25
    assert s.job_snapshot(result['jobs'][0]['id'])['original_source']['job_url']==raw['job_url']
    assert result['jobs'][0]['eligibility']=='needs_review'
    discover(s,'AI Engineer')
    assert seen[1]['location']=='Toronto, ON, Canada' and seen[1]['hours_old']==72
    with pytest.raises(ValueError):discover(s,'AI Engineer',26)
    with pytest.raises(ValueError):discover(s,'AI Engineer',location='x'*501)
    with pytest.raises(ValueError):discover(s,'AI Engineer',hours_old=0)


def test_verified_employer_salary_proof_is_retained_without_fetch(tmp_path):
    d=enabled_daily(tmp_path);j,a,image=ready_attempt(d)
    proof=dict(salary={**j['salary'],'raw':'CAD 125000 annual base salary','lower':125000},operator_note='Read exact employer structured salary at public source; currency and annual base explicit')
    result=d.verify_job(j['id'],proof)
    assert result['salary']['lower']==125000
    saved=d.store.job_snapshot(j['id'])['original_source']['employer_salary_verification']
    assert saved['salary']['raw']=='CAD 125000 annual base salary'
    assert saved['salary']['source_url']==j['salary']['source_url']
    assert saved['operator_note']==proof['operator_note']
    assert d.store.materials(j['id'])['qa_state']=='stale'
    with pytest.raises(ValueError):d.verify_job(j['id'],{**proof,'fetch_url':'http://localhost/private'})
    with pytest.raises(ValueError):d.verify_job(j['id'],{**proof,'salary':{**proof['salary'],'source_url':'http://127.0.0.1/private'}})
    with pytest.raises(ValueError):d.verify_job(j['id'],{**proof,'salary':{**proof['salary'],'lower':120000}})


def test_phone_required_saved_privately_and_default_ten_cap(tmp_path):
    d=enabled_daily(tmp_path)
    d.store.save_phone('+1 416 555 0111')
    # Supplying phone before initialization preserves it; the fixture uses existing profile.
    profile=d.store.profile()
    from personal_jobby import private_fs as fs
    profile['answers']['work_eligibility']='Authorized in Canada'
    profile['facts']=[dict(id='f',section='EXPERIENCE',group='Past Employer | AI Engineer',date='Apr 2026 - Present',text='Built Python services.',source='fixture',excerpt='Built Python services.')]
    profile['source_hashes']={'fixture':'v1'};fs.write_text(d.store.root/'candidate.json',json.dumps(profile))
    run=d.start('default-cap-fixture')
    for number in range(10):
        j,a,image=ready_attempt(d,suffix='cap-'+str(number))
        result=d.begin_submit(run['run_id'],a['id'],phone_required=True)
        assert '416 555' not in json.dumps(result)
    j,a,image=ready_attempt(d,suffix='cap-eleven')
    with pytest.raises(ValueError,match='cap'):d.begin_submit(run['run_id'],a['id'],phone_required=True)
    assert d.summary()['attempted_submissions_today']==10
    assert '416 555' not in json.dumps(d.status())
    assert d.policy()['max_submissions_per_day']==10


def test_changed_authoritative_file_and_reviewed_screenshot_fail_closed(tmp_path):
    from personal_jobby import private_fs as fs
    import hashlib
    d=enabled_daily(tmp_path);j,old,image=ready_attempt(d)
    source=tmp_path/'authoritative.txt';fs.write_text(source,'Fixture source v1')
    profile=d.store.profile();profile['source_hashes']={str(source):hashlib.sha256(fs.read_bytes(source)).hexdigest()};fs.write_text(d.store.root/'candidate.json',json.dumps(profile))
    j,a,image=ready_attempt(d)
    run=d.start('source-fixture')
    fs.write_text(source,'Fixture source v2')
    with pytest.raises(ValueError):d.begin_submit(run['run_id'],a['id'],phone_required=False)
    fs.write_text(source,'Fixture source v1')
    shot=a['id']
    screenshot=d.store.get(j['id'])['attempts'][-1]['screenshots'][0]
    fs.write_text(d.store.root/'applications'/shot/'screenshots'/screenshot['filename'],'corrupt fixture')
    with pytest.raises(ValueError):d.begin_submit(run['run_id'],a['id'],phone_required=False)
    assert d.summary()['attempted_submissions_today']==0


def test_confirmation_screenshot_does_not_clear_uncertainty_without_receipt(tmp_path):
    from personal_jobby.audit import add_screenshot
    d=enabled_daily(tmp_path);j,a,image=ready_attempt(d)
    run=d.start('fixture');d.begin_submit(run['run_id'],a['id'],phone_required=False)
    d.uncertain(run['run_id'],a['id'],'Unconfirmed fixture click')
    add_screenshot(d.store,a['id'],image,'employer_confirmation','Reviewed fixture confirmation, awaiting receipt record',True)
    assert d.store.get(j['id'])['attempts'][0]['status']=='uncertain'
    assert d.summary()['reservations'][0]['state']=='uncertain'


def test_manual_receipt_cannot_create_alternate_audit_for_reserved_posting(tmp_path):
    d=enabled_daily(tmp_path);j,a,image=ready_attempt(d)
    run=d.start('fixture');d.begin_submit(run['run_id'],a['id'],phone_required=False)
    with pytest.raises(ValueError):d.store.receipt(j['id'],text='Alternate reported receipt',timestamp=datetime.now(timezone.utc).isoformat())
    assert len(d.store.get(j['id'])['attempts'])==1
    assert d.summary()['counts']['submitted']==0


def test_meaningful_repeated_query_ids_are_not_collapsed(tmp_path):
    store=Store(tmp_path)
    job=dict(title='AI Engineer',company='Fixture',description='Fixture')
    first=store.add({**job,'job_url':'https://example.com/view?jk=first&jk=second&utm_campaign=ad'})
    second=store.add({**job,'job_url':'https://example.com/view?jk=second&jk=first'})
    assert first['id']!=second['id']
    assert store.add({**job,'job_url':'https://example.com/view?utm_source=new&jk=first&jk=second'})['id']==first['id']


def test_phone_presence_is_informational_before_actual_form_requirement(tmp_path):
    from fastapi.testclient import TestClient
    from personal_jobby.app import create_app
    client=TestClient(create_app(tmp_path),base_url='http://localhost')
    state=client.get('/api/state').json()
    assert state['phone_present'] is False
    assert 'phone' not in state['missing_answers']
    assert 'work_eligibility' in state['missing_answers']
