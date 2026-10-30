from decimal import Decimal
from types import SimpleNamespace

import flet as ft

import colors
from budget import (
    BudgetCategory,
    reorder_budget_categories,
    sync_recurring_fund_expenses,
)
from fund import Fund
from ui.budget import BudgetCategoryDialog, BudgetDashboard
from ui.savings import Dashboard


def test_budget_category_calculates_remaining_and_progress():
    category = BudgetCategory('Groceries', 1200, 350)

    assert category.remaining == 850
    assert category.percent_spent == Decimal(350) / Decimal(1200)

    category.spent = Decimal('1300')
    assert category.remaining == -100
    assert category.percent_spent > 1


def test_zero_budget_category_has_safe_progress_value():
    category = BudgetCategory('Unplanned', 0, 25)

    assert category.remaining == -25
    assert category.percent_spent == 0


def test_budget_categories_reorder_within_their_section():
    first = BudgetCategory('First expense', 10)
    income = BudgetCategory('Income', 100, 100, 'income')
    second = BudgetCategory('Second expense', 20)
    categories = [first, income, second]

    reorder_budget_categories(categories, 'expense', 0, 1)

    assert categories == [second, income, first]


def test_recurring_fund_expenses_are_created_updated_and_removed():
    fund = Fund('Emergency', 1000, recurring_transfer=125)
    manual = BudgetCategory('Rent', 900, 900)
    categories = [manual]

    assert sync_recurring_fund_expenses(categories, [fund]) is True
    generated = categories[1]
    assert (
        generated.name,
        generated.budgeted,
        generated.kind,
        generated.source_fund_id,
    ) == ('Emergency contribution', 125, 'expense', fund.id)
    assert sync_recurring_fund_expenses(categories, [fund]) is False

    fund.set_recurring_transfer(200)
    assert sync_recurring_fund_expenses(categories, [fund]) is True
    assert generated.budgeted == 200

    fund.set_recurring_transfer(0)
    assert sync_recurring_fund_expenses(categories, [fund]) is True
    assert categories == [manual]


def test_recurring_fund_expense_is_removed_when_fund_is_deleted():
    fund = Fund('Emergency', 1000, recurring_transfer=125)
    categories = []
    sync_recurring_fund_expenses(categories, [fund])

    assert sync_recurring_fund_expenses(categories, []) is True
    assert categories == []


def test_zeroed_contribution_preserves_already_spent_money():
    fund = Fund('Emergency', 1000, recurring_transfer=125)
    categories = []
    sync_recurring_fund_expenses(categories, [fund])
    generated = categories[0]
    generated.spent = Decimal('75.00')

    fund.set_recurring_transfer(0)
    assert sync_recurring_fund_expenses(categories, [fund]) is True

    assert categories == [generated]
    assert generated.budgeted == 0
    assert generated.spent == Decimal('75.00')


def test_deleting_fund_preserves_already_spent_money():
    fund = Fund('Emergency', 1000, recurring_transfer=125)
    categories = []
    sync_recurring_fund_expenses(categories, [fund])
    generated = categories[0]
    generated.spent = Decimal('75.00')

    assert sync_recurring_fund_expenses(categories, []) is True

    assert categories == [generated]
    assert generated.budgeted == 0
    assert generated.spent == Decimal('75.00')


def test_duplicate_generated_rows_merge_spending_before_removal():
    fund = Fund('Emergency', 1000, recurring_transfer=125)
    first = BudgetCategory('Emergency contribution', 125, 10, 'expense', fund.id)
    duplicate = BudgetCategory('Emergency contribution', 125, 5, 'expense', fund.id)
    categories = [first, duplicate]

    assert sync_recurring_fund_expenses(categories, [fund]) is True

    assert categories == [first]
    assert first.spent == Decimal('15.00')


def test_generated_budget_row_cannot_be_edited_directly():
    fund = Fund('Emergency', 1000, recurring_transfer=125)
    category = BudgetCategory('Emergency contribution', 125, 0, 'expense', fund.id)
    dialogs = []
    page = SimpleNamespace(
        show_dialog=dialogs.append,
        pop_dialog=lambda: None,
        update=lambda: None,
    )

    BudgetCategoryDialog(page, [category], lambda: None).modify(category)

    assert len(dialogs) == 1
    assert dialogs[0].title == 'Generated from a fund'
    assert category.budgeted == 125


def test_budget_category_dialog_uses_finite_form():
    dialogs = []
    page = SimpleNamespace(
        show_dialog=dialogs.append,
        pop_dialog=lambda: None,
        update=lambda: None,
    )

    BudgetCategoryDialog(page, [], lambda: None).add('expense')

    form = dialogs[0].content
    assert isinstance(form, ft.ListView)
    assert form.width == 320
    assert form.height == 240


def test_renaming_fund_preserves_generated_expense_spending():
    fund = Fund('Emergency', 1000, recurring_transfer=125)
    categories = []
    sync_recurring_fund_expenses(categories, [fund])
    categories[0].spent = Decimal('75.00')

    fund.name = 'Emergency Fund'
    sync_recurring_fund_expenses(categories, [fund])

    assert categories[0].name == 'Emergency Fund contribution'
    assert categories[0].source_fund_id == fund.id
    assert categories[0].spent == Decimal('75.00')


def test_duplicate_fund_names_keep_distinct_generated_expenses():
    first = Fund('Emergency', 1000, recurring_transfer=125)
    second = Fund('Emergency', 2000, recurring_transfer=50)
    categories = []

    sync_recurring_fund_expenses(categories, [first, second])

    sources = {category.source_fund_id for category in categories}
    assert sources == {first.id, second.id}
    assert len(categories) == 2
    assert sync_recurring_fund_expenses(categories, [first, second]) is False


def test_generated_fund_expense_is_rendered_in_the_expenses_section():
    fund = Fund('Car', 10000, recurring_transfer=250)
    categories = []
    sync_recurring_fund_expenses(categories, [fund])
    dashboard = BudgetDashboard(SimpleNamespace(width=800), categories, lambda: None)

    assert [control.key for control in dashboard.expense_list.controls] == [
        f'budget-category-{categories[0].category_id}'
    ]


def test_budget_rows_keep_compact_layout_and_aligned_balance_buttons():
    category = BudgetCategory('Rent', 1000)
    dashboard = BudgetDashboard(SimpleNamespace(width=800), [category], lambda: None)
    row = dashboard.cards[0]
    row_controls = row.control.content.controls
    assert [control.key for control in row_controls[-2:]] == [
        f'budget-add-{category.category_id}',
        f'budget-remove-{category.category_id}',
    ]
    assert row.name.size == 15
    assert dashboard.expense_list.height == 58
    assert dashboard.expense_list.scroll.value == 'hidden'


def test_income_card_describes_extra_income_as_above_plan():
    category = BudgetCategory('Paycheck', 4000, 4050, 'income')
    dashboard = BudgetDashboard(SimpleNamespace(width=800), [category], lambda: None)
    card = dashboard.cards[0]

    assert card.remaining.value == '$50.00 above plan'
    assert card.remaining.color == colors.GREEN


def test_savings_page_uses_one_page_level_scroller():
    savings = Dashboard(
        SimpleNamespace(width=800),
        [Fund('Car', 10000)],
        lambda: 1000,
        lambda _balance: None,
        lambda: None,
    )
    assert savings.content.content.scroll.value == 'auto'
    assert savings.fund_list.list_view.scroll.value == 'hidden'


def test_fund_budget_row_shows_remaining_to_goal():
    fund = Fund('Car', 600, 100, recurring_transfer=50)
    categories = []
    sync_recurring_fund_expenses(categories, [fund])
    dashboard = BudgetDashboard(
        SimpleNamespace(width=800), categories, lambda: None, funds=[fund]
    )

    row = dashboard.cards[0]
    assert row.planned.value == '$50.00'
    assert row.remaining.value == '$500.00 to goal'
