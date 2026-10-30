"""Budget category model and simple monthly budget calculations."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from fund import Fund
from utils import parse_money, parse_signed_money


@dataclass
class BudgetGroup:
    """A named section in the monthly plan, such as Giving or Savings."""

    name: str
    kind: str = 'expense'
    group_id: str = field(default_factory=lambda: uuid4().hex)
    sort_order: int = 0

    def __post_init__(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError('Budget group name cannot be empty')
        if self.kind not in {'income', 'expense'}:
            self.kind = 'expense'


@dataclass
class BudgetCategory:
    name: str
    budgeted: Decimal
    spent: Decimal = Decimal('0.00')
    kind: str = 'expense'
    source_fund_id: str | None = None
    category_id: str = field(default_factory=lambda: uuid4().hex)
    group: str = 'General'
    group_id: str | None = None
    sort_order: int = 0

    def __post_init__(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError('Budget category name cannot be empty')
        self.budgeted = parse_money(self.budgeted)
        self.spent = parse_signed_money(self.spent)
        if self.kind not in {'income', 'expense'}:
            self.kind = 'expense'
        self.group = (self.group or 'General').strip() or 'General'

    @property
    def remaining(self) -> Decimal:
        return self.budgeted - self.spent

    @property
    def percent_spent(self) -> Decimal:
        if self.budgeted <= 0:
            return Decimal('0')
        return self.spent / self.budgeted

    def reset_spent(self) -> None:
        self.spent = Decimal('0.00')


@dataclass
class BudgetState:
    categories: list[BudgetCategory]
    period: str
    groups: list[BudgetGroup] = field(default_factory=list)

    @property
    def planned_income(self) -> Decimal:
        return sum(
            (
                category.budgeted
                for category in self.categories
                if category.kind == 'income'
            ),
            Decimal('0.00'),
        )

    @property
    def planned_expenses(self) -> Decimal:
        return sum(
            (
                category.budgeted
                for category in self.categories
                if category.kind == 'expense'
            ),
            Decimal('0.00'),
        )

    @property
    def received_income(self) -> Decimal:
        return sum(
            (
                category.spent
                for category in self.categories
                if category.kind == 'income'
            ),
            Decimal('0.00'),
        )

    @property
    def actual_spending(self) -> Decimal:
        return sum(
            (
                category.spent
                for category in self.categories
                if category.kind == 'expense'
            ),
            Decimal('0.00'),
        )

    @property
    def to_be_budgeted(self) -> Decimal:
        """Money planned as income that has not yet been assigned to expenses."""
        return self.planned_income - self.planned_expenses

    @property
    def left_to_budget(self) -> Decimal:
        """Alias used by the EveryDollar-style summary."""
        return self.to_be_budgeted

    def category(self, category_id: str) -> BudgetCategory | None:
        return next(
            (item for item in self.categories if item.category_id == category_id),
            None,
        )


def current_period(today: datetime | None = None) -> str:
    return (today or datetime.today()).strftime('%Y-%m')


def format_period(period: str) -> str:
    try:
        return datetime.strptime(period, '%Y-%m').strftime('%B %Y')
    except (TypeError, ValueError):
        return period


def sync_recurring_fund_expenses(
    categories: list[BudgetCategory], funds: list[Fund]
) -> bool:
    """Keep generated expense rows aligned with funds' recurring contributions.

    Spending is never silently discarded. If a fund is deleted or its recurring
    amount is zeroed, a generated row that already has spending stays in place
    with a zero budget so the month's history still reconciles.
    """
    eligible_funds = {fund.id: fund for fund in funds if fund.recurring_transfer != 0}
    generated: dict[str, list[BudgetCategory]] = {}
    for category in categories:
        if category.source_fund_id is not None:
            generated.setdefault(category.source_fund_id, []).append(category)
    changed = False

    for source_id, generated_categories in list(generated.items()):
        fund = eligible_funds.pop(source_id, None)
        primary = generated_categories[0]

        # A corrupt or hand-edited file can contain duplicate generated rows.
        # Merge their spending before removing the duplicates so totals survive.
        for duplicate in generated_categories[1:]:
            primary.spent += duplicate.spent
            categories.remove(duplicate)
            changed = True

        if fund is None:
            if primary.spent == 0:
                categories.remove(primary)
                changed = True
            elif primary.budgeted != 0:
                primary.budgeted = Decimal('0.00')
                changed = True
            continue

        updated_name = f'{fund.name} contribution'
        if primary.name != updated_name or primary.budgeted != fund.recurring_transfer:
            primary.name = updated_name
            primary.budgeted = fund.recurring_transfer
            changed = True

    for fund in eligible_funds.values():
        categories.append(
            BudgetCategory(
                f'{fund.name} contribution',
                fund.recurring_transfer,
                Decimal('0.00'),
                'expense',
                fund.id,
                group='Savings',
            )
        )
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
    for position, category in zip(positions, section, strict=True):
        categories[position] = category
