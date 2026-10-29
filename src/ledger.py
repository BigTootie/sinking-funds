"""Local SQLite ledger for accounts and transactions.

Money is stored as integer minor units. The JSON files remain the migration
and synchronization format for the current release, while new account and
transaction data lives in the local ledger database.
"""

import csv
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from paths import get_data_dir

LEDGER_DB = get_data_dir() / 'ledger.db'
SCHEMA_VERSION = 1


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


class Ledger:
    """A small repository around the local SQLite ledger."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or LEDGER_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

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

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
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
                    recurring_transfer_minor INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS budget_imports (
                    period TEXT NOT NULL,
                    category_name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    budgeted_minor INTEGER NOT NULL,
                    spent_minor INTEGER NOT NULL,
                    PRIMARY KEY (period, category_name)
                );
                """
            )
            connection.execute(
                'INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)',
                ('schema_version', str(SCHEMA_VERSION)),
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

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT value FROM meta WHERE key = ?', (key,)
            ).fetchone()
            return row['value'] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                'INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)', (key, value)
            )

    def seed_legacy(
        self,
        balance: Decimal | None,
        funds: list,
        categories: list,
        period: str,
    ) -> None:
        """Import the current JSON totals once without duplicating data."""
        if self.get_meta('legacy_seeded') == '1':
            return

        with self._connect() as connection:
            has_account = connection.execute(
                'SELECT 1 FROM accounts LIMIT 1'
            ).fetchone()
            if has_account is None:
                account_id = uuid4().hex
                connection.execute(
                    'INSERT INTO accounts '
                    '(id, name, type, currency, opening_balance_minor, archived, created_at) '
                    'VALUES (?, ?, ?, ?, 0, 0, ?)',
                    (account_id, 'Savings', 'savings', 'USD', _now()),
                )
                if balance:
                    connection.execute(
                        'INSERT INTO transactions '
                        '(id, account_id, date, payee, memo, amount_minor, category, '
                        'cleared, transfer_id, fund_id, created_at, updated_at) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL, NULL, ?, ?)',
                        (
                            uuid4().hex,
                            account_id,
                            date.today().isoformat(),
                            'Opening balance',
                            'Migrated from balance.txt',
                            money_to_minor(balance),
                            'Opening balance',
                            _now(),
                            _now(),
                        ),
                    )
            connection.execute('DELETE FROM funds')
            for fund in funds:
                connection.execute(
                    'INSERT INTO funds '
                    '(id, name, balance_minor, target_minor, target_date, recurring_transfer_minor) '
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    (
                        fund.id,
                        fund.name,
                        money_to_minor(fund.balance),
                        money_to_minor(fund.target),
                        fund.target_date_as_str()
                        if fund.target_date is not None
                        else None,
                        money_to_minor(fund.recurring_transfer),
                    ),
                )
            connection.execute('DELETE FROM budget_imports')
            for category in categories:
                connection.execute(
                    'INSERT OR REPLACE INTO budget_imports '
                    '(period, category_name, kind, budgeted_minor, spent_minor) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (
                        period,
                        category.name,
                        category.kind,
                        money_to_minor(category.budgeted),
                        money_to_minor(category.spent),
                    ),
                )
            connection.execute(
                'INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)',
                ('legacy_seeded', '1'),
            )
            connection.execute(
                'INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)',
                (
                    'migration_note',
                    'Imported the existing account balance, funds, and budget '
                    'totals into the local ledger. Amounts remain derived from '
                    'the ledger for new transactions.',
                ),
            )

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
                'WHERE account_id = ?',
                (account_id,),
            ).fetchone()[0]
            cleared = connection.execute(
                'SELECT COALESCE(SUM(amount_minor), 0) FROM transactions '
                'WHERE account_id = ? AND cleared = 1',
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

    def archive_account(self, account_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                'UPDATE accounts SET archived = 1 WHERE id = ?', (account_id,)
            )

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
    ) -> list[Transaction]:
        clauses = []
        params: list[object] = []
        if account_id:
            clauses.append('t.account_id = ?')
            params.append(account_id)
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
            )
            for row in rows
        ]

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
                'cleared, transfer_id, fund_id, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
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
                    _now(),
                    _now(),
                ),
            )
        return transaction_id

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

    def restore_transactions(self, rows: list[dict]) -> None:
        if not rows:
            return
        with self._connect() as connection:
            connection.executemany(
                'INSERT OR REPLACE INTO transactions '
                '(id, account_id, date, payee, memo, amount_minor, category, '
                'cleared, transfer_id, fund_id, created_at, updated_at) '
                'VALUES (:id, :account_id, :date, :payee, :memo, :amount_minor, '
                ':category, :cleared, :transfer_id, :fund_id, :created_at, :updated_at)',
                rows,
            )

    def add_transfer(
        self,
        from_account_id: str,
        to_account_id: str,
        transaction_date: date | datetime | str,
        amount: Decimal | str,
        memo: str = '',
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
                    'cleared, transfer_id, fund_id, created_at, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, ?, ?)',
                    (
                        uuid4().hex,
                        account_id,
                        transaction_date,
                        'Transfer',
                        memo.strip(),
                        money_to_minor(signed_value),
                        'Transfer',
                        transfer_id,
                        _now(),
                        _now(),
                    ),
                )
        return transfer_id

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
        document = {
            'version': SCHEMA_VERSION,
            'exported_at': _now(),
            'accounts': accounts,
            'transactions': transactions,
            'funds': funds,
        }
        destination.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
        return destination

    def import_json(self, source: Path) -> None:
        source = Path(source)
        document = json.loads(source.read_text(encoding='utf-8'))
        if not isinstance(document, dict) or document.get('version') != SCHEMA_VERSION:
            raise LedgerError('unsupported ledger export version')
        accounts = document.get('accounts', [])
        transactions = document.get('transactions', [])
        funds = document.get('funds', [])
        if not isinstance(accounts, list) or not isinstance(transactions, list):
            raise LedgerError('invalid ledger export')
        with self._connect() as connection:
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
                    'cleared, transfer_id, fund_id, created_at, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
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
                        transaction.get('created_at', _now()),
                        transaction.get('updated_at', _now()),
                    ),
                )
            for fund in funds:
                connection.execute(
                    'INSERT INTO funds '
                    '(id, name, balance_minor, target_minor, target_date, recurring_transfer_minor) '
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    (
                        fund['id'],
                        fund['name'],
                        int(fund.get('balance_minor', 0)),
                        int(fund.get('target_minor', 0)),
                        fund.get('target_date'),
                        int(fund.get('recurring_transfer_minor', 0)),
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
