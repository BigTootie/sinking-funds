import os
import json

from fund import Fund


def load_funds_from_json(json_file):
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
