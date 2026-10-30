"""Headless UI coverage for v0.4 auto-post, undo, and month navigation."""

from decimal import Decimal

import pytest
from ui_helpers import click, enter, find_by_key, find_by_text, navigate

from ui.budget import shift_period


@pytest.mark.seed_funds(
    [
        {
            'name': 'Emergency',
            'target': 1000,
            'balance': 0,
            'target_date': 'None',
            'recurring_transfer': 100,
            'due_day': 1,
        }
    ]
)
async def test_due_contribution_is_visible_in_register_and_can_be_undone(headless_app):
    app = headless_app.app
    page = headless_app.page

    contributions = app.ledger.list_fund_contributions(status='posted')
    assert len(contributions) == 1
    contribution = contributions[0]
    assert contribution.amount == Decimal('100.00')
    assert app.ledger.get_fund(app.funds[0].id).balance == Decimal('100.00')
    assert find_by_text(page, 'Fund contribution: Emergency')

    transaction = app.ledger.list_transactions(fund_id=app.funds[0].id)[0]
    navigate(page, app, 2)
    find_by_key(page, f'transaction-{transaction.id}')
    await click(page, f'transaction-{transaction.id}')
    await click(page, 'confirm-action-button')

    assert app.ledger.list_fund_contributions(status='posted') == []
    assert app.ledger.get_fund(app.funds[0].id).balance == Decimal('0.00')
    assert app.ledger.list_transactions(fund_id=app.funds[0].id) == []


async def test_budget_month_navigation_and_copy_plan(headless_app):
    app = headless_app.app
    page = headless_app.page
    navigate(page, app, 0)
    current = app.budget_state.period

    await click(page, 'add-budget-income-button')
    await enter(page, 'budget-category-name-input', 'Paycheck')
    await enter(page, 'budget-category-budget-input', '4000')
    await click(page, 'budget-category-save-button')
    await click(page, 'add-budget-expense-button')
    await enter(page, 'budget-category-name-input', 'Rent')
    await enter(page, 'budget-category-budget-input', '1200')
    await click(page, 'budget-category-save-button')

    next_period = shift_period(current, 1)
    await click(page, 'budget-next-month')
    assert app.budget_state.period == next_period
    assert app.ledger.load_budget(next_period) is not None
    assert {category.name: category.budgeted for category in app.budget_categories} == {
        'Paycheck': 4000,
        'Rent': 1200,
    }
    assert all(category.spent == 0 for category in app.budget_categories)

    await click(page, 'budget-prev-month')
    assert app.budget_state.period == current
    assert len(find_by_text(page, '$2,800.00 left to budget')) == 2

    await click(page, 'copy-budget-plan-button')
    assert app.budget_state.period == shift_period(current, 1)
    assert app.ledger.load_budget(shift_period(current, 1)) is not None


async def test_fund_due_day_is_selectable_in_the_fund_dialog(headless_app):
    app = headless_app.app
    page = headless_app.page

    await click(page, 'add-fund-button')
    find_by_key(page, 'fund-due-day-input')
    await enter(page, 'fund-name-input', 'Holiday')
    await enter(page, 'fund-target-input', '500')
    await enter(page, 'fund-recurring-input', '50')
    due = find_by_key(page, 'fund-due-day-input')
    due.value = '15'
    await click(page, 'fund-save-button')

    fund = next(fund for fund in app.funds if fund.name == 'Holiday')
    assert fund.due_day == 15
