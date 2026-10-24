"""Flet test app fixture with isolated local data and no remote server access."""

import asyncio
import os
import json
from pathlib import Path
import shutil
import sys

import pytest
import pytest_asyncio
from flet.testing import FletTestApp


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def configure_host_mode_flutter_test(flutter_app_dir):
    """Match the generated Flutter driver to the Python-hosted test app."""
    flutter_dir = Path(flutter_app_dir)
    main_path = flutter_dir / 'lib' / 'main.dart'
    main_source = main_path.read_text(encoding='utf-8')

    if 'Tester? tester;' not in main_source:
        main_source = main_source.replace(
            'String outLogFilename = "";',
            'String outLogFilename = "";\nTester? tester;',
        )
        main_source = main_source.replace(
            'return FletApp(\n', 'return FletApp(\n      tester: tester,\n'
        )
        main_path.write_text(main_source, encoding='utf-8')

    test_driver = flutter_dir / 'integration_test' / 'app_test.dart'
    test_driver.write_text(
        """import 'package:flet_integration_test/flet_integration_test.dart';
import 'package:savings_funds/main.dart' as app;

void main() => runFletHostTest(
      appMain: app.main,
      assignTester: (tester) => app.tester = tester,
    );
""",
        encoding='utf-8',
    )


@pytest_asyncio.fixture
async def flet_app(tmp_path, monkeypatch, request):
    """Run the real app in Flet's host-mode tester against temporary files."""
    import app as app_module
    import data
    import nextcloud
    import ui.settings as settings_ui

    balance_path = tmp_path / 'balance.txt'
    funds_path = tmp_path / 'funds.json'
    budget_path = tmp_path / 'budget.json'
    config_path = tmp_path / 'nextcloud_sync.json'

    # These tests exercise the shipped UI and app callbacks while keeping all
    # persistence inside pytest's temporary directory.
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', balance_path)
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)
    monkeypatch.setattr(data, 'BUDGET_FILE', budget_path)
    monkeypatch.setattr(nextcloud, 'ACCOUNT_BALANCE_FILE', balance_path)
    monkeypatch.setattr(nextcloud, 'FUNDS_FILE', funds_path)
    monkeypatch.setattr(nextcloud, 'BUDGET_FILE', budget_path)
    monkeypatch.setattr(nextcloud, 'NEXTCLOUD_DATA_FILE', config_path)
    monkeypatch.setattr(app_module, 'ACCOUNT_BALANCE_FILE', balance_path)
    monkeypatch.setattr(app_module, 'FUNDS_FILE', funds_path)
    monkeypatch.setattr(app_module, 'BUDGET_FILE', budget_path)
    monkeypatch.setattr(app_module, 'NEXTCLOUD_DATA_FILE', config_path)
    monkeypatch.setattr(settings_ui, 'ping_nextcloud_server', lambda _data: (True, ''))

    if request.node.get_closest_marker('first_run') is None:
        config_path.write_text('{}', encoding='utf-8')
        balance_path.write_text('5000', encoding='utf-8')
        seed_funds = request.node.get_closest_marker('seed_funds')
        funds_path.write_text(
            json.dumps(seed_funds.args[0] if seed_funds else []), encoding='utf-8'
        )
        budget_path.write_text('[]', encoding='utf-8')

    flutter_app_dir = os.environ.get('FLET_TEST_FLUTTER_APP_DIR')
    if not flutter_app_dir:
        pytest.fail('Run the Flet integration suite with `uv run flet test`.')

    # flet test defaults to device mode. Host mode lets this fixture inject
    # temporary file paths and replace the remote ping before the UI launches.
    monkeypatch.setenv('FLET_TEST_DEVICE_MODE', '0')
    configure_host_mode_flutter_test(flutter_app_dir)
    if sys.platform.startswith('linux') and not shutil.which('clang++'):
        available_cxx = shutil.which('g++')
        if available_cxx:
            compiler_bin = tmp_path / 'compiler-bin'
            compiler_bin.mkdir()
            (compiler_bin / 'clang++').symlink_to(available_cxx)
            monkeypatch.setenv(
                'PATH', str(compiler_bin) + os.pathsep + os.environ.get('PATH', '')
            )
    state = {}

    async def test_main(page):
        app = app_module.SavingsFundsApp(page)
        state['sync_requests'] = []
        app._sync_file_in_background = state['sync_requests'].append
        state['app'] = app

        async def bootstrap():
            await app.perform_nextcloud_sync()
            app.load_account_balance_and_funds()

        state['bootstrap_task'] = asyncio.create_task(bootstrap())

    test_app = FletTestApp(
        flutter_app_dir=flutter_app_dir,
        flet_app_main=test_main,
        assets_dir=PROJECT_ROOT / 'src' / 'assets',
        test_path=str(request.fspath),
        device_mode=False,
    )
    test_app.paths = {
        'balance': balance_path,
        'funds': funds_path,
        'budget': budget_path,
        'nextcloud': config_path,
    }
    test_app.app_state = state
    try:
        await test_app.start()
        yield test_app
    finally:
        bootstrap_task = state.get('bootstrap_task')
        if bootstrap_task is not None and not bootstrap_task.done():
            bootstrap_task.cancel()
            try:
                await bootstrap_task
            except asyncio.CancelledError:
                pass
        await test_app.teardown()
