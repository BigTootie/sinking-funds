from pathlib import Path

import flet as ft

import colors
from data import load_funds_from_json, save_funds_to_json
from fund import Fund
from ui_components import (prompt_for_account_balance, PageHeader, SavingsSummary, FundCard,
                           open_add_fund, open_modify_fund)

FUNDS_FILE = Path(__file__).parent.parent / 'funds.json'


class SavingsFundsApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.funds = load_funds_from_json(str(FUNDS_FILE))
        self.summary = SavingsSummary()
        prompt_for_account_balance(self.set_account_balance, self.page, self.initialize_page)

    def set_account_balance(self, value):
        self.account_balance = value

    def _refresh_fund_cards(self):
        self.fund_cards = [FundCard(fund) for fund in self.funds]
        for fund_card in self.fund_cards:
            fund_card.control.on_click = lambda e, fund=fund_card.fund: \
                open_modify_fund(self.page, self.funds, fund, self.refresh_page)
        self.fund_cards_column.controls = [fund_card.control for fund_card in self.fund_cards]

    def _initialize_dashboard(self):
        self.summary.refresh(self.account_balance, sum(fund.balance for fund in self.funds))
        action_buttons = \
            ft.Row([ft.OutlinedButton('Add fund', icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                      on_click=lambda e: open_add_fund(e, self.page, self.funds,
                                                                       self.refresh_page),
                                      expand=True)
                   ], spacing=12)

        self.fund_cards_column = ft.Column(spacing=12)
        self._refresh_fund_cards()

        self.dashboard = \
            ft.Container(content=ft.Column([self.summary.control,
                                            action_buttons,
                                            self.fund_cards_column],
                                           spacing=18,
                                           horizontal_alignment=ft.CrossAxisAlignment.STRETCH))
        self._set_dashboard_width_and_padding()

        self.page.add(ft.Row([self.dashboard], alignment=ft.MainAxisAlignment.CENTER,
                             vertical_alignment=ft.CrossAxisAlignment.START, expand=True))

    def initialize_page(self):
        self.page.title = 'Savings Funds'
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = colors.BACKGROUND
        self.page.theme = \
            ft.Theme(color_scheme=ft.ColorScheme(primary=colors.BLUE, surface=colors.SURFACE))
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.on_resized = lambda e: self._set_dashboard_width_and_padding()
        self.page.add(PageHeader)
        self._initialize_dashboard()

    def refresh_page(self):
        self.summary.refresh(self.account_balance, sum(fund.balance for fund in self.funds))
        self._refresh_fund_cards()
        self.page.update()
        save_funds_to_json(self.funds, str(FUNDS_FILE))

    def _set_dashboard_width_and_padding(self):
        screen_width = self.page.width
        is_mobile = screen_width < 600
        margin = 12 if is_mobile else 24

        self.dashboard.width = min(760, max(screen_width - 2 * margin, 0))
        self.dashboard.padding = margin

        self.page.update()
