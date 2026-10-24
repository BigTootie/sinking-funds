"""Controls shared by the savings, budget, and settings pages."""

import math
from typing import Callable

import flet as ft

import colors


class LoadingDialog:
    """Modal progress indicator used during startup synchronization."""

    def __init__(self, page: ft.Page, message: str):
        self.page = page
        self.control = ft.AlertDialog(
            modal=True,
            content=ft.Row(
                controls=[ft.ProgressRing(width=24, height=24, stroke_width=3), ft.Text(message)],
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=20,
            ),
        )

    def open(self):
        self.page.show_dialog(self.control)


class AccountBalanceDialog:
    """Shared initial-entry and edit dialog for the account balance."""

    def __init__(self, page: ft.Page, on_saved: Callable[[float], None]):
        self.page = page
        self.on_saved = on_saved

    def add(self, on_complete: Callable[[], None]):
        self._open(None, 'Enter your current account balance', on_complete)

    def modify(self, current_balance: float, on_complete: Callable[[], None]):
        self._open(current_balance, 'Modify account balance', on_complete)

    def _open(self, initial_value: float | None, title: str, on_complete: Callable[[], None]):
        value = '' if initial_value is None else str(initial_value)
        balance_input = ft.TextField(
            label='Account balance ($)', value=value, keyboard_type=ft.KeyboardType.NUMBER,
            key='account-balance-input',
        )
        error = ft.Text(color=colors.RED)

        def save(e):
            try:
                balance = float(balance_input.value)
                if balance <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                error.value = 'Enter a valid account balance amount.'
                self.page.update()
                return

            self.on_saved(balance)
            self.page.pop_dialog()
            on_complete()

        actions = []
        if initial_value is not None:
            actions.append(ft.TextButton(
                'Cancel', key='account-balance-cancel', on_click=lambda e: self.page.pop_dialog()
            ))
        actions.append(ft.FilledButton('Done', key='account-balance-save', on_click=save))

        self.control = ft.AlertDialog(
            title=title,
            content=ft.Column([balance_input, error], tight=True, width=320),
            actions=actions,
            modal=True,
        )
        self.page.show_dialog(self.control)


class AmountAdjustmentDialog:
    """Apply a positive addition or subtraction to an item's current balance."""

    def __init__(self, page: ft.Page):
        self.page = page

    def open(self, name: str, current_balance: float, direction: int,
             on_saved: Callable[[float], None]):
        adding = direction > 0
        amount_input = ft.TextField(
            label='Amount ($)', keyboard_type=ft.KeyboardType.NUMBER,
            key='balance-adjustment-amount',
        )
        error = ft.Text(color=colors.RED)

        def save(e):
            try:
                amount = float(amount_input.value)
                if not math.isfinite(amount) or amount <= 0:
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
            content=ft.Column([amount_input, error], tight=True, width=320),
            actions=[
                ft.TextButton(
                    'Cancel', key='balance-adjustment-cancel',
                    on_click=lambda e: self.page.pop_dialog(),
                ),
                ft.FilledButton(
                    'Apply', key='balance-adjustment-save', on_click=save,
                ),
            ],
            modal=True,
        )
        self.page.show_dialog(self.control)
