"""Headless tests for the local ledger register and account balances."""

from decimal import Decimal

import flet as ft
from ui_helpers import click, enter, find_by_key, find_by_text, navigate, visible_page


async def test_ledger_account_and_transaction_flow(headless_app):
    app = headless_app.app
    page = headless_app.page

    assert app.ledger.total_balance() == Decimal('5000.00')
    navigate(page, app, 2)
    assert visible_page(app, 2)
    find_by_key(page, 'nav-transactions')

    await click(page, 'add-account-button')
    await enter(page, 'account-name-input', 'Savings')
    await enter(page, 'account-opening-input', '250')
    await click(page, 'account-save-button')
    assert len(find_by_text(page, '$250.00')) >= 1

    await click(page, 'add-transaction-button')
    await enter(page, 'transaction-date-input', '2026-10-15')
    await enter(page, 'transaction-payee-input', 'Paycheck')
    await enter(page, 'transaction-amount-input', '1000')
    await enter(page, 'transaction-category-input', 'Income')
    await click(page, 'transaction-save-button')

    assert app.ledger.total_balance() == Decimal('6250.00')
    assert len(find_by_text(page, 'Paycheck')) == 1
    assert app.ledger.total_balance() == Decimal('6250.00')

    transaction = app.ledger.list_transactions(search='Paycheck')[0]
    await click(page, f'transaction-{transaction.id}')
    await enter(page, 'transaction-amount-input', '1100')
    await click(page, 'transaction-save-button')
    assert app.ledger.total_balance() == Decimal('6350.00')

    await click(page, f'transaction-{transaction.id}')
    await click(page, 'transaction-delete-button')
    await click(page, 'confirm-action-button')
    assert app.ledger.list_transactions(search='Paycheck') == []
    assert app.ledger.total_balance() == Decimal('5250.00')


async def test_transactions_search_and_cleared_filter(headless_app):
    app = headless_app.app
    page = headless_app.page
    account = app.ledger.default_account()
    app.ledger.add_transaction(
        account.id, '2026-10-16', 'Groceries', amount='-40', category='Food'
    )
    app.ledger.add_transaction(
        account.id, '2026-10-17', 'Paycheck', amount='100', cleared=True
    )
    app.transactions_dashboard.refresh()

    navigate(page, app, 2)
    await enter(page, 'transactions-search', 'groceries')
    app.transactions_dashboard.refresh()
    assert len(find_by_text(page, 'Groceries')) == 1
    assert len(find_by_text(page, 'Paycheck')) == 0

    await enter(page, 'transactions-search', '')
    app.transactions_dashboard.cleared_filter.value = 'cleared'
    app.transactions_dashboard.refresh()
    assert len(find_by_text(page, 'Paycheck')) == 1
    assert len(find_by_text(page, 'Groceries')) == 0


async def test_theme_toggle_persists_to_the_ledger(headless_app):
    app = headless_app.app
    page = headless_app.page

    await click(page, 'settings-button')
    switch = find_by_key(page, 'theme-mode-switch')
    switch.value = True
    switch.on_change(type('Event', (), {'control': switch})())

    assert app.theme_mode == 'light'
    assert page.theme_mode == ft.ThemeMode.LIGHT
    assert app.ledger.get_meta('theme_mode') == 'light'

    switch.value = False
    switch.on_change(type('Event', (), {'control': switch})())
    assert app.theme_mode == 'dark'
    assert page.theme_mode == ft.ThemeMode.DARK
    assert app.ledger.get_meta('theme_mode') == 'dark'


async def test_ledger_json_import_restores_accounts_and_transactions(headless_app):
    app = headless_app.app
    page = headless_app.page
    export = app.ledger.export_json(headless_app.paths['funds'].parent / 'ledger.json')
    account = app.ledger.default_account()
    app.ledger.add_transaction(account.id, '2026-10-18', 'Temporary', amount='50')
    app.transactions_dashboard.refresh()
    assert app.ledger.total_balance() == 5050

    navigate(page, app, 2)
    await click(page, 'import-ledger-json-button')
    await enter(page, 'ledger-import-path-input', str(export))
    await click(page, 'ledger-import-save-button')

    assert app.ledger.total_balance() == 5000
    assert app.ledger.list_transactions(search='Temporary') == []


async def test_savings_balance_change_refreshes_the_register(headless_app):
    app = headless_app.app
    page = headless_app.page

    app.set_account_balance(Decimal('5500.00'))

    assert app.ledger.total_balance() == Decimal('5500.00')
    assert len(find_by_text(page, 'Balance adjustment')) == 1


async def test_account_opening_and_edit_create_ledger_transactions(headless_app):
    app = headless_app.app
    page = headless_app.page
    navigate(page, app, 2)

    await click(page, 'add-account-button')
    await enter(page, 'account-name-input', 'Checking')
    await enter(page, 'account-opening-input', '250')
    await click(page, 'account-save-button')

    account = next(a for a in app.ledger.list_accounts() if a.name == 'Checking')
    opening = [
        item
        for item in app.ledger.list_transactions(search='Opening balance')
        if item.account_id == account.id
    ]
    assert len(opening) == 1
    assert opening[0].amount == Decimal('250.00')

    await click(page, f'account-card-{account.id}')
    await enter(page, 'account-opening-input', '400')
    await click(page, 'account-save-button')
    adjustments = app.ledger.list_transactions(search='Balance adjustment')
    assert len(adjustments) == 1
    assert adjustments[0].amount == Decimal('150.00')
    assert len(find_by_text(page, 'Balance adjustment')) == 1

    await click(page, f'account-card-{account.id}')
    await click(page, 'account-delete-button')
    await click(page, 'confirm-action-button')
    assert all(a.id != account.id for a in app.ledger.list_accounts())
    assert find_by_key(page, f'account-card-{account.id}', count=0) == []
