from decimal import Decimal

import pytest

from utils import money_format, parse_money, parse_signed_money


def test_parse_money_rejects_negative_values_by_default():
    with pytest.raises(ValueError):
        parse_money('-1')


def test_signed_money_parser_preserves_overdrafts_and_rounds():
    assert parse_signed_money('-12.345') == Decimal('-12.35')
    assert parse_signed_money('1,234.5') == Decimal('1234.50')


def test_money_format_places_the_minus_sign_before_the_dollar_symbol():
    assert money_format(Decimal('1234.5')) == '$1,234.50'
    assert money_format(Decimal('-1234.5')) == '-$1,234.50'
    assert money_format('not money') == '$0.00'
