"""EveryDollar-inspired monthly budget page."""

from collections.abc import Callable
from decimal import Decimal

import flet as ft

import colors
from budget import (
    BudgetCategory,
    current_period,
    format_period,
    reorder_budget_categories,
)
from fund import Fund
from ui.shared import AmountAdjustmentDialog, ConfirmDialog, MessageDialog, dialog_form
from utils import money_format, parse_money, parse_signed_money

BUDGET_ROW_HEIGHT = 58


def shift_period(period: str, months: int) -> str:
    """Move a ``YYYY-MM`` period by a number of calendar months."""
    year, month = (int(part) for part in period.split('-', 1))
    index = year * 12 + (month - 1) + months
    return f'{index // 12:04d}-{index % 12 + 1:02d}'


class BudgetCategoryDialog:
    """Add, edit, or remove a monthly budget line."""

    def __init__(
        self,
        page: ft.Page,
        categories: list[BudgetCategory],
        on_changed: Callable[[], None],
    ):
        self.page = page
        self.categories = categories
        self.on_changed = on_changed

    def add(self, kind='expense'):
        self._open(kind=kind)

    def modify(self, category: BudgetCategory):
        self._open(category)

    def _open(self, category: BudgetCategory | None = None, kind='expense'):
        is_modify = category is not None
        if category is not None and category.source_fund_id is not None:
            MessageDialog(
                self.page,
                'Generated from a fund',
                "This budget line is controlled by the fund's recurring monthly "
                'transfer. Edit the amount in Savings; spending can still be '
                'adjusted here.',
            ).open()
            return
        kind = category.kind if category is not None else kind
        name_input = ft.TextField(
            label='Category name',
            value=category.name if category else '',
            key='budget-category-name-input',
        )
        budget_input = ft.TextField(
            label='Monthly income ($)' if kind == 'income' else 'Planned ($)',
            value=str(category.budgeted) if category else '',
            keyboard_type=ft.KeyboardType.NUMBER,
            key='budget-category-budget-input',
        )
        spent_input = ft.TextField(
            label='Received this month ($)'
            if kind == 'income'
            else 'Spent this month ($)',
            value=str(category.spent) if category else '0',
            keyboard_type=ft.KeyboardType.NUMBER,
            key='budget-category-spent-input',
        )
        error = ft.Text(color=colors.RED)

        def save(e):
            name = (name_input.value or '').strip()
            if not name:
                error.value = 'Enter a category name.'
                self.page.update()
                return
            try:
                budgeted = parse_money(budget_input.value)
                spent = parse_signed_money(spent_input.value or '0')
            except ValueError:
                error.value = 'Enter valid amounts; spending may be negative.'
                self.page.update()
                return
            if is_modify:
                category.name = name
                category.budgeted = budgeted
                category.spent = spent
            else:
                self.categories.insert(0, BudgetCategory(name, budgeted, spent, kind))
            self.page.pop_dialog()
            self.on_changed()

        actions: list[ft.Control] = []
        if is_modify:

            def delete(e):
                self.page.pop_dialog()

                def confirmed():
                    self.categories.remove(category)
                    self.on_changed()

                ConfirmDialog(
                    self.page,
                    'Delete budget category?',
                    f'Delete "{category.name}"? This cannot be undone.',
                    confirmed,
                ).open()

            actions.append(
                ft.FilledButton(
                    'Delete',
                    key='budget-category-delete-button',
                    bgcolor=colors.RED,
                    on_click=delete,
                )
            )
            actions.append(
                ft.TextButton(
                    'Cancel',
                    key='budget-category-cancel-button',
                    on_click=lambda e: self.page.pop_dialog(),
                )
            )
        else:
            actions.append(
                ft.TextButton(
                    'Cancel',
                    key='budget-category-cancel-button',
                    on_click=lambda e: self.page.pop_dialog(),
                )
            )
        actions.append(
            ft.FilledButton('Save', key='budget-category-save-button', on_click=save)
        )
        self.page.show_dialog(
            ft.AlertDialog(
                title=(
                    'Edit income'
                    if category is not None and category.kind == 'income'
                    else 'Edit expense'
                )
                if is_modify
                else ('Add income' if kind == 'income' else 'Add expense'),
                content=dialog_form(
                    [name_input, budget_input, spent_input, error], height=240
                ),
                actions=actions,
                modal=True,
            )
        )


class BudgetSummary:
    """Clean right-side monthly summary."""

    def __init__(self):
        self.period_text = ft.Text(size=12, color=colors.TEXT_SECONDARY)
        self.left_to_budget = ft.Text(size=24, weight=ft.FontWeight.BOLD)
        self.income = ft.Text(size=13, color=colors.GREEN)
        self.planned = ft.Text(size=13, color=colors.TEXT_SECONDARY)
        self.spent = ft.Text(size=13, color=colors.TEXT_SECONDARY)
        self.net = ft.Text(size=13, color=colors.TEXT_SECONDARY)
        self.ring = ft.ProgressRing(
            width=150,
            height=150,
            stroke_width=14,
            color=colors.BLUE,
            bgcolor=colors.BORDER,
        )
        self.ring_text = ft.Text(
            '0%', size=24, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER
        )
        self.control = ft.Container(
            width=300,
            content=ft.Column(
                [
                    ft.Text('MONTHLY BUDGET', size=11, weight=ft.FontWeight.BOLD),
                    self.period_text,
                    ft.Stack(
                        [
                            self.ring,
                            ft.Container(
                                content=self.ring_text,
                                alignment=ft.Alignment.CENTER,
                                width=150,
                                height=150,
                            ),
                        ]
                    ),
                    self.left_to_budget,
                    ft.Divider(color=colors.BORDER),
                    self.income,
                    self.planned,
                    self.spent,
                    self.net,
                ],
                spacing=12,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            border=ft.Border.all(1, colors.BORDER),
            border_radius=18,
            padding=22,
        )

    def refresh(self, categories: list[BudgetCategory], period: str | None = None):
        expenses = [c for c in categories if c.kind == 'expense']
        income = [c for c in categories if c.kind == 'income']
        planned = sum((c.budgeted for c in expenses), Decimal('0'))
        planned_income = sum((c.budgeted for c in income), Decimal('0'))
        spent = sum((c.spent for c in expenses), Decimal('0'))
        received = sum((c.spent for c in income), Decimal('0'))
        left = planned_income - planned
        self.period_text.value = format_period(period) if period else ''
        self.left_to_budget.value = (
            f'{money_format(left)} left to budget'
            if left >= 0
            else f'{money_format(abs(left))} over budget'
        )
        self.left_to_budget.color = colors.GREEN if left >= 0 else colors.RED
        self.income.value = f'{money_format(received)} income this month'
        self.planned.value = f'{money_format(planned)} planned for expenses'
        self.spent.value = f'{money_format(spent)} spent this month'
        self.net.value = f'{money_format(received - spent)} net cash flow'
        progress = min(spent / received, Decimal('1')) if received > 0 else Decimal('0')
        self.ring.value = float(progress)
        self.ring_text.value = f'{int(progress * 100)}%'


class BudgetRow:
    """One clean budget line with planned and remaining amounts."""

    def __init__(
        self,
        category: BudgetCategory,
        dialog: BudgetCategoryDialog,
        adjustment_dialog: AmountAdjustmentDialog,
        on_changed: Callable[[], None],
        fund: Fund | None = None,
    ):
        self.category = category
        self.dialog = dialog
        self.adjustment_dialog = adjustment_dialog
        self.on_changed = on_changed
        self.fund = fund
        self.name = ft.Text(size=15, weight=ft.FontWeight.W_500, expand=True)
        self.planned = ft.Text(size=14, width=110, text_align=ft.TextAlign.RIGHT)
        self.remaining = ft.Text(
            size=14,
            width=110,
            text_align=ft.TextAlign.RIGHT,
            weight=ft.FontWeight.W_600,
        )
        self.control = ft.Container(
            content=ft.Row(
                [
                    self.name,
                    self.planned,
                    self.remaining,
                    ft.IconButton(
                        icon=ft.Icons.ADD,
                        icon_size=16,
                        width=28,
                        height=28,
                        padding=0,
                        tooltip='Add to actual',
                        key=f'budget-add-{category.category_id}',
                        on_click=lambda e: self._adjust(1),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.REMOVE,
                        icon_size=16,
                        width=28,
                        height=28,
                        padding=0,
                        tooltip='Remove from actual',
                        key=f'budget-remove-{category.category_id}',
                        on_click=lambda e: self._adjust(-1),
                    ),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=BUDGET_ROW_HEIGHT,
            padding=ft.Padding.symmetric(horizontal=8),
            border=ft.Border.only(bottom=ft.BorderSide(1, colors.BORDER)),
            key=f'budget-category-{category.category_id}',
            ink=True,
            on_click=self._edit,
        )
        self.refresh()

    def _edit(self, e):
        self.dialog.modify(self.category)

    def _adjust(self, direction):
        def save(new_balance):
            self.category.spent = new_balance
            self.on_changed()

        self.adjustment_dialog.open(
            self.category.name, self.category.spent, direction, save
        )

    def refresh(self):
        self.name.value = self.category.name
        self.planned.value = money_format(self.category.budgeted)
        if self.fund is not None and self.fund.target > 0:
            goal_remaining = max(self.fund.target - self.fund.balance, Decimal('0'))
            self.remaining.value = f'{money_format(goal_remaining)} to goal'
            self.remaining.color = (
                colors.GREEN if goal_remaining == 0 else colors.TEXT_SECONDARY
            )
        elif self.category.kind == 'income':
            remaining = self.category.budgeted - self.category.spent
            if remaining < 0:
                self.remaining.value = f'{money_format(abs(remaining))} above plan'
                self.remaining.color = colors.GREEN
            else:
                self.remaining.value = money_format(remaining)
                self.remaining.color = colors.GREEN
        else:
            self.remaining.value = money_format(self.category.remaining)
            self.remaining.color = (
                colors.GREEN if self.category.remaining >= 0 else colors.RED
            )


class BudgetDashboard:
    """EveryDollar-style monthly budget with a concise summary panel."""

    def __init__(
        self,
        page: ft.Page,
        categories: list[BudgetCategory],
        on_categories_changed: Callable[[], None],
        period: str | None = None,
        on_reset_month: Callable[[], None] | None = None,
        funds: list[Fund] | None = None,
        on_period_changed: Callable[[str], None] | None = None,
        on_copy_plan: Callable[[], None] | None = None,
    ):
        self.page = page
        self.categories = categories
        self.funds = funds or []
        self.on_categories_changed = on_categories_changed
        self.period = period or current_period()
        self.on_reset_month = on_reset_month
        self.on_period_changed = on_period_changed
        self.on_copy_plan = on_copy_plan
        self.dialog = BudgetCategoryDialog(page, categories, self._categories_changed)
        self.adjustment_dialog = AmountAdjustmentDialog(page)
        self.summary = BudgetSummary()
        self.income_list = ft.ReorderableListView(
            spacing=0,
            on_reorder=lambda e: self._reorder('income', e),
            key='budget-income-list',
            scroll=ft.ScrollMode.HIDDEN,
        )
        self.expense_list = ft.ReorderableListView(
            spacing=0,
            on_reorder=lambda e: self._reorder('expense', e),
            key='budget-expense-list',
            scroll=ft.ScrollMode.HIDDEN,
        )
        self.income_section = self._section(
            'Income',
            self.income_list,
            'Add income',
            'add-budget-income-button',
            'income',
        )
        self.expense_section = self._section(
            'Expenses',
            self.expense_list,
            'Add expense',
            'add-budget-expense-button',
            'expense',
        )
        self.left_to_budget = ft.Text(size=16, weight=ft.FontWeight.W_600)
        self.left_column = ft.Column(
            [self.income_section, self.expense_section],
            spacing=18,
            width=680,
        )
        self.content = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.IconButton(
                                icon=ft.Icons.CHEVRON_LEFT,
                                tooltip='Previous month',
                                key='budget-prev-month',
                                on_click=lambda e: self._shift_month(-1),
                            ),
                            ft.Text(
                                format_period(self.period),
                                size=28,
                                weight=ft.FontWeight.BOLD,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CHEVRON_RIGHT,
                                tooltip='Next month',
                                key='budget-next-month',
                                on_click=lambda e: self._shift_month(1),
                            ),
                            ft.TextButton(
                                'Copy plan',
                                icon=ft.Icons.CONTENT_COPY_OUTLINED,
                                key='copy-budget-plan-button',
                                on_click=lambda e: (
                                    self.on_copy_plan() if self.on_copy_plan else None
                                ),
                            ),
                            ft.TextButton(
                                'Reset month',
                                icon=ft.Icons.RESTART_ALT,
                                key='reset-budget-month-button',
                                on_click=self._confirm_reset,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(
                        content=self.left_to_budget,
                        padding=12,
                        border_radius=12,
                        bgcolor=colors.SURFACE,
                        alignment=ft.Alignment.CENTER,
                    ),
                    ft.Row(
                        [
                            self.left_column,
                            self.summary.control,
                        ],
                        spacing=22,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ],
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
        self.rows: list[BudgetRow] = []
        self.cards = self.rows
        self.refresh()
        self.resize()

    def _section(self, title, list_view, add_label, add_key, kind):
        header = ft.Row(
            [
                ft.Text(title, size=18, weight=ft.FontWeight.BOLD, expand=True),
                ft.Text(
                    'Planned',
                    size=12,
                    width=110,
                    text_align=ft.TextAlign.RIGHT,
                    color=colors.TEXT_SECONDARY,
                ),
                ft.Text(
                    'Remaining',
                    size=12,
                    width=110,
                    text_align=ft.TextAlign.RIGHT,
                    color=colors.TEXT_SECONDARY,
                ),
                ft.Container(width=62),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return ft.Container(
            content=ft.Column(
                [
                    header,
                    list_view,
                    ft.TextButton(
                        add_label,
                        icon=ft.Icons.ADD,
                        key=add_key,
                        on_click=lambda e: self._add_category(kind),
                    ),
                ],
                spacing=4,
            ),
            padding=12,
            border=ft.Border.all(1, colors.BORDER),
            border_radius=16,
        )

    def _shift_month(self, months: int):
        period = shift_period(self.period, months)
        if self.on_period_changed is not None:
            self.on_period_changed(period)
            return
        self.period = period
        self.refresh()
        self.page.update()

    def _add_category(self, kind):
        self.dialog.add(kind)

    def _categories_changed(self):
        self.on_categories_changed()

    def _reorder(self, kind, event):
        reorder_budget_categories(
            self.categories, kind, event.old_index, event.new_index
        )
        self._categories_changed()

    def _confirm_reset(self, e):
        reset_month = self.on_reset_month
        if reset_month is None:
            return
        ConfirmDialog(
            self.page,
            'Reset budget month?',
            'The current budget will be archived and every spent amount will be reset to zero.',
            lambda: reset_month(),
            confirm_label='Reset',
        ).open()

    def refresh(self):
        self.summary.refresh(self.categories, self.period)
        funds_by_id = {fund.id: fund for fund in self.funds}
        self.rows = [
            BudgetRow(
                c,
                self.dialog,
                self.adjustment_dialog,
                self._categories_changed,
                funds_by_id.get(c.source_fund_id),
            )
            for c in self.categories
        ]
        self.cards = self.rows
        income = [row.control for row in self.rows if row.category.kind == 'income']
        expenses = [row.control for row in self.rows if row.category.kind == 'expense']
        self.income_list.controls = income
        self.expense_list.controls = expenses
        self.income_list.height = max(1, len(income) * BUDGET_ROW_HEIGHT)
        self.expense_list.height = max(1, len(expenses) * BUDGET_ROW_HEIGHT)
        self.left_to_budget.value = self.summary.left_to_budget.value
        self.left_to_budget.color = self.summary.left_to_budget.color

    def resize(self):
        width = self.page.width or 0
        margin = 12 if width < 600 else 24
        self.content.width = min(1080, max(width - 2 * margin, 0))
        self.content.padding = margin
        if self.content.width < 720:
            self.left_column.width = self.content.width
            self.summary.control.visible = False
        else:
            self.left_column.width = self.content.width - 340
            self.summary.control.visible = True
