import json
from datetime import datetime
from pathlib import Path

from budget import BudgetCategory
from fund import Fund

ACCOUNT_BALANCE_FILE = Path(__file__).parent.parent / 'balance.txt'
FUNDS_FILE = Path(__file__).parent.parent / 'funds.json'
BUDGET_FILE = Path(__file__).parent.parent / 'budget.json'


def load_balance_from_txt() -> float:
    if not ACCOUNT_BALANCE_FILE.exists():
        return -1.0

    value = ACCOUNT_BALANCE_FILE.read_text(encoding='utf-8').strip()
    return float(value) if value else -1.0


def save_balance_to_txt(account_balance: float) -> None:
    ACCOUNT_BALANCE_FILE.write_text(str(account_balance), encoding='utf-8')


def load_funds_from_json() -> list[Fund]:
    if not FUNDS_FILE.exists():
        FUNDS_FILE.touch()
        return []

    try:
        items = json.loads(FUNDS_FILE.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return []

    funds = []
    for item in items:
        date_value = item.get('target_date')
        target_date = (
            None if not date_value or date_value == 'None'
            else datetime.strptime(date_value, '%m/%d/%Y')
        )
        funds.append(Fund(
            name=item['name'],
            target=item['target'],
            initial_balance=item.get('balance', 0.0),
            target_date=target_date,
            recurring_transfer=item.get('recurring_transfer', 0.0),
        ))

    return funds


def save_funds_to_json(funds: list[Fund]) -> None:
    funds_as_dict = [
        {
            'name': fund.name,
            'target': fund.target,
            'balance': fund.balance,
            'target_date': fund.target_date_as_str(),
            'recurring_transfer': fund.recurring_transfer,
        }
        for fund in funds
    ]
    FUNDS_FILE.write_text(json.dumps(funds_as_dict, indent=4), encoding='utf-8')


def load_budget_categories_from_json() -> list[BudgetCategory]:
    if not BUDGET_FILE.exists():
        BUDGET_FILE.touch()
        return []

    with open(BUDGET_FILE, 'r') as f:
        try:
            return [BudgetCategory(**item) for item in json.load(f)]
        except json.JSONDecodeError:
            return []


def save_budget_categories_to_json(categories: list[BudgetCategory]) -> None:
    categories_as_dict = []
    for category in categories:
        item = {'name': category.name, 'budgeted': category.budgeted, 'spent': category.spent,
                'kind': category.kind}
        if category.source_fund is not None:
            item['source_fund'] = category.source_fund
        categories_as_dict.append(item)
    with open(BUDGET_FILE, 'w') as f:
        json.dump(categories_as_dict, f, indent=4)
