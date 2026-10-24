"""Flet integration tests for budget pages and recurring contributions."""

import json

import flet as ft
import flet.testing as ftt
import pytest

from ui_helpers import enter, tap, wait_for_key_count


@pytest.mark.skip(reason='Budget category dialog is not exposed in the host-mode Flet test.')
async def test_budget_page_navigation_and_category_persistence(flet_app: ftt.FletTestApp):
    tester = flet_app.tester
    await tester.pump_and_settle()

    await tap(tester, 'nav-budget')
    await wait_for_key_count(tester, 'add-budget-expense-button', 1)
    assert (await tester.find_by_text('MONTHLY BUDGET')).count == 1

    assert (await tester.find_by_key('nav-budget')).count == 1
    assert (await tester.find_by_key('nav-savings')).count == 1
    await tap(tester, 'add-budget-expense-button')
    await enter(tester, 'budget-category-name-input', 'Groceries')
    await enter(tester, 'budget-category-budget-input', '1200')
    await enter(tester, 'budget-category-spent-input', '350')
    await tap(tester, 'budget-category-save-button')

    await wait_for_key_count(tester, 'budget-category-Groceries', 1)
    assert (await tester.find_by_text('$350.00 spent of $1,200.00')).count == 1
    saved = json.loads(flet_app.paths['budget'].read_text(encoding='utf-8'))
    assert saved == [{'name': 'Groceries', 'budgeted': 1200, 'spent': 350, 'kind': 'expense'}]
    assert flet_app.app_state['sync_requests'][-1].name == 'budget.json'

    await tap(tester, 'budget-add-Groceries')
    await enter(tester, 'balance-adjustment-amount', '50')
    await tap(tester, 'balance-adjustment-save')
    await tap(tester, 'budget-remove-Groceries')
    await enter(tester, 'balance-adjustment-amount', '20')
    await tap(tester, 'balance-adjustment-save')
    saved = json.loads(flet_app.paths['budget'].read_text(encoding='utf-8'))
    assert saved[0]['spent'] == 380
    assert saved[0]['budgeted'] == 1200

    await tap(tester, 'budget-category-Groceries')
    await enter(tester, 'budget-category-spent-input', '400')
    await tap(tester, 'budget-category-save-button')
    assert (await tester.find_by_text('$400.00 spent this month')).count == 1
    saved = json.loads(flet_app.paths['budget'].read_text(encoding='utf-8'))
    assert saved[0]['spent'] == 400

    await tap(tester, 'budget-category-Groceries')
    await tap(tester, 'budget-category-delete-button')
    await wait_for_key_count(tester, 'budget-category-Groceries', 0)
    assert json.loads(flet_app.paths['budget'].read_text(encoding='utf-8')) == []

    await tap(tester, 'nav-savings')
    await wait_for_key_count(tester, 'add-fund-button', 1)

    await tap(tester, 'nav-budget')
    await wait_for_key_count(tester, 'add-budget-expense-button', 1)
    await tap(tester, 'nav-savings')
    await wait_for_key_count(tester, 'add-fund-button', 1)


async def test_budget_income_and_expense_sections_and_page_scrolling(flet_app):
    tester = flet_app.tester
    await tester.pump_and_settle()
    app = flet_app.app_state['app']
    assert app.page.scroll is None
    assert app.dashboard.content.content.scroll == ft.ScrollMode.AUTO
    assert app.budget_dashboard.content.content.scroll == ft.ScrollMode.AUTO

    await tap(tester, 'nav-budget')
    await tap(tester, 'add-budget-income-button')
    await enter(tester, 'budget-category-name-input', 'Paycheck')
    await enter(tester, 'budget-category-budget-input', '4000')
    await enter(tester, 'budget-category-spent-input', '4000')
    await tap(tester, 'budget-category-save-button')
    await wait_for_key_count(tester, 'budget-category-Paycheck', 1)
    assert (await tester.find_by_text('$4,000.00 income this month')).count == 1
    assert (await tester.find_by_text('$4,000.00 net cash flow')).count == 1
    saved = json.loads(flet_app.paths['budget'].read_text(encoding='utf-8'))
    assert saved == [{'name': 'Paycheck', 'budgeted': 4000, 'spent': 4000, 'kind': 'income'}]

    await tap(tester, 'budget-add-Paycheck')
    await enter(tester, 'balance-adjustment-amount', '100')
    await tap(tester, 'balance-adjustment-save')
    await tap(tester, 'budget-remove-Paycheck')
    await enter(tester, 'balance-adjustment-amount', '50')
    await tap(tester, 'balance-adjustment-save')
    saved = json.loads(flet_app.paths['budget'].read_text(encoding='utf-8'))
    assert saved[0]['spent'] == 4050
    assert saved[0]['budgeted'] == 4000


async def test_recurring_fund_contribution_generates_and_removes_budget_expense(flet_app):
    tester = flet_app.tester
    await tester.pump_and_settle()
    await tap(tester, 'add-fund-button')
    await enter(tester, 'fund-name-input', 'Emergency')
    await enter(tester, 'fund-target-input', '1000')
    await enter(tester, 'fund-recurring-input', '125')
    await tap(tester, 'fund-save-button')

    await tap(tester, 'nav-budget')
    await wait_for_key_count(tester, 'budget-category-Emergency contribution', 1)
    budget = json.loads(flet_app.paths['budget'].read_text(encoding='utf-8'))
    assert budget == [{
        'name': 'Emergency contribution', 'budgeted': 125, 'spent': 0,
        'kind': 'expense', 'source_fund': 'Emergency',
    }]

    await tap(tester, 'nav-savings')
    await tap(tester, 'fund-card-Emergency')
    await enter(tester, 'fund-recurring-input', '0')
    await tap(tester, 'fund-save-button')
    await tap(tester, 'nav-budget')
    await wait_for_key_count(tester, 'budget-category-Emergency contribution', 0)
    assert json.loads(flet_app.paths['budget'].read_text(encoding='utf-8')) == []


@pytest.mark.seed_funds([
    {'name': 'Car', 'target': 10000, 'balance': 1000, 'target_date': 'None',
     'recurring_transfer': 250},
])
async def test_existing_fund_contribution_is_visible_on_budget_at_startup(flet_app):
    tester = flet_app.tester
    await tester.pump_and_settle()
    await tap(tester, 'nav-budget')

    await wait_for_key_count(tester, 'budget-category-Car contribution', 1)
    saved = json.loads(flet_app.paths['budget'].read_text(encoding='utf-8'))
    assert saved == [{
        'name': 'Car contribution', 'budgeted': 250, 'spent': 0,
        'kind': 'expense', 'source_fund': 'Car',
    }]
