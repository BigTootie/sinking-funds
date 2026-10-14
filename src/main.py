from pathlib import Path

import flet as ft

import colors
from fund import Fund
from data import load_funds_from_json, save_funds_to_json
from ui_components import (PAGE_HEADER, TOTAL_SAVINGS_SUMMARY, refresh_summary,
                           create_fund_card, open_add_fund)

# TODO: Eliminate this
FUNDS_FILE = f'{Path(__file__).parent.parent}/funds.json'
FUNDS = load_funds_from_json(FUNDS_FILE)

PRIMARY_COLOR_SCHEME = ft.ColorScheme(primary=colors.BLUE, surface=colors.SURFACE)


def main(PAGE: ft.Page):

    PAGE.title = 'Savings Funds'
    PAGE.theme_mode = ft.ThemeMode.DARK
    PAGE.bgcolor = colors.BACKGROUND
    PAGE.theme = ft.Theme(color_scheme=PRIMARY_COLOR_SCHEME)
    PAGE.scroll = ft.ScrollMode.AUTO

    ACCOUNT_FUND = Fund('Total Account', max(sum(fund.balance for fund in FUNDS), 0.01))
    ACCOUNT_BALANCE_INPUT = ft.TextField(label='Account balance ($)', value='',
                                         keyboard_type=ft.KeyboardType.NUMBER)
    ACCOUNT_BALANCE_ERROR = ft.Text(color=colors.RED)
    ACCOUNT_BALANCE_INPUT_DIALOGUE = \
        ft.AlertDialog(modal=True, title=ft.Text('Enter your current account balance'),
                       content=ft.Column([ACCOUNT_BALANCE_INPUT, ACCOUNT_BALANCE_ERROR],
                                         tight=True, width=320))
    def update_account_balance(e):
        try:
            ACCOUNT_FUND.balance = float(ACCOUNT_BALANCE_INPUT.value)
            if ACCOUNT_FUND.balance <= 0:
                raise ValueError
        except ValueError:
            ACCOUNT_BALANCE_ERROR.value = 'Enter a valid account balance amount.'
            PAGE.update()
            return

        PAGE.pop_dialog()
        refresh_page()

    ACCOUNT_BALANCE_INPUT_DIALOGUE.actions = \
        [ft.FilledButton('Done', on_click=update_account_balance)]
    PAGE.show_dialog(ACCOUNT_BALANCE_INPUT_DIALOGUE)

    FUND_CARDS = ft.Column(spacing=12)

    def refresh_page():
        allocated = sum(fund.balance for fund in FUNDS)
        refresh_summary(ACCOUNT_FUND.balance, allocated)
        FUND_CARDS.controls = [create_fund_card(fund, FUNDS, PAGE, refresh_page) for fund in FUNDS]
        PAGE.update()
        save_funds_to_json(FUNDS, FUNDS_FILE)

    ACTION_BUTTONS = ft.Row([ft.OutlinedButton('Add fund', icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                               on_click=lambda e: open_add_fund(e, PAGE, FUNDS,
                                                                                refresh_page),
                                               expand=True),
                            ], spacing=12)

    DASHBOARD = \
        ft.Container(
            content=ft.Column([TOTAL_SAVINGS_SUMMARY, ACTION_BUTTONS, FUND_CARDS], spacing=18),
            width=760,
            padding=24)

    PAGE.add(PAGE_HEADER,
             ft.Row([DASHBOARD], alignment=ft.MainAxisAlignment.CENTER,
                    vertical_alignment=ft.CrossAxisAlignment.START))

    refresh_page()


if __name__ == '__main__':
    ft.run(main)
