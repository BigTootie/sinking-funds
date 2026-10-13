import os
import json

from fund import Fund


def load_funds_from_json(json_file):
    if not os.path.exists(json_file):
        raise RuntimeError(f'Funds file {json_file} does not exist')

    with open(json_file, 'r') as f:
        funds = [Fund(x['name'], x['target'], x['balance']) for x in json.load(f)]

    return funds
