from decimal import Decimal
from types import SimpleNamespace

import flet as ft

from ui.shared import AccountBalanceDialog, AmountAdjustmentDialog


def test_first_run_balance_can_be_skipped_without_saving_zero():
    dialogs = []
    saved = []
    completed = []
    page = SimpleNamespace(
        show_dialog=dialogs.append,
        pop_dialog=lambda: None,
        update=lambda: None,
    )
    dialog = AccountBalanceDialog(page, saved.append)

    dialog.add(
        lambda: completed.append('done'), on_skip=lambda: completed.append('skip')
    )
    form = dialogs[0].content
    assert isinstance(form, ft.ListView)
    assert form.width == 320
    assert form.height == 120
    skip = next(
        action for action in dialogs[0].actions if action.key == 'account-balance-skip'
    )
    skip.on_click(None)

    assert saved == []
    assert completed == ['skip']


def test_balance_adjustment_dialog_uses_finite_form():
    dialogs = []
    page = SimpleNamespace(
        show_dialog=dialogs.append,
        pop_dialog=lambda: None,
        update=lambda: None,
    )

    AmountAdjustmentDialog(page).open('Car', Decimal('100'), 1, lambda _balance: None)

    form = dialogs[0].content
    assert isinstance(form, ft.ListView)
    assert form.width == 320
    assert form.height == 120
