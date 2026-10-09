"""Launcher subprocess boundary; fixture commands never touch a real profile."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'personal_jobby/bin/jobby'


def fixture_launcher(tmp_path):
    repo = tmp_path / 'trusted repo'
    entry = repo / 'personal_jobby/bin/jobby'
    entry.parent.mkdir(parents=True)
    shutil.copy2(LAUNCHER, entry)
    (repo / '.venv/bin').mkdir(parents=True)
    (repo / '.venv/bin/python').symlink_to(sys.executable)
    (repo / 'personal_jobby/__init__.py').write_text('')
    (repo / 'personal_jobby/__main__.py').write_text(
        'import json, sys\n'
        'def main():\n'
        '    if sys.argv[1:] == ["--help"]:\n'
        '        print("fixture help"); return\n'
        '    if sys.argv[1:] == ["fail"]:\n'
        '        print("Error: input values withheld", file=sys.stderr)\n'
        '        raise SystemExit(7)\n'
        '    print(json.dumps(dict(argv=sys.argv[1:], isolated=sys.flags.isolated)))\n'
    )
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    link = scratch / 'jobby'
    link.symlink_to(entry)
    return link, scratch


def test_help_from_scratch_cwd_through_symlink(tmp_path):
    entry, scratch = fixture_launcher(tmp_path)
    result = subprocess.run([str(entry), '--help'], cwd=scratch, capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout == 'fixture help\n'
    assert result.stderr == ''


def test_failure_exit_and_stderr_are_preserved(tmp_path):
    entry, scratch = fixture_launcher(tmp_path)
    result = subprocess.run([str(entry), 'fail'], cwd=scratch, capture_output=True, text=True)
    assert result.returncode == 7
    assert result.stdout == ''
    assert result.stderr == 'Error: input values withheld\n'


def test_literal_arguments_and_isolated_imports(tmp_path):
    entry, scratch = fixture_launcher(tmp_path)
    (scratch / 'personal_jobby').mkdir()
    (scratch / 'personal_jobby/__init__.py').write_text('raise RuntimeError("cwd imported")')
    (scratch / 'sitecustomize.py').write_text('raise RuntimeError("environment imported")')
    args = ['space value', '$(touch injected)', '; touch injected', '"quoted"', '', '--flag']
    result = subprocess.run([str(entry), *args], cwd=scratch, capture_output=True, text=True,
                            env={**os.environ, 'PYTHONPATH': str(scratch), 'PYTHONHOME': str(scratch)})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'argv': args, 'isolated': 1}
    assert not (scratch / 'injected').exists()


def test_actual_repository_help_only(tmp_path):
    result = subprocess.run([str(LAUNCHER), '--help'], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout
    assert all(command in result.stdout for command in ('status', 'prepare', 'attempt', 'screenshot', 'receipt'))
