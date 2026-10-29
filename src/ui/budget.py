"""Budget page dialogs, cards, and dashboard composition."""

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
from ui.shared import AmountAdjustmentDialog, ConfirmDialog, MessageDialog, dialog_form
from utils import money_format, parse_money, parse_signed_money

BUDGET_CARD_HEIGHT = 130


class BudgetCategoryDialog:
    """Add, edit, or remove a monthly budget category."""

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
            label='Monthly income ($)' if kind == 'income' else 'Monthly budget ($)',
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

        self.control = ft.AlertDialog(
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
        self.page.show_dialog(self.control)


class BudgetSummary:
    """Monthly income, expenses, and net budget summary."""

    def __init__(self):
        self.period_text = ft.Text(size=12, color=colors.TEXT_SECONDARY)
        self.total_budgeted = ft.Text(size=32, weight=ft.FontWeight.BOLD)
        self.total_spent = ft.Text(size=13, color=colors.TEXT_SECONDARY)
        self.remaining = ft.Text(size=12, color=colors.TEXT_SECONDARY)
        self.income = ft.Text(size=13, color=colors.GREEN)
        self.net = ft.Text(size=13, color=colors.TEXT_SECONDARY)
        self.progress = ft.ProgressBar(
            value=0,
            color=colors.BLUE,
            bgcolor=colors.BORDER,
            height=8,
            border_radius=10,
        )
        self.control = ft.Container(
            content=ft.Column(
                [
                    ft.Text('MONTHLY BUDGET', size=11, weight=ft.FontWeight.BOLD),
                    self.period_text,
                    self.total_budgeted,
                    self.total_spent,
                    self.income,
                    self.progress,
                    self.remaining,
                    self.net,
                ],
                spacing=12,
            ),
            border=ft.Border.all(1, colors.BORDER),
            border_radius=18,
            padding=22,
        )

    def refresh(self, categories: list[BudgetCategory], period: str | None = None):
        expenses_budgeted = sum(
            (c.budgeted for c in categories if c.kind == 'expense'), Decimal('0')
        )
        total_spent = sum(
            (c.spent for c in categories if c.kind == 'expense'), Decimal('0')
        )
        total_income = sum(
            (c.spent for c in categories if c.kind == 'income'), Decimal('0')
        )
        available = expenses_budgeted - total_spent
        self.period_text.value = format_period(period) if period else ''
        self.total_budgeted.value = money_format(expenses_budgeted)
        self.total_spent.value = f'{money_format(total_spent)} spent this month'
        self.income.value = f'{money_format(total_income)} income this month'
        self.net.value = f'{money_format(total_income - total_spent)} net cash flow'
        self.remaining.value = (
            f'{money_format(available)} remaining'
            if available >= 0
            else f'{money_format(abs(available))} over budget'
        )
        self.remaining.color = colors.TEXT_SECONDARY if available >= 0 else colors.RED
        self.progress.value = (
            float(min(total_spent / expenses_budgeted, Decimal('1')))
            if expenses_budgeted > 0
            else 0
        )


class BudgetCategoryCard:
    """Presentation and edit action for one budget category."""

    def __init__(
        self,
        category: BudgetCategory,
        dialog: BudgetCategoryDialog,
        adjustment_dialog: AmountAdjustmentDialog,
        on_balance_changed: Callable[[], None],
    ):
        self.category = category
        self.dialog = dialog
        self.adjustment_dialog = adjustment_dialog
        self.on_balance_changed = on_balance_changed
        self.name = ft.Text(size=17, weight=ft.FontWeight.W_600, expand=True)
        self.amounts = ft.Text(size=12, color=colors.TEXT_SECONDARY)
        self.remaining = ft.Text(size=13, weight=ft.FontWeight.BOLD)
        self.progress = ft.ProgressBar(
            height=6, border_radius=10, color=colors.BLUE, bgcolor=colors.BORDER
        )
        self.control = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self.name,
                            self.remaining,
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
                                        key=f'budget-add-{category.category_id}',
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
                                        key=f'budget-remove-{category.category_id}',
                                        on_click=lambda e: self._adjust(-1),
                                    ),
                                ],
                                spacing=0,
                            ),
                        ],
                        spacing=4,
                    ),
                    self.amounts,
                    self.progress,
                ],
                spacing=6,
                margin=ft.Margin.only(right=22),
            ),
            border=ft.Border.all(1, colors.BORDER),
            border_radius=16,
            padding=12,
            key=f'budget-category-{category.category_id}',
            on_click=self._edit,
        )
        self.refresh()

    def _edit(self, e):
        self.dialog.modify(self.category)

    def _adjust(self, direction):
        def save(new_balance):
            self.category.spent = new_balance
            self.on_balance_changed()

        self.adjustment_dialog.open(
            self.category.name, self.category.spent, direction, save
        )

    def refresh(self):
        self.name.value = self.category.name
        if self.category.kind == 'income':
            self.amounts.value = (
                f'{money_format(self.category.spent)} received of '
                f'{money_format(self.category.budgeted)} expected'
            )
            if self.category.spent >= self.category.budgeted:
                extra = self.category.spent - self.category.budgeted
                self.remaining.value = (
                    f'{money_format(extra)} above plan' if extra > 0 else 'On plan'
                )
                self.remaining.color = colors.GREEN
            else:
                self.remaining.value = f'{money_format(self.category.budgeted - self.category.spent)} still expected'
                self.remaining.color = colors.TEXT_SECONDARY
        else:
            self.amounts.value = (
                f'{money_format(self.category.spent)} spent of '
                f'{money_format(self.category.budgeted)}'
            )
            if self.category.remaining >= 0:
                self.remaining.value = f'{money_format(self.category.remaining)} left'
                self.remaining.color = colors.GREEN
            else:
                self.remaining.value = (
                    f'{money_format(abs(self.category.remaining))} over'
                )
                self.remaining.color = colors.RED
        self.progress.value = float(
            min(max(self.category.percent_spent, Decimal('0')), Decimal('1'))
        )


class BudgetDashboard:
    """Responsive monthly budget page with category editing and totals."""

    def __init__(
        self,
        page: ft.Page,
        categories: list[BudgetCategory],
        on_categories_changed: Callable[[], None],
        period: str | None = None,
        on_reset_month: Callable[[], None] | None = None,
    ):
        self.page = page
        self.categories = categories
        self.on_categories_changed = on_categories_changed
        self.period = period or current_period()
        self.on_reset_month = on_reset_month
        self.dialog = BudgetCategoryDialog(page, categories, self._categories_changed)
        self.adjustment_dialog = AmountAdjustmentDialog(page)
        self.summary = BudgetSummary()
        self.income_button = ft.OutlinedButton(
            'Add income',
            icon=ft.Icons.ADD_CIRCLE_OUTLINE,
            key='add-budget-income-button',
            on_click=lambda e: self._add_category('income'),
        )
        self.expense_button = ft.OutlinedButton(
            'Add expense',
            icon=ft.Icons.ADD_CIRCLE_OUTLINE,
            key='add-budget-expense-button',
            on_click=lambda e: self._add_category('expense'),
        )
        self.reset_button = ft.TextButton(
            'Reset month',
            icon=ft.Icons.RESTART_ALT,
            key='reset-budget-month-button',
            tooltip='Archive this month and reset spent amounts',
            on_click=self._confirm_reset,
        )
        self.income_list = ft.ReorderableListView(
            spacing=10,
            on_reorder=lambda e: self._reorder('income', e),
            key='budget-income-list',
            scroll=ft.ScrollMode.HIDDEN,
        )
        self.expense_list = ft.ReorderableListView(
            spacing=10,
            on_reorder=lambda e: self._reorder('expense', e),
            key='budget-expense-list',
            scroll=ft.ScrollMode.HIDDEN,
        )
        self.content = ft.Container(
            content=ft.Column(
                [
                    self.summary.control,
                    ft.Row(
                        [
                            ft.Text(
                                'Track monthly spending by category.',
                                size=13,
                                color=colors.TEXT_SECONDARY,
                                expand=True,
                            ),
                            self.reset_button,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text('Income', size=18, weight=ft.FontWeight.BOLD),
                    self.income_button,
                    self.income_list,
                    ft.Text('Expenses', size=18, weight=ft.FontWeight.BOLD),
                    self.expense_button,
                    self.expense_list,
                ],
                spacing=16,
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
        self.cards: list[BudgetCategoryCard] = []
        self.refresh()
        self.resize()

    def _add_category(self, kind='expense'):
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

        def confirmed():
            reset_month()

        ConfirmDialog(
            self.page,
            'Reset budget month?',
            'The current budget will be archived and every spent amount will be reset to zero. '
            'Budgeted amounts and categories are kept.',
            confirmed,
            confirm_label='Reset',
        ).open()

    def refresh(self):
        self.summary.refresh(self.categories, self.period)
        self.cards = [
            BudgetCategoryCard(
                category, self.dialog, self.adjustment_dialog, self._categories_changed
            )
            for category in self.categories
        ]
        income_cards = [
            card.control for card in self.cards if card.category.kind == 'income'
        ]
        expense_cards = [
            card.control for card in self.cards if card.category.kind == 'expense'
        ]
        self.income_list.controls = income_cards
        self.expense_list.controls = expense_cards
        # Give each reorderable list enough room for all rows so wheel scrolling
        # bubbles to the page's single scrollable column.
        self.income_list.height = self._list_height(income_cards)
        self.expense_list.height = self._list_height(expense_cards)

    @staticmethod
    def _list_height(cards):
        return max(1, len(cards) * BUDGET_CARD_HEIGHT + max(0, len(cards) - 1) * 10)

    def resize(self):
        screen_width = self.page.width or 0
        margin = 12 if screen_width < 600 else 24
        self.content.width = min(760, max(screen_width - 2 * margin, 0))
        self.content.padding = margin
