"""Table metadata and snapshot diffing used by the operation log."""

import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SyncTable:
    name: str
    primary_key: tuple[str, ...]
    order: int


SYNC_TABLES: tuple[SyncTable, ...] = (
    SyncTable('category_groups', ('id',), 0),
    SyncTable('budget_categories', ('id',), 1),
    SyncTable('accounts', ('id',), 2),
    SyncTable('funds', ('id',), 3),
    SyncTable('transactions', ('id',), 4),
    SyncTable('budget_allocations', ('period', 'category_id'), 5),
    SyncTable('budget_history', ('period',), 6),
    SyncTable('fund_contributions', ('id',), 7),
)

TABLES_BY_NAME = {table.name: table for table in SYNC_TABLES}

SNAPSHOT_KEY_SEPARATOR = '\x1f'


def row_key(table: SyncTable, row: dict[str, Any]) -> str:
    return SNAPSHOT_KEY_SEPARATOR.join(str(row[column]) for column in table.primary_key)


def row_identity(table: SyncTable, row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row[column] for column in table.primary_key)


def snapshot_tables(connection: sqlite3.Connection) -> dict[str, dict[str, dict]]:
    """Read all synchronized rows keyed by table and primary-key string."""
    snapshot: dict[str, dict[str, dict]] = {}
    for table in SYNC_TABLES:
        rows = connection.execute(f'SELECT * FROM {table.name}').fetchall()
        snapshot[table.name] = {row_key(table, dict(row)): dict(row) for row in rows}
    return snapshot


def diff_snapshots(
    before: dict[str, dict[str, dict]], after: dict[str, dict[str, dict]]
) -> list[dict]:
    """Return row-level changes between two database snapshots."""
    changes: list[dict] = []
    for table in SYNC_TABLES:
        before_rows = before.get(table.name, {})
        after_rows = after.get(table.name, {})
        for key in sorted(set(before_rows) | set(after_rows)):
            old_row = before_rows.get(key)
            new_row = after_rows.get(key)
            if old_row == new_row:
                continue
            identity_row = new_row if new_row is not None else old_row
            assert identity_row is not None
            changes.append(
                {
                    'table': table.name,
                    'key': list(row_identity(table, identity_row)),
                    'before': old_row,
                    'after': new_row,
                }
            )
    return changes


def decode_row_key(table: SyncTable, key: list[Any]) -> tuple[Any, ...]:
    if len(key) != len(table.primary_key):
        raise ValueError(f'invalid key for {table.name}')
    return tuple(key)
