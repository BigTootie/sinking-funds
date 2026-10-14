import flet as ft

import colors
from fund import Fund


def _money_format(value):
    return f'${value:,.2f}'


PAGE_HEADER = ft.Container(
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


TOTAL_SAVINGS_TEXT = ft.Text(size=32, weight=ft.FontWeight.BOLD)
TOTAL_ALLOCATED_TEXT = ft.Text(size=13, color=colors.TEXT_SECONDARY)
TOTAL_UNALLOCATED_TEXT = ft.Text(size=12, color=colors.TEXT_SECONDARY)
SAVINGS_SUMMARY_PROGRESS_BAR = ft.ProgressBar(value=0, color=colors.BLUE, bgcolor=colors.BORDER,
                                              height=8, border_radius=10)
TOTAL_SAVINGS_SUMMARY = ft.Container(
    content=ft.Column(
        [
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text('TOTAL SAVINGS', size=11, weight=ft.FontWeight.BOLD),
                            TOTAL_SAVINGS_TEXT,
                        ],
                        spacing=6,
                        expand=True,
                    ),
                    ft.Container(content=ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, size=26),
                                 border_radius=14, padding=14),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            TOTAL_ALLOCATED_TEXT,
            SAVINGS_SUMMARY_PROGRESS_BAR,
            TOTAL_UNALLOCATED_TEXT,
        ],
        spacing=12,
    ),
    border=ft.Border.all(1, colors.BORDER),
    border_radius=18,
    padding=22,
)

def refresh_summary(total_savings: float, total_allocated: float):
    TOTAL_SAVINGS_TEXT.value = _money_format(total_savings)
    TOTAL_ALLOCATED_TEXT.value = \
        f'{_money_format(total_allocated)} allocated of {TOTAL_SAVINGS_TEXT.value}'
    TOTAL_UNALLOCATED_TEXT.value = f'{_money_format(total_savings - total_allocated)} unallocated'
    SAVINGS_SUMMARY_PROGRESS_BAR.value = \
        min(total_allocated / total_savings, 1) if total_savings > 0 else 0


def create_fund_card(fund: Fund, FUNDS: list[Fund], PAGE: ft.Page, refresh_page) -> ft.Container:
    icon_box = ft.Container(content=ft.Icon(ft.Icons.SHIELD, size=24), bgcolor=colors.SURFACE,
                            border_radius=12, padding=11)

    details = ft.Column([ft.Text(fund.name, size=15, weight=ft.FontWeight.W_600),
                         ft.Text(f'Target {_money_format(fund.target)}' if fund.target > 0 \
                                                                        else 'No target set',
                                 size=12)
                        ], spacing=4, expand=True)

    amounts = ft.Column([ft.Text(_money_format(fund.balance), size=16, weight=ft.FontWeight.BOLD),
                         ft.Text(f'{fund.percent_funded:.1f}% funded' if fund.target > 0 \
                                                                      else 'No target',
                                 size=12),
                        ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.END)

    return ft.Container(
        content=ft.Column(
            [ft.Row([icon_box, details, amounts], spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.ProgressBar(value=min(max(fund.percent_funded / 100, 0), 1), height=6,
                           border_radius=10, color=colors.BLUE, bgcolor=colors.BORDER),
            ], spacing=14),
        on_click=lambda e: open_modify_fund(e, PAGE, FUNDS, fund, refresh_page),
        border=ft.Border.all(1, colors.BORDER),
        border_radius=16,
        padding=16,
    )


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


def open_modify_fund(e, PAGE, FUNDS, fund, refresh_page):
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
        fund.target = target
        fund.balance = balance
        PAGE.pop_dialog()
        refresh_page()

    dialog.actions = [
        ft.FilledButton('Delete', bgcolor=colors.RED, on_click=delete_fund),
        ft.TextButton('Cancel', on_click=lambda e: PAGE.pop_dialog()),
        ft.FilledButton('Save', on_click=save_fund),
    ]

    PAGE.show_dialog(dialog)
