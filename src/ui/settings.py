"""Application header and settings page controls."""

import asyncio
from typing import Callable

import flet as ft

import colors
from nextcloud import load_nextcloud_sync_data, ping_nextcloud_server, save_nextcloud_sync_data


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
                            ft.Text('Savings Funds', size=20, weight=ft.FontWeight.BOLD),
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

    def __init__(self, page: ft.Page, on_saved: Callable[[dict], None]):
        self.page = page
        self.on_saved = on_saved

    def add(self, on_complete: asyncio.Event):
        self._open({}, 'Enter nextcloud server info (optional)', on_complete=on_complete)

    def modify(self):
        self._open(load_nextcloud_sync_data() or {}, 'Modify Nextcloud config')

    def _open(self, initial: dict, title: str, on_complete: asyncio.Event | None = None):
        url_input = ft.TextField(
            label='URL', value=initial.get('base_url', ''), key='nextcloud-url-input'
        )
        username_input = ft.TextField(
            label='Username', value=initial.get('username', ''), key='nextcloud-username-input'
        )
        password_input = ft.TextField(
            label='Password',
            value=initial.get('password', ''),
            password=True,
            can_reveal_password=True,
            key='nextcloud-password-input',
        )
        data_path_input = ft.TextField(
            label='Data path', value=initial.get('data_path', ''), key='nextcloud-path-input'
        )
        error = ft.Text(color=colors.RED)

        def skip(e):
            data = {}
            save_nextcloud_sync_data(data)
            self.page.pop_dialog()
            if on_complete is not None:
                on_complete.set()

        async def save(e):
            error.value = ''
            self.page.update()
            data = {
                'base_url': (url_input.value or '').strip(),
                'username': (username_input.value or '').strip(),
                'password': password_input.value or '',
                'data_path': (data_path_input.value or '').strip(),
            }
            success, error_message = await asyncio.to_thread(ping_nextcloud_server, data)
            if not success:
                error.value = error_message
                self.page.update()
                return

            save_nextcloud_sync_data(data)
            self.page.pop_dialog()
            if on_complete is not None:
                on_complete.set()
            else:
                self.on_saved(data)

        actions = []
        if on_complete is not None:
            actions.append(ft.TextButton('Skip', key='nextcloud-skip-button', on_click=skip))
        else:
            actions.append(ft.TextButton(
                'Cancel', key='nextcloud-cancel-button', on_click=lambda e: self.page.pop_dialog()
            ))
        actions.append(ft.FilledButton(
            'Done' if on_complete is not None else 'Save',
            key='nextcloud-save-button',
            on_click=save,
        ))

        self.control = ft.AlertDialog(
            title=title,
            content=ft.Column([url_input, username_input, password_input, data_path_input, error],
                              tight=True),
            actions=actions,
            modal=True,
        )
        self.page.show_dialog(self.control)


class SettingsView:
    """Settings screen and its Nextcloud configuration entry."""

    def __init__(self, page: ft.Page, on_back: Callable, nextcloud_dialog: NextcloudConfigDialog):
        self.page = page
        self.nextcloud_dialog = nextcloud_dialog
        self.nextcloud_card = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(ft.Icons.CLOUD_OUTLINED, size=24, color=colors.BLUE),
                        bgcolor=colors.SURFACE,
                        border_radius=10,
                        padding=12,
                    ),
                    ft.Column(
                        [
                            ft.Text('Nextcloud Sync', size=15, weight=ft.FontWeight.W_600),
                            ft.Text(
                                'Configure server connection and sync settings',
                                size=12,
                                color=colors.TEXT_SECONDARY,
                            ),
                        ],
                        spacing=4,
                        expand=True,
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color=colors.TEXT_SECONDARY),
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=16,
            border=ft.Border.all(1, colors.BORDER),
            border_radius=14,
            ink=True,
            key='nextcloud-settings-card',
            on_click=self._modify_nextcloud,
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
                            ft.Text('Settings', size=24, weight=ft.FontWeight.BOLD, expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(height=8),
                    self.nextcloud_card,
                ],
                spacing=16,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

    def _modify_nextcloud(self, e):
        self.nextcloud_dialog.modify()

    def show(self):
        self.control.visible = True
        self.page.update()

    def hide(self):
        self.control.visible = False
