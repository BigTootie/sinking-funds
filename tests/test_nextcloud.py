"""Tests for local Nextcloud settings and connectivity checks."""

from types import SimpleNamespace

import pytest

import nextcloud
from ledger import Ledger

SYNC_DATA = {
    'base_url': 'cloud.example.test',
    'username': 'test user',
    'password': 'test-password',
    'data_path': 'Savings Funds',
}


def test_webdav_url_encodes_path_components():
    url = nextcloud.get_file_url(SYNC_DATA, 'sync-v1/devices/a/ops.jsonl')

    assert url == (
        'https://cloud.example.test/remote.php/dav/files/test%20user/'
        'Savings%20Funds/sync-v1/devices/a/ops.jsonl'
    )


def test_base_url_accepts_a_full_https_url_and_rejects_paths():
    assert (
        nextcloud.normalize_base_url('https://cloud.example.test/')
        == 'cloud.example.test'
    )
    assert nextcloud.normalize_base_url('cloud.example.test') == 'cloud.example.test'

    with pytest.raises(ValueError):
        nextcloud.normalize_base_url('https://cloud.example.test/remote.php')
    with pytest.raises(ValueError):
        nextcloud.normalize_base_url('')


def test_ping_accepts_success_and_reports_invalid_credentials(monkeypatch):
    monkeypatch.setattr(
        nextcloud.requests,
        'head',
        lambda *args, **kwargs: SimpleNamespace(status_code=207),
    )
    assert nextcloud.ping_nextcloud_server(SYNC_DATA) == (True, '')

    monkeypatch.setattr(
        nextcloud.requests,
        'head',
        lambda *args, **kwargs: SimpleNamespace(status_code=401),
    )
    assert nextcloud.ping_nextcloud_server(SYNC_DATA) == (False, 'Invalid credentials')


def test_settings_are_stored_in_the_local_database(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.db')

    assert nextcloud.save_nextcloud_sync_data_to_db(SYNC_DATA, ledger) is True
    stored = ledger.get_setting('nextcloud_config')
    assert 'cloud.example.test' in stored
    assert 'test-password' in stored

    loaded = nextcloud.load_nextcloud_sync_data_from_db(ledger)
    assert loaded == SYNC_DATA


def test_sync_key_is_stored_in_the_local_database(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.db')

    assert nextcloud.set_sync_key('encoded-key', ledger) is True
    assert nextcloud.get_sync_key(ledger) == 'encoded-key'
    assert nextcloud.delete_sync_key(ledger) is True
    assert nextcloud.get_sync_key(ledger) is None


def test_missing_saved_password_is_loaded_for_settings_editing(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.db')
    ledger.set_setting(
        'nextcloud_config',
        '{"base_url": "cloud.example.test", "username": "test", '
        '"data_path": "Savings"}',
    )

    loaded = nextcloud.load_nextcloud_sync_data_from_db(ledger)
    assert loaded is not None
    assert loaded['password'] == ''
    assert loaded['base_url'] == 'cloud.example.test'
