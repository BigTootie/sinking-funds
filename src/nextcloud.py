"""Nextcloud connection settings, keyring credentials, and connectivity checks."""

from __future__ import annotations

import json
import logging
from urllib.parse import quote, urlsplit

import keyring
import requests

REQUEST_TIMEOUT = (5, 15)
KEYRING_SERVICE = 'savings-funds'
KEYRING_USERNAME = 'nextcloud'
KEYRING_SYNC_USERNAME = 'sync-e2e'
KEYRING_UNAVAILABLE_WARNING = (
    'The OS keyring is unavailable, so the Nextcloud password cannot be saved. '
    'Install a keyring backend to enable synchronization.'
)

logger = logging.getLogger(__name__)
_credential_warning: str | None = None


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


def credential_storage_warning() -> str | None:
    return _credential_warning


def _reset_credential_warning() -> None:
    global _credential_warning
    _credential_warning = None


def _keyring_get_password() -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        logger.warning('Could not read the Nextcloud password from the keyring')
        return None


def _keyring_set_password(password: str) -> bool:
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, password)
    except Exception:
        logger.warning('Could not save the Nextcloud password to the keyring')
        return False
    return True


def _keyring_delete_password() -> bool:
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        return False
    return True


def get_sync_key() -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_SYNC_USERNAME)
    except Exception:
        logger.warning('Could not read the sync encryption key from the keyring')
        return None


def set_sync_key(encoded_key: str) -> bool:
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_SYNC_USERNAME, encoded_key)
    except Exception:
        logger.warning('Could not save the sync encryption key to the keyring')
        return False
    return True


def delete_sync_key() -> bool:
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_SYNC_USERNAME)
    except Exception:
        return False
    return True


def _database_ledger(ledger=None):
    if ledger is not None:
        return ledger
    from ledger import Ledger

    return Ledger()


def load_nextcloud_sync_data_from_db(ledger=None) -> dict | None:
    """Load Nextcloud settings from SQLite, with the password in the keyring."""
    global _credential_warning
    _reset_credential_warning()
    store = _database_ledger(ledger)
    raw = store.get_setting('nextcloud_config')
    if not raw:
        return None
    try:
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError('expected an object')
        required = ('base_url', 'username', 'data_path')
        if any(not isinstance(document.get(key), str) for key in required):
            raise ValueError('missing connection fields')
        if not document['base_url'].strip() or not document['data_path'].strip():
            raise ValueError('server URL and data path are required')
        document['base_url'] = normalize_base_url(document['base_url'])
    except (json.JSONDecodeError, TypeError, ValueError):
        raise SyncError(
            'Could not read the Nextcloud settings stored locally.'
        ) from None
    password = _keyring_get_password()
    if password is None:
        raise SyncError(
            'Could not read the Nextcloud password from the OS keyring. '
            'Re-enter the password in Settings.'
        )
    document['password'] = password
    return document


def save_nextcloud_sync_data_to_db(
    nextcloud_sync_data: dict | None, ledger=None
) -> bool:
    """Store connection settings in SQLite; never store the password there."""
    global _credential_warning
    _reset_credential_warning()
    store = _database_ledger(ledger)
    document = dict(nextcloud_sync_data or {})
    document.pop('passphrase', None)
    password = document.pop('password', None)
    if password is not None and not _keyring_set_password(password):
        _credential_warning = KEYRING_UNAVAILABLE_WARNING
    if document:
        payload = json.dumps(document, indent=4, sort_keys=True) + '\n'
        store.set_setting('nextcloud_config', payload)
    else:
        store.delete_setting('nextcloud_config')
        delete_sync_key()
        if not _keyring_delete_password():
            _credential_warning = (
                'Nextcloud synchronization is disabled, but the password could '
                'not be removed from the OS keyring.'
            )
    return True
