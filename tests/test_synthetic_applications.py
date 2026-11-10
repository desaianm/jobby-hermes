"""Offline contract tests for the deliberately fictional scenario command."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('synthetic_applications', ROOT / 'scripts/run_synthetic_applications.py')
scenario = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenario)


def test_matrix_confines_exactly_five_distinct_fictional_roles():
    matrix = scenario.load_matrix()
    assert [r['id'] for r in matrix['roles']] == [
        'ai-engineer', 'backend-engineer', 'ml-platform-engineer', 'fde', 'senior-stretch']
    assert all(r['supported_fact_ids'] and r['gaps'] for r in matrix['roles'])
    for bad in ['https://forbidden.example/jobs/ai-engineer',
                'https://applications.example.test.evil/jobs/ai-engineer',
                'https://applications.example.test/jobs/unknown',
                'https://applications.example.test/jobs/ai-engineer?redirect=x']:
        with pytest.raises(ValueError):
            scenario.validate_url(bad, matrix)
    matrix['roles'][1]['id'] = matrix['roles'][0]['id']
    with pytest.raises(ValueError):
        scenario.validate_matrix(matrix)


def test_native_upload_boundary_rejects_hash_mismatch_and_duplicate_send(tmp_path):
    import subprocess
    result = subprocess.run(['/usr/bin/node', '--input-type=module', '-e', '''
      import assert from 'node:assert/strict';
      import { validatePost, routeKind } from './browser/synthetic-applications.mjs';
      const row = {id:'ai-engineer',attempt_id:'attempt',manifest:{resume:{sha256:'a'.repeat(64)}}};
      assert.throws(()=>validatePost(row, 'b'.repeat(64), 0));
      assert.throws(()=>validatePost(row, 'a'.repeat(64), 1));
      assert.equal(validatePost(row, 'a'.repeat(64), 0), true);
      assert.equal(routeKind('https://applications.example.test/jobs/ai-engineer','GET',row),'form');
      for(const url of ['https://evil.test/jobs/ai-engineer','https://applications.example.test/jobs/unknown',
                       'https://applications.example.test/jobs/ai-engineer?next=evil'])
        assert.equal(routeKind(url,'GET',row),'abort');
    '''], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope='module')
def prepared(tmp_path_factory):
    import json
    import subprocess
    output = tmp_path_factory.mktemp('scenario') / 'output'
    result = subprocess.run([str(ROOT / '.venv/bin/python'), str(ROOT / 'scripts/run_synthetic_applications.py'),
                             '--output', str(output), '--prepare-only'], cwd=output.parent,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    (output / 'command-stdout.txt').write_text(result.stdout)
    (output / 'command-stderr.txt').write_text(result.stderr)
    return output, json.loads((output / 'report.json').read_text())


def test_real_documents_retain_source_and_gaps_and_use_isolated_state(prepared):
    import json
    import fitz
    from docx import Document
    output, report = prepared
    assert len(report['roles']) == 5
    for row in report['roles']:
        assert row['truth_checked'] and row['post_count'] == 0
        assert row['outcome'] == 'prepared_browser_not_executed'
        assert Path(row['artifact_directory']).is_relative_to(output)
        assert len(row['source_hashes']) == 3
        with fitz.open(Path(row['artifact_directory']) / 'resume.pdf') as pdf:
            text = ' '.join(p.get_text() for p in pdf)
            assert len(pdf) == 1 and 'FICTIONAL TEST CANDIDATE' in text
        for gap in row['gaps']:
            assert gap['claim'] not in text
        assert Document(Path(row['artifact_directory']) / 'resume.docx').sections[0].left_margin.inches == .75
    assert not (output / 'unused-cli-root').exists()
    assert not list(output.glob('*.submit-intent.json'))


def test_native_audit_rejects_wrong_attachment_and_duplicate_receipts(prepared, tmp_path):
    import copy
    import shutil
    from personal_jobby.audit import create_attempt, add_screenshot, record_receipt, attempt_record
    from personal_jobby.store import Store, now
    output, report = prepared
    row = report['roles'][0]
    workspace = tmp_path / 'offline-audit-unit-fixture'
    shutil.copytree(output / 'hermes-profile/plugin-data/jobby/workspace', workspace)
    store = Store(workspace)
    bad = copy.deepcopy(row['manifest'])
    bad['operator'] = 'hermes'
    bad['resume']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='hash mismatch'):
        create_attempt(store, row['job_id'], bad)
    for outcome in ('error', 'challenge', 'uncertain'):
        with pytest.raises(ValueError, match='No verified'):
            scenario.reconcile(store, row, {'outcome':outcome})
    # Real generated PNG used for the offline audit seam only; not browser evidence or a reported run result.
    for kind in ('filled_form', 'employer_confirmation'):
        add_screenshot(store, row['attempt_id'], output / 'fictional-source.png', kind,
                       'Simulated fixture review: offline native audit test only', True)
    record_receipt(store, row['job_id'], 'Offline audit unit fixture only', now(), row['url'], row['attempt_id'])
    with pytest.raises(ValueError, match='already recorded'):
        record_receipt(store, row['job_id'], 'Duplicate offline audit fixture', now(), row['url'], row['attempt_id'])
    with pytest.raises(ValueError, match='Already submitted'):
        create_attempt(store, row['job_id'], {'operator':'hermes', **row['manifest']})
    assert attempt_record(store, row['attempt_id'])['status'] == 'applied'


def test_output_and_submit_intent_refuse_reuse_and_unsafe_destinations(tmp_path):
    from personal_jobby import private_fs as fs
    with pytest.raises(ValueError):
        scenario.fresh_output('/tmp/not-owned-synthetic-output')
    out = scenario.fresh_output(tmp_path / 'fresh')
    with pytest.raises(FileExistsError):
        scenario.fresh_output(out)
    scenario.reserve_once(out, 'ai-engineer', 'test-attempt')
    with pytest.raises(FileExistsError):
        scenario.reserve_once(out, 'ai-engineer', 'another-attempt')
    symlink = tmp_path / 'symlink'
    symlink.symlink_to(out, target_is_directory=True)
    with pytest.raises(ValueError):
        scenario.fresh_output(symlink / 'unsafe')


def test_final_artifact_truth_check_rejects_inserted_unsupported_claim(prepared, tmp_path):
    import shutil
    from docx import Document
    from personal_jobby.store import Store
    output, report = prepared
    workspace = tmp_path / 'tampered-fixture'
    shutil.copytree(output / 'hermes-profile/plugin-data/jobby/workspace', workspace)
    store = Store(workspace)
    role = scenario.load_matrix()['roles'][-1]
    row = report['roles'][-1]
    path = store.artifact_dir(row['job_id']) / 'resume.docx'
    document = Document(path)
    document.add_paragraph('Managed a team of 12 engineers')
    document.save(path)
    with pytest.raises(ValueError, match='Unsupported claim'):
        scenario.verify_truth(store, row['job_id'], role)


def test_prepare_only_entire_stdout_is_json_from_another_cwd(prepared):
    import json
    output, report = prepared
    result = json.loads((output / 'command-stdout.txt').read_text())
    assert result == dict(ok=True, browser_executed=False, report=str(output / 'report.json'))
    assert len(report['roles']) == 5


@pytest.mark.parametrize('spawn_fails', [False, True])
def test_deep_output_uses_unique_short_owned_browser_temp_and_cleans_up(tmp_path, monkeypatch, spawn_fails):
    import subprocess
    import sys
    output = tmp_path / ('deep-output-' + 'x' * 90) / 'evidence'
    output.mkdir(parents=True)
    real_popen = subprocess.Popen
    observed = []

    def offline_child(*args, **kwargs):
        temporary = Path(kwargs['env']['TMPDIR'])
        assert temporary.is_dir()
        assert temporary.stat().st_mode & 0o777 == 0o700
        observed.append(temporary)
        if spawn_fails:
            raise OSError('offline spawn failure')
        # Exercise real child EOF/reaping; never launch Chrome or access a network.
        return real_popen([sys.executable, '-c', 'pass'], **kwargs)

    monkeypatch.setattr(scenario.subprocess, 'Popen', offline_child)
    for _ in range(2):
        with pytest.raises((RuntimeError, OSError), match='Browser stopped|offline spawn failure'):
            scenario.browser_role(output, {'id': 'ai-engineer'}, None, 'unused', 'unused')
    assert len(set(observed)) == 2
    for temporary in observed:
        assert temporary.parent == scenario.BASE
        assert len(str(temporary)) < 65
        assert not temporary.exists()
    assert (output / 'ai-engineer.browser-input.json').is_file()
    assert (output / 'ai-engineer.browser-stderr.txt').is_file()


def test_loopback_receiver_preserves_native_binary_and_rejects_invalid_posts(tmp_path):
    """Real HTTP bytes and native multipart parser; no browser or CDP reconstruction."""
    import subprocess
    result = subprocess.run(['/usr/bin/node', '--input-type=module', '-e', r'''
      import assert from 'node:assert/strict';
      import {request} from 'node:http';
      import {createHash} from 'node:crypto';
      import {mkdir, readFile, writeFile} from 'node:fs/promises';
      import {startFixture, transportRouteKind} from './browser/synthetic-applications.mjs';
      const base=process.argv[1], hash=b=>createHash('sha256').update(b).digest('hex');
      const binary=Buffer.from([0x25,0x50,0x44,0x46,0,0xff,0xfe,0x80,0x0d,0x0a,0xc3,0x28]);
      for(const mode of ['valid','hash','answer','filename','extra','oversize']) {
        const directory=`${base}/${mode}`;await mkdir(directory);
        const row={id:'ai-engineer',attempt_id:'fixture-attempt',output_directory:directory,
          resume_path:`${directory}/resume.pdf`,manifest:{resume:{sha256:hash(binary)}},
          identity:{name:'Rowan Example — FICTIONAL TEST CANDIDATE',email:'rowan@example.test',
            location:'Example City (fictional)',answers:{work_eligibility:'Fixture only'}},
          gaps:[{claim:'Unverified fixture claim'}]};
        await writeFile(row.resume_path,binary);
        const fixture=await startFixture(row);
        const send=(path,method,bytes,contentType,host=new URL(fixture.origin).host)=>new Promise((resolve,reject)=>{
          const req=request(fixture.origin+path,{method,headers:{host,'content-type':contentType,
            'content-length':bytes.length}},res=>{const parts=[];res.on('data',b=>parts.push(b));
              res.on('end',()=>resolve({status:res.statusCode,body:Buffer.concat(parts).toString()}));});
          req.on('error',reject);req.setTimeout(5000,()=>req.destroy(new Error('test timeout')));
          req.end(bytes);
        });
        try {
          for(const path of ['/jobs/unknown','/jobs/ai-engineer?query=1','/submit/ai-engineer'])
            assert.equal((await send(path,'GET',Buffer.alloc(0),'text/plain')).status,403);
          assert.equal((await send('/jobs/ai-engineer','GET',Buffer.alloc(0),'text/plain','evil.test')).status,403);
          assert.equal(transportRouteKind(fixture.origin+'/jobs/ai-engineer','GET',row,fixture.origin),'form');
          for(const url of ['http://127.0.0.1:1/jobs/ai-engineer',fixture.origin+'/jobs/ai-engineer?x',
            'https://evil.test/jobs/ai-engineer']) assert.equal(transportRouteKind(url,'GET',row,fixture.origin),'abort');
          const data=new FormData();
          for(const [key,value] of Object.entries({attempt_id:row.attempt_id,name:row.identity.name,
            email:row.identity.email,location:row.identity.location,eligibility:'Fixture only',
            gaps:'Not supported: Unverified fixture claim',private_fixture:'fictional-preserved'})) data.set(key,value);
          if(mode==='answer') data.set('eligibility','Wrong answer');
          if(mode==='extra') data.append('unexpected','fixture');
          data.set('resume',new Blob([mode==='hash'?Buffer.from([1,2,3]):binary]),mode==='filename'?'wrong.pdf':'resume.pdf');
          const encoded=new Request(fixture.origin,{method:'POST',body:data});
          const bytes=mode==='oversize'?Buffer.alloc(8*1024*1024+1):Buffer.from(await encoded.arrayBuffer());
          const contentType=encoded.headers.get('content-type');
          const response=await send('/submit/ai-engineer','POST',bytes,contentType);
          assert.equal(fixture.observedPosts,1);
          if(mode==='valid') {
            assert.equal(response.status,200);assert.ok(response.body.includes('id="ack"'));
            assert.equal(fixture.postCount,1);assert.equal(fixture.error,null);
            assert.deepEqual(await readFile(fixture.captured.multipart_path),bytes);
            assert.equal(fixture.captured.multipart_sha256,hash(bytes));
            assert.equal(fixture.captured.resume_sha256,hash(binary));
            assert.equal(fixture.captured.content_type,contentType);
            const parsed=await new Request(fixture.origin,{method:'POST',headers:{'content-type':contentType},body:bytes}).formData();
            assert.deepEqual(Buffer.from(await parsed.get('resume').arrayBuffer()),binary);
            assert.equal((await send('/submit/ai-engineer','POST',bytes,contentType)).status,400);
            assert.equal(fixture.observedPosts,2);assert.equal(fixture.postCount,1);
          } else {
            assert.equal(response.status,400);assert.ok(!response.body.includes('id="ack"'));
            assert.equal(fixture.postCount,0);assert.equal(fixture.captured,null);assert.ok(fixture.error);
          }
        } finally {await fixture.close();}
        await assert.rejects(send('/jobs/ai-engineer','GET',Buffer.alloc(0),'text/plain'));
      }
      console.log('binary HTTP receiver and negative controls passed');
    ''', str(tmp_path)], cwd=ROOT, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr


def test_native_multipart_parser_preserves_binary_before_known_hash_validation():
    import subprocess
    result = subprocess.run(['/usr/bin/node', '--input-type=module', '-e', r'''
      import assert from 'node:assert/strict';
      import {createHash} from 'node:crypto';
      import {validatePost,transportRouteKind} from './browser/synthetic-applications.mjs';
      const bytes=Buffer.from([0,255,254,128,13,10,195,40]);
      const hash=b=>createHash('sha256').update(b).digest('hex');
      const data=new FormData();data.set('resume',new Blob([bytes]),'resume.pdf');
      const request=new Request('http://127.0.0.1:12345',{method:'POST',body:data});
      const raw=Buffer.from(await request.arrayBuffer());
      const parsed=await new Request(request.url,{method:'POST',headers:request.headers,body:raw}).formData();
      const actual=Buffer.from(await parsed.get('resume').arrayBuffer());
      assert.deepEqual(actual,bytes);
      const row={id:'ai-engineer',manifest:{resume:{sha256:hash(bytes)}}};
      assert.equal(validatePost(row,hash(actual),0),true);
      assert.throws(()=>validatePost(row,hash(Buffer.from([1])),0),/Uploaded file hash mismatch/);
      assert.throws(()=>validatePost(row,hash(actual),1),/Duplicate/);
      const origin='http://127.0.0.1:12345';
      assert.equal(transportRouteKind(origin+'/submit/ai-engineer','POST',row,origin),'post');
      for(const url of [origin+'/submit/ai-engineer?x',origin+'/submit/fde',
        'http://127.0.0.1:12346/submit/ai-engineer','https://evil.test/submit/ai-engineer'])
        assert.equal(transportRouteKind(url,'POST',row,origin),'abort');
    '''], cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_native_mode_requires_explicit_sdk_source_before_creating_state(tmp_path):
    import json
    import os
    import subprocess
    import sys
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_synthetic_applications.py'),
        '--native-installed', '--prepare-only', '--runtime-python', '/nonexistent-synthetic-runtime',
        '--output', str(tmp_path / 'unused')], cwd=tmp_path,
        env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'}, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert '--hermes-source' in json.loads(result.stdout)['blocker']
    assert not (tmp_path / 'unused').exists()


@pytest.mark.parametrize('extra', [[], ['--prepare-only', '--source-manifest', '/synthetic-manifest.json']])
def test_native_mode_refuses_browser_or_benchmark_work_before_state(tmp_path, extra):
    import json
    import os
    import subprocess
    import sys
    sdk = tmp_path / 'sdk'
    (sdk / 'hermes_cli').mkdir(parents=True)
    (sdk / 'hermes_cli/plugins.py').write_text('# synthetic source-shape check only\n')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_synthetic_applications.py'),
        '--native-installed', '--runtime-python', sys.executable, '--hermes-source', str(sdk),
        '--output', str(tmp_path / 'unused'), *extra], cwd=tmp_path,
        env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'}, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert '--prepare-only and no benchmark inputs' in json.loads(result.stdout)['blocker']
    assert not (tmp_path / 'unused').exists()


def test_native_runtime_failure_cannot_report_success(tmp_path, monkeypatch):
    from argparse import Namespace
    sdk = tmp_path / 'sdk'
    (sdk / 'hermes_cli').mkdir(parents=True)
    (sdk / 'hermes_cli/plugins.py').write_text('# synthetic source-shape check only\n')
    runtime = tmp_path / 'failed-runtime'
    runtime.write_text('#!/bin/sh\nprintf \'{"ok":true}\\n\'\nexit 7\n')
    runtime.chmod(0o700)
    monkeypatch.setattr(scenario, 'NATIVE_BASE', tmp_path)
    code, result = scenario.native_launch(Namespace(runtime_python=runtime, hermes_source=sdk,
        output=tmp_path / 'output', prepare_only=True, source_manifest=None, controlled_agent_answers=False))
    assert code == 7
    assert result['ok'] is False
    assert result['child_exit'] == 7
