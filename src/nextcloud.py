import re
from pathlib import Path
import json
from subprocess import run, PIPE

from data import ACCOUNT_BALANCE_FILE, FUNDS_FILE

NEXTCLOUD_DATA_FILE = Path(__file__).parent.parent / 'nextcloud_sync.json'


def ping_nextcloud_server(nextcloud_sync_data: dict):
    base_url, username, password, data_path = nextcloud_sync_data.values()
    nextcloud_sync_command = ['curl', '-u', f'{username}:{password}', '-I',
                              f'https://{base_url}/remote.php/dav/files/{username}/{data_path}']
    result = run(nextcloud_sync_command, stdout=PIPE, stderr=PIPE)

    # If the command didn't finish successfully, return a generic error message
    if result.returncode != 0:
        return False, 'Failed to connect to server'

    # Try to find the http code
    output_lines = result.stdout.decode().split('\n')
    http_code_search = re.search(r'HTTP/2 ([0-9]+)', output_lines[0])

    # If we didn't find the code, return a generic error message
    if http_code_search is None:
        return False, 'Failed to connect to server'

    # Return specific messages for different http codes
    http_code = int(http_code_search.group(1))
    match http_code:
        # Successful authentication
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
    base_url, username, password, data_path = nextcloud_sync_data.values()
    for data_file in [ACCOUNT_BALANCE_FILE, FUNDS_FILE]:
        data_url = \
            f'https://{base_url}/remote.php/dav/files/{username}/{data_path}/{data_file.name}'
        nextcloud_sync_command = ['curl', '-u', f'{username}:{password}', data_url,
                                  '-o', data_file.as_posix()]
        run(nextcloud_sync_command, check=True)


def sync_data_to_nextcloud(nextcloud_sync_data: dict):
    base_url, username, password, data_path = nextcloud_sync_data.values()
    for data_file in [ACCOUNT_BALANCE_FILE, FUNDS_FILE]:
        data_url = \
            f'https://{base_url}/remote.php/dav/files/{username}/{data_path}/{data_file.name}'
        nextcloud_sync_command = ['curl', '-u', f'{username}:{password}',
                                  '-T', data_file.as_posix(), data_url]
        run(nextcloud_sync_command, check=True)


def load_nextcloud_sync_data():
    with open(NEXTCLOUD_DATA_FILE, 'r') as f:
        return json.load(f)


def save_nextcloud_sync_data(nextcloud_sync_data: dict):
    with open(NEXTCLOUD_DATA_FILE, 'w') as f:
        json.dump(nextcloud_sync_data, f, indent=4)
