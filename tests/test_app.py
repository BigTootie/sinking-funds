"""Application startup, restore, and synchronization coordination tests."""

from datetime import datetime
from decimal import Decimal

import pytest
from ui_helpers import FakePage

import app as app_module
import data
import ledger
from budget import BudgetCategory, BudgetState, current_period
from fund import Fund
from sync.engine import SyncOutcome


def make_app(monkeypatch, tmp_path, *, prompted=True):
    ledger_path = tmp_path / 'ledger.db'
    monkeypatch.setattr(ledger, 'LEDGER_DB', ledger_path)
    store = ledger.Ledger(ledger_path)
    store.set_meta('nextcloud_prompted', '1' if prompted else '0')
    store.add_account('Savings', 'savings', '1234.50')
    store.set_setting('account_balance_set', '1')
    store.replace_funds([Fund('Emergency', 5000, 750)])
    store.replace_budget(
        '2026-10', [BudgetCategory('Rent', 1200, 1200, group='Housing')]
    )
    app = app_module.SavingsFundsApp(FakePage())
    return app, ledger_path


@pytest.mark.asyncio
async def test_startup_loads_the_single_database_and_initializes_dashboard(
    monkeypatch, tmp_path
):
    app, ledger_path = make_app(monkeypatch, tmp_path)

    await app.perform_nextcloud_sync()
    app.load_account_balance_and_funds()

    assert app.account_balance == Decimal('1234.50')
    assert [fund.name for fund in app.funds] == ['Emergency']
    assert [category.name for category in app.budget_categories] == ['Rent']
    assert app.dashboard is not None
    assert ledger_path.is_file()
    assert not (tmp_path / 'balance.txt').exists()
    assert not (tmp_path / 'funds.json').exists()


@pytest.mark.asyncio
async def test_nextcloud_setup_timeout_does_not_block_local_startup(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(app_module, 'NEXTCLOUD_SETUP_TIMEOUT_SECONDS', 0.01)
    app, _ledger_path = make_app(monkeypatch, tmp_path, prompted=False)
    app.ledger.set_meta('nextcloud_prompted', '0')

    await app.perform_nextcloud_sync()

    assert 'timed out' in app.startup_notice


def test_rollover_restores_memory_when_the_budget_cannot_be_saved(
    monkeypatch, tmp_path
):
    app, _ledger_path = make_app(monkeypatch, tmp_path)
    app.budget_state = BudgetState([BudgetCategory('Groceries', 1200, 350)], '2026-09')
    app.budget_categories = app.budget_state.categories

    def fail_to_save(_state, _ledger):
        raise OSError('disk full')

    monkeypatch.setattr(app_module, 'save_budget', fail_to_save)

    assert app._rollover_budget_if_needed(datetime(2026, 10, 2)) is False

    assert app.budget_state.period == '2026-09'
    assert app.budget_state.categories[0].spent == Decimal('350.00')
    assert any('Could not save budget plan' in error for error in app.startup_errors)


def test_restore_reloads_the_running_app_state(monkeypatch, tmp_path):
    app, _ledger_path = make_app(monkeypatch, tmp_path)
    app.load_account_balance_and_funds()
    backup = data.backup_database(app.ledger)

    app.ledger.replace_funds([Fund('Changed', 100)])
    app._perform_restore(backup)

    assert [fund.name for fund in app.funds] == ['Emergency']
    assert [category.name for category in app.budget_categories] == ['Rent']
    assert app.budget_state.categories is app.budget_categories


def test_initialize_dashboard_forces_the_current_budget_month(monkeypatch, tmp_path):
    app, _ledger_path = make_app(monkeypatch, tmp_path)
    app.load_account_balance_and_funds()

    app.budget_state.period = '2027-03'
    app.initialize_dashboard()

    assert app.budget_state.period == current_period()
    assert app.budget_dashboard.period == current_period()


@pytest.mark.asyncio
async def test_manual_sync_uses_the_sync_engine_and_reports_status(
    monkeypatch, tmp_path
):
    app, _ledger_path = make_app(monkeypatch, tmp_path)
    app.load_account_balance_and_funds()
    app.nextcloud_sync_data = {
        'base_url': 'cloud.example.test',
        'username': 'test',
        'password': 'test-password',
        'data_path': 'Savings',
    }

    class Engine:
        def sync(self):
            app.ledger.set_sync_state('last_sync', '2026-10-30T12:00:00')
            return SyncOutcome(applied=2, last_sync='2026-10-30T12:00:00')

    app.sync_engine = Engine()
    await app._manual_sync()

    assert app.ledger.get_sync_state('last_sync') == '2026-10-30T12:00:00'
    assert any(
        'Sync complete' in getattr(dialog, 'content', None).value
        for dialog in app.page.dialogs
        if hasattr(dialog, 'content')
    )


@pytest.mark.asyncio
async def test_local_changes_schedule_a_background_sync(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, 'SYNC_DEBOUNCE_SECONDS', 0)
    app, _ledger_path = make_app(monkeypatch, tmp_path)
    app.load_account_balance_and_funds()
    app.nextcloud_sync_data = {
        'base_url': 'cloud.example.test',
        'username': 'test',
        'password': 'test-password',
        'data_path': 'Savings',
    }
    calls = []

    class Engine:
        crypto = None

        def sync(self):
            calls.append(True)
            app.ledger.set_sync_state('last_sync', '2026-10-30T12:00:00')
            return SyncOutcome(applied=0, last_sync='2026-10-30T12:00:00')

    app.sync_engine = Engine()
    app._sync_ready = True
    app._on_sync_op()
    assert app._sync_task is not None
    await app._sync_task

    assert calls == [True]


def test_conflict_review_can_accept_the_remote_value(monkeypatch, tmp_path):
    from sync.protocol import seal

    app, _ledger_path = make_app(monkeypatch, tmp_path)
    app.load_account_balance_and_funds()
    account = app.ledger.list_accounts()[0]
    before = app.ledger.sync_snapshot()['accounts'][account.id]

    app.ledger.update_account(account.id, 'Local name', 'savings')
    after = dict(before, name='Remote name')
    remote = seal(
        {
            'id': 'remote-conflict-op',
            'device_id': 'other-device',
            'lamport': 1,
            'entity': 'accounts',
            'entity_id': account.id,
            'op': 'upsert',
            'payload': {
                'changes': [
                    {
                        'table': 'accounts',
                        'key': [account.id],
                        'before': before,
                        'after': after,
                    }
                ]
            },
            'created_at': '2026-10-30T12:00:00',
        }
    )
    assert app.ledger.apply_remote_operation(remote) == 'conflict'
    conflict = app.ledger.list_sync_conflicts()[0]

    app._show_sync_conflicts()
    from ui_helpers import click, find_by_key

    find_by_key(app.page, f'sync-use-remote-{conflict["id"]}')
    import asyncio

    asyncio.run(click(app.page, f'sync-use-remote-{conflict["id"]}'))
    assert [item.name for item in app.ledger.list_accounts()] == ['Remote name']


@pytest.mark.asyncio
async def test_nextcloud_password_is_loaded_from_the_local_database_on_restart(
    monkeypatch, tmp_path
):
    import json

    import nextcloud

    app, _ledger_path = make_app(monkeypatch, tmp_path)
    document = {
        'base_url': 'cloud.example.test',
        'username': 'test-user',
        'password': 'test-password',
        'data_path': 'Savings',
    }
    app.ledger.set_setting('nextcloud_config', json.dumps(document))

    restarted = app_module.SavingsFundsApp(FakePage())
    await restarted.perform_nextcloud_sync()

    assert restarted.nextcloud_sync_data == document
    assert restarted.sync_engine is not None
    assert nextcloud.get_sync_key(restarted.ledger) is None
