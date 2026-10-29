from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from fund import Fund


def test_balance_updates_recompute_percent_and_target_status():
    fund = Fund('Car repairs', 1200, 300)

    assert fund.compute_percent_funded() == 25
    assert fund.on_track is None

    fund.set_target_date(datetime.today() + timedelta(days=180))
    fund.set_recurring_transfer(1000)
    assert fund.on_track is True

    fund.set_balance(1200)
    assert fund.compute_percent_funded() == 100
    assert fund.on_track is True


def test_fund_add_and_remove_adjust_balance():
    fund = Fund('Car repairs', 1000, 250)

    fund.add(125)
    assert fund.balance == 375

    fund.remove(75)
    assert fund.balance == 300


def test_zero_target_has_safe_funded_percentage():
    fund = Fund('Unplanned', 0, 25)

    assert fund.compute_percent_funded() == 0


def test_negative_fund_balance_is_an_overdraft_not_an_invalid_value():
    fund = Fund('Car repairs', 1000, -75)

    assert fund.balance == Decimal('-75.00')
    assert fund.is_overdrawn is True
    assert fund.compute_percent_funded() == 0

    fund.set_balance(25)
    assert fund.is_overdrawn is False


def test_target_date_can_be_cleared_and_past_dates_are_allowed():
    fund = Fund('Car repairs', 1000, target_date=datetime(2020, 1, 1))

    assert fund.time_remaining_as_str() == 'Target date passed'
    fund.set_target_date(None)
    assert fund.target_date is None
    assert fund.target_date_as_str() == 'None'


def test_past_target_date_is_overdue_not_on_track():
    fund = Fund(
        'Past due',
        target=1000,
        initial_balance=100,
        target_date=datetime.today() - timedelta(days=65),
        recurring_transfer=0,
    )

    assert fund.on_track is False
    assert fund.required_recurring_transfer == Decimal('900.00')
    assert fund.time_remaining_as_str() == 'Target date passed'


def test_fund_preserves_supplied_id_and_generates_unique_default_ids():
    first = Fund('First', 100)
    second = Fund('Second', 100)
    preserved = Fund('Preserved', 100, fund_id='fixed-id')

    assert first.id != second.id
    assert preserved.id == 'fixed-id'


@pytest.mark.parametrize('value', ['-1', 'nan', 'inf', 'not-a-number'])
def test_fund_rejects_invalid_money_values(value):
    with pytest.raises(ValueError):
        Fund('Invalid', value)
