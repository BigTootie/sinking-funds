"""Local ledger register and account management UI."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import flet as ft

import colors
from ledger import Account, Ledger, LedgerError
from paths import get_data_dir
from ui.shared import ConfirmDialog, dialog_form
from utils import money_format, parse_money, parse_signed_money

ACCOUNT_TYPES = ['checking', 'savings', 'cash', 'credit']


class AccountDialog:
    """Create or edit a ledger account."""

    def __init__(self, page: ft.Page, ledger: Ledger, on_changed: Callable[[], None]):
        self.page = page
        self.ledger = ledger
        self.on_changed = on_changed

    def open(self, account: Account | None = None):
        name = ft.TextField(
            label='Account name',
            value=account.name if account else '',
            key='account-name-input',
        )
        account_type = ft.Dropdown(
            label='Type',
            value=account.type if account else 'checking',
            options=[ft.dropdown.Option(value) for value in ACCOUNT_TYPES],
            key='account-type-input',
        )
        opening = ft.TextField(
            label='Opening balance ($)',
            value=str(account.opening_balance) if account else '0',
            keyboard_type=ft.KeyboardType.NUMBER,
            key='account-opening-input',
        )
        error = ft.Text(color=colors.RED)

        def save(e):
            try:
                value = parse_signed_money(opening.value or '0')
                if account:
                    self.ledger.update_account(
                        account.id,
                        name.value or '',
                        account_type.value or 'checking',
                        value,
                    )
                else:
                    self.ledger.add_account(
                        name.value or '', account_type.value or 'checking', value
                    )
            except (LedgerError, ValueError) as exc:
                error.value = str(exc)
                self.page.update()
                return
            self.page.pop_dialog()
            self.on_changed()

        self.page.show_dialog(
            ft.AlertDialog(
                title='Edit account' if account else 'Add account',
                content=dialog_form([name, account_type, opening, error], height=240),
                actions=[
                    ft.TextButton(
                        'Cancel',
                        key='account-cancel-button',
                        on_click=lambda e: self.page.pop_dialog(),
                    ),
                    ft.FilledButton('Save', key='account-save-button', on_click=save),
                ],
                modal=True,
            )
        )


class TransactionDialog:
    """Add or edit one ledger transaction or transfer."""

    def __init__(self, page: ft.Page, ledger: Ledger, on_changed: Callable[[], None]):
        self.page = page
        self.ledger = ledger
        self.on_changed = on_changed

    def open(self, transaction=None):
        accounts = self.ledger.list_accounts()
        if not accounts:
            self.page.show_dialog(
                ft.SnackBar(ft.Text('Add an account before recording a transaction.'))
            )
            return
        account_options = [ft.dropdown.Option(a.id, a.name) for a in accounts]
        transaction_date = ft.TextField(
            label='Date (YYYY-MM-DD)',
            value=transaction.date if transaction else date.today().isoformat(),
            key='transaction-date-input',
        )
        payee = ft.TextField(
            label='Payee',
            value=transaction.payee if transaction else '',
            key='transaction-payee-input',
        )
        memo = ft.TextField(
            label='Memo',
            value=transaction.memo if transaction else '',
            key='transaction-memo-input',
        )
        amount = ft.TextField(
            label='Amount ($, negative for spending)',
            value=str(transaction.amount) if transaction else '',
            keyboard_type=ft.KeyboardType.NUMBER,
            key='transaction-amount-input',
        )
        category = ft.TextField(
            label='Category',
            value=transaction.category if transaction else '',
            key='transaction-category-input',
        )
        account = ft.Dropdown(
            label='Account',
            value=transaction.account_id if transaction else accounts[0].id,
            options=account_options,
            key='transaction-account-input',
        )
        transfer = ft.Dropdown(
            label='Transfer to (optional)',
            value=None,
            options=[ft.dropdown.Option('', 'None')]
            + [ft.dropdown.Option(a.id, a.name) for a in accounts],
            key='transaction-transfer-input',
        )
        cleared = ft.Switch(
            label='Cleared',
            value=transaction.cleared if transaction else False,
            key='transaction-cleared-input',
        )
        error = ft.Text(color=colors.RED)

        def save(e):
            try:
                if transaction:
                    self.ledger.update_transaction(
                        transaction.id,
                        account.value or '',
                        transaction_date.value or '',
                        payee.value or '',
                        memo.value or '',
                        parse_signed_money(amount.value or '0'),
                        category.value or '',
                        bool(cleared.value),
                    )
                elif transfer.value:
                    self.ledger.add_transfer(
                        account.value or '',
                        transfer.value,
                        transaction_date.value or '',
                        parse_money(amount.value or '0'),
                        memo.value or '',
                    )
                else:
                    self.ledger.add_transaction(
                        account.value or '',
                        transaction_date.value or '',
                        payee.value or '',
                        memo.value or '',
                        parse_signed_money(amount.value or '0'),
                        category.value or '',
                        bool(cleared.value),
                    )
            except (LedgerError, ValueError) as exc:
                error.value = str(exc)
                self.page.update()
                return
            self.page.pop_dialog()
            self.on_changed()

        actions = []
        if transaction:

            def delete(e):
                self.page.pop_dialog()
                ConfirmDialog(
                    self.page,
                    'Delete transaction?',
                    f'Delete "{transaction.payee}"?',
                    lambda: self._delete(transaction.id),
                ).open()

            actions.append(
                ft.FilledButton(
                    'Delete',
                    key='transaction-delete-button',
                    bgcolor=colors.RED,
                    on_click=delete,
                )
            )
        actions.extend(
            [
                ft.TextButton(
                    'Cancel',
                    key='transaction-cancel-button',
                    on_click=lambda e: self.page.pop_dialog(),
                ),
                ft.FilledButton('Save', key='transaction-save-button', on_click=save),
            ]
        )
        self.page.show_dialog(
            ft.AlertDialog(
                title='Edit transaction' if transaction else 'Add transaction',
                content=dialog_form(
                    [
                        transaction_date,
                        payee,
                        memo,
                        amount,
                        category,
                        account,
                        transfer,
                        cleared,
                        error,
                    ],
                    height=430,
                ),
                actions=actions,
                modal=True,
            )
        )

    def _delete(self, transaction_id: str):
        deleted = self.ledger.delete_transaction(transaction_id)
        self.on_changed()
        snack = ft.SnackBar(ft.Text('Transaction deleted.'), action='Undo')

        def undo(_event):
            self.ledger.restore_transactions(deleted)
            self.on_changed()

        snack.on_action = undo
        self.page.show_dialog(snack)


class TransactionsDashboard:
    """Account summary, filters, and the local transaction register."""

    def __init__(self, page: ft.Page, ledger: Ledger, on_changed: Callable[[], None]):
        self.page = page
        self.ledger = ledger
        self.on_changed = on_changed
        self.account_dialog = AccountDialog(page, ledger, self._changed)
        self.transaction_dialog = TransactionDialog(page, ledger, self._changed)
        self.total_text = ft.Text(size=30, weight=ft.FontWeight.BOLD)
        self.cleared_text = ft.Text(size=12, color=colors.TEXT_SECONDARY)
        self.uncleared_text = ft.Text(size=12, color=colors.TEXT_SECONDARY)
        self.search = ft.TextField(
            hint_text='Search payee, memo, or category',
            prefix_icon=ft.Icons.SEARCH,
            key='transactions-search',
            on_change=lambda e: self.refresh(),
            expand=True,
        )
        self.account_filter = ft.Dropdown(
            value='',
            options=[ft.dropdown.Option('', 'All accounts')],
            key='transactions-account-filter',
            on_select=lambda e: self.refresh(),
            width=200,
        )
        self.cleared_filter = ft.Dropdown(
            value='all',
            options=[
                ft.dropdown.Option('all', 'All'),
                ft.dropdown.Option('cleared', 'Cleared'),
                ft.dropdown.Option('uncleared', 'Uncleared'),
            ],
            key='transactions-cleared-filter',
            on_select=lambda e: self.refresh(),
            width=150,
        )
        self.account_row = ft.Row(spacing=10, wrap=True)
        self.register = ft.Column(spacing=0)
        self.control = ft.Container(
            padding=24,
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        'Transactions',
                                        size=30,
                                        weight=ft.FontWeight.BOLD,
                                        expand=True,
                                    ),
                                    ft.OutlinedButton(
                                        'Add account',
                                        icon=ft.Icons.ADD,
                                        key='add-account-button',
                                        on_click=lambda e: self.account_dialog.open(),
                                    ),
                                    ft.FilledButton(
                                        'Add transaction',
                                        icon=ft.Icons.ADD,
                                        key='add-transaction-button',
                                        on_click=lambda e: (
                                            self.transaction_dialog.open()
                                        ),
                                    ),
                                ],
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Container(
                                content=ft.Row(
                                    [
                                        ft.Column(
                                            [
                                                ft.Text(
                                                    'TOTAL BALANCE',
                                                    size=11,
                                                    weight=ft.FontWeight.BOLD,
                                                    color=colors.TEXT_SECONDARY,
                                                ),
                                                self.total_text,
                                                self.cleared_text,
                                                self.uncleared_text,
                                            ],
                                            spacing=4,
                                            expand=True,
                                        ),
                                        ft.Icon(
                                            ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED,
                                            size=36,
                                            color=colors.BLUE,
                                        ),
                                    ]
                                ),
                                padding=20,
                                border=ft.Border.all(1, colors.BORDER),
                                border_radius=18,
                            ),
                            self.account_row,
                            ft.Row(
                                [
                                    self.search,
                                    self.account_filter,
                                    self.cleared_filter,
                                ],
                                spacing=10,
                            ),
                            ft.Container(
                                content=self.register,
                                border=ft.Border.all(1, colors.BORDER),
                                border_radius=16,
                                padding=8,
                            ),
                            ft.Row(
                                [
                                    ft.TextButton(
                                        'Export CSV',
                                        icon=ft.Icons.TABLE_VIEW_OUTLINED,
                                        key='export-ledger-csv-button',
                                        on_click=lambda e: self._export('csv'),
                                    ),
                                    ft.TextButton(
                                        'Export JSON',
                                        icon=ft.Icons.DOWNLOAD_OUTLINED,
                                        key='export-ledger-json-button',
                                        on_click=lambda e: self._export('json'),
                                    ),
                                    ft.TextButton(
                                        'Import ledger JSON',
                                        icon=ft.Icons.UPLOAD_FILE_OUTLINED,
                                        key='import-ledger-json-button',
                                        on_click=lambda e: self._import(),
                                    ),
                                ]
                            ),
                        ],
                        spacing=16,
                        scroll=ft.ScrollMode.AUTO,
                        expand=True,
                    )
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                expand=True,
            ),
        )
        self.refresh()

    def _changed(self):
        self.on_changed()
        self.refresh()
        self.page.update()

    def refresh(self):
        accounts = self.ledger.list_accounts()
        self.total_text.value = money_format(self.ledger.total_balance())
        cleared = sum((a.cleared_balance for a in accounts), Decimal('0'))
        self.cleared_text.value = f'{money_format(cleared)} cleared'
        self.uncleared_text.value = (
            f'{money_format(self.ledger.total_balance() - cleared)} uncleared'
        )
        selected = self.account_filter.value or ''
        self.account_filter.options = [ft.dropdown.Option('', 'All accounts')] + [
            ft.dropdown.Option(a.id, a.name) for a in accounts
        ]
        self.account_filter.value = (
            selected if any(a.id == selected for a in accounts) else ''
        )
        self.account_row.controls = [
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(a.name, size=14, weight=ft.FontWeight.W_600),
                        ft.Text(
                            money_format(a.balance), size=20, weight=ft.FontWeight.BOLD
                        ),
                        ft.Text(
                            f'{money_format(a.cleared_balance)} cleared',
                            size=11,
                            color=colors.TEXT_SECONDARY,
                        ),
                    ],
                    spacing=2,
                ),
                padding=14,
                border=ft.Border.all(1, colors.BORDER),
                border_radius=14,
                ink=True,
                key=f'account-card-{a.id}',
                on_click=lambda e, account=a: self.account_dialog.open(account),
            )
            for a in accounts
        ]
        cleared_filter = None
        if self.cleared_filter.value == 'cleared':
            cleared_filter = True
        elif self.cleared_filter.value == 'uncleared':
            cleared_filter = False
        transactions = self.ledger.list_transactions(
            selected or None, self.search.value or '', cleared_filter
        )
        rows = []
        for transaction in transactions:
            rows.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(
                                transaction.date, width=100, color=colors.TEXT_SECONDARY
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        transaction.payee,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                    ft.Text(
                                        ' • '.join(
                                            part
                                            for part in (
                                                transaction.category,
                                                transaction.memo,
                                                transaction.account_name,
                                            )
                                            if part
                                        ),
                                        size=11,
                                        color=colors.TEXT_SECONDARY,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.Text(
                                money_format(transaction.amount),
                                weight=ft.FontWeight.BOLD,
                                color=colors.GREEN
                                if transaction.amount >= 0
                                else colors.TEXT_PRIMARY,
                            ),
                            ft.Icon(
                                ft.Icons.CHECK_CIRCLE
                                if transaction.cleared
                                else ft.Icons.RADIO_BUTTON_UNCHECKED,
                                size=18,
                                color=colors.GREEN
                                if transaction.cleared
                                else colors.TEXT_SECONDARY,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=12,
                    border=ft.Border.only(bottom=ft.BorderSide(1, colors.BORDER)),
                    key=f'transaction-{transaction.id}',
                    ink=True,
                    on_click=lambda e, item=transaction: self.transaction_dialog.open(
                        item
                    ),
                )
            )
        if not rows:
            rows = [
                ft.Container(
                    content=ft.Text(
                        'No transactions yet. Add one to start your register.',
                        color=colors.TEXT_SECONDARY,
                    ),
                    padding=24,
                )
            ]
        self.register.controls = rows

    def _import(self):
        path_input = ft.TextField(
            label='Ledger JSON path', key='ledger-import-path-input'
        )
        error = ft.Text(color=colors.RED)

        def restore(e):
            try:
                self.ledger.import_json(Path(path_input.value or ''))
            except (OSError, ValueError, KeyError, LedgerError) as exc:
                error.value = f'Could not import ledger: {exc}'
                self.page.update()
                return
            self.page.pop_dialog()
            self._changed()

        self.page.show_dialog(
            ft.AlertDialog(
                title='Import ledger JSON',
                content=dialog_form([path_input, error], height=120),
                actions=[
                    ft.TextButton(
                        'Cancel',
                        key='ledger-import-cancel-button',
                        on_click=lambda e: self.page.pop_dialog(),
                    ),
                    ft.FilledButton(
                        'Import', key='ledger-import-save-button', on_click=restore
                    ),
                ],
                modal=True,
            )
        )

    def _export(self, kind: str):
        destination = get_data_dir() / 'exports'
        destination.mkdir(parents=True, exist_ok=True)
        try:
            if kind == 'csv':
                path = self.ledger.export_csv(destination / 'transactions.csv')
            else:
                path = self.ledger.export_json(destination / 'ledger.json')
        except (OSError, LedgerError) as exc:
            self.page.show_dialog(
                ft.SnackBar(ft.Text(f'Could not export: {exc}'), bgcolor=colors.RED)
            )
            return
        self.page.show_dialog(ft.SnackBar(ft.Text(f'Export created: {path}')))
