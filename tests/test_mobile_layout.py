"""Phone-sized layout tests that preserve the desktop layout above 600 px."""

from types import SimpleNamespace

import flet as ft

from budget import BudgetCategory
from ledger import Ledger
from ui.budget import BudgetDashboard
from ui.savings import Dashboard
from ui.settings import AppHeader, SettingsView
from ui.shared import ConfirmDialog, MessageDialog, dialog_form, dialog_width
from ui.transactions import TransactionsDashboard


def page(width):
    return SimpleNamespace(width=width, height=800, update=lambda: None)


def test_budget_mobile_layout_switches_to_compact_rows():
    dashboard = BudgetDashboard(
        page(390),
        [
            BudgetCategory('Rent', 1000),
            BudgetCategory('Paycheck', 2000, 2000, 'income'),
        ],
        lambda: None,
    )

    assert dashboard.content.width == 366
    assert dashboard.left_column.width == 342
    assert dashboard.summary.control.visible is False
    assert dashboard._compact is True
    assert dashboard.row_height == 76
    assert dashboard.income_header.visible is False
    assert isinstance(dashboard.rows[0].control.content, ft.Column)
    assert dashboard.rows[0].control.height == 76


def test_budget_desktop_layout_remains_wide():
    dashboard = BudgetDashboard(
        page(1280), [BudgetCategory('Rent', 1000)], lambda: None
    )

    assert dashboard.content.width == 1080
    assert dashboard.summary.control.visible is True
    assert dashboard._compact is False
    assert dashboard.row_height == 58
    assert len(dashboard.rows[0].control.content.controls) == 5
    assert dashboard.income_header.visible is True


def test_settings_and_dialogs_adapt_to_phone_width():
    mobile = page(390)
    settings = SettingsView(mobile, lambda: None, None)
    assert settings.control.padding == 12
    assert isinstance(settings.nextcloud_card.content, ft.Column)
    assert isinstance(settings.data_card.content, ft.Column)
    assert settings.appearance_card.padding == 12

    message = MessageDialog(mobile, 'Title', 'Message')
    assert message.control.content.width == 342
    confirm = ConfirmDialog(mobile, 'Title', 'Message', lambda: None)
    assert confirm.control.content.width == 342
    form = dialog_form([], height=100, width=dialog_width(mobile))
    assert form.width == 320
    header = AppHeader(lambda: None)
    header.resize(390)
    assert header.control.padding == 12


def test_settings_desktop_spacing_is_unchanged():
    desktop = page(1280)
    settings = SettingsView(desktop, lambda: None, None)
    assert settings.control.padding == 24
    assert isinstance(settings.nextcloud_card.content, ft.Row)
    assert isinstance(settings.data_card.content, ft.Row)
    assert settings.appearance_card.padding == 16


def test_transactions_and_savings_adapt_to_phone_width(tmp_path):
    mobile = page(390)
    ledger = Ledger(tmp_path / 'ledger.db')
    ledger.add_account('Checking', 'checking', '100')
    transactions = TransactionsDashboard(mobile, ledger, lambda: None)
    assert transactions.control.padding == 12
    assert transactions.date_width == 76
    assert transactions.account_filter.width == 150
    assert isinstance(transactions.filters_row, ft.Column)

    savings = Dashboard(mobile, [], lambda: 100, lambda _balance: None, lambda: None)
    assert savings.content.width == 366
    assert savings.summary.control.padding == 12


def test_transactions_and_savings_desktop_layout_is_unchanged(tmp_path):
    desktop = page(1280)
    ledger = Ledger(tmp_path / 'ledger.db')
    ledger.add_account('Checking', 'checking', '100')
    transactions = TransactionsDashboard(desktop, ledger, lambda: None)
    assert transactions.control.padding == 24
    assert transactions.date_width == 100
    assert transactions.account_filter.width == 200
    assert isinstance(transactions.filters_row, ft.Row)

    savings = Dashboard(desktop, [], lambda: 100, lambda _balance: None, lambda: None)
    assert savings.content.width == 760
    assert savings.summary.control.padding == 22
