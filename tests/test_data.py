import json
import os
import stat
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

import data
from budget import BudgetCategory, BudgetState, current_period
from fund import Fund


def test_funds_round_trip_through_json(tmp_path, monkeypatch):
    funds_path = tmp_path / 'funds.json'
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)
    source = [Fund('Home repair', 2500, 675, datetime(2027, 5, 1), 125)]

    assert data.save_funds_to_json(source) is True
    document = json.loads(funds_path.read_text(encoding='utf-8'))
    restored = data.load_funds_from_json()

    assert document['version'] == data.SCHEMA_VERSION
    assert document['funds'][0]['name'] == 'Home repair'
    assert document['funds'][0]['id'] == source[0].id
    assert document['funds'][0]['target'] == '2500.00'
    assert document['funds'][0]['balance'] == '675.00'
    assert restored[0].name == 'Home repair'
    assert restored[0].target == 2500
    assert restored[0].balance == 675
    assert restored[0].target_date == datetime(2027, 5, 1)
    assert restored[0].recurring_transfer == 125


def test_missing_funds_file_starts_with_empty_funds(tmp_path, monkeypatch):
    funds_path = tmp_path / 'funds.json'
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)

    assert data.load_funds_from_json() == []
    assert not funds_path.exists()


def test_fund_loading_uses_named_fields_and_defaults_optional_contribution(
    tmp_path, monkeypatch
):
    funds_path = tmp_path / 'funds.json'
    funds_path.write_text(
        '[{"balance":50,"target":100,"name":"Car","target_date":"None"}]',
        encoding='utf-8',
    )
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)

    fund = data.load_funds_from_json()[0]

    assert (fund.name, fund.target, fund.balance, fund.recurring_transfer) == (
        'Car',
        100,
        50,
        0,
    )
    assert fund.id


def test_balance_round_trip_and_missing_balance_sentinel(tmp_path, monkeypatch):
    balance_path = tmp_path / 'balance.txt'
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', balance_path)

    assert data.load_balance_from_txt() is None
    assert data.save_balance_to_txt(321.75) is True
    assert balance_path.read_text(encoding='utf-8') == '321.75'
    assert data.load_balance_from_txt() == Decimal('321.75')
    assert data.save_balance_to_txt(0) is True
    assert data.load_balance_from_txt() == Decimal('0.00')


def test_legacy_negative_balance_sentinel_is_treated_as_unset(tmp_path, monkeypatch):
    balance_path = tmp_path / 'balance.txt'
    balance_path.write_text('-1', encoding='utf-8')
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', balance_path)

    assert data.load_balance_from_txt() is None


def test_corrupt_balance_is_preserved_and_reported(tmp_path, monkeypatch):
    balance_path = tmp_path / 'balance.txt'
    balance_path.write_text('not money', encoding='utf-8')
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', balance_path)

    with pytest.raises(data.DataCorruptionError) as error:
        data.load_balance_from_txt()

    assert error.value.quarantine_path is not None
    assert error.value.quarantine_path.exists()
    assert not balance_path.exists()
    assert error.value.quarantine_path.read_text(encoding='utf-8') == 'not money'


def test_budget_categories_round_trip_through_json(tmp_path, monkeypatch):
    budget_path = tmp_path / 'budget.json'
    monkeypatch.setattr(data, 'BUDGET_FILE', budget_path)
    state = BudgetState([BudgetCategory('Groceries', 1200, 350)], '2026-10')

    assert data.save_budget_to_json(state) is True
    document = json.loads(budget_path.read_text(encoding='utf-8'))
    restored = data.load_budget_from_json()

    assert document['version'] == data.SCHEMA_VERSION
    assert document['period'] == '2026-10'
    assert restored == state


def test_generated_budget_expense_source_round_trips(tmp_path, monkeypatch):
    budget_path = tmp_path / 'budget.json'
    monkeypatch.setattr(data, 'BUDGET_FILE', budget_path)
    fund = Fund('Emergency', 1000)
    generated = BudgetCategory('Emergency contribution', 125, 0, 'expense', fund.id)
    state = BudgetState([generated], '2026-10')

    data.save_budget_to_json(state)
    restored = data.load_budget_from_json([fund])

    assert restored.categories == [generated]


def test_legacy_budget_data_defaults_to_expense_and_resolves_fund_name(
    tmp_path, monkeypatch
):
    budget_path = tmp_path / 'budget.json'
    budget_path.write_text(
        '[{"name":"Emergency contribution","budgeted":100,"spent":25,'
        '"source_fund":"Emergency"}]',
        encoding='utf-8',
    )
    monkeypatch.setattr(data, 'BUDGET_FILE', budget_path)
    fund = Fund('Emergency', 1000)

    restored = data.load_budget_from_json([fund])

    assert restored.period == current_period()
    assert restored.categories[0].kind == 'expense'
    assert restored.categories[0].source_fund_id == fund.id


def test_unknown_generated_source_id_is_preserved_when_funds_are_unavailable(
    tmp_path, monkeypatch
):
    budget_path = tmp_path / 'budget.json'
    budget_path.write_text(
        json.dumps(
            {
                'version': 2,
                'period': '2026-10',
                'categories': [
                    {
                        'name': 'Emergency contribution',
                        'budgeted': 100,
                        'spent': 0,
                        'kind': 'expense',
                        'source_fund_id': 'missing-fund-id',
                    }
                ],
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(data, 'BUDGET_FILE', budget_path)

    restored = data.load_budget_from_json(None)

    assert restored.categories[0].source_fund_id == 'missing-fund-id'


def test_corrupt_funds_file_is_quarantined_instead_of_silently_emptied(
    tmp_path, monkeypatch
):
    funds_path = tmp_path / 'funds.json'
    funds_path.write_text('[{"name": "Broken"', encoding='utf-8')
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)

    with pytest.raises(data.DataCorruptionError) as error:
        data.load_funds_from_json()

    assert error.value.quarantine_path is not None
    assert error.value.quarantine_path.exists()
    assert not funds_path.exists()


def test_unchanged_writes_are_skipped_and_changed_writes_create_backups(
    tmp_path, monkeypatch
):
    funds_path = tmp_path / 'funds.json'
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)
    funds = [Fund('Car', 1000)]

    assert data.save_funds_to_json(funds) is True
    assert data.save_funds_to_json(funds) is False

    funds[0].set_balance(500)
    assert data.save_funds_to_json(funds) is True
    backups = list((tmp_path / 'backups').glob('funds-*.json.bak'))
    assert backups


def test_budget_rollover_archives_spending_and_resets_current_month(
    tmp_path, monkeypatch
):
    budget_path = tmp_path / 'budget.json'
    history_path = tmp_path / 'budget_history.json'
    monkeypatch.setattr(data, 'BUDGET_FILE', budget_path)
    monkeypatch.setattr(data, 'BUDGET_HISTORY_FILE', history_path)
    state = BudgetState([BudgetCategory('Groceries', 1200, 350)], '2026-09')

    assert data.rollover_budget(state, datetime(2026, 10, 2)) is True

    assert state.period == '2026-10'
    assert state.categories[0].spent == 0
    history = data.load_budget_history()
    assert history[-1]['period'] == '2026-09'
    assert history[-1]['categories'][0]['spent'] == '350.00'


def test_budget_rollover_is_a_noop_within_the_same_month(tmp_path, monkeypatch):
    history_path = tmp_path / 'budget_history.json'
    monkeypatch.setattr(data, 'BUDGET_HISTORY_FILE', history_path)
    state = BudgetState([BudgetCategory('Groceries', 1200, 350)], '2026-10')

    assert data.rollover_budget(state, datetime(2026, 10, 2)) is False
    assert not history_path.exists()


def test_manual_budget_reset_archives_even_within_the_same_month(tmp_path, monkeypatch):
    history_path = tmp_path / 'budget_history.json'
    monkeypatch.setattr(data, 'BUDGET_HISTORY_FILE', history_path)
    state = BudgetState([BudgetCategory('Groceries', 1200, 350)], '2026-10')

    assert data.reset_budget_period(state, datetime(2026, 10, 20)) is True

    assert state.categories[0].spent == 0
    assert data.load_budget_history()[-1]['period'] == '2026-10'


def test_repeated_reset_replaces_the_same_period_snapshot(tmp_path, monkeypatch):
    history_path = tmp_path / 'budget_history.json'
    monkeypatch.setattr(data, 'BUDGET_HISTORY_FILE', history_path)
    state = BudgetState([BudgetCategory('Groceries', 1200, 350)], '2026-10')

    data.reset_budget_period(state, datetime(2026, 10, 20))
    state.categories[0].spent = Decimal('99.00')
    data.reset_budget_period(state, datetime(2026, 10, 21))

    history = data.load_budget_history()
    assert len(history) == 1
    assert history[0]['period'] == '2026-10'
    assert history[0]['categories'][0]['spent'] == '99.00'


def test_rollover_never_moves_a_newer_budget_backwards(tmp_path, monkeypatch):
    history_path = tmp_path / 'budget_history.json'
    monkeypatch.setattr(data, 'BUDGET_HISTORY_FILE', history_path)
    state = BudgetState([BudgetCategory('Groceries', 1200, 350)], '2026-11')

    assert data.rollover_budget(state, datetime(2026, 10, 2)) is False

    assert state.period == '2026-11'
    assert state.categories[0].spent == 350
    assert not history_path.exists()


def test_version_two_money_is_migrated_and_saved_as_strings(tmp_path, monkeypatch):
    funds_path = tmp_path / 'funds.json'
    funds_path.write_text(
        json.dumps(
            {
                'version': 2,
                'funds': [
                    {
                        'id': 'fund-id',
                        'name': 'Car',
                        'target': 1000.0,
                        'balance': 125.5,
                        'target_date': 'None',
                        'recurring_transfer': 50.0,
                    }
                ],
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)

    funds = data.load_funds_from_json()
    assert funds[0].target == Decimal('1000.00')
    assert funds[0].balance == Decimal('125.50')

    data.save_funds_to_json(funds)
    document = json.loads(funds_path.read_text(encoding='utf-8'))
    assert document['version'] == data.SCHEMA_VERSION == 3
    assert document['funds'][0]['balance'] == '125.50'


def test_newer_schema_is_preserved_instead_of_quarantined(tmp_path, monkeypatch):
    funds_path = tmp_path / 'funds.json'
    funds_path.write_text(
        json.dumps(
            {
                'version': data.SCHEMA_VERSION + 1,
                'funds': [],
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)

    with pytest.raises(data.UnsupportedSchemaError):
        data.load_funds_from_json()

    assert funds_path.exists()
    assert not list(tmp_path.glob('funds.json.corrupt-*'))


def test_duplicate_fund_ids_quarantine_instead_of_orphaning_budget_links(
    tmp_path, monkeypatch
):
    funds_path = tmp_path / 'funds.json'
    funds_path.write_text(
        json.dumps(
            {
                'version': 2,
                'funds': [
                    {'id': 'same-id', 'name': 'One', 'target': 10, 'balance': 0},
                    {'id': 'same-id', 'name': 'Two', 'target': 10, 'balance': 0},
                ],
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)

    with pytest.raises(data.DataCorruptionError) as error:
        data.load_funds_from_json()

    assert error.value.quarantine_path is not None
    assert not funds_path.exists()


def test_duplicate_budget_ids_quarantine_instead_of_silently_changing_them(
    tmp_path, monkeypatch
):
    budget_path = tmp_path / 'budget.json'
    budget_path.write_text(
        json.dumps(
            {
                'version': 2,
                'period': '2026-10',
                'categories': [
                    {'id': 'same-id', 'name': 'One', 'budgeted': 10, 'spent': 0},
                    {'id': 'same-id', 'name': 'Two', 'budgeted': 10, 'spent': 0},
                ],
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(data, 'BUDGET_FILE', budget_path)

    with pytest.raises(data.DataCorruptionError):
        data.load_budget_from_json()


def test_negative_account_balance_round_trips_as_an_overdraft(tmp_path, monkeypatch):
    balance_path = tmp_path / 'balance.txt'
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', balance_path)

    assert data.save_balance_to_txt('-25.50') is True
    assert balance_path.read_text(encoding='utf-8') == '-25.50'
    assert data.load_balance_from_txt() == Decimal('-25.50')


def test_backup_and_export_include_data_but_not_credentials(tmp_path, monkeypatch):
    paths = {
        'balance': tmp_path / 'balance.txt',
        'funds': tmp_path / 'funds.json',
        'budget': tmp_path / 'budget.json',
        'history': tmp_path / 'budget_history.json',
        'config': tmp_path / 'nextcloud_sync.json',
    }
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', paths['balance'])
    monkeypatch.setattr(data, 'FUNDS_FILE', paths['funds'])
    monkeypatch.setattr(data, 'BUDGET_FILE', paths['budget'])
    monkeypatch.setattr(data, 'BUDGET_HISTORY_FILE', paths['history'])
    for name in ('balance', 'funds', 'budget', 'history'):
        paths[name].write_text('{}', encoding='utf-8')
    paths['config'].write_text('{"password": "secret"}', encoding='utf-8')

    backup = data.backup_all_files()
    assert (backup / 'funds.json').read_text(encoding='utf-8') == '{}'
    assert not (backup / 'nextcloud_sync.json').exists()
    if os.name != 'nt':
        assert stat.S_IMODE(backup.stat().st_mode) == 0o700
        assert stat.S_IMODE((tmp_path / 'backups').stat().st_mode) == 0o700

    export = data.export_data(tmp_path / 'export.zip')
    with zipfile.ZipFile(export) as archive:
        names = set(archive.namelist())
        assert {
            'balance.txt',
            'funds.json',
            'budget.json',
            'budget_history.json',
            'manifest.json',
        } <= names
        assert 'nextcloud_sync.json' not in names
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['schema_version'] == data.SCHEMA_VERSION
        assert 'nextcloud_sync.json' in manifest['excluded']


def test_latest_full_backup_repairs_legacy_directory_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', tmp_path / 'balance.txt')
    backup = tmp_path / 'backups' / 'full-20260101-000000-000000'
    backup.mkdir(parents=True)
    (backup / 'balance.txt').write_text('100.00', encoding='utf-8')
    (backup / '.complete').write_text('complete\n', encoding='utf-8')
    if os.name != 'nt':
        backup.chmod(0o600)

    assert data.latest_full_backup() == backup
    if os.name != 'nt':
        assert stat.S_IMODE(backup.stat().st_mode) == 0o700
        assert stat.S_IMODE((backup / 'balance.txt').stat().st_mode) == 0o600


def test_restore_backup_reports_unreadable_source_file(tmp_path, monkeypatch):
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', tmp_path / 'balance.txt')
    source = tmp_path / 'backup'
    source.mkdir()
    source_file = source / 'balance.txt'
    source_file.write_text('250.00', encoding='utf-8')
    original_read_bytes = Path.read_bytes

    def read_bytes(path):
        if path == source_file:
            raise PermissionError(13, 'Permission denied', str(path))
        return original_read_bytes(path)

    monkeypatch.setattr(Path, 'read_bytes', read_bytes)

    with pytest.raises(ValueError, match='cannot read backup file'):
        data.restore_backup(source)


def test_restore_backup_validates_files_and_snapshots_current_data(
    tmp_path, monkeypatch
):
    paths = {
        'balance': tmp_path / 'balance.txt',
        'funds': tmp_path / 'funds.json',
        'budget': tmp_path / 'budget.json',
        'history': tmp_path / 'budget_history.json',
    }
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', paths['balance'])
    monkeypatch.setattr(data, 'FUNDS_FILE', paths['funds'])
    monkeypatch.setattr(data, 'BUDGET_FILE', paths['budget'])
    monkeypatch.setattr(data, 'BUDGET_HISTORY_FILE', paths['history'])
    paths['balance'].write_text('100.00', encoding='utf-8')
    paths['funds'].write_text(json.dumps({'version': 3, 'funds': []}), encoding='utf-8')

    backup = tmp_path / 'backup'
    backup.mkdir()
    (backup / 'balance.txt').write_text('250.00', encoding='utf-8')
    (backup / 'funds.json').write_text(
        json.dumps({'version': 3, 'funds': []}), encoding='utf-8'
    )

    restored = data.restore_backup(backup)

    assert set(restored) == {paths['balance'], paths['funds']}
    assert paths['balance'].read_text(encoding='utf-8') == '250.00'
    safety = data.latest_full_backup()
    assert safety is not None
    assert (safety / 'balance.txt').read_text(encoding='utf-8') == '100.00'


def test_restore_backup_rejects_invalid_files_without_changing_current_data(
    tmp_path, monkeypatch
):
    paths = {
        'balance': tmp_path / 'balance.txt',
        'funds': tmp_path / 'funds.json',
        'budget': tmp_path / 'budget.json',
        'history': tmp_path / 'budget_history.json',
    }
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', paths['balance'])
    monkeypatch.setattr(data, 'FUNDS_FILE', paths['funds'])
    monkeypatch.setattr(data, 'BUDGET_FILE', paths['budget'])
    monkeypatch.setattr(data, 'BUDGET_HISTORY_FILE', paths['history'])
    paths['balance'].write_text('100.00', encoding='utf-8')

    backup = tmp_path / 'backup'
    backup.mkdir()
    (backup / 'balance.txt').write_text('250.00', encoding='utf-8')
    (backup / 'funds.json').write_text('not json', encoding='utf-8')

    with pytest.raises(ValueError, match='invalid funds.json'):
        data.restore_backup(backup)

    assert paths['balance'].read_text(encoding='utf-8') == '100.00'
    assert data.latest_full_backup() is None
