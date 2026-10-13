import flet as ft

import colors
from fund import Fund
from data import load_funds_from_json
from ui_components import create_fund_card, _money_format

# TODO: Eliminate this
FUNDS_FILE = 'funds.json'
ACCOUNT_BALANCE = 25000

PRIMARY_COLOR_SCHEME = ft.ColorScheme(primary=colors.BLUE, surface=colors.SURFACE)


def main(page: ft.Page):

    funds = load_funds_from_json(FUNDS_FILE)

    page.title = 'Savings Funds'
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = colors.BACKGROUND
    page.theme = ft.Theme(color_scheme=PRIMARY_COLOR_SCHEME)
    page.scroll = ft.ScrollMode.AUTO

    # ---------- Dashboard components ----------

    total_text = ft.Text(size=32, weight=ft.FontWeight.BOLD)
    allocation_text = ft.Text(size=13, color=colors.TEXT_SECONDARY)
    unallocated_text = ft.Text(size=12, color=colors.TEXT_SECONDARY)
    allocation_progress = ft.ProgressBar(value=0, color=colors.BLUE, bgcolor=colors.BORDER,
                                         height=8, border_radius=10)

    fund_list = ft.Column(spacing=12)

    def refresh_page():
        allocated = sum(b.balance for b in funds)
        total_text.value = _money_format(ACCOUNT_BALANCE)
        allocation_text.value = (f'{_money_format(allocated)} allocated of '
                                 f'{_money_format(ACCOUNT_BALANCE)}')
        unallocated_text.value = f'{_money_format(ACCOUNT_BALANCE - allocated)} unallocated'

        allocation_progress.value = \
            min(allocated / ACCOUNT_BALANCE, 1) if ACCOUNT_BALANCE > 0 else 0

        fund_list.controls = [create_fund_card(b) for b in funds]
        page.update()

    # ---------- Dialog helpers ----------

    def close_dialog(dialog):
        page.pop_dialog()

    def open_add_fund(e):
        name_input = ft.TextField(label='Fund name')
        target_input = ft.TextField(label='Savings target ($)', value='0',
                                    keyboard_type=ft.KeyboardType.NUMBER)
        error = ft.Text(color=colors.RED, size=12)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text('Add a fund'),
            content=ft.Column([name_input, target_input, error], tight=True, width=320),
        )

        def save_fund(e):
            name = (name_input.value or '').strip()

            try:
                target = float(target_input.value or '0')
                if target < 0:
                    raise ValueError
            except ValueError:
                error.value = 'Enter a valid target amount.'
                page.update()
                return

            if not name:
                error.value = 'Enter a fund name.'
                page.update()
                return

            funds.append(Fund(name, target, 0.0))

            close_dialog(dialog)
            refresh_page()

        dialog.actions = [
            ft.TextButton('Cancel', on_click=lambda e: close_dialog(dialog)),
            ft.FilledButton('Add fund', on_click=save_fund),
        ]

        page.show_dialog(dialog)

    def open_move_money(e):
        if len(funds) < 2:
            return

        source = ft.Dropdown(label='Move money from',
                             options=[ft.dropdown.Option(b.name) for b in funds],
                             value=funds[0].name)

        destination = ft.Dropdown(label='Move money to',
                                  options=[ft.dropdown.Option(b.name) for b in funds],
                                  value=funds[1].name)

        amount = ft.TextField(label='Amount ($)', keyboard_type=ft.KeyboardType.NUMBER)
        error = ft.Text(color=colors.RED, size=12)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text('Move money'),
            content=ft.Column([source, destination, amount, error], tight=True, width=320),
        )

        def transfer(e):
            try:
                value = float(amount.value or '0')
                if value <= 0:
                    raise ValueError
            except ValueError:
                error.value = 'Enter an amount greater than zero.'
                page.update()
                return

            src = next(b for b in funds if b.name == source.value)
            dst = next(b for b in funds if b.name == destination.value)

            if src is dst:
                error.value = 'Choose two different funds.'
                page.update()
                return

            if value > src.balance:
                error.value = 'Insufficient funds in that fund.'
                page.update()
                return

            src.balance -= value
            dst.balance += value

            close_dialog(dialog)
            refresh_page()

        dialog.actions = [
            ft.TextButton('Cancel', on_click=lambda e: close_dialog(dialog)),
            ft.FilledButton('Transfer', on_click=transfer),
        ]

        page.show_dialog(dialog)

    # ---------- Header ----------

    header = ft.Container(
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
        border=ft.Border.only(bottom=ft.BorderSide(1, '#E9EDF2')),
    )

    # ---------- Savings summary ----------

    summary = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text('TOTAL SAVINGS', size=11, weight=ft.FontWeight.BOLD),
                                total_text,
                            ],
                            spacing=6,
                            expand=True,
                        ),
                        ft.Container(content=ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, size=26),
                                     border_radius=14, padding=14),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                allocation_text,
                allocation_progress,
                unallocated_text,
            ],
            spacing=12,
        ),
        border=ft.Border.all(1, '#E9EDF2'),
        border_radius=18,
        padding=22,
    )

    heading = ft.Row(
        [
            ft.Column(
                [
                    ft.Text('Your funds', size=19, weight=ft.FontWeight.BOLD),
                    ft.Text('Track progress toward what matters.', size=12),
                ],
                spacing=4,
                expand=True,
            ),
            ft.FilledButton('Add fund', icon=ft.Icons.ADD, on_click=open_add_fund),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    actions = ft.Row(
        [
            ft.OutlinedButton('Add fund', icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                              on_click=open_add_fund, expand=True),
            ft.OutlinedButton('Move money', icon=ft.Icons.SWAP_HORIZ,
                              on_click=open_move_money, expand=True),
        ],
        spacing=12,
    )

    dashboard = \
        ft.Container(
            content=ft.Column([summary,
                               heading,
                               fund_list,
                               actions,
                               ft.Text('Demo data only · Not saved after restarting', size=11,
                                       color=colors.TEXT_SECONDARY, text_align=ft.TextAlign.CENTER)
                               ], spacing=18),
            width=760,
            padding=24,
    )

    page.add(header,
             ft.Row([dashboard], alignment=ft.MainAxisAlignment.CENTER,
                    vertical_alignment=ft.CrossAxisAlignment.START),
    )

    refresh_page()


if __name__ == '__main__':
    ft.run(main)
