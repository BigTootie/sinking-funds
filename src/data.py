import os
import json

from fund import Fund


def load_funds_from_json(json_file: str):
    if not os.path.exists(json_file):
        with open(json_file, 'a') as f:
            pass
        return []

    with open(json_file, 'r') as f:
        try:
            funds = [Fund(x['name'], x['target'], x['balance']) for x in json.load(f)]
        except json.JSONDecodeError:
            return []

    return funds


def save_funds_to_json(funds: Fund, json_file: str):
    funds_as_dict = \
        [{key: getattr(fund, key) for key in ['name', 'target', 'balance']} for fund in funds]
    with open(json_file, 'w') as f:
        json.dump(funds_as_dict, f, indent=4)
