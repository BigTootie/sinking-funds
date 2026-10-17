import os
import json
from datetime import datetime

from fund import Fund


def load_balance_from_txt(txt_file: str):
    if not os.path.exists(txt_file):
        return -1.0

    with open(txt_file, 'r') as f:
        return float(f.read())


def save_balance_to_txt(account_balance: float, txt_file: str):
    with open(txt_file, 'w') as f:
        f.write(str(account_balance))


def load_funds_from_json(json_file: str):
    if not os.path.exists(json_file):
        with open(json_file, 'a') as f:
            pass
        return []

    with open(json_file, 'r') as f:
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


def save_funds_to_json(funds: Fund, json_file: str):
    funds_as_dict = [{'name': fund.name, 'target': fund.target, 'balance': fund.balance,
                      'target_date': fund.target_date_as_str(),
                      'recurring_transfer': fund.recurring_transfer} for fund in funds]
    with open(json_file, 'w') as f:
        json.dump(funds_as_dict, f, indent=4)
