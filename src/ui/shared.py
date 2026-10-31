"""Controls shared by the savings, budget, and settings pages."""

import asyncio
from collections.abc import Callable
from decimal import Decimal

import flet as ft

import colors
from utils import parse_money, parse_signed_money

MOBILE_BREAKPOINT = 600


def is_mobile(page) -> bool:
    """Return True when the page is a phone-sized layout."""
    width = getattr(page, 'width', 0) or 0
    return bool(width and width < MOBILE_BREAKPOINT)


def dialog_width(page, default: int = 320) -> int:
    """Keep dialogs usable on phones while preserving desktop widths."""
    width = getattr(page, 'width', None)
    if not width:
        return default
    return min(default, max(220, int(width) - 48))


def show_snack(
    page: ft.Page,
    message: str,
    *,
    bgcolor=None,
    action: str | None = None,
    on_action: Callable | None = None,
    duration_ms: int = 4000,
) -> ft.SnackBar:
    """Show a snackbar that reliably dismisses and supports an action."""
    snack = ft.SnackBar(
        ft.Text(message),
        bgcolor=bgcolor,
        action=action,
        duration=duration_ms,
        show_close_icon=True,
    )

    def dismiss():
        if not snack.open:
            return
        dialogs = getattr(page, '_dialogs', None)
        if (
            dialogs is not None
            and dialogs.controls
            and dialogs.controls[-1] is not snack
        ):
            return
        page.pop_dialog()

    if on_action is not None:

        def handle_action(event):
            dismiss()
            return on_action(event)

        snack.on_action = handle_action

    page.show_dialog(snack)
    if isinstance(page, ft.Page):

        async def close_later():
            await asyncio.sleep(duration_ms / 1000 + 0.25)
            dismiss()

        page.run_task(close_later)
    return snack


def dialog_form(
    controls: list[ft.Control], *, height: int, width: int = 320
) -> ft.ListView:
    """Build a finite, scrollable form body for an AlertDialog.

    Flet 1.0.5 cannot lay out a tight Column containing TextField controls:
    the dialog stays invisible while its modal barrier blocks the app. A
    ListView gives the form a finite height and avoids that broken path.
    """
    return ft.ListView(
        controls=controls,
        width=width,
        height=height,
        spacing=10,
        padding=0,
    )


class LoadingDialog:
    """Modal progress indicator used during startup synchronization."""

    def __init__(self, page: ft.Page, message: str):
        self.page = page
        self.control = ft.AlertDialog(
            modal=True,
            content=ft.Row(
                controls=[
                    ft.ProgressRing(width=24, height=24, stroke_width=3),
                    ft.Text(message),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=20,
            ),
        )

    def open(self):
        self.page.show_dialog(self.control)


class MessageDialog:
    """Simple modal message used for startup and synchronization problems."""

    def __init__(self, page: ft.Page, title: str, message: str):
        self.page = page
        self.control = ft.AlertDialog(
            title=title,
            content=ft.Container(
                content=ft.Text(message, selectable=True),
                width=dialog_width(page, 440),
            ),
            actions=[
                ft.FilledButton(
                    'OK',
                    key='message-dialog-ok',
                    on_click=lambda e: self.page.pop_dialog(),
                )
            ],
            modal=True,
        )

    def open(self):
        self.page.show_dialog(self.control)


class ConfirmDialog:
    """Confirmation prompt for destructive actions."""

    def __init__(
        self,
        page: ft.Page,
        title: str,
        message: str,
        on_confirm: Callable[[], None],
        confirm_label: str = 'Delete',
    ):
        self.page = page

        def confirm(e):
            self.page.pop_dialog()
            on_confirm()

        self.control = ft.AlertDialog(
            title=title,
            content=ft.Container(
                content=ft.Text(message), width=dialog_width(page, 380)
            ),
            actions=[
                ft.TextButton(
                    'Cancel',
                    key='confirm-cancel-button',
                    on_click=lambda e: self.page.pop_dialog(),
                ),
                ft.FilledButton(
                    confirm_label,
                    key='confirm-action-button',
                    bgcolor=colors.RED,
                    on_click=confirm,
                ),
            ],
            modal=True,
        )

    def open(self):
        self.page.show_dialog(self.control)


class AccountBalanceDialog:
    """Shared initial-entry and edit dialog for the account balance."""

    def __init__(self, page: ft.Page, on_saved: Callable[[Decimal], None]):
        self.page = page
        self.on_saved = on_saved

    def add(
        self,
        on_complete: Callable[[], None],
        on_skip: Callable[[], None] | None = None,
    ):
        self._open(
            None,
            'Enter your current account balance',
            on_complete,
            on_skip=on_skip,
        )

    def modify(self, current_balance: Decimal, on_complete: Callable[[], None]):
        self._open(current_balance, 'Modify account balance', on_complete)

    def _open(
        self,
        initial_value: Decimal | None,
        title: str,
        on_complete: Callable[[], None],
        on_skip: Callable[[], None] | None = None,
    ):
        value = '' if initial_value is None else str(initial_value)
        balance_input = ft.TextField(
            label='Account balance ($)',
            value=value,
            keyboard_type=ft.KeyboardType.NUMBER,
            key='account-balance-input',
        )
        error = ft.Text(color=colors.RED)

        def save(e):
            try:
                balance = parse_signed_money(balance_input.value)
            except ValueError:
                error.value = 'Enter a valid account balance amount.'
                self.page.update()
                return

            self.on_saved(balance)
            self.page.pop_dialog()
            on_complete()

        def skip(e):
            self.page.pop_dialog()
            if on_skip is not None:
                on_skip()

        actions: list[ft.Control] = []
        if initial_value is not None:
            actions.append(
                ft.TextButton(
                    'Cancel',
                    key='account-balance-cancel',
                    on_click=lambda e: self.page.pop_dialog(),
                )
            )
        elif on_skip is not None:
            actions.append(
                ft.TextButton(
                    'Skip for now',
                    key='account-balance-skip',
                    on_click=skip,
                )
            )
        actions.append(
            ft.FilledButton('Done', key='account-balance-save', on_click=save)
        )

        self.control = ft.AlertDialog(
            title=title,
            content=dialog_form(
                [balance_input, error],
                height=120,
                width=dialog_width(self.page),
            ),
            actions=actions,
            modal=True,
        )
        self.page.show_dialog(self.control)


class AmountAdjustmentDialog:
    """Apply a positive addition or subtraction to an item's current balance."""

    def __init__(self, page: ft.Page):
        self.page = page

    def open(
        self,
        name: str,
        current_balance: Decimal,
        direction: int,
        on_saved: Callable[[Decimal], None],
    ):
        adding = direction > 0
        amount_input = ft.TextField(
            label='Amount ($)',
            keyboard_type=ft.KeyboardType.NUMBER,
            key='balance-adjustment-amount',
        )
        error = ft.Text(color=colors.RED)

        def save(e):
            try:
                amount = parse_money(amount_input.value)
                if not amount.is_finite() or amount <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                error.value = 'Enter a valid amount greater than zero.'
                self.page.update()
                return

            new_balance = current_balance + direction * amount
            if new_balance < 0:
                error.value = 'The amount cannot exceed the current balance.'
                self.page.update()
                return

            on_saved(new_balance)
            self.page.pop_dialog()

        action = 'Add to' if adding else 'Remove from'
        self.control = ft.AlertDialog(
            title=f'{action} {name} balance',
            content=dialog_form(
                [amount_input, error],
                height=120,
                width=dialog_width(self.page),
            ),
            actions=[
                ft.TextButton(
                    'Cancel',
                    key='balance-adjustment-cancel',
                    on_click=lambda e: self.page.pop_dialog(),
                ),
                ft.FilledButton(
                    'Apply',
                    key='balance-adjustment-save',
                    on_click=save,
                ),
            ],
            modal=True,
        )
        self.page.show_dialog(self.control)
