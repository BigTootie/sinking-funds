"""Legacy import/export helpers, SQLite migrations, and database backups.

The runtime source of truth is the single SQLite database managed by
``ledger.py``. JSON and text helpers here exist for one-time migration,
compatibility parsing, and explicit import/export.
"""

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
        due_day=item.get('due_day', 31),
        kind=item.get('kind', 'savings_goal'),
        priority=item.get('priority', 0),
        status=item.get('status', 'active'),
        source_account_id=item.get('source_account_id'),
        destination_account_id=item.get('destination_account_id'),
        notes=item.get('notes', ''),
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
        'due_day': fund.due_day,
        'kind': fund.kind,
        'priority': fund.priority,
        'status': fund.status,
        'source_account_id': fund.source_account_id,
        'destination_account_id': fund.destination_account_id,
        'notes': fund.notes,
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
        group=item.get('group', 'General'),
        group_id=item.get('group_id'),
        sort_order=item.get('sort_order', 0),
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
    item: dict[str, object] = {
        'id': category.category_id,
        'name': category.name,
        'budgeted': str(category.budgeted),
        'spent': str(category.spent),
        'kind': category.kind,
    }
    if category.source_fund_id is not None:
        item['source_fund_id'] = category.source_fund_id
    if category.group != 'General':
        item['group'] = category.group
        item['group_id'] = category.group_id
    if category.sort_order:
        item['sort_order'] = category.sort_order
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


def _ledger_for(ledger=None):
    if ledger is not None:
        return ledger
    from ledger import Ledger

    return Ledger()


def load_budget_history(ledger=None) -> list[dict]:
    if ledger is not None:
        return ledger.list_budget_history()
    text = _read_text(BUDGET_HISTORY_FILE)
    if text is None or not text.strip():
        return []
    try:
        return parse_budget_history_text(text)
    except FutureSchemaVersion as exc:
        raise UnsupportedSchemaError(BUDGET_HISTORY_FILE, str(exc)) from None
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise _corrupt(BUDGET_HISTORY_FILE, str(exc)) from None


def save_budget_history(periods: list[dict], ledger=None) -> bool:
    if ledger is not None:
        changed = False
        for snapshot in periods:
            changed = ledger.save_budget_history(snapshot) or changed
        return changed
    document = {'version': SCHEMA_VERSION, 'periods': periods}
    return atomic_write_text(BUDGET_HISTORY_FILE, json.dumps(document, indent=4) + '\n')


def archive_budget(state: BudgetState, ledger=None) -> bool:
    """Archive a period snapshot, replacing any earlier snapshot for it.

    Replacing makes rollover and retry safe: if the budget save fails after the
    archive succeeds, the next attempt cannot create a duplicate period.
    """
    snapshot = {
        'period': state.period,
        'archived_at': datetime.now().isoformat(timespec='seconds'),
        'categories': [category_to_dict(category) for category in state.categories],
    }
    if ledger is not None:
        return ledger.save_budget_history(snapshot)
    periods = load_budget_history()
    periods = [period for period in periods if period.get('period') != state.period]
    periods.append(snapshot)
    periods.sort(key=lambda period: period.get('period', ''))
    return save_budget_history(periods)


def rollover_budget(
    state: BudgetState, today: datetime | None = None, ledger=None
) -> bool:
    """Archive and reset a budget that belongs to an earlier month.

    The operation is idempotent: archives are keyed by period, and a clock that
    moves backwards never rolls a newer budget back to an older one.
    """
    new_period = current_period(today)
    if state.period == new_period:
        return False
    if state.period > new_period:
        return False
    archive_budget(state, ledger)
    for category in state.categories:
        category.reset_spent()
    state.period = new_period
    return True


def reset_budget_period(
    state: BudgetState, today: datetime | None = None, ledger=None
) -> bool:
    """Archive the current snapshot and start over in the current month."""
    archive_budget(state, ledger)
    for category in state.categories:
        category.reset_spent()
    state.period = current_period(today)
    return True


# ---------------------------------------------------------------------------
# SQLite runtime repositories
# ---------------------------------------------------------------------------


def migrate_legacy_json_data(ledger=None, *, force: bool = False) -> bool:
    """Import legacy JSON once; SQLite is the source of truth afterward."""
    ledger = _ledger_for(ledger)
    if not force and ledger.get_meta('legacy_json_migrated') == '1':
        return False

    balance = load_balance_from_txt()
    funds = load_funds_from_json()
    budget = load_budget_from_json(funds)
    history = load_budget_history()

    legacy_sources = any(
        path.exists()
        for path in (
            ACCOUNT_BALANCE_FILE,
            FUNDS_FILE,
            BUDGET_FILE,
            BUDGET_HISTORY_FILE,
        )
    )
    already_seeded = ledger.get_meta('legacy_seeded') == '1'
    has_database_data = bool(
        ledger.list_funds()
        or ledger.list_accounts(include_archived=True)
        or ledger.latest_budget_period()
    )
    if not already_seeded and not has_database_data and legacy_sources:
        ledger.seed_legacy(balance, funds, budget.categories, budget.period)
    elif not ledger.list_funds() and funds:
        ledger.replace_funds(funds)
    if history:
        for snapshot in history:
            ledger.save_budget_history(snapshot)
    ledger.set_meta('legacy_json_migrated', '1')
    return True


def load_funds(ledger=None) -> list[Fund]:
    ledger = _ledger_for(ledger)
    if ledger.get_meta('legacy_json_migrated') != '1':
        migrate_legacy_json_data(ledger)
    return ledger.list_funds()


def save_funds(funds: list[Fund], ledger=None) -> bool:
    return _ledger_for(ledger).replace_funds(funds)


def load_budget(period: str | None = None, ledger=None) -> BudgetState:
    ledger = _ledger_for(ledger)
    if ledger.get_meta('legacy_json_migrated') != '1':
        migrate_legacy_json_data(ledger)
    state = ledger.load_budget(period)
    if state is None:
        return BudgetState([], period or current_period())
    return state


def save_budget(state: BudgetState, ledger=None) -> bool:
    return _ledger_for(ledger).replace_budget(state.period, state.categories)


def copy_plan_forward(
    source: BudgetState | None,
    period: str,
    ledger=None,
) -> BudgetState:
    """Copy planned amounts into a future month, clearing actual spending."""
    ledger = _ledger_for(ledger)
    if source is None:
        source = ledger.load_budget()
    if source is None:
        return BudgetState([], period)
    categories = []
    for index, category in enumerate(source.categories):
        copied = BudgetCategory(
            category.name,
            category.budgeted,
            Decimal('0.00'),
            category.kind,
            category.source_fund_id,
            category.category_id,
            category.group,
            category.group_id,
            index,
        )
        categories.append(copied)
    return BudgetState(categories, period)


def budget_history_for(period: str, ledger=None) -> dict | None:
    snapshot = next(
        (item for item in load_budget_history(ledger) if item.get('period') == period),
        None,
    )
    return snapshot


# ---------------------------------------------------------------------------
# Database backup / restore helpers
# ---------------------------------------------------------------------------


def database_backup_dir(ledger=None) -> Path:
    ledger = _ledger_for(ledger)
    directory = Path(ledger.path).parent / 'backups'
    directory.mkdir(parents=True, exist_ok=True)
    _set_private_permissions(directory, directory=True)
    return directory


def backup_database(ledger=None) -> Path:
    """Create a consistent SQLite snapshot using SQLite's backup API."""
    import sqlite3

    ledger = _ledger_for(ledger)
    destination = database_backup_dir(ledger) / f'database-{_timestamp()}.db'
    source = sqlite3.connect(ledger.path)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    _set_private_permissions(destination)
    return destination


def latest_database_backup(ledger=None) -> Path | None:
    ledger = _ledger_for(ledger)
    candidates = sorted(database_backup_dir(ledger).glob('database-*.db'))
    return candidates[-1] if candidates else None


def restore_database(source: Path, ledger=None) -> Path:
    """Validate and restore a database snapshot, preserving the current DB."""
    import sqlite3

    ledger = _ledger_for(ledger)
    source = Path(source)
    if not source.is_file():
        raise ValueError('database backup does not exist')
    probe = sqlite3.connect(source)
    try:
        integrity = probe.execute('PRAGMA integrity_check').fetchone()[0]
        tables = {
            row[0]
            for row in probe.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        probe.close()
    if integrity != 'ok':
        raise ValueError('database backup failed its integrity check')
    if not {'accounts', 'transactions', 'funds', 'budget_allocations'} <= tables:
        raise ValueError('database backup is not a Savings Funds database')
    safety = backup_database(ledger)
    ledger.path.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(ledger.path)
    try:
        source_connection.backup(target_connection)
        target_connection.execute('PRAGMA journal_mode = WAL')
        target_connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:
        target_connection.close()
        source_connection.close()
    return safety


def export_database(destination: Path | None = None, ledger=None) -> Path:
    """Export a consistent SQLite snapshot (including WAL contents)."""
    import sqlite3

    ledger = _ledger_for(ledger)
    if destination is None:
        export_dir = Path(ledger.path).parent / 'exports'
        export_dir.mkdir(parents=True, exist_ok=True)
        destination = export_dir / f'savings-funds-{_timestamp()}.db'
    else:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(ledger.path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    _set_private_permissions(destination)
    return destination


# Descriptive aliases used by integrations that prefer explicit storage names.
load_funds_from_db = load_funds
save_funds_to_db = save_funds
load_budget_from_db = load_budget
save_budget_to_db = save_budget
load_budget_history_from_db = load_budget_history
migrate_legacy_data = migrate_legacy_json_data
