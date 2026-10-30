"""Savings page dialogs, cards, and dashboard composition."""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

import flet as ft

import colors
from fund import Fund
from ui.shared import (
    AccountBalanceDialog,
    AmountAdjustmentDialog,
    ConfirmDialog,
    dialog_form,
)
from utils import money_format, parse_money, parse_signed_money

FUND_CARD_HEIGHT = 140
DATED_FUND_CARD_HEIGHT = 170


class FundDialog:
    """Add or modify a fund through a single form and validation path."""

    def __init__(
        self, page: ft.Page, funds: list[Fund], on_changed: Callable[[], None]
    ):
        self.page = page
        self.funds = funds
        self.on_changed = on_changed

    def add(self):
        self._open()

    def modify(self, fund: Fund):
        self._open(fund)

    def _open(self, fund: Fund | None = None):
        modifying = fund is not None
        name_input = ft.TextField(
            label='Fund name', value=fund.name if fund else '', key='fund-name-input'
        )
        target_input = ft.TextField(
            label='Savings target ($)',
            value=str(fund.target) if fund else '',
            keyboard_type=ft.KeyboardType.NUMBER,
            key='fund-target-input',
        )
        balance_input = ft.TextField(
            label='Current balance ($)',
            value=str(fund.balance) if fund else '',
            keyboard_type=ft.KeyboardType.NUMBER,
            key='fund-balance-input',
        )
        recurring_input = ft.TextField(
            label='Recurring monthly transfer ($)',
            value=str(fund.recurring_transfer) if fund else '',
            keyboard_type=ft.KeyboardType.NUMBER,
            key='fund-recurring-input',
        )
        due_day_input = ft.Dropdown(
            label='Monthly due day (clamped to month end)',
            value=str(fund.due_day if fund else 31),
            options=[
                ft.dropdown.Option(
                    str(day),
                    'Last day of month (31)' if day == 31 else str(day),
                )
                for day in range(1, 32)
            ],
            key='fund-due-day-input',
        )
        target_date = fund.target_date if fund else None
        date_label = 'Target date: ' + (fund.target_date_as_str() if fund else 'None')
        error = ft.Text(color=colors.RED)

        def set_date(e):
            nonlocal target_date
            target_date = e.control.value
            date_button.content = 'Target date: ' + target_date.strftime('%m/%d/%Y')
            self.page.update()

        def clear_date(e):
            nonlocal target_date
            target_date = None
            date_button.content = 'Target date: None'
            self.page.update()

        today = datetime.today()
        date_picker = ft.DatePicker(
            first_date=datetime(1900, 1, 1),
            current_date=target_date or today,
            last_date=datetime(year=today.year + 50, month=today.month, day=1),
            on_change=set_date,
        )
        date_button = ft.Button(
            content=date_label,
            icon=ft.Icons.CALENDAR_MONTH,
            key='fund-date-button',
            on_click=lambda e: self.page.show_dialog(date_picker),
        )
        date_controls = ft.Row(
            [
                date_button,
                ft.IconButton(
                    icon=ft.Icons.CLEAR,
                    tooltip='Clear target date',
                    key='fund-date-clear',
                    on_click=clear_date,
                ),
            ],
            spacing=4,
        )

        def save(e):
            name = (name_input.value or '').strip()
            if not name:
                error.value = 'Enter a fund name.'
                self.page.update()
                return

            try:
                target = parse_money(target_input.value)
            except ValueError:
                error.value = 'Enter a valid target amount.'
                self.page.update()
                return

            try:
                balance = parse_signed_money(balance_input.value or '0')
            except ValueError:
                error.value = 'Enter a valid initial balance amount.'
                self.page.update()
                return

            try:
                recurring_transfer = parse_money(recurring_input.value or '0')
            except ValueError:
                error.value = 'Enter a valid recurring transfer amount.'
                self.page.update()
                return

            try:
                due_day = int(due_day_input.value or 31)
            except (TypeError, ValueError):
                error.value = 'Choose a due day between 1 and 31.'
                self.page.update()
                return

            if modifying:
                fund.name = name
                fund.set_target(target)
                fund.set_balance(balance)
                fund.set_target_date(target_date)
                fund.set_recurring_transfer(recurring_transfer)
                fund.set_due_day(due_day)
            else:
                self.funds.insert(
                    0,
                    Fund(
                        name,
                        target,
                        balance,
                        target_date,
                        recurring_transfer,
                        due_day=due_day,
                    ),
                )
            self.page.pop_dialog()
            self.on_changed()

        actions: list[ft.Control] = []
        if modifying:

            def delete(e):
                self.page.pop_dialog()

                def confirmed():
                    self.funds.remove(fund)
                    self.on_changed()

                ConfirmDialog(
                    self.page,
                    'Delete fund?',
                    f'Delete "{fund.name}" and its generated budget expense? '
                    'This cannot be undone.',
                    confirmed,
                ).open()

            actions.append(
                ft.FilledButton(
                    'Delete',
                    key='fund-delete-button',
                    bgcolor=colors.RED,
                    on_click=delete,
                )
            )
            actions.append(
                ft.TextButton(
                    'Cancel',
                    key='fund-cancel-button',
                    on_click=lambda e: self.page.pop_dialog(),
                )
            )
        else:
            actions.append(
                ft.TextButton(
                    'Cancel',
                    key='fund-cancel-button',
                    on_click=lambda e: self.page.pop_dialog(),
                )
            )
        actions.append(ft.FilledButton('Save', key='fund-save-button', on_click=save))

        self.control = ft.AlertDialog(
            title='Modify fund' if modifying else 'Add fund',
            content=dialog_form(
                [
                    name_input,
                    target_input,
                    balance_input,
                    recurring_input,
                    date_controls,
                    due_day_input,
                    error,
                ],
                height=420,
            ),
            actions=actions,
            modal=True,
        )
        self.page.show_dialog(self.control)


class SavingsSummary:
    """Summary card showing the account total and allocated savings."""

    def __init__(
        self,
        page: ft.Page,
        get_account_balance: Callable[[], Decimal | None],
        on_account_balance_saved: Callable[[Decimal], None],
        on_refresh: Callable[[], None],
    ):
        self.page = page
        self.get_account_balance = get_account_balance
        self.on_refresh = on_refresh
        self.account_balance_dialog = AccountBalanceDialog(
            page, on_account_balance_saved
        )
        self.total_savings_text = ft.Text(size=32, weight=ft.FontWeight.BOLD)
        self.total_allocated_text = ft.Text(size=13, color=colors.TEXT_SECONDARY)
        self.total_unallocated_text = ft.Text(size=12, color=colors.TEXT_SECONDARY)
        self.progress_bar = ft.ProgressBar(
            value=0,
            color=colors.BLUE,
            bgcolor=colors.BORDER,
            height=8,
            border_radius=10,
        )
        self.control = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(
                                        'TOTAL SAVINGS',
                                        size=11,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    self.total_savings_text,
                                ],
                                spacing=6,
                                expand=True,
                            ),
                            ft.Container(
                                content=ft.Icon(
                                    ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, size=26
                                ),
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
            key='savings-summary',
            on_click=self._edit_account_balance,
        )

    def _edit_account_balance(self, e):
        current = self.get_account_balance()
        if current is not None:
            self.account_balance_dialog.modify(current, self.on_refresh)

    def refresh(self, total_savings: Decimal, total_allocated: Decimal):
        self.total_savings_text.value = money_format(total_savings)
        self.total_allocated_text.value = f'{money_format(total_allocated)} allocated of {self.total_savings_text.value}'
        self.total_unallocated_text.value = (
            f'{money_format(total_savings - total_allocated)} unallocated'
        )
        self.progress_bar.value = (
            float(min(total_allocated / total_savings, Decimal('1')))
            if total_savings > 0
            else 0
        )


class FundCard:
    """Presentation and click behavior for one fund."""

    def __init__(
        self,
        page: ft.Page,
        fund: Fund,
        fund_dialog: FundDialog,
        adjustment_dialog: AmountAdjustmentDialog,
        on_balance_changed: Callable[[], None],
        on_contribution: Callable[[Fund, Decimal], None] | None = None,
    ):
        self.page = page
        self.fund = fund
        self.fund_dialog = fund_dialog
        self.adjustment_dialog = adjustment_dialog
        self.on_balance_changed = on_balance_changed
        self.on_contribution = on_contribution
        self.icon_box = ft.Container(
            content=ft.Icon(ft.Icons.SHIELD, size=24),
            bgcolor=colors.SURFACE,
            border_radius=12,
            padding=11,
        )
        self.name_text = ft.Text(size=15, weight=ft.FontWeight.W_600)
        self.target_text = ft.Text(size=12)
        self.balance_text = ft.Text(size=16, weight=ft.FontWeight.BOLD)
        self.funded_text = ft.Text(size=12)
        self.progress_bar = ft.ProgressBar(
            height=6, border_radius=10, color=colors.BLUE, bgcolor=colors.BORDER
        )
        self.card_content = ft.Column(
            [
                ft.Row(
                    [
                        self.icon_box,
                        ft.Column(
                            [self.name_text, self.target_text], spacing=4, expand=True
                        ),
                        ft.Column(
                            [self.balance_text, self.funded_text],
                            spacing=4,
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                            expand=True,
                        ),
                        ft.Column(
                            [
                                ft.IconButton(
                                    icon=ft.Icons.ADD,
                                    icon_size=18,
                                    width=30,
                                    height=30,
                                    size_constraints=ft.BoxConstraints(
                                        min_width=30,
                                        max_width=30,
                                        min_height=30,
                                        max_height=30,
                                    ),
                                    padding=0,
                                    tooltip='Add to balance',
                                    key=f'fund-add-{fund.id}',
                                    on_click=lambda e: self._adjust(1),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.REMOVE,
                                    icon_size=18,
                                    width=30,
                                    height=30,
                                    size_constraints=ft.BoxConstraints(
                                        min_width=30,
                                        max_width=30,
                                        min_height=30,
                                        max_height=30,
                                    ),
                                    padding=0,
                                    tooltip='Remove from balance',
                                    key=f'fund-remove-{fund.id}',
                                    on_click=lambda e: self._adjust(-1),
                                ),
                            ],
                            spacing=0,
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
            self.target_date_text = ft.Text(size=12)
            self.on_track_status_text = ft.Text(size=12)
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
            key=f'fund-card-{fund.id}',
            on_click=self._edit,
        )
        self.refresh()

    def _edit(self, e):
        self.fund_dialog.modify(self.fund)

    def _adjust(self, direction):
        if self.on_contribution is not None:
            self.adjustment_dialog.open(
                self.fund.name,
                self.fund.balance,
                direction,
                lambda new_balance: self.on_contribution(
                    self.fund, new_balance - self.fund.balance
                ),
            )
            return

        def save(new_balance):
            self.fund.set_balance(new_balance)
            self.on_balance_changed()

        self.adjustment_dialog.open(self.fund.name, self.fund.balance, direction, save)

    def refresh(self):
        self.name_text.value = self.fund.name
        self.target_text.value = (
            f'Target {money_format(self.fund.target)}'
            if self.fund.target > 0
            else 'No target set'
        )
        self.balance_text.value = money_format(self.fund.balance)
        self.balance_text.color = colors.RED if self.fund.is_overdrawn else None
        self.funded_text.value = (
            'Overdrawn'
            if self.fund.is_overdrawn
            else (
                f'{self.fund.compute_percent_funded():.1f}% funded'
                if self.fund.target > 0
                else 'No target'
            )
        )
        self.progress_bar.value = float(
            min(
                max(self.fund.compute_percent_funded() / 100, Decimal('0')),
                Decimal('1'),
            )
        )
        if self.fund.target_date is not None and self.target_date_text is not None:
            self.target_date_text.value = (
                f'Target date: {self.fund.target_date_as_str()} '
                f'({self.fund.time_remaining_as_str()})'
            )
            self.on_track_status_text.value = self.fund.get_on_track_status_as_str()
            self.on_track_status_text.color = (
                colors.GREEN if self.fund.on_track else colors.RED
            )


class FundList:
    """Reorderable fund cards and the add-fund action."""

    def __init__(
        self,
        page: ft.Page,
        funds: list[Fund],
        on_changed: Callable[[], None],
        on_contribution: Callable[[Fund, Decimal], None] | None = None,
    ):
        self.page = page
        self.funds = funds
        self.on_changed = on_changed
        self.on_contribution = on_contribution
        self.dialog = FundDialog(page, funds, self._funds_changed)
        self.adjustment_dialog = AmountAdjustmentDialog(page)
        self.add_button = ft.OutlinedButton(
            'Add fund',
            icon=ft.Icons.ADD_CIRCLE_OUTLINE,
            expand=True,
            key='add-fund-button',
            on_click=self._add_fund,
        )
        self.list_view = ft.ReorderableListView(
            spacing=12,
            on_reorder=self._reorder,
            scroll=ft.ScrollMode.HIDDEN,
        )
        self.control = ft.Column(
            [ft.Row([self.add_button], spacing=12), self.list_view],
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.cards: list[FundCard] = []
        self.refresh()

    def _add_fund(self, e):
        self.dialog.add()

    def _reorder(self, e):
        self.funds.insert(e.new_index, self.funds.pop(e.old_index))
        self.on_changed()

    def _funds_changed(self):
        self.on_changed()

    def _balance_changed(self):
        self.on_changed()

    def refresh(self):
        self.cards = [
            FundCard(
                self.page,
                fund,
                self.dialog,
                self.adjustment_dialog,
                self._balance_changed,
                self.on_contribution,
            )
            for fund in self.funds
        ]
        self.list_view.controls = [card.control for card in self.cards]
        self.list_view.height = (
            sum(
                DATED_FUND_CARD_HEIGHT
                if fund.target_date is not None
                else FUND_CARD_HEIGHT
                for fund in self.funds
            )
            + max(0, len(self.funds) - 1) * 12
        )


class Dashboard:
    """Responsive dashboard composed from the summary and fund list."""

    def __init__(
        self,
        page: ft.Page,
        funds: list[Fund],
        get_account_balance: Callable[[], Decimal],
        on_account_balance_saved: Callable[[Decimal], None],
        on_funds_changed: Callable[[], None],
        on_fund_contribution: Callable[[Fund, Decimal], None] | None = None,
    ):
        self.page = page
        self.funds = funds
        self.summary = SavingsSummary(
            page,
            get_account_balance,
            on_account_balance_saved,
            self._refresh_after_balance_change,
        )
        self.fund_list = FundList(page, funds, on_funds_changed, on_fund_contribution)
        self.content = ft.Container(
            content=ft.Column(
                [self.summary.control, self.fund_list.control],
                spacing=18,
                scroll=ft.ScrollMode.AUTO,
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
        balance = self.get_account_balance()
        total_allocated = sum((fund.balance for fund in self.funds), Decimal('0'))
        self.summary.refresh(balance or Decimal('0'), total_allocated)
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
