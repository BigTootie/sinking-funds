"""Property tests for ledger money and transfer invariants."""

from decimal import Decimal
from uuid import uuid4

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ledger import Ledger, minor_to_money, money_to_minor


@given(st.decimals(min_value='-100000', max_value='100000', places=2))
@settings(max_examples=100, deadline=None, database=None)
def test_money_round_trips_at_cent_precision(amount):
    assert minor_to_money(money_to_minor(amount)) == amount.quantize(Decimal('0.01'))


@given(
    opening=st.decimals(min_value='0', max_value='10000', places=2),
    amount=st.decimals(min_value='0.01', max_value='10000', places=2),
)
@settings(
    max_examples=10,
    deadline=None,
    database=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_transfer_preserves_total_balance(tmp_path, opening, amount):
    ledger = Ledger(tmp_path / f'{uuid4().hex}.db')
    checking = ledger.add_account('Checking', opening_balance=opening)
    savings = ledger.add_account('Savings')

    ledger.add_transfer(checking.id, savings.id, '2026-10-01', amount)

    assert ledger.total_balance() == opening.quantize(Decimal('0.01'))
