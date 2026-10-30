"""Application header and settings page controls."""

import asyncio
import inspect
from collections.abc import Callable

import flet as ft

import colors
from data import DataFileError
from nextcloud import (
    load_nextcloud_sync_data,
    normalize_base_url,
    ping_nextcloud_server,
    save_nextcloud_sync_data,
)
from ui.shared import ConfirmDialog, MessageDialog, dialog_form


class SettingsButton:
    """Settings entry point used by the application header."""

    def __init__(self, on_click: Callable):
        self.control = ft.IconButton(
            icon=ft.Icons.SETTINGS_OUTLINED,
            tooltip='Settings',
            key='settings-button',
            icon_color=colors.TEXT_SECONDARY,
            on_click=lambda e: on_click(),
        )


class AppHeader:
    """Top-level application branding and settings button."""

    def __init__(self, on_settings: Callable):
        self.settings_button = SettingsButton(on_settings)
        self.control = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, size=23),
                        bgcolor=colors.BLUE,
                        border_radius=12,
                        padding=10,
                    ),
                    ft.Column(
                        [
                            ft.Text(
                                'Savings Funds', size=20, weight=ft.FontWeight.BOLD
                            ),
                            ft.Text('Give every dollar a purpose.', size=12),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    self.settings_button.control,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=20,
            border=ft.Border.only(bottom=ft.BorderSide(1, colors.BORDER)),
        )


class NextcloudConfigDialog:
    """Add or edit the saved Nextcloud connection using one shared form."""

    def __init__(
        self,
        page: ft.Page,
        on_saved: Callable[[dict], None],
        *,
        load_settings: Callable[[], dict | None] | None = None,
        save_settings: Callable[[dict | None], bool] | None = None,
    ):
        self.page = page
        self.on_saved = on_saved
        self.load_settings = load_settings or load_nextcloud_sync_data
        self.save_settings = save_settings or save_nextcloud_sync_data

    def add(self, on_complete: asyncio.Event):
        self._open(
            {}, 'Enter nextcloud server info (optional)', on_complete=on_complete
        )

    def modify(self):
        try:
            initial = self.load_settings() or {}
        except (DataFileError, OSError) as exc:
            MessageDialog(self.page, 'Nextcloud settings', str(exc)).open()
            initial = {}
        self._open(initial, 'Modify Nextcloud config')

    def _persist(self, document: dict | None, error: ft.Text) -> bool:
        try:
            self.save_settings(document)
        except OSError as exc:
            error.value = f'Could not save Nextcloud settings: {exc}'
            self.page.update()
            return False
        return True

    def _open(
        self, initial: dict, title: str, on_complete: asyncio.Event | None = None
    ):
        url_input = ft.TextField(
            label='URL', value=initial.get('base_url', ''), key='nextcloud-url-input'
        )
        username_input = ft.TextField(
            label='Username',
            value=initial.get('username', ''),
            key='nextcloud-username-input',
        )
        password_input = ft.TextField(
            label='Password',
            value=initial.get('password', ''),
            password=True,
            can_reveal_password=True,
            key='nextcloud-password-input',
        )
        data_path_input = ft.TextField(
            label='Data path',
            value=initial.get('data_path', ''),
            key='nextcloud-path-input',
        )
        error = ft.Text(color=colors.RED)

        def skip(e):
            if self._persist(None, error):
                self.page.pop_dialog()
                if on_complete is not None:
                    on_complete.set()

        async def save(e):
            error.value = ''
            self.page.update()
            try:
                base_url = normalize_base_url(url_input.value or '')
            except ValueError as exc:
                error.value = str(exc)
                self.page.update()
                return

            data_path = (data_path_input.value or '').strip()
            if not data_path:
                error.value = 'Enter the folder path on Nextcloud.'
                self.page.update()
                return

            data = {
                'base_url': base_url,
                'username': (username_input.value or '').strip(),
                'password': password_input.value or '',
                'data_path': data_path,
            }
            success, error_message = await asyncio.to_thread(
                ping_nextcloud_server, data
            )
            if not success:
                error.value = error_message
                self.page.update()
                return

            if not self._persist(data, error):
                return
            self.page.pop_dialog()
            if on_complete is not None:
                on_complete.set()
            else:
                self.on_saved(data)

        actions: list[ft.Control] = []
        if on_complete is not None:
            actions.append(
                ft.TextButton('Skip', key='nextcloud-skip-button', on_click=skip)
            )
        else:
            actions.append(
                ft.TextButton(
                    'Cancel',
                    key='nextcloud-cancel-button',
                    on_click=lambda e: self.page.pop_dialog(),
                )
            )
        actions.append(
            ft.FilledButton(
                'Done' if on_complete is not None else 'Save',
                key='nextcloud-save-button',
                on_click=save,
            )
        )

        self.control = ft.AlertDialog(
            title=title,
            content=dialog_form(
                [url_input, username_input, password_input, data_path_input, error],
                height=320,
            ),
            actions=actions,
            on_dismiss=(
                (lambda e: on_complete.set()) if on_complete is not None else None
            ),
            modal=True,
        )
        self.page.show_dialog(self.control)


class SettingsView:
    """Settings screen and its Nextcloud configuration entry."""

    def __init__(
        self,
        page: ft.Page,
        on_back: Callable,
        nextcloud_dialog: NextcloudConfigDialog,
        on_disable_sync: Callable[[], None] | None = None,
        on_manual_sync: Callable[[], None] | None = None,
        on_backup: Callable[[], None] | None = None,
        on_export: Callable[[], None] | None = None,
        on_restore: Callable[[], None] | None = None,
        on_open_data_folder: Callable[[], None] | None = None,
        theme_mode: str = 'dark',
        on_theme_change: Callable[[str], None] | None = None,
    ):
        self.page = page
        self.nextcloud_dialog = nextcloud_dialog
        self.on_disable_sync = on_disable_sync
        self.on_manual_sync = on_manual_sync
        self.on_backup = on_backup
        self.on_export = on_export
        self.on_restore = on_restore
        self.on_open_data_folder = on_open_data_folder
        self.on_theme_change = on_theme_change
        self.theme_switch = ft.Switch(
            label='Light mode',
            value=theme_mode == 'light',
            key='theme-mode-switch',
            on_change=lambda e: (
                self.on_theme_change('light' if e.control.value else 'dark')
                if self.on_theme_change
                else None
            ),
        )
        self.appearance_card = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.PALETTE_OUTLINED, color=colors.BLUE),
                    ft.Column(
                        [
                            ft.Text(
                                'Appearance',
                                size=15,
                                weight=ft.FontWeight.W_600,
                            ),
                            ft.Text(
                                'Choose a light or dark blue theme.',
                                size=12,
                                color=colors.TEXT_SECONDARY,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    self.theme_switch,
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=16,
            border=ft.Border.all(1, colors.BORDER),
            border_radius=14,
            key='appearance-settings-card',
        )
        self.manual_sync_button = ft.TextButton(
            'Sync now',
            icon=ft.Icons.SYNC,
            key='manual-sync-button',
            on_click=self._run_manual_sync,
        )
        self.disable_sync_button = ft.TextButton(
            'Disable',
            icon=ft.Icons.CLOUD_OFF_OUTLINED,
            key='disable-nextcloud-button',
            on_click=self._confirm_disable_sync,
        )
        nextcloud_actions: list[ft.Control] = []
        if self.on_manual_sync is not None:
            nextcloud_actions.append(self.manual_sync_button)
        if self.on_disable_sync is not None:
            nextcloud_actions.append(self.disable_sync_button)
        self.nextcloud_card = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Container(
                                    content=ft.Icon(
                                        ft.Icons.CLOUD_OUTLINED,
                                        size=22,
                                        color=colors.BLUE,
                                    ),
                                    bgcolor=colors.SURFACE,
                                    border_radius=10,
                                    padding=11,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(
                                            'Nextcloud Sync',
                                            size=15,
                                            weight=ft.FontWeight.W_600,
                                        ),
                                        ft.Text(
                                            'Manage the server connection and synchronization.',
                                            size=12,
                                            color=colors.TEXT_SECONDARY,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                            ],
                            spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        expand=True,
                        ink=True,
                        key='nextcloud-settings-card',
                        on_click=self._modify_nextcloud,
                    ),
                    *nextcloud_actions,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=16,
            border=ft.Border.all(1, colors.BORDER),
            border_radius=14,
        )
        self.backup_button = ft.FilledButton(
            'Back up now',
            icon=ft.Icons.ARCHIVE_OUTLINED,
            key='backup-data-button',
            on_click=lambda e: self.on_backup() if self.on_backup else None,
        )
        self.export_item = ft.PopupMenuItem(
            content=ft.Text('Export data'),
            icon=ft.Icons.DOWNLOAD_OUTLINED,
            key='export-data-button',
            on_click=lambda e: self.on_export() if self.on_export else None,
        )
        self.restore_item = ft.PopupMenuItem(
            content=ft.Text('Restore latest backup'),
            icon=ft.Icons.RESTORE,
            key='restore-data-button',
            on_click=lambda e: self.on_restore() if self.on_restore else None,
        )
        self.open_folder_item = ft.PopupMenuItem(
            content=ft.Text('Open data folder'),
            icon=ft.Icons.FOLDER_OPEN_OUTLINED,
            key='open-data-folder-button',
            on_click=lambda e: (
                self.on_open_data_folder() if self.on_open_data_folder else None
            ),
        )
        self.data_card = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(
                            ft.Icons.SAVE_OUTLINED, size=22, color=colors.BLUE
                        ),
                        bgcolor=colors.SURFACE,
                        border_radius=10,
                        padding=11,
                    ),
                    ft.Column(
                        [
                            ft.Text(
                                'Data',
                                size=15,
                                weight=ft.FontWeight.W_600,
                            ),
                            ft.Text(
                                'Back up or move your local database.',
                                size=12,
                                color=colors.TEXT_SECONDARY,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    self.backup_button,
                    ft.PopupMenuButton(
                        icon=ft.Icons.MORE_HORIZ,
                        tooltip='More data actions',
                        items=[
                            self.export_item,
                            self.restore_item,
                            self.open_folder_item,
                        ],
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=16,
            border=ft.Border.all(1, colors.BORDER),
            border_radius=14,
            key='data-settings-card',
        )
        self.control = ft.Container(
            visible=False,
            padding=24,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.IconButton(
                                icon=ft.Icons.ARROW_BACK,
                                tooltip='Back to dashboard',
                                key='settings-back-button',
                                on_click=lambda e: on_back(),
                            ),
                            ft.Text(
                                'Settings',
                                size=24,
                                weight=ft.FontWeight.BOLD,
                                expand=True,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(height=8),
                    self.appearance_card,
                    self.nextcloud_card,
                    self.data_card,
                ],
                spacing=16,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

    def _modify_nextcloud(self, e):
        self.nextcloud_dialog.modify()

    async def _run_manual_sync(self, _event):
        if self.on_manual_sync is None:
            return
        result = self.on_manual_sync()
        if inspect.isawaitable(result):
            await result

    def _confirm_disable_sync(self, e):
        if self.on_disable_sync is None:
            return

        ConfirmDialog(
            self.page,
            'Disable Nextcloud sync?',
            'Local data will stay on this device. Changes will no longer be uploaded.',
            self.on_disable_sync,
            confirm_label='Disable',
        ).open()

    def show(self):
        self.control.visible = True
        self.page.update()

    def hide(self):
        self.control.visible = False
