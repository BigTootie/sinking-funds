
import json
from pathlib import Path
from urllib.parse import quote

import requests

from data import ACCOUNT_BALANCE_FILE, BUDGET_FILE, FUNDS_FILE

NEXTCLOUD_DATA_FILE = Path(__file__).parent.parent / 'nextcloud_sync.json'

REQUEST_TIMEOUT = 15


def _get_file_url(nextcloud_sync_data: dict, filename: str | None = None):
    base_url = nextcloud_sync_data['base_url'].rstrip('/')
    username = nextcloud_sync_data['username']
    data_path = nextcloud_sync_data['data_path'].strip('/')

    # Encode individual path components while preserving directory separators.
    encoded_username = quote(username, safe='')
    encoded_data_path = quote(data_path, safe='/')

    url = f'https://{base_url}/remote.php/dav/files/{encoded_username}/{encoded_data_path}'

    if filename is not None:
        url += f'/{quote(filename, safe="")}'

    return url


def _get_auth(nextcloud_sync_data: dict):
    return (nextcloud_sync_data['username'], nextcloud_sync_data['password'])


def ping_nextcloud_server(nextcloud_sync_data: dict):
    try:
        response = requests.head(_get_file_url(nextcloud_sync_data),
                                 auth=_get_auth(nextcloud_sync_data), timeout=REQUEST_TIMEOUT,
                                 allow_redirects=True)
    except requests.RequestException:
        return False, 'Failed to connect to server'

    match response.status_code:
        case 200 | 207:
            return True, ''
        # Invalid credentials
        case 401:
            return False, 'Invalid credentials'
        case 403:
            return False, 'Access denied'
        case 404:
            return False, 'Data path does not exist on server'
        # For all other codes, return a generic error message
        case _:
            return False, 'Failed to connect to server'


def sync_data_from_nextcloud(nextcloud_sync_data: dict):
    for data_file in [ACCOUNT_BALANCE_FILE, FUNDS_FILE, BUDGET_FILE]:
        response = requests.get(_get_file_url(nextcloud_sync_data, data_file.name),
                                auth=_get_auth(nextcloud_sync_data), timeout=REQUEST_TIMEOUT)
        if response.status_code == 404:
            data_file.touch(exist_ok=True)
            continue
        response.raise_for_status()

        # Write only after a successful download.
        data_file.write_bytes(response.content)


def sync_data_to_nextcloud(data_file: Path, nextcloud_sync_data: dict):
    with data_file.open('rb') as file:
        response = requests.put(_get_file_url(nextcloud_sync_data, data_file.name),
                                auth=_get_auth(nextcloud_sync_data), data=file,
                                timeout=REQUEST_TIMEOUT)
    response.raise_for_status()


def load_nextcloud_sync_data():
    with open(NEXTCLOUD_DATA_FILE, 'r') as f:
        return json.load(f)


def save_nextcloud_sync_data(nextcloud_sync_data: dict):
    with open(NEXTCLOUD_DATA_FILE, 'w') as f:
        json.dump(nextcloud_sync_data, f, indent=4)
