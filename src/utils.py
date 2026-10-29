"""Shared formatting and money parsing helpers."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal('0.01')


def parse_money(value, *, allow_negative: bool = False) -> Decimal:
    """Parse a finite dollar amount and round it to cents.

    Negative amounts are rejected unless ``allow_negative`` is true. UI entry
    forms keep the safe default; persisted balances and spending use the signed
    form so overdrafts and refunds survive a round trip.

    Raises:
        ValueError: if the value is empty, non-numeric, non-finite, or negative
            when negatives are not allowed.
    """
    if value is None:
        raise ValueError('empty amount')
    text = str(value).strip().replace(',', '')
    if not text:
        raise ValueError('empty amount')
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValueError('invalid amount') from None
    if not amount.is_finite() or (amount < 0 and not allow_negative):
        raise ValueError('invalid amount')
    try:
        return amount.quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError('amount is too large') from None


def parse_signed_money(value) -> Decimal:
    """Parse a dollar amount that may be negative."""
    return parse_money(value, allow_negative=True)


def money_format(value) -> str:
    """Format a numeric value as US dollars with two decimal places."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return '$0.00'
    if not amount.is_finite():
        return '$0.00'
    sign = '-' if amount < 0 else ''
    return f'{sign}${abs(amount):,.2f}'
