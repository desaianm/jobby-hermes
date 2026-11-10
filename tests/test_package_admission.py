"""Offline packaging contract; no provider requests or managed-environment writes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
import pytest

ROOT = Path(__file__).resolve().parents[1]


def discovery_requirement(requirements):
    matches = [Requirement(spec) for spec in requirements
               if Requirement(spec).name == 'python-jobspy']
    assert len(matches) == 1, 'Default plugin admission must include python-jobspy'
    requirement = matches[0]
    assert requirement.marker is None and requirement.url is None
    assert '1.4.1' in requirement.specifier
    assert '1.1.82' not in requirement.specifier
    assert '2.0' not in requirement.specifier
    return requirement


def test_default_install_admits_python314_discovery_dependency():
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    discovery_requirement(project['dependencies'])


def test_existing_install_extras_and_python_range_remain_compatible():
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    default = discovery_requirement(project['dependencies'])
    extras = project['optional-dependencies']
    assert discovery_requirement(extras['discovery']).specifier == default.specifier
    # Existing pip install .[discovery], .[dashboard] and .[test] stay declared.
    assert extras['dashboard'] == ['uvicorn>=0.27,<1']
    assert extras['test'] == ['pytest>=8,<10', 'httpx>=0.27,<1', 'Pillow>=10,<13']
    python = SpecifierSet(project['requires-python'])
    assert all(version in python for version in ('3.11', '3.12', '3.13', '3.14'))
    assert all(version not in python for version in ('3.10', '3.15'))


def test_actual_hermes_pm_admits_default_discovery(tmp_path):
    """Opt in with the owned SDK checkout; execute its unmodified declaration reader."""
    source = os.environ.get('JOBBY_HERMES_SOURCE')
    if not source:
        pytest.skip('Set JOBBY_HERMES_SOURCE to an owned Hermes SDK checkout')
    sdk = Path(source).resolve()
    assert (sdk / 'pm/plugin_declarations.py').is_file()
    script = '''import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from pm.plugin_declarations import read_python_declaration
d = read_python_declaration(Path(sys.argv[2]))
print(json.dumps(dict(requirements=d.install_requirements,
    requires_python=d.requires_python, python314_error=d.python_error('3.14'),
    installs_packages=d.installs_packages, pyproject=str(d.pyproject))))
'''
    runtime = os.environ.get('JOBBY_NATIVE_PYTHON', sys.executable)
    result = subprocess.run(
        [runtime, '-I', '-B', '-c', script, str(sdk), str(ROOT)],
        cwd=tmp_path, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    admitted = json.loads(result.stdout)
    discovery_requirement(admitted['requirements'])
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    assert admitted['requirements'] == project['dependencies']
    assert admitted['requires_python'] == project['requires-python']
    assert admitted['python314_error'] is None
    assert admitted['installs_packages'] is True
    assert admitted['pyproject'] == str(ROOT / 'pyproject.toml')
