"""Tests for database backups, exports, and budget model bridges."""

from datetime import datetime
from decimal import Decimal

import pytest

import data
from budget import BudgetCategory, BudgetState
from fund import Fund
from ledger import Ledger


def make_ledger(tmp_path):
    return Ledger(tmp_path / 'ledger.db')


def test_database_backup_restore_and_export_round_trip(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.add_account('Checking', 'checking', '500')
    ledger.replace_funds([Fund('Emergency', 1000, 100)])

    backup = data.backup_database(ledger)
    assert backup.is_file()
    assert data.latest_database_backup(ledger) == backup

    ledger.replace_funds([Fund('Changed', 100, 50)])
    safety = data.restore_database(backup, ledger)
    assert safety.is_file()
    assert [fund.name for fund in ledger.list_funds()] == ['Emergency']

    exported = data.export_database(tmp_path / 'export.db', ledger)
    assert exported.is_file()
    restored = Ledger(tmp_path / 'restored.db')
    data.restore_database(exported, restored)
    assert [fund.name for fund in restored.list_funds()] == ['Emergency']


def test_database_backups_are_pruned_to_the_limit(tmp_path, monkeypatch):
    ledger = make_ledger(tmp_path)
    monkeypatch.setattr(data, 'BACKUP_LIMIT', 2)
    for _ in range(3):
        data.backup_database(ledger)

    backups = sorted((tmp_path / 'backups').glob('database-*.db'))
    assert len(backups) == 2


def test_restore_rejects_an_invalid_database(tmp_path):
    ledger = make_ledger(tmp_path)
    broken = tmp_path / 'broken.db'
    broken.write_bytes(b'not sqlite')

    with pytest.raises((ValueError, OSError)):
        data.restore_database(broken, ledger)


def test_rollover_archives_once_and_never_moves_backwards(tmp_path):
    ledger = make_ledger(tmp_path)
    state = BudgetState([BudgetCategory('Groceries', 300, 50)], '2026-09')

    assert data.rollover_budget(state, datetime(2026, 10, 2), ledger) is True
    assert state.period == '2026-10'
    assert state.categories[0].spent == Decimal('0.00')
    assert data.rollover_budget(state, datetime(2026, 10, 3), ledger) is False
    assert data.rollover_budget(state, datetime(2026, 9, 3), ledger) is False
    assert [item['period'] for item in ledger.list_budget_history()] == ['2026-09']


def test_copy_plan_forward_preserves_plan_and_clears_actuals(tmp_path):
    ledger = make_ledger(tmp_path)
    source = BudgetState(
        [BudgetCategory('Rent', 1200, 1200, group='Housing')], '2026-10'
    )
    ledger.replace_budget(source.period, source.categories)

    copied = data.copy_plan_forward(source, '2026-11', ledger)

    assert copied.period == '2026-11'
    assert copied.categories[0].budgeted == Decimal('1200.00')
    assert copied.categories[0].spent == Decimal('0.00')
    assert copied.categories[0].group == 'Housing'
