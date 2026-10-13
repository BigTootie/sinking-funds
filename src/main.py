import flet as ft

import colors
from fund import Fund
from data import load_funds_from_json
from ui_components import (BASIC_PROGRESS_BAR, PAGE_HEADER, TOTAL_SAVINGS_SUMMARY, refresh_summary,
                           create_fund_card)

# TODO: Eliminate this
FUNDS_FILE = 'funds.json'
ACCOUNT_BALANCE = 25000

PRIMARY_COLOR_SCHEME = ft.ColorScheme(primary=colors.BLUE, surface=colors.SURFACE)


def main(PAGE: ft.Page):

    funds = load_funds_from_json(FUNDS_FILE)

    PAGE.title = 'Savings Funds'
    PAGE.theme_mode = ft.ThemeMode.DARK
    PAGE.bgcolor = colors.BACKGROUND
    PAGE.theme = ft.Theme(color_scheme=PRIMARY_COLOR_SCHEME)
    PAGE.scroll = ft.ScrollMode.AUTO

    # ---------- Dashboard components ----------


    FUND_CARDS = ft.Column(spacing=12)

    def refresh_page():
        allocated = sum(b.balance for b in funds)
        refresh_summary(ACCOUNT_BALANCE, allocated)

        BASIC_PROGRESS_BAR.value = \
            min(allocated / ACCOUNT_BALANCE, 1) if ACCOUNT_BALANCE > 0 else 0

        FUND_CARDS.controls = [create_fund_card(b) for b in funds]
        PAGE.update()

    # ---------- Dialog helpers ----------

    def close_dialog(dialog):
        PAGE.pop_dialog()

    def open_add_fund(e):
        name_input = ft.TextField(label='Fund name')
        target_input = ft.TextField(label='Savings target ($)', value='0',
                                    keyboard_type=ft.KeyboardType.NUMBER)
        error = ft.Text(color=colors.RED)

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
                PAGE.update()
                return

            if not name:
                error.value = 'Enter a fund name.'
                PAGE.update()
                return

            funds.append(Fund(name, target, 0.0))

            close_dialog(dialog)
            refresh_page()

        dialog.actions = [
            ft.TextButton('Cancel', on_click=lambda e: close_dialog(dialog)),
            ft.FilledButton('Add fund', on_click=save_fund),
        ]

        PAGE.show_dialog(dialog)



    ACTION_BUTTONS = ft.Row([ft.OutlinedButton('Add fund', icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                               on_click=open_add_fund, expand=True),
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
