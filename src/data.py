import json
from pathlib import Path
from datetime import datetime

from fund import Fund
from budget import BudgetCategory

ACCOUNT_BALANCE_FILE = Path(__file__).parent.parent / 'balance.txt'
FUNDS_FILE = Path(__file__).parent.parent / 'funds.json'
BUDGET_FILE = Path(__file__).parent.parent / 'budget.json'


def load_balance_from_txt():
    if not ACCOUNT_BALANCE_FILE.exists():
        return -1.0

    with open(ACCOUNT_BALANCE_FILE, 'r') as f:
        return float(f.read())


def save_balance_to_txt(account_balance: float):
    with open(ACCOUNT_BALANCE_FILE, 'w') as f:
        f.write(str(account_balance))


def load_funds_from_json():
    if not FUNDS_FILE.exists():
        with open(FUNDS_FILE, 'a') as f:
            pass
        return []

    with open(FUNDS_FILE, 'r') as f:
        try:
            funds = []
            for item in json.load(f):
                name, target, balance, target_date, recurring_transfer = item.values()
                if target_date == 'None':
                    target_date = None
                else:
                    target_date = datetime.strptime(target_date, '%m/%d/%Y')
                funds.append(Fund(name, target, balance, target_date, recurring_transfer))
        except json.JSONDecodeError:
            return []

    return funds


def save_funds_to_json(funds: Fund):
    funds_as_dict = [{'name': fund.name, 'target': fund.target, 'balance': fund.balance,
                      'target_date': fund.target_date_as_str(),
                      'recurring_transfer': fund.recurring_transfer} for fund in funds]
    with open(FUNDS_FILE, 'w') as f:
        json.dump(funds_as_dict, f, indent=4)


def load_budget_categories_from_json():
    if not BUDGET_FILE.exists():
        BUDGET_FILE.touch()
        return []

    with open(BUDGET_FILE, 'r') as f:
        try:
            return [BudgetCategory(**item) for item in json.load(f)]
        except json.JSONDecodeError:
            return []


def save_budget_categories_to_json(categories: list[BudgetCategory]):
    categories_as_dict = [
        {'name': category.name, 'budgeted': category.budgeted, 'spent': category.spent}
        for category in categories
    ]
    with open(BUDGET_FILE, 'w') as f:
        json.dump(categories_as_dict, f, indent=4)
