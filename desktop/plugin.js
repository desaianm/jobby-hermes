import { host, gatewayActivationEpoch, useValue, useQuery, useMutation, useQueryClient, Button, Input, Textarea, Badge, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA } from '@hermes/plugin-sdk';
import { createElement as h, useState, useRef, useLayoutEffect } from 'react';

const scopeKey = (connection, profile, focused, owner) => JSON.stringify([connection, profile, focused, owner?.connectionId ?? null, owner?.profile ?? null, gatewayActivationEpoch()]);
const scopeNow = () => scopeKey(host.state.connectionId.get(), host.state.profile.get(), host.state.focusedSessionProfile.get(), host.state.focusedSessionOwner.get());
const scopeStores = () => [host.state.connectionId, host.state.profile, host.state.focusedSessionProfile, host.state.focusedSessionOwner];

// Pending React Query mutations survive unmount. Retire their closures at the
// component boundary AND synchronously on host transitions, including A→B→A.
function useLifetime(scope) {
  const live = useRef(false);
  useLayoutEffect(() => {
    live.current = true;
    const stops = scopeStores().map(store => store.listen(() => { if (scopeNow() !== scope) live.current = false; }));
    return () => { live.current = false; stops.forEach(stop => stop()); };
  }, [scope]);
  return () => live.current && scopeNow() === scope;
}
const text = { initialize_resume: 'Import your source resume to begin.', intake_posting: 'Add the posting you selected.', select_posting: 'Choose a saved posting to continue.', prepare_materials: 'Prepare documents from your imported source.', review_exact_generation: 'Inspect both PDFs and DOCX files for this generation. Visual review is still pending.', hold_existing_application: 'This application is on hold. Resolve its existing attempt in the operator workflow before preparing again.', capture_attachment_manifest: 'Review is recorded. Attachment capture belongs to the operator workflow.', external_browser_pending: 'Continue only through the separate, authorized operator workflow.' };
const panel = { border: '1px solid var(--ui-stroke-secondary)', borderRadius: 6, padding: 16, minWidth: 0 };
const stack = { display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 };
const row = { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' };
const button = (label, props = {}) => h(Button, { type: 'button', style: { fontSize: 13, whiteSpace: 'normal', height: 'auto', minHeight: 32 }, ...props }, label);
const hint = value => h('p', { style: { margin: 0, color: 'var(--ui-text-secondary)' } }, value);
function checked(value) { if (!value?.ok) throw new Error('Local operation unavailable'); return value; }
function field(label, value, update, props = {}) {
  const Component = props.multiline ? Textarea : Input;
  const { multiline, ...input } = props;
  return h('label', { style: stack }, h('span', null, label), h(Component, { value, onChange: e => update(e.target.value), required: true, style: { width: '100%', boxSizing: 'border-box', fontSize: 14, minHeight: multiline ? 130 : 36 }, ...input }));
}

export function Desk({ ctx }) {
  const connection = useValue(host.state.connectionId);
  const profile = useValue(host.state.profile);
  const focused = useValue(host.state.focusedSessionProfile);
  const owner = useValue(host.state.focusedSessionOwner);
  const [epoch, setEpoch] = useState(0);
  useLayoutEffect(() => {
    let previous = scopeNow();
    const stops = scopeStores().map(store => store.listen(() => {
      const next = scopeNow();
      if (next !== previous) { previous = next; setEpoch(value => value + 1); }
    }));
    return () => stops.forEach(stop => stop());
  }, []);
  const scope = scopeKey(connection, profile, focused, owner);
  // Remount before any new profile render: inputs, selection, errors and documents
  // all belong to this scope. Late responses stay in retired query/mutation state.
  return h(ScopedDesk, { key: `${scope}:${epoch}`, scope, ctx });
}

function ScopedDesk({ ctx, scope }) {
  const alive = useLifetime(scope);
  const cache = useQueryClient();
  const prefix = [ctx.source, 'desk', scope];
  const [selected, select] = useState(null);
  const [pdf, setPdf] = useState('');
  const [replace, setReplace] = useState(false);
  const [posting, setPosting] = useState({ company: '', title: '', url: '', location: '', description: '' });
  const [explicit, setExplicit] = useState(false);
  const query = (key, path) => ({ queryKey: [...prefix, key], queryFn: async ({ signal }) => {
    if (!alive() || signal.aborted) throw new Error('Scope changed');
    const result = checked(await ctx.rest(path));
    if (!alive() || signal.aborted) throw new Error('Scope changed');
    return result;
  }, retry: false, gcTime: 0, refetchOnWindowFocus: false });
  const overview = useQuery(query('overview', '/desk'));
  const discovery = useQuery(query('discovery', '/discovery'));
  const job = useQuery({ ...query(selected, `/desk/${selected}`), enabled: selected !== null });
  const mutation = useMutation({ mutationKey: [...prefix, 'operation'], gcTime: 0, mutationFn: async ({ path, body }) => {
    if (!alive()) throw new Error('Scope changed');
    const result = checked(await ctx.rest(path, { method: 'POST', body, timeoutMs: 120000 }));
    if (!alive()) throw new Error('Scope changed');
    return result;
  }, onSuccess: result => {
    if (!alive()) return;
    cache.invalidateQueries({ queryKey: prefix });
    if (result.shortlist) { cache.setQueryData([...prefix, 'discovery'], result); return; }
    if (result.job) select(result.job.id);
    setPdf(''); setReplace(false); setPosting({ company: '', title: '', url: '', location: '', description: '' }); setExplicit(false);
  } });
  const act = (path, body) => mutation.mutate({ path, body });
  const refresh = () => { mutation.reset(); cache.invalidateQueries({ queryKey: prefix }); };
  const busy = mutation.isPending;
  const current = job.data;
  const unavailable = overview.isError || job.isError || mutation.isError || discovery.isError;
  const meta = current?.materials;
  const fresh = meta && ['pending_visual_review', 'visual_approved'].includes(meta.qa_state);
  return h('main', { 'aria-label': 'Jobby desk', style: { ...stack, padding: 16, fontSize: 14, lineHeight: 1.5, color: 'var(--ui-text-primary)', overflowWrap: 'anywhere', maxWidth: 1400, margin: '0 auto', boxSizing: 'border-box', width: '100%' } },
    h('header', { style: row }, h('h1', { style: { margin: 0, fontSize: 22 } }, 'Jobby desk'), h(Badge, { variant: 'muted', style: { fontSize: 13, whiteSpace: 'normal' } }, 'Local drafts · no submission'), button('Refresh', { onClick: refresh, disabled: busy })),
    hint('Import your source, confirm search preferences, inspect your shortlist, then prepare documents for a selected posting. You can also paste a posting. Nothing here submits an application.'),
    unavailable && h('div', { role: 'alert', style: panel }, 'The local desk is unavailable. Check that the Jobby Python backend is enabled for this profile and that your inputs are valid, then Refresh. No submission was performed.'),
    (overview.isPending || job.isFetching || busy) && h('p', { role: 'status' }, busy ? 'Working on your requested operation…' : 'Loading this desk…'),
    h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-start' } },
      h('aside', { 'aria-label': 'Source and selected postings', style: { ...stack, flex: '1 1 280px' } },
        h('section', { style: panel }, h('h2', { style: { marginTop: 0, fontSize: 17 } }, '1. Source resume'),
          hint(overview.data?.source_status === 'imported' ? 'Source imported. Documents remain bound to its exact bytes.' : 'Start with your authoritative text PDF resume.'),
          h('form', { style: stack, onSubmit: e => { e.preventDefault(); act('/initialize', { pdf_path: pdf, replace }); } },
            field('Absolute PDF path on the Hermes backend machine', pdf, setPdf, { maxLength: 2000, placeholder: '/absolute/path/resume.pdf' }),
            hint('For a remote connection, this path is on the remote machine. This desk does not browse your filesystem.'),
            h('label', { style: row }, h('input', { type: 'checkbox', checked: replace, onChange: e => setReplace(e.target.checked) }), 'Replace imported source and invalidate existing documents'),
            button('Import source PDF', { type: 'submit', disabled: busy || !pdf.startsWith('/') }))),
        discovery.data && !(busy && mutation.variables?.path === '/initialize') && h(SearchSetup, {
          key: `${discovery.data.source_token}:${JSON.stringify(discovery.data.preferences)}:${JSON.stringify(discovery.data.queries)}`,
          data: discovery.data, busy,
          confirm: body => act('/discovery', { operation: 'confirm', ...body }),
          search: () => act('/discovery', { operation: 'search' }),
          select: id => { mutation.reset(); select(id); }
        }),
        h('section', { style: panel }, h('h2', { style: { marginTop: 0, fontSize: 17 } }, 'Or paste a selected posting'),
          h('form', { style: stack, onSubmit: e => { e.preventDefault(); if (explicit) act('/posting', posting); } },
            ...[['company', 'Company', 250], ['title', 'Job title', 250], ['url', 'Posting URL', 2000], ['location', 'Location', 500], ['description', 'Posting description', 60000]].map(([key, label, maxLength]) => h('div', { key }, field(label, posting[key], value => setPosting({ ...posting, [key]: value }), { maxLength, multiline: key === 'description', type: key === 'url' ? 'url' : 'text', required: key !== 'location' }))),
            h('label', { style: row }, h('input', { type: 'checkbox', required: true, checked: explicit, onChange: e => setExplicit(e.target.checked) }), 'I selected this posting for local document preparation'),
            button('Save selected posting', { type: 'submit', disabled: busy || !explicit }))),
        h('section', { style: panel }, h('h2', { style: { marginTop: 0, fontSize: 17 } }, 'Saved postings'),
          overview.data?.jobs.length ? h('div', { style: stack }, ...overview.data.jobs.map(item => button(`${item.title} · ${item.company}`, { key: item.id, 'aria-pressed': selected === item.id, variant: selected === item.id ? 'secondary' : 'outline', onClick: () => { mutation.reset(); select(item.id); }, disabled: busy }))) : hint('No saved postings yet. Add the one you want to work on.'))),
      h('section', { 'aria-label': 'Document dossier', style: { ...stack, flex: '3 1 520px', ...panel } },
        h('h2', { style: { margin: 0, fontSize: 19 } }, current ? `${current.job.title} · ${current.job.company}` : 'Your document dossier'),
        !current && hint(text[overview.data?.next_action] || 'Import a resume and select a posting to see its documents here.'),
        current && h('div', { style: stack },
          hint(current.job.location || 'Location not specified'),
          h('p', { role: 'status', style: { margin: 0 } }, text[current.next_action] || 'Continue in the operator workflow.'),
          button(meta ? 'Regenerate documents' : 'Prepare documents', { disabled: busy || overview.data?.source_status !== 'imported' || current.next_action === 'hold_existing_application', onClick: () => act('/prepare', { job_id: selected }) }),
          h('details', null, h('summary', null, 'Posting and preparation boundaries'), hint(current.job.description), hint('Direct selection allows preparation. Discovery ranking and downstream holds still apply.'), ...(current.downstream_blockers || []).map((value, i) => h('p', { key: i }, value)), current.missing_answers?.length > 0 && hint('Some private application answers are unknown. Resolve them through the operator workflow; this desk does not display or edit them.')),
          meta && !fresh && hint('Documents are stale or unavailable. Reimport changed source if needed, then regenerate and inspect again.'),
          fresh && !job.isFetching && !unavailable && !busy && h(Documents, { key: `${scope}:${selected}:${meta.generation_id}:${meta.review_token}`, ctx, scope, jobId: selected, meta, prefix })))));
}

function choice(label, value, update, options, disabled) {
  return h('div', { style: stack }, h('span', null, label),
    h(Select, { value, onValueChange: update, disabled },
      h(SelectTrigger, { 'aria-label': label, style: { width: '100%', whiteSpace: 'normal', height: 'auto', minHeight: 36 } }, h(SelectValue, { placeholder: 'Choose explicitly' })),
      h(SelectContent, null, ...options.map(([key, name]) => h(SelectItem, { key, value: key }, name)))));
}

export function SearchSetup({ data, busy, confirm, search, select }) {
  const saved = data.preferences;
  const [preferences, setPreferences] = useState(saved ? { ...saved, remote: String(saved.remote), hours_old: String(saved.hours_old), per_query: String(saved.per_query), total: String(saved.total) } : { country: '', location: '', remote: '', hours_old: '', per_query: '', total: '', order: '' });
  const [queries, setQueries] = useState(data.confirmed ? data.queries.filter(term => data.proposals.some(p => p.term === term)) : data.proposals.slice(0, 3).map(p => p.term));
  const [approved, setApproved] = useState(false);
  const update = key => value => { setPreferences(current => ({ ...current, [key]: value })); setApproved(false); };
  const payload = { ...preferences, remote: preferences.remote === 'true', hours_old: Number(preferences.hours_old), per_query: Number(preferences.per_query), total: Number(preferences.total) };
  const countries = data.supported_countries || [];
  const valid = data.source_token && queries.length > 0 && queries.length <= 3 && countries.includes(preferences.country) && preferences.location.trim() && preferences.remote !== '' && preferences.order && [[payload.hours_old, 720], [payload.per_query, 10], [payload.total, 25]].every(([value, cap]) => Number.isInteger(value) && value >= 1 && value <= cap);
  const unchanged = saved && Object.keys(payload).every(key => payload[key] === saved[key]) && JSON.stringify(queries) === JSON.stringify(data.queries);
  return h('section', { 'aria-label': 'Resume search and shortlist', style: { ...panel, ...stack } },
    h('h2', { style: { margin: 0, fontSize: 17 } }, '2. Find jobs from your resume'),
    hint('Provider-supported international discovery · Indeed and LinkedIn via JobSpy. Queries contain only the approved public role or skill terms below. Resume text and employer history are not sent.'),
    hint('Search setup does not confirm work authorization, employer eligibility or application consent. Eventual auto-apply within approved rules is NOT ACTIVE.'),
    ...(data.warnings || []).map((warning, i) => h('p', { key: i, role: 'status' }, warning)),
    h('form', { style: stack, onSubmit: e => { e.preventDefault(); if (valid && approved) confirm({ source_token: data.source_token, queries, preferences: payload }); } },
      hint('Inspect the source suggestions. Choose up to three; unsupported roles and seniority are not inferred.'),
      ...data.proposals.map(proposal => h('div', { key: proposal.term, style: stack },
        h('label', { style: row }, h(Checkbox, { checked: queries.includes(proposal.term), disabled: busy || (!queries.includes(proposal.term) && queries.length >= 3), onCheckedChange: checked => { setQueries(current => checked === true ? [...current, proposal.term] : current.filter(term => term !== proposal.term)); setApproved(false); } }), proposal.term),
        ...proposal.evidence.map((evidence, i) => hint(`${evidence.fact_id}${evidence.role ? ` · ${evidence.role}` : ''}: ${evidence.excerpt}`)))),
      choice('Search country', preferences.country, update('country'), countries.map(country => [country, country]), busy),
      field('Public search location', preferences.location, update('location'), { maxLength: 120, disabled: busy, placeholder: 'City, region or selected country' }),
      hint('Use public place names only: a city/region name, or the selected country for country-wide search. Names may use Unicode letters; recognizable contact, credential and resume patterns and invalid characters are rejected. Arbitrary sensitive prose may not be detected. The selected country is added explicitly. This validates input, not geocoding; verify returned listings.'),
      choice('Remote preference', preferences.remote, update('remote'), [['true', 'Remote only'], ['false', 'Include all arrangements']], busy),
      ...[['hours_old', 'Freshness in hours', 720], ['per_query', 'Results per query', 10], ['total', 'Total results per run', 25]].map(([key, label, max]) => h('div', { key }, field(label, preferences[key], update(key), { type: 'number', min: 1, max, step: 1, disabled: busy }))),
      choice('Shortlist order', preferences.order, update('order'), [['lexical', 'Lexical coverage'], ['newest', 'Newest source posting first'], ['oldest', 'Oldest source posting first']], busy),
      h('label', { style: row }, h(Checkbox, { checked: approved, disabled: busy, onCheckedChange: value => setApproved(value === true) }), 'I confirm these search preferences and source-backed query terms'),
      button('Confirm search setup', { type: 'submit', disabled: busy || !valid || !approved })),
    hint(data.confirmed ? 'Search setup confirmed for this imported source.' : 'Confirm setup before searching. Replacing or changing the source requires confirmation again.'),
    button('Search approved terms', { disabled: busy || !valid || !data.confirmed || !unchanged, onClick: search }),
    data.last_run && h('div', { role: 'status', style: stack }, hint(`Last search: ${data.last_run.outcome} · ${data.last_run.unique_jobs_observed} distinct stored postings observed. Existing shortlist retained.`), ...data.last_run.errors.map((error, i) => hint(`${error.query}: ${error.message}`))),
    h('h3', { style: { margin: 0, fontSize: 16 } }, 'Persistent shortlist'),
    hint(data.ranking_method),
    hint('Up to 100 stored results shown. Unknown source dates stay unknown; search freshness is a provider filter, not employer verification.'),
    data.shortlist.length === 0 && hint('No discovered postings yet. Search after confirming setup, or paste a selected posting.'),
    ...data.shortlist.map(item => h('div', { key: item.id, style: { ...panel, ...stack } },
      button(`${item.title} · ${item.company}`, { disabled: busy, onClick: () => select(item.id) }),
      hint(`${item.location || 'Location unknown'} · Posted: ${item.posted_date || 'unknown'} · ${item.status}`),
      h('a', { href: item.job_url, target: '_blank', rel: 'noreferrer' }, 'Source listing'),
      hint(`Matching terms: ${item.matching_terms.join(', ') || 'none'}`),
      ...item.evidence.map(evidence => hint(`${evidence.fact_id}: ${evidence.excerpt}`)),
      hint(`Posting terms without source overlap: ${item.unmatched_posting_terms.join(', ') || 'none identified'}`),
      ...item.unknowns.map(hint))));
}

function Documents({ ctx, scope, jobId, meta, prefix }) {
  const alive = useLifetime(scope);
  const [notice, setNotice] = useState('');
  const binding = { job_id: jobId, generation_id: meta.generation_id, review_token: meta.review_token };
  const read = async filename => {
    if (!alive()) throw new Error('Scope changed');
    const value = checked(await ctx.rest('/artifact', { method: 'POST', body: { ...binding, filename } }));
    if (!alive() || value.generation_id !== meta.generation_id || value.review_token !== meta.review_token) throw new Error('Scope changed');
    return value;
  };
  const files = useQuery({ queryKey: [...prefix, 'documents', jobId, meta.generation_id, meta.review_token], queryFn: async ({ signal }) => {
    const result = await Promise.all(['preview.png', 'cover_preview.png', 'evidence.json'].map(read));
    if (!alive() || signal.aborted) throw new Error('Scope changed');
    return result;
  }, gcTime: 0, retry: false, refetchOnWindowFocus: false });
  const download = useMutation({ mutationKey: [...prefix, 'download', jobId, meta.generation_id], gcTime: 0, mutationFn: read, onSuccess: file => {
    if (!alive()) return;
    const link = document.createElement('a');
    link.href = `data:${file.content_type};base64,${file.base64}`; link.download = file.filename;
    link.click(); setNotice(`${file.filename} opened for download. Visual review remains a separate operator action.`);
  } });
  const evidence = files.data?.[2].evidence;
  return h('div', { style: stack },
    h('h3', { style: { margin: 0, fontSize: 17 } }, '3. Inspect this generation'),
    hint(meta.qa_state === 'visual_approved' ? 'Operator review recorded for this generation.' : 'Visual review pending. Previews show the generated PDFs. DOCX pagination requires a separate check in a document editor.'),
    hint('Viewing or downloading files does not record approval. Review both PDFs and DOCX files through the existing operator workflow.'),
    (files.isError || download.isError) && h('p', { role: 'alert' }, 'These exact documents are unavailable. Refresh the posting and regenerate if its source or bytes changed.'),
    files.isPending && h('p', { role: 'status' }, 'Loading exact PDF previews and evidence…'),
    files.data && !files.isError && h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 19rem), 1fr))', gap: 16 } },
      ...['Resume', 'Cover letter'].map((label, index) => h('article', { key: label, style: stack }, h('h4', { style: { margin: 0 } }, `${label} · PDF preview`), h('img', { alt: `${label} preview from current generated PDF`, src: `data:image/png;base64,${files.data[index].base64}`, style: { width: '100%', height: 'auto', border: '1px solid var(--ui-stroke-secondary)' } }), h('div', { style: row }, ...['pdf', 'docx'].map(ext => {
        const filename = `${index ? 'cover_letter' : 'resume'}.${ext}`;
        return button(`Download ${ext.toUpperCase()}`, { key: ext, variant: 'outline', disabled: download.isPending, onClick: () => download.mutate(filename) });
      }))))),
    notice && h('p', { role: 'status' }, notice),
    evidence && h('details', null, h('summary', null, 'Source evidence and gaps'), hint('Posting-term overlap guides emphasis; it does not verify qualifications or hiring fit.'), ...(evidence.gaps || []).map((gap, i) => h('p', { key: `gap-${i}` }, gap)), ...(evidence.evidence || []).filter(item => item.included).map(item => h('div', { key: item.fact_id, style: { ...panel, marginTop: 8 } }, h('p', null, item.text), hint(`Source excerpt: ${item.source_excerpt}`)))),
    h('details', null, h('summary', null, 'Exact document generation'), hint(`Generated ${meta.created}`), hint(`Generation ${meta.generation_id}`), ...Object.entries(meta.artifact_hashes || {}).map(([name, hash]) => h('p', { key: name }, `${name} · SHA-256 ${hash}`))));
}

export default {
  id: 'jobby', name: 'Jobby desk', defaultEnabled: false,
  register(ctx) {
    ctx.register({ id: 'desk', area: ROUTES_AREA, data: { path: '/jobby' }, render: () => h(Desk, { ctx }) });
    ctx.register({ id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: '/jobby', label: 'Jobby desk', codicon: 'files' } });
    ctx.register({ id: 'open', area: PALETTE_AREA, data: { id: 'jobby.open', label: 'Open Jobby desk', keywords: ['resume', 'posting', 'documents'], run: () => host.navigate('/jobby') } });
  }
};
