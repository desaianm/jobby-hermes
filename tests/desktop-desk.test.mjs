/** Module contracts and offline rendered SDK regressions; no native UI acceptance. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {SourceTextModule, SyntheticModule} from 'node:vm';
const require=createRequire((process.env.JOBBY_DESK_NODE_MODULES || '/home/adcan288/.hermes/hermes-agent/node_modules') + '/package.json');
const React=require('react');
const atom=value=>({get:()=>value,set:next=>{value=next;}});
const host={state:{connectionId:atom('local'),profile:atom('a'),focusedSessionProfile:atom('a'),focusedSessionOwner:atom(null)},navigate:path=>{host.path=path;}};
let activationEpoch=0;
const sdk={host,gatewayActivationEpoch:()=>activationEpoch,useValue:store=>store.get(),useQuery:()=>{throw Error('No renderer in contract test');},useMutation:()=>{},useQueryClient:()=>{},Button:'button',Input:'input',Textarea:'textarea',Badge:'span',Checkbox:'checkbox',Select:'select-root',SelectContent:'select-content',SelectItem:'select-item',SelectTrigger:'select-trigger',SelectValue:'select-value',ROUTES_AREA:'routes',SIDEBAR_NAV_AREA:'sidebar.nav',PALETTE_AREA:'palette'};
const sdkModule=new SyntheticModule(Object.keys(sdk),function(){for(const [key,value] of Object.entries(sdk))this.setExport(key,value);});
const reactModule=new SyntheticModule(['createElement','useState','useRef','useLayoutEffect'],function(){this.setExport('createElement',React.createElement);this.setExport('useState',initial=>[initial,()=>{}]);this.setExport('useRef',React.useRef);this.setExport('useLayoutEffect',()=>{});});
const module=new SourceTextModule(await readFile(new URL('../desktop/plugin.js',import.meta.url),'utf8'));
await module.link(name=>name==='@hermes/plugin-sdk'?sdkModule:reactModule);await module.evaluate();

test('desk is opt-in and reachable by route, sidebar and palette without backend work',()=>{
 const entries=[];const plugin=module.namespace.default;
 assert.equal(plugin.defaultEnabled,false);
 plugin.register({register:entry=>entries.push(entry),rest:()=>{throw Error('Registration must be lazy');}});
 assert.deepEqual(entries.map(entry=>entry.area),['routes','sidebar.nav','palette']);
 assert.equal(entries[0].data.path,'/jobby');assert.equal(entries[1].data.path,'/jobby');
 entries[2].data.run();assert.equal(host.path,'/jobby');
 const element=entries[0].render();assert.equal(element.type,module.namespace.Desk);
});

test('connection, profile and focused-profile transitions remount all private desk state',()=>{
 const ctx={source:'plugin:jobby'};
 const first=module.namespace.Desk({ctx});
 assert.deepEqual(JSON.parse(first.props.scope).slice(0,3),['local','a','a']);
 host.state.profile.set('b');
 const second=module.namespace.Desk({ctx});assert.notEqual(first.key,second.key);
 host.state.connectionId.set('other-host');
 const third=module.namespace.Desk({ctx});assert.notEqual(second.key,third.key);
 host.state.focusedSessionProfile.set('c');
 const fourth=module.namespace.Desk({ctx});assert.notEqual(third.key,fourth.key);
 assert.ok(fourth.key.startsWith(fourth.props.scope+':'));
});


test('same-name focused profiles on different connections retire private state',()=>{
 const before=module.namespace.Desk({ctx:{source:'plugin:jobby'}});
 host.state.focusedSessionOwner.set({connectionId:'different-focused-host',profile:'c'});
 const after=module.namespace.Desk({ctx:{source:'plugin:jobby'}});
 assert.notEqual(before.key,after.key);
});

test('same-name gateway reactivation changes the private desk scope',()=>{
 const before=module.namespace.Desk({ctx:{source:'plugin:jobby'}});
 activationEpoch++;
 const after=module.namespace.Desk({ctx:{source:'plugin:jobby'}});
 assert.notEqual(before.key,after.key);
});

test('harness completion requires all four exact saved/hash-verified downloads',async()=>{
 const {assertHarnessDownloads}=await import('../scripts/qualify_desktop_desk.mjs');
 const filenames=['resume.pdf','resume.docx','cover_letter.pdf','cover_letter.docx'];
 const complete=filenames.map(filename=>({filename,outcome:'saved_hash_verified',sha256:'a'.repeat(64)}));
 assert.throws(()=>assertHarnessDownloads([]));
 assert.throws(()=>assertHarnessDownloads(complete.slice(0,3)));
 assert.throws(()=>assertHarnessDownloads(complete.map(item=>({...item,outcome:'download_event_unavailable'}))));
 assert.throws(()=>assertHarnessDownloads([...complete.slice(0,3),complete[0]]));
 assert.doesNotThrow(()=>assertHarnessDownloads(complete));
});

test('qualification launcher keeps the normal Chromium sandbox',async()=>{
 const source=await readFile(new URL('../scripts/qualify_desktop_desk.mjs',import.meta.url),'utf8');
 assert.match(source,/chromiumSandbox\s*:\s*true/);
 assert.doesNotMatch(source,/--no-sandbox|--disable-setuid-sandbox|--disable-web-security/);
});

test('qualification teardown waits for its owned fixture child to exit',async()=>{
 const source=await readFile(new URL('../scripts/qualify_desktop_desk.mjs',import.meta.url),'utf8');
 assert.match(source,/await stopFixture\(api\)/);
 assert.match(source,/await new Promise\(.*server\.close/s);
});

test('native driver accepts only the parent-owned endpoint and exact renderer',async()=>{
 const {validateNativeTarget}=await import('../scripts/qualify_desktop_desk.mjs');
 assert.deepEqual(validateNativeTarget('http://127.0.0.1:19338','http://127.0.0.1:15274'),{endpoint:'http://127.0.0.1:19338',page:'http://127.0.0.1:15274/'});
 for(const endpoint of ['http://localhost:19338','http://127.0.0.1:9222','https://127.0.0.1:19338','http://127.0.0.1:19338/other','http://name:secret@127.0.0.1:19338']) assert.throws(()=>validateNativeTarget(endpoint,'http://127.0.0.1:15274'));
 for(const page of ['http://127.0.0.1:15275','http://127.0.0.1:15274/other','http://127.0.0.1:15274/?query=1']) assert.throws(()=>validateNativeTarget('http://127.0.0.1:19338',page));
});

test('owned fixture stop awaits real child termination',async()=>{
 const {spawn}=await import('node:child_process');
 const {stopFixture}=await import('../scripts/qualify_desktop_desk.mjs');
 const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'});
 await stopFixture(child);
 assert.ok(child.exitCode!==null || child.signalCode!==null);
 await stopFixture(child);
});

test('native qualification leaves host state and lifecycle with its parent',async()=>{
 const source=await readFile(new URL('../scripts/qualify_desktop_desk.mjs',import.meta.url),'utf8');
 const native=source.slice(source.indexOf('async function nativeJourney'),source.indexOf('export async function main'));
 assert.match(native,/connectOverCDP/);
 assert.match(native,/page\.url\(\) === target\.page/);
 assert.match(native,/window\.hermesDesktop\.api/);
 assert.doesNotMatch(native,/page\.route\(|\.fulfill\(|switchDeskProfile|\.newContext\(|\.newPage\(|page\.close\(|context\.close\(/);
 assert.match(native,/native_connection_disconnected = true/);
});

test('browser scratch path stays short and private and is removed after failed work',async()=>{
 const {withBrowserTemp}=await import('../scripts/qualify_desktop_desk.mjs');
 assert.equal(typeof withBrowserTemp,'function');
 const {stat}=await import('node:fs/promises');
 let scratch;
 const previousTemp=process.env.TMPDIR;
 await assert.rejects(()=>withBrowserTemp(async path=>{
   scratch=path;
   assert.equal(process.env.TMPDIR,path);
   assert.ok(path.startsWith('/home/adcan288/tmp/jobby-hackathon-20261107/worker/b-'));
   assert.ok(Buffer.byteLength(path+'/com.google.Chrome.XXXXXX/SingletonSocket')<108);
   assert.equal((await stat(path)).mode&0o777,0o700);
   throw new Error('simulated browser failure');
 }),/simulated browser failure/);
 await assert.rejects(()=>stat(scratch),{code:'ENOENT'});
 assert.equal(process.env.TMPDIR,previousTemp);
 assert.equal(await withBrowserTemp(async path=>{scratch=path;return 'completed';}),'completed');
 await assert.rejects(()=>stat(scratch),{code:'ENOENT'});
 assert.equal(process.env.TMPDIR,previousTemp);
 const source=await readFile(new URL('../scripts/qualify_desktop_desk.mjs',import.meta.url),'utf8');
 assert.match(source,/withBrowserTemp\(async browserTemp/);
 assert.match(source,/TMPDIR\s*[:=]\s*browserTemp/);
 assert.doesNotMatch(source,/TMPDIR\s*[:=]\s*output/);
});

test('native exact target accepts the observed Jobby hash route only',async()=>{
 const {validateNativeTarget}=await import('../scripts/qualify_desktop_desk.mjs');
 const target='http://127.0.0.1:15274/#/jobby';
 assert.deepEqual(validateNativeTarget('http://127.0.0.1:19338',target),{endpoint:'http://127.0.0.1:19338',page:target});
 for(const page of ['http://127.0.0.1:15274/#/other','http://127.0.0.1:15274/#/%6aobby','http://127.0.0.1:15274/%23/jobby','http://127.0.0.1:15274/#/jobby?x=1','http://127.0.0.1:15274/?x=1#/jobby','http://127.0.0.1:15275/#/jobby','http://localhost:15274/#/jobby']) assert.throws(()=>validateNativeTarget('http://127.0.0.1:19338',page));
});

test('harness runs the delayed selected-job download regression after its real primary journey',async()=>{
 const {delayedSelectedJobDownload}=await import('../scripts/qualify_desktop_desk.mjs');
 assert.equal(typeof delayedSelectedJobDownload,'function');
 const source=await readFile(new URL('../scripts/qualify_desktop_desk.mjs',import.meta.url),'utf8');
 const harness=source.slice(source.indexOf('  await page.goto(base);'));
 assert.ok(harness.indexOf('await primaryJourney(')<harness.indexOf('await delayedSelectedJobDownload(page, receipt)'));
 const native=source.slice(source.indexOf('async function nativeJourney'),source.indexOf('export async function main'));
 assert.doesNotMatch(native,/delayedSelectedJobDownload/);
 const regression=source.slice(source.indexOf('export async function delayedSelectedJobDownload'),source.indexOf('async function nativeJourney'));
 assert.match(regression,/await route\.fetch\(\)/);
 assert.match(regression,/await held;\s*await route\.fulfill\(\{ response \}\)/);
 assert.match(regression,/await inFlight;\s*if \(retire\) await retire/);
 assert.match(regression,/else \{\s*await savedB\.click\(\)/);
 assert.match(regression,/getMutationCache\(\)\.subscribe/);
 assert.match(regression,/assert\.deepEqual\(observed\.download_starts, \[\]/);
 assert.match(regression,/assert\.deepEqual\(observed\.download_events, \[\]/);
 assert.match(regression,/assert\.deepEqual\(observed\.completion_notices, \[\]/);
 assert.match(regression,/assert\.deepEqual\(observed\.query_updates_after_release, \[\]/);
 assert.match(harness,/assertHarnessDownloads\(receipt.downloads\)/);
 for(const key of ['delayed_regenerated_download','profile_roundtrip','profile_batched_roundtrip','connection_roundtrip','focused_owner_roundtrip','same_name_connection_activation','delayed_retired_preview_query']) assert.ok(harness.includes(key),key);
 assert.doesNotMatch(regression,/waitForTimeout|setTimeout\(ok|force:\s*true/);
});

test('first-use search setup shows grounded evidence and requires explicit provider choices',()=>{
 const save=[];
 const data={confirmed:false,source_token:'a'.repeat(64),preferences:null,queries:[],proposals:[{term:'Python',evidence:[{fact_id:'skills-1',excerpt:'Python, FastAPI',role:''}]}],warnings:[],shortlist:[]};
 assert.equal(typeof module.namespace.SearchSetup,'function');
 const view=module.namespace.SearchSetup({data,busy:false,confirm:value=>save.push(value)});
 const nodes=[];
 const visit=value=>{if(!value || typeof value!=='object')return;if(Array.isArray(value)){value.forEach(visit);return;}nodes.push(value);visit(value.props?.children);};
 visit(view);
 const labels=nodes.filter(n=>n.type==='label').map(n=>n.props.children);
 const serialized=JSON.stringify(view);
 assert.match(serialized,/Python, FastAPI/);
 assert.match(serialized,/Canada only/);
 assert.doesNotMatch(serialized,/Toronto|120000|CAD/);
 for(const label of ['Search location in Canada','Freshness in hours','Results per query','Total results per run']) assert.ok(serialized.includes(label),label);
 assert.ok(nodes.some(n=>n.type==='button' && n.props.disabled && n.props.children==='Confirm search setup'));
 assert.equal(save.length,0);
});

test('replaced resume starts query selection from its current evidence',()=>{
 const data={confirmed:false,source_token:'b'.repeat(64),preferences:null,queries:['AI Engineer'],proposals:[{term:'Python',evidence:[{fact_id:'new-skills',excerpt:'Python',role:''}]}],warnings:[],shortlist:[]};
 const view=module.namespace.SearchSetup({data,busy:false,confirm:()=>{}});
 const nodes=[];
 const visit=value=>{if(!value || typeof value!=='object')return;if(Array.isArray(value)){value.forEach(visit);return;}nodes.push(value);visit(value.props?.children);};
 visit(view);
 assert.equal(nodes.filter(n=>n.type==='checkbox')[0].props.checked,true,'Current supported query must replace the previous source selection');
});

test('discovery retirement records distinguish connection roundtrip from same-name activation and refuse overwrite',async()=>{
 const {recordDiscoveryRetirement}=await import('../scripts/qualify_desktop_desk.mjs');
 assert.equal(typeof recordDiscoveryRetirement,'function','Driver must expose its actual retirement recorder');
 const receipt={};
 for(const operation of ['inspect','confirm','search']) {
   const roundtrip=recordDiscoveryRetirement(receipt,operation,'switchDeskConnection','other-harness',false);
   roundtrip.real_response_held=true;
   roundtrip.passed=true;
   const activation=recordDiscoveryRetirement(receipt,operation,'switchDeskConnection','harness',false);
   assert.notEqual(roundtrip,activation);
   assert.ok(Object.values(receipt).includes(roundtrip),'Connection roundtrip evidence must survive activation');
   assert.deepEqual([roundtrip.operation,roundtrip.switcher,roundtrip.target,roundtrip.batched],[operation,'switchDeskConnection','other-harness',false]);
   assert.deepEqual([activation.operation,activation.switcher,activation.target,activation.batched],[operation,'switchDeskConnection','harness',false]);
   assert.equal(activation.passed,false);
   assert.throws(()=>recordDiscoveryRetirement(receipt,operation,'switchDeskConnection','other-harness',false),/duplicate/i);
   assert.equal(roundtrip.passed,true);
 }
 assert.equal(Object.keys(receipt).length,6);
});

test('harness discovery acceptance requires every identified operation and transition',async()=>{
 const {recordDiscoveryRetirement,assertHarnessDiscoveryRetirements}=await import('../scripts/qualify_desktop_desk.mjs');
 assert.equal(typeof assertHarnessDiscoveryRetirements,'function');
 const receipt={scope:'test observation only',discovery_journey:{persistent_shortlist:true}};
 for(const operation of ['inspect','confirm','search']) {
   for(const [switcher,target,batched] of [['switchDeskProfile','b',false],['switchDeskProfile','b',true],['switchDeskConnection','other-harness',false],['switchDeskOwner','other-focused-harness',false],['switchDeskConnection','harness',false]]) {
     Object.assign(recordDiscoveryRetirement(receipt,operation,switcher,target,batched),{passed:true,real_response_held:true,query_updates_after_release:[],mutation_outcome:operation==='inspect'?null:'error'});
   }
 }
 assert.equal(Object.keys(receipt).length,17);
 assert.doesNotThrow(()=>assertHarnessDiscoveryRetirements(receipt));
 assert.throws(()=>assertHarnessDiscoveryRetirements({}));
 const keys=Object.keys(receipt).filter(key=>key!=='scope' && key!=='discovery_journey');
 for(const key of keys) {
   const missing={...receipt};delete missing[key];
   assert.throws(()=>assertHarnessDiscoveryRetirements(missing),key);
   for(const change of [{passed:false},{real_response_held:false},{target:'wrong-target'},{batched:'false'},{query_updates_after_release:[['stale']]},{mutation_outcome:'success'}]) {
     assert.throws(()=>assertHarnessDiscoveryRetirements({...receipt,[key]:{...receipt[key],...change}}),key);
   }
 }
 const connection=keys.find(key=>receipt[key].target==='other-harness');
 const activation=keys.find(key=>receipt[key].target==='harness');
 assert.throws(()=>assertHarnessDiscoveryRetirements({...receipt,[connection]:receipt[activation]}));
 assert.throws(()=>assertHarnessDiscoveryRetirements({...receipt,discovery_unexpected:{passed:true}}));
});

test('live qualification is explicit and requires both exact owned native arguments',async()=>{
 const {parseQualificationMode}=await import('../scripts/qualify_desktop_desk.mjs');
 assert.equal(typeof parseQualificationMode,'function');
 const target=['--native-cdp','http://127.0.0.1:19338','--native-page','http://127.0.0.1:15274/#/jobby'];
 assert.deepEqual(parseQualificationMode([]),{mode:'harness',target:null});
 assert.equal(parseQualificationMode(target).mode,'native-cdp');
 assert.equal(parseQualificationMode(['--native-live',...target,'--live-home','/home/adcan288/tmp/jobby-live-acceptance-20261107/home']).mode,'native-live');
 assert.equal(parseQualificationMode([...target,'--native-live','--live-home','/home/adcan288/tmp/jobby-live-acceptance-20261107/home']).mode,'native-live');
 for(const flags of [['--native-live'],['--native-live',...target.slice(0,2)],['--native-live',...target,'--native-live'],['--live',...target],['--native-live',...target.slice(0,3),'http://localhost:15274/#/jobby'],['--native-live','--native-cdp','http://127.0.0.1:9222',...target.slice(2)]]) assert.throws(()=>parseQualificationMode(flags));
});

test('live route returns before native fictional generation and harness bootstrap',async()=>{
 const source=await readFile(new URL('../scripts/qualify_desktop_desk.mjs',import.meta.url),'utf8');
 const main=source.slice(source.indexOf('export async function main'));
 assert.match(main,/if \(mode === 'native-live'\) \{ await nativeLiveJourney\(playwright, native, output, receipt, \{ liveHome, python \}\); return; \}/);
 assert.ok(main.indexOf("if (mode === 'native-live')")<main.indexOf('await nativeJourney('));
 assert.ok(main.indexOf("if (mode === 'native-live')")<main.indexOf('const requireDeps'));
 const live=source.slice(source.indexOf('async function nativeLiveJourney'),source.indexOf('async function nativeJourney'));
 assert.ok(live.length>0);
 assert.match(source.slice(source.indexOf('export async function withNativeActions'),source.indexOf('async function nativeLiveJourney')),/window\.hermesDesktop\.api/);
 assert.match(live,/new MutationObserver/);
 assert.match(live,/assertNativeLiveRun/);
 assert.match(live,/await reload\(\{ reacquire: true, ready:/);
 assert.match(live,/await readNativePrivate\(\{ \.\.\.privateInput, operation: 'status' \}\)/);
 assert.match(live,/await readNativePrivate\(\{ \.\.\.privateInput, operation: 'show', jobId: id \}\)/);
 assert.match(live,/bindNativeDossier\(first, shown, last, currentSetup, status\)/);
 assert.match(live,/await verifyNativeArtifacts\(privateInput.liveHome, shown\)/);
 assert.doesNotMatch(live,/\.job\.attempts|\.job\.original_source|item\.events/);
 assert.doesNotMatch(live,/spawn\(|createServer\(|page\.route\(|\.fulfill\(|route\.fetch|page\.request|primaryJourney\(|source_documents|fictional-source|switchDesk|\.newPage\(|\.newContext\(|page\.goto\(|method:\s*['"]POST|dispatch\(/);
});

test('live run requires exact confirmed bounds and new observations beyond the prior event watermark',async()=>{
 const {assertNativeLiveSetup,assertNativeLiveRun}=await import('../scripts/qualify_desktop_desk.mjs');
 assert.equal(typeof assertNativeLiveSetup,'function');
 assert.equal(typeof assertNativeLiveRun,'function');
 // Contract data only; never used as a provider or native acceptance receipt.
 const setup={ok:true,confirmed:true,submission_available:false,source_token:'a'.repeat(64),queries:['Python'],preferences:{country:'Canada',location:'Toronto, ON, Canada',remote:false,hours_old:720,per_query:5,total:5,order:'newest'},proposals:[{term:'Python',evidence:[{fact_id:'skills-1',excerpt:'Python-based Jobby CLI'}]}]};
 assert.doesNotThrow(()=>assertNativeLiveSetup(setup));
 for(const change of [{confirmed:false},{submission_available:true},{queries:['AI Engineer']},{source_token:null},{proposals:[]},{preferences:{...setup.preferences,total:25}}]) assert.throws(()=>assertNativeLiveSetup({...setup,...change}));
 const job={id:1,job_url:'https://ca.indeed.com/viewjob?jk=contract',matching_terms:['python'],evidence:[{fact_id:'skills-1',excerpt:'Python-based Jobby CLI',matching_terms:['python']}]};
 const after={...setup,last_run:{outcome:'completed',queries:[{term:'Python',requested:5,stored:1}],errors:[],requested:5,unique_jobs_observed:1},shortlist:[job]};
 const dossiers=[{public:{ok:true,job:{id:1,job_url:job.job_url}},audit:{job_id:1,job_url:job.job_url,site:'indeed',attempt_count:0,events:[{id:11,kind:'discovery_observed',query:'Python'}]}}];
 assert.deepEqual(assertNativeLiveRun(setup,after,10,dossiers).map(item=>item.id),[1]);
 assert.throws(()=>assertNativeLiveRun(setup,after,11,dossiers),'Stale observations must fail even with a nonempty shortlist');
 assert.throws(()=>assertNativeLiveRun(setup,{...after,source_token:'b'.repeat(64)},10,dossiers));
 for(const last_run of [null,{...after.last_run,unique_jobs_observed:0},{...after.last_run,outcome:'failed'},{...after.last_run,queries:[]},{...after.last_run,requested:25},{...after.last_run,errors:[{code:'source_failed'}]}]) assert.throws(()=>assertNativeLiveRun(setup,{...after,last_run},10,dossiers));
 assert.throws(()=>assertNativeLiveRun(setup,after,10,[]));
 assert.throws(()=>assertNativeLiveRun(setup,after,10,[...dossiers,...dossiers]));
 for(const audit of [{...dossiers[0].audit,job_url:'https://ca.indeed.com/viewjob?jk=other'},{...dossiers[0].audit,site:'linkedin'},{...dossiers[0].audit,attempt_count:1}]) assert.throws(()=>assertNativeLiveRun(setup,after,10,[{...dossiers[0],audit}]));
 assert.throws(()=>assertNativeLiveRun(setup,{...after,shortlist:[{...job,evidence:[]}]},10,dossiers));
 assert.throws(()=>assertNativeLiveRun(setup,{...after,shortlist:[{...job,job_url:'https://jobs.example.test/fake'}]},10,dossiers));
});

test('live download receipt separates native dialog/events from four exact saved files',async()=>{
 const {nativeLiveDownloadOutcome}=await import('../scripts/qualify_desktop_desk.mjs');
 assert.equal(typeof nativeLiveDownloadOutcome,'function');
 const downloads=['resume.pdf','resume.docx','cover_letter.pdf','cover_letter.docx'].map(filename=>({filename,job_id:1,generation_id:'a'.repeat(32),expected_sha256:'b'.repeat(64),initiated_via_visible_control:true,os_save_verified:true,outcome:'saved_hash_verified',sha256:'b'.repeat(64)}));
 assert.equal(nativeLiveDownloadOutcome(downloads),'desk_passed_pending_operator_review');
 for(const outcome of ['native_dialog_pending','download_event_unavailable']) {
   const pending=downloads.map(item=>({...item,outcome,os_save_verified:false,sha256:undefined}));
   assert.equal(nativeLiveDownloadOutcome(pending),'pending_native_saves');
   assert.throws(()=>nativeLiveDownloadOutcome(pending.map(item=>({...item,os_save_verified:true}))));
 }
 assert.throws(()=>nativeLiveDownloadOutcome([]));
 assert.throws(()=>nativeLiveDownloadOutcome(downloads.slice(0,3)));
 assert.throws(()=>nativeLiveDownloadOutcome([...downloads.slice(0,3),downloads[0]]));
 for(const change of [{sha256:'c'.repeat(64)},{os_save_verified:false},{initiated_via_visible_control:false},{job_id:2},{generation_id:'c'.repeat(32)},{expected_sha256:null}]) assert.throws(()=>nativeLiveDownloadOutcome([{...downloads[0],...change},...downloads.slice(1)]));
});

function liveContract() {
 const setup={ok:true,confirmed:true,submission_available:false,source_token:'a'.repeat(64),queries:['Python'],preferences:{country:'Canada',location:'Toronto, ON, Canada',remote:false,hours_old:720,per_query:5,total:5,order:'newest'},proposals:[{term:'Python',evidence:[{fact_id:'skills-1',excerpt:'Python-based Jobby CLI'}]}]};
 const job={id:7,company:'Synthetic',title:'Python Engineer',job_url:'https://ca.indeed.com/viewjob?jk=synthetic',location:'Toronto',description:'Python',status:'discovered',explanation:[],attempts:[],original_source:{site:'indeed',job_url:'https://ca.indeed.com/viewjob?jk=synthetic'}};
 const shown={job,events:[{id:23,job_id:7,kind:'discovery_observed',data:'{"query":"Python","private_extra":"withheld"}'}],materials:null,current_artifact_directory:null};
 const status={candidate_initialized:true,fact_count:1,settings:{discovery:{source_token:setup.source_token,queries:setup.queries,preferences:setup.preferences}}};
 return {setup,shown,status};
}

async function withRenderedNativeDesk(action,{posting=false,documents=false,evidenceRole}={}) {
 const {withBrowserTemp}=await import('../scripts/qualify_desktop_desk.mjs');
 const {mkdtemp,mkdir,writeFile,rm}=await import('node:fs/promises');
 const {join,dirname}=await import('node:path');
 const {EventEmitter}=await import('node:events');
 const {PassThrough}=await import('node:stream');
 const {setup,status}=liveContract();
 if(evidenceRole!==undefined)setup.proposals[0].evidence=[{fact_id:'experience-1',role:evidenceRole,excerpt:'Built a Python-based Jobby CLI'}];
 const home=await mkdtemp('/home/adcan288/tmp/jobby-live-acceptance-20261107/driver-contract-fix/readback-');
 await mkdir(join(home,'plugin-data/jobby/workspace'),{recursive:true,mode:0o700});
 try {
  await withBrowserTemp(async scratch=>{
   const modules=dirname(require.resolve('esbuild/package.json'))+'/..';
   const desktop=join(modules,'../apps/desktop/src');
   const component=name=>JSON.stringify(join(desktop,'components/ui',name+'.tsx'));
   // Same host boundary and real UI/query libraries as the maintained harness.
   // All responses below are synthetic. No native renderer or provider is used.
   const bridge=join(scratch,'sdk-bridge.js');
   await writeFile(bridge,`
import {atom} from 'nanostores';
export {useStore as useValue} from '@nanostores/react';
export {useQuery,useMutation,useQueryClient} from '@tanstack/react-query';
export {Button} from ${component('button')};
export {Input} from ${component('input')};
export {Textarea} from ${component('textarea')};
export {Badge} from ${component('badge')};
export {Checkbox} from ${component('checkbox')};
export {Select,SelectContent,SelectItem,SelectTrigger,SelectValue} from ${component('select')};
export const ROUTES_AREA='routes',SIDEBAR_NAV_AREA='sidebar.nav',PALETTE_AREA='palette';
let activationEpoch=0;
export const gatewayActivationEpoch=()=>activationEpoch;
export const host={state:{connectionId:atom('harness'),profile:atom('a'),focusedSessionProfile:atom('a'),focusedSessionOwner:atom({connectionId:'harness',profile:'a'})}};
window.switchDeskProfile=value=>{host.state.profile.set(value);host.state.focusedSessionProfile.set(value);host.state.focusedSessionOwner.set({connectionId:'harness',profile:value});};
window.reactivateDesk=()=>{activationEpoch++;host.state.connectionId.set('harness');};
`);
   const entry=join(scratch,'entry.js');
   await writeFile(entry,`
import React from 'react';
import {createRoot} from 'react-dom/client';
import {flushSync} from 'react-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import plugin from ${JSON.stringify(new URL('../desktop/plugin.js',import.meta.url).pathname)};
import * as sdk from './sdk-bridge.js';
window.__HERMES_PLUGIN_SDK__=sdk;
window.searchStarts=[];
window.workStarts=[];
window.inputEvents=[];
window.addEventListener('click',event=>{window.lastClickTrusted=event.isTrusted;},true);
window.mount=({setup,posting,documents})=>{
 const job={id:7,title:'Synthetic Python Engineer',company:'Synthetic',location:'Toronto',description:'Synthetic Python',status:'discovered',job_url:'https://example.test/fixture'};
 const materials=documents?{generation_id:'a'.repeat(32),review_token:'b'.repeat(64),qa_state:'pending_visual_review',artifact_hashes:{},created:'Synthetic fixture'}:null;
 const dossier={ok:true,job,materials,next_action:documents?'review_exact_generation':'prepare_materials',submission_available:false};
 const discovery={...setup,warnings:[],shortlist:posting?[{...job,matching_terms:['python'],evidence:[],unknowns:[],unmatched_posting_terms:[]}]:[],last_run:null,ranking_method:'Synthetic offline fixture'};
 const overview={ok:true,source_status:'imported',jobs:posting?[job]:[],next_action:'intake_posting',submission_available:false};
 const ctx={source:'plugin:jobby',register:entry=>entries.push(entry),rest:async(path,options={})=>{
  if(path==='/desk' && (!options.method || options.method==='GET'))return structuredClone(overview);
  if(path==='/desk/7')return structuredClone(dossier);
  if(path==='/prepare' || (path==='/artifact' && /\\.(pdf|docx)$/.test(options.body.filename)))window.workStarts.push({operation:path==='/prepare'?'prepare':options.body.filename,profile:sdk.host.state.profile.get(),trusted:window.lastClickTrusted});
  if(path==='/prepare')return structuredClone(dossier);
  if(path==='/artifact')return {ok:true,...materials,filename:options.body.filename,content_type:'application/octet-stream',base64:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jM1sAAAAASUVORK5CYII=',evidence:{evidence:[],gaps:[]}};
  if(path==='/discovery'){
   if(options.method==='POST'){
    if(options.body.operation!=='search')throw Error('Unexpected offline operation');
    window.searchStarts.push({profile:sdk.host.state.profile.get(),trusted:window.lastClickTrusted});
   }
   return structuredClone(discovery);
  }
  throw Error('Outside offline fixture boundary');
 }};
 const entries=[];plugin.register(ctx);
 window.hermesDesktop={api:({path,method})=>ctx.rest(path.replace('/api/plugins/jobby',''),{method})};
 const root=createRoot(document.getElementById('app')),client=new QueryClient();
 let revision=0;
 const render=()=>root.render(React.createElement(QueryClientProvider,{client},React.cloneElement(entries.find(entry=>entry.id==='desk').render(),{key:++revision})));
 window.remountDesk=()=>flushSync(render);
 render();
};
`);
   const bundle=join(scratch,'bundle.js');
   await require('esbuild').build({entryPoints:[entry],outfile:bundle,bundle:true,format:'iife',jsx:'automatic',nodePaths:[modules],alias:{'@hermes/plugin-sdk':bridge,'@':desktop},define:{'process.env.NODE_ENV':'"production"'}});
   const {chromium}=await import(process.env.JOBBY_PLAYWRIGHT_MODULE || '/home/adcan288/hermes-secure-browser/control/node_modules/playwright-core/index.mjs');
   const browser=await chromium.launch({executablePath:process.env.JOBBY_TEST_CHROME || '/usr/bin/google-chrome',headless:true,chromiumSandbox:true,env:{...process.env,TMPDIR:scratch}});
   try {
    const page=await browser.newPage();
    await page.route('**/*',route=>route.abort());
    const mount=async()=>{
     await page.setContent('<div id="app"></div>');
     await page.addScriptTag({path:bundle});
     await page.evaluate(input=>window.mount(input),{setup,posting,documents});
     await page.getByRole('button',{name:'Search approved terms',exact:true}).waitFor();
    };
    await mount();
    // Execute the actual, unchanged journey, exposing its entry point through
    // the VM already used in this file. Only external CLI/attachment boundaries
    // are adapted. readNativePrivate still validates its synthetic owned home.
    const url=new URL('../scripts/qualify_desktop_desk.mjs',import.meta.url);
    const qualifier=new SourceTextModule((await readFile(url,'utf8'))+'\nexport {nativeLiveJourney};',{initializeImportMeta:meta=>{meta.url=url.href;}});
    await qualifier.link(async name=>{
     const values={...await import(name)};
     if(name==='node:child_process')values.spawn=(file,args,options)=>{
      assert.equal(file,'/home/adcan288/tmp/jobby-live-acceptance-20261107/runtime-native/bin/python');
      assert.deepEqual(args,['-I','-B','-m','personal_jobby','status','--brief']);
      assert.equal(options.cwd,home);
      const child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();child.kill=()=>true;
      queueMicrotask(()=>{child.stdout.end(JSON.stringify(status));child.emit('close',0,null);});
      return child;
     };
     return new SyntheticModule(Object.keys(values),function(){for(const [key,value]of Object.entries(values))this.setExport(key,value);});
    });
    await qualifier.evaluate();
    const runJourney=(attached,receipt={})=>qualifier.namespace.nativeLiveJourney(
     {chromium:{connectOverCDP:async()=>({contexts:()=>[{pages:()=>[attached]}],close:async()=>{}})}},
     {endpoint:'offline-test',page:page.url()},scratch,receipt,
     {liveHome:home,python:'/home/adcan288/tmp/jobby-live-acceptance-20261107/runtime-native/bin/python'}
    );
    await action({page,qualifier:qualifier.namespace,scratch,home,mount,runJourney});
   } finally {await browser.close();}
  });
 } finally {await rm(home,{recursive:true,force:true});}
}

test('native qualifier rejects Search in scope B after checking confirmed bounds in A',async()=>{
 await withRenderedNativeDesk(async({page,runJourney})=>{
  let transitioned=false;
  const attached=new Proxy(page,{get(target,key){
   if(key==='screenshot')return async options=>{
    await target.screenshot(options);
    if(options.path.endsWith('live-confirmed-search.png')){
     transitioned=true;
     await target.evaluate(()=>window.switchDeskProfile('b'));
     await target.getByRole('button',{name:'Search approved terms',exact:true}).waitFor();
    }
   };
   // Stop after the first action, regardless of whether its trusted input uses
   // a Locator or a retained ElementHandle. This is not an action interceptor.
   if(key==='waitForFunction')return (fn,arg,options)=>{
    if(options?.timeout===150000)throw Error('Offline test stops immediately after dispatch');
    return target.waitForFunction(fn,arg,options);
   };
   const value=Reflect.get(target,key);return typeof value==='function'?value.bind(target):value;
  }});
  let failure;
  try {await runJourney(attached);}
  catch(error){failure=error;}
  assert.equal(transitioned,true,'Must reach confirmed bounds in A before switching');
  assert.deepEqual(await page.evaluate(()=>window.searchStarts),[],'Retired qualification must start zero searches in B');
  assert.match(failure?.message || '',/scope|retired|activation/i,'Scope rejection must reach the caller');
  assert.deepEqual(await page.evaluate(()=>Object.keys(window).filter(key=>key.startsWith('__jobbyNativeAction_'))),[]);
 });
});

test('native qualifier accepts actual rendered evidence with optional roles',async t=>{
 const cases=[
  {role:'',text:'experience-1: Built a Python-based Jobby CLI',name:'empty role'},
  {role:'Software Engineer',text:'experience-1 · Software Engineer: Built a Python-based Jobby CLI',name:'nonempty role'}
 ];
 for(const {role,text,name}of cases)await t.test(name,async()=>{
  await withRenderedNativeDesk(async({page,runJourney})=>{
   page.setDefaultTimeout(3000);
   const search=page.getByRole('region',{name:'Resume search and shortlist'});
   await search.getByText(text,{exact:true}).waitFor();
   assert.equal(await search.getByText(text,{exact:true}).innerText(),text,'Observe the real component evidence before running the qualifier');
   const stop='Offline role test stops after trusted Search';
   const attached=new Proxy(page,{get(target,key){
    if(key==='setDefaultTimeout')return ()=>target.setDefaultTimeout(3000);
    if(key==='waitForFunction')return (fn,arg,options)=>{
     if(options?.timeout===150000)throw Error(stop);
     return target.waitForFunction(fn,arg,options);
    };
    const value=Reflect.get(target,key);return typeof value==='function'?value.bind(target):value;
   }});
   const receipt={};
   let failure;
   try {await runJourney(attached,receipt);}catch(error){failure=error;}
   assert.equal(receipt.stage,'live_search_requested','Rendered evidence must let the journey verify confirmed bounds and request Search');
   assert.deepEqual(await page.evaluate(()=>window.searchStarts),[{profile:'a',trusted:true}],'Evidence verification must reach an allowed trusted action');
   assert.equal(failure?.message,stop,'Only the deliberate post-action stop is accepted; a locator timeout is a failure');
   assert.deepEqual(await page.evaluate(()=>Object.keys(window).filter(key=>key.startsWith('__jobbyNativeAction_'))),[]);
  },{evidenceRole:role});
 });
});

test('native action dispatch checks trusted event interleavings and retired targets',async t=>{
 const scenarios=[
  {name:'current scope permits trusted Search',positive:true},
  {name:'scope changes after any awaited preflight',event:'pointerdown',change:'profile'},
  {name:'scope changes at trusted click dispatch',event:'click',change:'profile'},
  {name:'A to B to A before dispatch remains retired',before:true,change:'roundtrip'},
  {name:'A to B to A during dispatch remains retired',event:'click',change:'roundtrip'},
  {name:'same-name activation changes at dispatch',event:'click',change:'activation'},
  {name:'element replaced during trusted input',event:'pointerdown',change:'element'},
  {name:'document replaced during trusted input',event:'pointerdown',change:'document'}
 ];
 for(const scenario of scenarios)await t.test(scenario.name,async()=>{
  await withRenderedNativeDesk(async({page,qualifier})=>{
   page.setDefaultTimeout(3000);
   const search=page.getByRole('button',{name:'Search approved terms',exact:true});
   await page.evaluate(scenario=>{
    window.changeForTest=()=>{
     if(scenario.change==='profile' || scenario.change==='roundtrip')window.switchDeskProfile('b');
     if(scenario.change==='roundtrip')window.switchDeskProfile('a');
     if(scenario.change==='activation')window.reactivateDesk();
     if(scenario.change==='element')window.remountDesk();
     if(scenario.change==='document'){document.open();document.write('<p>Replaced offline document</p>');document.close();}
     window.changedForTest=true;
    };
    if(scenario.event)window.addEventListener(scenario.event,event=>{
     window.inputEvents.push({type:event.type,trusted:event.isTrusted});
     window.changeForTest();
    },{capture:true,once:true});
   },scenario);
   let failure;
   try {
    await qualifier.withNativeActions(page,async({click})=>{
     if(scenario.before)await page.evaluate(()=>window.changeForTest());
     await click(search);
    });
   } catch(error){failure=error;}
   if(scenario.positive){
    assert.equal(failure,undefined);
    assert.deepEqual(await page.evaluate(()=>window.searchStarts),[{profile:'a',trusted:true}]);
   } else {
    assert.equal(await page.evaluate(()=>window.changedForTest),true,'The intended interleaving must execute');
    if(scenario.event)assert.deepEqual(await page.evaluate(()=>window.inputEvents),[{type:scenario.event,trusted:true}]);
    assert.deepEqual(await page.evaluate(()=>window.searchStarts),[],'Retirement must prevent work before it begins');
    assert.match(failure?.message || '',/scope|retired|activation|target|attached|detached|context|trusted dispatch/i);
   }
   assert.deepEqual(await page.evaluate(()=>Object.keys(window).filter(key=>key.startsWith('__jobbyNativeAction_'))),[]);
  });
 });
});

test('native action dispatch refuses changes while trusted input waits for an enabled target',async t=>{
 for(const change of ['profile','activation','element','document'])await t.test(change,async()=>{
  await withRenderedNativeDesk(async({page,qualifier,mount})=>{
   page.setDefaultTimeout(3000);
   const button=page.getByRole('button',{name:'Search approved terms',exact:true});
   await button.evaluate(node=>{node.disabled=true;});
   let started;
   const waiting=new Promise(resolve=>{started=resolve;});
   // Cover both Locator and retained ElementHandle input. Signal only after the
   // real click starts; the target remains disabled until the intervention.
   const wrap=target=>new Proxy(target,{get(object,key){
    if(key==='click')return (...args)=>{const pending=object.click(...args);started();return pending;};
    if(key==='elementHandle')return async(...args)=>wrap(await object.elementHandle(...args));
    const value=Reflect.get(object,key);return typeof value==='function'?value.bind(object):value;
   }});
   let failure;
   await qualifier.withNativeActions(page,async({click})=>{
    const pending=click(wrap(button)).catch(error=>{failure=error;});
    await Promise.race([waiting,pending.then(()=>{throw Error('Input ended before the waiting interleaving');})]);
    if(change==='document'){
     await page.goto('about:blank');
     await mount(); // Same names/owner values, new document and real components.
    } else {
     await page.evaluate(change=>{
      if(change==='profile')window.switchDeskProfile('b');
      if(change==='activation')window.reactivateDesk();
      if(change==='element')window.remountDesk();
     },change);
     await button.waitFor();
     await button.evaluate(node=>{node.disabled=false;});
    }
    await pending;
   });
   assert.deepEqual(await page.evaluate(()=>window.searchStarts),[]);
   assert.match(failure?.message || '',/scope|retired|activation|target|attached|detached|context|destroyed/i,'Waiting input must reject rather than retarget');
   assert.deepEqual(await page.evaluate(()=>Object.keys(window).filter(key=>key.startsWith('__jobbyNativeAction_'))),[]);
  });
 });
});

test('native selection, Prepare and download use the same trusted scope gate',async t=>{
 for(const operation of ['selection','prepare','download'])for(const changed of [false,true])await t.test(`${operation}: ${changed?'retired':'current'} scope`,async()=>{
  await withRenderedNativeDesk(async({page,qualifier})=>{
   page.setDefaultTimeout(3000);
   const saved=page.getByRole('button',{name:'Synthetic Python Engineer · Synthetic',exact:true}).last();
   if(operation!=='selection'){
    await saved.click();
    await page.getByRole('heading',{name:'Synthetic Python Engineer · Synthetic',exact:true}).waitFor();
   }
   const target=operation==='selection'?saved:operation==='prepare'
    ?page.getByRole('button',{name:'Prepare documents',exact:true})
    :page.getByRole('region',{name:'Document dossier'}).locator('article').first().getByRole('button',{name:'Download PDF',exact:true});
   await target.waitFor();
   if(changed)await page.evaluate(()=>{
    window.addEventListener('click',event=>{
     window.inputEvents.push({type:event.type,trusted:event.isTrusted});
     window.switchDeskProfile('b');
    },{capture:true,once:true});
   });
   let failure;
   try {await qualifier.withNativeActions(page,({click})=>click(target));}catch(error){failure=error;}
   if(changed){
    assert.deepEqual(await page.evaluate(()=>window.inputEvents),[{type:'click',trusted:true}]);
    assert.match(failure?.message || '',/scope|retired|activation/i);
    assert.deepEqual(await page.evaluate(()=>window.workStarts),[]);
   } else {
    assert.equal(failure,undefined);
    if(operation==='selection')assert.equal(await saved.getAttribute('aria-pressed'),'true');
    else assert.deepEqual(await page.evaluate(()=>window.workStarts),[{operation:operation==='prepare'?'prepare':'resume.pdf',profile:'a',trusted:true}]);
   }
   assert.deepEqual(await page.evaluate(()=>Object.keys(window).filter(key=>key.startsWith('__jobbyNativeAction_'))),[]);
  },{posting:true,documents:operation==='download'});
 });
});

// Browser-boundary lifecycle fixture only. No native renderer, providers,
// private workspace or successful live-acceptance receipt is represented here.
async function offlineNativeLifecycle() {
 const {createContext,runInContext}=await import('node:vm');
 let context,state,navigation,onReload=()=>{};
 const reads=[];
 const install=(values={})=>{
  state={profile:'a',connectionId:'local',focused:'a',focusedOwner:{profile:'a',connectionId:'local'},epoch:1,...values};
  const listeners=new Map();
  const store=key=>({get:()=>state[key],set:value=>{state[key]=value;for(const listener of listeners.get(key)||[])listener();},listen:listener=>{
   if(!listeners.has(key))listeners.set(key,new Set());listeners.get(key).add(listener);return()=>listeners.get(key).delete(listener);
  }});
  const events=new Map();
  const window={
   __HERMES_PLUGIN_SDK__:{host:{state:{profile:store('profile'),connectionId:store('connectionId'),focusedSessionProfile:store('focused'),focusedSessionOwner:store('focusedOwner')}},gatewayActivationEpoch:()=>state.epoch},
   hermesDesktop:{api:async request=>{reads.push(structuredClone(request));return{ok:true,value:7};}},
   addEventListener:(type,fn)=>{if(!events.has(type))events.set(type,new Set());events.get(type).add(fn);},
   removeEventListener:(type,fn)=>events.get(type)?.delete(fn),
   location:{reload:()=>{for(const fn of events.get('pagehide')||[])fn();const next={...state,epoch:state.epoch+1};onReload(next);install(next);navigation?.();}}
  };
  context=createContext({window,document:{}});
 };
 install();
 const page={
  url:()=> 'http://127.0.0.1:15274/#/jobby',
  evaluate:async(fn,arg)=>{context.__argument=structuredClone(arg);return structuredClone(await runInContext('('+fn.toString()+')(__argument)',context));},
  waitForNavigation:()=>new Promise(ok=>{navigation=ok;}),
  waitForFunction:async fn=>{assert.equal(await page.evaluate(fn),true);}
 };
 return{page,reads,activate:()=>{state.epoch++;},change:async fn=>page.evaluate(fn),onReload:fn=>{onReload=fn;},keys:()=>Object.keys(context.window).filter(key=>key.startsWith('__jobbyNativeAction_'))};
}

test('owned explicit native reload reacquires scope before guarded read',async()=>{
 const {withNativeActions}=await import('../scripts/qualify_desktop_desk.mjs');
 const lifecycle=await offlineNativeLifecycle();
 await withNativeActions(lifecycle.page,async({read,reload})=>{
  assert.equal((await read('/discovery')).value,7);
  const oldKey=lifecycle.keys()[0];
  await reload({reacquire:true});
  assert.notEqual(lifecycle.keys()[0],oldKey,'Acquire a new guard; never revive the retired one');
  assert.equal((await read('/discovery')).value,7);
 });
 assert.equal(lifecycle.reads.length,2);
 assert.deepEqual(lifecycle.keys(),[]);
});

test('owned reload and reads reject wrong scope and unsolicited same-name activation',async t=>{
 const {withNativeActions}=await import('../scripts/qualify_desktop_desk.mjs');
 for(const key of ['profile','connectionId','focused','focusedOwner'])await t.test('reload changes '+key,async()=>{
  const lifecycle=await offlineNativeLifecycle();
  lifecycle.onReload(next=>{next[key]=key==='focusedOwner'?{profile:'b',connectionId:'local'}:'b';});
  await assert.rejects(()=>withNativeActions(lifecycle.page,async({read,reload})=>{
   await read('/desk');await reload({reacquire:true});await read('/desk');
  }),/scope changed across reload/);
  assert.equal(lifecycle.reads.length,1);assert.deepEqual(lifecycle.keys(),[]);
 });
 for(const when of ['before reload','after reload'])await t.test('unsolicited activation '+when,async()=>{
  const lifecycle=await offlineNativeLifecycle();
  await withNativeActions(lifecycle.page,async({read,reload})=>{
   if(when==='after reload')await reload({reacquire:true});
   lifecycle.activate();
   await assert.rejects(()=>read('/desk'),/scope retired/);
   await assert.rejects(()=>reload({reacquire:true}),/scope retired/);
  });
  assert.equal(lifecycle.reads.length,0);assert.deepEqual(lifecycle.keys(),[]);
 });
 await t.test('profile roundtrip stays retired before read',async()=>{
  const lifecycle=await offlineNativeLifecycle();
  await withNativeActions(lifecycle.page,async({read})=>{
   await lifecycle.change(()=>{const profile=window.__HERMES_PLUGIN_SDK__.host.state.profile;profile.set('b');profile.set('a');});
   await assert.rejects(()=>read('/discovery'),/scope retired/);
  });
  assert.equal(lifecycle.reads.length,0);
 });
});

test('native no-event save waits for exact confined bytes before next action or reload',async()=>{
 const {saveNativeDownload}=await import('../scripts/qualify_desktop_desk.mjs');
 const {mkdtemp,writeFile,rm}=await import('node:fs/promises');
 const {createHash}=await import('node:crypto');
 const output=await mkdtemp('/home/adcan288/tmp/jobby-hackathon-20261107/worker/native-save-test-');
 const bytes=Buffer.from('synthetic OS save bytes');
 const item={filename:'resume.pdf',expected_sha256:createHash('sha256').update(bytes).digest('hex'),os_save_verified:false,outcome:'download_event_unavailable'};
 const actions=[];let activated;
 const started=new Promise(ok=>{activated=ok;});
 try {
  const saving=saveNativeDownload({page:{waitForEvent:async()=>null},output,item,timeoutMs:1000},async()=>{actions.push('visible control');activated();}).then(saved=>{actions.push('next action/reload');return saved;});
  await started;await new Promise(ok=>setImmediate(ok));
  assert.deepEqual(actions,['visible control'],'No next action or reload before actual file bytes');
  await writeFile(output+'/resume.pdf',bytes,{flag:'wx',mode:0o600});
  assert.equal(await saving,true);
  assert.deepEqual(actions,['visible control','next action/reload']);
  assert.equal(item.sha256,item.expected_sha256);assert.equal(item.os_save_verified,true);
 } finally {await rm(output,{recursive:true,force:true});}
});

test('native save rejects absent, unsafe and changed bytes without certifying a save',async t=>{
 const {saveNativeDownload}=await import('../scripts/qualify_desktop_desk.mjs');
 const fs=await import('node:fs/promises');
 const {createHash}=await import('node:crypto');
 const bytes=Buffer.from('synthetic saved document'),expected=createHash('sha256').update(bytes).digest('hex');
 for(const kind of ['absent','preexisting','wrong bytes','symlink','directory','hardlink','foreign owner','retired scope','outside filename','outside directory','symlink ancestor','saveAs supported','saveAs unsupported'])await t.test(kind,async()=>{
  const output=await fs.mkdtemp('/home/adcan288/tmp/jobby-hackathon-20261107/worker/native-save-negative-');
  const path=output+'/resume.pdf';
  const item={filename:'resume.pdf',expected_sha256:expected,os_save_verified:false,outcome:'download_event_unavailable'};
  let activated=0,save=saveNativeDownload;
  const options={output,item,timeoutMs:100,page:{waitForEvent:async()=>null}};
  try {
   if(kind==='preexisting')await fs.writeFile(path,bytes);
   if(kind==='outside filename')item.filename='../resume.pdf';
   if(kind==='outside directory')options.output='/tmp';
   if(kind==='symlink ancestor'){await fs.symlink(output,output+'/alias');options.output=output+'/alias';}
   if(kind==='foreign owner'){
    const url=new URL('../scripts/qualify_desktop_desk.mjs',import.meta.url);
    const qualifier=new SourceTextModule(await readFile(url,'utf8'),{initializeImportMeta:meta=>{meta.url=url.href;}});
    await qualifier.link(async name=>{
     const values={...await import(name)};
     if(name==='node:fs/promises')values.lstat=async file=>{
      const info=await fs.lstat(file);
      return file===path?new Proxy(info,{get:(target,key)=>key==='uid'?process.getuid()+1:typeof target[key]==='function'?target[key].bind(target):target[key]}):info;
     };
     return new SyntheticModule(Object.keys(values),function(){for(const [key,value]of Object.entries(values))this.setExport(key,value);});
    });
    await qualifier.evaluate();save=qualifier.namespace.saveNativeDownload;
   }
   if(kind==='saveAs supported')options.page={waitForEvent:async()=>({suggestedFilename:()=>item.filename,saveAs:async destination=>{assert.equal(destination,path);await fs.writeFile(destination,bytes,{flag:'wx'});},failure:async()=>null})};
   if(kind==='saveAs unsupported')options.page={waitForEvent:async()=>({suggestedFilename:()=>item.filename,saveAs:async()=>{throw Error('acceptDownloads not supported');}})};
   const run=()=>save(options,async()=>{
    activated++;
    if(['wrong bytes','foreign owner','saveAs unsupported'].includes(kind))await fs.writeFile(path,kind==='wrong bytes'?'wrong':bytes);
    if(kind==='symlink'||kind==='hardlink'){
     await fs.writeFile(output+'/target',bytes);
     await fs[kind==='symlink'?'symlink':'link'](output+'/target',path);
    }
    if(kind==='directory')await fs.mkdir(path);
   });
   // Use an external scope check just like the real lifetime guard.
   let retired=false;
   if(kind==='retired scope'){
    options.check=async()=>{if(retired)throw Error('Owned native scope retired');};
    await assert.rejects(()=>save(options,async()=>{activated++;retired=true;}),/scope retired/);
   }else if(kind==='absent')assert.equal(await run(),false);
   else if(kind==='saveAs supported'||kind==='saveAs unsupported'){
    assert.equal(await run(),true);assert.equal(item.sha256,expected);assert.equal(item.os_save_verified,true);
   }else await assert.rejects(run,/preexist|hash mismatch|regular native save|Owned native save|filename|owned temporary path|symlink/i);
   if(!kind.startsWith('saveAs '))assert.equal(item.os_save_verified,false);
   if(['preexisting','outside filename','outside directory','symlink ancestor'].includes(kind))assert.equal(activated,0);
  } finally {await fs.rm(output,{recursive:true,force:true});}
 });
});

test('native reload checks the pinned scope in the same turn as navigation',async t=>{
 for(const changed of [false,true])await t.test(changed?'retired scope':'current scope',async()=>{
  await withRenderedNativeDesk(async({page,qualifier})=>{
   let navigations=0;
   page.on('framenavigated',()=>{navigations++;});
   let failure;
   try {
    await qualifier.withNativeActions(page,async({reload})=>{
     if(changed)await page.evaluate(()=>window.switchDeskProfile('b'));
     await reload();
    });
   }catch(error){failure=error;}
   if(changed){assert.match(failure?.message || '',/scope|retired/i);assert.equal(navigations,0);}
   else {assert.equal(failure,undefined);assert.equal(navigations,1);}
   assert.deepEqual(await page.evaluate(()=>Object.keys(window).filter(key=>key.startsWith('__jobbyNativeAction_'))),[]);
  });
 });
});

test('native audit binds genuine CLI show shape to the actual public_desk filter without exposing private fields',async()=>{
 const {execFile}=await import('node:child_process');
 const {promisify}=await import('node:util');
 const {bindNativeDossier}=await import('../scripts/qualify_desktop_desk.mjs');
 const {setup,shown,status}=liveContract();
 const publicValue=JSON.parse((await promisify(execFile)(new URL('../.venv/bin/python',import.meta.url).pathname,['-B','-c','import json,sys; from dashboard.plugin_api import public_desk; print(json.dumps(public_desk(json.loads(sys.argv[1]))))',JSON.stringify({ok:true,...shown,next_action:'prepare_materials',submission_available:false})],{cwd:new URL('..',import.meta.url),env:{PATH:'/usr/bin:/bin',PYTHON_DOTENV_DISABLED:'1'},maxBuffer:100000,timeout:10000})).stdout);
 assert.equal(publicValue.events,undefined);
 assert.equal(publicValue.job.attempts,undefined);
 assert.equal(publicValue.job.original_source,undefined);
 const bound=bindNativeDossier(publicValue,shown,structuredClone(publicValue),setup,status);
 assert.deepEqual(bound.public,publicValue);
 assert.equal(bound.audit.attempt_count,0);
 assert.equal(bound.audit.site,'indeed');
 assert.deepEqual(bound.audit.events,[{id:23,kind:'discovery_observed',query:'Python'}]);
 assert.ok(!JSON.stringify(bound).includes('private_extra'));
});

test('private readback admits the exact selected managed runtime tuple up to launch only',async()=>{
 const liveHome='/home/adcan288/tmp/jobby-live-acceptance-20261107/bundle-home';
 const python=liveHome+'/installs/65f699a597de2c44/environments/61b324b1922344b891a3f4c3fbc6483a/venv/bin/python';
 const base=liveHome+'/tools/python-3.14.9+20261021-linux-x64/bin/python3.14';
 const metadata={base,symlink:null,foreignOwner:null};
 const url=new URL('../scripts/qualify_desktop_desk.mjs',import.meta.url);
 // Explicit filesystem metadata only: never inspect the parent's live data,
 // execute Python or fake a successful process/readback.
 const qualifier=new SourceTextModule(await readFile(url,'utf8'),{initializeImportMeta:meta=>{meta.url=url.href;}});
 await qualifier.link(async name=>{
  const values={...await import(name)};
  if(name==='node:fs/promises')Object.assign(values,{
   lstat:async path=>({uid:process.getuid()+(path===metadata.foreignOwner?1:0),isSymbolicLink:()=>path===metadata.symlink,isDirectory:()=>true}),
   readdir:async()=>[],realpath:async path=>{assert.equal(path,python);return metadata.base;},
   mkdir:async()=>{throw Error('Deliberate test stop before output creation');}
  });
  return new SyntheticModule(Object.keys(values),function(){for(const [key,value]of Object.entries(values))this.setExport(key,value);});
 });
 await qualifier.evaluate();
 let reachedLaunch=false;
 await assert.rejects(()=>qualifier.namespace.readNativePrivate({liveHome,python,operation:'status'},file=>{
  assert.equal(file,python);reachedLaunch=true;throw Error('Deliberate test stop before process creation');
 }),/^Error: Private CLI launch failed$/);
 assert.equal(reachedLaunch,true);
 const args=['/home/adcan288/tmp/jobby-hackathon-20261107/worker/runtime-tuple-test-not-created',undefined,undefined,python,'--native-live','--native-cdp','http://127.0.0.1:19338','--native-page','http://127.0.0.1:15274/#/jobby','--live-home',liveHome];
 await assert.rejects(()=>qualifier.namespace.main(args),/^Error: Deliberate test stop before output creation$/);
 let unexpectedLaunches=0;
 const reject=(change,pattern)=>assert.rejects(()=>qualifier.namespace.readNativePrivate({liveHome,python,operation:'status',...change},()=>{unexpectedLaunches++;throw Error('Must reject before launch');}),pattern);
 for(const change of [
  {liveHome:'/home/adcan288/tmp/jobby-live-acceptance-20261107/home'},
  {liveHome:liveHome+'-other'},
  {liveHome:liveHome+'/../bundle-home'},
  {python:python.replace('61b324b1922344b891a3f4c3fbc6483a','another-environment')},
  {python:python.replace('65f699a597de2c44','another-install')},
  {python:python+'3'},
  {python:'/tmp/python'},
  {python:undefined},
  {python:'/home/adcan288/tmp/jobby-live-acceptance-20261107/runtime-native/bin/python'},
  {python:'/tmp/python',receipt:{ok:true,executable:python,resolved_base:base}}
 ])await reject(change,/installed runtime/);
 for(const changed of ['/usr/bin/python3',base.replace('3.14.9','3.14.8'),'/home/adcan288/.hermes/tools/python-3.14.9+20261021-linux-x64/bin/python3.14']){
  metadata.base=changed;await reject({},/interpreter changed/);
 }
 metadata.base=base;
 for(const path of [liveHome,liveHome+'/plugin-data',liveHome+'/plugin-data/jobby/workspace',python.slice(0,python.lastIndexOf('/'))]){
  metadata.symlink=path;await reject({},/symlink/);
 }
 metadata.symlink=null;
 for(const path of [liveHome,liveHome+'/plugin-data',python.slice(0,python.lastIndexOf('/'))]){
  metadata.foreignOwner=path;await reject({},/Owned temporary path/);
 }
 assert.equal(unexpectedLaunches,0);
});

test('private readback rejects unsafe homes before launch and confines sanitized children to show/status',async()=>{
 const {mkdtemp,mkdir,symlink,rm}=await import('node:fs/promises');
 const {join}=await import('node:path');
 const {EventEmitter}=await import('node:events');
 const {PassThrough}=await import('node:stream');
 const {readNativePrivate}=await import('../scripts/qualify_desktop_desk.mjs');
 const root=await mkdtemp('/home/adcan288/tmp/jobby-live-acceptance-20261107/driver-contract-fix/readback-');
 const home=join(root,'home'),workspace=join(home,'plugin-data/jobby/workspace');
 await mkdir(workspace,{recursive:true,mode:0o700});
 const python='/home/adcan288/tmp/jobby-live-acceptance-20261107/runtime-native/bin/python';
 const options={liveHome:home,python,operation:'show',jobId:7};
 const calls=[];
 const launch=(out='{}',code=0,err='',hang=false)=> (file,args,opts)=>{
   calls.push({file,args,opts});
   const child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();
   child.kill=()=>{queueMicrotask(()=>child.emit('close',null,'SIGKILL'));return true;};
   queueMicrotask(()=>{child.stdout.end(out);child.stderr.end(err);if(!hang) child.emit('close',code,null);});
   return child;
 };
 try {
   for(const liveHome of [undefined,'home','/tmp/home','/home/adcan288/.hermes',root+'/home/../home',root+'//home',root+'/home/']) await assert.rejects(()=>readNativePrivate({...options,liveHome},launch()));
   await symlink(home,join(root,'alias'));
   await assert.rejects(()=>readNativePrivate({...options,liveHome:join(root,'alias')},launch()),/symlink/i);
   await symlink('/tmp',join(workspace,'escape'));
   await assert.rejects(()=>readNativePrivate(options,launch()),/symlink/i);
   await rm(join(workspace,'escape'));
   for(const change of [{operation:'search'},{operation:'status',jobId:7},{jobId:'7'},{jobId:0},{python:'/usr/bin/python3'}]) await assert.rejects(()=>readNativePrivate({...options,...change},launch()));
   assert.equal(calls.length,0);
   const old=process.env.OPENAI_API_KEY;process.env.OPENAI_API_KEY='synthetic-secret';
   try { assert.deepEqual(await readNativePrivate(options,launch('{"job":{}}',0,'ignored private stderr')),{job:{}}); }
   finally {if(old===undefined)delete process.env.OPENAI_API_KEY;else process.env.OPENAI_API_KEY=old;}
   assert.equal(calls[0].file,python);
   assert.deepEqual(calls[0].args,['-I','-B','-m','personal_jobby','show','7']);
   assert.equal(calls[0].opts.cwd,home);
   assert.deepEqual(calls[0].opts.env,{HOME:home,JOBBY_ROOT:workspace,PYTHON_DOTENV_DISABLED:'1',PYTHONDONTWRITEBYTECODE:'1',PATH:'/usr/bin:/bin',LANG:'C.UTF-8'});
   assert.equal(calls[0].opts.shell,undefined);
   await readNativePrivate({...options,operation:'status',jobId:undefined},launch());
   assert.deepEqual(calls[1].args,['-I','-B','-m','personal_jobby','status','--brief']);
   for(const [stdout,code] of [['{}',1],['',0],['warning\n{}',0],['{}\n{}',0],['[]',0],['null',0],['{"x":',0],['x'.repeat(2*1024*1024+1),0]]) {
     await assert.rejects(()=>readNativePrivate(options,launch(stdout,code,'PRIVATE_SENTINEL')),error=>!error.message.includes('PRIVATE_SENTINEL')&&!error.message.includes(stdout.slice(0,30)||'PRIVATE_SENTINEL'));
   }
   await assert.rejects(()=>readNativePrivate(options,launch('{}',0,'x'.repeat(2*1024*1024+1))),/output limit/);
   await assert.rejects(()=>readNativePrivate(options,launch(Buffer.from([123,34,120,34,58,34,255,34,125]))),/complete JSON/);
   await assert.rejects(()=>readNativePrivate(options,()=>{throw Error('PRIVATE_SENTINEL');}),/^Error: Private CLI launch failed$/);
   await assert.rejects(()=>readNativePrivate(options,()=>{const child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();child.kill=()=>true;queueMicrotask(()=>child.emit('error',Error('PRIVATE_SENTINEL')));return child;}),/^Error: Private CLI launch failed$/);
   await assert.rejects(()=>readNativePrivate({...options,timeoutMs:20},launch('',0,'',true)),/deadline/);
 } finally {await rm(root,{recursive:true,force:true});}
});

test('native live requires explicit owned home and rejects partial or duplicate home options',async()=>{
 const {parseQualificationMode}=await import('../scripts/qualify_desktop_desk.mjs');
 const target=['--native-cdp','http://127.0.0.1:19338','--native-page','http://127.0.0.1:15274/#/jobby'];
 const home='/home/adcan288/tmp/jobby-live-acceptance-20261107/home';
 assert.equal(parseQualificationMode(['--native-live',...target,'--live-home',home]).liveHome,home);
 for(const tail of [[],['--live-home'],['--live-home','/tmp/home'],['--live-home',home+'/../home'],['--live-home',home,'--live-home',home]]) assert.throws(()=>parseQualificationMode(['--native-live',...target,...tail]));
 assert.throws(()=>parseQualificationMode([...target,'--live-home',home]));
});

test('native private binding fails on caller, source, current material and provider mismatches',async()=>{
 const {bindNativeDossier}=await import('../scripts/qualify_desktop_desk.mjs');
 const {setup,shown,status}=liveContract();
 const material={generation_id:'b'.repeat(32),review_token:'c'.repeat(64),qa_state:'pending_visual_review',artifact_hashes:{'resume.pdf':'d'.repeat(64)}};
 shown.materials=material;shown.job.materials=material;
 const publicValue={ok:true,submission_available:false,job:{id:7,job_url:shown.job.job_url,status:'discovered'},materials:structuredClone(material)};
 const bind=(s=shown,p=publicValue,st=status)=>bindNativeDossier(publicValue,s,p,setup,st);
 assert.doesNotThrow(()=>bind());
 for(const change of [{id:8},{job_url:'https://ca.indeed.com/viewjob?jk=other'},{status:'applied'},{attempts:[{id:'private'}]},{submitted_at:'2026-11-07'},{original_source:{site:'linkedin',job_url:shown.job.job_url}},{original_source:{site:'indeed',job_url:'https://ca.indeed.com/other'}}]) assert.throws(()=>bind({...shown,job:{...shown.job,...change}}));
 assert.throws(()=>bind({...shown,job:{...shown.job,attempts:[{id:'PRIVATE_SENTINEL',answers:'PRIVATE_SENTINEL'}]}}),error=>!error.message.includes('PRIVATE_SENTINEL'));
 for(const change of [{generation_id:'e'.repeat(32)},{review_token:'e'.repeat(64)},{qa_state:'stale'},{qa_state:'visual_approved'},{artifact_hashes:{'resume.pdf':'e'.repeat(64)}}]) assert.throws(()=>bind({...shown,materials:{...material,...change},job:{...shown.job,materials:{...material,...change}}}));
 assert.throws(()=>bind({...shown,job:{...shown.job,materials:null}}));
 assert.throws(()=>bind(shown,{...publicValue,materials:{...material,review_token:'f'.repeat(64)}}));
 for(const change of [{candidate_initialized:false},{fact_count:0},{settings:{discovery:{...status.settings.discovery,source_token:'f'.repeat(64)}}},{settings:{discovery:{...status.settings.discovery,queries:['Other']}}},{settings:{discovery:{...status.settings.discovery,preferences:{...setup.preferences,total:25}}}}]) assert.throws(()=>bind(shown,publicValue,{...status,...change}));
 for(const events of [undefined,[{...shown.events[0],job_id:8}],[shown.events[0],shown.events[0]],[{...shown.events[0],data:'prefix {}'}]]) assert.throws(()=>bind({...shown,events}));
});

test('native current artifact checks reject escaped directories, changed hashes, sources and links',async()=>{
 const {mkdtemp,mkdir,writeFile,symlink,rm}=await import('node:fs/promises');
 const {join}=await import('node:path');
 const {createHash}=await import('node:crypto');
 const {verifyNativeArtifacts}=await import('../scripts/qualify_desktop_desk.mjs');
 const root=await mkdtemp('/home/adcan288/tmp/jobby-live-acceptance-20261107/driver-contract-fix/artifact-');
 const home=join(root,'home'),generation='b'.repeat(32),folder=join(home,'plugin-data/jobby/workspace/artifacts/7/generations',generation);
 await mkdir(folder,{recursive:true,mode:0o700});
 const sha=value=>createHash('sha256').update(value).digest('hex');
 const source=join(root,'source.pdf');await writeFile(source,'synthetic source');
 const names=['resume.pdf','resume.docx','cover_letter.pdf','cover_letter.docx','preview.png','cover_preview.png'];
 for(const name of names)await writeFile(join(folder,name),'synthetic artifact');
 const shown={job:{id:7},materials:{generation_id:generation,qa_state:'pending_visual_review',source_hashes:{[source]:sha('synthetic source')},artifact_hashes:Object.fromEntries(names.map(name=>[name,sha('synthetic artifact')]))},current_artifact_directory:folder};
 try {
   await verifyNativeArtifacts(home,shown);
   for(const current_artifact_directory of ['/tmp/elsewhere',folder+'/../'+generation,folder.replace(generation,'c'.repeat(32))]) await assert.rejects(()=>verifyNativeArtifacts(home,{...shown,current_artifact_directory}));
   await assert.rejects(()=>verifyNativeArtifacts(home,{...shown,materials:{...shown.materials,source_hashes:{'/etc/passwd':sha('synthetic source')}}}));
   await assert.rejects(()=>verifyNativeArtifacts(home,{...shown,materials:{...shown.materials,artifact_hashes:{...shown.materials.artifact_hashes,'../../escape':'a'.repeat(64)}}}));
   await assert.rejects(()=>verifyNativeArtifacts(home,{...shown,materials:{...shown.materials,source_hashes:{}}}));
   await writeFile(source,'changed source');await assert.rejects(()=>verifyNativeArtifacts(home,shown),/hash/);await writeFile(source,'synthetic source');
   await writeFile(join(folder,'resume.pdf'),'changed artifact');await assert.rejects(()=>verifyNativeArtifacts(home,shown),/hash/);
   await rm(join(folder,'resume.pdf'));await symlink(source,join(folder,'resume.pdf'));await assert.rejects(()=>verifyNativeArtifacts(home,shown),/symlink/i);
 } finally {await rm(root,{recursive:true,force:true});}
});

test('serialized checkout CLI show/status bind to actual filtered public materials in an offline synthetic workspace',async()=>{
 const {mkdtemp,mkdir,rm}=await import('node:fs/promises');
 const {join}=await import('node:path');
 const {execFile,spawn}=await import('node:child_process');
 const {promisify}=await import('node:util');
 const {readNativePrivate,bindNativeDossier,verifyNativeArtifacts}=await import('../scripts/qualify_desktop_desk.mjs');
 const root=await mkdtemp('/home/adcan288/tmp/jobby-live-acceptance-20261107/driver-contract-fix/serialized-');
 const home=join(root,'home');await mkdir(home,{mode:0o700});
 const workspace=join(home,'plugin-data/jobby/workspace');
 const repo=new URL('..',import.meta.url).pathname;
 const code=`import sys,json
from contextlib import redirect_stdout
from io import StringIO
with redirect_stdout(StringIO()):
 from pathlib import Path
 sys.path.insert(0,sys.argv[1])
 from scripts.run_synthetic_applications import source_documents,load_matrix
 from personal_jobby.store import Store
 from personal_jobby.import_profile import initialize
 from personal_jobby.documents import prepare
 from personal_jobby.search import setup,confirm
 from dashboard.plugin_api import public_desk
 from plugin import overview
 root=Path(sys.argv[2]);matrix=load_matrix()
 matrix['source_sections'][1][1][0]='Sandbox CLI: Built a Python-based Jobby CLI for synthetic local documents.'
 source_documents(root,matrix)
 store=Store();initialize(store,root/'fictional-source.pdf')
 current=setup(store)
 current=confirm(store,current['source_token'],['Python'],dict(country='Canada',location='Toronto, ON, Canada',remote=False,hours_old=720,per_query=5,total=5,order='newest'))
 job=store.add(dict(company='Synthetic',title='Python Engineer',job_url='https://ca.indeed.com/viewjob?jk=synthetic-only',location='Toronto',description='Synthetic Python tools',original_source=dict(site='indeed',job_url='https://ca.indeed.com/viewjob?jk=synthetic-only')))
 prepare(store,job['id'])
print(json.dumps(dict(setup=current,public=public_desk(overview(store,store.get(job['id']))))))`;
 try {
   const result=await promisify(execFile)(join(repo,'.venv/bin/python'),['-I','-B','-c',code,repo,root],{cwd:root,env:{PATH:'/usr/bin:/bin',HOME:home,JOBBY_ROOT:workspace,PYTHON_DOTENV_DISABLED:'1'},timeout:15000,maxBuffer:2*1024*1024});
   const value=JSON.parse(result.stdout);
   const input={liveHome:home,python:'/home/adcan288/tmp/jobby-live-acceptance-20261107/runtime-native/bin/python'};
   // Offline transport adapter executes only the checkout launcher against this
   // synthetic state. It neither invokes nor certifies the installed live app.
   const launch=(_file,args,options)=>spawn(join(repo,'personal_jobby/bin/jobby'),args.slice(4),options);
   const status=await readNativePrivate({...input,operation:'status'},launch);
   const shown=await readNativePrivate({...input,operation:'show',jobId:value.public.job.id},launch);
   assert.deepEqual(Object.keys(shown).sort(),['current_artifact_directory','events','job','materials']);
   assert.equal(shown.ok,undefined);
   assert.ok(Array.isArray(shown.job.attempts));
   assert.equal(value.public.job.original_source,undefined);
   const bound=bindNativeDossier(value.public,shown,value.public,value.setup,status);
   await verifyNativeArtifacts(home,shown);
   assert.deepEqual(bound.public.materials, value.public.materials);
   assert.equal(bound.audit.attempt_count,0);
   assert.equal(bound.audit.site,'indeed');
 } finally {await rm(root,{recursive:true,force:true});}
});
