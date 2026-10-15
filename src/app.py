from pathlib import Path

import flet as ft

import colors
from data import (load_balance_from_txt, save_balance_to_txt,
                  load_funds_from_json, save_funds_to_json)
from ui_components import (PageHeader, SavingsSummary, FundCard,
                           prompt_for_account_balance, open_modify_account_balance,
                           open_add_fund, open_modify_fund)

ACCOUNT_BALANCE_FILE = Path(__file__).parent.parent / 'balance.txt'
FUNDS_FILE = Path(__file__).parent.parent / 'funds.json'


class SavingsFundsApp:
    """
    This class handles high-level setup and state management of the saving funds app
    """
    def __init__(self, page: ft.Page):
        # Initialize the page
        self.page = page
        self._initialize_page()

        # Load the previously stored funds
        self.funds = load_funds_from_json(str(FUNDS_FILE))

        # Prompt the user to input their total account balance if we don't already have one
        self.account_balance = load_balance_from_txt(ACCOUNT_BALANCE_FILE)
        if self.account_balance < 0:
            prompt_for_account_balance(self.set_account_balance, self.page,
                                       self.initialize_dashboard)
        # Otherwise, go ahead and initialize the dashboard
        else:
            self.initialize_dashboard()

    # Initialization for the entire page
    def _initialize_page(self):
        # Set page title and color scheme
        self.page.title = 'Savings Funds'
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = colors.BACKGROUND
        self.page.theme = \
            ft.Theme(color_scheme=ft.ColorScheme(primary=colors.BLUE, surface=colors.SURFACE))
        self.page.scroll = ft.ScrollMode.AUTO

        # Adjust sizes of items when the page is resized
        self.page.on_resized = lambda e: self._set_dashboard_width_and_padding()

        # Add the header and setup the dashboard
        self.page.add(PageHeader)

    # Setter for account balance
    def set_account_balance(self, value):
        self.account_balance = value

        # Save off the new account balance anytime it is updated
        save_balance_to_txt(self.account_balance, ACCOUNT_BALANCE_FILE)

    # Refresh routine for the fund cards section
    def _refresh_fund_cards(self):
        # Regenerate a FundCard for each Fund object
        self.fund_cards = [FundCard(fund) for fund in self.funds]
        # Set the action to open the fund modifier dialogue when a fund card is clicked on
        for fund_card in self.fund_cards:
            fund_card.control.on_click = lambda e, fund=fund_card.fund: \
                open_modify_fund(self.page, self.funds, fund, self.refresh_page)

        # Update the content of the fund cards column
        self.fund_cards_column.controls = [fund_card.control for fund_card in self.fund_cards]

    # Initialization for the dashboard section
    def initialize_dashboard(self):
        # Initialize the savings summary section
        self.summary = SavingsSummary()
        self.summary.refresh(self.account_balance, sum(fund.balance for fund in self.funds))
        self.summary.control.on_click = lambda e: \
            open_modify_account_balance(self.set_account_balance, self.page, self.refresh_page)

        # Create the "Add fund" button
        action_buttons = \
            ft.Row([ft.OutlinedButton('Add fund', icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                      on_click=lambda e: open_add_fund(e, self.page, self.funds,
                                                                       self.refresh_page),
                                      expand=True)
                   ], spacing=12)

        # Initialize the fund cards section
        self.fund_cards_column = ft.Column(spacing=12)
        self._refresh_fund_cards()

        # Create the dashboard Container object
        self.dashboard = \
            ft.Container(content=ft.Column([self.summary.control,
                                            action_buttons,
                                            self.fund_cards_column],
                                           spacing=18,
                                           horizontal_alignment=ft.CrossAxisAlignment.STRETCH))
        self._set_dashboard_width_and_padding()

        # Add the dashboard to the page
        self.page.add(ft.Row([self.dashboard], alignment=ft.MainAxisAlignment.CENTER,
                             vertical_alignment=ft.CrossAxisAlignment.START, expand=True))

    # Refresher for all dynamic page elements
    def refresh_page(self):
        self.summary.refresh(self.account_balance, sum(fund.balance for fund in self.funds))
        self._refresh_fund_cards()
        self.page.update()

        # Save the current Fund objects each time the page is refreshed
        save_funds_to_json(self.funds, str(FUNDS_FILE))

    # Special handling for differenct screen sizes
    def _set_dashboard_width_and_padding(self):
        screen_width = self.page.width
        is_mobile = screen_width < 600
        margin = 12 if is_mobile else 24

        self.dashboard.width = min(760, max(screen_width - 2 * margin, 0))
        self.dashboard.padding = margin

        self.page.update()
