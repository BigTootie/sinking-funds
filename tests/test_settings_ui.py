"""Headless tests for settings and Nextcloud configuration."""

import inspect
import json
from types import SimpleNamespace

import flet as ft
from ui_helpers import click, enter, find_by_key, visible_page

import ui.settings as settings_ui


def test_nextcloud_settings_write_failure_is_reported(monkeypatch):
    def fail_to_save(_document):
        raise OSError('read-only filesystem')

    monkeypatch.setattr(settings_ui, 'save_nextcloud_sync_data_to_db', fail_to_save)
    dialog = settings_ui.NextcloudConfigDialog(
        SimpleNamespace(update=lambda: None), lambda _data: None
    )
    error = ft.Text()

    assert dialog._persist(None, error) is False
    assert 'Could not save Nextcloud settings' in error.value
    assert 'read-only filesystem' in error.value


def test_nextcloud_dialog_uses_finite_form():
    dialogs = []
    page = SimpleNamespace(
        show_dialog=dialogs.append,
        pop_dialog=lambda: None,
        update=lambda: None,
    )
    dialog = settings_ui.NextcloudConfigDialog(page, lambda _data: None)

    dialog._open({}, 'Modify Nextcloud config')

    form = dialogs[0].content
    assert isinstance(form, ft.ListView)
    assert form.width == 320
    assert form.height == 470


async def test_settings_can_modify_nextcloud_configuration(headless_app):
    app = headless_app.app
    page = headless_app.page

    await click(page, 'settings-button')
    assert app.settings_view.control.visible is True
    await click(page, 'nextcloud-settings-card')

    await enter(page, 'nextcloud-url-input', 'cloud.example.test')
    await enter(page, 'nextcloud-username-input', 'test-user')
    await enter(page, 'nextcloud-password-input', 'test-password')
    await enter(page, 'nextcloud-path-input', 'Savings')
    await click(page, 'nextcloud-save-button')

    stored = json.loads(app.ledger.get_setting('nextcloud_config'))
    assert stored['base_url'] == 'cloud.example.test'
    assert stored['username'] == 'test-user'
    assert stored['data_path'] == 'Savings'
    assert 'test-password' in app.ledger.get_setting('nextcloud_config')
    assert app.nextcloud_sync_data['password'] == 'test-password'
    await click(page, 'settings-back-button')
    assert app.settings_view.control.visible is False
    assert visible_page(app, 1) is True
    find_by_key(page, 'add-fund-button')


async def test_settings_can_disable_nextcloud_sync(headless_app):
    app = headless_app.app
    page = headless_app.page

    await click(page, 'settings-button')
    await click(page, 'disable-nextcloud-button')
    await click(page, 'confirm-action-button')

    assert app.ledger.get_setting('nextcloud_config') is None
    assert app.nextcloud_sync_data is None
    await click(page, 'settings-back-button')
    assert app.settings_view.control.visible is False
    assert visible_page(app, 1) is True


def test_settings_data_buttons_invoke_backup_and_export_callbacks():
    calls = []
    page = SimpleNamespace(update=lambda: None)
    view = settings_ui.SettingsView(
        page,
        lambda: None,
        None,
        on_backup=lambda: calls.append('backup'),
        on_export=lambda: calls.append('export'),
        on_restore=lambda: calls.append('restore'),
        on_open_data_folder=lambda: calls.append('open'),
    )
    view.backup_button.on_click(None)
    view.export_item.on_click(None)
    view.restore_item.on_click(None)
    view.open_folder_item.on_click(None)

    assert calls == ['backup', 'export', 'restore', 'open']


async def test_nextcloud_card_offers_manual_sync(headless_app):
    app = headless_app.app
    page = headless_app.page
    app.nextcloud_sync_data = {
        'base_url': 'cloud.example.test',
        'username': 'test-user',
        'password': 'test-password',
        'data_path': 'Savings',
    }

    class Engine:
        def sync(self):
            from sync.engine import SyncOutcome

            return SyncOutcome(applied=1, last_sync='2026-10-30T12:00:00')

    app.sync_engine = Engine()

    await click(page, 'settings-button')
    assert inspect.iscoroutinefunction(find_by_key(page, 'manual-sync-button').on_click)
    await click(page, 'manual-sync-button')

    assert any(
        isinstance(dialog, ft.SnackBar) and 'Sync complete' in dialog.content.value
        for dialog in page.dialogs
    )


def test_nextcloud_dialog_exposes_optional_encryption_and_key_generation():
    page = SimpleNamespace(
        show_dialog=lambda control: None,
        pop_dialog=lambda: None,
        update=lambda: None,
    )
    dialog = settings_ui.NextcloudConfigDialog(page, lambda _data: None)
    dialog._open({}, 'Modify Nextcloud config')

    switch = dialog.control.content.controls[4]
    passphrase = dialog.control.content.controls[5].controls[0]
    generate = dialog.control.content.controls[5].controls[1]
    assert switch.key == 'nextcloud-encryption-switch'
    assert passphrase.visible is False
    switch.value = True
    switch.on_change(None)
    assert passphrase.visible is True
    generate.on_click(None)
    assert passphrase.value
