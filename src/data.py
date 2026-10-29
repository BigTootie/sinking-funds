"""Atomic local persistence for funds, budgets, and account balance."""

import json
import os
import shutil
import tempfile
import zipfile
from contextlib import suppress
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import uuid4

from budget import BudgetCategory, BudgetState, current_period
from fund import Fund
from paths import get_data_dir
from utils import parse_signed_money

DATA_DIR = get_data_dir()
ACCOUNT_BALANCE_FILE = DATA_DIR / 'balance.txt'
FUNDS_FILE = DATA_DIR / 'funds.json'
BUDGET_FILE = DATA_DIR / 'budget.json'
BUDGET_HISTORY_FILE = DATA_DIR / 'budget_history.json'

SCHEMA_VERSION = 3
BACKUP_LIMIT = 10
DATA_FILE_NAMES = ('balance.txt', 'funds.json', 'budget.json', 'budget_history.json')


class DataFileError(Exception):
    """Base error for unreadable or unwritable application data."""

    def __init__(self, path: Path, message: str, quarantine_path: Path | None = None):
        self.path = path
        self.quarantine_path = quarantine_path
        self.message = message
        super().__init__(message)

    def __str__(self):
        if self.quarantine_path is not None:
            return f'{self.message} (saved as {self.quarantine_path.name})'
        return self.message


class DataCorruptionError(DataFileError):
    """Raised when a data file exists but cannot be safely interpreted."""


class UnsupportedSchemaError(DataFileError):
    """Raised when a file was written by a newer app version.

    These files are deliberately not quarantined: they may be perfectly valid
    and must not be replaced with empty data by an older build.
    """


class FutureSchemaVersion(ValueError):
    """Internal signal that a document version is newer than this build."""


def _timestamp() -> str:
    return datetime.now().strftime('%Y%m%d-%H%M%S-%f')


def _set_private_permissions(path: Path, *, directory: bool = False) -> None:
    # Windows and some mobile filesystems do not support POSIX modes.
    # Directories need the execute bit to be traversable, so they use 0700.
    with suppress(OSError):
        path.chmod(0o700 if directory else 0o600)


def _backup_dir(path: Path) -> Path:
    directory = path.parent / 'backups'
    directory.mkdir(parents=True, exist_ok=True)
    _set_private_permissions(directory, directory=True)
    return directory


def backup_file(path: Path) -> Path | None:
    """Copy an existing file into a rolling backup directory."""
    if not path.is_file():
        return None
    backup = _backup_dir(path) / f'{path.stem}-{_timestamp()}{path.suffix}.bak'
    shutil.copy2(path, backup)
    _set_private_permissions(backup)

    backups = sorted(
        _backup_dir(path).glob(f'{path.stem}-*{path.suffix}.bak'),
        key=lambda item: item.name,
    )
    for old_backup in backups[:-BACKUP_LIMIT]:
        with suppress(OSError):
            old_backup.unlink()
    return backup


def _data_files() -> tuple[Path, ...]:
    """Return current data paths after test/user path overrides are applied."""
    return (ACCOUNT_BALANCE_FILE, FUNDS_FILE, BUDGET_FILE, BUDGET_HISTORY_FILE)


def backup_all_files() -> Path:
    """Copy every existing data file into one timestamped snapshot directory."""
    destination = _backup_dir(ACCOUNT_BALANCE_FILE) / f'full-{_timestamp()}'
    destination.mkdir(parents=True, exist_ok=False)
    _set_private_permissions(destination, directory=True)
    for path in _data_files():
        if path.is_file():
            copy = destination / path.name
            shutil.copy2(path, copy)
            _set_private_permissions(copy)
    marker = destination / '.complete'
    marker.write_text(
        datetime.now().isoformat(timespec='seconds') + '\n', encoding='utf-8'
    )
    _set_private_permissions(marker)
    return destination


def export_data(destination: Path | None = None) -> Path:
    """Export user data (never credentials) as a portable zip archive."""
    export_dir = ACCOUNT_BALANCE_FILE.parent / 'exports'
    export_dir.mkdir(parents=True, exist_ok=True)
    if destination is None:
        destination = export_dir / f'savings-funds-{_timestamp()}.zip'
    else:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)

    included = []
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in _data_files():
            if path.is_file():
                archive.write(path, arcname=path.name)
                included.append(path.name)
        manifest = {
            'schema_version': SCHEMA_VERSION,
            'exported_at': datetime.now().isoformat(timespec='seconds'),
            'files': included,
            'excluded': ['nextcloud_sync.json', 'sync_state.json'],
        }
        archive.writestr('manifest.json', json.dumps(manifest, indent=2) + '\n')
    _set_private_permissions(destination)
    return destination


def _repair_backup_permissions(backup_root: Path) -> None:
    """Repair directory modes left by older builds that used 0600 for folders."""
    _set_private_permissions(backup_root, directory=True)
    try:
        entries = list(backup_root.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith('full-') and entry.is_dir() and not entry.is_symlink():
            _set_private_permissions(entry, directory=True)
            try:
                children = list(entry.iterdir())
            except OSError:
                continue
            for child in children:
                if child.is_file() and not child.is_symlink():
                    _set_private_permissions(child)


def latest_full_backup() -> Path | None:
    """Return the newest full backup directory, if one exists."""
    backup_root = _backup_dir(ACCOUNT_BALANCE_FILE)
    _repair_backup_permissions(backup_root)
    candidates = [
        path
        for path in backup_root.glob('full-*')
        if path.is_dir() and (path / '.complete').is_file()
    ]
    return max(candidates, key=lambda path: path.name) if candidates else None


def _validate_backup_content(path: Path, content: bytes) -> None:
    if not content.strip():
        return
    try:
        text = content.decode('utf-8')
        if path.name == ACCOUNT_BALANCE_FILE.name:
            parse_balance_text(text)
        elif path.name == FUNDS_FILE.name:
            parse_funds_text(text)
        elif path.name == BUDGET_FILE.name:
            parse_budget_text(text)
        elif path.name == BUDGET_HISTORY_FILE.name:
            parse_budget_history_text(text)
    except (UnicodeDecodeError, ValueError, DataFileError) as exc:
        raise ValueError(f'backup contains invalid {path.name}: {exc}') from None


def restore_backup(source: Path) -> list[Path]:
    """Restore a full backup after validating it and backing up current data.

    Restoring is intentionally a restart-required operation in the UI; this
    function only guarantees that every file in the backup is valid and that
    the current files are preserved in a fresh safety snapshot first.
    """
    source = Path(source)
    if not source.is_dir():
        raise ValueError('backup folder does not exist')
    destinations = {path.name: path for path in _data_files()}
    available = {
        name: source / name for name in DATA_FILE_NAMES if (source / name).is_file()
    }
    if not available:
        raise ValueError('backup contains no data files')
    contents = {}
    for name, path in available.items():
        try:
            contents[name] = path.read_bytes()
        except OSError as exc:
            raise ValueError(
                f'cannot read backup file {path}: {exc}. Check that the backup '
                'folder and its files are readable by the user running '
                'Savings Funds.'
            ) from None
        _validate_backup_content(destinations[name], contents[name])

    backup_all_files()
    restored = []
    for name, content in contents.items():
        destination = destinations[name]
        atomic_write_bytes(destination, content, make_backup=False)
        restored.append(destination)
    return restored


def atomic_write_bytes(
    path: Path, data: bytes, *, make_backup: bool = True, private: bool = True
) -> bool:
    """Write bytes via a temporary file and atomically replace the target.

    Returns True when the file content changed.  Existing content is backed up
    before replacement so a crash cannot leave a truncated data file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            if path.read_bytes() == data:
                if private:
                    _set_private_permissions(path)
                return False
        except OSError:
            pass

    if make_backup:
        backup_file(path)

    fd, temporary_name = tempfile.mkstemp(
        prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
        if private:
            _set_private_permissions(path)
    except Exception:
        with suppress(OSError):
            temporary_path.unlink()
        raise
    return True


def atomic_write_text(path: Path, text: str, **kwargs) -> bool:
    return atomic_write_bytes(path, text.encode('utf-8'), **kwargs)


def quarantine_file(path: Path) -> Path:
    """Move a corrupt file aside so it is never overwritten by empty data."""
    path = Path(path)
    destination = path.with_name(f'{path.name}.corrupt-{_timestamp()}')
    os.replace(path, destination)
    return destination


def _corrupt(path: Path, detail: str) -> DataCorruptionError:
    quarantine_path = quarantine_file(path)
    return DataCorruptionError(
        path,
        f'Could not read {path.name}: {detail}. The file was preserved.',
        quarantine_path,
    )


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise _corrupt(path, 'file is not valid UTF-8') from None
    _set_private_permissions(path)
    return text


def parse_balance_text(text: str) -> Decimal | None:
    """Parse balance file contents without touching the filesystem.

    Bare ``-1`` remains the legacy "not set" sentinel. Other negative values
    are real overdraft balances and are preserved.
    """
    text = text.strip()
    if not text or text == '-1':
        return None
    try:
        return parse_signed_money(text)
    except ValueError:
        raise ValueError('expected a number') from None


def load_balance_from_txt() -> Decimal | None:
    """Return the saved account balance, or None when it has not been set."""
    text = _read_text(ACCOUNT_BALANCE_FILE)
    if text is None:
        return None
    try:
        return parse_balance_text(text)
    except ValueError as exc:
        raise _corrupt(ACCOUNT_BALANCE_FILE, str(exc)) from None


def save_balance_to_txt(account_balance) -> bool:
    balance = parse_signed_money(account_balance)
    return atomic_write_text(ACCOUNT_BALANCE_FILE, str(balance))


def _parse_target_date(value) -> datetime | None:
    if value is None or value == '' or value == 'None':
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError('target_date must be a date string')
    return datetime.strptime(value, '%m/%d/%Y')


def _schema_version(document) -> int:
    if isinstance(document, list):
        return 0
    if not isinstance(document, dict):
        return 0
    version = document.get('version', 0)
    if version is None:
        return 0
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise ValueError('invalid schema version')
    return version


def _guard_schema_version(document) -> None:
    version = _schema_version(document)
    if version > SCHEMA_VERSION:
        raise FutureSchemaVersion(
            f'document version {version} is newer than supported version '
            f'{SCHEMA_VERSION}; update Savings Funds to read it'
        )


def migrate_funds_document(document) -> dict:
    """Return a funds document in the current schema shape.

    Money values from older versions may be floats or strings; the fund parser
    accepts both and the next save writes canonical decimal strings.
    """
    _guard_schema_version(document)
    if isinstance(document, dict):
        result = dict(document)
        items = document.get('funds')
    elif isinstance(document, list):
        result = {}
        items = document
    else:
        raise ValueError('expected a funds object or list')
    if not isinstance(items, list):
        raise ValueError('expected a list of funds')
    result['version'] = SCHEMA_VERSION
    result['funds'] = items
    return result


def migrate_budget_document(document) -> dict:
    """Return a budget document in the current schema shape."""
    _guard_schema_version(document)
    if isinstance(document, dict):
        result = dict(document)
        items = document.get('categories', [])
    elif isinstance(document, list):
        result = {}
        items = document
    else:
        raise ValueError('expected a budget object or list')
    if not isinstance(items, list):
        raise ValueError('expected a list of budget categories')
    period = result.get('period') or current_period()
    datetime.strptime(period, '%Y-%m')
    result['version'] = SCHEMA_VERSION
    result['period'] = period
    result['categories'] = items
    return result


def migrate_budget_history_document(document) -> dict:
    """Return a budget-history document in the current schema shape."""
    _guard_schema_version(document)
    if isinstance(document, dict):
        result = dict(document)
        periods = document.get('periods')
    elif isinstance(document, list):
        result = {}
        periods = document
    else:
        raise ValueError('expected a budget-history object or list')
    if not isinstance(periods, list):
        raise ValueError('expected a list of budget periods')
    result['version'] = SCHEMA_VERSION
    result['periods'] = periods
    return result


def _document_id(value, seen_ids: set[str], label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        identifier = uuid4().hex
        seen_ids.add(identifier)
        return identifier
    identifier = value.strip()
    if identifier in seen_ids:
        # Regenerating a duplicate would orphan generated budget rows and
        # silently change persisted references. Quarantine instead.
        raise ValueError(f'duplicate {label} id {identifier!r}')
    seen_ids.add(identifier)
    return identifier


def _fund_from_dict(item: dict, seen_ids: set[str]) -> Fund:
    if not isinstance(item, dict):
        raise ValueError('each fund must be an object')
    name = item.get('name')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('fund name is required')

    fund_id = _document_id(item.get('id'), seen_ids, 'fund')

    return Fund(
        name=name,
        target=item.get('target'),
        initial_balance=item.get('balance', 0),
        target_date=_parse_target_date(item.get('target_date')),
        recurring_transfer=item.get('recurring_transfer', 0),
        fund_id=fund_id,
    )


def parse_funds_text(text: str) -> list[Fund]:
    """Parse a funds document, migrating and validating every fund entry."""
    document = migrate_funds_document(json.loads(text))
    seen_ids: set[str] = set()
    return [_fund_from_dict(item, seen_ids) for item in document['funds']]


def load_funds_from_json() -> list[Fund]:
    text = _read_text(FUNDS_FILE)
    if text is None or not text.strip():
        return []
    try:
        return parse_funds_text(text)
    except FutureSchemaVersion as exc:
        raise UnsupportedSchemaError(FUNDS_FILE, str(exc)) from None
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise _corrupt(FUNDS_FILE, str(exc)) from None


def fund_to_dict(fund: Fund) -> dict:
    return {
        'id': fund.id,
        'name': fund.name,
        'target': str(fund.target),
        'balance': str(fund.balance),
        'target_date': fund.target_date_as_str(),
        'recurring_transfer': str(fund.recurring_transfer),
    }


def save_funds_to_json(funds: list[Fund]) -> bool:
    document = {
        'version': SCHEMA_VERSION,
        'funds': [fund_to_dict(fund) for fund in funds],
    }
    return atomic_write_text(FUNDS_FILE, json.dumps(document, indent=4) + '\n')


def _category_from_dict(
    item: dict,
    funds_by_name: dict[str, Fund],
    seen_ids: set[str],
) -> BudgetCategory:
    if not isinstance(item, dict):
        raise ValueError('each budget category must be an object')
    name = item.get('name')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('budget category name is required')

    category_id = _document_id(item.get('id'), seen_ids, 'budget category')

    source_fund_id = item.get('source_fund_id')
    if not isinstance(source_fund_id, str) or not source_fund_id:
        source_fund_id = None
    if source_fund_id is None:
        legacy_name = item.get('source_fund')
        if isinstance(legacy_name, str):
            fund = funds_by_name.get(legacy_name)
            source_fund_id = fund.id if fund is not None else None

    return BudgetCategory(
        name=name,
        budgeted=cast(Decimal, item.get('budgeted')),
        spent=item.get('spent', 0),
        kind=item.get('kind', 'expense'),
        source_fund_id=source_fund_id or None,
        category_id=category_id,
    )


def parse_budget_text(text: str, funds: list[Fund] | None = None) -> BudgetState:
    """Parse a budget document, migrating and validating every entry."""
    funds_by_name = {fund.name: fund for fund in (funds or [])}
    document = migrate_budget_document(json.loads(text))
    seen_ids: set[str] = set()
    categories = [
        _category_from_dict(item, funds_by_name, seen_ids)
        for item in document['categories']
    ]
    return BudgetState(categories, document['period'])


def load_budget_from_json(funds: list[Fund] | None = None) -> BudgetState:
    text = _read_text(BUDGET_FILE)
    if text is None or not text.strip():
        return BudgetState([], current_period())
    try:
        return parse_budget_text(text, funds)
    except FutureSchemaVersion as exc:
        raise UnsupportedSchemaError(BUDGET_FILE, str(exc)) from None
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise _corrupt(BUDGET_FILE, str(exc)) from None


def category_to_dict(category: BudgetCategory) -> dict:
    item = {
        'id': category.category_id,
        'name': category.name,
        'budgeted': str(category.budgeted),
        'spent': str(category.spent),
        'kind': category.kind,
    }
    if category.source_fund_id is not None:
        item['source_fund_id'] = category.source_fund_id
    return item


def save_budget_to_json(state: BudgetState) -> bool:
    document = {
        'version': SCHEMA_VERSION,
        'period': state.period,
        'categories': [category_to_dict(category) for category in state.categories],
    }
    return atomic_write_text(BUDGET_FILE, json.dumps(document, indent=4) + '\n')


def parse_budget_history_text(text: str) -> list[dict]:
    """Parse archived budget periods, migrating and validating their shape."""
    document = migrate_budget_history_document(json.loads(text))
    periods = document['periods']
    for period in periods:
        if not isinstance(period, dict):
            raise ValueError('each budget period must be an object')
        period_name = period.get('period')
        if not isinstance(period_name, str):
            raise ValueError('budget period is required')
        datetime.strptime(period_name, '%Y-%m')
        categories = period.get('categories', [])
        if not isinstance(categories, list):
            raise ValueError('budget period categories must be a list')
        if any(not isinstance(category, dict) for category in categories):
            raise ValueError('each archived budget category must be an object')
    return periods


def load_budget_history() -> list[dict]:
    text = _read_text(BUDGET_HISTORY_FILE)
    if text is None or not text.strip():
        return []
    try:
        return parse_budget_history_text(text)
    except FutureSchemaVersion as exc:
        raise UnsupportedSchemaError(BUDGET_HISTORY_FILE, str(exc)) from None
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise _corrupt(BUDGET_HISTORY_FILE, str(exc)) from None


def save_budget_history(periods: list[dict]) -> bool:
    document = {'version': SCHEMA_VERSION, 'periods': periods}
    return atomic_write_text(BUDGET_HISTORY_FILE, json.dumps(document, indent=4) + '\n')


def archive_budget(state: BudgetState) -> bool:
    """Archive a period snapshot, replacing any earlier snapshot for it.

    Replacing makes rollover and retry safe: if the budget save fails after the
    archive succeeds, the next attempt cannot create a duplicate period.
    """
    periods = load_budget_history()
    snapshot = {
        'period': state.period,
        'archived_at': datetime.now().isoformat(timespec='seconds'),
        'categories': [category_to_dict(category) for category in state.categories],
    }
    periods = [period for period in periods if period.get('period') != state.period]
    periods.append(snapshot)
    periods.sort(key=lambda period: period.get('period', ''))
    return save_budget_history(periods)


def rollover_budget(state: BudgetState, today: datetime | None = None) -> bool:
    """Archive and reset a budget that belongs to an earlier month.

    The operation is idempotent: archives are keyed by period, and a clock that
    moves backwards never rolls a newer budget back to an older one.
    """
    new_period = current_period(today)
    if state.period == new_period:
        return False
    if state.period > new_period:
        return False
    archive_budget(state)
    for category in state.categories:
        category.reset_spent()
    state.period = new_period
    return True


def reset_budget_period(state: BudgetState, today: datetime | None = None) -> bool:
    """Archive the current snapshot and start over in the current month."""
    archive_budget(state)
    for category in state.categories:
        category.reset_spent()
    state.period = current_period(today)
    return True
