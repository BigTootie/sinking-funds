from types import SimpleNamespace

from budget import (
    BudgetCategory,
    reorder_budget_categories,
    sync_recurring_fund_expenses,
)
from fund import Fund
from ui.budget import BudgetDashboard
from ui.savings import Dashboard


def test_budget_category_calculates_remaining_and_progress():
    category = BudgetCategory('Groceries', 1200, 350)

    assert category.remaining == 850
    assert category.percent_spent == 350 / 1200

    category.spent = 1300
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
    assert (generated.name, generated.budgeted, generated.kind, generated.source_fund) == (
        'Emergency contribution', 125, 'expense', 'Emergency'
    )
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


def test_generated_fund_expense_is_rendered_in_the_expenses_section():
    fund = Fund('Car', 10000, recurring_transfer=250)
    categories = []
    sync_recurring_fund_expenses(categories, [fund])
    dashboard = BudgetDashboard(SimpleNamespace(width=800), categories, lambda: None)

    assert [control.key for control in dashboard.expense_list.controls] == [
        'budget-category-Car contribution'
    ]


def test_budget_cards_keep_compact_layout_and_aligned_balance_buttons():
    dashboard = BudgetDashboard(
        SimpleNamespace(width=800), [BudgetCategory('Rent', 1000)], lambda: None
    )
    card_content = dashboard.cards[0].control.content
    assert card_content.margin.right == 22
    actions = card_content.controls[0].controls[-1]
    assert len(actions.controls) == 2
    assert actions.controls[0].key == 'budget-add-Rent'
    assert actions.controls[1].key == 'budget-remove-Rent'
    assert actions.controls[0].size_constraints.min_height == 30
    assert dashboard.cards[0].name.size == 17
    assert dashboard.expense_list.height == 130
    assert dashboard.expense_list.scroll.value == 'hidden'


def test_savings_page_uses_one_page_level_scroller():
    savings = Dashboard(
        SimpleNamespace(width=800), [Fund('Car', 10000)], lambda: 1000,
        lambda _balance: None, lambda: None,
    )
    assert savings.content.content.scroll.value == 'auto'
    assert savings.fund_list.list_view.expand is None
    assert savings.fund_list.list_view.scroll.value == 'hidden'
    assert savings.fund_list.list_view.height == 135
