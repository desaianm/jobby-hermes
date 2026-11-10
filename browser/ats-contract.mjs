/** Browser-executable observation only. Selectors must come from the inspected form.
 * No values, names, filenames, answers or free page text leave this snapshot.
 * Re-run after a native option click, blur and a bounded readiness wait.
 */
export function inspectForm(config = {}) {
  const visible = n => !!n && n.getClientRects().length > 0 && getComputedStyle(n).visibility !== 'hidden';
  const query = selector => selector ? document.querySelector(selector) : null;
  const fields = [...document.querySelectorAll('input,textarea,select,[role="combobox"]')].filter(visible).map(n => {
    const wrapper = n.closest('[data-question],fieldset,[role="group"],.ashby-application-form-field-entry');
    const labels = [...(n.labels || [])];
    for (const id of (n.getAttribute('aria-labelledby') || '').split(/\s+/)) { const label=document.getElementById(id); if(label) labels.push(label); }
    const text = labels.map(l=>l.textContent).join(' ') + (wrapper?.querySelector('label,legend')?.textContent || '');
    return {type:n.type || n.getAttribute('role') || n.tagName.toLowerCase(),
      required:!!n.required || n.getAttribute('aria-required') === 'true' || wrapper?.getAttribute('aria-required') === 'true' || text.includes('*') || !!wrapper?.querySelector('[aria-label="required"],[data-required="true"]')};
  });
  const upload = query(config.uploadSelector);
  const replace = upload && [...upload.querySelectorAll('button')].find(b => visible(b) && b.textContent.trim() === 'Replace');
  const busy = upload?.getAttribute('aria-busy') === 'true' || [...(upload?.querySelectorAll('[role="progressbar"],[aria-busy="true"]') || [])].some(visible);
  const location = query(config.locationSelector), selected = query(config.selectedLocationSelector);
  return {fields, upload:!upload ? 'unknown' : replace && !replace.disabled && replace.getAttribute('aria-disabled') !== 'true' && !busy ? 'ready' : 'pending',
    locationSelected:!!location && !!selected && visible(selected) && typeof config.expectedLocation === 'string' && config.expectedLocation.length > 0 && selected.textContent.trim() === config.expectedLocation && location.value === config.expectedLocation && document.activeElement !== location};
}

/** Visually hide private surfaces before capture, preserving native form state.
 * Opacity composites the entire subtree, even descendants overriding visibility.
 * Recheck after rerenders; original styles alone are retained in this context.
 */
export function maskPrivateFields(selector = 'input[type="tel"],input[type="password"],input[autocomplete="tel"],[data-private]') {
  const key = Symbol.for('jobby.privateVisualMasks');
  const originals = globalThis[key] ??= new Map();
  const nodes = document.querySelectorAll(selector);
  for (const node of nodes) {
    if (!originals.has(node)) originals.set(node, node.getAttribute('style'));
    node.style.setProperty('transition', 'none', 'important');
    node.style.setProperty('opacity', '0', 'important');
  }
  return nodes.length;
}

/** Restore only visual styles; current answers and native events are untouched. */
export function restorePrivateFields() {
  const key = Symbol.for('jobby.privateVisualMasks');
  const originals = globalThis[key];
  if (!originals) return 0;
  for (const [node, style] of originals) {
    // Flush pending CSSOM serialization before removing an originally absent attribute.
    node.getAttribute('style');
    if (style === null) node.removeAttribute('style');
    else node.setAttribute('style', style);
  }
  const count = originals.size;
  delete globalThis[key];
  return count;
}

/** Observation, never a receipt. Match a freshly inspected dedicated panel exactly.
 * Hermes must bind URL/identity/attempt and review screenshot before native receipt.
 */
export function inspectOutcome(config = {}) {
  // Keep the detector inside this serialized observer: page.evaluate has no module scope.
  const visible = n => {
    if (!n || !n.getClientRects().length) return false;
    // Visibility can be overridden by descendants; CSS can override hidden's default display.
    const visibility=n.ownerDocument.defaultView.getComputedStyle(n).visibility;
    if (visibility === 'hidden' || visibility === 'collapse') return false;
    for (let a=n; a; a=a.parentElement) {
      const s=a.ownerDocument.defaultView.getComputedStyle(a);
      if (s.display === 'none' || Number(s.opacity) === 0 || s.contentVisibility === 'hidden') return false;
    }
    return [...n.getClientRects()].some(r => r.width > 0 && r.height > 0);
  };
  const signals=[];
  const add = (provider,state,evidence) => {
    if (!signals.some(s => s.provider === provider && s.state === state && s.evidence === evidence)) signals.push({provider,state,evidence});
  };
  let documents=0;
  const scan = (doc,depth=0) => {
    if (++documents > 16 || depth > 4) {add('unknown','unknown','inspection_limit');return;}
    for (const [selector,provider] of [['.g-recaptcha,#recaptcha-anchor,.recaptcha-checkbox','recaptcha'],['.h-captcha','hcaptcha'],['.cf-turnstile','turnstile']]) {
      for (const n of doc.querySelectorAll(selector)) {
        const controls=[...(n.matches('[role="checkbox"],input[type="checkbox"]') ? [n] : []),...n.querySelectorAll('[role="checkbox"],input[type="checkbox"]')].filter(visible);
        if (!visible(n) && !controls.length) continue;
        if (n.closest('.grecaptcha-badge') || (!controls.length && n.querySelector('.grecaptcha-badge') && ![...n.children].some(c => visible(c) && !c.matches('.grecaptcha-badge')))) continue;
        if (controls.length) {
          for (const c of controls) {
            const checked=c.type === 'checkbox' ? (c.indeterminate ? 'mixed' : String(c.checked)) : c.getAttribute('aria-checked');
            add(provider,checked === 'true' ? 'checked' : checked === 'false' ? 'active' : 'unknown','control');
          }
        } else add(provider,'unknown','embedded_control');
      }
    }
    // Exact labels on dedicated panels/headings, never body-wide keyword matching.
    const humanLabel = /^(?:(?:please )?(?:verify|confirm) (?:that )?you(?: are|'re) (?:a )?human|(?:please )?complete (?:the )?(?:captcha|security check)|(?:i am|i'm|i’m) not a robot|verify you are human to (?:continue|proceed))[.!]?$/i;
    for (const n of doc.querySelectorAll('[role="dialog"],[role="alert"],[role="group"],fieldset,section,h1,h2,h3,.captcha,#captcha,.human-verification,#human-verification')) {
      if (!visible(n)) continue;
      const labels=[n.getAttribute('aria-label') || ''];
      for (const id of (n.getAttribute('aria-labelledby') || '').split(/\s+/)) {
        const label=doc.getElementById(id);if (visible(label)) labels.push(label.textContent.trim());
      }
      if (n.matches('h1,h2,h3')) labels.push(n.textContent.trim());
      labels.push([...n.childNodes].filter(c => c.nodeType === Node.TEXT_NODE).map(c => c.textContent).join(' ').trim());
      for (const label of n.querySelectorAll(':scope > legend,:scope > h1,:scope > h2,:scope > h3,:scope > label')) if (visible(label)) labels.push(label.textContent.trim());
      if (labels.some(l => humanLabel.test(l))) add('generic','active','panel');
    }
    for (const n of doc.querySelectorAll('#challenge-running,#challenge-stage,.cf-challenge-running')) if (visible(n)) add('turnstile','active','interstitial');
    for (const n of doc.querySelectorAll('.rc-anchor-error-msg,.rc-anchor-error-message')) if (visible(n) && n.textContent.trim()) add('recaptcha','active','verification_error');
    for (const frame of doc.querySelectorAll('iframe,frame')) {
      if (!visible(frame)) continue;
      let provider='unknown',challenge=false;
      // Inspect provider host/path only. Never inspect query parameters or response fields.
      try {
        const url=new URL(frame.getAttribute('src') || '',doc.baseURI);
        if (/^(?:www\.)?(?:google\.com|recaptcha\.net)$/.test(url.hostname) && url.pathname.startsWith('/recaptcha/')) {provider='recaptcha';challenge=url.pathname.endsWith('/bframe');}
        if (/(^|\.)hcaptcha\.com$/.test(url.hostname)) provider='hcaptcha';
        if (url.hostname === 'challenges.cloudflare.com' && url.pathname.startsWith('/cdn-cgi/challenge-platform/')) provider='turnstile';
      } catch { /* Unknown frames remain subject to inspection below. */ }
      const title=(frame.getAttribute('title') || '').trim();
      if (/^recaptcha(?: challenge(?: expires in (?:two|\d+) minutes)?)?$/i.test(title)) {provider='recaptcha';challenge=/challenge/i.test(title);}
      if (/^(?:widget containing checkbox for hcaptcha security challenge|main content of the hcaptcha challenge)$/i.test(title)) {provider='hcaptcha';challenge=/^main content/i.test(title);}
      if (/^(?:cloudflare )?turnstile(?: (?:widget|challenge))?$/i.test(title)) provider='turnstile';
      if (provider !== 'unknown') {
        // Tiny attribution badges alone are not evidence of a blocking challenge.
        const r=frame.getBoundingClientRect();
        if (r.width < 80 || r.height < 40) continue;
        add(provider,challenge ? 'active' : 'unknown',challenge ? 'challenge_frame' : 'embedded_frame');
      } else {
        try {
          const child=frame.contentDocument;
          if (!child || child.readyState === 'loading') add('unknown','unknown','uninspectable_frame');
          else scan(child,depth+1);
        } catch {add('unknown','unknown','uninspectable_frame');}
      }
    }
  };
  try {scan(document);} catch {add('unknown','unknown','inspection_failed');}
  let invalidSelector=false;
  const any = selector => {
    try {return !!selector && [...document.querySelectorAll(selector)].some(visible);}
    catch {invalidSelector=true;return false;}
  };
  const explicitChallenge=any(config.challengeSelector),error=any(config.errorSelector);
  if (explicitChallenge) add('generic','active','operator_selector');
  const verification={presence:signals.length ? 'observed' : 'not_observed',active:signals.some(s => s.state === 'active'),uncertain:signals.some(s => s.state === 'unknown'),signals};
  if (explicitChallenge || verification.active) return {outcome:'challenge',verification};
  if (verification.uncertain || invalidSelector) return {outcome:'uncertain',verification};
  if (error) return {outcome:'error',verification};
  let success,formPresent;
  try {
    success=config.successSelector ? document.querySelector(config.successSelector) : null;
    formPresent=!!config.formSelector && !!document.querySelector(config.formSelector);
  } catch {return {outcome:'uncertain',verification};}
  const exact=typeof config.expectedText === 'string' && config.expectedText.trim().length>0 && success?.textContent.trim() === config.expectedText.trim();
  return {outcome:config.formSelector && config.challengeSelector && config.errorSelector && visible(success) && exact && !formPresent ? 'confirmation_observed' : 'uncertain',verification};
}
