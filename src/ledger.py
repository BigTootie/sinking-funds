"""The single local SQLite database: ledger, funds, budget, sync, and settings.

Money is stored as integer minor units. SQLite is the only runtime data store;
JSON is used only for explicit user-requested import/export.
"""

import csv
import json
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import uuid4

from paths import get_data_dir
from sync.protocol import ProtocolError, verify
from sync.state import (
    SYNC_TABLES,
    TABLES_BY_NAME,
    diff_snapshots,
    snapshot_tables,
)

LEDGER_DB = get_data_dir() / 'ledger.db'
SCHEMA_VERSION = 3


class LedgerError(Exception):
    """A ledger validation or persistence error."""


def money_to_minor(value: Decimal | str | int | float) -> int:
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if not amount.is_finite():
        raise ValueError('amount must be finite')
    return int((amount * 100).quantize(Decimal('1')))


def minor_to_money(value: int) -> Decimal:
    return (Decimal(value) / 100).quantize(Decimal('0.01'))


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _date(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError('date must be YYYY-MM-DD') from None


def _sync_mutation(method):
    """Capture all row changes made by a public ledger mutation."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._sync_capture():
            return method(self, *args, **kwargs)

    return wrapped


@dataclass
class Account:
    id: str
    name: str
    type: str
    currency: str
    opening_balance: Decimal
    archived: bool
    balance: Decimal = Decimal('0')
    cleared_balance: Decimal = Decimal('0')


@dataclass
class Transaction:
    id: str
    account_id: str
    account_name: str
    date: str
    payee: str
    memo: str
    amount: Decimal
    category: str
    cleared: bool
    transfer_id: str | None
    fund_id: str | None
    budget_excluded: bool = False
    affects_balance: bool = True
    contribution_id: str | None = None

    @property
    def classification(self) -> str:
        if self.transfer_id:
            return 'transfer'
        if self.fund_id and self.budget_excluded:
            return 'savings'
        if self.category in {'Opening balance', 'Adjustment'}:
            return 'adjustment'
        if self.amount < 0:
            return 'expense'
        if self.amount > 0:
            return 'income'
        return 'zero'


@dataclass
class FundContribution:
    id: str
    fund_id: str
    fund_name: str
    period: str
    kind: str
    amount: Decimal
    due_date: str
    posted_at: str
    status: str
    budget_excluded: bool
    transaction_id: str | None
    memo: str = ''


class Ledger:
    """A small repository around the local SQLite ledger."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or LEDGER_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.on_sync_op: Callable[[], None] | None = None
        self._sync_logging = True
        self._sync_depth = 0
        self._migrate()
        with suppress(OSError):
            self.path.chmod(0o600)

    @contextmanager
    def _sync_capture(self):
        """Record one operation containing all rows changed by a mutation."""
        if not self._sync_logging:
            yield
            return
        if self._sync_depth:
            self._sync_depth += 1
            try:
                yield
            finally:
                self._sync_depth -= 1
            return
        self._sync_depth = 1
        before = self.sync_snapshot()
        completed = False
        try:
            yield
            completed = True
        finally:
            self._sync_depth = 0
        if not completed:
            return
        after = self.sync_snapshot()
        changes = diff_snapshots(before, after)
        if changes:
            self._append_sync_operation(changes)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA journal_mode = WAL')
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {
            row['name']
            for row in connection.execute(f'PRAGMA table_info({table})').fetchall()
        }

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        if column not in self._columns(connection, table):
            connection.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    opening_balance_minor INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id),
                    date TEXT NOT NULL,
                    payee TEXT NOT NULL,
                    memo TEXT NOT NULL DEFAULT '',
                    amount_minor INTEGER NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    cleared INTEGER NOT NULL DEFAULT 0,
                    transfer_id TEXT,
                    fund_id TEXT,
                    budget_excluded INTEGER NOT NULL DEFAULT 0,
                    affects_balance INTEGER NOT NULL DEFAULT 1,
                    contribution_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS transactions_date_idx
                    ON transactions(date);
                CREATE INDEX IF NOT EXISTS transactions_account_idx
                    ON transactions(account_id);
                CREATE TABLE IF NOT EXISTS funds (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    balance_minor INTEGER NOT NULL DEFAULT 0,
                    target_minor INTEGER NOT NULL DEFAULT 0,
                    target_date TEXT,
                    recurring_transfer_minor INTEGER NOT NULL DEFAULT 0,
                    due_day INTEGER NOT NULL DEFAULT 31,
                    kind TEXT NOT NULL DEFAULT 'savings_goal',
                    priority INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    source_account_id TEXT,
                    destination_account_id TEXT,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS category_groups (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'expense',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS budget_categories (
                    id TEXT PRIMARY KEY,
                    group_id TEXT REFERENCES category_groups(id),
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'expense',
                    rollover INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS budget_allocations (
                    period TEXT NOT NULL,
                    category_id TEXT NOT NULL REFERENCES budget_categories(id),
                    budgeted_minor INTEGER NOT NULL DEFAULT 0,
                    spent_minor INTEGER NOT NULL DEFAULT 0,
                    source_fund_id TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (period, category_id)
                );
                CREATE TABLE IF NOT EXISTS budget_history (
                    period TEXT PRIMARY KEY,
                    archived_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fund_contributions (
                    id TEXT PRIMARY KEY,
                    fund_id TEXT NOT NULL,
                    period TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'recurring',
                    amount_minor INTEGER NOT NULL,
                    due_date TEXT NOT NULL,
                    posted_at TEXT NOT NULL,
                    transaction_id TEXT,
                    status TEXT NOT NULL DEFAULT 'posted',
                    budget_excluded INTEGER NOT NULL DEFAULT 1,
                    memo TEXT NOT NULL DEFAULT ''
                );
                CREATE UNIQUE INDEX IF NOT EXISTS fund_contributions_recurring_idx
                    ON fund_contributions(fund_id, period)
                    WHERE kind = 'recurring';
                CREATE INDEX IF NOT EXISTS fund_contributions_period_idx
                    ON fund_contributions(period);
                CREATE TABLE IF NOT EXISTS sync_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sync_ops (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    lamport INTEGER NOT NULL,
                    entity TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    op TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    applied INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS sync_ops_lamport_idx
                    ON sync_ops(device_id, lamport);
                CREATE UNIQUE INDEX IF NOT EXISTS sync_ops_device_lamport_idx
                    ON sync_ops(device_id, lamport);
                CREATE TABLE IF NOT EXISTS sync_conflicts (
                    id TEXT PRIMARY KEY,
                    op_id TEXT NOT NULL UNIQUE,
                    device_id TEXT NOT NULL,
                    lamport INTEGER NOT NULL,
                    entity TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolution TEXT
                );
                """
            )
            connection.execute('DROP TABLE IF EXISTS budget_imports')
            # Additive migration for databases created by v0.3.
            for column, definition in (
                ('budget_excluded', 'INTEGER NOT NULL DEFAULT 0'),
                ('affects_balance', 'INTEGER NOT NULL DEFAULT 1'),
                ('contribution_id', 'TEXT'),
            ):
                self._ensure_column(connection, 'transactions', column, definition)
            for column, definition in (
                ('due_day', 'INTEGER NOT NULL DEFAULT 31'),
                ('kind', "TEXT NOT NULL DEFAULT 'savings_goal'"),
                ('priority', 'INTEGER NOT NULL DEFAULT 0'),
                ('status', "TEXT NOT NULL DEFAULT 'active'"),
                ('source_account_id', 'TEXT'),
                ('destination_account_id', 'TEXT'),
                ('notes', "TEXT NOT NULL DEFAULT ''"),
                ('created_at', 'TEXT'),
                ('updated_at', 'TEXT'),
            ):
                self._ensure_column(connection, 'funds', column, definition)

            now = _now()
            for version in range(1, SCHEMA_VERSION + 1):
                connection.execute(
                    'INSERT OR IGNORE INTO migrations(version, applied_at) '
                    'VALUES (?, ?)',
                    (version, now),
                )
            connection.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
            connection.execute(
                'INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)',
                ('schema_version', str(SCHEMA_VERSION)),
            )
            device = connection.execute(
                'SELECT value FROM meta WHERE key = ?', ('device_id',)
            ).fetchone()
            if device is None:
                connection.execute(
                    'INSERT INTO meta(key, value) VALUES (?, ?)',
                    ('device_id', uuid4().hex),
                )
            migrated_default = connection.execute(
                'SELECT 1 FROM meta WHERE key = ?', ('default_account_migrated',)
            ).fetchone()
            if migrated_default is None:
                accounts = connection.execute(
                    'SELECT id, name, type FROM accounts'
                ).fetchall()
                if (
                    len(accounts) == 1
                    and accounts[0]['name'] == 'Checking'
                    and accounts[0]['type'] == 'checking'
                ):
                    connection.execute(
                        "UPDATE accounts SET name = 'Savings', type = 'savings' "
                        'WHERE id = ?',
                        (accounts[0]['id'],),
                    )
                connection.execute(
                    'INSERT INTO meta(key, value) VALUES (?, ?)',
                    ('default_account_migrated', '1'),
                )
            balances_migrated = connection.execute(
                'SELECT 1 FROM meta WHERE key = ?', ('opening_balances_migrated',)
            ).fetchone()
            if balances_migrated is None:
                for row in connection.execute(
                    'SELECT id, opening_balance_minor FROM accounts '
                    'WHERE opening_balance_minor != 0'
                ).fetchall():
                    connection.execute(
                        'INSERT INTO transactions '
                        '(id, account_id, date, payee, memo, amount_minor, category, '
                        'cleared, transfer_id, fund_id, created_at, updated_at) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL, NULL, ?, ?)',
                        (
                            uuid4().hex,
                            row['id'],
                            date.today().isoformat(),
                            'Opening balance',
                            'Migrated opening balance',
                            row['opening_balance_minor'],
                            'Opening balance',
                            _now(),
                            _now(),
                        ),
                    )
                    connection.execute(
                        'UPDATE accounts SET opening_balance_minor = 0 WHERE id = ?',
                        (row['id'],),
                    )
                connection.execute(
                    'INSERT INTO meta(key, value) VALUES (?, ?)',
                    ('opening_balances_migrated', '1'),
                )

            connection.execute(
                'UPDATE funds SET created_at = ? WHERE created_at IS NULL',
                (now,),
            )
            connection.execute(
                'UPDATE funds SET updated_at = ? WHERE updated_at IS NULL',
                (now,),
            )

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT value FROM meta WHERE key = ?', (key,)
            ).fetchone()
            if row is not None:
                return row['value']
            # Settings supersede meta for user preferences, but keep the old
            # accessor working for callers written against earlier releases.
            row = connection.execute(
                'SELECT value FROM settings WHERE key = ?', (key,)
            ).fetchone()
            return row['value'] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                'INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)', (key, value)
            )

    # ------------------------------------------------------------------
    # Settings, migration metadata, and the v0.5 operation-log foundation
    # ------------------------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT value FROM settings WHERE key = ?', (key,)
            ).fetchone()
            return row['value'] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                'INSERT OR REPLACE INTO settings(key, value, updated_at) '
                'VALUES (?, ?, ?)',
                (key, value, _now()),
            )

    def delete_setting(self, key: str) -> None:
        with self._connect() as connection:
            connection.execute('DELETE FROM settings WHERE key = ?', (key,))

    def get_sync_state(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT value FROM sync_state WHERE key = ?', (key,)
            ).fetchone()
            return row['value'] if row else default

    def set_sync_state(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                'INSERT OR REPLACE INTO sync_state(key, value, updated_at) '
                'VALUES (?, ?, ?)',
                (key, value, _now()),
            )

    def get_migrations(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT version, applied_at FROM migrations ORDER BY version'
            ).fetchall()
        return [dict(row) for row in rows]

    def sync_snapshot(self) -> dict[str, dict[str, dict]]:
        with self._connect() as connection:
            return snapshot_tables(connection)

    def is_empty(self) -> bool:
        with self._connect() as connection:
            for table in SYNC_TABLES:
                if connection.execute(f'SELECT 1 FROM {table.name} LIMIT 1').fetchone():
                    return False
        return True

    def _device_id(self) -> str:
        device_id = self.get_meta('device_id')
        if device_id is None:
            device_id = uuid4().hex
            self.set_meta('device_id', device_id)
        return device_id

    def _append_sync_operation(
        self, changes: list[dict], *, notify: bool = True
    ) -> str:
        device_id = self._device_id()
        entity = changes[0]['table'] if len(changes) == 1 else 'batch'
        entity_id = str(changes[0]['key'][0]) if changes else ''
        with self._connect() as connection:
            row = connection.execute(
                'SELECT COALESCE(MAX(lamport), 0) FROM sync_ops WHERE device_id = ?',
                (device_id,),
            ).fetchone()
            lamport = int(row[0]) + 1
            operation_id = uuid4().hex
            connection.execute(
                'INSERT INTO sync_ops '
                '(id, device_id, lamport, entity, entity_id, op, payload, '
                'created_at, applied) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)',
                (
                    operation_id,
                    device_id,
                    lamport,
                    entity,
                    entity_id,
                    'upsert',
                    json.dumps({'changes': changes}, sort_keys=True),
                    _now(),
                ),
            )
        if notify and self.on_sync_op is not None:
            self.on_sync_op()
        return operation_id

    def ensure_sync_baseline(self) -> bool:
        """Seed the first operation from an existing v0.4 database."""
        if self.get_meta('sync_baseline') == '1' or self.is_empty():
            return False
        snapshot = self.sync_snapshot()
        changes = []
        for table in SYNC_TABLES:
            for row in snapshot.get(table.name, {}).values():
                changes.append(
                    {
                        'table': table.name,
                        'key': [row[column] for column in table.primary_key],
                        'before': None,
                        'after': row,
                    }
                )
        if changes:
            self._append_sync_operation(changes, notify=False)
        self.set_meta('sync_baseline', '1')
        return bool(changes)

    def list_sync_ops(
        self, *, device_id: str | None = None, after_lamport: int = 0
    ) -> list[dict]:
        query = 'SELECT * FROM sync_ops'
        parameters: list[Any] = []
        clauses = []
        if device_id is not None:
            clauses.append('device_id = ?')
            parameters.append(device_id)
        if after_lamport:
            clauses.append('lamport > ?')
            parameters.append(after_lamport)
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        query += ' ORDER BY device_id, lamport'
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def local_sync_ops(self, *, after_lamport: int = 0) -> list[dict]:
        return self.list_sync_ops(
            device_id=self._device_id(), after_lamport=after_lamport
        )

    def list_sync_devices(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT device_id, MAX(lamport) AS lamport, '
                'MAX(created_at) AS last_seen FROM sync_ops '
                'GROUP BY device_id ORDER BY last_seen DESC'
            ).fetchall()
        return [dict(row) for row in rows]

    def _sync_row(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        key: list[Any],
    ) -> dict | None:
        table = TABLES_BY_NAME[table_name]
        where = ' AND '.join(f'{column} = ?' for column in table.primary_key)
        row = connection.execute(
            f'SELECT * FROM {table_name} WHERE {where}', key
        ).fetchone()
        return dict(row) if row is not None else None

    def _has_recurring_duplicate(
        self, connection: sqlite3.Connection, changes: list[dict]
    ) -> bool:
        for change in changes:
            if change.get('table') != 'fund_contributions':
                continue
            after = change.get('after')
            if not after or after.get('kind') != 'recurring' or change.get('before'):
                continue
            existing = connection.execute(
                'SELECT id FROM fund_contributions '
                'WHERE fund_id = ? AND period = ? AND kind = ?',
                (after['fund_id'], after['period'], 'recurring'),
            ).fetchone()
            if existing is not None and existing['id'] != after['id']:
                return True
        return False

    def _insert_sync_op_record(
        self, connection: sqlite3.Connection, operation: dict
    ) -> None:
        payload = operation['payload']
        connection.execute(
            'INSERT OR IGNORE INTO sync_ops '
            '(id, device_id, lamport, entity, entity_id, op, payload, '
            'created_at, applied) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)',
            (
                operation['id'],
                operation['device_id'],
                operation['lamport'],
                operation['entity'],
                operation['entity_id'],
                operation.get('op', 'upsert'),
                json.dumps(payload, sort_keys=True),
                operation.get('created_at', _now()),
            ),
        )

    def apply_remote_operation(self, operation: dict) -> str:
        """Apply one verified remote operation.

        Returns ``applied``, ``duplicate``, or ``conflict``. A conflict is
        stored locally and leaves the database untouched until the user chooses.
        """
        try:
            verify(operation)
        except ProtocolError:
            raise
        with self._connect() as connection:
            existing = connection.execute(
                'SELECT 1 FROM sync_ops WHERE id = ?', (operation['id'],)
            ).fetchone()
            if existing is not None:
                return 'duplicate'
            changes = operation['payload'].get('changes')
            if not isinstance(changes, list) or not changes:
                raise ProtocolError('operation contains no changes')
            if self._has_recurring_duplicate(connection, changes):
                return 'duplicate'
            conflict = False
            changed = False
            for change in changes:
                table_name = change.get('table')
                if table_name not in TABLES_BY_NAME:
                    raise ProtocolError(f'unknown sync table: {table_name}')
                current = self._sync_row(connection, table_name, change['key'])
                if current == change.get('after'):
                    continue
                changed = True
                if current != change.get('before'):
                    conflict = True
                    break
            if not changed:
                self._insert_sync_op_record(connection, operation)
                return 'duplicate'
            if conflict:
                connection.execute(
                    'INSERT OR IGNORE INTO sync_conflicts '
                    '(id, op_id, device_id, lamport, entity, entity_id, payload, '
                    'created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (
                        uuid4().hex,
                        operation['id'],
                        operation['device_id'],
                        operation['lamport'],
                        operation['entity'],
                        operation['entity_id'],
                        json.dumps(operation, sort_keys=True),
                        _now(),
                    ),
                )
                return 'conflict'
            self._apply_changes(connection, changes)
            self._insert_sync_op_record(connection, operation)
            return 'applied'

    def _apply_changes(self, connection: sqlite3.Connection, changes: list[dict]):
        ordered = sorted(
            changes,
            key=lambda change: TABLES_BY_NAME[change['table']].order,
        )
        for change in ordered:
            table = TABLES_BY_NAME[change['table']]
            after = change.get('after')
            if after is None:
                where = ' AND '.join(f'{column} = ?' for column in table.primary_key)
                connection.execute(
                    f'DELETE FROM {table.name} WHERE {where}', change['key']
                )
                continue
            columns = list(after)
            placeholders = ', '.join('?' for _ in columns)
            connection.execute(
                f'INSERT OR REPLACE INTO {table.name} '
                f'({", ".join(columns)}) VALUES ({placeholders})',
                [after[column] for column in columns],
            )

    def list_sync_conflicts(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT * FROM sync_conflicts WHERE resolved_at IS NULL '
                'ORDER BY created_at, id'
            ).fetchall()
        return [
            {
                **dict(row),
                'operation': json.loads(row['payload']),
            }
            for row in rows
        ]

    def resolve_sync_conflict(self, conflict_id: str, resolution: str) -> dict | None:
        if resolution not in {'local', 'remote'}:
            raise ValueError('invalid conflict resolution')
        counter_changes: list[dict] = []
        with self._connect() as connection:
            row = connection.execute(
                'SELECT * FROM sync_conflicts WHERE id = ?', (conflict_id,)
            ).fetchone()
            if row is None or row['resolved_at'] is not None:
                return None
            operation = json.loads(row['payload'])
            if resolution == 'remote':
                with self._sync_logging_off():
                    self._apply_changes(connection, operation['payload']['changes'])
                self._insert_sync_op_record(connection, operation)
            else:
                for change in operation['payload']['changes']:
                    current = self._sync_row(connection, change['table'], change['key'])
                    if current != change.get('after'):
                        counter_changes.append(
                            {
                                'table': change['table'],
                                'key': change['key'],
                                'before': change.get('after'),
                                'after': current,
                            }
                        )
            connection.execute(
                'UPDATE sync_conflicts SET resolved_at = ?, resolution = ? '
                'WHERE id = ?',
                (_now(), resolution, conflict_id),
            )
        if counter_changes:
            self._append_sync_operation(counter_changes)
        return operation

    @contextmanager
    def _sync_logging_off(self):
        previous = self._sync_logging
        self._sync_logging = False
        try:
            yield
        finally:
            self._sync_logging = previous

    def apply_snapshot(self, snapshot: dict) -> bool:
        """Bootstrap an empty database from a verified snapshot."""
        if not self.is_empty():
            return False
        with self._sync_logging_off(), self._connect() as connection:
            for table in SYNC_TABLES:
                rows = snapshot.get('tables', {}).get(table.name, {})
                for row in rows.values():
                    columns = list(row)
                    placeholders = ', '.join('?' for _ in columns)
                    connection.execute(
                        f'INSERT OR REPLACE INTO {table.name} '
                        f'({", ".join(columns)}) VALUES ({placeholders})',
                        [row[column] for column in columns],
                    )
        self.set_meta('sync_baseline', '1')
        return True

    def list_accounts(self, include_archived: bool = False) -> list[Account]:
        where = '' if include_archived else 'WHERE archived = 0'
        with self._connect() as connection:
            rows = connection.execute(
                f'SELECT * FROM accounts {where} ORDER BY created_at, name'
            ).fetchall()
        accounts = []
        for row in rows:
            balance, cleared = self._balances(row['id'])
            accounts.append(
                Account(
                    id=row['id'],
                    name=row['name'],
                    type=row['type'],
                    currency=row['currency'],
                    opening_balance=minor_to_money(row['opening_balance_minor']),
                    archived=bool(row['archived']),
                    balance=balance,
                    cleared_balance=cleared,
                )
            )
        return accounts

    def _balances(self, account_id: str) -> tuple[Decimal, Decimal]:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT opening_balance_minor FROM accounts WHERE id = ?',
                (account_id,),
            ).fetchone()
            if row is None:
                raise LedgerError('account does not exist')
            total = connection.execute(
                'SELECT COALESCE(SUM(amount_minor), 0) FROM transactions '
                'WHERE account_id = ? AND affects_balance = 1',
                (account_id,),
            ).fetchone()[0]
            cleared = connection.execute(
                'SELECT COALESCE(SUM(amount_minor), 0) FROM transactions '
                'WHERE account_id = ? AND cleared = 1 AND affects_balance = 1',
                (account_id,),
            ).fetchone()[0]
        return (
            minor_to_money(row['opening_balance_minor'] + total),
            minor_to_money(row['opening_balance_minor'] + cleared),
        )

    def total_balance(self) -> Decimal:
        return sum((account.balance for account in self.list_accounts()), Decimal('0'))

    def default_account(self) -> Account | None:
        accounts = self.list_accounts()
        return accounts[0] if accounts else None

    @_sync_mutation
    def add_account(
        self,
        name: str,
        account_type: str = 'checking',
        opening_balance: Decimal | str | int = 0,
    ) -> Account:
        name = name.strip()
        if not name:
            raise LedgerError('account name is required')
        account_id = uuid4().hex
        with self._connect() as connection:
            connection.execute(
                'INSERT INTO accounts '
                '(id, name, type, currency, opening_balance_minor, archived, created_at) '
                'VALUES (?, ?, ?, ?, 0, 0, ?)',
                (account_id, name, account_type, 'USD', _now()),
            )
        self.adjust_account_balance(
            account_id,
            opening_balance,
            payee='Opening balance',
            memo='Initial deposit',
            category='Opening balance',
        )
        return next(a for a in self.list_accounts() if a.id == account_id)

    @_sync_mutation
    def update_account(self, account_id: str, name: str, account_type: str) -> None:
        name = name.strip()
        if not name:
            raise LedgerError('account name is required')
        with self._connect() as connection:
            cursor = connection.execute(
                'UPDATE accounts SET name = ?, type = ? WHERE id = ?',
                (name, account_type, account_id),
            )
            if cursor.rowcount == 0:
                raise LedgerError('account does not exist')

    @_sync_mutation
    def adjust_account_balance(
        self,
        account_id: str,
        target: Decimal | str | int,
        *,
        payee: str = 'Balance adjustment',
        memo: str = 'Manual account balance update',
        category: str = 'Adjustment',
    ) -> None:
        account = next(
            (
                item
                for item in self.list_accounts(include_archived=True)
                if item.id == account_id
            ),
            None,
        )
        if account is None:
            raise LedgerError('account does not exist')
        difference = Decimal(str(target)) - account.balance
        if difference == 0:
            return
        self.add_transaction(
            account_id,
            date.today(),
            payee,
            memo,
            difference,
            category,
        )

    @_sync_mutation
    def archive_account(self, account_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                'UPDATE accounts SET archived = 1 WHERE id = ?', (account_id,)
            )

    @_sync_mutation
    def set_total_balance(self, target: Decimal | str) -> None:
        account = self.default_account()
        if account is None:
            account = self.add_account('Checking')
        difference = Decimal(str(target)) - account.balance
        if difference == 0:
            return
        self.add_transaction(
            account.id,
            date.today(),
            'Balance adjustment',
            'Manual account balance update',
            difference,
            'Adjustment',
        )

    def list_transactions(
        self,
        account_id: str | None = None,
        search: str = '',
        cleared: bool | None = None,
        limit: int = 500,
        fund_id: str | None = None,
    ) -> list[Transaction]:
        clauses = []
        params: list[object] = []
        if account_id:
            clauses.append('t.account_id = ?')
            params.append(account_id)
        if fund_id:
            clauses.append('t.fund_id = ?')
            params.append(fund_id)
        if search.strip():
            clauses.append('(t.payee LIKE ? OR t.memo LIKE ? OR t.category LIKE ?)')
            value = f'%{search.strip()}%'
            params.extend([value, value, value])
        if cleared is not None:
            clauses.append('t.cleared = ?')
            params.append(1 if cleared else 0)
        where = f'WHERE {" AND ".join(clauses)}' if clauses else ''
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT t.*, a.name AS account_name
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                {where}
                ORDER BY t.date DESC, t.created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            Transaction(
                id=row['id'],
                account_id=row['account_id'],
                account_name=row['account_name'],
                date=row['date'],
                payee=row['payee'],
                memo=row['memo'],
                amount=minor_to_money(row['amount_minor']),
                category=row['category'],
                cleared=bool(row['cleared']),
                transfer_id=row['transfer_id'],
                fund_id=row['fund_id'],
                budget_excluded=bool(row['budget_excluded']),
                affects_balance=bool(row['affects_balance']),
                contribution_id=row['contribution_id'],
            )
            for row in rows
        ]

    @_sync_mutation
    def add_transaction(
        self,
        account_id: str,
        transaction_date: date | datetime | str,
        payee: str,
        memo: str = '',
        amount: Decimal | str | int = 0,
        category: str = '',
        cleared: bool = False,
        fund_id: str | None = None,
        transfer_id: str | None = None,
        budget_excluded: bool = False,
        affects_balance: bool = True,
        contribution_id: str | None = None,
    ) -> str:
        payee = payee.strip()
        if not payee:
            raise LedgerError('payee is required')
        transaction_id = uuid4().hex
        with self._connect() as connection:
            if (
                connection.execute(
                    'SELECT 1 FROM accounts WHERE id = ? AND archived = 0',
                    (account_id,),
                ).fetchone()
                is None
            ):
                raise LedgerError('account does not exist')
            connection.execute(
                'INSERT INTO transactions '
                '(id, account_id, date, payee, memo, amount_minor, category, '
                'cleared, transfer_id, fund_id, budget_excluded, affects_balance, '
                'contribution_id, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    transaction_id,
                    account_id,
                    _date(transaction_date),
                    payee,
                    memo.strip(),
                    money_to_minor(amount),
                    category.strip(),
                    1 if cleared else 0,
                    transfer_id,
                    fund_id,
                    1 if budget_excluded else 0,
                    1 if affects_balance else 0,
                    contribution_id,
                    _now(),
                    _now(),
                ),
            )
        return transaction_id

    @_sync_mutation
    def update_transaction(
        self,
        transaction_id: str,
        account_id: str,
        transaction_date: date | datetime | str,
        payee: str,
        memo: str,
        amount: Decimal | str,
        category: str,
        cleared: bool,
    ) -> None:
        payee = payee.strip()
        if not payee:
            raise LedgerError('payee is required')
        with self._connect() as connection:
            cursor = connection.execute(
                'UPDATE transactions SET account_id = ?, date = ?, payee = ?, '
                'memo = ?, amount_minor = ?, category = ?, cleared = ?, updated_at = ? '
                'WHERE id = ?',
                (
                    account_id,
                    _date(transaction_date),
                    payee,
                    memo.strip(),
                    money_to_minor(amount),
                    category.strip(),
                    1 if cleared else 0,
                    _now(),
                    transaction_id,
                ),
            )
            if cursor.rowcount == 0:
                raise LedgerError('transaction does not exist')

    @_sync_mutation
    def delete_transaction(self, transaction_id: str) -> list[dict]:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT * FROM transactions WHERE id = ?', (transaction_id,)
            ).fetchone()
            if row is None:
                return []
            if row['transfer_id']:
                rows = connection.execute(
                    'SELECT * FROM transactions WHERE transfer_id = ?',
                    (row['transfer_id'],),
                ).fetchall()
            else:
                rows = [row]
            connection.executemany(
                'DELETE FROM transactions WHERE id = ?',
                [(item['id'],) for item in rows],
            )
        return [dict(item) for item in rows]

    @_sync_mutation
    def restore_transactions(self, rows: list[dict]) -> None:
        if not rows:
            return
        normalized = []
        for row in rows:
            item = dict(row)
            item.setdefault('budget_excluded', 0)
            item.setdefault('affects_balance', 1)
            item.setdefault('contribution_id', None)
            normalized.append(item)
        with self._connect() as connection:
            connection.executemany(
                'INSERT OR REPLACE INTO transactions '
                '(id, account_id, date, payee, memo, amount_minor, category, '
                'cleared, transfer_id, fund_id, budget_excluded, affects_balance, '
                'contribution_id, created_at, updated_at) '
                'VALUES (:id, :account_id, :date, :payee, :memo, :amount_minor, '
                ':category, :cleared, :transfer_id, :fund_id, :budget_excluded, '
                ':affects_balance, :contribution_id, :created_at, :updated_at)',
                normalized,
            )

    @_sync_mutation
    def add_transfer(
        self,
        from_account_id: str,
        to_account_id: str,
        transaction_date: date | datetime | str,
        amount: Decimal | str,
        memo: str = '',
        *,
        fund_id: str | None = None,
        budget_excluded: bool = False,
        contribution_id: str | None = None,
    ) -> str:
        if from_account_id == to_account_id:
            raise LedgerError('choose two different accounts')
        transfer_id = uuid4().hex
        value = abs(Decimal(str(amount)))
        if value <= 0:
            raise LedgerError('transfer amount must be greater than zero')
        transaction_date = _date(transaction_date)
        with self._connect() as connection:
            for account_id in (from_account_id, to_account_id):
                if (
                    connection.execute(
                        'SELECT 1 FROM accounts WHERE id = ? AND archived = 0',
                        (account_id,),
                    ).fetchone()
                    is None
                ):
                    raise LedgerError('account does not exist')
            for account_id, signed_value in (
                (from_account_id, -value),
                (to_account_id, value),
            ):
                connection.execute(
                    'INSERT INTO transactions '
                    '(id, account_id, date, payee, memo, amount_minor, category, '
                    'cleared, transfer_id, fund_id, budget_excluded, '
                    'affects_balance, contribution_id, created_at, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 1, ?, ?, ?)',
                    (
                        uuid4().hex,
                        account_id,
                        transaction_date,
                        'Transfer',
                        memo.strip(),
                        money_to_minor(signed_value),
                        'Transfer',
                        transfer_id,
                        fund_id,
                        1 if budget_excluded else 0,
                        contribution_id,
                        _now(),
                        _now(),
                    ),
                )
        return transfer_id

    # ------------------------------------------------------------------
    # Funds
    # ------------------------------------------------------------------

    @staticmethod
    def _fund_from_row(row: sqlite3.Row):
        from fund import Fund

        target_date = None
        if row['target_date'] and row['target_date'] != 'None':
            target_date = datetime.strptime(row['target_date'], '%m/%d/%Y')
        return Fund(
            row['name'],
            minor_to_money(row['target_minor']),
            minor_to_money(row['balance_minor']),
            target_date,
            minor_to_money(row['recurring_transfer_minor']),
            fund_id=row['id'],
            due_day=row['due_day'],
            kind=row['kind'],
            priority=row['priority'],
            status=row['status'],
            source_account_id=row['source_account_id'],
            destination_account_id=row['destination_account_id'],
            notes=row['notes'] or '',
        )

    def list_funds(self, include_archived: bool = True) -> list:
        where = '' if include_archived else "WHERE status != 'archived'"
        with self._connect() as connection:
            rows = connection.execute(
                f'SELECT * FROM funds {where} ORDER BY created_at, rowid'
            ).fetchall()
        return [self._fund_from_row(row) for row in rows]

    def get_fund(self, fund_id: str):
        with self._connect() as connection:
            row = connection.execute(
                'SELECT * FROM funds WHERE id = ?', (fund_id,)
            ).fetchone()
        return self._fund_from_row(row) if row else None

    @_sync_mutation
    def replace_funds(self, funds: list) -> bool:
        with self._connect() as connection:
            existing = connection.execute(
                'SELECT id, name, balance_minor, target_minor, target_date, '
                'recurring_transfer_minor, due_day, kind, priority, status, '
                'source_account_id, destination_account_id, notes '
                'FROM funds ORDER BY rowid'
            ).fetchall()
            desired = [
                (
                    fund.id,
                    fund.name,
                    money_to_minor(fund.balance),
                    money_to_minor(fund.target),
                    fund.target_date_as_str() if fund.target_date is not None else None,
                    money_to_minor(fund.recurring_transfer),
                    fund.due_day,
                    fund.kind,
                    fund.priority,
                    fund.status,
                    fund.source_account_id,
                    fund.destination_account_id,
                    fund.notes,
                )
                for fund in funds
            ]
            current = [tuple(row) for row in existing]
            if current == desired:
                return False
            connection.execute('DELETE FROM funds')
            connection.executemany(
                'INSERT INTO funds '
                '(id, name, balance_minor, target_minor, target_date, '
                'recurring_transfer_minor, due_day, kind, priority, status, '
                'source_account_id, destination_account_id, notes, '
                'created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                [(*item, _now(), _now()) for item in desired],
            )
        return True

    @_sync_mutation
    def save_fund(self, fund) -> None:
        with self._connect() as connection:
            existing = connection.execute(
                'SELECT created_at FROM funds WHERE id = ?', (fund.id,)
            ).fetchone()
            created_at = existing['created_at'] if existing else _now()
            connection.execute(
                'INSERT OR REPLACE INTO funds '
                '(id, name, balance_minor, target_minor, target_date, '
                'recurring_transfer_minor, due_day, kind, priority, status, '
                'source_account_id, destination_account_id, notes, '
                'created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    fund.id,
                    fund.name,
                    money_to_minor(fund.balance),
                    money_to_minor(fund.target),
                    fund.target_date_as_str() if fund.target_date is not None else None,
                    money_to_minor(fund.recurring_transfer),
                    fund.due_day,
                    fund.kind,
                    fund.priority,
                    fund.status,
                    fund.source_account_id,
                    fund.destination_account_id,
                    fund.notes,
                    created_at,
                    _now(),
                ),
            )

    @_sync_mutation
    def update_fund_balance(self, fund_id: str, balance) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                'UPDATE funds SET balance_minor = ?, updated_at = ? WHERE id = ?',
                (money_to_minor(balance), _now(), fund_id),
            )
            if cursor.rowcount == 0:
                raise LedgerError('fund does not exist')

    # ------------------------------------------------------------------
    # Budget plan, allocations, and history
    # ------------------------------------------------------------------

    def latest_budget_period(self) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT MAX(period) FROM budget_allocations'
            ).fetchone()
        return row[0] if row and row[0] else None

    def has_budget_period(self, period: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT 1 FROM budget_allocations WHERE period = ? LIMIT 1',
                (period,),
            ).fetchone()
        return row is not None

    def list_budget_periods(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT DISTINCT period FROM budget_allocations ORDER BY period'
            ).fetchall()
        return [row['period'] for row in rows]

    def _group_id(
        self, connection: sqlite3.Connection, name: str, kind: str, order: int
    ) -> str:
        row = connection.execute(
            'SELECT id FROM category_groups WHERE name = ? AND kind = ?',
            (name, kind),
        ).fetchone()
        if row is not None:
            return row['id']
        group_id = uuid4().hex
        connection.execute(
            'INSERT INTO category_groups '
            '(id, name, kind, sort_order, archived) VALUES (?, ?, ?, ?, 0)',
            (group_id, name, kind, order),
        )
        return group_id

    @_sync_mutation
    def replace_budget(self, period: str, categories: list) -> bool:
        from budget import BudgetState

        state = BudgetState(categories, period)
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT a.budgeted_minor, a.spent_minor, a.source_fund_id, '
                'a.sort_order, c.id, c.name, c.kind, g.name AS group_name '
                'FROM budget_allocations a '
                'JOIN budget_categories c ON c.id = a.category_id '
                'LEFT JOIN category_groups g ON g.id = c.group_id '
                'WHERE a.period = ? ORDER BY a.sort_order, c.name',
                (period,),
            ).fetchall()
            current = [
                (
                    row['id'],
                    row['name'],
                    row['kind'],
                    row['budgeted_minor'],
                    row['spent_minor'],
                    row['source_fund_id'],
                    row['group_name'] or 'General',
                )
                for row in rows
            ]
            desired = [
                (
                    category.category_id,
                    category.name,
                    category.kind,
                    money_to_minor(category.budgeted),
                    money_to_minor(category.spent),
                    category.source_fund_id,
                    category.group,
                )
                for category in state.categories
            ]
            if current == desired:
                return False
            # Keep category definitions stable across months; only allocations
            # for this period are replaced.
            for index, category in enumerate(categories):
                group_id = self._group_id(
                    connection, category.group, category.kind, index
                )
                connection.execute(
                    'INSERT INTO budget_categories '
                    '(id, group_id, name, kind, rollover, archived, created_at) '
                    'VALUES (?, ?, ?, ?, 0, 0, ?) '
                    'ON CONFLICT(id) DO UPDATE SET '
                    'group_id = excluded.group_id, name = excluded.name, '
                    'kind = excluded.kind',
                    (
                        category.category_id,
                        group_id,
                        category.name,
                        category.kind,
                        _now(),
                    ),
                )
            connection.execute(
                'DELETE FROM budget_allocations WHERE period = ?', (period,)
            )
            connection.executemany(
                'INSERT INTO budget_allocations '
                '(period, category_id, budgeted_minor, spent_minor, '
                'source_fund_id, sort_order) VALUES (?, ?, ?, ?, ?, ?)',
                [
                    (
                        period,
                        category.category_id,
                        money_to_minor(category.budgeted),
                        money_to_minor(category.spent),
                        category.source_fund_id,
                        index,
                    )
                    for index, category in enumerate(categories)
                ],
            )
        return True

    def load_budget(self, period: str | None = None):
        from budget import BudgetCategory, BudgetState

        if period is None:
            period = self.latest_budget_period()
        if period is None:
            return None
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT a.budgeted_minor, a.spent_minor, a.source_fund_id, '
                'a.sort_order, c.id, c.name, c.kind, c.group_id, '
                'COALESCE(g.name, ?) AS group_name '
                'FROM budget_allocations a '
                'JOIN budget_categories c ON c.id = a.category_id '
                'LEFT JOIN category_groups g ON g.id = c.group_id '
                'WHERE a.period = ? ORDER BY a.sort_order, c.name',
                ('General', period),
            ).fetchall()
        categories = [
            BudgetCategory(
                row['name'],
                minor_to_money(row['budgeted_minor']),
                minor_to_money(row['spent_minor']),
                row['kind'],
                row['source_fund_id'],
                row['id'],
                row['group_name'],
                row['group_id'],
                row['sort_order'],
            )
            for row in rows
        ]
        return BudgetState(categories, period)

    @_sync_mutation
    def save_budget_history(self, snapshot: dict) -> bool:
        period = snapshot.get('period')
        if not isinstance(period, str):
            raise LedgerError('budget snapshot period is required')
        payload = json.dumps(snapshot, sort_keys=True)
        with self._connect() as connection:
            existing = connection.execute(
                'SELECT snapshot_json FROM budget_history WHERE period = ?',
                (period,),
            ).fetchone()
            if existing is not None and existing['snapshot_json'] == payload:
                return False
            connection.execute(
                'INSERT OR REPLACE INTO budget_history '
                '(period, archived_at, snapshot_json) VALUES (?, ?, ?)',
                (
                    period,
                    snapshot.get('archived_at', _now()),
                    payload,
                ),
            )
        return True

    def list_budget_history(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT snapshot_json FROM budget_history ORDER BY period'
            ).fetchall()
        return [json.loads(row['snapshot_json']) for row in rows]

    @_sync_mutation
    def delete_budget_period(self, period: str) -> None:
        with self._connect() as connection:
            connection.execute(
                'DELETE FROM budget_allocations WHERE period = ?', (period,)
            )

    # ------------------------------------------------------------------
    # Scheduled fund contributions, one-off contributions, and undo
    # ------------------------------------------------------------------

    def _insert_contribution_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        fund,
        contribution_id: str,
        amount_minor: int,
        transaction_date: str,
        account_id: str,
        note: str,
    ) -> tuple[str | None, str]:
        destination_id = fund.destination_account_id
        source_id = account_id
        payee = f'Fund contribution: {fund.name}'
        if destination_id and destination_id != source_id:
            destination = connection.execute(
                'SELECT 1 FROM accounts WHERE id = ? AND archived = 0',
                (destination_id,),
            ).fetchone()
            if destination is not None:
                transfer_id = uuid4().hex
                for leg_account, signed in (
                    (source_id, -amount_minor),
                    (destination_id, amount_minor),
                ):
                    connection.execute(
                        'INSERT INTO transactions '
                        '(id, account_id, date, payee, memo, amount_minor, category, '
                        'cleared, transfer_id, fund_id, budget_excluded, '
                        'affects_balance, contribution_id, created_at, updated_at) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 1, 1, ?, ?, ?)',
                        (
                            uuid4().hex,
                            leg_account,
                            transaction_date,
                            payee,
                            note,
                            signed,
                            'Savings',
                            transfer_id,
                            fund.id,
                            contribution_id,
                            _now(),
                            _now(),
                        ),
                    )
                return transfer_id, 'transfer'
        # Funds are earmarks/envelopes, not bank accounts. Without an explicit
        # destination account the contribution is a non-cash register entry
        # that does not change the bank balance.
        transaction_id = uuid4().hex
        connection.execute(
            'INSERT INTO transactions '
            '(id, account_id, date, payee, memo, amount_minor, category, '
            'cleared, transfer_id, fund_id, budget_excluded, affects_balance, '
            'contribution_id, created_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL, ?, 1, 0, ?, ?, ?)',
            (
                transaction_id,
                source_id,
                transaction_date,
                payee,
                note,
                amount_minor,
                'Savings',
                fund.id,
                contribution_id,
                _now(),
                _now(),
            ),
        )
        return transaction_id, 'earmark'

    @_sync_mutation
    def add_fund_contribution(
        self,
        fund,
        amount=None,
        *,
        period: str | None = None,
        kind: str = 'one_off',
        transaction_date: date | datetime | str | None = None,
        due_date: date | datetime | str | None = None,
        account_id: str | None = None,
        memo: str = '',
        allow_negative: bool = False,
    ) -> FundContribution | None:
        """Post one contribution and update the fund balance atomically.

        Recurring contributions are idempotent per ``(fund_id, period)``. A
        one-off contribution is always budget-excluded and may be posted any
        number of times.
        """
        from fund import due_date_for_period

        fund_id = fund if isinstance(fund, str) else fund.id
        with self._connect() as connection:
            row = connection.execute(
                'SELECT * FROM funds WHERE id = ?', (fund_id,)
            ).fetchone()
            if row is None:
                raise LedgerError('fund does not exist')
            fund_obj = self._fund_from_row(row)
            if period is None:
                today = transaction_date or date.today()
                if isinstance(today, str):
                    today = date.fromisoformat(today)
                if isinstance(today, datetime):
                    today = today.date()
                period = today.strftime('%Y-%m')
            if kind not in {'recurring', 'one_off'}:
                raise LedgerError('contribution kind must be recurring or one_off')
            if kind == 'recurring':
                existing = connection.execute(
                    'SELECT id FROM fund_contributions '
                    'WHERE fund_id = ? AND period = ? AND kind = ?',
                    (fund_id, period, kind),
                ).fetchone()
                if existing is not None:
                    return None
            value = fund_obj.recurring_transfer if amount is None else amount
            value_minor = money_to_minor(value)
            if value_minor < 0 and not allow_negative:
                raise LedgerError('contribution amount must not be negative')
            if value_minor == 0:
                raise LedgerError('contribution amount must be greater than zero')
            if due_date is None:
                due = due_date_for_period(period, fund_obj.due_day)
            elif isinstance(due_date, datetime):
                due = due_date.date()
            elif isinstance(due_date, date):
                due = due_date
            else:
                due = date.fromisoformat(str(due_date))
            posted = transaction_date or date.today()
            posted_date = _date(posted)
            source_id = account_id or fund_obj.source_account_id
            if source_id is None:
                default = connection.execute(
                    'SELECT id FROM accounts WHERE archived = 0 '
                    'ORDER BY created_at, name LIMIT 1'
                ).fetchone()
                if default is None:
                    source_id = uuid4().hex
                    connection.execute(
                        'INSERT INTO accounts '
                        '(id, name, type, currency, opening_balance_minor, '
                        'archived, created_at) VALUES (?, ?, ?, ?, 0, 0, ?)',
                        (source_id, 'Savings', 'savings', 'USD', _now()),
                    )
                else:
                    source_id = default['id']
            else:
                if (
                    connection.execute(
                        'SELECT 1 FROM accounts WHERE id = ?', (source_id,)
                    ).fetchone()
                    is None
                ):
                    raise LedgerError('account does not exist')
            contribution_id = uuid4().hex
            transaction_id, _mode = self._insert_contribution_transaction(
                connection,
                fund=fund_obj,
                contribution_id=contribution_id,
                amount_minor=value_minor,
                transaction_date=posted_date,
                account_id=source_id,
                note=memo.strip(),
            )
            connection.execute(
                'UPDATE funds SET balance_minor = balance_minor + ?, '
                'updated_at = ? WHERE id = ?',
                (value_minor, _now(), fund_id),
            )
            connection.execute(
                'INSERT INTO fund_contributions '
                '(id, fund_id, period, kind, amount_minor, due_date, posted_at, '
                'transaction_id, status, budget_excluded, memo) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)',
                (
                    contribution_id,
                    fund_id,
                    period,
                    kind,
                    value_minor,
                    due.isoformat(),
                    _now(),
                    transaction_id,
                    'posted',
                    memo.strip(),
                ),
            )
        return self.get_fund_contribution(contribution_id)

    @_sync_mutation
    def withdraw_fund(
        self,
        fund,
        amount,
        *,
        period: str | None = None,
        memo: str = 'Fund withdrawal',
    ) -> FundContribution | None:
        """Remove money from a fund without a budget impact."""
        return self.add_fund_contribution(
            fund,
            -abs(Decimal(str(amount))),
            period=period,
            kind='one_off',
            memo=memo,
            allow_negative=True,
        )

    def auto_post_fund_contributions(self, funds=None, today=None) -> list:
        """Post the current month's due recurring contribution per fund.

        Only the current occurrence is caught up; past months are never
        silently backfilled. The unique ``(fund_id, period)`` index makes the
        operation idempotent across restarts and devices.
        """
        from fund import due_date_for_period

        if isinstance(today, datetime):
            today = today.date()
        today = today or date.today()
        period = today.strftime('%Y-%m')
        funds = list(funds) if funds is not None else self.list_funds()
        posted = []
        for fund in funds:
            if not fund.is_active or fund.recurring_transfer <= 0:
                continue
            due = due_date_for_period(period, fund.due_day)
            if today < due:
                continue
            contribution = self.add_fund_contribution(
                fund,
                period=period,
                kind='recurring',
                transaction_date=today,
                due_date=due,
            )
            if contribution is not None:
                posted.append(contribution)
        return posted

    def post_due_fund_contributions(self, funds=None, today=None) -> list:
        """Alias for :meth:`auto_post_fund_contributions`."""
        return self.auto_post_fund_contributions(funds, today)

    def post_fund_contribution(self, fund, amount=None, **kwargs):
        """Alias for :meth:`add_fund_contribution`."""
        return self.add_fund_contribution(fund, amount, **kwargs)

    def undo_contribution(self, contribution_id: str) -> bool:
        """Alias for :meth:`undo_fund_contribution`."""
        return self.undo_fund_contribution(contribution_id)

    def get_fund_contribution(self, contribution_id: str) -> FundContribution | None:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT c.*, f.name AS fund_name FROM fund_contributions c '
                'LEFT JOIN funds f ON f.id = c.fund_id WHERE c.id = ?',
                (contribution_id,),
            ).fetchone()
        return self._contribution_from_row(row) if row else None

    @staticmethod
    def _contribution_from_row(row: sqlite3.Row) -> FundContribution:
        return FundContribution(
            id=row['id'],
            fund_id=row['fund_id'],
            fund_name=row['fund_name'] or '',
            period=row['period'],
            kind=row['kind'],
            amount=minor_to_money(row['amount_minor']),
            due_date=row['due_date'],
            posted_at=row['posted_at'],
            status=row['status'],
            budget_excluded=bool(row['budget_excluded']),
            transaction_id=row['transaction_id'],
            memo=row['memo'],
        )

    def list_fund_contributions(
        self,
        period: str | None = None,
        fund_id: str | None = None,
        status: str | None = None,
    ) -> list[FundContribution]:
        clauses = []
        params: list[object] = []
        if period is not None:
            clauses.append('c.period = ?')
            params.append(period)
        if fund_id is not None:
            clauses.append('c.fund_id = ?')
            params.append(fund_id)
        if status is not None:
            clauses.append('c.status = ?')
            params.append(status)
        where = f'WHERE {" AND ".join(clauses)}' if clauses else ''
        with self._connect() as connection:
            rows = connection.execute(
                f'SELECT c.*, f.name AS fund_name FROM fund_contributions c '
                f'LEFT JOIN funds f ON f.id = c.fund_id {where} '
                'ORDER BY c.posted_at, c.rowid',
                params,
            ).fetchall()
        return [self._contribution_from_row(row) for row in rows]

    @_sync_mutation
    def undo_fund_contribution(self, contribution_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT * FROM fund_contributions WHERE id = ?',
                (contribution_id,),
            ).fetchone()
            if row is None or row['status'] != 'posted':
                return False
            transaction_id = row['transaction_id']
            if transaction_id:
                transfer = connection.execute(
                    'SELECT transfer_id FROM transactions WHERE id = ?',
                    (transaction_id,),
                ).fetchone()
                if transfer is not None and transfer['transfer_id']:
                    connection.execute(
                        'DELETE FROM transactions WHERE transfer_id = ?',
                        (transfer['transfer_id'],),
                    )
                else:
                    connection.execute(
                        'DELETE FROM transactions WHERE contribution_id = ?',
                        (contribution_id,),
                    )
            connection.execute(
                'UPDATE funds SET balance_minor = balance_minor - ?, '
                'updated_at = ? WHERE id = ?',
                (row['amount_minor'], _now(), row['fund_id']),
            )
            connection.execute(
                "UPDATE fund_contributions SET status = 'undone', "
                'transaction_id = NULL WHERE id = ?',
                (contribution_id,),
            )
        return True

    def export_json(self, destination: Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            accounts = [
                dict(row) for row in connection.execute('SELECT * FROM accounts')
            ]
            transactions = [
                dict(row) for row in connection.execute('SELECT * FROM transactions')
            ]
            funds = [dict(row) for row in connection.execute('SELECT * FROM funds')]
            contributions = [
                dict(row)
                for row in connection.execute('SELECT * FROM fund_contributions')
            ]
        document = {
            'version': SCHEMA_VERSION,
            'exported_at': _now(),
            'accounts': accounts,
            'transactions': transactions,
            'funds': funds,
            'fund_contributions': contributions,
        }
        destination.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
        return destination

    @_sync_mutation
    def import_json(self, source: Path) -> None:
        source = Path(source)
        document = json.loads(source.read_text(encoding='utf-8'))
        if not isinstance(document, dict) or document.get('version') not in {
            1,
            SCHEMA_VERSION,
        }:
            raise LedgerError('unsupported ledger export version')
        accounts = document.get('accounts', [])
        transactions = document.get('transactions', [])
        funds = document.get('funds', [])
        contributions = document.get('fund_contributions', [])
        if not isinstance(accounts, list) or not isinstance(transactions, list):
            raise LedgerError('invalid ledger export')
        with self._connect() as connection:
            connection.execute('DELETE FROM fund_contributions')
            connection.execute('DELETE FROM transactions')
            connection.execute('DELETE FROM funds')
            connection.execute('DELETE FROM accounts')
            for account in accounts:
                connection.execute(
                    'INSERT INTO accounts '
                    '(id, name, type, currency, opening_balance_minor, archived, created_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (
                        account['id'],
                        account['name'],
                        account['type'],
                        account.get('currency', 'USD'),
                        int(account['opening_balance_minor']),
                        1 if account.get('archived') else 0,
                        account.get('created_at', _now()),
                    ),
                )
            for transaction in transactions:
                connection.execute(
                    'INSERT INTO transactions '
                    '(id, account_id, date, payee, memo, amount_minor, category, '
                    'cleared, transfer_id, fund_id, budget_excluded, '
                    'affects_balance, contribution_id, created_at, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (
                        transaction['id'],
                        transaction['account_id'],
                        transaction['date'],
                        transaction['payee'],
                        transaction.get('memo', ''),
                        int(transaction['amount_minor']),
                        transaction.get('category', ''),
                        1 if transaction.get('cleared') else 0,
                        transaction.get('transfer_id'),
                        transaction.get('fund_id'),
                        1 if transaction.get('budget_excluded') else 0,
                        1 if transaction.get('affects_balance', 1) else 0,
                        transaction.get('contribution_id'),
                        transaction.get('created_at', _now()),
                        transaction.get('updated_at', _now()),
                    ),
                )
            for fund in funds:
                connection.execute(
                    'INSERT INTO funds '
                    '(id, name, balance_minor, target_minor, target_date, '
                    'recurring_transfer_minor, due_day, kind, priority, status, '
                    'source_account_id, destination_account_id, notes, '
                    'created_at, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (
                        fund['id'],
                        fund['name'],
                        int(fund.get('balance_minor', 0)),
                        int(fund.get('target_minor', 0)),
                        fund.get('target_date'),
                        int(fund.get('recurring_transfer_minor', 0)),
                        int(fund.get('due_day', 31)),
                        fund.get('kind', 'savings_goal'),
                        int(fund.get('priority', 0)),
                        fund.get('status', 'active'),
                        fund.get('source_account_id'),
                        fund.get('destination_account_id'),
                        fund.get('notes', ''),
                        fund.get('created_at', _now()),
                        fund.get('updated_at', _now()),
                    ),
                )
            for contribution in contributions:
                connection.execute(
                    'INSERT INTO fund_contributions '
                    '(id, fund_id, period, kind, amount_minor, due_date, '
                    'posted_at, transaction_id, status, budget_excluded, memo) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (
                        contribution['id'],
                        contribution['fund_id'],
                        contribution['period'],
                        contribution.get('kind', 'recurring'),
                        int(contribution['amount_minor']),
                        contribution['due_date'],
                        contribution['posted_at'],
                        contribution.get('transaction_id'),
                        contribution.get('status', 'posted'),
                        1 if contribution.get('budget_excluded', 1) else 0,
                        contribution.get('memo', ''),
                    ),
                )

    def export_csv(self, destination: Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        transactions = self.list_transactions(limit=1_000_000)
        with destination.open('w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(
                ['date', 'account', 'payee', 'memo', 'category', 'amount', 'cleared']
            )
            for transaction in reversed(transactions):
                writer.writerow(
                    [
                        transaction.date,
                        transaction.account_name,
                        transaction.payee,
                        transaction.memo,
                        transaction.category,
                        f'{transaction.amount:.2f}',
                        'yes' if transaction.cleared else 'no',
                    ]
                )
        return destination
