import asyncio

import flet as ft

import colors
from data import (ACCOUNT_BALANCE_FILE, FUNDS_FILE, load_balance_from_txt,
                  load_funds_from_json, save_balance_to_txt, save_funds_to_json)
from nextcloud import (NEXTCLOUD_DATA_FILE, load_nextcloud_sync_data,
                       sync_data_from_nextcloud, sync_data_to_nextcloud)
from ui_components import (AccountBalanceDialog, AppHeader, Dashboard, LoadingDialog,
                           NextcloudConfigDialog, SettingsView)


class SavingsFundsApp:
    """Application state, persistence, synchronization, and UI composition."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.nextcloud_sync_data = None
        self.funds = []
        self.account_balance = -1.0
        self.dashboard = None
        self._initialize_page()

    def _initialize_page(self):
        self.page.title = 'Savings Funds'
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = colors.BACKGROUND
        self.page.theme = ft.Theme(
            color_scheme=ft.ColorScheme(primary=colors.BLUE, surface=colors.SURFACE)
        )
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.on_resized = lambda e: self._resize_dashboard()

        self.nextcloud_dialog = NextcloudConfigDialog(self.page, self._on_nextcloud_config_saved)
        self.header = AppHeader(self.show_settings)
        self.settings_view = SettingsView(
            self.page, self.show_dashboard, self.nextcloud_dialog
        )

        self.page.add(
            ft.SafeArea(
                content=self.header.control,
                avoid_intrusions_bottom=False,
                avoid_intrusions_left=False,
                avoid_intrusions_right=False,
            ),
            self.settings_view.control,
        )

    async def perform_nextcloud_sync(self):
        if not NEXTCLOUD_DATA_FILE.exists():
            self.sync_dialog_closed = asyncio.Event()
            self.nextcloud_dialog.add(self.sync_dialog_closed)
            await self.sync_dialog_closed.wait()

        self.nextcloud_sync_data = load_nextcloud_sync_data()
        if self.nextcloud_sync_data:
            loading_dialog = LoadingDialog(self.page, 'Syncing with Nextcloud...')
            loading_dialog.open()
            try:
                await asyncio.to_thread(sync_data_from_nextcloud, self.nextcloud_sync_data)
            finally:
                self.page.pop_dialog()

    async def _sync_file(self, file_path, sync_data):
        try:
            await asyncio.to_thread(sync_data_to_nextcloud, file_path, sync_data)
        except Exception as exc:
            print(f'Nextcloud sync failed for {file_path}: {exc}')

    def _sync_file_in_background(self, file_path):
        self.page.run_task(self._sync_file, file_path, self.nextcloud_sync_data)

    def show_settings(self):
        if self.dashboard is not None:
            self.dashboard.control.visible = False
        self.settings_view.show()

    def show_dashboard(self):
        self.settings_view.hide()
        if self.dashboard is not None:
            self.dashboard.control.visible = True
        self.page.update()

    def _on_nextcloud_config_saved(self, sync_data):
        self.nextcloud_sync_data = sync_data
        if hasattr(self, 'settings_view'):
            self.settings_view.control.visible = True
        self.page.update()

    def load_account_balance_and_funds(self):
        self.funds = load_funds_from_json()
        self.account_balance = load_balance_from_txt()

        if self.account_balance < 0:
            dialog = AccountBalanceDialog(self.page, self.set_account_balance)
            dialog.add(self.initialize_dashboard)
        else:
            self.initialize_dashboard()

    def set_account_balance(self, value):
        self.account_balance = value
        save_balance_to_txt(self.account_balance)
        if self.nextcloud_sync_data:
            self._sync_file_in_background(ACCOUNT_BALANCE_FILE)

    def initialize_dashboard(self):
        self.dashboard = Dashboard(
            self.page,
            self.funds,
            lambda: self.account_balance,
            self.set_account_balance,
            self._on_funds_changed,
        )
        self.dashboard.control.visible = True
        self.page.add(self.dashboard.control)
        self.page.update()

    def refresh_page(self):
        if self.dashboard is not None:
            self.dashboard.refresh()
        self.page.update()

    def _on_funds_changed(self):
        save_funds_to_json(self.funds)
        if self.nextcloud_sync_data:
            self._sync_file_in_background(FUNDS_FILE)
        self.refresh_page()

    def _resize_dashboard(self):
        if self.dashboard is not None:
            self.dashboard.resize()
            self.page.update()
