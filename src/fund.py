"""
Module containing the Fund class implementation
"""
from datetime import datetime
from dateutil import relativedelta


class Fund:
    def __init__(self, name: str, target: float, initial_balance: float = 0.0,
                 target_date: datetime = None, recurring_transfer: float = 0.0):
        self.name = name
        self.target = target
        self.balance = initial_balance
        self.target_date = target_date
        self.time_remaining = self._compute_time_remaining()
        self.recurring_transfer = recurring_transfer
        self.on_track = self._on_track_for_target()

    def add(self, amount):
        new_balance = self.balance + amount
        self.set_balance(new_balance)

    def remove(self, amount):
        new_balance = self.balance - amount
        self.set_balance(new_balance)

    def set_target(self, value):
        self.target = value
        self.on_track = self._on_track_for_target()

    def set_balance(self, value):
        self.balance = value
        self.on_track = self._on_track_for_target()

    def compute_percent_funded(self):
        return round(self.balance / self.target * 100, 2)

    def set_target_date(self, date):
        self.target_date = date
        self.time_remaining = self._compute_time_remaining()
        self.on_track = self._on_track_for_target()

    def _compute_time_remaining(self):
        if self.target_date is None:
            return None

        today = datetime.today()
        return relativedelta.relativedelta(self.target_date.replace(tzinfo=None),
                                           today.replace(tzinfo=None))

    def target_date_as_str(self):
        if self.target_date is None:
            return 'None'
        else:
            return self.target_date.strftime('%m/%d/%Y')

    def time_remaining_as_str(self):
        if self.time_remaining is None:
            return 'N/A'

        time_remaining_dict = {}
        time_remaining_dict['years'] = self.time_remaining.years
        time_remaining_dict['months'] = self.time_remaining.months
        time_remaining_dict['days'] = self.time_remaining.days
        time_remaining_str = ', '.join([f'{unit_value} {unit_lable}' \
            for unit_lable, unit_value in time_remaining_dict.items() if unit_value != 0])
        return time_remaining_str + ' remaining'

    def set_recurring_transfer(self, recurring_transfer):
        self.recurring_transfer = recurring_transfer
        self.on_track = self._on_track_for_target()

    def _on_track_for_target(self):
        if self.time_remaining is None:
            return None

        # Calculate our remaining balance
        remaining_balance = self.target - self.balance

        # Calculate how many months are remaining to contribute to this fund
        months_remaining = (self.time_remaining.years * 12) + self.time_remaining.months

        # If we don't have any months left, check to see if we currently have enough money
        if months_remaining == 0:
            if remaining_balance > 0:
                return False
            else:
                return True
        # Otherwise, check to see if our recurring transfer is high enough to meet the target
        else:
            return self.recurring_transfer >= remaining_balance / months_remaining

    def get_on_track_status_as_str(self):
        match self.on_track:
            case None:
                return 'N/A'
            case True:
                return 'On track to meet target'
            case False:
                return 'Behind schedule'
