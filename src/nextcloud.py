"""Nextcloud settings, keyring credentials, and the legacy WebDAV sync code.

v0.4 stores connection settings and sync state in SQLite and no longer runs
whole-file WebDAV synchronization from the app; operation-log sync lands in
v0.5. The file-based helpers remain for migration and compatibility tests.
"""

import hashlib
import json
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlsplit

import keyring
import requests

import data
from data import (
    ACCOUNT_BALANCE_FILE,
    BUDGET_FILE,
    BUDGET_HISTORY_FILE,
    FUNDS_FILE,
    DataCorruptionError,
    DataFileError,
    FutureSchemaVersion,
    UnsupportedSchemaError,
    atomic_write_bytes,
    parse_balance_text,
    parse_budget_history_text,
    parse_budget_text,
    parse_funds_text,
    quarantine_file,
)
from paths import get_data_dir

NEXTCLOUD_DATA_FILE = get_data_dir() / 'nextcloud_sync.json'
SYNC_STATE_FILE = get_data_dir() / 'sync_state.json'

REQUEST_TIMEOUT = (5, 15)


def data_files() -> tuple[Path, ...]:
    """Return the current data files, respecting test/runtime path overrides."""
    return (ACCOUNT_BALANCE_FILE, FUNDS_FILE, BUDGET_FILE, BUDGET_HISTORY_FILE)


logger = logging.getLogger(__name__)

KEYRING_SERVICE = 'savings-funds'
KEYRING_USERNAME = 'nextcloud'
KEYRING_UNAVAILABLE_WARNING = (
    'The OS keyring is unavailable, so the Nextcloud password is stored in '
    'nextcloud_sync.json. Install a keyring backend to avoid storing it in '
    'plaintext.'
)
_credential_warning: str | None = None


class SyncError(Exception):
    """A synchronization failure that is safe to show to the user."""


class SyncConflictError(SyncError):
    """The remote file changed after the last successful synchronization."""


@dataclass
class SyncResult:
    downloaded: list[Path] = field(default_factory=list)
    uploads: list[Path] = field(default_factory=list)
    conflicts: list[Path] = field(default_factory=list)
    created: list[Path] = field(default_factory=list)
    invalid_locals: list[Path] = field(default_factory=list)


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


def _get_file_url(nextcloud_sync_data: dict, filename: str | None = None):
    base_url = normalize_base_url(nextcloud_sync_data['base_url'])
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


def _redact(value: str, nextcloud_sync_data: dict) -> str:
    password = nextcloud_sync_data.get('password')
    if password:
        return value.replace(password, '[redacted]')
    return value


def _request_error(
    exc: requests.RequestException, nextcloud_sync_data: dict
) -> SyncError:
    return SyncError(
        f'Could not reach Nextcloud: {_redact(str(exc), nextcloud_sync_data)}'
    )


def ping_nextcloud_server(nextcloud_sync_data: dict):
    try:
        response = requests.head(
            _get_file_url(nextcloud_sync_data),
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


def _file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load_sync_state() -> dict:
    if not SYNC_STATE_FILE.exists():
        return {}
    try:
        text = SYNC_STATE_FILE.read_text(encoding='utf-8')
        if not text.strip():
            return {}
        document = json.loads(text)
        return document if isinstance(document, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.warning('Ignoring unreadable sync state file', exc_info=True)
        return {}


def _save_sync_state(state: dict) -> None:
    data.atomic_write_text(
        SYNC_STATE_FILE, json.dumps(state, indent=4) + '\n', make_backup=False
    )


def _state_entry(state: dict, filename: str) -> dict:
    files = state.setdefault('files', {})
    entry = files.get(filename)
    if not isinstance(entry, dict):
        entry = {}
        files[filename] = entry
    return entry


def _record_state(state: dict, filename: str, content: bytes, etag: str | None = None):
    _state_entry(state, filename).update(
        {
            'hash': _file_hash(content),
            'etag': etag,
        }
    )


def _validate_content(path: Path, content: bytes) -> None:
    """Raise ValueError when file contents cannot be loaded by the app."""
    if not content.strip():
        return
    text = content.decode('utf-8')
    try:
        if path.name == ACCOUNT_BALANCE_FILE.name:
            parse_balance_text(text)
        elif path.name == FUNDS_FILE.name:
            parse_funds_text(text)
        elif path.name == BUDGET_FILE.name:
            parse_budget_text(text)
        elif path.name == BUDGET_HISTORY_FILE.name:
            parse_budget_history_text(text)
    except FutureSchemaVersion as exc:
        # A newer version must be preserved, never quarantined or overwritten
        # by an older build.
        raise UnsupportedSchemaError(path, str(exc)) from None


def _validate_remote_file(path: Path, content: bytes) -> None:
    try:
        _validate_content(path, content)
    except (DataFileError, UnicodeDecodeError, TypeError, ValueError) as exc:
        raise SyncError(
            f'Nextcloud returned invalid data for {path.name}; local data was kept.'
        ) from exc


def _is_valid_local_file(path: Path, content: bytes) -> bool:
    try:
        _validate_content(path, content)
    except (UnicodeDecodeError, TypeError, ValueError):
        return False
    return True


def _is_unset_content(path: Path, content: bytes) -> bool:
    """Return True for blank files and the legacy unset-balance sentinel."""
    if not content.strip():
        return True
    if path.name == ACCOUNT_BALANCE_FILE.name:
        try:
            return parse_balance_text(content.decode('utf-8')) is None
        except (UnicodeDecodeError, ValueError):
            return False
    return False


def _conflict_path(path: Path) -> Path:
    from data import _timestamp

    return path.with_name(f'{path.name}.remote-{_timestamp()}.conflict')


def credential_storage_warning() -> str | None:
    """Return the last keyring fallback warning, if any."""
    return _credential_warning


def _reset_credential_warning() -> None:
    global _credential_warning
    _credential_warning = None


def _keyring_get_password() -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        logger.warning('OS keyring is unavailable; using local settings fallback')
        return None


def _keyring_set_password(password: str) -> bool:
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, password)
    except Exception:
        logger.warning('OS keyring is unavailable; using local settings fallback')
        return False
    return True


def _keyring_delete_password() -> bool:
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except (keyring.errors.NoKeyringError, keyring.errors.PasswordDeleteError):
        return True
    except Exception:
        logger.warning('Could not remove the Nextcloud password from the OS keyring')
        return False
    return True


def _remove_plaintext_config_backups() -> None:
    backup_dir = NEXTCLOUD_DATA_FILE.parent / 'backups'
    for path in backup_dir.glob('nextcloud_sync-*.bak'):
        with suppress(OSError):
            path.unlink()


def _write_config(document: dict) -> bool:
    changed = data.atomic_write_text(
        NEXTCLOUD_DATA_FILE,
        json.dumps(document, indent=4) + '\n',
        make_backup=False,
    )
    _remove_plaintext_config_backups()
    return changed


def load_nextcloud_sync_data() -> dict | None:
    """Load and validate saved Nextcloud settings.

    Passwords are read from the OS keyring when available. Legacy plaintext
    passwords are migrated to the keyring; systems without a keyring keep the
    password in the private settings file and report a warning.

    Returns None when synchronization has not been configured or was disabled.
    """
    global _credential_warning
    _reset_credential_warning()
    if not NEXTCLOUD_DATA_FILE.exists():
        return None
    with suppress(OSError):
        NEXTCLOUD_DATA_FILE.chmod(0o600)
    text = NEXTCLOUD_DATA_FILE.read_text(encoding='utf-8')
    if not text.strip():
        return None

    try:
        document = json.loads(text)
        if not isinstance(document, dict):
            raise ValueError('expected an object')
        if not document:
            return None
        required = ('base_url', 'username', 'data_path')
        if any(not isinstance(document.get(key), str) for key in required):
            raise ValueError('missing connection fields')
        if not document['base_url'].strip() or not document['data_path'].strip():
            raise ValueError('server URL and data path are required')
        document['base_url'] = normalize_base_url(document['base_url'])

        password = document.pop('password', None)
        if password is not None and not isinstance(password, str):
            raise ValueError('invalid password field')
        if password is None:
            password = _keyring_get_password()
            if password is None:
                raise DataFileError(
                    NEXTCLOUD_DATA_FILE,
                    'Could not read the Nextcloud password from the OS keyring. '
                    'Re-enter the password in Settings.',
                )
            _remove_plaintext_config_backups()
        elif _keyring_set_password(password):
            try:
                _write_config(document)
            except OSError:
                logger.warning(
                    'Could not remove the plaintext Nextcloud password from settings',
                    exc_info=True,
                )
                _credential_warning = (
                    'The Nextcloud password was copied to the OS keyring, but '
                    'nextcloud_sync.json could not be updated. The old password '
                    'may still be stored in that file.'
                )
        else:
            _credential_warning = KEYRING_UNAVAILABLE_WARNING
        document['password'] = password
        return document
    except DataFileError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        quarantine_path = quarantine_file(NEXTCLOUD_DATA_FILE)
        raise DataCorruptionError(
            NEXTCLOUD_DATA_FILE,
            f'Could not read Nextcloud settings: {exc}. The file was preserved.',
            quarantine_path,
        ) from None


def save_nextcloud_sync_data(nextcloud_sync_data: dict | None) -> bool:
    global _credential_warning
    _reset_credential_warning()
    document = dict(nextcloud_sync_data or {})
    password = document.pop('password', None)
    if password is not None and not _keyring_set_password(password):
        document['password'] = password
        _credential_warning = KEYRING_UNAVAILABLE_WARNING

    changed = _write_config(document)
    if not document and not _keyring_delete_password():
        _credential_warning = (
            'Nextcloud synchronization is disabled, but the password could not '
            'be removed from the OS keyring.'
        )
    return changed


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
        raise DataFileError(
            Path('ledger.db'),
            'Could not read the Nextcloud settings stored in the local database.',
        ) from None
    password = _keyring_get_password()
    if password is None:
        raise DataFileError(
            Path('ledger.db'),
            'Could not read the Nextcloud password from the OS keyring. '
            'Re-enter the password in Settings.',
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
    previous = store.get_setting('nextcloud_config')
    document = dict(nextcloud_sync_data or {})
    password = document.pop('password', None)
    if password is not None and not _keyring_set_password(password):
        _credential_warning = KEYRING_UNAVAILABLE_WARNING
    if document:
        payload = json.dumps(document, indent=4, sort_keys=True) + '\n'
        store.set_setting('nextcloud_config', payload)
    else:
        store.delete_setting('nextcloud_config')
        if not _keyring_delete_password():
            _credential_warning = (
                'Nextcloud synchronization is disabled, but the password could '
                'not be removed from the OS keyring.'
            )
    return previous != (store.get_setting('nextcloud_config') or None)


def migrate_nextcloud_file_to_db(ledger=None) -> bool:
    """Import the v0.3 settings file once, then never read it at runtime."""
    store = _database_ledger(ledger)
    if store.get_meta('nextcloud_file_migrated') == '1':
        return False
    if not NEXTCLOUD_DATA_FILE.exists():
        store.set_meta('nextcloud_file_migrated', '1')
        return False
    try:
        document = load_nextcloud_sync_data()
    except (DataFileError, OSError):
        store.set_meta('nextcloud_file_migrated', '1')
        raise
    if document is not None:
        save_nextcloud_sync_data_to_db(document, store)
    store.set_meta('nextcloud_file_migrated', '1')
    # An existing file - including an empty one that explicitly disables
    # synchronization - means the user has already seen the setup prompt.
    store.set_meta('nextcloud_prompted', '1')
    return True


def reconcile_file(
    local_content: bytes | None, remote_content: bytes | None, last_hash: str | None
) -> str:
    """Decide what to do with one local/remote file pair.

    The result is one of ``download``, ``upload``, ``conflict``, ``unchanged``,
    or ``create_empty``.
    """
    if remote_content is None:
        return 'create_empty' if local_content is None else 'upload'
    if local_content is None:
        return 'download'
    if local_content == remote_content:
        return 'unchanged'

    local_hash = _file_hash(local_content)
    remote_hash = _file_hash(remote_content)
    if last_hash == local_hash:
        return 'download'
    if last_hash == remote_hash:
        return 'upload'
    return 'conflict'


def _fetch_remote_file(
    data_file: Path, nextcloud_sync_data: dict
) -> tuple[bytes | None, str | None]:
    try:
        url = _get_file_url(nextcloud_sync_data, data_file.name)
    except ValueError as exc:
        raise SyncError(str(exc)) from exc

    try:
        response = requests.get(
            url, auth=_get_auth(nextcloud_sync_data), timeout=REQUEST_TIMEOUT
        )
    except requests.RequestException as exc:
        raise _request_error(exc, nextcloud_sync_data) from exc

    if response.status_code == 404:
        return None, None
    if response.status_code != 200:
        raise SyncError(
            f'Nextcloud returned HTTP {response.status_code} for {data_file.name}.'
        )

    content = response.content
    _validate_remote_file(data_file, content)
    etag = getattr(response, 'headers', {}).get('ETag')
    return content, etag


def sync_data_from_nextcloud(nextcloud_sync_data: dict) -> SyncResult:
    """Download remote data, preserving conflicting local and remote copies.

    Every remote file is fetched and validated before any local file is
    changed, so a network or validation failure cannot leave a half-synced
    data set.
    """
    state = _load_sync_state()
    result = SyncResult()

    fetched = []
    for data_file in data_files():
        remote_content, etag = _fetch_remote_file(data_file, nextcloud_sync_data)
        local_content = data_file.read_bytes() if data_file.exists() else None
        fetched.append((data_file, local_content, remote_content, etag))

    # Validate every local file before applying any remote file. A newer schema
    # raises and aborts the whole sync without writing anything.
    prepared = []
    for data_file, local_content, remote_content, etag in fetched:
        if local_content is not None and not _is_valid_local_file(
            data_file, local_content
        ):
            result.invalid_locals.append(quarantine_file(data_file))
            local_content = None
        prepared.append((data_file, local_content, remote_content, etag))
    fetched = prepared

    for data_file, local_content, remote_content, etag in fetched:
        # Empty files were created by older versions and the old balance
        # sentinel means "not set". Do not let those placeholder values
        # overwrite real data on either side.
        local_unset = local_content is not None and _is_unset_content(
            data_file, local_content
        )
        remote_unset = remote_content is not None and _is_unset_content(
            data_file, remote_content
        )
        if local_unset and remote_unset:
            local_content = remote_content = b''
        elif local_unset:
            local_content = None
        elif remote_unset:
            remote_content = None

        entry = _state_entry(state, data_file.name)
        action = reconcile_file(local_content, remote_content, entry.get('hash'))

        if action == 'download':
            assert remote_content is not None
            atomic_write_bytes(data_file, remote_content)
            _record_state(state, data_file.name, remote_content, etag)
            result.downloaded.append(data_file)
        elif action == 'unchanged':
            assert remote_content is not None
            _record_state(state, data_file.name, remote_content, etag)
        elif action == 'upload':
            if remote_content is None:
                # The remote file was deleted; do not send a stale If-Match.
                entry.pop('etag', None)
            result.uploads.append(data_file)
        elif action == 'conflict':
            assert remote_content is not None
            conflict = _conflict_path(data_file)
            atomic_write_bytes(conflict, remote_content, make_backup=False)
            # Keep the local copy and let it win, but upload unconditionally
            # because the remote ETag belongs to the preserved conflict copy.
            entry.pop('etag', None)
            result.conflicts.append(conflict)
            result.uploads.append(data_file)
        elif action == 'create_empty':
            atomic_write_bytes(data_file, b'')
            _record_state(state, data_file.name, b'')
            result.created.append(data_file)
            result.uploads.append(data_file)
        _save_sync_state(state)

    return result


def _put_file(nextcloud_sync_data: dict, filename: str, content: bytes, headers: dict):
    try:
        return requests.put(
            _get_file_url(nextcloud_sync_data, filename),
            auth=_get_auth(nextcloud_sync_data),
            data=content,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    except ValueError as exc:
        raise SyncError(str(exc)) from exc
    except requests.RequestException as exc:
        raise _request_error(exc, nextcloud_sync_data) from exc


def sync_data_to_nextcloud(data_file: Path, nextcloud_sync_data: dict) -> None:
    """Upload one file, refusing to overwrite a remote file changed elsewhere."""
    data_file = Path(data_file)
    if not data_file.exists():
        raise SyncError(f'Local file {data_file.name} does not exist.')

    content = data_file.read_bytes()
    state = _load_sync_state()
    entry = _state_entry(state, data_file.name)
    last_hash = entry.get('hash')

    headers = {}
    if entry.get('etag'):
        headers['If-Match'] = entry['etag']

    response = _put_file(nextcloud_sync_data, data_file.name, content, headers)

    if response.status_code == 412:
        # Some Nextcloud deployments rotate ETags without changing the file.
        # Verify the remote content before treating this as a real conflict.
        remote_content, remote_etag = _fetch_remote_file(data_file, nextcloud_sync_data)
        if remote_content is not None and remote_content == content:
            _record_state(state, data_file.name, content, remote_etag)
            _save_sync_state(state)
            return

        remote_is_unchanged = (
            remote_content is not None
            and not _is_unset_content(data_file, remote_content)
            and last_hash is not None
            and _file_hash(remote_content) == last_hash
        )
        if (
            remote_content is None
            or _is_unset_content(data_file, remote_content)
            or remote_is_unchanged
        ):
            # The remote copy is absent, empty, or still matches the last
            # synchronized hash. The ETag was stale, so retry without If-Match.
            response = _put_file(nextcloud_sync_data, data_file.name, content, {})

    if response.status_code == 412:
        raise SyncConflictError(
            f'{data_file.name} changed on Nextcloud. Restart the app to reconcile '
            'the two copies before uploading again.'
        )
    if response.status_code >= 400:
        raise SyncError(
            f'Nextcloud rejected {data_file.name} with HTTP {response.status_code}.'
        )

    _record_state(
        state,
        data_file.name,
        content,
        getattr(response, 'headers', {}).get('ETag'),
    )
    _save_sync_state(state)
