/** Controlled fictional forms, not ATS adapters. Importing this module starts nothing. */
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createServer} from 'node:http';
import {readFile, writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {createInterface} from 'node:readline';
import {inspectForm, maskPrivateFields, restorePrivateFields, inspectOutcome} from './ats-contract.mjs';

const HOST = 'https://applications.example.test';
const IDS = ['ai-engineer','backend-engineer','ml-platform-engineer','fde','senior-stretch'];
export const validCaseId = id => typeof id==='string' && (IDS.includes(id) || /^benchmark-(?:00[1-9]|0[1-9][0-9]|100)$/.test(id));
const ACK = 'synthetic test only — no real employer application';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const escape = value => value.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');

export function routeKind(url, method, row) {
  if (!validCaseId(row.id)) return 'abort';
  if (method === 'GET' && url === `${HOST}/jobs/${row.id}`) return 'form';
  if (method === 'POST' && url === `${HOST}/submit/${row.id}`) return 'post';
  return 'abort';
}

export function validatePost(row, actualHash, postCount) {
  assert.equal(postCount, 0, 'Duplicate synthetic submission blocked');
  assert.equal(actualHash, row.manifest.resume.sha256, 'Uploaded file hash mismatch');
  return true;
}

function benchmarkIdentity(row) {
  const benchmark=row.id.startsWith('benchmark-');
  if(benchmark) {
    assert.equal(row.identity.name,'AI Agent — NON-HUMAN SYNTHETIC FIXTURE');
    assert.equal(row.identity.first_name,'AI');
    assert.equal(row.identity.last_name,'Agent (NON-HUMAN SYNTHETIC FIXTURE)');
    assert.equal(row.identity.email,'agent@example.test');
    assert.equal(row.identity.contact,'Non-human AI Agent | agent@example.test');
    assert.deepEqual(row.identity.answers,{});
    assert.deepEqual(Object.keys(row.identity).sort(),['name','first_name','last_name','email','contact','answers'].sort());
  }
  return benchmark;
}

function controlledFields(row) {
  if(!row.controlled_answers) return null;
  assert.ok(benchmarkIdentity(row));
  const answers=row.controlled_answers;
  assert.equal(answers.policy,'controlled-nonhuman-fixture-v1');
  for(const key of ['candidate_fingerprint','source_fingerprint']) assert.match(answers[key],/^[a-f0-9]{64}$/);
  assert.ok(Array.isArray(answers.fields) && answers.fields.length<=3);
  const labels={first_name:'First Name',last_name:'Last Name',email:'Email'}, seen=new Set();
  for(const field of answers.fields) {
    assert.deepEqual(Object.keys(field).sort(),['fingerprint','name','source_type','type','label','required','value'].sort());
    assert.ok(Object.hasOwn(labels,field.name) && !seen.has(field.name));seen.add(field.name);
    assert.equal(field.label,labels[field.name]);
    assert.equal(field.source_type,'input_text');
    assert.equal(field.type,field.name==='email'?'email':'text');
    assert.equal(field.value,row.identity[field.name]);
    assert.equal(typeof field.required,'boolean');
    assert.match(field.fingerprint,/^[a-f0-9]{64}$/);
  }
  return answers.fields;
}

export function renderFixture(row) {
  const benchmark=benchmarkIdentity(row), safe=controlledFields(row);
  const group = row.id === 'fde' ? 'fieldset' : 'div';
  const field = (id, label, type='text', required=true, fingerprint='') => `<${group} data-question aria-required="${required}"><label id="${id}-label" for="${id}">${escape(label)} ${required?'*':''}</label><input id="${id}" name="${id}" type="${type}" ${type==='email'?'data-private':''} data-source-fingerprint="${fingerprint}" aria-labelledby="${id}-label" aria-required="${required}" ${required?'required':''}></${group}>`;
  return `<!doctype html><meta charset="utf-8"><title>Fictional application</title>
  <style>body{font:18px Georgia;margin:40px;max-width:800px}label{display:block;margin-top:12px}input,select,textarea{font:16px Georgia;width:95%;padding:6px}button{padding:10px;margin:10px}fieldset{border:0;padding:0}</style>
  <h1>Fable Systems (FICTIONAL)</h1><h2>${escape(row.id)}</h2><p>${ACK}</p>
  ${benchmark?`<p>${escape(row.identity.name)}</p>`:''}
  <form method="post" action="/submit/${row.id}" enctype="multipart/form-data">
  <input type="hidden" name="attempt_id" value="${escape(row.attempt_id)}">
  ${safe?safe.map(f=>field(f.name,f.label,f.type,f.required,f.fingerprint)).join(''):field('name','Fictional name')+field('email','Reserved test email','email')}
  ${benchmark?'':`<div role="group" aria-required="true"><label for="location">Fictional location *</label><select required id="location" name="location"><option value="">Select location</option><option>Example City (fictional)</option><option>Other sandbox</option></select><span id="selected-location"></span></div>
  <label for="eligibility">Sandbox eligibility (no real authorization asserted) *</label><textarea required id="eligibility" name="eligibility"></textarea>`}
  <label for="gaps">Unsupported qualifications (truthful fixture answer) *</label><textarea required id="gaps" name="gaps"></textarea>
  <div id="upload" aria-busy="false"><label for="resume">Resume PDF *</label><input required type="file" accept="application/pdf" id="resume" name="resume"><span id="filename"></span><button type="button" id="replace" disabled>Replace</button></div>
  <p>Cover letter: explicitly not attached.</p><input data-private type="hidden" name="private_fixture" value="fictional-preserved">
  <button id="submit" type="submit">Send to local mock only</button></form>
  <script>
  const loc=document.querySelector('#location'); if(loc) loc.onblur=()=>{document.querySelector('#selected-location').textContent=loc.value};
  const resume=document.querySelector('#resume');resume.onchange=()=>{document.querySelector('#filename').textContent=resume.files[0]?.name||'';document.querySelector('#upload').setAttribute('aria-busy','true');document.querySelector('#replace').disabled=true;setTimeout(()=>{document.querySelector('#upload').setAttribute('aria-busy','false');document.querySelector('#replace').disabled=false},600)};
  </script>`;
}

export async function validateMultipart(row, data, postCount) {
  const benchmark=benchmarkIdentity(row), safe=controlledFields(row);
  const file=data.get('resume');
  assert.ok(file && typeof file.arrayBuffer==='function');
  assert.equal(file.name,'resume.pdf');
  const fileBytes=Buffer.from(await file.arrayBuffer()), hash=sha(fileBytes);
  validatePost(row,hash,postCount);
  const expected={attempt_id:row.attempt_id,
    ...(safe?Object.fromEntries(safe.map(f=>[f.name,f.value])):{name:row.identity.name,email:row.identity.email}),
    ...(!benchmark?{location:row.identity.location,eligibility:row.identity.answers.work_eligibility}:{}),
    gaps:row.gaps.map(g=>`Not supported: ${g.claim}`).join('; '),private_fixture:'fictional-preserved'};
  assert.deepEqual([...data.keys()].sort(),[...Object.keys(expected),'resume'].sort());
  for(const [key,value] of Object.entries(expected)) assert.equal(data.get(key),value);
  assert.equal(hash,sha(await readFile(row.resume_path)));
  return {resume_sha256:hash,file_size:fileBytes.length,
    ...(safe?{submitted_safe_fields:safe.map(f=>({...f,value:data.get(f.name)}))}:{})};
}

const outcomeConfig = {successSelector:'#ack', expectedText:ACK, formSelector:'form', challengeSelector:'#challenge', errorSelector:'#error'};

// Mapping is exact and confined to this owned listener, never arbitrary loopback URLs.
export function transportRouteKind(url, method, row, origin) {
  if (typeof origin!=='string' || !/^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}$/.test(origin)
      || Number(origin.slice(origin.lastIndexOf(':')+1))>65535) return 'abort';
  for (const path of [`/jobs/${row.id}`, `/submit/${row.id}`]) {
    if (url === origin+path) return routeKind(HOST+path,method,row);
  }
  return 'abort';
}

function reportRouteError(error) {
  const diagnostic=String(error.stack||error).split('\n')
    .filter((line,index)=>index===0 || /^\s+at /.test(line)).join('\n').slice(0,4096);
  process.stderr.write('[synthetic-route-error] '+diagnostic+'\n');
}

export async function startFixture(row) {
  assert.ok(validCaseId(row.id));
  benchmarkIdentity(row);controlledFields(row);
  const state={origin:null,postCount:0,observedPosts:0,captured:null,error:null};
  const server=createServer(async (request,response)=>{
    request.setTimeout(10000,()=>request.destroy());
    const kind=request.headers.host===new URL(state.origin).host
      ? transportRouteKind(state.origin+request.url,request.method,row,state.origin) : 'abort';
    if (kind==='abort') {response.writeHead(403,{'Connection':'close'});response.end();return;}
    if (kind==='form') {response.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});response.end(renderFixture(row));return;}
    state.observedPosts++;
    process.stdout.write(JSON.stringify({stage:'post_observed',post_count:state.observedPosts})+'\n');
    try {
      assert.equal(state.observedPosts,1,'Duplicate synthetic submission blocked');
      const bytes=await new Promise((resolve,reject)=>{
        const chunks=[];let size=0,overLimit=false;
        request.on('data',chunk=>{
          if(overLimit) return;
          size+=chunk.length;
          if(size>8*1024*1024) {
            overLimit=true;chunks.length=0;
            reject(new Error('Synthetic multipart exceeds 8 MiB limit'));
          } else chunks.push(chunk);
        });
        request.once('end',()=>{if(!overLimit) resolve(Buffer.concat(chunks))});
        request.once('error',reject);
        request.once('aborted',()=>reject(new Error('Synthetic request aborted')));
      });
      const contentType=request.headers['content-type'];
      assert.ok(typeof contentType==='string' && contentType.startsWith('multipart/form-data;'));
      const data=await new Request(state.origin+request.url,{method:'POST',headers:{'content-type':contentType},body:bytes}).formData();
      const proof=await validateMultipart(row,data,state.postCount);
      const archive=`${row.output_directory}/${row.id}.multipart.bin`;
      await writeFile(archive,bytes,{mode:0o600,flag:'wx'});
      state.captured={...proof,multipart_sha256:sha(bytes),multipart_path:archive,content_type:contentType};
      state.postCount++;
      response.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Connection':'close'});
      response.end(`<!doctype html><meta charset="utf-8"><h1>Fictional mock acknowledgment</h1><div id="ack">${ACK}</div><p>${escape(row.id)} / ${escape(row.attempt_id)}</p>`);
    } catch(error) {
      state.error=error;
      request.resume();
      reportRouteError(error);
      if (!response.destroyed) {
        response.writeHead(400,{'Content-Type':'text/html; charset=utf-8','Connection':'close'});
        response.end('<div id="error">Synthetic request rejected; no acknowledgment</div>');
      }
    }
  });
  server.requestTimeout=10000;server.headersTimeout=10000;server.keepAliveTimeout=1000;
  server.on('clientError',(_error,socket)=>socket.destroy());
  await new Promise((resolve,reject)=>{
    server.once('error',reject);
    server.listen(0,'127.0.0.1',resolve);
  });
  state.origin=`http://127.0.0.1:${server.address().port}`;
  state.close=()=>new Promise((resolve,reject)=>{
    server.close(error=>error?reject(error):resolve());
    server.closeAllConnections();
  });
  return state;
}

export async function journey(row) {
  assert.equal(row.url, `${HOST}/jobs/${row.id}`);
  const benchmark=benchmarkIdentity(row), safe=controlledFields(row);
  if(!benchmark) {
    assert.equal(row.identity.name, 'Rowan Example — FICTIONAL TEST CANDIDATE');
    assert.equal(row.identity.email, 'rowan@example.test');
  }
  const modulePath = process.env.JOBBY_PLAYWRIGHT_MODULE;
  assert.ok(modulePath?.startsWith('/'), 'Absolute installed Playwright module required');
  const {chromium} = await import(pathToFileURL(modulePath));
  let browser=null,fixture=null;
  const requests=[], blocked=[];
  try {
    fixture=await startFixture(row);
    const transport={canonical_origin:HOST,actual_origin:fixture.origin,
      canonical_form_url:row.url,actual_form_url:`${fixture.origin}/jobs/${row.id}`,
      canonical_submit_url:`${HOST}/submit/${row.id}`,actual_submit_url:`${fixture.origin}/submit/${row.id}`};
    process.stdout.write(JSON.stringify({stage:'transport_ready',transport})+'\n');
    browser=await chromium.launch({executablePath:'/usr/bin/google-chrome', headless:true,
      args:['--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run']});
    const context = await browser.newContext({serviceWorkers:'block', viewport:{width:1100,height:1200}});
    await context.route('**/*', async route => {
      const request=route.request(), kind=transportRouteKind(request.url(),request.method(),row,fixture.origin);
      requests.push({url:request.url(),method:request.method(),kind});
      if (kind==='form' || kind==='post') return await route.continue();
      blocked.push({url:request.url(),method:request.method()});
      await route.abort('blockedbyclient');
    });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    // Real DOM negative controls. A matching success panel cannot conceal either barrier.
    await page.setContent(`<div id="ack">${ACK}</div><div id="challenge">CAPTCHA — fixture only</div>`);
    assert.equal((await page.evaluate(inspectOutcome,outcomeConfig)).outcome,'challenge');
    await page.setContent(`<div id="ack">${ACK}</div><div id="error">Invalid upload</div>`);
    assert.equal((await page.evaluate(inspectOutcome,outcomeConfig)).outcome,'error');
    await page.setContent('<form><label>Unknown required answer *<input required></label></form>');
    assert.ok((await page.evaluate(inspectForm)).fields.some(f=>f.required));
    assert.notEqual((await page.evaluate(inspectOutcome,outcomeConfig)).outcome,'confirmation_observed');
    await page.goto(transport.actual_form_url);
    if(safe) {
      for(const field of safe) await page.locator('#'+field.name).fill(field.value);
    } else {
      await page.locator('#name').fill(row.identity.name);
      await page.locator('#email').fill(row.identity.email);
    }
    await page.locator('#gaps').fill(row.gaps.map(g=>`Not supported: ${g.claim}`).join('; '));
    if(!benchmark) {
      await page.locator('#eligibility').fill(row.identity.answers.work_eligibility);
      await page.locator('#location').focus();
      await page.locator('#location').selectOption({label:row.identity.location});
      await page.locator('#location').blur();
    }
    const config={uploadSelector:'#upload',...(!benchmark?{locationSelector:'#location',selectedLocationSelector:'#selected-location',expectedLocation:row.identity.location}:{})};
    await page.locator('#resume').setInputFiles(row.resume_path);
    // Observe the async upload window: visible filename is insufficient while Replace is disabled.
    assert.equal((await page.evaluate(inspectForm,config)).upload,'pending');
    await page.waitForFunction(()=>!document.querySelector('#replace').disabled);
    const inspection=await page.evaluate(inspectForm,config);
    assert.equal(inspection.upload,'ready');if(!benchmark) assert.equal(inspection.locationSelected,true);
    assert.equal(inspection.fields.filter(f=>f.required).length,2+(safe?safe.filter(f=>f.required).length:2)+(benchmark?0:2));
    const renderedSafe=[];
    if(safe) for(const field of safe) {
      const observed=await page.locator('#'+field.name).evaluate(n=>({name:n.name,type:n.type,value:n.value,
        fingerprint:n.dataset.sourceFingerprint,required:n.required,label:document.querySelector(`label[for="${n.id}"]`).textContent.replace(/\s*\*\s*$/,'').trim()}));
      renderedSafe.push({...observed,source_type:'input_text'});
    }
    if(safe) assert.deepEqual(renderedSafe,safe);
    const browserHash=await page.locator('#resume').evaluate(async n=>{
      const bytes=await n.files[0].arrayBuffer();
      return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
    });
    validatePost(row,browserHash,fixture.postCount);
    const snapshot=()=>[...new FormData(document.querySelector('form'))].map(([k,v])=>[k,typeof v==='string'?v:{name:v.name,size:v.size,type:v.type}]);
    const before=await page.evaluate(snapshot);
    await page.evaluate(maskPrivateFields);
    assert.deepEqual(await page.evaluate(snapshot),before);
    const filled=`${row.output_directory}/${row.id}.filled.png`;
    await page.screenshot({path:filled,fullPage:true});
    await page.evaluate(restorePrivateFields);
    assert.deepEqual(await page.evaluate(snapshot),before);
    // Python ingests the screenshot and durably reserves no-retry intent before returning this permit.
    const lines=createInterface({input:process.stdin});
    const permit=new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('No submit permit; no retry')),20000);
      lines.once('line',line=>{clearTimeout(timer);resolve(line)});
    });
    process.stdout.write(JSON.stringify({stage:'filled',screenshot:filled,browser_sha256:browserHash,inspection})+'\n');
    assert.equal(await permit,'submit-once');lines.close();
    await Promise.all([page.waitForURL(transport.actual_submit_url),page.locator('#submit').click()]);
    if(fixture.error) throw fixture.error;
    const outcome=await page.evaluate(inspectOutcome,outcomeConfig);
    assert.equal(outcome.outcome,'confirmation_observed');assert.equal(fixture.postCount,1);
    const confirmation=`${row.output_directory}/${row.id}.confirmation.png`;
    await page.screenshot({path:confirmation,fullPage:true});
    await context.close();
    return {stage:'result',role_id:row.id,attempt_id:row.attempt_id,outcome:outcome.outcome,text:ACK,
      post_count:fixture.postCount,confirmation_screenshot:confirmation,browser_sha256:browserHash,...fixture.captured,
      ...(safe?{rendered_safe_fields:renderedSafe}:{}),transport,requests,blocked,
      negative_controls:['CAPTCHA blocks','error blocks','unknown required answer holds'],mask_preserved_form_data:true};
  } finally {
    try {if(browser) await browser.close()} finally {if(fixture) await fixture.close()}
  }
}

if (process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) {
  try {
    const result=await journey(JSON.parse(await readFile(process.argv[2],'utf8')));
    process.stdout.write(JSON.stringify(result)+'\n');
  } catch(error) {reportRouteError(error);process.exitCode=1}
}
