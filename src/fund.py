'''
Module containing the Fund class implementation
'''

class Fund:
    def __init__(self, name, target, initial_balance=0.0):
        self.name = name
        self.target = target
        self.balance = initial_balance
        self._compute_percent_funded()

    def add(self, amount):
        self.balance += amount
        self._compute_percent_funded()

    def remove(self, amount):
        self.balance -= amount
        self._compute_percent_funded()

    def set_target(self, value):
        self.target = value
        self._compute_percent_funded()

    def set_balance(self, value):
        self.balance = value
        self._compute_percent_funded()

    def _compute_percent_funded(self):
        self.percent_funded = round(self.balance / self.target * 100, 2)
