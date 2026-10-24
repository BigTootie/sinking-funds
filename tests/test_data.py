from datetime import datetime
import json

import data
from budget import BudgetCategory
from fund import Fund


def test_funds_round_trip_through_json(tmp_path, monkeypatch):
    funds_path = tmp_path / 'funds.json'
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)
    source = [Fund('Home repair', 2500, 675, datetime(2027, 5, 1), 125)]

    data.save_funds_to_json(source)
    restored = data.load_funds_from_json()

    assert json.loads(funds_path.read_text(encoding='utf-8'))[0]['name'] == 'Home repair'
    assert restored[0].name == 'Home repair'
    assert restored[0].target == 2500
    assert restored[0].balance == 675
    assert restored[0].target_date == datetime(2027, 5, 1)
    assert restored[0].recurring_transfer == 125


def test_missing_funds_file_starts_with_empty_funds(tmp_path, monkeypatch):
    funds_path = tmp_path / 'funds.json'
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)

    assert data.load_funds_from_json() == []
    assert funds_path.exists()


def test_fund_loading_uses_named_fields_and_defaults_optional_contribution(tmp_path, monkeypatch):
    funds_path = tmp_path / 'funds.json'
    funds_path.write_text(
        '[{"balance":50,"target":100,"name":"Car","target_date":"None"}]',
        encoding='utf-8',
    )
    monkeypatch.setattr(data, 'FUNDS_FILE', funds_path)

    fund = data.load_funds_from_json()[0]

    assert (fund.name, fund.target, fund.balance, fund.recurring_transfer) == (
        'Car', 100, 50, 0.0
    )


def test_balance_round_trip_and_missing_balance_sentinel(tmp_path, monkeypatch):
    balance_path = tmp_path / 'balance.txt'
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', balance_path)

    assert data.load_balance_from_txt() == -1.0
    data.save_balance_to_txt(321.75)
    assert data.load_balance_from_txt() == 321.75


def test_budget_categories_round_trip_through_json(tmp_path, monkeypatch):
    budget_path = tmp_path / 'budget.json'
    monkeypatch.setattr(data, 'BUDGET_FILE', budget_path)
    categories = [BudgetCategory('Groceries', 1200, 350)]

    data.save_budget_categories_to_json(categories)
    restored = data.load_budget_categories_from_json()

    assert restored == categories


def test_generated_budget_expense_source_round_trips(tmp_path, monkeypatch):
    budget_path = tmp_path / 'budget.json'
    monkeypatch.setattr(data, 'BUDGET_FILE', budget_path)
    generated = BudgetCategory('Emergency contribution', 125, 0, 'expense', 'Emergency')

    data.save_budget_categories_to_json([generated])

    assert data.load_budget_categories_from_json() == [generated]


def test_legacy_budget_data_defaults_to_expense(tmp_path, monkeypatch):
    budget_path = tmp_path / 'budget.json'
    budget_path.write_text('[{"name":"Rent","budgeted":1000,"spent":900}]')
    monkeypatch.setattr(data, 'BUDGET_FILE', budget_path)
    restored = data.load_budget_categories_from_json()
    assert restored[0].kind == 'expense'


def test_empty_balance_file_is_treated_as_unset(tmp_path, monkeypatch):
    balance_path = tmp_path / 'balance.txt'
    balance_path.touch()
    monkeypatch.setattr(data, 'ACCOUNT_BALANCE_FILE', balance_path)
    assert data.load_balance_from_txt() == -1.0
