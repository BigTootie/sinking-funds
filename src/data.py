"""Budget model bridges, database backups, and portable exports.

All runtime state lives in the SQLite database managed by :mod:`ledger`.
"""

from __future__ import annotations

import sqlite3
from contextlib import suppress
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from budget import BudgetCategory, BudgetState, current_period
from fund import Fund

BACKUP_LIMIT = 10


class DataFileError(Exception):
    """A database backup or export operation failed."""


def _ledger_for(ledger=None):
    if ledger is not None:
        return ledger
    from ledger import Ledger

    return Ledger()


def _set_private_permissions(path: Path, *, directory: bool = False) -> None:
    with suppress(OSError):
        path.chmod(0o700 if directory else 0o600)


def _timestamp() -> str:
    return datetime.now().strftime('%Y%m%d-%H%M%S-%f')


def category_to_dict(category: BudgetCategory) -> dict:
    return {
        'name': category.name,
        'budgeted': str(category.budgeted),
        'spent': str(category.spent),
        'kind': category.kind,
        'source_fund_id': category.source_fund_id,
        'category_id': category.category_id,
        'group': category.group,
        'group_id': category.group_id,
        'sort_order': category.sort_order,
    }


def load_funds(ledger=None) -> list[Fund]:
    return _ledger_for(ledger).list_funds()


def save_funds(funds: list[Fund], ledger=None) -> bool:
    return _ledger_for(ledger).replace_funds(funds)


def load_budget(period: str | None = None, ledger=None) -> BudgetState:
    ledger = _ledger_for(ledger)
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
        categories.append(
            BudgetCategory(
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
        )
    return BudgetState(categories, period)


def load_budget_history(ledger=None) -> list[dict]:
    return _ledger_for(ledger).list_budget_history()


def save_budget_history(periods: list[dict], ledger=None) -> bool:
    ledger = _ledger_for(ledger)
    changed = False
    for snapshot in periods:
        changed = ledger.save_budget_history(snapshot) or changed
    return changed


def archive_budget(state: BudgetState, ledger=None) -> bool:
    snapshot = {
        'period': state.period,
        'archived_at': datetime.now().isoformat(timespec='seconds'),
        'categories': [category_to_dict(category) for category in state.categories],
    }
    return _ledger_for(ledger).save_budget_history(snapshot)


def rollover_budget(
    state: BudgetState, today: datetime | None = None, ledger=None
) -> bool:
    new_period = current_period(today)
    if state.period == new_period or state.period > new_period:
        return False
    archive_budget(state, ledger)
    for category in state.categories:
        category.reset_spent()
    state.period = new_period
    return True


def reset_budget_period(
    state: BudgetState, today: datetime | None = None, ledger=None
) -> bool:
    archive_budget(state, ledger)
    for category in state.categories:
        category.reset_spent()
    state.period = current_period(today)
    return True


def budget_history_for(period: str, ledger=None) -> dict | None:
    return next(
        (item for item in load_budget_history(ledger) if item.get('period') == period),
        None,
    )


def database_backup_dir(ledger=None) -> Path:
    ledger = _ledger_for(ledger)
    directory = Path(ledger.path).parent / 'backups'
    directory.mkdir(parents=True, exist_ok=True)
    _set_private_permissions(directory, directory=True)
    return directory


def _prune_database_backups(directory: Path) -> None:
    candidates = sorted(directory.glob('database-*.db'), key=lambda item: item.name)
    for old_backup in candidates[:-BACKUP_LIMIT]:
        with suppress(OSError):
            old_backup.unlink()


def backup_database(ledger=None) -> Path:
    """Create a consistent SQLite snapshot using SQLite's backup API."""
    ledger = _ledger_for(ledger)
    directory = database_backup_dir(ledger)
    destination = directory / f'database-{_timestamp()}.db'
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
    _prune_database_backups(directory)
    return destination


def latest_database_backup(ledger=None) -> Path | None:
    ledger = _ledger_for(ledger)
    candidates = sorted(database_backup_dir(ledger).glob('database-*.db'))
    return candidates[-1] if candidates else None


def restore_database(source: Path, ledger=None) -> Path:
    """Validate and restore a database snapshot, preserving the current DB."""
    ledger = _ledger_for(ledger)
    source = Path(source)
    if not source.is_file():
        raise ValueError('database backup does not exist')
    probe = sqlite3.connect(source)
    try:
        try:
            integrity = probe.execute('PRAGMA integrity_check').fetchone()[0]
            tables = {
                row[0]
                for row in probe.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        except sqlite3.DatabaseError as exc:
            raise ValueError(f'database backup is not readable: {exc}') from None
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


load_budget_history_from_db = load_budget_history
