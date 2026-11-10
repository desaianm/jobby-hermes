/** Owned desktop qualification: explicit harness or native CDP, with separate receipts.
 * Usage: node scripts/qualify_desktop_desk.mjs OUTPUT HERMES_SOURCE NODE_MODULES PYTHON
 * Optional native mode: append --native-cdp http://127.0.0.1:19338 --native-page http://127.0.0.1:15274/#/jobby
 * Native mode attaches only to that owned app; parent stages/enables the plugin.
 * Add --native-live --live-home /absolute/owned/temporary/home for the approved,
 * already initialized AI-agent source, supplied installed PYTHON runtime and
 * confirmed bounded public search. This route never initializes a fixture.
 * NODE_MODULES must contain esbuild, @tanstack/react-query, nanostores,
 * @nanostores/react, React/DOM and Hermes UI component dependencies.
 * No installs, active Hermes homes, employer requests or submission operations.
 */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, writeFile, mkdir, mkdtemp, rm, lstat, readdir, realpath, open } from 'node:fs/promises';
import { constants as fsConstants } from 'node:fs';
import { resolve, dirname, join, isAbsolute } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { createHash, randomUUID } from 'node:crypto';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const liveRoot = '/home/adcan288/tmp/jobby-live-acceptance-20261107';
const installedPython = liveRoot + '/runtime-native/bin/python';
const managedLiveHome = liveRoot + '/bundle-home';
const managedPython = managedLiveHome + '/installs/65f699a597de2c44/environments/61b324b1922344b891a3f4c3fbc6483a/venv/bin/python';

function assertOwnedSpelling(path, root = liveRoot) {
  assert.ok(typeof path === 'string' && isAbsolute(path) && resolve(path) === path && path.startsWith(root + '/'), 'Explicit canonical owned temporary path required');
}

async function checkedOwnedPath(path, root = liveRoot) {
  assertOwnedSpelling(path, root);
  let current = '/';
  for (const part of path.slice(1).split('/')) {
    current = join(current, part);
    const info = await lstat(current);
    assert.ok(!info.isSymbolicLink(), 'Owned data path contains a symlink');
    if (current === root || current.startsWith(root + '/')) assert.equal(info.uid, process.getuid(), 'Owned temporary path required');
  }
  return path;
}

export async function validateOwnedLiveHome(liveHome, python) {
  const managed = liveHome === managedLiveHome && python === managedPython;
  assert.ok(managed || (liveHome !== managedLiveHome && python === installedPython), 'Explicit supplied installed runtime required');
  await checkedOwnedPath(liveHome);
  assert.ok((await lstat(liveHome)).isDirectory(), 'Live home must be a directory');
  const workspace = join(liveHome, 'plugin-data/jobby/workspace');
  await checkedOwnedPath(workspace);
  // Metadata only: reject links in the data tree before the CLI owner opens it.
  // No profile, database or account file is read by this preflight.
  let remaining = 10000;
  const walk = async (folder, depth) => {
    assert.ok(depth <= 12, 'Owned workspace is too deep');
    for (const entry of await readdir(folder, { withFileTypes: true })) {
      assert.ok(--remaining >= 0, 'Owned workspace is too large');
      const path = join(folder, entry.name), info = await lstat(path);
      assert.ok(!info.isSymbolicLink(), 'Owned workspace contains a symlink');
      assert.ok(info.isFile() || info.isDirectory(), 'Regular owned data required');
      assert.equal(info.uid, process.getuid());
      if (info.isDirectory()) await walk(path, depth + 1);
    }
  };
  await walk(workspace, 0);
  await checkedOwnedPath(dirname(python));
  // Only these parent-provisioned executable links may resolve outside the
  // no-symlink data tree. Pin the managed base to its observed exact spelling.
  assert.equal(await realpath(python), managed
    ? managedLiveHome + '/tools/python-3.14.9+20261021-linux-x64/bin/python3.14'
    : '/home/adcan288/.hermes/tools/python-3.14.9+20261021-linux-x64/bin/python3.14', 'Installed runtime interpreter changed');
  return workspace;
}

export async function readNativePrivate({ liveHome, python, operation, jobId, timeoutMs = 15000 }, launch = spawn) {
  assert.ok(operation === 'show' || operation === 'status', 'Only read-only show/status are allowed');
  if (operation === 'show') assert.ok(Number.isSafeInteger(jobId) && jobId > 0 && jobId <= 999999999999, 'Numeric job ID required');
  else assert.equal(jobId, undefined);
  assert.ok(Number.isInteger(timeoutMs) && timeoutMs > 0 && timeoutMs <= 15000);
  const workspace = await validateOwnedLiveHome(liveHome, python);
  const args = ['-I', '-B', '-m', 'personal_jobby', ...(operation === 'show' ? ['show', String(jobId)] : ['status', '--brief'])];
  const options = { cwd: liveHome, env: { HOME: liveHome, JOBBY_ROOT: workspace, PYTHON_DOTENV_DISABLED: '1', PYTHONDONTWRITEBYTECODE: '1', PATH: '/usr/bin:/bin', LANG: 'C.UTF-8' }, stdio: ['ignore', 'pipe', 'pipe'] };
  let child;
  try { child = launch(python, args, options); }
  catch { throw new Error('Private CLI launch failed'); }
  return await new Promise((ok, fail) => {
    let bytes = 0, chunks = [], settled = false;
    const finish = (error, value) => {
      if (settled) return;
      settled = true; clearTimeout(timer); chunks = [];
      if (error) { child.kill('SIGKILL'); fail(new Error(error)); } else ok(value);
    };
    const timer = setTimeout(() => finish('Private CLI deadline exceeded'), timeoutMs);
    const collect = (data, stdout) => {
      if (settled) return;
      bytes += Buffer.byteLength(data);
      if (bytes > 2 * 1024 * 1024) return finish('Private CLI output limit exceeded');
      if (stdout) chunks.push(Buffer.from(data));
    };
    child.stdout.on('data', data => collect(data, true));
    child.stderr.on('data', data => collect(data, false));
    child.once('error', () => finish('Private CLI launch failed'));
    child.once('close', (code, signal) => {
      if (settled) return;
      if (code !== 0 || signal) return finish('Private CLI read failed');
      try {
        const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)));
        assert.ok(value && typeof value === 'object' && !Array.isArray(value));
        finish(null, value);
      } catch { finish('Private CLI requires one complete JSON object'); }
    });
  });
}
export function validateNativeTarget(endpoint, target) {
  assert.ok(['http://127.0.0.1:19338', 'http://127.0.0.1:19338/'].includes(endpoint), 'Exact owned endpoint spelling required');
  assert.ok(['http://127.0.0.1:15274', 'http://127.0.0.1:15274/', 'http://127.0.0.1:15274/#/jobby'].includes(target), 'Exact owned renderer spelling required');
  const cdp = new URL(endpoint), page = new URL(target);
  assert.equal(cdp.href, 'http://127.0.0.1:19338/', 'Only the explicitly owned CDP endpoint is allowed');
  assert.equal(page.origin, 'http://127.0.0.1:15274', 'Only the explicitly owned renderer origin is allowed');
  return { endpoint: cdp.origin, page: page.href };
}

export function parseQualificationMode(flags) {
  flags = [...flags];
  const homes = flags.filter(flag => flag === '--live-home');
  assert.ok(homes.length <= 1, 'Duplicate live home option');
  let liveHome;
  if (homes.length) {
    const index = flags.indexOf('--live-home');
    liveHome = flags[index + 1];
    assertOwnedSpelling(liveHome);
    flags.splice(index, 2);
  }
  const live = flags.includes('--native-live');
  assert.equal(Boolean(liveHome), live, 'Native live requires an explicit owned live home');
  const native = flags.filter(flag => flag !== '--native-live');
  assert.equal(flags.length - native.length, live ? 1 : 0, 'Duplicate live option');
  if (!flags.length) return { mode: 'harness', target: null };
  assert.ok(native.length === 4 && native[0] === '--native-cdp' && native[2] === '--native-page', 'Expected explicit native CDP and renderer URL options');
  return { mode: live ? 'native-live' : 'native-cdp', target: validateNativeTarget(native[1], native[3]), ...(live ? { liveHome } : {}) };
}

export function assertNativeLiveSetup(value) {
  assert.equal(value.ok, true);
  assert.equal(value.confirmed, true, 'Live setup must already be confirmed');
  assert.equal(value.submission_available, false);
  assert.match(value.source_token || '', /^[a-f0-9]{64}$/);
  assert.deepEqual(value.queries, ['Python']);
  assert.deepEqual(value.preferences, { country: 'Canada', location: 'Toronto, ON, Canada', remote: false, hours_old: 720, per_query: 5, total: 5, order: 'newest' }, 'Only the approved live search bounds are allowed');
  assert.ok(value.proposals.some(proposal => proposal.term === 'Python' && proposal.evidence.some(evidence => evidence.fact_id && /Python-based Jobby CLI/.test(evidence.excerpt))), 'Expected the approved source-backed Python tool evidence');
}

export function assertNativePrivateStatus(status, setup) {
  try {
    assertNativeLiveSetup(setup);
    assert.equal(status.candidate_initialized, true, 'Owned workspace source required');
    assert.ok(Number.isSafeInteger(status.fact_count) && status.fact_count > 0);
    assert.deepEqual(status.settings?.discovery, { source_token: setup.source_token, queries: setup.queries, preferences: setup.preferences }, 'Private workspace must match the confirmed public source and search bounds');
  } catch { throw new Error('Private workspace source identity or confirmation mismatch'); }
}

// Keep the SDK response intact. Only this bounded audit summary crosses the
// private CLI boundary; raw job/source/event payloads never enter a receipt.
export function bindNativeDossier(first, shown, last, setup, status) {
  try {
    assertNativePrivateStatus(status, setup);
    assert.deepEqual(first, last, 'Public dossier changed during private readback');
    assert.equal(last.ok, true);
    assert.equal(last.submission_available, false);
    assert.ok(Number.isSafeInteger(last.job?.id) && last.job.id > 0);
    for (const [key, value] of Object.entries(last.job)) assert.deepEqual(shown.job?.[key], value, 'Public/private job mismatch');
    assert.equal(shown.job.id, last.job.id);
    assert.equal(shown.job.job_url, last.job.job_url);
    assert.ok(['discovered', 'needs_review', 'eligible', 'materials_ready'].includes(shown.job.status), 'Existing application state blocks qualification');
    assert.deepEqual(shown.job.attempts, [], 'Live selection must have no application attempts');
    assert.equal(shown.job.submitted_at ?? null, null);
    assert.deepEqual(shown.job.materials ?? null, shown.materials, 'CLI material snapshots disagree');
    const source = shown.job.original_source;
    const url = new URL(last.job.job_url);
    const sites = { 'ca.indeed.com': 'indeed', 'www.indeed.com': 'indeed', 'indeed.com': 'indeed', 'www.linkedin.com': 'linkedin', 'linkedin.com': 'linkedin' };
    assert.equal(url.protocol, 'https:');
    assert.equal(url.username + url.password + url.port, '');
    assert.ok(sites[url.hostname], 'Expected a real provider listing');
    assert.equal(source?.site, sites[url.hostname], 'Provider site evidence mismatch');
    assert.equal(source.job_url, last.job.job_url, 'Original provider URL mismatch');
    if (last.materials) {
      assert.equal(shown.materials?.qa_state, 'pending_visual_review', 'Current unapproved materials required');
      assert.equal(last.materials.qa_state, 'pending_visual_review');
      assert.deepEqual(last.materials.artifact_hashes, shown.materials.artifact_hashes, 'Exact public artifact hashes required');
      for (const [key, value] of Object.entries(last.materials)) assert.deepEqual(shown.materials[key], value, 'Public/private material mismatch');
      assert.match(last.materials.generation_id || '', /^[a-f0-9]{32}$/);
      assert.match(last.materials.review_token || '', /^[a-f0-9]{64}$/);
    } else {
      assert.equal(shown.materials, null);
      assert.equal(shown.current_artifact_directory, null);
    }
    assert.ok(Array.isArray(shown.events) && shown.events.length <= 10000, 'Bounded CLI events required');
    let previous = 0;
    const events = shown.events.map(event => {
      assert.ok(Number.isSafeInteger(event.id) && event.id > previous, 'Ordered unique event IDs required');
      previous = event.id;
      assert.equal(event.job_id, last.job.id, 'Cross-job audit evidence');
      const result = { id: event.id, kind: event.kind === 'discovery_observed' ? 'discovery_observed' : 'other' };
      if (event.kind === 'discovery_observed') {
        const data = JSON.parse(event.data);
        assert.equal(typeof data?.query, 'string');
        assert.ok(data.query.length <= 100);
        result.query = data.query;
      }
      return result;
    });
    return { public: last, audit: { job_id: last.job.id, job_url: last.job.job_url, site: source.site, attempt_count: 0, events } };
  } catch { throw new Error('Private CLI evidence did not match the public desk'); }
}

export async function verifyNativeArtifacts(liveHome, shown) {
  const meta = shown.materials;
  if (!meta) return;
  assert.equal(meta.qa_state, 'pending_visual_review');
  assert.match(meta.generation_id || '', /^[a-f0-9]{32}$/);
  assert.ok(Number.isSafeInteger(shown.job.id) && shown.job.id > 0);
  const folder = join(liveHome, 'plugin-data/jobby/workspace/artifacts', String(shown.job.id), 'generations', meta.generation_id);
  assert.equal(shown.current_artifact_directory, folder, 'Exact current immutable artifact directory required');
  await checkedOwnedPath(folder);
  const hashes = async (path, expected) => {
    assert.match(expected || '', /^[a-f0-9]{64}$/);
    await checkedOwnedPath(path);
    const info = await lstat(path);
    assert.ok(info.isFile() && info.size <= 16 * 1024 * 1024, 'Bounded regular evidence file required');
    assert.equal(createHash('sha256').update(await readFile(path)).digest('hex'), expected, 'Current evidence hash mismatch');
  };
  const sources = Object.entries(meta.source_hashes || {});
  assert.ok(sources.length > 0 && sources.length <= 8, 'Immutable source hashes required');
  for (const [path, expected] of sources) await hashes(path, expected);
  const names = ['resume.pdf', 'resume.docx', 'cover_letter.pdf', 'cover_letter.docx', 'preview.png', 'cover_preview.png', 'posting.json', 'evidence.json'];
  for (const name of names.slice(0, 6)) assert.ok(Object.hasOwn(meta.artifact_hashes, name), 'All current documents and previews required');
  for (const [name, expected] of Object.entries(meta.artifact_hashes)) {
    assert.ok(names.includes(name), 'Unexpected artifact filename');
    await hashes(join(folder, name), expected);
  }
}

export function assertNativeLiveRun(before, after, watermark, dossiers) {
  assertNativeLiveSetup(after);
  assert.equal(after.source_token, before.source_token, 'Source changed during live search');
  assert.ok(Number.isSafeInteger(watermark) && watermark >= 0);
  const run = after.last_run;
  assert.ok(run, 'Fresh search result required');
  assert.equal(run.outcome, 'completed');
  assert.deepEqual(run.errors, []);
  assert.equal(run.requested, 5);
  assert.ok(Number.isInteger(run.unique_jobs_observed) && run.unique_jobs_observed > 0 && run.unique_jobs_observed <= 5, 'Current observations required; retained shortlist is insufficient');
  assert.equal(run.queries.length, 1);
  assert.equal(run.queries[0].term, 'Python');
  assert.equal(run.queries[0].requested, 5);
  assert.ok(Number.isInteger(run.queries[0].stored) && run.queries[0].stored >= run.unique_jobs_observed && run.queries[0].stored <= 5);
  assert.ok(dossiers.length <= 100);
  assert.equal(new Set(dossiers.map(dossier => dossier.audit.job_id)).size, dossiers.length, 'Distinct bound dossiers required');
  const observed = dossiers.filter(dossier => dossier.audit.events.some(event => event.id > watermark && event.kind === 'discovery_observed' && event.query === 'Python'));
  assert.equal(observed.length, run.unique_jobs_observed, 'Fresh per-posting observations must account for the current run');
  const matches = observed.map(dossier => after.shortlist.find(item => item.id === dossier.audit.job_id));
  for (const [index, item] of matches.entries()) {
    assert.ok(item, 'Current observation missing from visible shortlist');
    assert.equal(observed[index].public.ok, true);
    assert.equal(observed[index].public.job.id, item.id);
    assert.equal(observed[index].audit.job_url, item.job_url, 'Observation must bind the exact public listing');
    assert.equal(observed[index].public.job.job_url, item.job_url);
    assert.equal(observed[index].audit.attempt_count, 0);
    const url = new URL(item.job_url);
    assert.equal(url.protocol, 'https:');
    assert.ok(['ca.indeed.com', 'www.indeed.com', 'indeed.com', 'www.linkedin.com', 'linkedin.com'].includes(url.hostname), 'Expected a real provider listing');
    assert.equal(url.username + url.password + url.port, '');
    assert.equal(observed[index].audit.site, url.hostname.includes('indeed') ? 'indeed' : 'linkedin', 'Actual provider site evidence required');
  }
  const grounded = matches.filter(item => item.matching_terms.includes('python') && item.evidence.some(evidence => evidence.matching_terms.includes('python') && before.proposals.some(proposal => proposal.term === 'Python' && proposal.evidence.some(source => source.fact_id === evidence.fact_id && source.excerpt === evidence.excerpt))));
  assert.ok(grounded.length, 'Current real results require exact source-backed Python overlap');
  return grounded;
}

export function nativeLiveDownloadOutcome(downloads) {
  assert.deepEqual(downloads.map(item => item.filename).sort(), ['cover_letter.docx', 'cover_letter.pdf', 'resume.docx', 'resume.pdf']);
  for (const item of downloads) {
    assert.equal(item.initiated_via_visible_control, true);
    assert.ok(Number.isSafeInteger(item.job_id) && item.job_id > 0);
    assert.match(item.generation_id || '', /^[a-f0-9]{32}$/);
    assert.match(item.expected_sha256 || '', /^[a-f0-9]{64}$/);
    assert.ok(['saved_hash_verified', 'native_dialog_pending', 'download_event_unavailable'].includes(item.outcome));
    assert.equal(item.os_save_verified, item.outcome === 'saved_hash_verified');
    if (item.os_save_verified) assert.equal(item.sha256, item.expected_sha256);
  }
  assert.equal(new Set(downloads.map(item => `${item.job_id}:${item.generation_id}`)).size, 1);
  return downloads.every(item => item.os_save_verified) ? 'desk_passed_pending_operator_review' : 'pending_native_saves';
}

// Same short, exclusive scratch-directory lifecycle as browser_role in the
// maintained synthetic runner. Evidence stays in output, Chrome sockets do not.
export async function withBrowserTemp(action) {
  const browserTemp = await mkdtemp('/home/adcan288/tmp/jobby-hackathon-20261107/worker/b-');
  const previousTemp = process.env.TMPDIR;
  try {
    process.env.TMPDIR = browserTemp;
    return await action(browserTemp);
  } finally {
    if (previousTemp === undefined) delete process.env.TMPDIR;
    else process.env.TMPDIR = previousTemp;
    await rm(browserTemp, { recursive: true, force: true });
  }
}

export async function stopFixture(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  await new Promise((ok, fail) => {
    const cleanup = () => { clearTimeout(term); clearTimeout(limit); child.off('close', done); child.off('error', error); };
    const done = () => { cleanup(); ok(); };
    const error = err => { cleanup(); fail(err); };
    const term = setTimeout(() => child.kill('SIGKILL'), 5000);
    const limit = setTimeout(() => { cleanup(); fail(new Error('Owned fixture child did not exit')); }, 10000);
    child.once('close', done); child.once('error', error); child.kill('SIGTERM');
  });
}

export function assertHarnessDownloads(downloads) {
  assert.deepEqual(downloads.map(item => item.filename).sort(), ['cover_letter.docx', 'cover_letter.pdf', 'resume.docx', 'resume.pdf'], 'Harness requires all four distinct downloads');
  assert.ok(downloads.every(item => item.outcome === 'saved_hash_verified' && /^[a-f0-9]{64}$/.test(item.sha256)), 'Harness requires four saved/hash-verified outcomes');
}

async function primaryJourney(page, output, readCurrent, receipt) {
  const desk = page.getByRole('main', { name: 'Jobby desk' });
  await desk.getByText('No saved postings yet.', { exact: false }).waitFor();
  receipt.empty_desk = true;
  await page.screenshot({ path: join(output, 'empty-wide.png'), fullPage: true });
  await desk.getByLabel('Absolute PDF path on the Hermes backend machine').fill(join(output, 'fictional-source.pdf'));
  await desk.getByRole('button', { name: 'Import source PDF', exact: true }).click();
  await desk.getByText('Source imported.', { exact: false }).waitFor();
  for (const [name, value] of [['Company', 'Fictional Example'], ['Job title', 'Python Engineer'], ['Posting URL', 'https://jobs.example.test/desk'], ['Location', 'Berlin'], ['Posting description', 'Build Python services']]) await desk.getByLabel(name, { exact: true }).fill(value);
  await desk.getByLabel('I selected this posting for local document preparation').check();
  await desk.getByRole('button', { name: 'Save selected posting', exact: true }).click();
  await desk.getByRole('button', { name: 'Prepare documents', exact: true }).click();
  await desk.getByAltText('Resume preview from current generated PDF').waitFor();
  await desk.getByAltText('Cover letter preview from current generated PDF').waitFor();
  await desk.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode())));
  const current = await readCurrent();
  assert.equal(current.materials.qa_state, 'pending_visual_review');
  assert.equal(current.next_action, 'review_exact_generation');
  assert.equal(current.submission_available, false);
  await writeFile(join(output, 'current-dossier.json'), JSON.stringify(current, null, 2));
  receipt.pending_visual_review = true;
  receipt.next_action = current.next_action;
  await page.screenshot({ path: join(output, 'documents-wide.png'), fullPage: true });
  receipt.downloads = [];
  // An actual download event/save is evidence; clicking alone never counts.
  for (const [index, prefix] of ['resume', 'cover_letter'].entries()) {
    const article = desk.locator('article').nth(index);
    for (const extension of ['pdf', 'docx']) {
      const event = page.waitForEvent('download', { timeout: 8000 }).catch(() => null);
      await article.getByRole('button', { name: `Download ${extension.toUpperCase()}`, exact: true }).click();
      const download = await event;
      if (!download) { receipt.downloads.push({ filename: `${prefix}.${extension}`, outcome: 'download_event_unavailable' }); continue; }
      const filename = `${prefix}.${extension}`;
      assert.equal(download.suggestedFilename(), filename);
      try { await download.saveAs(join(output, filename)); }
      catch (error) {
        if (receipt.mode === 'native-cdp' && /acceptDownloads|not supported/i.test(error.message)) {
          receipt.downloads.push({ filename, outcome: 'native_download_save_unavailable' }); continue;
        }
        throw error;
      }
      assert.equal(await download.failure(), null);
      const sha256 = createHash('sha256').update(await readFile(join(output, filename))).digest('hex');
      assert.equal(sha256, current.materials.artifact_hashes[filename]);
      receipt.downloads.push({ filename, outcome: 'saved_hash_verified', sha256 });
    }
  }
  assert.equal((await readCurrent()).materials.qa_state, 'pending_visual_review');
  receipt.primary_ui = true;
}

// Harness-only provider boundary. The UI, adapter, Store and generator remain
// real. Native mode cannot claim this journey without its own provider fixture.
export async function discoveryJourney(page, output, base, receipt) {
  const desk = page.getByRole('main', { name: 'Jobby desk' });
  const search = desk.getByRole('region', { name: 'Resume search and shortlist' });
  const choose = async (label, value) => {
    await search.getByRole('combobox', { name: label, exact: true }).click();
    await page.getByRole('option', { name: value, exact: true }).click();
  };
  assert.equal(await search.getByLabel('Search location in Canada', { exact: true }).inputValue(), '');
  assert.equal(await search.getByRole('button', { name: 'Search approved terms', exact: true }).isDisabled(), true);
  await choose('Search country', 'Canada only');
  await search.getByLabel('Search location in Canada', { exact: true }).fill('Ottawa, ON');
  await choose('Remote preference', 'Remote only');
  for (const [label, value] of [['Freshness in hours', '72'], ['Results per query', '2'], ['Total results per run', '4']]) await search.getByLabel(label, { exact: true }).fill(value);
  await choose('Shortlist order', 'Lexical coverage');
  await search.getByLabel('I confirm these search preferences and source-backed query terms', { exact: true }).check();
  await search.getByRole('button', { name: 'Confirm search setup', exact: true }).click();
  await search.getByText('Search setup confirmed for this imported source.', { exact: true }).waitFor();
  await search.getByRole('button', { name: 'Search approved terms', exact: true }).click();
  await search.getByText('Last search: completed', { exact: false }).waitFor();
  const found = await (await page.request.get(base + '/api/plugins/jobby/discovery')).json();
  assert.equal(found.confirmed, true);
  assert.equal(found.shortlist.length, 2);
  assert.ok(found.shortlist[0].matching_terms.includes('python'));
  assert.deepEqual(found.shortlist[1].matching_terms, []);
  assert.equal(found.shortlist[1].posted_date, null);
  await search.getByRole('button', { name: 'Discovery Python Engineer · Fictional Discovery', exact: true }).click();
  const dossier = desk.getByRole('region', { name: 'Document dossier' });
  await dossier.getByRole('button', { name: 'Prepare documents', exact: true }).click();
  await dossier.getByAltText('Resume preview from current generated PDF').waitFor();
  await dossier.getByAltText('Cover letter preview from current generated PDF').waitFor();
  await dossier.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode())));
  const draft = await (await page.request.get(base + '/api/plugins/jobby/desk/' + found.shortlist[0].id)).json();
  assert.equal(draft.materials.qa_state, 'pending_visual_review');
  assert.equal(draft.submission_available, false);
  await writeFile(join(output, 'discovery-dossier.json'), JSON.stringify(draft, null, 2));
  await page.reload();
  await search.getByRole('button', { name: 'Discovery Python Engineer · Fictional Discovery', exact: true }).waitFor();
  await search.getByRole('button', { name: 'Registered Nurse · Fictional Hospital', exact: true }).waitFor();
  await search.getByText('Search setup confirmed for this imported source.', { exact: true }).waitFor();
  const viewport = page.viewportSize();
  const captures = [];
  try {
    for (const width of [1280, 600, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `Discovery shortlist overflows at ${width}px`);
      const filename = `discovery-shortlist-${width}.png`;
      await page.screenshot({ path: join(output, filename), fullPage: true });
      captures.push({ width, height: 1000, filename, no_horizontal_overflow: true });
    }
  } finally {
    await page.setViewportSize(viewport);
  }
  receipt.discovery_journey = { scope: 'Browser SDK harness only', persistent_shortlist: true, hard_negative: true, prepared_generation: draft.materials.generation_id, qa_state: draft.materials.qa_state, captures };
}

const discoveryOperations = ['inspect', 'confirm', 'search'];
const discoveryTransitions = [
  ['switchDeskProfile', 'b', false],
  ['switchDeskProfile', 'b', true],
  ['switchDeskConnection', 'other-harness', false],
  ['switchDeskOwner', 'other-focused-harness', false],
  ['switchDeskConnection', 'harness', false],
];
const discoveryRetirementKey = (operation, switcher, target, batched) => `discovery_${operation}_${switcher}_${target}_${batched ? 'batched' : 'roundtrip'}`;

export function recordDiscoveryRetirement(receipt, operation, switcher, target, batched = false) {
  const key = discoveryRetirementKey(operation, switcher, target, batched);
  assert.ok(!Object.hasOwn(receipt, key), `Duplicate discovery retirement: ${key}`);
  return receipt[key] = { operation, switcher, target, batched, passed: false };
}

export function assertHarnessDiscoveryRetirements(receipt) {
  const expected = [];
  for (const operation of discoveryOperations) {
    for (const [switcher, target, batched] of discoveryTransitions) {
      const key = discoveryRetirementKey(operation, switcher, target, batched);
      expected.push(key);
      const observed = receipt[key];
      assert.ok(observed, `Missing discovery retirement: ${key}`);
      assert.deepEqual([observed.operation, observed.switcher, observed.target, observed.batched], [operation, switcher, target, batched], `Mismatched discovery retirement: ${key}`);
      assert.equal(observed.passed, true, `Incomplete discovery retirement: ${key}`);
      assert.equal(observed.real_response_held, true, `Missing real discovery response: ${key}`);
      assert.deepEqual(observed.query_updates_after_release, [], `Retired discovery query updated: ${key}`);
      assert.equal(observed.mutation_outcome, operation === 'inspect' ? null : 'error', `Unexpected discovery outcome: ${key}`);
    }
  }
  const actual = Object.keys(receipt).filter(key => key.startsWith('discovery_') && key !== 'discovery_journey');
  assert.deepEqual(actual.sort(), expected.sort(), 'Harness requires the complete distinct discovery retirement matrix');
}

export async function delayedDiscoveryResponse(page, receipt, operation, switcher, other, batched = false) {
  const desk = page.getByRole('main', { name: 'Jobby desk' });
  const search = desk.getByRole('region', { name: 'Resume search and shortlist' });
  const observed = recordDiscoveryRetirement(receipt, operation, switcher, other, batched);
  let release, ready, rejectReady, timer, captured = false;
  const held = new Promise(ok => { release = ok; });
  const inFlight = new Promise((ok, fail) => { ready = ok; rejectReady = fail; timer = setTimeout(() => fail(new Error('Discovery response did not reach delay gate')), 20000); });
  const pattern = '**/api/plugins/jobby/discovery';
  const intercept = async route => {
    const request = route.request();
    const kind = request.method() === 'GET' ? 'inspect' : request.postDataJSON()?.operation;
    if (captured || kind !== operation) return route.fallback();
    captured = true;
    try {
      const response = await route.fetch();
      assert.equal((await response.json()).ok, true);
      observed.real_response_held = true;
      clearTimeout(timer); ready();
      await held;
      await route.fulfill({ response });
    } catch (error) { clearTimeout(timer); rejectReady(error); throw error; }
  };
  await page.evaluate(() => {
    window.harnessDelayedDiscovery = { terminal: null, updates: [], released: false, count: 0 };
    window.harnessDelayedDiscovery.stopMutations = window.harnessQueryClient.getMutationCache().subscribe(event => {
      if (event.type === 'updated' && event.mutation.state.variables?.path === '/discovery' && ['success', 'error'].includes(event.mutation.state.status)) window.harnessDelayedDiscovery.terminal = event.mutation.state.status;
    });
    window.harnessDelayedDiscovery.stopQueries = window.harnessQueryClient.getQueryCache().subscribe(event => {
      if (window.harnessDelayedDiscovery.released && event.type === 'updated' && event.action.type === 'success') window.harnessDelayedDiscovery.updates.push(event.query.queryKey);
    });
  });
  await page.route(pattern, intercept);
  try {
    if (operation === 'inspect') await desk.getByRole('button', { name: 'Refresh', exact: true }).click();
    else if (operation === 'search') await search.getByRole('button', { name: 'Search approved terms', exact: true }).click();
    else {
      await search.getByLabel('I confirm these search preferences and source-backed query terms', { exact: true }).check();
      await search.getByRole('button', { name: 'Confirm search setup', exact: true }).click();
    }
    await inFlight;
    const original = switcher === 'switchDeskProfile' ? 'a' : 'harness';
    if (batched) await page.evaluate(({ switcher, other, original }) => { window[switcher](other); window[switcher](original); }, { switcher, other, original });
    else {
      await page.evaluate(({ switcher, other }) => window[switcher](other), { switcher, other });
      await desk.getByRole('heading', { name: 'Your document dossier', exact: true }).waitFor();
      if (switcher === 'switchDeskProfile') {
        await search.getByText('No discovered postings yet.', { exact: false }).waitFor();
        assert.equal(await search.getByText('Discovery Python Engineer', { exact: false }).count(), 0);
        assert.equal(await search.getByLabel('Search location in Canada', { exact: true }).inputValue(), '');
      }
      await page.evaluate(({ switcher, original }) => window[switcher](original), { switcher, original });
    }
    await search.getByRole('button', { name: 'Discovery Python Engineer · Fictional Discovery', exact: true }).waitFor();
    await page.waitForFunction(() => window.harnessQueryClient.isFetching() === 0);
    const before = await desk.innerText();
    await page.evaluate(() => { window.harnessDelayedDiscovery.count = window.harnessDiscoveryResponses; window.harnessDelayedDiscovery.released = true; });
    release();
    if (operation === 'inspect') await page.waitForFunction(() => window.harnessDiscoveryResponses > window.harnessDelayedDiscovery.count);
    else await page.waitForFunction(() => window.harnessDelayedDiscovery.terminal !== null);
    await page.evaluate(() => new Promise(ok => requestAnimationFrame(() => requestAnimationFrame(ok))));
    observed.query_updates_after_release = await page.evaluate(() => window.harnessDelayedDiscovery.updates);
    observed.mutation_outcome = await page.evaluate(() => window.harnessDelayedDiscovery.terminal);
    assert.deepEqual(observed.query_updates_after_release, []);
    if (operation !== 'inspect') assert.equal(observed.mutation_outcome, 'error');
    assert.equal(await desk.innerText(), before);
    assert.equal(await desk.getByRole('heading', { name: 'Your document dossier', exact: true }).count(), 1);
    observed.passed = true;
  } finally {
    clearTimeout(timer); release();
    await page.unroute(pattern, intercept);
    await page.evaluate(() => { window.harnessDelayedDiscovery.stopMutations(); window.harnessDelayedDiscovery.stopQueries(); });
  }
}

// Harness-only vertical tracer: retire a real Documents view while its actual
// artifact response is held. No substitute artifact, transport or persistence.
export async function delayedSelectedJobDownload(page, receipt, options = {}) {
  const { key = 'delayed_selected_job_download', retire, filename = 'resume.pdf', query = false } = options;
  const desk = page.getByRole('main', { name: 'Jobby desk' });
  const dossier = desk.getByRole('region', { name: 'Document dossier' });
  const savedA = desk.getByRole('button', { name: 'Python Engineer · Fictional Example', exact: true });
  const nameB = 'Systems Engineer · Fictional Second Example';
  if (!retire) {
    for (const [name, value] of [['Company', 'Fictional Second Example'], ['Job title', 'Systems Engineer'], ['Posting URL', 'https://jobs.example.test/desk-second'], ['Location', 'Berlin'], ['Posting description', 'Build fictional Python systems']]) await desk.getByLabel(name, { exact: true }).fill(value);
    await desk.getByLabel('I selected this posting for local document preparation').check();
    await desk.getByRole('button', { name: 'Save selected posting', exact: true }).click();
    await dossier.getByRole('heading', { name: nameB, exact: true }).waitFor();
  }
  const savedB = desk.getByRole('button', { name: nameB, exact: true });
  await savedA.click();
  await dossier.getByAltText('Resume preview from current generated PDF').waitFor();

  const observed = receipt[key] = { response_in_flight: false, selected_b_before_release: false, download_events: [], download_starts: [], completion_notices: [] };
  let release, ready, rejectReady, timer, captured = false;
  const held = new Promise(ok => { release = ok; });
  const inFlight = new Promise((ok, fail) => { ready = ok; rejectReady = fail; timer = setTimeout(() => fail(new Error('Real resume.pdf response did not reach the delay gate')), 20000); });
  const onDownload = download => observed.download_events.push(download.suggestedFilename());
  const pattern = '**/api/plugins/jobby/artifact';
  const intercept = async route => {
    const body = route.request().postDataJSON();
    if (captured || body?.filename !== filename || body.job_id !== 1) return route.fallback();
    captured = true;
    try {
      const response = await route.fetch();
      assert.equal(response.status(), 200);
      const actual = await response.json();
      assert.equal(actual.ok, true);
      assert.equal(actual.filename, filename);
      assert.ok(actual.base64, 'Delay must hold the real generated artifact');
      observed.generation_id = actual.generation_id;
      observed.response_in_flight = true;
      clearTimeout(timer); ready();
      await held;
      await route.fulfill({ response });
    } catch (error) { clearTimeout(timer); rejectReady(error); throw error; }
  };
  page.on('download', onDownload);
  await page.evaluate(() => {
    const original = HTMLAnchorElement.prototype.click;
    window.harnessDelayedDownload = { starts: [], terminal: null, queryUpdates: [], released: false, responseCount: window.harnessArtifactResponses.length, restore: () => { HTMLAnchorElement.prototype.click = original; } };
    HTMLAnchorElement.prototype.click = function () {
      if (this.download) window.harnessDelayedDownload.starts.push(this.download);
      return original.call(this);
    };
    window.harnessDelayedDownload.unsubscribe = window.harnessQueryClient.getMutationCache().subscribe(event => {
      if (event.type === 'updated' && event.mutation.state.variables === 'resume.pdf' && ['success', 'error'].includes(event.mutation.state.status)) window.harnessDelayedDownload.terminal = event.mutation.state.status;
    });
    window.harnessDelayedDownload.unsubscribeQueries = window.harnessQueryClient.getQueryCache().subscribe(event => {
      if (window.harnessDelayedDownload.released && event.type === 'updated' && event.action.type === 'success') window.harnessDelayedDownload.queryUpdates.push(event.query.queryKey);
    });
  });
  await page.route(pattern, intercept);
  try {
    if (query) await desk.getByRole('button', { name: 'Refresh', exact: true }).click();
    else await dossier.locator('article').first().getByRole('button', { name: 'Download PDF', exact: true }).click();
    await inFlight;
    if (retire) await retire({ desk, dossier, savedA, savedB, observed });
    else {
      await savedB.click();
      await dossier.getByRole('heading', { name: nameB, exact: true }).waitFor();
      assert.equal(await savedB.getAttribute('aria-pressed'), 'true');
      assert.equal(await dossier.getByAltText('Resume preview from current generated PDF').count(), 0);
      observed.selected_b_before_release = true;
    }
    await page.waitForFunction(() => window.harnessQueryClient.isFetching() === 0);
    const before = await dossier.innerText();
    await page.evaluate(() => { window.harnessDelayedDownload.responseCount = window.harnessArtifactResponses.length; window.harnessDelayedDownload.released = true; });
    release();
    // Mutation success/error is dispatched AFTER the hook-level callbacks.
    // Then yield actual rendering tasks before observing notices/downloads.
    if (query) await page.waitForFunction(({ filename, generation }) => window.harnessArtifactResponses.slice(window.harnessDelayedDownload.responseCount).some(value => value.filename === filename && value.generation_id === generation), { filename, generation: observed.generation_id });
    else await page.waitForFunction(() => window.harnessDelayedDownload.terminal !== null);
    await page.evaluate(() => new Promise(ok => requestAnimationFrame(() => requestAnimationFrame(ok))));
    observed.download_starts = await page.evaluate(() => window.harnessDelayedDownload.starts);
    observed.mutation_outcome = await page.evaluate(() => window.harnessDelayedDownload.terminal);
    observed.query_updates_after_release = await page.evaluate(() => window.harnessDelayedDownload.queryUpdates);
    observed.completion_notices = await desk.getByText('resume.pdf opened for download.', { exact: false }).allTextContents();
    assert.deepEqual(observed.download_starts, [], 'Retired job A initiated a download after selecting job B');
    assert.deepEqual(observed.download_events, [], 'Retired job A emitted a browser download after selecting job B');
    assert.deepEqual(observed.completion_notices, [], 'Retired job A displayed an old download completion notice');
    assert.deepEqual(observed.query_updates_after_release, [], 'Retired response updated a query after release');
    assert.equal(await dossier.innerText(), before, 'Retired response changed the current dossier');
    observed.passed = true;
  } finally {
    clearTimeout(timer); release();
    await page.unroute(pattern, intercept);
    page.off('download', onDownload);
    await page.evaluate(() => { window.harnessDelayedDownload.unsubscribe(); window.harnessDelayedDownload.unsubscribeQueries(); window.harnessDelayedDownload.restore(); });
  }
  // Preserve the original viewport/profile journey's selected job A.
  await savedA.click();
  await dossier.getByAltText('Resume preview from current generated PDF').waitFor();
}

// One temporary lifetime for the pinned SDK owner. Retain each action's element
// so a late locator cannot select a replacement document/button. The event gate
// runs synchronously during trusted input, not in an awaited preflight.
export async function withNativeActions(page, action) {
  let key, owner;
  const acquire = async (previous, retiredKey) => {
  const nextKey = '__jobbyNativeAction_' + randomUUID();
  const nextOwner = await page.evaluate(({ key, previous, retiredKey }) => {
    if (retiredKey && Object.hasOwn(window, retiredKey)) throw new Error('Owned reload requires a fresh document');
    const sdk = window.__HERMES_PLUGIN_SDK__;
    if (!sdk?.host || !window.hermesDesktop?.api) throw new Error('Native SDK/IPC unavailable');
    const doc = document;
    const snapshot = () => ({ profile: sdk.host.state.profile.get(), connectionId: sdk.host.state.connectionId.get(), focused: sdk.host.state.focusedSessionProfile.get(), focusedOwner: sdk.host.state.focusedSessionOwner.get(), epoch: sdk.gatewayActivationEpoch() });
    const owner = snapshot(), identity = JSON.stringify(owner);
    if (previous) {
      const { epoch: oldEpoch, ...before } = previous;
      const { epoch: newEpoch, ...after } = owner;
      if (JSON.stringify(before) !== JSON.stringify(after)) throw new Error('Owned native scope changed across reload');
    }
    let retired = false, element = null, activeEvent = null, clicked = false;
    const events = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
    const cancel = event => { event.preventDefault(); event.stopImmediatePropagation(); };
    const retire = () => { retired = true; if (activeEvent) cancel(activeEvent); };
    const check = (targetRequired = true) => {
      if (retired || document !== doc || window.__HERMES_PLUGIN_SDK__ !== sdk || JSON.stringify(snapshot()) !== identity || (targetRequired && element && (!element.isConnected || element.ownerDocument !== doc))) {
        retire();
        throw new Error('Owned native scope retired or action target replaced');
      }
    };
    const gate = event => {
      if (!event.isTrusted) return; // The app owns its asynchronous download link.
      activeEvent = event;
      try {
        check();
        if (!event.composedPath().includes(element)) throw new Error('Action target replaced');
        if (event.type === 'click') clicked = true;
      } catch { retire(); cancel(event); }
    };
    const disarm = () => {
      for (const type of events) {
        window.removeEventListener(type, gate, true);
        element?.removeEventListener(type, gate, true);
      }
      element = null; activeEvent = null; clicked = false;
    };
    const stops = [];
    try {
      for (const store of [sdk.host.state.profile, sdk.host.state.connectionId, sdk.host.state.focusedSessionProfile, sdk.host.state.focusedSessionOwner]) {
        stops.push(store.listen(() => { if (JSON.stringify(snapshot()) !== identity) retire(); }));
      }
      window.addEventListener('pagehide', retire, true);
      if (Object.hasOwn(window, key)) throw new Error('Native action guard collision');
      window[key] = {
        check,
        arm(node) {
          check(); element = node; clicked = false; check();
          for (const type of events) {
            window.addEventListener(type, gate, { capture: true, passive: false });
            node.addEventListener(type, gate, { capture: true, passive: false });
          }
        },
        finish() { check(false); if (!clicked) throw new Error('Native action requires trusted dispatch'); },
        reload() { check(); window.location.reload(); },
        disarm,
        dispose() { retire(); disarm(); stops.forEach(stop => stop()); window.removeEventListener('pagehide', retire, true); }
      };
      return owner;
    } catch (error) {
      disarm(); stops.forEach(stop => stop()); window.removeEventListener('pagehide', retire, true);
      throw error;
    }
  }, { key: nextKey, previous, retiredKey });
  key = nextKey; owner = nextOwner;
  };
  await acquire();
  const click = async locator => {
    const element = await locator.elementHandle();
    assert.ok(element, 'Native action target unavailable');
    try {
      await element.evaluate((node, key) => {
        const guard = window[key];
        if (!guard) throw new Error('Owned native document retired');
        guard.arm(node);
      }, key);
      await element.click();
      await element.evaluate((_node, key) => {
        const guard = window[key];
        if (!guard) throw new Error('Owned native document retired');
        guard.finish();
      }, key);
    } finally {
      await page.evaluate(key => window[key]?.disarm(), key).catch(() => {});
      await element.dispose();
    }
  };
  const read = suffix => page.evaluate(async ({ suffix, owner, key }) => {
      const guard = window[key];
      if (!guard) throw new Error('Owned native document retired');
      guard.check(false);
      const sdk = window.__HERMES_PLUGIN_SDK__;
      const current = { profile: sdk.host.state.profile.get(), connectionId: sdk.host.state.connectionId.get(), focused: sdk.host.state.focusedSessionProfile.get(), focusedOwner: sdk.host.state.focusedSessionOwner.get(), epoch: sdk.gatewayActivationEpoch() };
      if (JSON.stringify(current) !== JSON.stringify(owner)) throw new Error('Owned native scope changed');
      if (!/^\/(desk(?:\/[1-9][0-9]*)?|discovery)$/.test(suffix)) throw new Error('Read outside live desk boundary');
      const result = await window.hermesDesktop.api({ path: '/api/plugins/jobby' + suffix, method: 'GET', profile: owner.profile, connectionId: owner.connectionId });
      guard.check(false);
      if (!result.ok) throw new Error('Native plugin read unavailable');
      return result;
    }, { suffix, owner, key });
  const reload = async ({ reacquire = false, ready = async () => {} } = {}) => {
  const priorUrl = page.url();
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
    page.evaluate(key => {
      const guard = window[key];
      if (!guard) throw new Error('Owned native document retired');
      guard.reload();
    }, key)
  ]);
  if (reacquire) {
    assert.equal(page.url(), priorUrl, 'Owned reload changed renderer URL');
    await page.waitForFunction(() => Boolean(window.__HERMES_PLUGIN_SDK__?.host && window.hermesDesktop?.api), null, { timeout: 20000 });
    // The native view mounts after SDK bootstrap/activation. No read or action
    // may run in this gap; acquire a new guard only at the explicit boundary.
    await ready();
    assert.equal(page.url(), priorUrl, 'Owned reload changed renderer URL');
    await acquire(owner, key);
  }
  };
  const check = () => page.evaluate(key => {
    const guard = window[key];
    if (!guard) throw new Error('Owned native document retired');
    guard.check(false);
  }, key);
  try { return await action({ owner, click, reload, read, check }); }
  finally {
    // A replaced document has already discarded this exact guard and listeners.
    await page.evaluate(key => { if (Object.hasOwn(window, key)) { window[key].dispose(); delete window[key]; } }, key).catch(() => {});
  }
}

// Verify only observed save bytes; never source these from backend artifacts.
async function verifyNativeSavedFile(output, filename, expected) {
  assert.ok(['resume.pdf', 'resume.docx', 'cover_letter.pdf', 'cover_letter.docx'].includes(filename), 'Exact native save filename required');
  assert.match(expected || '', /^[a-f0-9]{64}$/);
  await checkedOwnedPath(output, '/home/adcan288/tmp/jobby-hackathon-20261107/worker');
  assert.ok((await lstat(output)).isDirectory(), 'Native save directory required');
  const path = join(output, filename);
  let info;
  try { info = await lstat(path); } catch (error) { if (error.code === 'ENOENT') return null; throw error; }
  assert.ok(!info.isSymbolicLink() && info.isFile() && info.nlink === 1 && info.size <= 16 * 1024 * 1024, 'Bounded regular native save required; no symlink or hardlink');
  assert.equal(info.uid, process.getuid(), 'Owned native save required');
  const file = await open(path, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW | fsConstants.O_NONBLOCK);
  try {
    const opened = await file.stat();
    assert.ok(opened.isFile() && opened.uid === process.getuid() && opened.ino === info.ino && opened.dev === info.dev && opened.size === info.size, 'Native save changed during open');
    const bytes = Buffer.alloc(info.size + 1);
    let count = 0, part;
    do { part = await file.read(bytes, count, bytes.length - count, count); count += part.bytesRead; } while (part.bytesRead && count < bytes.length);
    assert.equal(count, info.size, 'Native save size changed');
    const sha256 = createHash('sha256').update(bytes.subarray(0, count)).digest('hex');
    const final = await lstat(path), stillOpen = await file.stat();
    assert.ok(!final.isSymbolicLink() && final.ino === info.ino && final.dev === info.dev && final.uid === info.uid && final.nlink === 1 && stillOpen.size === info.size && stillOpen.mtimeMs === opened.mtimeMs && stillOpen.ctimeMs === opened.ctimeMs, 'Native save changed during verification');
    assert.equal(sha256, expected, 'Native saved file hash mismatch');
    return sha256;
  } finally { await file.close(); }
}

export async function saveNativeDownload({ page, output, item, check = async () => {}, timeoutMs = 120000 }, activate) {
  const { filename, expected_sha256: expected } = item;
  assert.ok(Number.isInteger(timeoutMs) && timeoutMs > 0 && timeoutMs <= 120000, 'Bounded native save deadline required');
  // This also validates directory ancestors and filename before any UI action.
  assert.equal(await verifyNativeSavedFile(output, filename, expected), null, 'Native save file must not preexist');
  const directory = await lstat(output), path = join(output, filename);
  const deadline = Date.now() + timeoutMs;
  await check();
  const event = page.waitForEvent('download', { timeout: Math.min(8000, timeoutMs) }).catch(() => null);
  await activate();
  item.initiated_via_visible_control = true;
  const download = await event;
  await check();
  if (Date.now() >= deadline) return false;
  if (download) {
    item.outcome = 'native_dialog_pending';
    assert.equal(download.suggestedFilename(), filename);
    let timer;
    try {
      await Promise.race([
        (async () => { await download.saveAs(path); assert.equal(await download.failure(), null); })(),
        new Promise((_, fail) => { timer = setTimeout(() => fail(new Error('Native save deadline; parent OS dialog may be pending')), Math.max(1, Math.min(8000, deadline - Date.now()))); })
      ]);
    } catch (error) {
      if (!/acceptDownloads|not supported|Native save deadline/i.test(error.message)) { item.outcome = 'save_failed'; throw error; }
      item.save_limitation = error.message;
    } finally { clearTimeout(timer); }
  }
  do {
    await check();
    if (Date.now() >= deadline) return false;
    await checkedOwnedPath(output, '/home/adcan288/tmp/jobby-hackathon-20261107/worker');
    const current = await lstat(output);
    assert.ok(current.ino === directory.ino && current.dev === directory.dev, 'Native save directory changed');
    const sha256 = await verifyNativeSavedFile(output, filename, expected);
    await check();
    if (Date.now() >= deadline) return false;
    if (sha256) {
      item.sha256 = sha256; item.outcome = 'saved_hash_verified'; item.os_save_verified = true;
      return true;
    }
    const remaining = deadline - Date.now();
    if (remaining <= 0) return false;
    await new Promise(done => setTimeout(done, Math.min(250, remaining)));
  } while (true);
}

async function nativeLiveJourney(playwright, target, output, receipt, privateInput) {
  receipt.qualification_outcome = 'incomplete';
  receipt.unexecuted = ['operator PDF/DOCX visual approval', 'employer forms and submission', 'OS save dialogs unless saved_hash_verified'];
  const checkpoint = async stage => {
    receipt.stage = stage;
    await writeFile(join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  };
  await checkpoint('connecting_owned_native');
  let connection;
  try {
    connection = await playwright.chromium.connectOverCDP(target.endpoint, { timeout: 10000, artifactsDir: output, downloadsPath: output, noDefaults: true });
    const matches = connection.contexts().flatMap(context => context.pages()).filter(page => page.url() === target.page);
    assert.equal(matches.length, 1, 'Expected exactly one page at the supplied owned renderer URL');
    const page = matches[0]; page.setDefaultTimeout(20000);
    // Read only through the genuine profile-scoped IPC door used by ctx.rest.
    // Pin its owner before any UI action; a host transition fails closed.
    await withNativeActions(page, async ({ read, click, reload, check }) => {
    const readDossier = async (id, setup) => {
      try {
        assert.ok(Number.isSafeInteger(id) && id > 0 && id <= 999999999999);
        const first = await read('/desk/' + id);
        const status = await readNativePrivate({ ...privateInput, operation: 'status' });
        assertNativePrivateStatus(status, setup);
        const shown = await readNativePrivate({ ...privateInput, operation: 'show', jobId: id });
        const last = await read('/desk/' + id);
        const currentSetup = await read('/discovery');
        assertNativeLiveSetup(currentSetup);
        assert.equal(currentSetup.source_token, setup.source_token, 'Source changed during audit readback');
        const bound = bindNativeDossier(first, shown, last, currentSetup, status);
        assert.equal(bound.audit.job_id, id, 'Private readback must match the requested job');
        await verifyNativeArtifacts(privateInput.liveHome, shown);
        return bound;
      } catch { throw new Error('Native public/private readback or current artifact validation failed; private values withheld'); }
    };
    const desk = page.getByRole('main', { name: 'Jobby desk' });
    const search = desk.getByRole('region', { name: 'Resume search and shortlist' });
    const dossier = desk.getByRole('region', { name: 'Document dossier' });
    const errors = []; const onError = error => errors.push(error.message); page.on('pageerror', onError);
    try {
      if (!await desk.count()) await click(page.getByRole('button', { name: 'Jobby desk', exact: true }));
      await desk.waitFor();
      await desk.getByText('Source imported.', { exact: false }).waitFor();
      await search.getByText('Search setup confirmed for this imported source.', { exact: true }).waitFor();
      receipt.native_mount = true;
      const before = await read('/discovery');
      assertNativeLiveSetup(before);
      const overview = await read('/desk');
      assert.equal(overview.source_status, 'imported');
      assert.equal(overview.submission_available, false);
      assert.ok(overview.jobs.length <= 100, 'Bounded isolated live workspace required');
      assertNativePrivateStatus(await readNativePrivate({ ...privateInput, operation: 'status' }), before);
      // Full pre-search event watermark, including postings already prepared.
      const prior = [];
      for (const job of overview.jobs) prior.push(await readDossier(job.id, before));
      const watermark = prior.reduce((max, item) => item.audit.events.reduce((value, event) => Math.max(value, event.id), max), 0);
      receipt.search_before = { source_token: before.source_token, preferences: before.preferences, queries: before.queries, last_run: before.last_run, event_watermark: watermark };
      await writeFile(join(output, 'live-discovery-before.json'), JSON.stringify(before, null, 2));
      for (const [label, value] of [['Search location in Canada', 'Toronto, ON, Canada'], ['Freshness in hours', '720'], ['Results per query', '5'], ['Total results per run', '5']]) assert.equal(await search.getByLabel(label, { exact: true }).inputValue(), value);
      for (const [label, value] of [['Search country', 'Canada only'], ['Remote preference', 'Include all arrangements'], ['Shortlist order', 'Newest source posting first']]) assert.equal(await search.getByRole('combobox', { name: label, exact: true }).innerText(), value);
      for (const evidence of before.proposals.find(proposal => proposal.term === 'Python').evidence) await search.getByText(`${evidence.fact_id}${evidence.role ? ` · ${evidence.role}` : ''}: ${evidence.excerpt}`, { exact: true }).first().waitFor();
      await page.screenshot({ path: join(output, 'live-confirmed-search.png'), fullPage: true });
      await checkpoint('confirmed_source_and_bounds');
      // Observe DOM progress only. No transport interception or response adapters.
      await page.evaluate(() => {
        const root = document.querySelector('main[aria-label="Jobby desk"]');
        const state = window.jobbyLiveSearchProgress = { busy: false, done: false };
        const observe = () => {
          const busy = root.textContent.includes('Working on your requested operation…');
          if (busy) state.busy = true;
          if (state.busy && !busy) { state.done = true; observer.disconnect(); }
        };
        const observer = new MutationObserver(observe);
        window.jobbyLiveSearchObserver = observer;
        observer.observe(root, { childList: true, subtree: true, characterData: true });
      });
      receipt.search_started_at = new Date().toISOString();
      try {
        await click(search.getByRole('button', { name: 'Search approved terms', exact: true }));
        await checkpoint('live_search_requested');
        await page.waitForFunction(() => window.jobbyLiveSearchProgress?.done, null, { timeout: 150000 });
      }
      finally { await page.evaluate(() => { window.jobbyLiveSearchObserver?.disconnect(); delete window.jobbyLiveSearchObserver; }); }
      receipt.search_finished_at = new Date().toISOString();
      const after = await read('/discovery');
      await writeFile(join(output, 'live-discovery-after.json'), JSON.stringify(after, null, 2));
      receipt.last_run = after.last_run;
      const current = [];
      assert.ok(after.shortlist.length <= 100);
      for (const item of after.shortlist) current.push(await readDossier(item.id, after));
      receipt.current_observations = current.flatMap(({ audit }) => audit.events.filter(event => event.id > watermark && event.kind === 'discovery_observed' && event.query === 'Python').map(event => ({ job_id: audit.job_id, event_id: event.id, query: event.query, site: audit.site, job_url: audit.job_url })));
      await checkpoint('live_search_returned');
      const grounded = assertNativeLiveRun(before, after, watermark, current);
      receipt.source_backed_matches = grounded;
      await search.getByText('Last search: completed', { exact: false }).waitFor();
      for (const item of grounded) {
        const card = search.getByRole('button', { name: `${item.title} · ${item.company}`, exact: true }).locator('..');
        await card.getByRole('link', { name: 'Source listing', exact: true }).waitFor();
        assert.equal(await card.getByRole('link', { name: 'Source listing', exact: true }).getAttribute('href'), item.job_url);
        await card.getByText(`Matching terms: ${item.matching_terms.join(', ')}`, { exact: true }).waitFor();
      }
      await page.screenshot({ path: join(output, 'live-current-shortlist.png'), fullPage: true });
      await checkpoint('fresh_live_observations_verified');
      const selected = grounded[0];
      await click(search.getByRole('button', { name: `${selected.title} · ${selected.company}`, exact: true }));
      await dossier.getByRole('heading', { name: `${selected.title} · ${selected.company}`, exact: true }).waitFor();
      const initialBound = await readDossier(selected.id, after);
      const initial = initialBound.public;
      assert.equal(initialBound.audit.attempt_count, 0, 'Live selection must have no application attempts');
      const initialGeneration = initial.materials?.generation_id;
      receipt.selected_job = selected;
      await click(dossier.getByRole('button', { name: initial.materials ? 'Regenerate documents' : 'Prepare documents', exact: true }));
      let prepared;
      const deadline = Date.now() + 120000;
      do {
        prepared = await read('/desk/' + selected.id);
        if (prepared.materials?.generation_id !== initialGeneration && prepared.materials?.qa_state === 'pending_visual_review') break;
        assert.ok(Date.now() < deadline, 'Fresh document generation did not finish');
        await new Promise(done => setTimeout(done, 250));
      } while (true);
      const preparedBound = await readDossier(selected.id, after);
      assert.deepEqual(preparedBound.public, prepared, 'Prepared public generation changed');
      const previews = [];
      for (const [name, filename] of [['Resume', 'preview.png'], ['Cover letter', 'cover_preview.png']]) {
        const preview = dossier.getByAltText(`${name} preview from current generated PDF`);
        await preview.waitFor({ timeout: 120000 });
        const decoded = await preview.evaluate(async image => { await image.decode(); return { alt: image.alt, decoded: image.complete && image.naturalWidth > 0, width: image.naturalWidth, height: image.naturalHeight, src: image.src }; });
        assert.ok(decoded.src.startsWith('data:image/png;base64,'));
        const sha256 = createHash('sha256').update(Buffer.from(decoded.src.split(',')[1], 'base64')).digest('hex');
        assert.equal(sha256, prepared.materials.artifact_hashes[filename], 'Preview must belong to the exact new generation');
        delete decoded.src;
        previews.push({ ...decoded, filename, sha256 });
      }
      assert.ok(previews.every(preview => preview.decoded));
      assert.equal(prepared.job.id, selected.id);
      assert.notEqual(prepared.materials.generation_id, initialGeneration);
      assert.match(prepared.materials.generation_id, /^[a-f0-9]{32}$/);
      assert.equal(prepared.materials.qa_state, 'pending_visual_review');
      assert.equal(prepared.next_action, 'review_exact_generation');
      assert.equal(prepared.submission_available, false);
      assert.equal(preparedBound.audit.attempt_count, 0);
      receipt.previews = previews;
      receipt.generation = prepared.materials;
      await writeFile(join(output, 'live-selected-dossier.json'), JSON.stringify(prepared, null, 2));
      await page.screenshot({ path: join(output, 'live-documents.png'), fullPage: true });
      await checkpoint('real_documents_and_previews');
      receipt.downloads = [];
      for (const [index, prefix] of ['resume', 'cover_letter'].entries()) {
        for (const extension of ['pdf', 'docx']) {
          const downloadBound = await readDossier(selected.id, after);
          assert.deepEqual(downloadBound.public, prepared, 'Download generation must remain current');
          const filename = `${prefix}.${extension}`;
          const expected = prepared.materials.artifact_hashes[filename];
          assert.match(expected || '', /^[a-f0-9]{64}$/);
          const item = { filename, job_id: selected.id, generation_id: prepared.materials.generation_id, expected_sha256: expected, outcome: 'download_event_unavailable', os_save_verified: false };
          receipt.downloads.push(item);
          const saved = await saveNativeDownload({ page, output, item, check }, async () => {
            await checkpoint('native_save_requested');
            await click(dossier.locator('article').nth(index).getByRole('button', { name: `Download ${extension.toUpperCase()}`, exact: true }));
            await dossier.getByText(`${filename} opened for download. Visual review remains a separate operator action.`, { exact: true }).waitFor();
          });
          await checkpoint('native_downloads_in_progress');
          if (!saved) {
            receipt.qualification_outcome = 'pending_native_saves'; process.exitCode = 2;
            await checkpoint('native_save_pending');
            return; // Never queue another dialog or reload before this save.
          }
        }
      }
      await reload({ reacquire: true, ready: () => search.getByText('Search setup confirmed for this imported source.', { exact: true }).waitFor() });
      const persisted = await read('/discovery');
      assertNativeLiveSetup(persisted);
      assert.equal(persisted.source_token, after.source_token);
      assert.deepEqual(persisted.queries, after.queries);
      assert.deepEqual(persisted.preferences, after.preferences);
      assert.deepEqual(persisted.last_run, after.last_run);
      assert.deepEqual(persisted.shortlist.map(item => item.id), after.shortlist.map(item => item.id));
      for (const item of grounded) await search.getByRole('button', { name: `${item.title} · ${item.company}`, exact: true }).waitFor();
      const finalBound = await readDossier(selected.id, after);
      const final = finalBound.public;
      assert.deepEqual(final, prepared, 'Final source/job/current generation binding changed');
      assert.deepEqual(final.materials, prepared.materials, 'Final exact material binding changed');
      assert.equal(final.materials.generation_id, prepared.materials.generation_id);
      assert.equal(final.materials.qa_state, 'pending_visual_review');
      assert.equal(final.submission_available, false);
      assert.equal(finalBound.audit.attempt_count, 0);
      assert.deepEqual(errors, []);
      receipt.persistent_shortlist = true;
      receipt.pending_visual_review = true;
      receipt.submission_available = false;
      for (const item of receipt.downloads) assert.equal(await verifyNativeSavedFile(output, item.filename, item.expected_sha256), item.sha256, 'Final native saved bytes changed');
      receipt.qualification_outcome = nativeLiveDownloadOutcome(receipt.downloads);
      if (receipt.qualification_outcome === 'pending_native_saves') process.exitCode = 2;
      await page.screenshot({ path: join(output, 'live-persistent-shortlist.png'), fullPage: true });
      await checkpoint('live_desk_complete');
    } finally { page.off('pageerror', onError); }
    });
  } finally {
    if (connection) { await connection.close(); receipt.native_connection_disconnected = true; }
  }
}

async function nativeJourney(playwright, target, output, python, receipt) {
  // Generate only the maintained fictional source in worker storage. Never read
  // or configure the parent-owned Hermes home.
  const fixtureCode = `import sys, importlib.util; from pathlib import Path
spec=importlib.util.spec_from_file_location('fictional_runner',Path(${JSON.stringify(repo)})/'scripts/run_synthetic_applications.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.source_documents(Path(${JSON.stringify(output)}),module.load_matrix())`;
  const child = spawn(python, ['-I', '-B', '-c', fixtureCode], { cwd: output, env: { ...process.env, HERMES_HOME: join(output, 'unused-home'), JOBBY_ROOT: join(output, 'unused-state'), PYTHON_DOTENV_DISABLED: '1', PYTHONDONTWRITEBYTECODE: '1', TMPDIR: process.env.TMPDIR }, stdio: ['ignore', 'pipe', 'pipe'] });
  let diagnostic = ''; child.stdout.on('data', data => { diagnostic += data; }); child.stderr.on('data', data => { diagnostic += data; });
  try {
    await new Promise((ok, fail) => { const timer = setTimeout(() => fail(new Error('Fictional source generation timeout')), 20000); child.once('error', error => { clearTimeout(timer); fail(error); }); child.once('close', code => { clearTimeout(timer); code === 0 ? ok() : fail(new Error('Fictional source generation failed')); }); });
  } finally { await stopFixture(child); await writeFile(join(output, 'source-generation.log'), diagnostic); }
  receipt.unexecuted = ['native profile switching', 'native delayed response race', 'native unavailable backend', 'full usability acceptance', 'human PDF/DOCX visual QA'];
  let connection;
  try {
    connection = await playwright.chromium.connectOverCDP(target.endpoint, { timeout: 10000, artifactsDir: output, downloadsPath: output, noDefaults: true });
    const matches = connection.contexts().flatMap(context => context.pages()).filter(page => page.url() === target.page);
    assert.equal(matches.length, 1, 'Expected exactly one page at the supplied owned renderer URL');
    const page = matches[0]; page.setDefaultTimeout(20000);
    // Genuine host IPC readback, restricted to our plugin namespace. All writes
    // in the journey remain normal pointer/keyboard form actions.
    const readCurrent = () => page.evaluate(async () => {
      const sdk = window.__HERMES_PLUGIN_SDK__;
      if (!sdk?.host || !window.hermesDesktop?.api) throw new Error('Native SDK/IPC unavailable');
      const scope = { profile: sdk.host.state.profile.get(), connectionId: sdk.host.state.connectionId.get() };
      const overview = await window.hermesDesktop.api({ path: '/api/plugins/jobby/desk', ...scope });
      if (!overview.ok || overview.jobs.length !== 1) throw new Error('Expected one fictional selected posting');
      return window.hermesDesktop.api({ path: '/api/plugins/jobby/desk/' + overview.jobs[0].id, ...scope });
    });
    const errors = []; const onError = error => errors.push(error.message); page.on('pageerror', onError);
    try {
      if (!await page.getByRole('main', { name: 'Jobby desk' }).count()) await page.getByRole('button', { name: 'Jobby desk', exact: true }).click();
      await page.getByRole('main', { name: 'Jobby desk' }).waitFor();
      receipt.native_mount = true;
      await primaryJourney(page, output, readCurrent, receipt);
      assert.deepEqual(errors, []);
      receipt.native_primary_ui = true;
    } finally { page.off('pageerror', onError); }
  } finally {
    // Playwright connectOverCDP's close implementation closes its WebSocket
    // transport only (inspected installed implementation); no Browser.close CDP
    // command, page.close, context.close or parent process termination.
    if (connection) { await connection.close(); receipt.native_connection_disconnected = true; }
  }
}

export async function main(argv = process.argv.slice(2)) {
const [outputArg, sdkArg, modulesArg, pythonArg, ...flags] = argv;
const { mode, target: native, liveHome } = parseQualificationMode(flags);
const owned = '/home/adcan288/tmp/jobby-hackathon-20261107/worker/';
assert.ok(outputArg && isAbsolute(outputArg) && resolve(outputArg).startsWith(owned), 'Fresh output must be inside the owned Nov07 worker directory');
const output = resolve(outputArg), sdk = resolve(sdkArg || '/home/adcan288/.hermes/hermes-agent');
const modules = resolve(modulesArg || join(sdk, 'apps/desktop/node_modules'));
const python = pythonArg || '/home/adcan288/tmp/jobby-hackathon-20261106/parent-runtime/bin/python';
if (mode === 'native-live') {
  await validateOwnedLiveHome(liveHome, pythonArg);
}
await mkdir(output, { mode: 0o700 });
return await withBrowserTemp(async browserTemp => {
const receipt = { native_mount: false, browser_harness: false, mode, scope: native ? 'Actual parent-owned Electron renderer/SDK/IPC. No host/component/state/API adapters.' : 'Fictional local browser harness with real API, storage, generation, React Query and SDK UI components. Host registration/navigation/state are harness adapters; theme CSS is a harness approximation.' };
let browser, server, api;
try {
  const playwright = await import(pathToFileURL(process.env.JOBBY_PLAYWRIGHT_MODULE || '/home/adcan288/hermes-secure-browser/control/node_modules/playwright-core/index.mjs'));
  if (mode === 'native-live') { await nativeLiveJourney(playwright, native, output, receipt, { liveHome, python }); return; }
  if (native) { await nativeJourney(playwright, native, output, python, receipt); return; }
  const requireDeps = createRequire(join(modules, '__qualification__.js'));
  for (const name of ['esbuild', '@tanstack/react-query', 'react', 'react-dom/client', 'nanostores', '@nanostores/react']) requireDeps.resolve(name);
  const { build } = requireDeps('esbuild');
  const component = name => JSON.stringify(join(sdk, `apps/desktop/src/components/ui/${name}.tsx`));
  // Only the host boundary is adapted. All UI and query implementations are real.
  const bridge = `
import { atom } from 'nanostores';
export { useStore as useValue } from '@nanostores/react';
export { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
export { Button } from ${component('button')};
export { Input } from ${component('input')};
export { Textarea } from ${component('textarea')};
export { Badge } from ${component('badge')};
export { Checkbox } from ${component('checkbox')};
export { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from ${component('select')};
export const ROUTES_AREA='routes', SIDEBAR_NAV_AREA='sidebar.nav', PALETTE_AREA='palette';
let activationEpoch=0;
export const gatewayActivationEpoch=()=>activationEpoch;
export const host = { state: { connectionId: atom('harness'), profile: atom('a'), focusedSessionProfile: atom('a'), focusedSessionOwner: atom({connectionId:'harness',profile:'a'}) }, navigate: path => window.harnessNavigate(path) };
window.switchDeskProfile = value => { host.state.profile.set(value); host.state.focusedSessionProfile.set(value); host.state.focusedSessionOwner.set({connectionId:'harness',profile:value}); };
window.switchDeskConnection = value => { activationEpoch++; host.state.connectionId.set(value); host.state.focusedSessionOwner.set({connectionId:value,profile:host.state.profile.get()}); };
window.switchDeskOwner = value => host.state.focusedSessionOwner.set({connectionId:value,profile:host.state.profile.get()});
`;
  await writeFile(join(output, 'sdk-bridge.js'), bridge);
  const entry = `
import React from 'react';
import {createRoot} from 'react-dom/client';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import plugin from ${JSON.stringify(join(repo, 'desktop/plugin.js'))};
import {host} from './sdk-bridge.js';
const contributions=[];
window.harnessArtifactResponses=[];
window.harnessDiscoveryResponses=0;
const ctx={source:'plugin:jobby', register:c=>contributions.push(c), rest:async(path,opts={})=>{
 const profile=host.state.profile.get();
 const response=await fetch('/api/plugins/jobby'+path,{method:opts.method||'GET', headers:{'Content-Type':'application/json','X-Fixture-Profile':profile},body:opts.body?JSON.stringify(opts.body):undefined});
 const value=await response.json();
 if(path==='/artifact') window.harnessArtifactResponses.push({filename:opts.body.filename,generation_id:opts.body.generation_id});
 if(path==='/discovery') window.harnessDiscoveryResponses++;
 return value;
}};
plugin.register(ctx);
window.harnessContributions=contributions.map(c=>({id:c.id,area:c.area,data:c.data}));
const client=new QueryClient();
window.harnessQueryClient=client;
const root=createRoot(document.getElementById('app'));
window.harnessNavigate=()=>root.render(React.createElement(QueryClientProvider,{client},contributions.find(c=>c.id==='desk').render()));
window.harnessNavigate('/jobby');
`;
  await writeFile(join(output, 'entry.js'), entry);
  await build({ entryPoints: [join(output, 'entry.js')], outfile: join(output, 'bundle.js'), bundle: true, format: 'esm', jsx: 'automatic', nodePaths: [modules, join(sdk, 'node_modules')], alias: { '@hermes/plugin-sdk': join(output, 'sdk-bridge.js'), '@': join(sdk, 'apps/desktop/src') }, define: { 'process.env.NODE_ENV': '"production"' } });
  const backend = `
import sys, os, json, asyncio, importlib.util
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
sys.path[:0]=[${JSON.stringify(repo)},${JSON.stringify(sdk)}]
os.environ['HERMES_HOME']=${JSON.stringify(join(output, 'home-a'))}
os.environ['PYTHON_DOTENV_DISABLED']='1'
from scripts.run_synthetic_applications import source_documents, load_matrix
source_documents(Path(${JSON.stringify(output)}),load_matrix())
# Only the external provider is replaced, never adapter/Store/API methods.
import types
import pandas as pd
def fictional_search(**options):
 assert options['search_term'] in ('Software Engineer','Python','TypeScript','FastAPI','PostgreSQL','Docker','RAG','MCP')
 assert options['country_indeed']=='Canada' and options['location']=='Ottawa, ON, Canada'
 return pd.DataFrame([
  dict(title='Discovery Python Engineer',company='Fictional Discovery',location='Ottawa',job_url='https://jobs.example.test/discovered-python',description='Build Python FastAPI PostgreSQL services',date_posted='2026-11-06'),
  dict(title='Registered Nurse',company='Fictional Hospital',location='Ottawa',job_url='https://jobs.example.test/discovered-nurse',description='Clinical nursing licensure and bedside care',date_posted=None),
 ])
sys.modules['jobspy']=types.SimpleNamespace(scrape_jobs=fictional_search)
from fastapi import FastAPI
import httpx
from hermes_constants import set_hermes_home_override, reset_hermes_home_override
spec=importlib.util.spec_from_file_location('hermes_dashboard_plugin_jobby',Path(${JSON.stringify(repo)})/'dashboard/plugin_api.py')
mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
app=FastAPI();app.include_router(mod.router,prefix='/api/plugins/jobby')
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self): self.respond()
 def do_POST(self): self.respond()
 def respond(self):
  profile=self.headers.get('X-Fixture-Profile','a')
  if profile not in ('a','b'): self.send_error(400);return
  length=int(self.headers.get('Content-Length',0))
  if length>150000: self.send_error(413);return
  raw=self.rfile.read(length)
  async def call():
   token=set_hermes_home_override(Path(${JSON.stringify(output)})/('home-'+profile))
   try:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
     return await client.request(self.command,self.path,content=raw,headers={'Content-Type':'application/json'})
   finally: reset_hermes_home_override(token)
  response=asyncio.run(call());self.send_response(response.status_code);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(response.content)
http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
print(json.dumps({'port':http.server_port}),flush=True);http.serve_forever()
`;
  await writeFile(join(output, 'api.py'), backend);
  api = spawn(python, ['-I', '-B', join(output, 'api.py')], { env: { ...process.env, PYTHON_DOTENV_DISABLED: '1', PYTHONDONTWRITEBYTECODE: '1', TMPDIR: browserTemp }, stdio: ['ignore', 'pipe', 'pipe'] });
  let apiError=''; api.stderr.on('data', data=>{apiError+=data;});
  const port = await new Promise((ok, fail) => { let buffer=''; const timer=setTimeout(()=>fail(new Error('Fixture API startup timeout')),15000); api.stdout.on('data',data=>{buffer+=data; for(const line of buffer.split('\n')) { try { const value=JSON.parse(line);if(value.port){clearTimeout(timer);ok(value.port);return;} } catch {} }}); api.once('error',error=>{clearTimeout(timer);fail(error);}); api.once('exit',()=>{clearTimeout(timer);fail(new Error('Fixture API failed: '+apiError));}); });
  const html = `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Jobby browser harness</title><style>:root{color-scheme:light;--ui-text-primary:CanvasText;--ui-text-secondary:GrayText;--ui-stroke-secondary:ButtonBorder;--ui-bg-quaternary:ButtonFace}*{box-sizing:border-box}body{margin:0;font:14px system-ui}button,input,textarea{font:inherit;padding:7px}button{cursor:pointer}input,textarea{border:1px solid ButtonBorder}button:focus-visible,input:focus-visible,textarea:focus-visible,summary:focus-visible{outline:2px solid Highlight;outline-offset:2px}details summary{cursor:pointer}img{display:block}</style><div id="app"></div><script type="module" src="/bundle.js"></script>`;
  server=createServer(async(req,res)=>{
    if(req.url.startsWith('/api/plugins/jobby/')) {
      try { const raw=[];for await(const chunk of req)raw.push(chunk); const response=await fetch('http://127.0.0.1:'+port+req.url,{method:req.method,headers:{'Content-Type':'application/json','X-Fixture-Profile':req.headers['x-fixture-profile']||'a'},body:req.method==='POST'?Buffer.concat(raw):undefined});res.writeHead(response.status,{'Content-Type':'application/json'});res.end(await response.text()); }catch{res.writeHead(503);res.end('{"ok":false}');}return;
    }
    if(req.url==='/bundle.js'){res.setHeader('Content-Type','application/javascript');res.end(await readFile(join(output,'bundle.js')));return;}
    res.setHeader('Content-Type','text/html');res.end(html);
  });
  await new Promise((ok,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
  browser=await playwright.chromium.launch({ executablePath: process.env.JOBBY_TEST_CHROME || '/usr/bin/google-chrome', headless:true, chromiumSandbox:true, artifactsDir:output, downloadsPath:output, env:{...process.env,TMPDIR:browserTemp} });
  const page=await browser.newPage({viewport:{width:1280,height:1000}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*', route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
  const base='http://127.0.0.1:'+server.address().port;
  await page.goto(base);
  assert.deepEqual((await page.evaluate(()=>window.harnessContributions)).map(c=>c.id),['desk','nav','open']);
  await primaryJourney(page, output, async () => (await page.request.get(base+'/api/plugins/jobby/desk/1')).json(), receipt);
  assertHarnessDownloads(receipt.downloads);
  await delayedSelectedJobDownload(page, receipt);
  await delayedSelectedJobDownload(page, receipt, { key: 'delayed_regenerated_download', retire: async ({ desk, dossier, observed }) => {
    await desk.getByRole('button', { name: 'Regenerate documents', exact: true }).click();
    await dossier.getByText(`Generation ${observed.generation_id}`, { exact: true }).waitFor({ state: 'detached' });
    await dossier.getByAltText('Resume preview from current generated PDF').waitFor();
    assert.notEqual(await dossier.getByText(/^Generation /).textContent(), `Generation ${observed.generation_id}`);
    observed.new_generation_before_release = true;
  } });
  for (const [key, switcher, other, batched] of [
    ['profile_roundtrip', 'switchDeskProfile', 'b', false],
    ['profile_batched_roundtrip', 'switchDeskProfile', 'b', true],
    ['connection_roundtrip', 'switchDeskConnection', 'other-harness', false],
    ['focused_owner_roundtrip', 'switchDeskOwner', 'other-focused-harness', false],
    ['same_name_connection_activation', 'switchDeskConnection', 'harness', false],
  ]) {
    await delayedSelectedJobDownload(page, receipt, { key: 'delayed_' + key, retire: async ({ desk, dossier, savedA, observed }) => {
      await desk.getByLabel('Posting description', { exact: true }).fill('Fictional input must clear');
      const original = switcher === 'switchDeskProfile' ? 'a' : 'harness';
      if (batched) await page.evaluate(({ switcher, other, original }) => { window[switcher](other); window[switcher](original); }, { switcher, other, original });
      else {
        await page.evaluate(({ switcher, other }) => window[switcher](other), { switcher, other });
        await dossier.getByRole('heading', { name: 'Your document dossier', exact: true }).waitFor();
        assert.equal(await desk.getByLabel('Posting description', { exact: true }).inputValue(), '');
        await page.evaluate(({ switcher, original }) => window[switcher](original), { switcher, original });
      }
      await dossier.getByRole('heading', { name: 'Your document dossier', exact: true }).waitFor();
      assert.equal(await desk.getByLabel('Posting description', { exact: true }).inputValue(), '');
      assert.equal(await savedA.getAttribute('aria-pressed'), 'false');
      await savedA.click();
      await dossier.getByAltText('Resume preview from current generated PDF').waitFor();
      observed.scope_roundtrip_before_release = true;
    } });
  }
  await delayedSelectedJobDownload(page, receipt, { key: 'delayed_retired_preview_query', filename: 'preview.png', query: true, retire: async ({ dossier, savedB, observed }) => {
    await savedB.click();
    await dossier.getByRole('heading', { name: 'Systems Engineer · Fictional Second Example', exact: true }).waitFor();
    assert.equal(await savedB.getAttribute('aria-pressed'), 'true');
    observed.selected_b_before_release = true;
  } });
  // Positive control after all retirements: the current generation still saves.
  const positiveCurrent = await (await page.request.get(base+'/api/plugins/jobby/desk/1')).json();
  assert.equal(positiveCurrent.materials.qa_state, 'pending_visual_review');
  assert.equal(positiveCurrent.submission_available, false);
  const positiveEvent = page.waitForEvent('download');
  await page.getByRole('main', { name: 'Jobby desk' }).locator('article').first().getByRole('button', { name: 'Download PDF', exact: true }).click();
  const positiveDownload = await positiveEvent;
  await positiveDownload.saveAs(join(output, 'positive-current-resume.pdf'));
  assert.equal(positiveDownload.suggestedFilename(), 'resume.pdf');
  assert.equal(await positiveDownload.failure(), null);
  const positiveHash = createHash('sha256').update(await readFile(join(output, 'positive-current-resume.pdf'))).digest('hex');
  assert.equal(positiveHash, positiveCurrent.materials.artifact_hashes['resume.pdf']);
  receipt.current_download_positive_control = { outcome: 'saved_hash_verified', sha256: positiveHash };
  for(const width of [320,600]){await page.setViewportSize({width,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:join(output,'documents-'+width+'.png'),fullPage:true});}
  await page.setViewportSize({width:1280,height:1000});
  await discoveryJourney(page, output, base, receipt);
  for (const operation of discoveryOperations) {
    for (const [switcher, other, batched] of discoveryTransitions) {
      await delayedDiscoveryResponse(page, receipt, operation, switcher, other, batched);
    }
  }
  await page.getByRole('button',{name:'Python Engineer · Fictional Example',exact:true}).click();
  await page.getByAltText('Resume preview from current generated PDF').waitFor();
  // A delayed old-profile response must never repopulate the new profile.
  let release; const delay=new Promise(ok=>{release=ok;});
  await page.route('**/api/plugins/jobby/desk/1',async route=>{await delay;await route.continue();});
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await page.evaluate(()=>window.switchDeskProfile('b'));
  release();
  await page.getByText('No saved postings yet.',{exact:false}).waitFor();
  assert.equal(await page.getByAltText('Resume preview from current generated PDF').count(),0);
  assert.equal(await page.getByLabel('Absolute PDF path on the Hermes backend machine').inputValue(),'');
  assert.equal(await page.getByLabel('Posting description',{exact:true}).inputValue(),'');
  await page.screenshot({path:join(output,'profile-b-320.png'),fullPage:true});
  await page.route('**/api/plugins/jobby/**',route=>route.fulfill({status:503,contentType:'application/json',body:'{"ok":false}'}));
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await page.getByRole('alert').waitFor();
  assert.deepEqual(errors,[]);
  assertHarnessDownloads(receipt.downloads);
  assertHarnessDiscoveryRetirements(receipt);
  receipt.browser_harness=true;receipt.checks=['actual API import/prepare/previews','pending review retained','sidebar/palette registration','320/600/wide captures without overflow','profile clear and delayed old response','retired download/query and generation/scope round trips','current download positive control','recoverable backend error'];
} catch(error) { receipt.error=String(error.message); if (mode === 'native-live') receipt.qualification_outcome = 'failed'; process.exitCode=1; }
finally {
  const cleanupErrors = [];
  try { if (browser) await browser.close(); } catch (error) { cleanupErrors.push(error.message); }
  try { if (server) await new Promise(ok => { server.close(ok); server.closeAllConnections(); }); } catch (error) { cleanupErrors.push(error.message); }
  try { await stopFixture(api); } catch (error) { cleanupErrors.push(error.message); }
  receipt.fixture_cleanup = cleanupErrors.length ? 'failed' : mode === 'native-live' ? 'not_started' : 'awaited';
  if (cleanupErrors.length) { receipt.cleanup_errors = cleanupErrors; process.exitCode = 1; }
  await writeFile(join(output,'receipt.json'),JSON.stringify(receipt,null,2));
  process.stdout.write(JSON.stringify(receipt)+'\n');
}
});
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
