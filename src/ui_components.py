"""Flet components for the savings funds application.

Each component owns the controls it renders and the events that belong to those
controls. Dialog classes keep add and modify flows together so shared fields,
validation, and presentation have a single implementation.
"""

import asyncio
from datetime import datetime
from typing import Callable

import flet as ft

import colors
from fund import Fund
from nextcloud import load_nextcloud_sync_data, ping_nextcloud_server, save_nextcloud_sync_data
from utils import money_format


class SettingsButton:
    """Settings entry point used by the application header."""

    def __init__(self, on_click: Callable):
        self.control = ft.IconButton(
            icon=ft.Icons.SETTINGS_OUTLINED,
            tooltip='Settings',
            icon_color=colors.TEXT_SECONDARY,
            on_click=lambda e: on_click(),
        )


class AppHeader:
    """Top-level application branding and settings button."""

    def __init__(self, on_settings: Callable):
        self.settings_button = SettingsButton(on_settings)
        self.control = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, size=23),
                        bgcolor=colors.BLUE,
                        border_radius=12,
                        padding=10,
                    ),
                    ft.Column(
                        [
                            ft.Text('Savings Funds', size=20, weight=ft.FontWeight.BOLD),
                            ft.Text('Give every dollar a purpose.', size=12),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    self.settings_button.control,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=20,
            border=ft.Border.only(bottom=ft.BorderSide(1, colors.BORDER)),
        )


class LoadingDialog:
    """Modal progress indicator used during startup synchronization."""

    def __init__(self, page: ft.Page, message: str):
        self.page = page
        self.control = ft.AlertDialog(
            modal=True,
            content=ft.Row(
                controls=[ft.ProgressRing(width=24, height=24, stroke_width=3), ft.Text(message)],
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=20,
            ),
        )

    def open(self):
        self.page.show_dialog(self.control)


class NextcloudConfigDialog:
    """Add or edit the saved Nextcloud connection using one shared form."""

    def __init__(self, page: ft.Page, on_saved: Callable[[dict], None]):
        self.page = page
        self.on_saved = on_saved

    def add(self, on_complete: asyncio.Event):
        self._open({}, 'Enter nextcloud server info (optional)', on_complete=on_complete)

    def modify(self):
        self._open(load_nextcloud_sync_data() or {}, 'Modify Nextcloud config')

    def _open(self, initial: dict, title: str, on_complete: asyncio.Event | None = None):
        url_input = ft.TextField(label='URL', value=initial.get('base_url', ''))
        username_input = ft.TextField(label='Username', value=initial.get('username', ''))
        password_input = ft.TextField(
            label='Password',
            value=initial.get('password', ''),
            password=True,
            can_reveal_password=True,
        )
        data_path_input = ft.TextField(label='Data path', value=initial.get('data_path', ''))
        error = ft.Text(color=colors.RED)

        def skip(e):
            data = {}
            save_nextcloud_sync_data(data)
            self.page.pop_dialog()
            if on_complete is not None:
                on_complete.set()

        async def save(e):
            error.value = ''
            self.page.update()
            data = {
                'base_url': (url_input.value or '').strip(),
                'username': (username_input.value or '').strip(),
                'password': password_input.value or '',
                'data_path': (data_path_input.value or '').strip(),
            }
            success, error_message = await asyncio.to_thread(ping_nextcloud_server, data)
            if not success:
                error.value = error_message
                self.page.update()
                return

            save_nextcloud_sync_data(data)
            self.page.pop_dialog()
            if on_complete is not None:
                on_complete.set()
            else:
                self.on_saved(data)

        actions = []
        if on_complete is not None:
            actions.append(ft.TextButton('Skip', on_click=skip))
        else:
            actions.append(ft.TextButton('Cancel', on_click=lambda e: self.page.pop_dialog()))
        actions.append(ft.FilledButton('Done' if on_complete is not None else 'Save', on_click=save))

        self.control = ft.AlertDialog(
            title=title,
            content=ft.Column([url_input, username_input, password_input, data_path_input, error],
                              tight=True),
            actions=actions,
            modal=True,
        )
        self.page.show_dialog(self.control)


class AccountBalanceDialog:
    """Shared initial-entry and edit dialog for the account balance."""

    def __init__(self, page: ft.Page, on_saved: Callable[[float], None]):
        self.page = page
        self.on_saved = on_saved

    def add(self, on_complete: Callable[[], None]):
        self._open(None, 'Enter your current account balance', on_complete)

    def modify(self, current_balance: float, on_complete: Callable[[], None]):
        self._open(current_balance, 'Modify account balance', on_complete)

    def _open(self, initial_value: float | None, title: str, on_complete: Callable[[], None]):
        value = '' if initial_value is None else str(initial_value)
        balance_input = ft.TextField(
            label='Account balance ($)', value=value, keyboard_type=ft.KeyboardType.NUMBER
        )
        error = ft.Text(color=colors.RED)

        def save(e):
            try:
                balance = float(balance_input.value)
                if balance <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                error.value = 'Enter a valid account balance amount.'
                self.page.update()
                return

            self.on_saved(balance)
            self.page.pop_dialog()
            on_complete()

        actions = []
        if initial_value is not None:
            actions.append(ft.TextButton('Cancel', on_click=lambda e: self.page.pop_dialog()))
        actions.append(ft.FilledButton('Done', on_click=save))

        self.control = ft.AlertDialog(
            title=title,
            content=ft.Column([balance_input, error], tight=True, width=320),
            actions=actions,
            modal=True,
        )
        self.page.show_dialog(self.control)


class FundDialog:
    """Add or modify a fund through a single form and validation path."""

    def __init__(self, page: ft.Page, funds: list[Fund], on_changed: Callable[[], None]):
        self.page = page
        self.funds = funds
        self.on_changed = on_changed

    def add(self):
        self._open()

    def modify(self, fund: Fund):
        self._open(fund)

    def _open(self, fund: Fund | None = None):
        modifying = fund is not None
        name_input = ft.TextField(label='Fund name', value=fund.name if fund else '')
        target_input = ft.TextField(
            label='Savings target ($)', value=str(fund.target) if fund else '',
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        balance_input = ft.TextField(
            label='Current balance ($)', value=str(fund.balance) if fund else '',
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        recurring_input = ft.TextField(
            label='Recurring monthly transfer ($)',
            value=str(fund.recurring_transfer) if fund else '',
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        target_date = fund.target_date if fund else None
        date_label = 'Target date: ' + (fund.target_date_as_str() if fund else 'None')
        error = ft.Text(color=colors.RED)

        def set_date(e):
            nonlocal target_date
            target_date = e.control.value
            date_button.content = 'Target date: ' + target_date.strftime('%m/%d/%Y')
            self.page.update()

        today = datetime.today()
        date_picker = ft.DatePicker(
            first_date=today,
            current_date=today,
            last_date=datetime(year=today.year + 50, month=today.month, day=1),
            on_change=set_date,
        )
        date_button = ft.Button(
            content=date_label,
            icon=ft.Icons.CALENDAR_MONTH,
            on_click=lambda e: self.page.show_dialog(date_picker),
        )

        def save(e):
            name = (name_input.value or '').strip()
            if not name:
                error.value = 'Enter a fund name.'
                self.page.update()
                return

            try:
                target = float(target_input.value or '-1')
                if target < 0:
                    raise ValueError
            except ValueError:
                error.value = 'Enter a valid target amount.'
                self.page.update()
                return

            try:
                balance = float(balance_input.value or '0')
            except ValueError:
                error.value = 'Enter a valid initial balance amount.'
                self.page.update()
                return

            try:
                recurring_transfer = float(recurring_input.value or '0')
            except ValueError:
                error.value = 'Enter a valid recurring transfer amount.'
                self.page.update()
                return

            if modifying:
                fund.name = name
                fund.set_target(target)
                fund.set_balance(balance)
                fund.set_target_date(target_date)
                fund.set_recurring_transfer(recurring_transfer)
            else:
                self.funds.insert(0, Fund(name, target, balance, target_date, recurring_transfer))
            self.page.pop_dialog()
            self.on_changed()

        actions = []
        if modifying:
            def delete(e):
                self.funds.remove(fund)
                self.page.pop_dialog()
                self.on_changed()

            actions.append(ft.FilledButton('Delete', bgcolor=colors.RED, on_click=delete))
            actions.append(ft.TextButton('Cancel', on_click=lambda e: self.page.pop_dialog()))
        else:
            actions.append(ft.TextButton('Cancel', on_click=lambda e: self.page.pop_dialog()))
        actions.append(ft.FilledButton('Save', on_click=save))

        self.control = ft.AlertDialog(
            title='Modify fund' if modifying else 'Add fund',
            content=ft.Column(
                [name_input, target_input, balance_input, recurring_input, date_button, error],
                tight=True,
                width=320,
            ),
            actions=actions,
            modal=True,
        )
        self.page.show_dialog(self.control)


class SavingsSummary:
    """Summary card showing the account total and allocated savings."""

    def __init__(self, page: ft.Page, get_account_balance: Callable[[], float],
                 on_account_balance_saved: Callable[[float], None],
                 on_refresh: Callable[[], None]):
        self.page = page
        self.get_account_balance = get_account_balance
        self.on_refresh = on_refresh
        self.account_balance_dialog = AccountBalanceDialog(page, on_account_balance_saved)
        self.total_savings_text = ft.Text(size=32, weight=ft.FontWeight.BOLD)
        self.total_allocated_text = ft.Text(size=13, color=colors.TEXT_SECONDARY)
        self.total_unallocated_text = ft.Text(size=12, color=colors.TEXT_SECONDARY)
        self.progress_bar = ft.ProgressBar(
            value=0, color=colors.BLUE, bgcolor=colors.BORDER, height=8, border_radius=10
        )
        self.control = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text('TOTAL SAVINGS', size=11, weight=ft.FontWeight.BOLD),
                                    self.total_savings_text,
                                ],
                                spacing=6,
                                expand=True,
                            ),
                            ft.Container(
                                content=ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, size=26),
                                border_radius=14,
                                padding=14,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.total_allocated_text,
                    self.progress_bar,
                    self.total_unallocated_text,
                ],
                spacing=12,
                expand=True,
            ),
            border=ft.Border.all(1, colors.BORDER),
            border_radius=18,
            padding=22,
            on_click=self._edit_account_balance,
        )

    def _edit_account_balance(self, e):
        self.account_balance_dialog.modify(self.get_account_balance(), self.on_refresh)

    def refresh(self, total_savings: float, total_allocated: float):
        self.total_savings_text.value = money_format(total_savings)
        self.total_allocated_text.value = (
            f'{money_format(total_allocated)} allocated of {self.total_savings_text.value}'
        )
        self.total_unallocated_text.value = (
            f'{money_format(total_savings - total_allocated)} unallocated'
        )
        self.progress_bar.value = min(total_allocated / total_savings, 1) if total_savings > 0 else 0


class FundCard:
    """Presentation and click behavior for one fund."""

    def __init__(self, page: ft.Page, fund: Fund, fund_dialog: FundDialog):
        self.page = page
        self.fund = fund
        self.fund_dialog = fund_dialog
        self.icon_box = ft.Container(
            content=ft.Icon(ft.Icons.SHIELD, size=24),
            bgcolor=colors.SURFACE,
            border_radius=12,
            padding=11,
        )
        self.name_text = ft.Text(size=15, weight=ft.FontWeight.W_600, expand=True)
        self.target_text = ft.Text(size=12, expand=True)
        self.balance_text = ft.Text(size=16, weight=ft.FontWeight.BOLD, expand=True)
        self.funded_text = ft.Text(size=12, expand=True)
        self.progress_bar = ft.ProgressBar(
            height=6, border_radius=10, color=colors.BLUE, bgcolor=colors.BORDER, expand=True
        )
        self.card_content = ft.Column(
            [
                ft.Row(
                    [
                        self.icon_box,
                        ft.Column([self.name_text, self.target_text], spacing=4, expand=True),
                        ft.Column(
                            [self.balance_text, self.funded_text],
                            spacing=4,
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                            expand=True,
                        ),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self.progress_bar,
            ],
            spacing=14,
            expand=True,
            margin=ft.Margin.only(right=22),
        )
        self.target_date_text = None
        self.on_track_status_text = None
        if fund.target_date is not None:
            self.target_date_text = ft.Text(size=12, expand=True)
            self.on_track_status_text = ft.Text(size=12, expand=True)
            self.card_content.controls.append(
                ft.Row(
                    [
                        ft.Column([self.target_date_text], spacing=4, expand=True),
                        ft.Column(
                            [self.on_track_status_text],
                            spacing=4,
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                            expand=True,
                        ),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        self.control = ft.Container(
            content=self.card_content,
            border=ft.Border.all(1, colors.BORDER),
            border_radius=16,
            padding=16,
            expand=True,
            margin=ft.Margin.only(bottom=8),
            on_click=self._edit,
        )
        self.refresh()

    def _edit(self, e):
        self.fund_dialog.modify(self.fund)

    def refresh(self):
        self.name_text.value = self.fund.name
        self.target_text.value = (
            f'Target {money_format(self.fund.target)}' if self.fund.target > 0 else 'No target set'
        )
        self.balance_text.value = money_format(self.fund.balance)
        self.funded_text.value = (
            f'{self.fund.compute_percent_funded():.1f}% funded'
            if self.fund.target > 0 else 'No target'
        )
        self.progress_bar.value = min(max(self.fund.compute_percent_funded() / 100, 0), 1)
        if self.fund.target_date is not None and self.target_date_text is not None:
            self.target_date_text.value = (
                f'Target date: {self.fund.target_date_as_str()} '
                f'({self.fund.time_remaining_as_str()})'
            )
            self.on_track_status_text.value = self.fund.get_on_track_status_as_str()
            self.on_track_status_text.color = colors.GREEN if self.fund.on_track else colors.RED


class FundList:
    """Reorderable fund cards and the add-fund action."""

    def __init__(self, page: ft.Page, funds: list[Fund], on_changed: Callable[[], None]):
        self.page = page
        self.funds = funds
        self.on_changed = on_changed
        self.dialog = FundDialog(page, funds, self._funds_changed)
        self.add_button = ft.OutlinedButton(
            'Add fund', icon=ft.Icons.ADD_CIRCLE_OUTLINE, expand=True, on_click=self._add_fund
        )
        self.list_view = ft.ReorderableListView(
            expand=True, spacing=12, on_reorder=self._reorder
        )
        self.control = ft.Column(
            [ft.Row([self.add_button], spacing=12), self.list_view],
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.cards = []
        self.refresh()

    def _add_fund(self, e):
        self.dialog.add()

    def _reorder(self, e):
        self.funds.insert(e.new_index, self.funds.pop(e.old_index))
        self.on_changed()

    def _funds_changed(self):
        self.on_changed()

    def refresh(self):
        self.cards = [FundCard(self.page, fund, self.dialog) for fund in self.funds]
        self.list_view.controls = [card.control for card in self.cards]


class Dashboard:
    """Responsive dashboard composed from the summary and fund list."""

    def __init__(self, page: ft.Page, funds: list[Fund], get_account_balance: Callable[[], float],
                 on_account_balance_saved: Callable[[float], None],
                 on_funds_changed: Callable[[], None]):
        self.page = page
        self.funds = funds
        self.summary = SavingsSummary(
            page, get_account_balance, on_account_balance_saved, self._refresh_after_balance_change
        )
        self.fund_list = FundList(page, funds, on_funds_changed)
        self.content = ft.Container(
            content=ft.Column(
                [self.summary.control, self.fund_list.control],
                spacing=18,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )
        )
        self.control = ft.Row(
            [self.content],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.START,
            expand=True,
        )
        self.refresh()
        self.resize()

    def refresh(self):
        self.summary.refresh(self.get_account_balance(), sum(fund.balance for fund in self.funds))
        self.fund_list.refresh()

    def _refresh_after_balance_change(self):
        self.refresh()
        self.page.update()

    def get_account_balance(self):
        return self.summary.get_account_balance()

    def resize(self):
        screen_width = self.page.width or 0
        margin = 12 if screen_width < 600 else 24
        self.content.width = min(760, max(screen_width - 2 * margin, 0))
        self.content.padding = margin


class SettingsView:
    """Settings screen and its Nextcloud configuration entry."""

    def __init__(self, page: ft.Page, on_back: Callable, nextcloud_dialog: NextcloudConfigDialog):
        self.page = page
        self.nextcloud_dialog = nextcloud_dialog
        self.nextcloud_card = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(ft.Icons.CLOUD_OUTLINED, size=24, color=colors.BLUE),
                        bgcolor=colors.SURFACE,
                        border_radius=10,
                        padding=12,
                    ),
                    ft.Column(
                        [
                            ft.Text('Nextcloud Sync', size=15, weight=ft.FontWeight.W_600),
                            ft.Text(
                                'Configure server connection and sync settings',
                                size=12,
                                color=colors.TEXT_SECONDARY,
                            ),
                        ],
                        spacing=4,
                        expand=True,
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color=colors.TEXT_SECONDARY),
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=16,
            border=ft.Border.all(1, colors.BORDER),
            border_radius=14,
            ink=True,
            on_click=self._modify_nextcloud,
        )
        self.control = ft.Container(
            visible=False,
            padding=24,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.IconButton(
                                icon=ft.Icons.ARROW_BACK,
                                tooltip='Back to dashboard',
                                on_click=lambda e: on_back(),
                            ),
                            ft.Text('Settings', size=24, weight=ft.FontWeight.BOLD, expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(height=8),
                    self.nextcloud_card,
                ],
                spacing=16,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

    def _modify_nextcloud(self, e):
        self.nextcloud_dialog.modify()

    def show(self):
        self.control.visible = True
        self.page.update()

    def hide(self):
        self.control.visible = False
