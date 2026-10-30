"""Savings fund model and target progress calculations."""

import calendar
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from dateutil import relativedelta

from utils import money_format, parse_money, parse_signed_money

LAST_DAY_OF_MONTH = 31
FUND_KINDS = {'savings_goal', 'sinking_fund'}
FUND_STATUSES = {'active', 'archived'}


def normalize_due_day(value) -> int:
    """Return a monthly due day in 1..31, defaulting to the last day (31)."""
    if value is None or value == '' or value == 'None':
        return LAST_DAY_OF_MONTH
    if isinstance(value, bool):
        raise ValueError('due day must be between 1 and 31')
    try:
        day = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError('due day must be between 1 and 31') from None
    if not 1 <= day <= LAST_DAY_OF_MONTH:
        raise ValueError('due day must be between 1 and 31')
    return day


def due_date_for_period(period: str, due_day: int = LAST_DAY_OF_MONTH) -> date:
    """Return the clamped due date for a calendar month (``YYYY-MM``)."""
    try:
        year, month = (int(part) for part in period.split('-', 1))
        if not 1 <= month <= 12:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('period must be YYYY-MM') from None
    day = min(normalize_due_day(due_day), calendar.monthrange(year, month)[1])
    return date(year, month, day)


def last_day_of_period(period: str) -> date:
    return due_date_for_period(period, LAST_DAY_OF_MONTH)


class Fund:
    """A savings goal/envelope and the balance currently assigned to it."""

    def __init__(
        self,
        name: str,
        target,
        initial_balance=0,
        target_date: datetime | None = None,
        recurring_transfer=0,
        fund_id: str | None = None,
        due_day=LAST_DAY_OF_MONTH,
        kind: str = 'savings_goal',
        priority: int = 0,
        status: str = 'active',
        source_account_id: str | None = None,
        destination_account_id: str | None = None,
        notes: str = '',
    ):
        self.id = fund_id or uuid4().hex
        self.name = name.strip()
        if not self.name:
            raise ValueError('Fund name cannot be empty')
        self.target = parse_money(target)
        self.balance = parse_signed_money(initial_balance)
        self.target_date = target_date
        self.recurring_transfer = parse_money(recurring_transfer)
        self.due_day = normalize_due_day(due_day)
        self.kind = kind if kind in FUND_KINDS else 'savings_goal'
        self.priority = max(0, int(priority or 0))
        self.status = status if status in FUND_STATUSES else 'active'
        self.source_account_id = source_account_id or None
        self.destination_account_id = destination_account_id or None
        self.notes = notes or ''

    @property
    def is_overdrawn(self) -> bool:
        """Whether spending has pulled this fund below zero."""
        return self.balance < 0

    @property
    def monthly_contribution(self) -> Decimal:
        """Alias for the recurring monthly set-aside."""
        return self.recurring_transfer

    @monthly_contribution.setter
    def monthly_contribution(self, value) -> None:
        self.recurring_transfer = parse_money(value)

    @property
    def is_active(self) -> bool:
        return self.status == 'active'

    def due_date(self, period: str) -> date:
        """Return the clamped due date for a calendar month."""
        return due_date_for_period(period, self.due_day)

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

    def set_due_day(self, due_day) -> None:
        self.due_day = normalize_due_day(due_day)

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
