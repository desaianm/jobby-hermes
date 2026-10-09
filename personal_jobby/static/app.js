'use strict';
const $=id=>document.getElementById(id);let state,current,reviewToken;
function note(text){$('message').textContent=text;}
async function api(path,method='GET',body){const r=await fetch(path,{method,headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));return data;}
function values(form){return Object.fromEntries(new FormData(form));}
function list(el,items){el.replaceChildren();for(const text of items){const li=document.createElement('li');li.textContent=text;el.append(li);}}
function populate(form,data){for(const [key,value]of Object.entries(data)){const e=form.elements.namedItem(key);if(!e)continue;if(e.type==='checkbox')e.checked=Boolean(value);else e.value=Array.isArray(value)?value.join('\n'):value??'';}}
async function refresh(){await refreshDaily();state=await api('/api/state');populate($('settings'),state.settings);populate($('answers'),state.profile.answers);$('phone-status').textContent='Phone: '+(state.phone_present?'saved privately':'not saved')+' · Required only when the actual employer form requires it';$('identity').textContent=state.profile.name+' · '+state.profile.contact;$('missing').textContent='Missing answers: '+(state.missing_answers.join(', ')||'none supplied as unknown')+' · Criteria '+(state.settings.criteria_confirmed?'confirmed':'PROVISIONAL');$('provenance').textContent=state.settings.provenance+' · Permanent full-time only';$('criteria-state').textContent=state.settings.criteria_confirmed?'CONFIRMED':'PROVISIONAL until confirmed';list($('facts'),state.profile.facts.map(f=>f.id+' — '+f.text));$('jobs').replaceChildren();for(const j of state.jobs){const card=document.createElement('div');card.className='job';const b=document.createElement('button');b.textContent=j.company+' / '+j.title+' — '+j.status+' · '+j.eligibility;b.addEventListener('click',()=>run(()=>detail(j.id)));const p=document.createElement('p');p.textContent=j.explanation.join('; ');card.append(b,p);$('jobs').append(card);}if(!state.jobs.length)$('jobs').textContent='No listings yet. Add a posting or explicitly run search.';}
async function detail(id){current=id;const d=await api('/api/jobs/'+id);reviewToken=d.job.materials?.review_token;$('detail').hidden=false;renderAttempts(d.job);$('jobtitle').textContent=d.job.company+' / '+d.job.title;$('jobstatus').textContent=d.job.status+' · Eligibility: '+d.job.eligibility+' — '+d.job.explanation.join('; ');list($('blockers'),d.job.blockers);$('posting').href=d.job.job_url;$('description').textContent=d.job.description;populate($('salary'),d.job.salary);populate($('fit'),d.job);$('qa-state').textContent='Document QA: '+(d.job.materials?.qa_state||'not generated');$('history').textContent=d.events.map(e=>e.at+' '+e.kind+'\n'+e.data).join('\n\n');$('downloads').replaceChildren();$('resume-preview').hidden=!d.job.materials;if(d.job.materials)$('resume-preview').src='/api/jobs/'+id+'/artifacts/preview.png?version='+encodeURIComponent(d.job.materials.created);for(const n of (d.job.materials?['resume.pdf','resume.docx','cover_letter.pdf','cover_letter.docx','evidence.json','metadata.json','posting.json','preview.png','cover_preview.png']:[])){const a=document.createElement('a');a.href='/api/jobs/'+id+'/artifacts/'+n;a.textContent=n;a.target='_blank';a.rel='noopener';$('downloads').append(a);} $('detail').scrollIntoView({behavior:'smooth'});}
async function run(fn){try{note('Working…');const result=await fn();if(result==='keep-message')return;note('Saved / completed. No application was submitted.');}catch(e){note('Error: '+e.message);}}
function submit(id,fn){$(id).addEventListener('submit',e=>{e.preventDefault();run(()=>fn(values(e.target)));});}
submit('settings',async d=>{for(const key of ['target_terms','locations','blacklist'])d[key]=d[key].split('\n').map(x=>x.trim()).filter(Boolean);d.minimum=Number(d.minimum);d.criteria_confirmed=$('settings').elements.criteria_confirmed.checked;d.submission_desired=$('settings').elements.submission_desired.checked;await api('/api/settings','PUT',d);await refresh();});
submit('answers',async d=>{await api('/api/profile/answers','PUT',d);await refresh();});
submit('phone',async d=>{d.clear=$('phone').elements.clear.checked;try{await api('/api/profile/phone','PUT',d);}finally{$('phone').reset();}await refresh();});
submit('add',async d=>{const raw=d.raw;delete d.raw;d.salary={raw,origin:'unknown',verified:false};const j=await api('/api/jobs','POST',d);$('add').reset();await refresh();await detail(j.id);});
submit('search',async d=>{d.limit=Number(d.limit);const r=await api('/api/search','POST',d);await refresh();note('Search returned '+r.jobs.length+' stored listings. '+r.message+(r.errors.length?' Row errors: '+r.errors.join('; '):''));return 'keep-message';});
submit('fit',async d=>{d.qualifications_reviewed=$('fit').elements.qualifications_reviewed.checked;await api('/api/jobs/'+current+'/fit','PUT',d);await refresh();await detail(current);});
submit('salary',async d=>{for(const k of ['lower','upper'])d[k]=d[k]===''?null:Number(d[k]);for(const k of ['currency','unit','kind'])d[k]=d[k]||null;d.verified=$('salary').elements.verified.checked;await api('/api/jobs/'+current+'/salary','PUT',d);await refresh();await detail(current);});
$('prepare').addEventListener('click',()=>run(async()=>{await api('/api/jobs/'+current+'/prepare','POST',{});await refresh();await detail(current);}));
submit('approval',async d=>{d.review_token=reviewToken;await api('/api/jobs/'+current+'/visual-approval','POST',d);await detail(current);});
submit('track',async d=>{await api('/api/jobs/'+current+'/status','PATCH',d);await refresh();await detail(current);});
submit('receipt',async d=>{d.attempt_id=d.attempt_id||null;await api('/api/jobs/'+current+'/receipt','POST',d);await refresh();await detail(current);});
refresh().then(()=>note('Private workspace ready. See daily controls for external executor status.')).catch(e=>note('Error: '+e.message));

function renderAttempts(job){
 const root=$('attempts');root.replaceChildren();const select=$('receipt-attempt');select.replaceChildren();
 const unknown=document.createElement('option');unknown.value='';unknown.textContent='User report: documents used unknown';select.append(unknown);
 const submitted=document.createElement('p');submitted.textContent='Submitted at: '+(job.submitted_at||'not recorded');root.append(submitted);
 for(const attempt of job.attempts||[]){
  const card=document.createElement('div');card.className='job';
  const p=document.createElement('p');p.textContent=attempt.operator+' · '+attempt.status+' · Submitted at: '+(attempt.submitted_at||'not submitted')+' · Documents: '+attempt.documents_used+' · Generation: '+(attempt.generation_id||'unknown');card.append(p);
  const option=document.createElement('option');option.value=attempt.id;option.textContent=attempt.id+' / '+attempt.operator+' / '+attempt.status;select.append(option);
  for(const [role,doc]of Object.entries(attempt.documents||{})){const a=document.createElement('a');a.href='/api/jobs/'+job.id+'/attempts/'+attempt.id+'/documents/'+doc.filename;a.textContent=role+' '+doc.filename+' · SHA256 '+doc.sha256;card.append(a,document.createElement('br'));}
  for(const shot of attempt.screenshots||[]){const a=document.createElement('a');a.href='/api/jobs/'+job.id+'/attempts/'+attempt.id+'/screenshots/'+shot.id;a.textContent=shot.kind+' screenshot · '+shot.at+' · QA: '+shot.qa_note+' · SHA256 '+shot.sha256;card.append(a,document.createElement('br'));}
  const timeline=document.createElement('pre');timeline.textContent=attempt.timeline.map(e=>e.at+' / '+e.kind+' / '+JSON.stringify(e.data)).join('\n');card.append(timeline);root.append(card);
 }
}

async function refreshDaily(){
 const d=await api('/api/daily');const p=d.policy;
 $('daily-status').textContent='Hermes cron agent: '+(p.enabled?'enabled in configuration':'disabled')+' · Schedule: '+(p.schedule||'not configured')+' · '+p.timezone+' · Cron ID: '+(p.cron_job_id||'not configured')+' · '+d.capability;
 $('daily-counts').textContent='Toronto day '+d.latest_outcomes.day+' · Reserved '+d.latest_outcomes.attempted_submissions_today+'/'+p.max_submissions_per_day+' · Confirmed '+d.confirmed_today+' · Pending '+d.pending_count+' · Uncertain '+d.uncertain_count+' · Latest run: '+(d.latest_run?(d.latest_run.status==='running'&&!d.latest_outcomes.lease_active?'lease expired':d.latest_run.status):'none');
 list($('daily-holds'),[...d.holds,...d.unresolved_submissions.map(r=>'Job '+r.job_id+' · '+r.state+' · '+(r.reason||'Await guarded receipt; no retry'))]);
 $('daily-events').textContent=d.latest_outcomes.events.map(e=>e.at+' · '+e.kind+(e.job_id?' · Job '+e.job_id:'')+(e.reason?' · '+e.reason:'')+(e.source_url?' · '+e.source_url:'')).join('\n')||'No runs recorded.';
}

setInterval(()=>refreshDaily().catch(()=>{}),30000);
