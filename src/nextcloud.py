"""Nextcloud connection settings and connectivity checks."""

from __future__ import annotations

import json
from urllib.parse import quote, urlsplit

import requests

REQUEST_TIMEOUT = (5, 15)


class SyncError(Exception):
    """A synchronization failure that is safe to show to the user."""


def normalize_base_url(value: str) -> str:
    """Return a host-only Nextcloud base URL, rejecting paths and schemes."""
    value = (value or '').strip()
    if not value:
        raise ValueError('Enter a Nextcloud server URL.')
    if '://' in value:
        parsed = urlsplit(value)
        if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('Enter only the server host, not a URL path.')
        value = parsed.netloc
    value = value.rstrip('/')
    if not value or '/' in value:
        raise ValueError('Enter only the server host, for example cloud.example.com.')
    return value


def get_file_url(nextcloud_sync_data: dict, path: str = '') -> str:
    base_url = normalize_base_url(nextcloud_sync_data['base_url'])
    username = nextcloud_sync_data['username']
    data_path = nextcloud_sync_data['data_path'].strip('/')
    encoded_username = quote(username, safe='')
    encoded_data_path = quote(data_path, safe='/')
    url = (
        f'https://{base_url}/remote.php/dav/files/{encoded_username}/'
        f'{encoded_data_path}'
    )
    if path:
        url += '/' + quote(path, safe='/')
    return url


def _get_auth(nextcloud_sync_data: dict):
    return (nextcloud_sync_data['username'], nextcloud_sync_data['password'])


def ping_nextcloud_server(nextcloud_sync_data: dict):
    try:
        response = requests.head(
            get_file_url(nextcloud_sync_data),
            auth=_get_auth(nextcloud_sync_data),
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except ValueError as exc:
        return False, str(exc)
    except requests.RequestException:
        return False, 'Failed to connect to server'

    match response.status_code:
        case 200 | 207:
            return True, ''
        case 401:
            return False, 'Invalid credentials'
        case 403:
            return False, 'Access denied'
        case 404:
            return False, 'Data path does not exist on server'
        case _:
            return False, 'Failed to connect to server'


def _database_ledger(ledger=None):
    if ledger is not None:
        return ledger
    from ledger import Ledger

    return Ledger()


def _connection_document(raw: str) -> dict:
    try:
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError('expected an object')
        required = ('base_url', 'username', 'data_path')
        if any(not isinstance(document.get(key), str) for key in required):
            raise ValueError('missing connection fields')
        password = document.get('password', '')
        if not isinstance(password, str):
            raise ValueError('invalid password field')
        if not document['base_url'].strip() or not document['data_path'].strip():
            raise ValueError('server URL and data path are required')
        document['password'] = password
        document['base_url'] = normalize_base_url(document['base_url'])
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SyncError(
            'Could not read the Nextcloud settings stored locally. Re-enter the '
            'server password in Settings.'
        ) from exc
    return document


def load_nextcloud_sync_data_from_db(ledger=None) -> dict | None:
    """Load local Nextcloud settings, including the password."""
    store = _database_ledger(ledger)
    raw = store.get_setting('nextcloud_config')
    if not raw:
        return None
    return _connection_document(raw)


def save_nextcloud_sync_data_to_db(
    nextcloud_sync_data: dict | None, ledger=None
) -> bool:
    """Store connection settings in the local SQLite database."""
    store = _database_ledger(ledger)
    document = dict(nextcloud_sync_data or {})
    if document:
        if not document.get('password'):
            raise SyncError('Enter the Nextcloud password.')
        payload = json.dumps(document, indent=4, sort_keys=True) + '\n'
        store.set_setting('nextcloud_config', payload)
    else:
        store.delete_setting('nextcloud_config')
        store.delete_setting('sync_e2e_key')
    return True


def get_sync_key(ledger=None) -> str | None:
    return _database_ledger(ledger).get_setting('sync_e2e_key')


def set_sync_key(encoded_key: str, ledger=None) -> bool:
    _database_ledger(ledger).set_setting('sync_e2e_key', encoded_key)
    return True


def delete_sync_key(ledger=None) -> bool:
    _database_ledger(ledger).delete_setting('sync_e2e_key')
    return True
