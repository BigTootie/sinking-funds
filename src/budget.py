"""Budget category model and simple monthly budget calculations."""

from dataclasses import dataclass


@dataclass
class BudgetCategory:
    name: str
    budgeted: float
    spent: float = 0.0

    @property
    def remaining(self) -> float:
        return self.budgeted - self.spent

    @property
    def percent_spent(self) -> float:
        if self.budgeted <= 0:
            return 0.0
        return self.spent / self.budgeted
