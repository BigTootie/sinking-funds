import flet as ft

import colors
from utils import money_format
from fund import Fund


def prompt_for_account_balance(set_account_balance, PAGE, initialize_page):
    account_balance_input = ft.TextField(label='Account balance ($)', value='',
                                         keyboard_type=ft.KeyboardType.NUMBER)
    account_balance_error = ft.Text(color=colors.RED)

    def save_account_balance(e):
        try:
            balance = float(account_balance_input.value)
            if balance <= 0:
                raise ValueError
        except (ValueError, TypeError):
            account_balance_error.value = 'Enter a valid account balance amount.'
            PAGE.update()
            return

        set_account_balance(balance)
        PAGE.pop_dialog()
        initialize_page()

    AccountBalanceInputDialogue = \
        ft.AlertDialog(modal=True, title=ft.Text('Enter your current account balance'),
                       content=ft.Column([account_balance_input, account_balance_error],
                                         tight=True, width=320),
                       actions=[ft.FilledButton('Done', on_click=save_account_balance)])

    PAGE.show_dialog(AccountBalanceInputDialogue)


PageHeader = ft.Container(
    content=ft.Row(
        [
            ft.Container(content=ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, size=23),
                         bgcolor=colors.BLUE, border_radius=12, padding=10),
            ft.Column(
                [
                    ft.Text('Savings Funds', size=20, weight=ft.FontWeight.BOLD),
                    ft.Text('Give every dollar a purpose.', size=12),
                ],
                spacing=2,
                expand=True,
            ),
            ft.IconButton(icon=ft.Icons.SETTINGS_OUTLINED, tooltip='Settings',
                          icon_color=colors.TEXT_SECONDARY),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    ),
    padding=20,
    border=ft.Border.only(bottom=ft.BorderSide(1, colors.BORDER)))


class SavingsSummary:
    def __init__(self):
        self.total_savings_text = ft.Text(size=32, weight=ft.FontWeight.BOLD)
        self.total_allocated_text = ft.Text(size=13, color=colors.TEXT_SECONDARY)
        self.total_unallocated_text = ft.Text(size=12, color=colors.TEXT_SECONDARY)
        self.progress_bar = ft.ProgressBar(value=0, color=colors.BLUE, bgcolor=colors.BORDER,
                                           height=8, border_radius=10)
        self.control = \
            ft.Container(content=ft.Column([
                ft.Row([ft.Column([ft.Text('TOTAL SAVINGS', size=11, weight=ft.FontWeight.BOLD),
                                   self.total_savings_text], spacing=6, expand=True),
                        ft.Container(content=ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED,
                                                     size=26),
                                     border_radius=14, padding=14)
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self.total_allocated_text,
                self.progress_bar,
                self.total_unallocated_text], spacing=12, expand=True),
            border=ft.Border.all(1, colors.BORDER), border_radius=18, padding=22)

    def refresh(self, total_savings: float, total_allocated: float) -> None:
        self.total_savings_text.value = money_format(total_savings)
        self.total_allocated_text.value = \
            f'{money_format(total_allocated)} allocated of {self.total_savings_text.value}'
        self.total_unallocated_text.value = \
            f'{money_format(total_savings - total_allocated)} unallocated'
        self.progress_bar.value = \
            min(total_allocated / total_savings, 1) if total_savings > 0 else 0


class FundCard:
    def __init__(self, fund: Fund):
        self.fund = fund
        self.icon_box = ft.Container(content=ft.Icon(ft.Icons.SHIELD, size=24),
                                     bgcolor=colors.SURFACE, border_radius=12, padding=11)
        self.name_text = ft.Text(size=15, weight=ft.FontWeight.W_600, expand=True)
        self.target_text = ft.Text(size=12, expand=True)
        self.progress_bar = ft.ProgressBar(height=6, border_radius=10, color=colors.BLUE,
                                           bgcolor=colors.BORDER, expand=True)
        self.balance_text = ft.Text(size=16, weight=ft.FontWeight.BOLD, expand=True)
        self.funded_text = ft.Text(size=12, expand=True)
        self.control = ft.Container(
            content=ft.Column(
                [ft.Row([self.icon_box,
                         ft.Column([self.name_text, self.target_text], spacing=4, expand=True),
                         ft.Column([self.balance_text, self.funded_text], spacing=4,
                                   horizontal_alignment=ft.CrossAxisAlignment.END, expand=True)
                         ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                 self.progress_bar,
                ], spacing=14, expand=True),
            border=ft.Border.all(1, colors.BORDER), border_radius=16, padding=16,
            expand=True)

        self.refresh()

    def refresh(self) -> None:
        self.name_text.value = self.fund.name
        self.target_text.value = \
            f'Target {money_format(self.fund.target)}' if self.fund.target > 0 else 'No target set'
        self.balance_text.value = money_format(self.fund.balance)
        self.funded_text.value = \
            f'{self.fund.percent_funded:.1f}% funded' if self.fund.target > 0 else 'No target'
        self.progress_bar.value = min(max(self.fund.percent_funded / 100, 0), 1)


def open_add_fund(e, PAGE, FUNDS, refresh_page):
    name_input = ft.TextField(label='Fund name')
    target_input = ft.TextField(label='Savings target ($)', value='',
                                keyboard_type=ft.KeyboardType.NUMBER)
    initial_balance_input = ft.TextField(label='Initial balance ($)', value='',
                                         keyboard_type=ft.KeyboardType.NUMBER)
    error = ft.Text(color=colors.RED)

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text('Add a fund'),
        content=ft.Column([name_input, target_input, initial_balance_input, error],
                          tight=True, width=320),
    )

    def save_fund(e):
        name = (name_input.value or '').strip()
        if not name:
            error.value = 'Enter a fund name.'
            PAGE.update()
            return

        try:
            target = float(target_input.value or '-1')
            if target < 0:
                raise ValueError
        except ValueError:
            error.value = 'Enter a valid target amount.'
            PAGE.update()
            return

        try:
            initial_balance = float(initial_balance_input.value or '0')
        except ValueError:
            error.value = 'Enter a valid initial balance amount.'
            PAGE.update()
            return

        FUNDS.append(Fund(name, target, initial_balance))
        PAGE.pop_dialog()
        refresh_page()

    dialog.actions = [
        ft.TextButton('Cancel', on_click=lambda e: PAGE.pop_dialog()),
        ft.FilledButton('Add fund', on_click=save_fund),
    ]

    PAGE.show_dialog(dialog)


def open_modify_fund(PAGE, FUNDS, fund, refresh_page):
    name_input = ft.TextField(label='Fund name', value=fund.name)
    target_input = ft.TextField(label='Savings target ($)', value=fund.target,
                                keyboard_type=ft.KeyboardType.NUMBER)
    balance_input = ft.TextField(label='Balance ($)', value=fund.balance,
                                 keyboard_type=ft.KeyboardType.NUMBER)
    error = ft.Text(color=colors.RED)

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text('Modify fund'),
        content=ft.Column([name_input, target_input, balance_input, error],
                          tight=True, width=320),
    )

    def delete_fund(e):
        FUNDS.remove(fund)
        PAGE.pop_dialog()
        refresh_page()

    def save_fund(e):
        name = (name_input.value or '').strip()
        if not name:
            error.value = 'Enter a fund name.'
            PAGE.update()
            return

        try:
            target = float(target_input.value or '-1')
            if target < 0:
                raise ValueError
        except ValueError:
            error.value = 'Enter a valid target amount.'
            PAGE.update()
            return

        try:
            balance = float(balance_input.value or '0')
        except ValueError:
            error.value = 'Enter a valid initial balance amount.'
            PAGE.update()
            return

        fund.name = name
        fund.set_target(target)
        fund.set_balance(balance)
        PAGE.pop_dialog()
        refresh_page()

    dialog.actions = [
        ft.FilledButton('Delete', bgcolor=colors.RED, on_click=delete_fund),
        ft.TextButton('Cancel', on_click=lambda e: PAGE.pop_dialog()),
        ft.FilledButton('Save', on_click=save_fund),
    ]

    PAGE.show_dialog(dialog)
