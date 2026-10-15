from pathlib import Path

import flet as ft

import colors
from data import load_funds_from_json, save_funds_to_json
from fund import Fund
from ui_components import PageHeader, SavingsSummary, FundCard, open_add_fund, open_modify_fund

FUNDS_FILE = Path(__file__).parent.parent / 'funds.json'


class SavingsFundsApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.funds = load_funds_from_json(str(FUNDS_FILE))
        self.summary = SavingsSummary()
        self._prompt_for_account_balance()

    def _refresh_fund_cards(self):
        self.fund_cards = [FundCard(fund) for fund in self.funds]
        for fund_card in self.fund_cards:
            fund_card.control.on_click = lambda e, fund=fund_card.fund: \
                open_modify_fund(self.page, self.funds, fund, self._refresh_page)
        self.fund_cards_column.controls = [fund_card.control for fund_card in self.fund_cards]

    def _initialize_dashboard(self):
        self.summary.refresh(self.account_balance, sum(fund.balance for fund in self.funds))
        action_buttons = \
            ft.Row([ft.OutlinedButton('Add fund', icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                      on_click=self.on_add_fund, expand=True)
                   ], spacing=12)

        self.fund_cards_column = ft.Column(spacing=12)
        self._refresh_fund_cards()

        dashboard = \
            ft.Container(content=ft.Column([self.summary.control,
                                            action_buttons,
                                            self.fund_cards_column],
                                           spacing=18),
                         width=760,
                         padding=24)

        self.page.add(ft.Row([dashboard], alignment=ft.MainAxisAlignment.CENTER,
                             vertical_alignment=ft.CrossAxisAlignment.START))

    def _initialize_page(self):
        self.page.title = 'Savings Funds'
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = colors.BACKGROUND
        self.page.theme = \
            ft.Theme(color_scheme=ft.ColorScheme(primary=colors.BLUE, surface=colors.SURFACE))
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.add(PageHeader)
        self._initialize_dashboard()

    def _refresh_page(self):
        self.summary.refresh(self.account_balance, sum(fund.balance for fund in self.funds))
        self._refresh_fund_cards()
        self.page.update()
        save_funds_to_json(self.funds, str(FUNDS_FILE))

    def on_add_fund(self, e):
        open_add_fund(e, self.page, self.funds, self._refresh_page)

    def _prompt_for_account_balance(self):
        self.account_balance_input = ft.TextField(
            label='Account balance ($)',
            value='',
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self.account_balance_error = ft.Text(color=colors.RED)

        self.account_balance_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text('Enter your current account balance'),
            content=ft.Column(
                [self.account_balance_input, self.account_balance_error],
                tight=True,
                width=320,
            ),
            actions=[
                ft.FilledButton('Done', on_click=self.on_account_balance_done)
            ],
        )

        self.page.show_dialog(self.account_balance_dialog)

    def on_account_balance_done(self, e):
        try:
            balance = float(self.account_balance_input.value)
            if balance <= 0:
                raise ValueError
        except (ValueError, TypeError):
            self.account_balance_error.value = (
                'Enter a valid account balance amount.'
            )
            self.page.update()
            return

        self.account_balance = balance
        self.page.pop_dialog()
        self._initialize_page()
