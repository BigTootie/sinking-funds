"""Budget category model and simple monthly budget calculations."""

from dataclasses import dataclass
from typing import Literal

from fund import Fund


@dataclass
class BudgetCategory:
    name: str
    budgeted: float
    spent: float = 0.0
    kind: str = 'expense'
    source_fund: str | None = None

    def __post_init__(self):
        if self.kind not in {'income', 'expense'}:
            self.kind = 'expense'

    @property
    def remaining(self) -> float:
        return self.budgeted - self.spent

    @property
    def percent_spent(self) -> float:
        if self.budgeted <= 0:
            return 0.0
        return self.spent / self.budgeted


def sync_recurring_fund_expenses(
    categories: list[BudgetCategory], funds: list[Fund]
) -> bool:
    """Keep generated expense rows aligned with funds' recurring contributions."""
    eligible_funds = {
        fund.name: fund
        for fund in funds
        if fund.recurring_transfer != 0
    }
    generated = {
        category.source_fund: category
        for category in categories
        if category.source_fund is not None
    }
    changed = False

    for source_name, category in list(generated.items()):
        fund = eligible_funds.pop(source_name, None)
        if fund is None:
            categories.remove(category)
            changed = True
            continue
        updated_name = f'{fund.name} contribution'
        if category.name != updated_name or category.budgeted != fund.recurring_transfer:
            category.name = updated_name
            category.budgeted = fund.recurring_transfer
            changed = True

    for fund in eligible_funds.values():
        categories.append(BudgetCategory(
            f'{fund.name} contribution', fund.recurring_transfer, 0, 'expense', fund.name
        ))
        changed = True

    return changed


def reorder_budget_categories(
    categories: list[BudgetCategory],
    kind: Literal['income', 'expense'],
    old_index: int,
    new_index: int,
) -> None:
    """Reorder items within their income or expense section in place."""
    section = [category for category in categories if category.kind == kind]
    section.insert(new_index, section.pop(old_index))
    positions = [i for i, category in enumerate(categories) if category.kind == kind]
    for position, category in zip(positions, section):
        categories[position] = category
