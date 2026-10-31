"""Headless UI test fixture with an isolated SQLite database and no network."""

import os
import tempfile
from types import SimpleNamespace

import pytest_asyncio
from ui_helpers import FakePage

os.environ.setdefault(
    'FLET_APP_STORAGE_DATA', tempfile.mkdtemp(prefix='savings-funds-tests-')
)


def _seed_funds(store, entries):
    from datetime import datetime

    from fund import Fund

    funds = []
    for entry in entries:
        target_date = entry.get('target_date')
        if target_date in (None, '', 'None'):
            target_date = None
        else:
            target_date = datetime.strptime(target_date, '%m/%d/%Y')
        funds.append(
            Fund(
                entry['name'],
                entry['target'],
                entry.get('balance', 0),
                target_date=target_date,
                recurring_transfer=entry.get('recurring_transfer', 0),
                due_day=entry.get('due_day', 31),
                kind=entry.get('kind', 'savings_goal'),
                priority=entry.get('priority', 0),
            )
        )
    store.replace_funds(funds)


@pytest_asyncio.fixture
async def headless_app(tmp_path, monkeypatch, request):
    """Run the real app and Flet control tree without a Flutter host."""
    import app as app_module
    import ledger
    import ui.settings as settings_ui

    ledger_path = tmp_path / 'ledger.db'
    monkeypatch.setattr(ledger, 'LEDGER_DB', ledger_path)
    monkeypatch.setattr(settings_ui, 'ping_nextcloud_server', lambda _data: (True, ''))

    first_run = request.node.get_closest_marker('first_run') is not None
    if not first_run:
        store = ledger.Ledger(ledger_path)
        store.set_meta('nextcloud_prompted', '1')
        store.add_account('Savings', 'savings', '5000')
        store.set_setting('account_balance_set', '1')
        seed_funds = request.node.get_closest_marker('seed_funds')
        if seed_funds is not None:
            _seed_funds(store, seed_funds.args[0])

    page = FakePage()
    app = app_module.SavingsFundsApp(page)

    if not first_run:
        await app.perform_nextcloud_sync()
        app.load_account_balance_and_funds()
        # UI fixtures must never attempt a real WebDAV request.
        app._sync_ready = False

    yield SimpleNamespace(
        app=app,
        page=page,
        paths={'ledger': ledger_path},
    )
