"""Headless UI test fixture with isolated local data and no remote server access."""

import json
import os
import tempfile
from types import SimpleNamespace

import pytest
import pytest_asyncio
from ui_helpers import FakePage

# Importing data/nextcloud creates their data directory. Keep the test suite
# away from the real platform user-data location.
os.environ.setdefault(
    'FLET_APP_STORAGE_DATA', tempfile.mkdtemp(prefix='savings-funds-tests-')
)


@pytest.fixture(autouse=True)
def no_os_keyring(monkeypatch):
    """Keep tests deterministic when a desktop keyring is available."""
    import keyring

    import nextcloud

    def unavailable(*_args, **_kwargs):
        raise keyring.errors.NoKeyringError('test keyring disabled')

    monkeypatch.setattr(nextcloud.keyring, 'get_password', unavailable)
    monkeypatch.setattr(nextcloud.keyring, 'set_password', unavailable)
    monkeypatch.setattr(nextcloud.keyring, 'delete_password', unavailable)


@pytest_asyncio.fixture
async def headless_app(tmp_path, monkeypatch, request):
    """Run the real app and Flet control tree without a Flutter host."""
    import app as app_module
    import data
    import ledger
    import nextcloud
    import ui.settings as settings_ui

    balance_path = tmp_path / 'balance.txt'
    funds_path = tmp_path / 'funds.json'
    budget_path = tmp_path / 'budget.json'
    history_path = tmp_path / 'budget_history.json'
    ledger_path = tmp_path / 'ledger.db'
    config_path = tmp_path / 'nextcloud_sync.json'
    sync_state_path = tmp_path / 'sync_state.json'

    # These tests exercise the shipped UI and app callbacks while keeping all
    # persistence inside pytest's temporary directory.
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', balance_path)
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)
    monkeypatch.setattr(data, 'BUDGET_FILE', budget_path)
    monkeypatch.setattr(data, 'BUDGET_HISTORY_FILE', history_path)
    monkeypatch.setattr(ledger, 'LEDGER_DB', ledger_path)
    monkeypatch.setattr(nextcloud, 'ACCOUNT_BALANCE_FILE', balance_path)
    monkeypatch.setattr(nextcloud, 'FUNDS_FILE', funds_path)
    monkeypatch.setattr(nextcloud, 'BUDGET_FILE', budget_path)
    monkeypatch.setattr(nextcloud, 'BUDGET_HISTORY_FILE', history_path)
    monkeypatch.setattr(nextcloud, 'NEXTCLOUD_DATA_FILE', config_path)
    monkeypatch.setattr(nextcloud, 'SYNC_STATE_FILE', sync_state_path)
    monkeypatch.setattr(app_module, 'ACCOUNT_BALANCE_FILE', balance_path)
    monkeypatch.setattr(app_module, 'FUNDS_FILE', funds_path)
    monkeypatch.setattr(app_module, 'BUDGET_FILE', budget_path)
    monkeypatch.setattr(app_module, 'BUDGET_HISTORY_FILE', history_path)
    monkeypatch.setattr(app_module, 'NEXTCLOUD_DATA_FILE', config_path)
    monkeypatch.setattr(settings_ui, 'ping_nextcloud_server', lambda _data: (True, ''))

    first_run = request.node.get_closest_marker('first_run') is not None
    if not first_run:
        config_path.write_text('{}', encoding='utf-8')
        balance_path.write_text('5000', encoding='utf-8')
        seed_funds = request.node.get_closest_marker('seed_funds')
        funds_path.write_text(
            json.dumps(seed_funds.args[0] if seed_funds else []), encoding='utf-8'
        )
        budget_path.write_text('[]', encoding='utf-8')

    page = FakePage()
    app = app_module.SavingsFundsApp(page)
    sync_requests = []
    app._sync_file_in_background = sync_requests.append

    if not first_run:
        await app.perform_nextcloud_sync()
        app.load_account_balance_and_funds()

    yield SimpleNamespace(
        app=app,
        page=page,
        paths={
            'balance': balance_path,
            'funds': funds_path,
            'budget': budget_path,
            'history': history_path,
            'nextcloud': config_path,
            'sync_state': sync_state_path,
        },
        sync_requests=sync_requests,
    )
