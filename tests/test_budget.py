from budget import BudgetCategory


def test_budget_category_calculates_remaining_and_progress():
    category = BudgetCategory('Groceries', 1200, 350)

    assert category.remaining == 850
    assert category.percent_spent == 350 / 1200

    category.spent = 1300
    assert category.remaining == -100
    assert category.percent_spent > 1


def test_zero_budget_category_has_safe_progress_value():
    category = BudgetCategory('Unplanned', 0, 25)

    assert category.remaining == -25
    assert category.percent_spent == 0
