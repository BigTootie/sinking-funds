"""Savings fund model and target progress calculations."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from dateutil import relativedelta

from utils import money_format, parse_money, parse_signed_money


class Fund:
    """A savings goal and the balance currently assigned to it."""

    def __init__(
        self,
        name: str,
        target,
        initial_balance=0,
        target_date: datetime | None = None,
        recurring_transfer=0,
        fund_id: str | None = None,
    ):
        self.id = fund_id or uuid4().hex
        self.name = name.strip()
        if not self.name:
            raise ValueError('Fund name cannot be empty')
        self.target = parse_money(target)
        self.balance = parse_signed_money(initial_balance)
        self.target_date = target_date
        self.recurring_transfer = parse_money(recurring_transfer)

    @property
    def is_overdrawn(self) -> bool:
        """Whether spending has pulled this fund below zero."""
        return self.balance < 0

    @property
    def time_remaining(self) -> relativedelta.relativedelta | None:
        if self.target_date is None:
            return None
        today = datetime.today()
        return relativedelta.relativedelta(
            self.target_date.replace(tzinfo=None), today.replace(tzinfo=None)
        )

    @property
    def on_track(self) -> bool | None:
        return self._on_track_for_target()[0]

    @property
    def required_recurring_transfer(self) -> Decimal | None:
        return self._on_track_for_target()[1]

    def add(self, amount) -> None:
        self.set_balance(self.balance + parse_money(amount))

    def remove(self, amount) -> None:
        self.set_balance(self.balance - parse_money(amount))

    def set_target(self, value) -> None:
        self.target = parse_money(value)

    def set_balance(self, value) -> None:
        self.balance = parse_signed_money(value)

    def compute_percent_funded(self) -> Decimal:
        if self.target <= 0 or self.balance <= 0:
            return Decimal('0.00')
        return (self.balance / self.target * 100).quantize(Decimal('0.01'))

    def set_target_date(self, date: datetime | None) -> None:
        self.target_date = date

    def target_date_as_str(self) -> str:
        if self.target_date is None:
            return 'None'
        return self.target_date.strftime('%m/%d/%Y')

    def time_remaining_as_str(self) -> str:
        if self.target_date is None:
            return 'N/A'
        if self.target_date.date() < datetime.today().date():
            return 'Target date passed'

        remaining = self.time_remaining
        if remaining is None:
            return 'N/A'
        time_units = (
            ('years', remaining.years),
            ('months', remaining.months),
            ('days', remaining.days),
        )
        time_remaining_str = ', '.join(
            f'{value} {label}' for label, value in time_units if value != 0
        )

        if time_remaining_str:
            return time_remaining_str + ' remaining'
        return 'No time remaining'

    def set_recurring_transfer(self, recurring_transfer) -> None:
        self.recurring_transfer = parse_money(recurring_transfer)

    def _on_track_for_target(self) -> tuple[bool | None, Decimal | None]:
        if self.target_date is None:
            return None, None

        remaining_balance = self.target - self.balance
        if remaining_balance < 0:
            remaining_balance = Decimal('0.00')

        today = datetime.today()
        if self.target_date.date() <= today.date():
            return remaining_balance <= 0, remaining_balance

        remaining = self.time_remaining
        if remaining is None:
            return remaining_balance <= 0, remaining_balance
        months_remaining = (remaining.years * 12) + remaining.months
        if months_remaining <= 0:
            # Less than a full month remains, so the remaining balance is due now.
            return remaining_balance <= 0, remaining_balance

        required_recurring_transfer = (remaining_balance / months_remaining).quantize(
            Decimal('0.01')
        )
        return (
            self.recurring_transfer >= required_recurring_transfer,
            required_recurring_transfer,
        )

    def get_on_track_status_as_str(self) -> str:
        match self.on_track:
            case None:
                return 'N/A'
            case True:
                return 'On track to meet target'
            case False:
                return (
                    f'Contribute {money_format(self.required_recurring_transfer)} / month '
                    'to meet target'
                )
