"""Application startup and background upload coordination tests."""

import asyncio
import json
from datetime import datetime
from decimal import Decimal

import pytest

import app as app_module
import data
import ledger
import nextcloud
from budget import BudgetCategory, BudgetState
from fund import Fund
from nextcloud import SyncConflictError

SYNC_DATA = {
    'base_url': 'cloud.example.test',
    'username': 'test-user',
    'password': 'test-password',
    'data_path': 'Savings',
}


class FakePage:
    """Minimal page surface used by SavingsFundsApp outside a Flutter host."""

    def __init__(self):
        self.width = 800
        self.scroll = None
        self.navigation_bar = None
        self.controls = []
        self.dialogs = []

    def add(self, *controls):
        self.controls.extend(controls)

    def update(self):
        pass

    def show_dialog(self, control):
        self.dialogs.append(control)

    def pop_dialog(self):
        if self.dialogs:
            self.dialogs.pop()

    def run_task(self, handler, *args, **kwargs):
        return asyncio.create_task(handler(*args, **kwargs))


def patch_app_paths(monkeypatch, tmp_path):
    paths = {
        'balance': tmp_path / 'balance.txt',
        'funds': tmp_path / 'funds.json',
        'budget': tmp_path / 'budget.json',
        'history': tmp_path / 'budget_history.json',
        'config': tmp_path / 'nextcloud_sync.json',
        'state': tmp_path / 'sync_state.json',
        'database': tmp_path / 'ledger.db',
    }
    for module in (data, nextcloud):
        monkeypatch.setattr(module, 'ACCOUNT_BALANCE_FILE', paths['balance'])
        monkeypatch.setattr(module, 'FUNDS_FILE', paths['funds'])
        monkeypatch.setattr(module, 'BUDGET_FILE', paths['budget'])
        monkeypatch.setattr(module, 'BUDGET_HISTORY_FILE', paths['history'])
    monkeypatch.setattr(ledger, 'LEDGER_DB', paths['database'])
    monkeypatch.setattr(nextcloud, 'NEXTCLOUD_DATA_FILE', paths['config'])
    monkeypatch.setattr(nextcloud, 'SYNC_STATE_FILE', paths['state'])
    return paths


def seed_local_data(paths):
    paths['balance'].write_text('1234.50', encoding='utf-8')
    paths['funds'].write_text(
        json.dumps(
            {
                'version': 2,
                'funds': [
                    {
                        'id': 'fund-id',
                        'name': 'Emergency',
                        'target': 5000,
                        'balance': 750,
                        'target_date': 'None',
                        'recurring_transfer': 0,
                    }
                ],
            }
        ),
        encoding='utf-8',
    )
    paths['budget'].write_text(
        json.dumps(
            {
                'version': 2,
                'period': '2026-10',
                'categories': [
                    {
                        'id': 'category-id',
                        'name': 'Rent',
                        'budgeted': 1200,
                        'spent': 1200,
                        'kind': 'expense',
                    }
                ],
            }
        ),
        encoding='utf-8',
    )


@pytest.mark.asyncio
async def test_startup_migrates_legacy_json_into_sqlite(monkeypatch, tmp_path):
    paths = patch_app_paths(monkeypatch, tmp_path)
    seed_local_data(paths)
    paths['config'].write_text('{}', encoding='utf-8')

    app = app_module.SavingsFundsApp(FakePage())
    app._sync_file_in_background = lambda _path: None

    await app.perform_nextcloud_sync()
    app.load_account_balance_and_funds()

    assert app.account_balance == Decimal('1234.50')
    assert [fund.name for fund in app.funds] == ['Emergency']
    assert [category.name for category in app.budget_categories] == ['Rent']
    assert app.dashboard is not None
    assert paths['database'].is_file()
    assert app.ledger.get_meta('legacy_json_migrated') == '1'
    # Legacy files are migration sources, not the runtime destination.
    assert paths['balance'].read_text(encoding='utf-8') == '1234.50'


@pytest.mark.asyncio
async def test_nextcloud_setup_timeout_does_not_block_local_startup(
    monkeypatch, tmp_path
):
    paths = patch_app_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, 'NEXTCLOUD_SETUP_TIMEOUT_SECONDS', 0.01)
    app = app_module.SavingsFundsApp(FakePage())

    await app.perform_nextcloud_sync()

    assert 'timed out' in app.startup_notice
    assert not paths['config'].exists()


def test_rollover_restores_memory_when_the_budget_cannot_be_saved(
    monkeypatch, tmp_path
):
    patch_app_paths(monkeypatch, tmp_path)
    app = app_module.SavingsFundsApp(FakePage())
    app.budget_state = BudgetState([BudgetCategory('Groceries', 1200, 350)], '2026-09')
    app.budget_categories = app.budget_state.categories

    def fail_to_save(_state, _ledger):
        raise OSError('disk full')

    monkeypatch.setattr(app_module, 'save_budget', fail_to_save)

    assert app._rollover_budget_if_needed(datetime(2026, 10, 2)) is False

    assert app.budget_state.period == '2026-09'
    assert app.budget_state.categories[0].spent == Decimal('350.00')
    assert any('Could not save budget plan' in error for error in app.startup_errors)


def test_newer_schema_disables_writes_instead_of_overwriting_the_file(
    monkeypatch, tmp_path
):
    paths = patch_app_paths(monkeypatch, tmp_path)
    seed_local_data(paths)
    paths['funds'].write_text(
        json.dumps({'version': 99, 'funds': []}), encoding='utf-8'
    )
    original = paths['funds'].read_text(encoding='utf-8')
    app = app_module.SavingsFundsApp(FakePage())

    app.load_account_balance_and_funds()

    assert app._writes_blocked is True
    assert paths['funds'].read_text(encoding='utf-8') == original
    assert any('newer than supported' in error for error in app.startup_errors)


def test_restore_reloads_the_running_app_state(monkeypatch, tmp_path):
    paths = patch_app_paths(monkeypatch, tmp_path)
    seed_local_data(paths)
    app = app_module.SavingsFundsApp(FakePage())
    app.load_account_balance_and_funds()
    backup = data.backup_database(app.ledger)

    app.ledger.replace_funds([Fund('Changed', 100, fund_id='changed-fund')])
    app._perform_restore(backup)

    assert [fund.name for fund in app.funds] == ['Emergency']
    assert [category.name for category in app.budget_categories] == ['Rent']
    assert app.budget_state.categories is app.budget_categories


@pytest.mark.asyncio
async def test_startup_imports_legacy_nextcloud_settings_without_network(
    monkeypatch, tmp_path
):
    paths = patch_app_paths(monkeypatch, tmp_path)
    seed_local_data(paths)
    paths['config'].write_text(json.dumps(SYNC_DATA), encoding='utf-8')

    def fail_network(_sync_data):
        raise AssertionError('v0.4 must not perform WebDAV synchronization')

    monkeypatch.setattr(app_module, 'sync_data_to_nextcloud', fail_network)
    app = app_module.SavingsFundsApp(FakePage())
    app._sync_file_in_background = lambda _path: None

    await app.perform_nextcloud_sync()

    stored = json.loads(app.ledger.get_setting('nextcloud_config'))
    assert stored['base_url'] == 'cloud.example.test'
    assert 'password' not in stored
    assert any('keyring' in error.lower() for error in app.startup_errors)


def worker_app():
    app = object.__new__(app_module.SavingsFundsApp)
    app.page = FakePage()
    app.nextcloud_sync_data = SYNC_DATA
    app._sync_pending = {}
    app._sync_failed = {}
    app._sync_task = None
    app.sync_errors = []
    app._show_sync_error = app.sync_errors.append
    return app


@pytest.mark.asyncio
async def test_sync_worker_uploads_pending_files_in_order(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, 'SYNC_DEBOUNCE_SECONDS', 0)
    uploaded = []
    monkeypatch.setattr(
        app_module,
        'sync_data_to_nextcloud',
        lambda path, _sync_data: uploaded.append(path.name),
    )
    app = worker_app()
    files = [tmp_path / name for name in ('funds.json', 'budget.json', 'balance.txt')]
    for file_path in files:
        file_path.write_text('{}', encoding='utf-8')
    app._sync_pending = {file_path.name: file_path for file_path in files}

    await app._sync_worker()

    assert uploaded == ['funds.json', 'budget.json', 'balance.txt']
    assert app._sync_pending == {}
    assert app._sync_failed == {}
    assert app._sync_task is None


@pytest.mark.asyncio
async def test_sync_worker_requeues_failed_batch_and_retries_on_next_change(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(app_module, 'SYNC_DEBOUNCE_SECONDS', 0)
    files = {
        name: tmp_path / name
        for name in ('funds.json', 'budget.json', 'budget_history.json', 'balance.txt')
    }
    for file_path in files.values():
        file_path.write_text('{}', encoding='utf-8')

    uploaded = []

    def failing_upload(path, _sync_data):
        if path.name == 'funds.json':
            raise nextcloud.SyncError('network down')
        uploaded.append(path.name)

    monkeypatch.setattr(app_module, 'sync_data_to_nextcloud', failing_upload)
    app = worker_app()
    app._sync_pending = {
        name: files[name]
        for name in ('funds.json', 'budget.json', 'budget_history.json')
    }

    await app._sync_worker()

    assert uploaded == []
    assert set(app._sync_failed) == {'funds.json', 'budget.json', 'budget_history.json'}
    assert app._sync_pending == {}
    assert len(app.sync_errors) == 1
    assert 'next change' in app.sync_errors[0]

    monkeypatch.setattr(
        app_module,
        'sync_data_to_nextcloud',
        lambda path, _sync_data: uploaded.append(path.name),
    )
    app._sync_file_in_background(files['balance.txt'])
    await app._sync_task

    assert uploaded == [
        'balance.txt',
        'funds.json',
        'budget.json',
        'budget_history.json',
    ]
    assert app._sync_failed == {}
    assert app._sync_pending == {}


@pytest.mark.asyncio
async def test_sync_worker_does_not_repeat_a_conflicted_upload(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, 'SYNC_DEBOUNCE_SECONDS', 0)
    files = [tmp_path / name for name in ('funds.json', 'budget.json')]
    for file_path in files:
        file_path.write_text('{}', encoding='utf-8')

    def conflict_upload(path, _sync_data):
        if path.name == 'funds.json':
            raise SyncConflictError('remote changed')
        raise AssertionError(f'unexpected upload for {path.name}')

    monkeypatch.setattr(app_module, 'sync_data_to_nextcloud', conflict_upload)
    app = worker_app()
    app._sync_pending = {file_path.name: file_path for file_path in files}

    await app._sync_worker()

    assert 'funds.json' not in app._sync_failed
    assert set(app._sync_failed) == {'budget.json'}
    assert app._sync_pending == {}
    assert app.sync_errors == ['remote changed']


def test_initialize_dashboard_forces_the_current_budget_month(monkeypatch, tmp_path):
    paths = patch_app_paths(monkeypatch, tmp_path)
    seed_local_data(paths)
    paths['config'].write_text('{}', encoding='utf-8')
    app = app_module.SavingsFundsApp(FakePage())
    app.load_account_balance_and_funds()

    app.budget_state.period = '2027-03'
    app.initialize_dashboard()

    from budget import current_period

    assert app.budget_state.period == current_period()
    assert app.budget_dashboard.period == current_period()
