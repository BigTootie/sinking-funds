"""v0.4 storage, budget, and fund-contribution foundation tests."""

import json
from datetime import date
from decimal import Decimal

import pytest

import data
from budget import BudgetCategory, BudgetState
from fund import Fund, due_date_for_period
from ledger import Ledger, LedgerError, money_to_minor


def make_ledger(tmp_path):
    return Ledger(tmp_path / 'ledger.db')


def test_schema_has_migration_metadata_and_single_database_tables(tmp_path):
    ledger = make_ledger(tmp_path)

    assert ledger.get_meta('schema_version') == '2'
    assert ledger.get_meta('device_id')
    assert [row['version'] for row in ledger.get_migrations()] == [1, 2]
    with ledger._connect() as connection:
        assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {
        'accounts',
        'transactions',
        'funds',
        'category_groups',
        'budget_categories',
        'budget_allocations',
        'budget_history',
        'fund_contributions',
        'settings',
        'sync_ops',
    } <= tables


def test_json_migration_imports_funds_budget_history_and_settings_once(
    tmp_path, monkeypatch
):
    ledger = make_ledger(tmp_path)
    funds_path = tmp_path / 'funds.json'
    budget_path = tmp_path / 'budget.json'
    history_path = tmp_path / 'budget_history.json'
    balance_path = tmp_path / 'balance.txt'
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)
    monkeypatch.setattr(data, 'BUDGET_FILE', budget_path)
    monkeypatch.setattr(data, 'BUDGET_HISTORY_FILE', history_path)
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', balance_path)

    balance_path.write_text('500.00', encoding='utf-8')
    funds_path.write_text(
        json.dumps(
            {
                'version': 3,
                'funds': [
                    {
                        'id': 'car-fund',
                        'name': 'Car',
                        'target': '2000.00',
                        'balance': '250.00',
                        'target_date': 'None',
                        'recurring_transfer': '100.00',
                        'due_day': 15,
                        'kind': 'sinking_fund',
                        'priority': 2,
                    }
                ],
            }
        ),
        encoding='utf-8',
    )
    budget_path.write_text(
        json.dumps(
            {
                'version': 3,
                'period': '2026-10',
                'categories': [
                    {
                        'id': 'income-id',
                        'name': 'Paycheck',
                        'budgeted': '4000.00',
                        'spent': '4000.00',
                        'kind': 'income',
                    },
                    {
                        'id': 'rent-id',
                        'name': 'Rent',
                        'budgeted': '1200.00',
                        'spent': '1200.00',
                        'kind': 'expense',
                    },
                    {
                        'id': 'car-budget-id',
                        'name': 'Car contribution',
                        'budgeted': '100.00',
                        'spent': '0.00',
                        'kind': 'expense',
                        'source_fund_id': 'car-fund',
                        'group': 'Savings',
                    },
                ],
            }
        ),
        encoding='utf-8',
    )
    history_path.write_text(
        json.dumps(
            {
                'version': 3,
                'periods': [
                    {
                        'period': '2026-09',
                        'archived_at': '2026-10-01T00:00:00',
                        'categories': [],
                    }
                ],
            }
        ),
        encoding='utf-8',
    )

    assert data.migrate_legacy_json_data(ledger) is True
    assert data.migrate_legacy_json_data(ledger) is False

    funds = ledger.list_funds()
    assert len(funds) == 1
    assert funds[0].name == 'Car'
    assert funds[0].due_day == 15
    assert funds[0].kind == 'sinking_fund'
    assert funds[0].priority == 2
    assert ledger.total_balance() == Decimal('500.00')
    budget = ledger.load_budget('2026-10')
    assert budget is not None
    assert budget.to_be_budgeted == Decimal('2700.00')
    assert [category.name for category in budget.categories] == [
        'Paycheck',
        'Rent',
        'Car contribution',
    ]
    assert budget.categories[-1].group == 'Savings'
    assert ledger.list_budget_history()[0]['period'] == '2026-09'


def test_budget_groups_tbb_periods_and_copy_plan_forward(tmp_path):
    ledger = make_ledger(tmp_path)
    october = BudgetState(
        [
            BudgetCategory('Paycheck', 4000, 4000, 'income', group='Income'),
            BudgetCategory('Rent', 1200, 1200, group='Housing'),
            BudgetCategory('Car contribution', 300, 150, group='Savings'),
        ],
        '2026-10',
    )

    assert ledger.replace_budget(october.period, october.categories) is True
    assert ledger.replace_budget(october.period, october.categories) is False
    loaded = ledger.load_budget('2026-10')
    assert loaded.to_be_budgeted == Decimal('2500.00')
    assert loaded.categories[1].group == 'Housing'
    assert ledger.list_budget_periods() == ['2026-10']

    november = data.copy_plan_forward(loaded, '2026-11', ledger)
    assert all(category.spent == 0 for category in november.categories)
    assert [category.budgeted for category in november.categories] == [
        4000,
        1200,
        300,
    ]
    assert ledger.replace_budget(november.period, november.categories)
    assert ledger.list_budget_periods() == ['2026-10', '2026-11']
    assert ledger.load_budget('2026-11').to_be_budgeted == Decimal('2500.00')


def test_fund_due_day_defaults_to_month_end_and_clamps_short_months():
    assert Fund('Car', 100).due_day == 31
    assert due_date_for_period('2027-02', 31) == date(2027, 2, 28)
    assert due_date_for_period('2028-02', 31) == date(2028, 2, 29)
    assert due_date_for_period('2027-04', 31) == date(2027, 4, 30)
    assert due_date_for_period('2027-01', 15) == date(2027, 1, 15)
    with pytest.raises(ValueError):
        Fund('Car', 100, due_day=0)
    with pytest.raises(ValueError):
        Fund('Car', 100, due_day=32)


def test_recurring_contribution_auto_posts_once_and_catches_up_current_month(
    tmp_path,
):
    ledger = make_ledger(tmp_path)
    ledger.add_account('Checking', 'checking', '100.00')
    fund = Fund('Emergency', 1000, recurring_transfer=100, due_day=31)
    ledger.replace_funds([fund])

    assert ledger.auto_post_fund_contributions(today=date(2026, 10, 30)) == []
    first = ledger.auto_post_fund_contributions(today=date(2026, 10, 31))
    second = ledger.auto_post_fund_contributions(today=date(2026, 10, 31))

    assert len(first) == 1
    assert second == []
    assert first[0].period == '2026-10'
    assert first[0].budget_excluded is True
    assert ledger.get_fund(fund.id).balance == Decimal('100.00')
    assert ledger.total_balance() == Decimal('100.00')
    assert ledger.list_fund_contributions() == first
    register = ledger.list_transactions(fund_id=fund.id)
    assert register[0].budget_excluded is True
    assert register[0].affects_balance is False
    assert register[0].contribution_id == first[0].id
    # A past month is not backfilled; only the current occurrence is caught up.
    assert ledger.list_fund_contributions(period='2026-09') == []


def test_recurring_contribution_can_overdraw_a_real_destination_transfer(tmp_path):
    ledger = make_ledger(tmp_path)
    checking = ledger.add_account('Checking', 'checking', '0')
    savings = ledger.add_account('Savings', 'savings', '0')
    fund = Fund(
        'Emergency',
        1000,
        recurring_transfer=100,
        due_day=1,
        destination_account_id=savings.id,
    )
    ledger.replace_funds([fund])

    posted = ledger.auto_post_fund_contributions(today=date(2026, 10, 2), funds=[fund])

    assert len(posted) == 1
    accounts = {account.name: account for account in ledger.list_accounts()}
    assert accounts['Checking'].balance == Decimal('-100.00')
    assert accounts['Savings'].balance == Decimal('100.00')
    assert accounts['Checking'].balance < 0
    assert checking.id != savings.id
    assert ledger.total_balance() == Decimal('0.00')


def test_one_off_contributions_are_repeatable_budget_excluded_and_unbudgeted(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.add_account('Checking', 'checking', '1000')
    fund = Fund('Vacation', 1000, recurring_transfer=100)
    ledger.replace_funds([fund])
    state = BudgetState([BudgetCategory('Paycheck', 1000, 0, 'income')], '2026-10')
    ledger.replace_budget(state.period, state.categories)

    first = ledger.add_fund_contribution(fund, 75, period='2026-10')
    second = ledger.add_fund_contribution(fund, 25, period='2026-10')

    assert first is not None and second is not None
    assert first.kind == second.kind == 'one_off'
    assert first.budget_excluded and second.budget_excluded
    assert ledger.get_fund(fund.id).balance == Decimal('100.00')
    assert ledger.total_balance() == Decimal('1000.00')
    assert ledger.load_budget('2026-10').to_be_budgeted == Decimal('1000.00')
    assert len(ledger.list_fund_contributions()) == 2


def test_undo_contribution_removes_register_entry_and_restores_fund_balance(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.add_account('Checking', 'checking', '500')
    fund = Fund('Emergency', 1000, recurring_transfer=100, due_day=1)
    ledger.replace_funds([fund])
    contribution = ledger.auto_post_fund_contributions(
        today=date(2026, 10, 1), funds=[fund]
    )[0]

    assert ledger.undo_fund_contribution(contribution.id) is True
    assert ledger.undo_fund_contribution(contribution.id) is False
    assert ledger.get_fund(fund.id).balance == Decimal('0.00')
    assert ledger.list_transactions(fund_id=fund.id) == []
    assert ledger.list_fund_contributions(status='undone')[0].id == contribution.id
    # Undo is sticky for the occurrence key: the same month is not re-posted.
    assert (
        ledger.auto_post_fund_contributions(today=date(2026, 10, 1), funds=[fund]) == []
    )


def test_withdraw_fund_is_budget_excluded_and_does_not_change_bank_total(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.add_account('Checking', 'checking', '500')
    fund = Fund('Car', 1000, 300)
    ledger.replace_funds([fund])

    withdrawal = ledger.withdraw_fund(fund, 125, period='2026-10')

    assert withdrawal is not None
    assert withdrawal.amount == Decimal('-125.00')
    assert withdrawal.budget_excluded is True
    assert ledger.get_fund(fund.id).balance == Decimal('175.00')
    assert ledger.total_balance() == Decimal('500.00')


def test_settings_and_operation_log_foundation(tmp_path):
    ledger = make_ledger(tmp_path)

    ledger.set_setting('theme_mode', 'light')
    assert ledger.get_setting('theme_mode') == 'light'
    assert ledger.get_meta('theme_mode') == 'light'
    ledger.delete_setting('theme_mode')
    assert ledger.get_setting('theme_mode') is None

    operation_id = ledger.record_sync_op('fund', 'fund-id', 'update', {'name': 'Car'})
    operations = ledger.list_sync_ops()
    assert operations[0]['id'] == operation_id
    assert operations[0]['entity'] == 'fund'
    assert operations[0]['lamport'] == 1
    assert json.loads(operations[0]['payload']) == {'name': 'Car'}


def test_invalid_contribution_is_rejected_without_mutating_fund(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.add_account('Checking', 'checking', '100')
    fund = Fund('Car', 1000, 100)
    ledger.replace_funds([fund])

    with pytest.raises(LedgerError):
        ledger.add_fund_contribution(fund, 0, period='2026-10')
    with pytest.raises(LedgerError):
        ledger.add_fund_contribution('missing-fund', 10, period='2026-10')

    assert ledger.get_fund(fund.id).balance == Decimal('100.00')
    assert ledger.list_fund_contributions() == []


def test_minor_unit_storage_is_exact_for_contributions(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.add_account('Checking', 'checking', '0.01')
    fund = Fund('Tiny', 100, recurring_transfer=Decimal('0.01'))
    ledger.replace_funds([fund])

    contribution = ledger.add_fund_contribution(fund, Decimal('0.01'), period='2026-10')

    assert money_to_minor(contribution.amount) == 1
    assert ledger.get_fund(fund.id).balance == Decimal('0.01')
    assert ledger.total_balance() == Decimal('0.01')


def test_deleted_budget_is_not_resurrected_by_legacy_import_migration(tmp_path):
    path = tmp_path / 'ledger.db'
    ledger = Ledger(path)
    category = BudgetCategory('Groceries', 300, 50)
    ledger.seed_legacy(None, [], [category], '2026-10')
    assert ledger.load_budget('2026-10').categories

    assert ledger.replace_budget('2026-10', []) is True
    reopened = Ledger(path)

    assert reopened.load_budget('2026-10').categories == []


def test_ledger_json_export_round_trips_contributions_and_exclusions(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.add_account('Checking', 'checking', '500')
    fund = Fund('Emergency', 1000, recurring_transfer=100, due_day=1)
    ledger.replace_funds([fund])
    contribution = ledger.auto_post_fund_contributions(
        today=date(2026, 10, 1), funds=[fund]
    )[0]
    export = ledger.export_json(tmp_path / 'ledger.json')

    other = Ledger(tmp_path / 'other.db')
    other.import_json(export)

    assert other.total_balance() == Decimal('500.00')
    assert other.list_fund_contributions()[0].id == contribution.id
    transaction = other.list_transactions(fund_id=fund.id)[0]
    assert transaction.budget_excluded is True
    assert transaction.affects_balance is False
    assert transaction.contribution_id == contribution.id


def test_transaction_classification_distinguishes_savings_expenses_and_transfers(
    tmp_path,
):
    ledger = make_ledger(tmp_path)
    checking = ledger.add_account('Checking', 'checking', '1000')
    savings = ledger.add_account('Savings', 'savings', '0')
    fund = Fund('Emergency', 1000, recurring_transfer=100, due_day=1)
    ledger.replace_funds([fund])

    ledger.add_transaction(checking.id, '2026-10-01', 'Store', amount='-20')
    ledger.add_transfer(checking.id, savings.id, '2026-10-02', '50')
    contribution = ledger.add_fund_contribution(fund, 100, period='2026-10')

    classifications = {
        transaction.payee: transaction.classification
        for transaction in ledger.list_transactions()
    }
    assert classifications['Store'] == 'expense'
    assert classifications['Transfer'] == 'transfer'
    assert classifications['Fund contribution: Emergency'] == 'savings'
    assert contribution.budget_excluded is True
