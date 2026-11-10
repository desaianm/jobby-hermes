import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {inspectForm} from '../browser/ats-contract.mjs';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.JOBBY_PLAYWRIGHT_MODULE || 'playwright-core');

// Offline DOM regressions only: these fixtures do not execute provider scripts.
test('offline visible descendant overrides ancestor visibility and blocks apparent success', async t => {
  const {inspectOutcome} = await import('../browser/ats-contract.mjs');
  const browser=await chromium.launch({executablePath:process.env.JOBBY_TEST_CHROME || '/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
  try {
    const page=await browser.newPage();
    await page.setContent('<div id="success">Application received</div><div style="visibility:hidden"><div class="g-recaptcha" style="visibility:visible"><input type="checkbox"></div></div>');
    const presentation=await page.evaluate(() => {
      const panel=document.querySelector('.g-recaptcha'),control=panel.querySelector('input');
      return {
        ancestor:getComputedStyle(panel.parentElement).visibility,
        panel:getComputedStyle(panel).visibility,
        control:getComputedStyle(control).visibility,
        boxes:[panel,control].every(n => [...n.getClientRects()].some(r => r.width > 0 && r.height > 0)),
        rendered:control.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}),
      };
    });
    assert.deepEqual(presentation,{ancestor:'hidden',panel:'visible',control:'visible',boxes:true,rendered:true});
    for (const challengeSelector of ['#wrong','.g-recaptcha']) await t.test(challengeSelector,async () => {
      const cfg={successSelector:'#success',expectedText:'Application received',formSelector:'form',challengeSelector,errorSelector:'#error'};
      const r=await page.evaluate(inspectOutcome,cfg);
      assert.equal(r.outcome,'challenge');
      assert.ok(r.verification.signals.some(s => s.provider === 'recaptcha' && s.state === 'active' && s.evidence === 'control'));
    });
  } finally {await browser.close();}
});

test('visible verification takes priority over success without an operator challenge marker', async () => {
  const {inspectOutcome} = await import('../browser/ats-contract.mjs');
  const browser = await chromium.launch({executablePath:process.env.JOBBY_TEST_CHROME || '/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
  try {
    const page = await browser.newPage();
    await page.setContent('<div id="success">Application received</div><div class="g-recaptcha"><div role="checkbox" aria-checked="false" aria-label="I’m not a robot" style="width:28px;height:28px"></div></div>');
    const cfg = {successSelector:'#success',expectedText:'Application received',formSelector:'form',challengeSelector:'#wrong',errorSelector:'#error'};
    assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'challenge');
    delete cfg.challengeSelector;
    assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'challenge');
  } finally {await browser.close();}
});

test('wrapper required, pending upload, exact persisted location, private snapshot', async () => {
  const browser = await chromium.launch({executablePath:process.env.JOBBY_TEST_CHROME || '/usr/bin/google-chrome', headless:true, args:['--no-sandbox']});
  try {
    const page = await browser.newPage();
    const requests = [];
    page.on('request', request => requests.push(request.url()));
    await page.setContent(`<form><div data-question><label for="city">Location *</label><input id="city" role="combobox" value="Berlin"></div><div id="upload"><input type="file"><span>resume.pdf</span><button disabled>Replace</button></div><input type="tel" value="+1 416 555 0199"></form>`);
    const config = {uploadSelector:'#upload',locationSelector:'#city',selectedLocationSelector:'[data-selected-location]',expectedLocation:'Berlin'};
    let r = await page.evaluate(inspectForm,config);
    assert.equal(r.fields[0].required,true);
    assert.equal(r.upload,'pending');
    assert.equal(r.locationSelected,false);
    assert.equal(JSON.stringify(r).includes('416'),false);
    await page.evaluate(() => {document.querySelector('button').disabled=false;const s=document.createElement('span');s.dataset.selectedLocation='';s.textContent='Berlin';document.body.append(s);});
    r=await page.evaluate(inspectForm,config);
    assert.equal(r.upload,'ready');
    assert.equal(r.locationSelected,true);
  } finally {await browser.close();}
});

test('confirmation requires exact visible panel, absent form, and no challenge or error', async () => {
  const {inspectOutcome} = await import('../browser/ats-contract.mjs');
  const browser=await chromium.launch({executablePath:process.env.JOBBY_TEST_CHROME || '/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
  try {
    const page=await browser.newPage();
    const cfg={successSelector:'#success',formSelector:'form',challengeSelector:'#captcha',errorSelector:'#error',expectedText:'Application received'};
    await page.setContent('<p>Application received</p><form><input type="tel" value="private-value"></form>');
    assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'uncertain');
    await page.setContent('<div id="success">Application received</div>');
    assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'confirmation_observed');
    await page.setContent('<div id="success">Application received</div><div id="captcha">Human check</div>');
    assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'challenge');
    await page.setContent('<div id="success">Application received</div><div id="error">Failed</div>');
    assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'error');
  } finally {await browser.close();}
});


test('private screenshot mask preserves FormData, original attributes and custom DOM, then restores visuals', async () => {
  const helpers = await import('../browser/ats-contract.mjs');
  const browser = await chromium.launch({executablePath:process.env.JOBBY_TEST_CHROME || '/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
  try {
    const page = await browser.newPage();
    const requests = [];
    page.on('request', request => requests.push(request.url()));
    await page.setContent(`<form>
      <input name="phone" type="tel" value="synthetic-original" title="Fixture title" aria-label="Fixture phone">
      <input name="callback" autocomplete="tel" style="color: rgb(12, 34, 56); transition: opacity 10s">
      <input name="secret" type="password" value="synthetic-secret">
      <div data-private title="Fixture custom title" aria-label="Fixture custom label"><span style="visibility: visible !important; opacity: 1 !important">synthetic private text</span><button type="button">Keep child</button></div>
    </form>`);
    await page.evaluate(() => {
      document.querySelector('[name="phone"]').value = 'synthetic-current';
      document.querySelector('[name="callback"]').value = 'synthetic-callback';
      window.privateChild = document.querySelector('[data-private] span');
      window.privateText = window.privateChild.firstChild;
      window.applicationCallbacks = 0;
      for (const event of ['input','change','blur','click','submit']) {
        document.querySelector('form').addEventListener(event, () => window.applicationCallbacks++);
      }
    });
    const snapshot = () => ({
      form: [...new FormData(document.querySelector('form')).entries()],
      nodes: [...document.querySelectorAll('input,[data-private]')].map(n => ({
        value: 'value' in n ? n.value : null,
        attributes: [...n.attributes].map(a => [a.name,a.value]).sort(([a],[b]) => a.localeCompare(b)),
        text: n.textContent,
      })),
    });
    const original = await page.evaluate(snapshot);
    assert.equal(await page.evaluate(helpers.maskPrivateFields),4);
    // This existing export must preserve submission data before any restoration API is tested.
    const masked = await page.evaluate(snapshot);
    assert.equal(await page.evaluate(helpers.maskPrivateFields),4);
    assert.deepEqual(await page.evaluate(snapshot),masked);
    assert.deepEqual(masked.form, original.form);
    for (let i=0;i<original.nodes.length;i++) {
      assert.equal(masked.nodes[i].value, original.nodes[i].value);
      assert.equal(masked.nodes[i].text, original.nodes[i].text);
      // Only visual styles change; original value/type attribute presence must not.
      const valueAttr = n => n.attributes.find(([key]) => key === 'value') ?? null;
      assert.deepEqual(valueAttr(masked.nodes[i]), valueAttr(original.nodes[i]));
      const nonvisualAttrs = n => n.attributes.filter(([key]) => key !== 'style');
      assert.deepEqual(nonvisualAttrs(masked.nodes[i]), nonvisualAttrs(original.nodes[i]));
    }
    assert.equal(await page.evaluate(() => window.privateChild === document.querySelector('[data-private] span') && window.privateText === window.privateChild.firstChild),true);
    assert.equal(await page.evaluate(() => [...document.querySelectorAll('input,[data-private]')].every(n => {
      const s = getComputedStyle(n);
      return n.type === 'password' || s.webkitTextSecurity === 'disc' || s.visibility === 'hidden' || s.display === 'none' || s.opacity === '0' || s.color === 'rgba(0, 0, 0, 0)';
    })),true);
    // A descendant's own visible/opaque style cannot override ancestor compositing.
    assert.equal(await page.evaluate(() => {
      const child = document.querySelector('[data-private] span');
      return getComputedStyle(child).visibility === 'visible' && getComputedStyle(child).opacity === '1'
        && getComputedStyle(child.parentElement).opacity === '0';
    }),true);
    // Restoration must recover all attributes, including originally absent ones.
    assert.equal(typeof helpers.restorePrivateFields,'function');
    await page.evaluate(helpers.restorePrivateFields);
    assert.deepEqual(await page.evaluate(snapshot),original);
    assert.equal(await page.evaluate(helpers.restorePrivateFields),0);
    await page.evaluate(helpers.maskPrivateFields);
    await page.evaluate(() => {document.querySelector('[name="phone"]').value = 'synthetic-human-edit';});
    await page.evaluate(helpers.restorePrivateFields);
    const edited = structuredClone(original);
    edited.form[0][1] = 'synthetic-human-edit';
    edited.nodes[0].value = 'synthetic-human-edit';
    assert.deepEqual(await page.evaluate(snapshot),edited);
    assert.equal(await page.evaluate(() => window.applicationCallbacks),0);
    assert.deepEqual(requests,[]);
  } finally {await browser.close();}
});

// All fixtures below are offline structural examples, never live-provider acceptance.
test('offline visible provider and dedicated human panels return bounded evidence', async () => {
  const {inspectOutcome} = await import('../browser/ats-contract.mjs');
  const browser=await chromium.launch({executablePath:process.env.JOBBY_TEST_CHROME || '/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
  try {
    const page=await browser.newPage();
    const fixtures=[
      ['<div class="g-recaptcha"><div role="checkbox" aria-checked="false">Check</div></div>','recaptcha','active','control'],
      ['<div class="g-recaptcha"><div role="checkbox">Check</div></div>','recaptcha','unknown','control'],
      ['<div class="h-captcha"><input type="checkbox"></div>','hcaptcha','active','control'],
      ['<div class="cf-turnstile"><input type="checkbox"></div>','turnstile','active','control'],
      ['<div id="challenge-running">Checking your browser</div>','turnstile','active','interstitial'],
      ['<section aria-label="Verify you are human"><button>Continue</button></section>','generic','active','panel'],
      ['<div class="human-verification">Verify you are human<button>Continue</button></div>','generic','active','panel'],
      ['<div role="dialog" aria-labelledby="human"><h2 id="human">Please confirm that you are human.</h2><button>Continue</button></div>','generic','active','panel'],
      ['<fieldset><legend>Complete the security check</legend><input></fieldset>','generic','active','panel'],
      ['<iframe title="reCAPTCHA" src="https://www.google.com/recaptcha/api2/anchor?k=synthetic-private-sitekey" srcdoc="Offline fixture" width="304" height="78"></iframe>','recaptcha','unknown','embedded_frame'],
      ['<iframe src="https://www.recaptcha.net/recaptcha/api2/bframe?k=synthetic-private-sitekey" srcdoc="Offline fixture" width="300" height="300"></iframe>','recaptcha','active','challenge_frame'],
      ['<iframe title="Main content of the hCaptcha challenge" srcdoc="Offline fixture" width="300" height="300"></iframe>','hcaptcha','active','challenge_frame'],
      ['<iframe src="https://newassets.hcaptcha.com/captcha/v1/checkbox.html#synthetic-private-sitekey" srcdoc="Offline fixture" width="300" height="80"></iframe>','hcaptcha','unknown','embedded_frame'],
      ['<iframe src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/test?secret=synthetic-private-sitekey" srcdoc="Offline fixture" width="300" height="65"></iframe>','turnstile','unknown','embedded_frame'],
      ['<div class="g-recaptcha" style="width:300px;height:78px"></div>','recaptcha','unknown','embedded_control'],
      ['<iframe sandbox srcdoc="Offline opaque frame" width="300" height="80"></iframe>','unknown','unknown','uninspectable_frame'],
      ['<iframe srcdoc="&lt;section aria-label=&quot;Verify you are human&quot;&gt;Check&lt;/section&gt;" width="300" height="80"></iframe>','generic','active','panel'],
    ];
    const cfg={successSelector:'#success',expectedText:'Application received',formSelector:'form',challengeSelector:'#wrong',errorSelector:'#error'};
    for (const [html,provider,state,evidence] of fixtures) {
      await page.setContent('<div id="success">Application received</div>'+html);
      const r=await page.evaluate(inspectOutcome,cfg);
      assert.equal(r.outcome,state === 'active' ? 'challenge' : 'uncertain',evidence+':'+provider);
      assert.equal(r.verification.presence,'observed');
      assert.ok(r.verification.signals.some(s => s.provider === provider && s.state === state && s.evidence === evidence));
      assert.equal(JSON.stringify(r).includes('synthetic-private'),false);
      assert.equal(JSON.stringify(r).includes('Offline'),false);
      assert.ok(r.verification.signals.length <= 32);
      for (const s of r.verification.signals) {
        assert.deepEqual(Object.keys(s).sort(),['evidence','provider','state']);
        assert.ok(['recaptcha','hcaptcha','turnstile','generic','unknown'].includes(s.provider));
        assert.ok(['active','unknown','checked'].includes(s.state));
        assert.ok(['control','panel','interstitial','embedded_control','embedded_frame','challenge_frame','verification_error','uninspectable_frame','inspection_limit','inspection_failed','operator_selector'].includes(s.evidence));
      }
    }
  } finally {await browser.close();}
});

test('offline hidden providers, scripts, response fields, badges and ordinary prose are not active proof', async () => {
  const {inspectOutcome} = await import('../browser/ats-contract.mjs');
  const browser=await chromium.launch({executablePath:process.env.JOBBY_TEST_CHROME || '/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
  try {
    const page=await browser.newPage();
    const control='<div class="g-recaptcha"><input type="checkbox"></div>';
    const fixtures=[
      '<script type="text/plain" src="https://www.google.com/recaptcha/api.js"></script>',
      '<input type="hidden" name="g-recaptcha-response" value="synthetic-token"><textarea name="h-captcha-response" hidden>synthetic-token</textarea>',
      '<div class="grecaptcha-badge" style="width:30px;height:30px">reCAPTCHA</div>',
      '<div class="g-recaptcha"><div class="grecaptcha-badge" style="width:30px;height:30px">reCAPTCHA</div></div>',
      '<iframe title="reCAPTCHA" width="30" height="30" srcdoc="Badge"></iframe>',
      '<p>Our team builds captcha tools. This robot is a demo.</p><section><h2>About CAPTCHA and robot detection</h2></section>',
      '<section><h2>Verify you are human resources manager</h2></section>',
      // visibility:hidden is overridable; its formerly hidden expectation was incorrect.
      ...['display:none','opacity:0','content-visibility:hidden'].map(style=>`<div style="${style}"><div style="visibility:visible;opacity:1">${control}</div></div>`),
      ...['hidden','collapse'].map(value=>`<div style="visibility:${value}">${control}</div>`),
      `<div hidden>${control}</div>`,
      '<iframe hidden title="reCAPTCHA" srcdoc="Hidden" width="300" height="80"></iframe>',
      '<div style="opacity:0"><iframe title="reCAPTCHA" srcdoc="Hidden" width="300" height="80"></iframe></div>',
    ];
    const cfg={successSelector:'#success',expectedText:'Application received',formSelector:'form',challengeSelector:'#captcha',errorSelector:'#error'};
    for (const html of fixtures) {
      await page.setContent('<div id="success">Application received</div>'+html);
      const r=await page.evaluate(inspectOutcome,cfg);
      assert.equal(r.outcome,'confirmation_observed',html);
      assert.deepEqual(r.verification,{presence:'not_observed',active:false,uncertain:false,signals:[]});
      // No marker observation alone grants no authority or confirmation.
      assert.equal((await page.evaluate(inspectOutcome,{})).outcome,'uncertain');
    }
    await page.setContent('<div id="captcha">Human check</div>');
    assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'challenge');
    assert.equal((await page.evaluate(inspectOutcome,{challengeSelector:'['})).outcome,'uncertain');
    await page.setContent('<div id="success">Application received extra text</div>');
    assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'uncertain');
    await page.setContent('<div id="success">Application received</div><form hidden></form>');
    assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'uncertain');
  } finally {await browser.close();}
});

// Effective-presentation regressions only, never live-provider acceptance or completion.
test('offline effective presentation governs automatic, challenge and error observation', async t => {
  const {inspectOutcome} = await import('../browser/ats-contract.mjs');
  const browser=await chromium.launch({executablePath:process.env.JOBBY_TEST_CHROME || '/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
  try {
    const page=await browser.newPage();
    const requests=[];
    page.on('request',r=>requests.push(r.url()));
    const fixtures=[
      ['own visible','','visibility:visible',false,true],
      ['ancestor hidden overridden','style="visibility:hidden"','visibility:visible',false,true],
      ['ancestor collapse overridden','style="visibility:collapse"','visibility:visible',false,true],
      ['ancestor hidden display override','hidden style="display:block"','',false,true],
      ['own hidden display override','','display:block',true,true],
      ['ancestor default hidden','hidden','',false,false],
      ['own default hidden','','',true,false],
      ...['hidden','collapse'].flatMap(value=>[
        [`own visibility ${value}`,'',`visibility:${value}`,false,false],
        [`ancestor visibility ${value}`,`style="visibility:${value}"`,'',false,false],
      ]),
      ...['display:none','opacity:0','content-visibility:hidden'].flatMap(style=>[
        [`own ${style}`,'',style,false,false],
        [`ancestor ${style}`,`style="${style}"`,'display:block;visibility:visible;opacity:1;content-visibility:visible',false,false],
      ]),
    ];
    for (const [name,ancestor,style,hidden,rendered] of fixtures) await t.test(name,async () => {
      const outcomes={};
      for (const mode of ['automatic','challenge','error']) {
        const provider=mode === 'automatic' ? 'class="g-recaptcha"' : '';
        await page.setContent(`<div id="success">Application received</div><div ${ancestor}><div id="target" ${provider} ${hidden ? 'hidden' : ''} style="${style}"><input type="checkbox" style="display:inline-block;visibility:inherit;opacity:1;content-visibility:visible"></div></div>`);
        const presentation=await page.evaluate(() => {
          const panel=document.querySelector('#target'),control=panel.querySelector('input');
          return {
            visibility:getComputedStyle(control).visibility,
            boxes:[panel,control].every(n => [...n.getClientRects()].some(r => r.width > 0 && r.height > 0)),
            rendered:control.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}),
          };
        });
        // Browser presentation is an independent prerequisite, not the detector's verdict.
        assert.equal(presentation.rendered,rendered,mode+': '+name);
        if (rendered) {
          assert.equal(presentation.visibility,'visible');
          assert.equal(presentation.boxes,true);
        }
        await page.evaluate(() => {
          window.presentationActions=0;
          window.presentationMutations=0;
          for (const event of ['click','input','change','submit','keydown']) document.addEventListener(event,()=>window.presentationActions++);
          HTMLElement.prototype.click=()=>{window.presentationActions++;throw new Error('Automated click');};
          for (const method of ['submit','requestSubmit']) HTMLFormElement.prototype[method]=()=>{window.presentationActions++;throw new Error('Automated submit');};
          new MutationObserver(records=>window.presentationMutations+=records.length).observe(document,{subtree:true,childList:true,attributes:true,characterData:true});
        });
        const snapshot=()=>({dom:document.documentElement.outerHTML,checked:document.querySelector('input').checked});
        const before=await page.evaluate(snapshot);
        const cfg={successSelector:'#success',expectedText:'Application received',formSelector:'form',challengeSelector:mode === 'challenge' ? '#target' : '#wrong',errorSelector:mode === 'error' ? '#target' : '#error'};
        const r=await page.evaluate(inspectOutcome,cfg);
        assert.deepEqual(await page.evaluate(snapshot),before);
        assert.deepEqual(await page.evaluate(()=>[window.presentationActions,window.presentationMutations]),[0,0]);
        assert.deepEqual(requests,[]);
        outcomes[mode]=r.outcome;
        if (!rendered) assert.deepEqual(r.verification,{presence:'not_observed',active:false,uncertain:false,signals:[]});
      }
      assert.deepEqual(outcomes,rendered ? {automatic:'challenge',challenge:'challenge',error:'error'} : {automatic:'confirmation_observed',challenge:'confirmation_observed',error:'confirmation_observed'});
    });
  } finally {await browser.close();}
});

test('offline human completion is reobserved without mutation, token access or browser actions', async () => {
  const {inspectOutcome} = await import('../browser/ats-contract.mjs');
  const browser=await chromium.launch({executablePath:process.env.JOBBY_TEST_CHROME || '/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
  try {
    const page=await browser.newPage();
    const requests=[];
    page.on('request',r=>requests.push(r.url()));
    await page.setContent('<form><input name="answer" value="synthetic-answer"><input type="hidden" name="g-recaptcha-response" value="synthetic-private-token"><div class="g-recaptcha"><input id="human" type="checkbox"></div></form><div id="error" hidden>Verification expired</div>');
    const snapshot=()=>({dom:document.documentElement.outerHTML,data:[...new FormData(document.querySelector('form')).entries()]});
    await page.evaluate(()=>{
      window.observerActions=0;
      for (const event of ['click','input','change','submit','keydown']) document.addEventListener(event,()=>window.observerActions++);
      HTMLElement.prototype.click=()=>{window.observerActions++;throw new Error('Automated click');};
      for (const method of ['submit','requestSubmit']) HTMLFormElement.prototype[method]=()=>{window.observerActions++;throw new Error('Automated submit');};
      navigator.sendBeacon=()=>{window.observerActions++;throw new Error('Network API access');};
      for (const name of ['grecaptcha','hcaptcha','turnstile']) Object.defineProperty(window,name,{get(){window.observerActions++;throw new Error('Token API access');}});
      const response=document.querySelector('[name="g-recaptcha-response"]');
      Object.defineProperty(response,'value',{get(){window.observerActions++;throw new Error('Token value access');}});
      response.getAttribute=()=>{window.observerActions++;throw new Error('Token attribute access');};
      for (const name of ['fetch','XMLHttpRequest']) Object.defineProperty(window,name,{get(){window.observerActions++;throw new Error('Network API access');}});
      window.observerMutations=0;
      new MutationObserver(records=>window.observerMutations+=records.length).observe(document,{subtree:true,childList:true,attributes:true,characterData:true});
    });
    const cfg={successSelector:'#success',expectedText:'Application received',formSelector:'form',challengeSelector:'#captcha',errorSelector:'#error'};
    let before=await page.evaluate(snapshot);
    for (let i=0;i<2;i++) assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'challenge');
    assert.deepEqual(await page.evaluate(snapshot),before);
    assert.equal(await page.evaluate(()=>window.observerMutations),0);
    // Simulate human edits in the fixture only; production observer never writes them.
    await page.evaluate(()=>{document.querySelector('#human').checked=true;document.querySelector('[name="answer"]').value='synthetic-human-edit';});
    before=await page.evaluate(snapshot);
    let r=await page.evaluate(inspectOutcome,cfg);
    assert.equal(r.outcome,'uncertain'); // Checked is not submitted or authorized.
    assert.deepEqual(r.verification,{presence:'observed',active:false,uncertain:false,signals:[{provider:'recaptcha',state:'checked',evidence:'control'}]});
    assert.deepEqual(await page.evaluate(snapshot),before);
    await page.evaluate(()=>{
      const frame=document.createElement('iframe');
      frame.title='reCAPTCHA';frame.width='300';frame.height='80';frame.srcdoc='Offline still uninspectable provider state';document.body.append(frame);
    });
    assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'uncertain');
    await page.evaluate(()=>document.querySelector('iframe').remove());
    await page.evaluate(()=>{document.querySelector('#error').hidden=false;});
    assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'error');
    await page.evaluate(()=>{document.querySelector('#human').checked=false;});
    assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'challenge');
    await page.setContent('<div class="g-recaptcha"><input type="checkbox" checked><div class="rc-anchor-error-msg">Verification expired</div></div>');
    assert.equal((await page.evaluate(inspectOutcome,cfg)).outcome,'challenge');
    assert.equal(await page.evaluate(()=>window.observerActions),0);
    assert.deepEqual(requests,[]);
  } finally {await browser.close();}
});
