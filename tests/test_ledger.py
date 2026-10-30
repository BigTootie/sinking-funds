import json
from datetime import date
from decimal import Decimal

import pytest

from ledger import Ledger, LedgerError, minor_to_money, money_to_minor


def make_ledger(tmp_path):
    return Ledger(tmp_path / 'ledger.db')


def test_money_round_trips_minor_units():
    assert money_to_minor('12.346') == 1235
    assert money_to_minor('-1.006') == -101
    assert minor_to_money(-101) == Decimal('-1.01')


def test_account_balances_are_derived_from_opening_and_transactions(tmp_path):
    ledger = make_ledger(tmp_path)
    checking = ledger.add_account('Checking', 'checking', '100.00')
    ledger.add_account('Savings', 'savings', '50.00')

    ledger.add_transaction(checking.id, date(2026, 10, 1), 'Paycheck', amount='2000')
    ledger.add_transaction(
        checking.id, date(2026, 10, 2), 'Groceries', amount='-125.50'
    )

    accounts = {account.name: account for account in ledger.list_accounts()}
    assert accounts['Checking'].balance == Decimal('1974.50')
    assert accounts['Savings'].balance == Decimal('50.00')
    assert ledger.total_balance() == Decimal('2024.50')


def test_transfer_moves_money_without_changing_total(tmp_path):
    ledger = make_ledger(tmp_path)
    checking = ledger.add_account('Checking', 'checking', '1000')
    savings = ledger.add_account('Savings', 'savings', '0')

    ledger.add_transfer(checking.id, savings.id, '2026-10-03', '250', 'Emergency')

    accounts = {account.name: account for account in ledger.list_accounts()}
    assert accounts['Checking'].balance == Decimal('750.00')
    assert accounts['Savings'].balance == Decimal('250.00')
    assert ledger.total_balance() == Decimal('1000.00')
    assert len([t for t in ledger.list_transactions() if t.transfer_id]) == 2


def test_transaction_update_search_filter_and_delete_undo(tmp_path):
    ledger = make_ledger(tmp_path)
    account = ledger.add_account('Checking')
    transaction_id = ledger.add_transaction(
        account.id, '2026-10-04', 'Coffee Shop', 'Morning', '-4.50', 'Food'
    )

    assert ledger.list_transactions(search='coffee')[0].payee == 'Coffee Shop'
    assert ledger.list_transactions(cleared=False)[0].id == transaction_id

    ledger.update_transaction(
        transaction_id,
        account.id,
        '2026-10-05',
        'Coffee Shop',
        'Morning',
        '-5.00',
        'Food',
        True,
    )
    updated = ledger.list_transactions(cleared=True)[0]
    assert updated.date == '2026-10-05'
    assert updated.amount == Decimal('-5.00')

    deleted = ledger.delete_transaction(transaction_id)
    assert ledger.list_transactions() == []
    ledger.restore_transactions(deleted)
    assert ledger.list_transactions()[0].id == transaction_id


def test_transfer_delete_removes_both_legs(tmp_path):
    ledger = make_ledger(tmp_path)
    checking = ledger.add_account('Checking')
    savings = ledger.add_account('Savings')
    ledger.add_transfer(checking.id, savings.id, '2026-10-06', '25')

    transaction = ledger.list_transactions()[0]
    ledger.delete_transaction(transaction.id)
    assert ledger.list_transactions() == []


def test_ledger_export_import_round_trip(tmp_path):
    ledger = make_ledger(tmp_path)
    account = ledger.add_account('Checking', opening_balance='100')
    ledger.add_transaction(account.id, '2026-10-07', 'Store', amount='-10')
    export = ledger.export_json(tmp_path / 'ledger.json')
    csv_export = ledger.export_csv(tmp_path / 'transactions.csv')

    assert 'transactions' in json.loads(export.read_text(encoding='utf-8'))
    assert 'payee' in csv_export.read_text(encoding='utf-8')

    other = make_ledger(tmp_path / 'other')
    other.import_json(export)
    assert other.total_balance() == Decimal('90.00')
    assert other.list_transactions(search='Store')[0].payee == 'Store'


def test_invalid_account_and_transfer_are_rejected(tmp_path):
    ledger = make_ledger(tmp_path)
    account = ledger.add_account('Checking')
    with pytest.raises(LedgerError):
        ledger.add_transaction('missing', '2026-10-01', 'Store', amount='-1')
    with pytest.raises(LedgerError):
        ledger.add_transfer(account.id, account.id, '2026-10-01', '10')
    with pytest.raises(LedgerError):
        ledger.add_transfer(account.id, 'missing', '2026-10-01', '10')
    assert ledger.list_transactions() == []


def test_failed_import_rolls_back_existing_ledger(tmp_path):
    ledger = make_ledger(tmp_path)
    account = ledger.add_account('Checking', opening_balance='100')
    ledger.add_transaction(account.id, '2026-10-08', 'Store', amount='-10')
    before = ledger.total_balance()
    bad_export = tmp_path / 'bad.json'
    bad_export.write_text(
        json.dumps(
            {
                'version': 1,
                'accounts': [],
                'transactions': [{'id': 'broken'}],
                'funds': [],
            }
        ),
        encoding='utf-8',
    )

    with pytest.raises(KeyError):
        ledger.import_json(bad_export)

    assert ledger.total_balance() == before
    assert ledger.list_transactions(search='Store')[0].payee == 'Store'
