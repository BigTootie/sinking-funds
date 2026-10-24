"""Flet integration tests for settings and Nextcloud configuration."""

import json

import flet.testing as ftt

from ui_helpers import enter, tap, wait_for_key_count


async def test_settings_can_modify_nextcloud_configuration(flet_app: ftt.FletTestApp):
    tester = flet_app.tester
    await tester.pump_and_settle()

    await tap(tester, 'settings-button')
    await tap(tester, 'nextcloud-settings-card')

    await enter(tester, 'nextcloud-url-input', 'cloud.example.test')
    await enter(tester, 'nextcloud-username-input', 'test-user')
    await enter(tester, 'nextcloud-password-input', 'test-password')
    await enter(tester, 'nextcloud-path-input', 'Savings')
    await tap(tester, 'nextcloud-save-button')
    await wait_for_key_count(tester, 'nextcloud-save-button', 0)

    saved = json.loads(flet_app.paths['nextcloud'].read_text(encoding='utf-8'))
    assert saved == {
        'base_url': 'cloud.example.test',
        'username': 'test-user',
        'password': 'test-password',
        'data_path': 'Savings',
    }
    assert flet_app.app_state['app'].nextcloud_sync_data == saved

    await tap(tester, 'settings-back-button')
    await wait_for_key_count(tester, 'add-fund-button', 1)
