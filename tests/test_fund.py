from datetime import datetime, timedelta

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
