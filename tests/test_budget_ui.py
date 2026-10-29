"""Headless tests for budget pages and recurring contributions."""

import json

import flet as ft
import pytest
from ui_helpers import (
    budget_action_key,
    budget_key,
    click,
    enter,
    find_by_key,
    find_by_text,
    navigate,
    visible_page,
)


async def open_budget(headless_app):
    """Switch to the budget page and return its app state."""
    navigate(headless_app.page, headless_app.app, 0)
    assert visible_page(headless_app.app, 1)
    return headless_app.app


async def test_budget_category_lifecycle_and_navigation(headless_app):
    """Create, adjust, edit, and delete an expense, then navigate away and back."""
    app = await open_budget(headless_app)
    page = headless_app.page

    assert len(find_by_text(page, 'MONTHLY BUDGET')) == 1
    find_by_key(page, 'nav-budget')
    find_by_key(page, 'nav-savings')

    await click(page, 'add-budget-expense-button')
    await enter(page, 'budget-category-name-input', 'Groceries')
    await enter(page, 'budget-category-budget-input', '1200')
    await enter(page, 'budget-category-spent-input', '350')
    await click(page, 'budget-category-save-button')

    card_key = budget_key(app, 'Groceries')
    find_by_key(page, card_key)
    assert len(find_by_text(page, '$350.00 spent this month')) == 1
    assert len(find_by_text(page, '$850.00')) == 1
    saved = json.loads(headless_app.paths['budget'].read_text(encoding='utf-8'))
    assert saved['period']
    assert saved['categories'] == [
        {
            'id': app.budget_categories[0].category_id,
            'name': 'Groceries',
            'budgeted': '1200.00',
            'spent': '350.00',
            'kind': 'expense',
        }
    ]
    assert headless_app.sync_requests[-1].name == 'budget.json'

    await click(page, budget_action_key(app, 'Groceries', 'add'))
    await enter(page, 'balance-adjustment-amount', '50')
    await click(page, 'balance-adjustment-save')
    await click(page, budget_action_key(app, 'Groceries', 'remove'))
    await enter(page, 'balance-adjustment-amount', '20')
    await click(page, 'balance-adjustment-save')
    saved = json.loads(headless_app.paths['budget'].read_text(encoding='utf-8'))
    assert saved['categories'][0]['spent'] == '380.00'
    assert saved['categories'][0]['budgeted'] == '1200.00'

    await click(page, card_key)
    await enter(page, 'budget-category-spent-input', '400')
    await click(page, 'budget-category-save-button')
    assert len(find_by_text(page, '$400.00 spent this month')) == 1
    saved = json.loads(headless_app.paths['budget'].read_text(encoding='utf-8'))
    assert saved['categories'][0]['spent'] == '400.00'

    await click(page, card_key)
    await click(page, 'budget-category-delete-button')
    await click(page, 'confirm-action-button')
    find_by_key(page, card_key, count=0)
    assert (
        json.loads(headless_app.paths['budget'].read_text(encoding='utf-8'))[
            'categories'
        ]
        == []
    )

    navigate(page, app, 1)
    assert visible_page(app, 0)
    find_by_key(page, 'add-fund-button')
    navigate(page, app, 0)
    assert visible_page(app, 1)
    find_by_key(page, 'add-budget-expense-button')
    navigate(page, app, 1)
    assert visible_page(app, 0)
    find_by_key(page, 'add-fund-button')


async def test_budget_income_totals_and_page_scrolling(headless_app):
    """Income categories feed the summary and adjustments update their totals."""
    app = await open_budget(headless_app)
    page = headless_app.page

    assert app.page.scroll is None
    assert app.dashboard.content.content.scroll == ft.ScrollMode.AUTO
    assert app.budget_dashboard.content.content.scroll == ft.ScrollMode.AUTO

    await click(page, 'add-budget-income-button')
    await enter(page, 'budget-category-name-input', 'Paycheck')
    await enter(page, 'budget-category-budget-input', '4000')
    await enter(page, 'budget-category-spent-input', '4000')
    await click(page, 'budget-category-save-button')
    find_by_key(page, budget_key(app, 'Paycheck'))
    assert len(find_by_text(page, '$4,000.00 income this month')) == 1
    assert len(find_by_text(page, '$4,000.00 net cash flow')) == 1
    saved = json.loads(headless_app.paths['budget'].read_text(encoding='utf-8'))
    assert saved['categories'] == [
        {
            'id': app.budget_categories[0].category_id,
            'name': 'Paycheck',
            'budgeted': '4000.00',
            'spent': '4000.00',
            'kind': 'income',
        }
    ]

    await click(page, budget_action_key(app, 'Paycheck', 'add'))
    await enter(page, 'balance-adjustment-amount', '100')
    await click(page, 'balance-adjustment-save')
    await click(page, budget_action_key(app, 'Paycheck', 'remove'))
    await enter(page, 'balance-adjustment-amount', '50')
    await click(page, 'balance-adjustment-save')
    saved = json.loads(headless_app.paths['budget'].read_text(encoding='utf-8'))
    assert saved['categories'][0]['spent'] == '4050.00'
    assert saved['categories'][0]['budgeted'] == '4000.00'


async def test_recurring_fund_contribution_generates_and_removes_budget_expense(
    headless_app,
):
    """A fund's recurring transfer creates an expense and removes it when zeroed."""
    app = headless_app.app
    page = headless_app.page

    await click(page, 'add-fund-button')
    await enter(page, 'fund-name-input', 'Emergency')
    await enter(page, 'fund-target-input', '1000')
    await enter(page, 'fund-recurring-input', '125')
    await click(page, 'fund-save-button')

    navigate(page, app, 0)
    contribution_key = budget_key(app, 'Emergency contribution')
    find_by_key(page, contribution_key)
    budget = json.loads(headless_app.paths['budget'].read_text(encoding='utf-8'))
    assert budget['categories'] == [
        {
            'id': app.budget_categories[0].category_id,
            'name': 'Emergency contribution',
            'budgeted': '125.00',
            'spent': '0.00',
            'kind': 'expense',
            'source_fund_id': app.funds[0].id,
        }
    ]

    navigate(page, app, 1)
    await click(page, f'fund-card-{app.funds[0].id}')
    await enter(page, 'fund-recurring-input', '0')
    await click(page, 'fund-save-button')
    navigate(page, app, 0)
    find_by_key(page, contribution_key, count=0)
    assert (
        json.loads(headless_app.paths['budget'].read_text(encoding='utf-8'))[
            'categories'
        ]
        == []
    )


@pytest.mark.seed_funds(
    [
        {
            'name': 'Car',
            'target': 10000,
            'balance': 1000,
            'target_date': 'None',
            'recurring_transfer': 250,
        },
    ]
)
async def test_existing_fund_contribution_is_visible_on_budget_at_startup(headless_app):
    """A seeded recurring transfer is reconciled into the budget on startup."""
    app = await open_budget(headless_app)
    page = headless_app.page

    find_by_key(page, budget_key(app, 'Car contribution'))
    saved = json.loads(headless_app.paths['budget'].read_text(encoding='utf-8'))
    assert saved['categories'] == [
        {
            'id': app.budget_categories[0].category_id,
            'name': 'Car contribution',
            'budgeted': '250.00',
            'spent': '0.00',
            'kind': 'expense',
            'source_fund_id': app.funds[0].id,
        }
    ]


async def test_left_to_budget_uses_planned_amounts(headless_app):
    app = await open_budget(headless_app)
    page = headless_app.page

    await click(page, 'add-budget-income-button')
    await enter(page, 'budget-category-name-input', 'Paycheck')
    await enter(page, 'budget-category-budget-input', '4000')
    await click(page, 'budget-category-save-button')

    await click(page, 'add-budget-expense-button')
    await enter(page, 'budget-category-name-input', 'Rent')
    await enter(page, 'budget-category-budget-input', '1000')
    await click(page, 'budget-category-save-button')

    assert len(find_by_text(page, '$3,000.00 left to budget')) == 2

    await click(page, budget_key(app, 'Rent'))
    await enter(page, 'budget-category-budget-input', '1250')
    await click(page, 'budget-category-save-button')

    assert len(find_by_text(page, '$2,750.00 left to budget')) == 2
