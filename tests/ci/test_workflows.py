"""CI contracts: failures stay fatal, reports survive failures, live access stays opt-in."""
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    # YAML 1.1 treats `on` as a boolean; the base loader preserves GitHub syntax.
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


def require_fatal_checks(job, commands):
    steps = job['steps']
    for command in commands:
        matching = [step for step in steps if step.get('run') == command]
        assert len(matching) == 1, f'Missing required check: {command}'
        assert matching[0].get('continue-on-error') != 'true', command
        assert '||' not in command, 'Checks must not swallow failures'


def test_backend_checks_and_reports_are_required():
    config = workflow('backend-ci.yml')
    job = config['jobs']['backend']
    require_fatal_checks(job, [
        'uv sync --locked',
        'uv run ruff check src tests scripts',
        'uv run mypy src/skriller',
        'uv run python scripts/export_contracts.py --output apps/web/contracts/openapi.json --check',
        "uv run pytest -m 'not live and not integration_db' --junitxml=.runtime/offline-tests.xml",
        'uv run pytest -m integration_db --junitxml=.runtime/database-tests.xml',
        'uv run pytest -m live --junitxml=.runtime/live-skips.xml',
    ])
    assert job['env']['SKRILLER_LIVE_TESTS'] == '0'
    runs = [step.get('run', '') for step in job['steps']]
    assert runs.index('docker compose up -d --wait postgres rabbitmq') < runs.index(
        'uv run pytest -m integration_db --junitxml=.runtime/database-tests.xml')
    artifact = next(step for step in job['steps'] if step.get('uses', '').startswith('actions/upload-artifact'))
    assert artifact['if'] == 'always()'
    assert artifact['with']['path'] == '.runtime/*.xml'
    cleanup = next(step for step in job['steps'] if step.get('run') == 'docker compose down')
    assert cleanup['if'] == 'always()'
    assert config['permissions'] == {'contents': 'read'}


def test_web_build_typecheck_tests_and_failure_artifacts_are_required():
    config = workflow('web-ci.yml')
    job = config['jobs']['web']
    require_fatal_checks(job, [
        'pnpm install --frozen-lockfile',
        'pnpm contracts:check',
        'pnpm test --reporter=default --reporter=junit --outputFile.junit=.runtime/web-tests.xml',
        'pnpm build', 'pnpm typecheck', 'docker build --tag skriller-web:ci .',
    ])
    artifact = next(step for step in job['steps'] if step.get('uses', '').startswith('actions/upload-artifact'))
    assert artifact['if'] == 'always()'
    # Upload actions do not inherit defaults.run.working-directory.
    assert artifact['with']['path'] == 'apps/web/.runtime/*.xml'
    assert config['permissions'] == {'contents': 'read'}


@pytest.mark.parametrize('mutation', ['removed', 'ignored'])
def test_ci_contract_rejects_removed_or_nonfatal_build(mutation):
    job = deepcopy(workflow('web-ci.yml')['jobs']['web'])
    step = next(step for step in job['steps'] if step.get('run') == 'pnpm build')
    if mutation == 'removed':
        job['steps'].remove(step)
    else:
        step['continue-on-error'] = 'true'
    with pytest.raises(AssertionError):
        require_fatal_checks(job, ['pnpm build'])


def test_backend_typecheck_rejects_broken_contract(tmp_path):
    import subprocess
    import sys

    contract = tmp_path / 'broken_contract.py'
    contract.write_text('def accept_limit(limit: int) -> int:\n    return limit\naccept_limit("twenty")\n')
    result = subprocess.run(
        [sys.executable, '-m', 'mypy', '--no-incremental', str(contract)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert '[arg-type]' in result.stdout


def test_live_without_opt_in_produces_skipped_report(tmp_path, monkeypatch):
    import subprocess
    import sys
    import xml.etree.ElementTree as ET

    monkeypatch.delenv('SKRILLER_LIVE_TESTS', raising=False)
    (tmp_path / 'conftest.py').write_text((ROOT / 'tests/conftest.py').read_text())
    (tmp_path / 'test_live.py').write_text(
        'import pytest\n@pytest.mark.live\ndef test_real_live_probe():\n'
        '    raise AssertionError("Live probe must not run without opt-in")\n'
    )
    report = tmp_path / 'results.xml'
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', str(tmp_path / 'test_live.py'),
         '--junitxml', str(report)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    cases = ET.parse(report).findall('.//testcase')
    assert len(cases) == 1
    assert cases[0].find('skipped') is not None
