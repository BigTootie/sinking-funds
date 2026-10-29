"""Headless tests for savings-fund UI controls and persistence."""

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import flet as ft
import pytest
from ui_helpers import click, enter, find_by_key, find_by_text

from fund import Fund
from ui.savings import FundDialog


def test_fund_dialog_accepts_past_dates_and_can_clear_them():
    dialogs = []
    page = SimpleNamespace(
        show_dialog=dialogs.append,
        pop_dialog=lambda: None,
        update=lambda: None,
    )
    fund = Fund('Car', 1000, target_date=datetime(2020, 1, 1))
    dialog = FundDialog(page, [fund], lambda: None)

    dialog.modify(fund)

    form = dialogs[0].content
    assert isinstance(form, ft.ListView)
    assert form.width == 320
    assert form.height == 360
    date_controls = form.controls[4]
    clear_button = date_controls.controls[1]
    assert clear_button.key == 'fund-date-clear'
    clear_button.on_click(None)
    assert date_controls.controls[0].content == 'Target date: None'


@pytest.mark.first_run
async def test_first_run_skips_nextcloud_and_sets_account_balance(headless_app):
    app = headless_app.app
    page = headless_app.page

    sync_task = asyncio.create_task(app.perform_nextcloud_sync())
    await asyncio.sleep(0)
    await click(page, 'nextcloud-skip-button')
    await sync_task

    assert json.loads(headless_app.paths['nextcloud'].read_text(encoding='utf-8')) == {}

    app.load_account_balance_and_funds()
    await click(page, 'account-balance-save')
    assert len(find_by_text(page, 'Enter a valid account balance amount.')) == 1

    await enter(page, 'account-balance-input', '1234.50')
    await click(page, 'account-balance-save')

    assert len(find_by_text(page, '$1,234.50')) == 1
    assert headless_app.paths['balance'].read_text(encoding='utf-8') == '1234.50'
    assert json.loads(headless_app.paths['nextcloud'].read_text(encoding='utf-8')) == {}


async def test_fund_add_modify_delete_validation_and_persistence(headless_app):
    app = headless_app.app
    page = headless_app.page

    await click(page, 'add-fund-button')
    await click(page, 'fund-save-button')
    assert len(find_by_text(page, 'Enter a fund name.')) == 1

    await enter(page, 'fund-name-input', 'Emergency')
    await enter(page, 'fund-target-input', 'not-a-number')
    await click(page, 'fund-save-button')
    assert len(find_by_text(page, 'Enter a valid target amount.')) == 1

    await enter(page, 'fund-target-input', '1000')
    await enter(page, 'fund-balance-input', '100')
    await enter(page, 'fund-recurring-input', '20')
    await click(page, 'fund-save-button')

    card_key = f'fund-card-{app.funds[0].id}'
    find_by_key(page, card_key)
    saved = json.loads(headless_app.paths['funds'].read_text(encoding='utf-8'))['funds']
    assert saved[0]['name'] == 'Emergency'
    assert saved[0]['balance'] == '100.00'

    await click(page, card_key)
    await enter(page, 'fund-balance-input', '350')
    await click(page, 'fund-save-button')
    assert len(find_by_text(page, '$350.00 allocated of $5,000.00')) == 1
    saved = json.loads(headless_app.paths['funds'].read_text(encoding='utf-8'))['funds']
    assert saved[0]['balance'] == '350.00'

    await click(page, f'fund-add-{app.funds[0].id}')
    await enter(page, 'balance-adjustment-amount', '50')
    await click(page, 'balance-adjustment-save')
    saved = json.loads(headless_app.paths['funds'].read_text(encoding='utf-8'))['funds']
    assert saved[0]['balance'] == '400.00'
    assert saved[0]['target'] == '1000.00'

    await click(page, f'fund-remove-{app.funds[0].id}')
    await enter(page, 'balance-adjustment-amount', '25')
    await click(page, 'balance-adjustment-save')
    saved = json.loads(headless_app.paths['funds'].read_text(encoding='utf-8'))['funds']
    assert saved[0]['balance'] == '375.00'
    assert saved[0]['target'] == '1000.00'

    await click(page, card_key)
    await click(page, 'fund-delete-button')
    await click(page, 'confirm-action-button')
    find_by_key(page, card_key, count=0)
    assert (
        json.loads(headless_app.paths['funds'].read_text(encoding='utf-8'))['funds']
        == []
    )


async def test_account_balance_can_be_modified(headless_app):
    page = headless_app.page

    await click(page, 'savings-summary')
    await enter(page, 'account-balance-input', '7500')
    await click(page, 'account-balance-save')

    assert len(find_by_text(page, '$7,500.00')) == 1
    assert headless_app.paths['balance'].read_text(encoding='utf-8') == '7500.00'


@pytest.mark.seed_funds(
    [
        {
            'name': 'First',
            'target': 100,
            'balance': 10,
            'target_date': 'None',
            'recurring_transfer': 0,
        },
        {
            'name': 'Second',
            'target': 200,
            'balance': 20,
            'target_date': '01/01/2027',
            'recurring_transfer': 10,
        },
    ]
)
async def test_funds_can_be_reordered_and_target_dates_are_shown(headless_app):
    app = headless_app.app
    page = headless_app.page

    assert len(find_by_text(page, 'Target date: 01/01/2027', containing=True)) == 1

    list_view = app.dashboard.fund_list.list_view
    list_view.on_reorder(SimpleNamespace(old_index=0, new_index=1))

    saved = json.loads(headless_app.paths['funds'].read_text(encoding='utf-8'))['funds']
    assert [fund['name'] for fund in saved] == ['Second', 'First']
