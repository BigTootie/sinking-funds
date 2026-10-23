import asyncio
from datetime import datetime

import flet as ft

import colors
from utils import money_format
from fund import Fund
from nextcloud import ping_nextcloud_server, save_nextcloud_sync_data


# Define the static page header
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


# Define the base nextcloud sync data input dialogue
url_input = ft.TextField(label='URL')
username_input = ft.TextField(label='Username')
password_input = ft.TextField(label='Password', password=True, can_reveal_password=True)
data_path_input = ft.TextField(label='Data path')
nextcloud_error = ft.Text(color=colors.RED)
NextcloudDataInputDialogue = \
    ft.AlertDialog(title='Enter nextcloud server info (optional)',
                   content=ft.Column([url_input, username_input, password_input, data_path_input,
                                      nextcloud_error], tight=True),
                   modal=True)


# Initial prompt when nextcloud sync data has not yet been provided
def prompt_for_nextcloud_sync(page: ft.Page, dialog_closed: asyncio.Event):

    def save_empty_nextcloud_data(e):
        save_nextcloud_sync_data({})
        page.pop_dialog()
        dialog_closed.set()

    async def save_nextcloud_data(e):
        nextcloud_error.value = ''
        page.update()

        nextcloud_sync_data = {'base_url': url_input.value, 'username': username_input.value,
                               'password': password_input.value, 'data_path': data_path_input.value}

        success, error_message = await asyncio.to_thread(ping_nextcloud_server, nextcloud_sync_data)
        if not success:
            nextcloud_error.value = error_message
            page.update()
            return

        save_nextcloud_sync_data(nextcloud_sync_data)
        page.pop_dialog()
        dialog_closed.set()

    NextcloudDataInputDialogue.actions = \
        [ft.TextButton('Skip', on_click=save_empty_nextcloud_data),
         ft.FilledButton('Done', on_click=save_nextcloud_data)]
    page.show_dialog(NextcloudDataInputDialogue)


# Loading dialogue
def show_loading_dialog(page: ft.Page, message: str):
    LoadingDialogue = ft.AlertDialog(
        modal=True,
        content=ft.Row(
            controls=[ft.ProgressRing(width=24, height=24, stroke_width=3), ft.Text(message)],
            alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=20),
    )
    page.show_dialog(LoadingDialogue)


# Define the base account balance input dialogue
account_balance_input = ft.TextField(label='Account balance ($)', value='',
                                     keyboard_type=ft.KeyboardType.NUMBER)
account_balance_error = ft.Text(color=colors.RED)
AccountBalanceInputDialogue = \
    ft.AlertDialog(content=ft.Column([account_balance_input, account_balance_error],
                                     tight=True, width=320),
                   modal=True)


# Function to save user's account balance input to the app state
def save_account_balance(set_account_balance, page):
    try:
        balance = float(account_balance_input.value)
        if balance <= 0:
            raise ValueError
    except (ValueError, TypeError):
        account_balance_error.value = 'Enter a valid account balance amount.'
        page.update()
        return False

    set_account_balance(balance)
    page.pop_dialog()
    return True


# Initial prompt when account balance has not yet been provided
def prompt_for_account_balance(set_account_balance, page, initialize_dashboard):
    def save_account_balance_and_initialize(e):
        success = save_account_balance(set_account_balance, page)
        if success:
            initialize_dashboard()

    AccountBalanceInputDialogue.title = 'Enter your current account balance'
    AccountBalanceInputDialogue.actions = \
        [ft.FilledButton('Done', on_click=save_account_balance_and_initialize)]
    page.show_dialog(AccountBalanceInputDialogue)


# Modifier for account balance
def open_modify_account_balance(set_account_balance, page, refresh_page):
    def save_account_balance_and_refresh(e):
        success = save_account_balance(set_account_balance, page)
        if success:
            refresh_page()
    AccountBalanceInputDialogue.title = 'Modify account balance'
    AccountBalanceInputDialogue.actions = \
        [ft.TextButton('Cancel', on_click=lambda e: page.pop_dialog()),
         ft.FilledButton('Done', on_click=save_account_balance_and_refresh)]

    page.show_dialog(AccountBalanceInputDialogue)


# Definition of savings summary section
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


# Definition of cards that display each fund's information
class FundCard:
    def __init__(self, fund: Fund):
        self.fund = fund
        self.icon_box = ft.Container(content=ft.Icon(ft.Icons.SHIELD, size=24),
                                     bgcolor=colors.SURFACE, border_radius=12, padding=11)
        self.name_text = ft.Text(size=15, weight=ft.FontWeight.W_600, expand=True)
        self.target_text = ft.Text(size=12, expand=True)
        self.balance_text = ft.Text(size=16, weight=ft.FontWeight.BOLD, expand=True)
        self.funded_text = ft.Text(size=12, expand=True)
        self.progress_bar = ft.ProgressBar(height=6, border_radius=10, color=colors.BLUE,
                                           bgcolor=colors.BORDER, expand=True)
        self.control = ft.Container(
            content=ft.Column(
                [ft.Row([self.icon_box,
                         ft.Column([self.name_text, self.target_text], spacing=4, expand=True),
                         ft.Column([self.balance_text, self.funded_text], spacing=4,
                                   horizontal_alignment=ft.CrossAxisAlignment.END, expand=True)
                         ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                 self.progress_bar],
                 spacing=14, expand=True, margin=ft.Margin.only(right=22)),
            border=ft.Border.all(1, colors.BORDER), border_radius=16, padding=16, expand=True,
            margin=ft.Margin.only(bottom=8))

        # Add target date information if one exists for this fund
        if self.fund.target_date is not None:
            self.target_date_text = ft.Text(size=12, expand=True)
            self.on_track_status_text = ft.Text(size=12, expand=True)
            if self.fund.on_track:
                self.on_track_status_text.color = colors.GREEN
            else:
                self.on_track_status_text.color = colors.RED

            self.control.content.controls.append(
                 ft.Row([ft.Column([self.target_date_text], spacing=4, expand=True),
                         ft.Column([self.on_track_status_text], spacing=4,
                                   horizontal_alignment=ft.CrossAxisAlignment.END, expand=True)
                         ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        # Load the values of all fields
        self.refresh()

    def refresh(self) -> None:
        self.name_text.value = self.fund.name
        self.target_text.value = \
            f'Target {money_format(self.fund.target)}' if self.fund.target > 0 else 'No target set'
        self.balance_text.value = money_format(self.fund.balance)
        self.funded_text.value = f'{self.fund.compute_percent_funded():.1f}% funded' \
                                 if self.fund.target > 0 else 'No target'
        self.progress_bar.value = min(max(self.fund.compute_percent_funded() / 100, 0), 1)
        if self.fund.target_date is not None:
            self.target_date_text.value = f'Target date: {self.fund.target_date_as_str()} ' \
                                          f'({self.fund.time_remaining_as_str()})'
            self.on_track_status_text.value = self.fund.get_on_track_status_as_str()


# Function to generate and display the "Add fund" dialogue
def open_add_fund_dialogue(page, funds, refresh_page):

    # Initialize the name, target, balance, and date input fields
    name_input = ft.TextField(label='Fund name')
    target_input = ft.TextField(label='Savings target ($)', keyboard_type=ft.KeyboardType.NUMBER)
    balance_input = ft.TextField(label='Current balance ($)', keyboard_type=ft.KeyboardType.NUMBER)
    recurring_transfer_input = ft.TextField(label='Recurring monthly transfer ($)',
                                            keyboard_type=ft.KeyboardType.NUMBER)

    # Date selector button which spawns the date picker dialogue
    def open_date_picker(e):
        page.show_dialog(date_picker)

    date_select_button = ft.Button(content='Target date: None', icon=ft.Icons.CALENDAR_MONTH,
                                   on_click=open_date_picker)

    # Define a function for the date picker to use to save the date selected
    target_date = None
    def set_date(e):
        nonlocal target_date
        target_date = e.control.value
        date_select_button.content = 'Target date: ' + target_date.strftime('%m/%d/%Y')
        page.update()

    # Setup datepicker dialogue for add/modify fund dialogues
    today = datetime.today()
    date_picker = ft.DatePicker(first_date=today, current_date=today,
                                last_date=datetime(year=today.year + 50, month=today.month, day=1),
                                on_change=set_date)

    # Error message text field
    error = ft.Text(color=colors.RED)

    # Define a function to handle saving the new fund
    def save_fund(e):
        name = (name_input.value or '').strip()
        if not name:
            error.value = 'Enter a fund name.'
            page.update()
            return

        try:
            target = float(target_input.value or '-1')
            if target < 0:
                raise ValueError
        except ValueError:
            error.value = 'Enter a valid target amount.'
            page.update()
            return

        try:
            initial_balance = float(balance_input.value or '0')
        except ValueError:
            error.value = 'Enter a valid initial balance amount.'
            page.update()
            return

        try:
            recurring_transfer = float(recurring_transfer_input.value or '0')
        except ValueError:
            error.value = 'Enter a valid recurring transfer amount.'
            page.update()
            return

        funds.insert(0, Fund(name, target, initial_balance, target_date, recurring_transfer))
        page.pop_dialog()
        refresh_page()

    # Define the "Add fund" dialogue and display it
    AddFundDialogue = \
        ft.AlertDialog(title='Add fund', modal=True,
                       content=ft.Column([name_input, target_input, balance_input,
                                          recurring_transfer_input, date_select_button, error],
                                         tight=True, width=320),
                       actions=[ft.TextButton('Cancel', on_click=lambda e: page.pop_dialog()),
                                ft.FilledButton('Save', on_click=save_fund)])

    page.show_dialog(AddFundDialogue)


# Function to generate and display the "Modify fund" dialogue
def open_modify_fund_dialogue(page, funds, fund, refresh_page):

    # Pre-fill the name, target, balance, and date input fields with the current values from
    # the fund
    name_input = ft.TextField(fund.name, label='Fund name')
    target_input = ft.TextField(fund.target, label='Savings target ($)',
                                keyboard_type=ft.KeyboardType.NUMBER)
    balance_input = ft.TextField(fund.balance, label='Current balance ($)',
                                 keyboard_type=ft.KeyboardType.NUMBER)
    recurring_transfer_input = ft.TextField(fund.recurring_transfer,
                                            label='Recurring monthly transfer ($)',
                                            keyboard_type=ft.KeyboardType.NUMBER)

    # Date selector button which spawns the date picker dialogue
    def open_date_picker(e):
        page.show_dialog(date_picker)

    date_select_button = ft.Button(content='Target date: ' + fund.target_date_as_str(),
                                   icon=ft.Icons.CALENDAR_MONTH, on_click=open_date_picker)

    # Define a function for the date picker to use to save the date selected
    new_target_date = fund.target_date
    def set_date(e):
        nonlocal new_target_date
        new_target_date = e.control.value
        date_select_button.content = 'Target date: ' + new_target_date.strftime('%m/%d/%Y')
        page.update()

    # Setup datepicker dialogue for add/modify fund dialogues
    today = datetime.today()
    date_picker = ft.DatePicker(first_date=today, current_date=today,
                                last_date=datetime(year=today.year + 50, month=today.month, day=1),
                                on_change=set_date)


    # Error message text field
    error = ft.Text(color=colors.RED)

    # Define a function to handle saving changes to the fund
    def save_fund(e):
        name = (name_input.value or '').strip()
        if not name:
            error.value = 'Enter a fund name.'
            page.update()
            return

        try:
            target = float(target_input.value or '-1')
            if target < 0:
                raise ValueError
        except ValueError:
            error.value = 'Enter a valid target amount.'
            page.update()
            return

        try:
            balance = float(balance_input.value or '0')
        except ValueError:
            error.value = 'Enter a valid initial balance amount.'
            page.update()
            return

        try:
            recurring_transfer = float(recurring_transfer_input.value or '0')
        except ValueError:
            error.value = 'Enter a valid recurring transfer amount.'
            page.update()
            return

        fund.name = name
        fund.set_target(target)
        fund.set_balance(balance)
        fund.set_target_date(new_target_date)
        fund.set_recurring_transfer(recurring_transfer)
        page.pop_dialog()
        refresh_page()

    # Define a function to handle fund deletion
    def delete_fund(e):
        funds.remove(fund)
        page.pop_dialog()
        refresh_page()

    # Define the "Modify fund" dialogue and display it
    ModifyFundDialogue = \
        ft.AlertDialog(title='Modify fund', modal=True,
                       content=ft.Column([name_input, target_input, balance_input,
                                          recurring_transfer_input, date_select_button, error],
                                         tight=True, width=320),
                       actions=[ft.FilledButton('Delete', bgcolor=colors.RED, on_click=delete_fund),
                                ft.TextButton('Cancel', on_click=lambda e: page.pop_dialog()),
                                ft.FilledButton('Save', on_click=save_fund)])

    page.show_dialog(ModifyFundDialogue)
