"""Flet integration tests for savings funds."""

import json

import flet as ft
import flet.testing as ftt
import pytest

from ui_helpers import enter, tap, wait_for_key_count


@pytest.mark.first_run
async def test_first_run_skips_nextcloud_and_sets_account_balance(flet_app: ftt.FletTestApp):
    tester = flet_app.tester
    await tester.pump_and_settle()

    await tap(tester, 'nextcloud-skip-button')
    await wait_for_key_count(tester, 'account-balance-input', 1)

    await tap(tester, 'account-balance-save')
    assert (await tester.find_by_text('Enter a valid account balance amount.')).count == 1

    await enter(tester, 'account-balance-input', '1234.50')
    await tap(tester, 'account-balance-save')
    assert (await tester.find_by_text('$1,234.50')).count == 1
    assert flet_app.paths['balance'].read_text(encoding='utf-8') == '1234.5'
    assert json.loads(flet_app.paths['nextcloud'].read_text(encoding='utf-8')) == {}


async def test_fund_add_modify_delete_validation_and_persistence(flet_app: ftt.FletTestApp):
    tester = flet_app.tester
    await tester.pump_and_settle()
    await tap(tester, 'add-fund-button')

    await tap(tester, 'fund-save-button')
    assert (await tester.find_by_text('Enter a fund name.')).count == 1

    await enter(tester, 'fund-name-input', 'Emergency')
    await enter(tester, 'fund-target-input', 'not-a-number')
    await tap(tester, 'fund-save-button')
    assert (await tester.find_by_text('Enter a valid target amount.')).count == 1

    await enter(tester, 'fund-target-input', '1000')
    await enter(tester, 'fund-balance-input', '100')
    await enter(tester, 'fund-recurring-input', '20')
    await tap(tester, 'fund-save-button')

    card_key = 'fund-card-Emergency'
    await wait_for_key_count(tester, card_key, 1)
    saved = json.loads(flet_app.paths['funds'].read_text(encoding='utf-8'))
    assert saved[0]['name'] == 'Emergency'
    assert saved[0]['balance'] == 100

    await tap(tester, card_key)
    await enter(tester, 'fund-balance-input', '350')
    await tap(tester, 'fund-save-button')
    assert (await tester.find_by_text('$350.00 allocated of $5,000.00')).count == 1
    saved = json.loads(flet_app.paths['funds'].read_text(encoding='utf-8'))
    assert saved[0]['balance'] == 350

    await tap(tester, 'fund-add-Emergency')
    await enter(tester, 'balance-adjustment-amount', '50')
    await tap(tester, 'balance-adjustment-save')
    saved = json.loads(flet_app.paths['funds'].read_text(encoding='utf-8'))
    assert saved[0]['balance'] == 400
    assert saved[0]['target'] == 1000

    await tap(tester, 'fund-remove-Emergency')
    await enter(tester, 'balance-adjustment-amount', '25')
    await tap(tester, 'balance-adjustment-save')
    saved = json.loads(flet_app.paths['funds'].read_text(encoding='utf-8'))
    assert saved[0]['balance'] == 375
    assert saved[0]['target'] == 1000

    await tap(tester, card_key)
    await tap(tester, 'fund-delete-button')
    await wait_for_key_count(tester, card_key, 0)
    assert json.loads(flet_app.paths['funds'].read_text(encoding='utf-8')) == []


async def test_account_balance_can_be_modified(flet_app: ftt.FletTestApp):
    tester = flet_app.tester
    await tester.pump_and_settle()

    await tap(tester, 'savings-summary')
    await enter(tester, 'account-balance-input', '7500')
    await tap(tester, 'account-balance-save')

    assert (await tester.find_by_text('$7,500.00')).count == 1
    assert flet_app.paths['balance'].read_text(encoding='utf-8') == '7500.0'


@pytest.mark.seed_funds([
    {'name': 'First', 'target': 100, 'balance': 10, 'target_date': 'None', 'recurring_transfer': 0},
    {'name': 'Second', 'target': 200, 'balance': 20, 'target_date': '01/01/2027',
     'recurring_transfer': 10},
])
async def test_funds_can_be_reordered_and_target_dates_are_shown(flet_app: ftt.FletTestApp):
    tester = flet_app.tester
    await tester.pump_and_settle()

    assert (await tester.find_by_text_containing('Target date: 01/01/2027')).count == 1
    await tester.drag(await tester.find_by_key('fund-card-First'), ft.Offset(0, 180))
    await tester.pump_and_settle()

    saved = json.loads(flet_app.paths['funds'].read_text(encoding='utf-8'))
    assert [fund['name'] for fund in saved] == ['Second', 'First']
